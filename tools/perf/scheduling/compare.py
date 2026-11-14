"""Paired CPU page-budget scheduling, no GPU/model calls or latency prediction."""

from dataclasses import replace, asdict
from pathlib import Path
import argparse, hashlib, json, os, statistics, sys, uuid

if __package__:
    from .algorithm import Engine, Entry, Limits
else:
    from algorithm import Engine, Entry, Limits

J02 = Path(__file__).resolve().parents[1] / "runtime/J02-mixed-sequence.json"


def digest(obj):
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def workload(path=J02, profile="clean"):
    raw = Path(path).read_bytes()
    d = json.loads(raw)
    entries = [
        Entry(
            "j02-" + str(x["index"]).zfill(3),
            x["shape"],
            x["input_target_tokens"],
            x["output_cap_tokens"],
            x["planned_offset_ms"] // 10,
            prefix_key=("shared" if x["index"] % 4 == 0 else None),
            cancel_round=(
                x["planned_offset_ms"] // 10 + 8
                if profile == "faults" and x["index"] % 31 == 0
                else None
            ),
            fail_after=(3 if profile == "faults" and x["index"] % 47 == 1 else None),
            lose_release=(profile == "faults" and x["index"] == 1),
        )
        for x in d["entries"]
    ]
    return (
        entries,
        {"shared": 33},
        {
            "source_workload": d["workload_id"],
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "distribution": d["distribution"],
            "arrival_mapping": "planned_offset_ms // 10 interpreted ONLY as logical rounds",
            "lengths": "synthetic target counts; no frozen tokenizer/model executed",
            "prefix": "synthetic exact-match shared length33 on every fourth entry",
            "profile": profile,
            "entry_sha256": digest([asdict(e) for e in entries]),
        },
    )


def score(result):
    # Incomplete/rejected runs cannot win static tuning by dropping work.
    if result["counts"].get("completed", 0) != result["sent"]:
        return (1, float("inf"))
    return (0, result["logical_rounds"])


def compare(repeats=3, limits=Limits(), profiles=("clean", "faults")):
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("bounded repeats")
    entries, prefix, manifest = workload()
    # Disjoint synthetic calibration corpus, not J02 measurement rows.
    calibration = [
        Entry(
            "cal-" + str(i),
            ("S", "M", "L")[i % 3],
            (128, 768, 3072)[i % 3],
            (32, 64, 128)[i % 3],
            i // 2,
        )
        for i in range(12)
    ]
    tuning = []
    for chunk in (64, 128, 256):
        result = Engine(
            calibration, limits, prefixes={}, policy="static", chunk=chunk
        ).run()
        tuning.append(
            {
                "chunk": chunk,
                "score": score(result),
                "logical_rounds": result["logical_rounds"],
                "counts": result["counts"],
                "planning_cpu_ns": result["planning_cpu_ns"],
            }
        )
    best = min(tuning, key=lambda r: (r["score"], r["chunk"]))["chunk"]
    trials = []
    for profile in profiles:
        entries, prefix, manifest = workload(profile=profile)
        policy_defs = [
            ("static", best),
            ("adaptive", best),
            ("age_fair", best),
            ("no_age", best),
        ]
        for replicate in range(repeats):
            # Deterministic balanced permutation, paired identical inputs/resources.
            order = (
                policy_defs[:] if replicate % 2 == 0 else list(reversed(policy_defs))
            )
            for policy, chunk in order:
                trial = Engine(
                    entries, limits, prefixes=prefix, policy=policy, chunk=chunk
                ).run()
                trial.update(profile=profile, replicate=replicate, manifest=manifest)
                trials.append(trial)
    summaries = []
    for profile in profiles:
        base = [
            r for r in trials if r["profile"] == profile and r["policy"] == "static"
        ]
        for policy in Engine.POLICIES:
            cases = [
                r for r in trials if r["profile"] == profile and r["policy"] == policy
            ]
            comparisons = [
                {
                    "replicate": a["replicate"],
                    "round_delta": b["logical_rounds"] - a["logical_rounds"],
                    "counts_equal": b["counts"] == a["counts"],
                    "planning_cpu_ns_ratio": b["planning_cpu_ns"]["sum"]
                    / a["planning_cpu_ns"]["sum"],
                }
                for a, b in zip(base, cases)
            ]
            first = cases[0]
            summaries.append(
                {
                    "profile": profile,
                    "policy": policy,
                    "counts": first["counts"],
                    "remaining_unrecovered": first["remaining_unrecovered"],
                    "remaining_pending": first["remaining_pending"],
                    "logical_rounds": first["logical_rounds"],
                    "peak_physical_pages": first["peak_physical_pages"],
                    "peak_reserved_pages": first["peak_reserved_including_cache"],
                    "remaining_pages": first["pages_remaining"],
                    "by_shape": first["by_shape"],
                    "diagnostics": first["diagnostics"],
                    "planning_cpu_ns_total_median": statistics.median(
                        c["planning_cpu_ns"]["sum"] for c in cases
                    ),
                    "paired_against_tuned_static": comparisons,
                }
            )
    return {
        "schema_version": "cpu-page-scheduling-1.0",
        "synthetic_inputs": True,
        "execution_enabled": False,
        "gpu_executed": False,
        "model_executed": False,
        "engine_executed": False,
        "real_performance_conclusion": None,
        "real_slo": None,
        "baseline_scope": "tuned CPU static / adaptive-share proxy; upstream AST probe is separate and NOT a full SGLang baseline",
        "limits": asdict(limits),
        "derived_capacity_pages": limits.capacity,
        "activation_model": "linear synthetic bytes per selected position; requires engine-specific profile before real use",
        "calibration_entry_sha256": digest([asdict(e) for e in calibration]),
        "calibration_tuning": tuning,
        "selected_static_chunk": best,
        "repeats": repeats,
        "independent_statistical_ci": None,
        "ci_reason": "logical scheduler deterministic repeats are not independent model performance samples",
        "summaries": summaries,
        "trials": trials,
        "implementation_boundary": "synchronous host page occupancy; prior runtime_lab separately covers asynchronous completion/cancel",
    }


def write_report(path, report):
    path = Path(path)
    if path.exists():
        raise FileExistsError("fresh report filename required")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(report, indent=2, allow_nan=False) + "\n"
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--horizon", type=int, default=4000)
    a = p.parse_args()
    if not __debug__:
        p.error("normal invariant mode required")
    if a.output.exists():
        p.error("fresh output filename required")
    try:
        report = compare(a.repeats, replace(Limits(), horizon=a.horizon))
        write_report(a.output, report)
    except (ValueError, OSError) as exc:
        print(type(exc).__name__ + ": scheduling lab rejected", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "policies": 4,
                "profiles": 2,
                "paired_repeats": a.repeats,
                "output": a.output.name,
                "gpu_executed": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
