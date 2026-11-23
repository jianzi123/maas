"""Frozen E-LIT-01 protocol and portable validation; imports no CUDA framework."""
import argparse
import copy
import datetime
import hashlib
import json
from pathlib import Path
import re

POLICIES = ("query_block", "query_cluster", "idle_matched")
SOURCE_FILES = (
    "cadence_protocol.py", "bench_kv_cadence.py", "analyze_kv_cadence.py",
    "bench_kv_interleaved.py", "native_kv_binding.py", "run_decode.py",
)
CONFIG = {
    "primary_scope": "full",
    "primary_metric": "completed_cluster_wall_ns_per_100_planned_calls",
    "cluster_clock": "before first prepare to last block completion; includes policy/prepare, excludes boundary archival IO",
    "gap_clock": "host-observed preceding own-device completion to pre-event submission; not physical GPU idle",
    "expected_per_run": {"clusters": 54, "blocks": 540, "measured_calls": 5400,
        "calibration_queries": 20, "comparison_queries": 198, "gate_events": 13,
        "warmup_calls": 144},
    "diagnostic_scopes": ["bare_graph"],
    "batches": [3, 5, 8],
    "input_length": 12,
    "KV_context_length": 13,
    "blocks_per_cluster_total": 10,
    "NM_pairs_per_cluster": 5,
    "calls_per_block": 10,
    "calls_per_cluster": 100,
    "calls_per_variant_per_cluster": 50,
    "rounds_per_cell": 3,
    "runs": [{"id": "R01", "reverse": False}, {"id": "R02", "reverse": True}],
    "capture_first": "native",
    "warmup_calls_per_variant_per_cell": 12,
    "calibration_samples_per_variant": 10,
    "calibration_cell": {"batch": 3, "scope": "full"},
    "idle_target": "per_variant_median_calibrated_completion_to_submit_gap",
    "match_tolerance_abs_ns": 250000,
    "match_tolerance_relative": 0.05,
    "max_calibrated_target_ns": 500000000,
    "resource_caps": {"gpu": 0, "allocator_fraction": 0.20, "planner_fraction": 0.20,
                      "max_requests": 8, "KV_tokens": 512, "context_length": 128,
                      "min_free_bytes": 1073741824, "process_seconds": 600,
                      "internal_stop_seconds": 570, "default_split_cap": 8,
                      "research_lock": "/var/tmp/maas-10-gpu-01a1a5ba/gpu0-research.lock"},
    "stop_on": ["lock_busy", "resource_limit", "query_error", "numerical_error",
                "identity_error", "deadline"],
    "missing_policy": "retain all planned block identities; never retry or replace slow/missing blocks",
    "interpretation": "composite policy effects only; no isolated query/idle root-cause or model speedup",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def write_json(path, value, exclusive=False):
    with Path(path).open("x" if exclusive else "w", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def build_schedule(experiment):
    clusters = []
    for run_index, run in enumerate(CONFIG["runs"]):
        for scope in ("full", "bare_graph"):
            for batch in CONFIG["batches"]:
                for rotation in range(3):
                    order = list(POLICIES[rotation:] + POLICIES[:rotation])
                    if run["reverse"]:
                        order.reverse()
                    for position, policy in enumerate(order):
                        key = f"{experiment}/{run['id']}/{scope}/B{batch}/T{rotation}"
                        cid = key + "/" + policy
                        blocks = []
                        for pair in range(5):
                            variants = ["native", "mature"]
                            if (pair + rotation + position + run_index) % 2:
                                variants.reverse()
                            for v in variants:
                                slot = len(blocks)
                                blocks.append({"block_id": cid + f"/b{slot:02d}",
                                    "pair_id": cid + f"/p{pair:02d}", "variant": v,
                                    "slot": slot, "pair": pair, "calls_planned": 10})
                        clusters.append({"cluster_id": cid, "triplet_id": key,
                            "run_id": run["id"], "scope": scope, "batch": batch,
                            "rotation": rotation, "strategy_position": position,
                            "policy": policy, "blocks": blocks})
    return clusters


def make_plan(experiment, execution_commit):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", experiment):
        raise ValueError("invalid experiment identity")
    if not re.fullmatch(r"[a-f0-9]{40}", execution_commit):
        raise ValueError("invalid checkout commit")
    parent = Path(__file__).parent
    return {"schema": "ELIT01-cadence-pilot1-v1", "experiment": experiment,
        "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "execution_checkout_commit": execution_commit, "config": copy.deepcopy(CONFIG),
        "source_sha256": {n: hashlib.sha256((parent / n).read_bytes()).hexdigest()
                          for n in SOURCE_FILES},
        "schedule": build_schedule(experiment)}


def validate_plan(plan, verify_sources=True):
    if set(plan) != {"schema", "experiment", "created_at_utc", "execution_checkout_commit",
                     "config", "source_sha256", "schedule"}:
        raise ValueError("plan fields changed")
    if plan["schema"] != "ELIT01-cadence-pilot1-v1":
        raise ValueError("unknown schema")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", plan["experiment"]):
        raise ValueError("invalid experiment identity")
    if not re.fullmatch(r"[a-f0-9]{40}", plan["execution_checkout_commit"]):
        raise ValueError("invalid checkout commit")
    datetime.datetime.fromisoformat(plan["created_at_utc"])
    # Canonical comparison also rejects NaN and booleans substituted for integer budgets.
    if canonical(plan["config"]) != canonical(CONFIG):
        raise ValueError("frozen config changed")
    if canonical(plan["schedule"]) != canonical(build_schedule(plan["experiment"])):
        raise ValueError("frozen schedule/identity changed")
    if set(plan["source_sha256"]) != set(SOURCE_FILES):
        raise ValueError("source set changed")
    for name, sha in plan["source_sha256"].items():
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("invalid source digest")
        if verify_sources and hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != sha:
            raise ValueError("source digest mismatch: " + name)
    return plan


def load_plan(path, verify_sources=True):
    return validate_plan(json.loads(Path(path).read_text(encoding="utf-8")),
                         verify_sources=verify_sources)


def match_error(actual_gap_ns, target_ns, config=CONFIG):
    error = actual_gap_ns - target_ns
    tolerance = max(config["match_tolerance_abs_ns"],
                    config["match_tolerance_relative"] * target_ns)
    return {"actual_gap_ns": actual_gap_ns, "target_gap_ns": target_ns,
            "error_ns": error, "relative_error": error / target_ns,
            "tolerance_ns": tolerance, "matched": abs(error) <= tolerance}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create", help="write an immutable pilot schedule; no GPU imports")
    c.add_argument("--experiment", required=True)
    c.add_argument("--checkout-commit", required=True)
    c.add_argument("--output", type=Path, required=True)
    v = sub.add_parser("validate", help="validate plan and current measured source bytes")
    v.add_argument("--plan", type=Path, required=True)
    args = p.parse_args()
    if args.command == "create":
        plan = make_plan(args.experiment, args.checkout_commit)
        validate_plan(plan)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output, plan, exclusive=True)
    else:
        plan = load_plan(args.plan)
    print(json.dumps({"plan_sha256": digest(plan), "clusters": len(plan["schedule"]),
                      "planned_blocks": sum(len(c["blocks"]) for c in plan["schedule"]),
                      "GPU_imports": False}))


if __name__ == "__main__":
    main()
