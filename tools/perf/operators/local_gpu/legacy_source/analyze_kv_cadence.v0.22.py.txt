"""Read-only E-LIT-01 analysis: complete planned denominator, no fast-sample selection."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics

from cadence_protocol import load_plan, digest, match_error, write_json


def jsonlines(path):
    if not path.exists():
        return []
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]


def validate_block(row, block, cluster, runtime, cell, config):
    for key in ("block_id", "pair_id", "variant", "slot", "pair", "calls_planned"):
        if row.get(key) != block[key]:
            raise ValueError("block/pair identity changed: " + key)
    for key in ("cluster_id", "triplet_id", "run_id", "scope", "batch", "policy",
                "rotation", "strategy_position"):
        if row.get(key) != cluster[key]:
            raise ValueError("cluster identity changed: " + key)
    if row.get("status") not in ("measured", "missing", "invalid"):
        raise ValueError("unknown block status")
    if row["status"] == "missing":
        if row.get("calls_completed") != 0 or any(k in row for k in ("wall_ns", "event_ns")):
            raise ValueError("missing block carries measurements")
        return
    if row["status"] == "invalid":
        return
    if runtime is None or cell is None:
        raise ValueError("measured block lacks frozen manifest")
    if row["clock_scope"] != runtime["clock_scope"] or row["runtime_manifest_sha256"] != digest(runtime):
        raise ValueError("foreign clock/runtime identity")
    if row["cell_sha256"] != digest(cell):
        raise ValueError("cell identity changed")
    if row["calls_completed"] != 10:
        raise ValueError("incomplete hot block")
    for k in ("event_ns", "wall_ns", "host_enqueue_ns", "wait_ns", "thread_cpu_ns"):
        if not isinstance(row[k], (int, float)) or isinstance(row[k], bool) or not math.isfinite(row[k]) or row[k] <= 0:
            raise ValueError("nonfinite/nonpositive timing")
    previous, ready, submit, enqueue, done = [row[k] for k in
        ("previous_done_ns", "ready_ns", "submit_ns", "enqueue_end_ns", "done_ns")]
    if not previous <= ready <= submit <= enqueue <= done:
        raise ValueError("timestamp order")
    if row["wall_ns"] != done - submit or row["host_enqueue_ns"] != enqueue - submit or row["wait_ns"] != done - enqueue:
        raise ValueError("wall accounting changed")
    if row["preparation_ns"] != ready - previous or row["ready_to_submit_ns"] != submit - ready:
        raise ValueError("gap accounting changed")
    if "frozen_at_monotonic_ns" in runtime and not runtime["frozen_at_monotonic_ns"] <= cell["frozen_at_monotonic_ns"] <= submit:
        raise ValueError("manifest frozen after sample")
    target = runtime["targets_ns"][row["variant"]]
    if not isinstance(target, int) or isinstance(target, bool) or not 0 < target <= config["max_calibrated_target_ns"]:
        raise ValueError("invalid calibration target")
    expected = match_error(submit - previous, target, config)
    if row["gap_match"] != expected:
        raise ValueError("idle matching error/qualification changed")
    should_query = row["policy"] == "query_block" or (row["policy"] == "query_cluster" and row["slot"] == 0)
    if should_query:
        if row["query_id"] != row["block_id"] + "/query":
            raise ValueError("query identity")
        if not ready <= row["query_begin_ns"] <= row["query_end_ns"] <= submit:
            raise ValueError("query timestamps")
    elif any(row.get(k) is not None for k in ("query_id", "query_begin_ns", "query_end_ns")):
        raise ValueError("unexpected query")
    if row["policy"] == "idle_matched":
        if not ready <= row["sleep_begin_ns"] <= row["sleep_end_ns"] <= submit:
            raise ValueError("sleep timestamps")
        expected_sleep = max(0, previous + target - row["sleep_begin_ns"])
        if row["sleep_requested_ns"] != expected_sleep:
            raise ValueError("sleep request changed")


def analyze(plan, root):
    config = plan["config"]
    all_rows, complete_clusters, run_summaries = [], {}, []
    for run in config["runs"]:
        name = run["id"]
        folder = root / name
        expected_clusters = [c for c in plan["schedule"] if c["run_id"] == name]
        expected = {b["block_id"]: (b, c) for c in expected_clusters for b in c["blocks"]}
        result = json.loads((folder / "run.json").read_text()) if (folder / "run.json").exists() else None
        runtime = json.loads((folder / "runtime-manifest.json").read_text()) if (folder / "runtime-manifest.json").exists() else None
        cells = json.loads((folder / "cells.json").read_text()) if (folder / "cells.json").exists() else []
        cell_map = {c["cell_id"]: c for c in cells}
        if len(cell_map) != len(cells):
            raise ValueError("duplicate cell")
        if runtime is not None and (runtime["run_id"] != name or runtime["plan_sha256"] != digest(plan)
                                    or runtime["source_sha256"] != plan["source_sha256"]):
            raise ValueError("runtime manifest mismatch")
        rows = jsonlines(folder / "blocks.jsonl")
        by_id = {}
        for r in rows:
            key = r["block_id"]
            if key not in expected or key in by_id:
                raise ValueError("unknown/duplicate block")
            b, c = expected[key]
            cell = cell_map.get(f"{name}/{c['scope']}/B{c['batch']}")
            validate_block(r, b, c, runtime, cell, config)
            by_id[key] = r
        for key, (b, c) in expected.items():
            if key not in by_id:
                by_id[key] = dict(b, run_id=name, scope=c["scope"], batch=c["batch"],
                    cluster_id=c["cluster_id"], triplet_id=c["triplet_id"],
                    policy=c["policy"], rotation=c["rotation"],
                    strategy_position=c["strategy_position"], status="missing", calls_completed=0,
                    missing_reason="not observed / process not completed; synthesized identity only")
        if len(by_id) != 540:
            raise ValueError("run denominator changed")
        status = Counter(r["status"] for r in by_id.values())
        queries = jsonlines(folder / "queries.jsonl")
        query_ids = {q["query_id"] for q in queries}
        if len(query_ids) != len(queries):
            raise ValueError("duplicate query identity")
        for q in queries:
            if runtime and q["clock_scope"] != runtime["clock_scope"]:
                raise ValueError("foreign query clock")
        for r in by_id.values():
            if r["status"] == "measured" and r.get("query_id"):
                q = next((q for q in queries if q["query_id"] == r["query_id"]), None)
                if q is None or q["begin_ns"] != r["query_begin_ns"] or q["end_ns"] != r["query_end_ns"]:
                    raise ValueError("query record missing/mismatched")
        if runtime is not None:
            calibration = json.loads((folder / "calibration.json").read_text())
            if len(calibration) != 20 or digest(calibration) != runtime["calibration_sha256"]:
                raise ValueError("calibration identity changed")
            for variant in ("native", "mature"):
                samples = [r["total_gap_ns"] for r in calibration if r["variant"] == variant]
                if len(samples) != 10 or int(statistics.median(samples)) != runtime["targets_ns"][variant]:
                    raise ValueError("calibration target changed")
            for c in calibration:
                q = next((q for q in queries if q["query_id"] == c["query_id"]), None)
                if q is None or c["query_duration_ns"] != q["end_ns"] - q["begin_ns"] or c["total_gap_ns"] != c["submit_proxy_ns"] - c["previous_done_ns"]:
                    raise ValueError("calibration query accounting")
        if result is not None and result.get("status") == "completed":
            if result.get("collection_complete") is not True or status != Counter({"measured": 540}) or len(queries) != 218:
                raise ValueError("complete run hides missing/query coverage")
            gates = json.loads((folder / "gates.json").read_text())
            if len(gates) != 13 or any(g["status"] != "passed" for g in gates):
                raise ValueError("complete run lacks state gates")
            import hashlib
            import numpy as np
            for gate in gates:
                arrays = {}
                for variant, snapshots in gate["snapshots"].items():
                    arrays[variant] = []
                    for snapshot in snapshots:
                        path = (folder / snapshot["path"]).resolve()
                        if not path.is_relative_to(folder.resolve()):
                            raise ValueError("snapshot path escaped evidence")
                        with np.load(path, allow_pickle=False) as archive:
                            value = archive["value"]
                            if (not np.isfinite(value).all() or list(value.shape) != snapshot["shape"]
                                    or str(value.dtype) != snapshot["dtype"]
                                    or hashlib.sha256(value.tobytes()).hexdigest() != snapshot["raw_sha256"]):
                                raise ValueError("snapshot finite/hash mismatch")
                            arrays[variant].append(value.copy())
                for a, b in zip(arrays["native"], arrays["mature"]):
                    if a.dtype != b.dtype or a.shape != b.shape or a.tobytes() != b.tobytes():
                        raise ValueError("state gate bitwise mismatch")
        reports = json.loads((folder / "clusters.json").read_text()) if (folder / "clusters.json").exists() else []
        expected_by_cid = {c["cluster_id"]: c for c in expected_clusters}
        seen = set()
        for report in reports:
            cid = report["cluster_id"]
            if cid not in expected_by_cid or cid in seen:
                raise ValueError("cluster duplicate/unknown")
            seen.add(cid)
            if report["status"] != "completed":
                continue
            c = expected_by_cid[cid]
            measured = [by_id[b["block_id"]] for b in c["blocks"]]
            if any(r["status"] != "measured" for r in measured):
                raise ValueError("completed cluster contains missing/invalid block")
            if (report["planned_blocks"], report["completed_blocks"], report["planned_calls"], report["completed_calls"]) != (10, 10, 100, 100):
                raise ValueError("cluster denominator changed")
            if report["elapsed_ns"] != report["end_ns"] - report["begin_ns"] or report["elapsed_ns"] < sum(r["wall_ns"] for r in measured):
                raise ValueError("cluster wall accounting")
            stats = {}
            for variant in ("native", "mature"):
                subset = [r for r in measured if r["variant"] == variant]
                if len(subset) != 5:
                    raise ValueError("variant denominator changed")
                stats[variant] = {k: statistics.median(r[k] / 10000 for r in subset)
                                  for k in ("wall_ns", "event_ns", "host_enqueue_ns", "wait_ns")}
            match_blocks = [r for r in measured if c["policy"] in ("query_block", "idle_matched")]
            value = {"cluster_id": cid, "run_id": name, "scope": c["scope"],
                "batch": c["batch"], "rotation": c["rotation"], "policy": c["policy"],
                "strategy_position": c["strategy_position"],
                "cluster_wall_ms_per_100_calls": report["elapsed_ns"] / 1e6,
                "variant_block_median_us_per_call": stats,
                "gap_matched": sum(r["gap_match"]["matched"] for r in match_blocks),
                "gap_qualification_denominator": len(match_blocks),
                "match_errors_ns": [r["gap_match"]["error_ns"] for r in match_blocks]}
            complete_clusters[cid] = value
        if result is not None and result.get("status") == "completed" and len(reports) != 54:
            raise ValueError("completed run hides missing cluster")
        all_rows.extend(by_id.values())
        run_summaries.append({"run_id": name, "result": result,
            "planned_blocks": 540, "status_counts": dict(status),
            "observed_ledger_rows": len(rows), "unobserved_identities": 540 - len(rows),
            "query_events": len(queries), "complete_clusters": sum(c["run_id"] == name for c in complete_clusters.values())})
    triplets = []
    for key in dict.fromkeys(c["triplet_id"] for c in plan["schedule"]):
        wanted = [c for c in plan["schedule"] if c["triplet_id"] == key]
        found = {c["policy"]: complete_clusters[c["cluster_id"]] for c in wanted if c["cluster_id"] in complete_clusters}
        row = {"triplet_id": key, "scope": wanted[0]["scope"], "run_id": wanted[0]["run_id"],
               "batch": wanted[0]["batch"], "rotation": wanted[0]["rotation"],
               "completed_policies": len(found), "complete": len(found) == 3}
        if len(found) == 3:
            base = found["query_block"]["cluster_wall_ms_per_100_calls"]
            row["policy_cluster_ms"] = {p: r["cluster_wall_ms_per_100_calls"] for p, r in found.items()}
            row["ratio_vs_query_block"] = {p: r["cluster_wall_ms_per_100_calls"] / base for p, r in found.items()}
            row["idle_match_qualified"] = found["idle_matched"]["gap_matched"] == 10 and found["query_block"]["gap_matched"] == 10
        triplets.append(row)
    return {"schema": "ELIT01-analysis-v1", "plan_sha256": digest(plan),
        "primary_scope": config["primary_scope"], "primary_metric": config["primary_metric"],
        "planned_clusters": 108, "planned_blocks": 1080, "planned_calls": 10800,
        "block_status_counts": dict(Counter(r["status"] for r in all_rows)),
        "run_summaries": run_summaries, "clusters": list(complete_clusters.values()), "triplets": triplets,
        "full_independent_processes_planned": 2,
        "dependent_blocks_not_population_samples": True,
        "stable_model_gain_claim": False, "isolated_query_or_idle_root_cause_claim": False,
        "scope_limit": "artificial-weight static calls/replays; all missing/slow/mismatched blocks retained"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True, help="contains R01/R02, including missing runs")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    plan = load_plan(args.plan)
    result = analyze(plan, args.root)
    write_json(args.output, result, exclusive=True)
    print(json.dumps({"planned_blocks": result["planned_blocks"],
        "status_counts": result["block_status_counts"], "complete_clusters": len(result["clusters"]),
        "primary_scope": result["primary_scope"], "root_cause_claim": False}))


if __name__ == "__main__":
    main()
