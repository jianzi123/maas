"""Cap6 vs cap8 on original SGLang0.5.2 GPU decode; no Engine/weights.

The old harness stays byte-identical. Both variants are initially constructed
with cap8, then original backend metadata is rebuilt with the tested cap.
"""

import argparse, fcntl, hashlib, importlib.metadata as md, json, math, os, random, time
from pathlib import Path
import torch
from decode_path import DecodePath, check_finite_close
from run_decode import (
    capture,
    graph_sample,
    save,
    telemetry,
    verify_sources,
    fingerprint,
    summarize,
)

CELLS = (
    ("b8_l512", [512] * 8),
    ("b8_l1024", [1024] * 8),
    ("b8_l2048", [2048] * 8),
    ("b8_ragged", [17, 33, 129, 257, 511, 1023, 2048, 2049]),
)


def make(lengths, cap, seed, dtype=torch.float16):
    if cap not in (6, 8):
        raise ValueError("only predeclared cap6/cap8 comparison")
    p = DecodePath(lengths, cap=8, dtype=dtype, seed=seed)
    p.cap = cap
    p.backend.max_kv_splits = cap
    p.rebuild_metadata()
    p.assert_mapping()
    if p.backend.forward_metadata.attn_logits.shape[2] != cap:
        raise AssertionError("stale scratch")
    return p


def partition(p):
    splits = p.backend.forward_metadata.num_kv_splits.cpu().tolist()
    chunks = [math.ceil(math.ceil(n / s) / 32) * 32 for n, s in zip(p.lengths, splits)]
    active = [min(s, math.ceil(n / c)) for n, s, c in zip(p.lengths, splits, chunks)]
    groups = math.ceil(p.hq / min(16, p.hq // p.hkv))
    return {
        "splits": splits,
        "chunk_lengths": chunks,
        "active_splits": active,
        "stage1_grid": [len(p.lengths), groups, p.cap],
        "launched_CTAs": len(p.lengths) * groups * p.cap,
        "nonempty_CTAs": sum(active) * groups,
        "scratch_bytes": int(
            p.backend.forward_metadata.attn_logits.nbytes
            + p.backend.forward_metadata.attn_lse.nbytes
        ),
    }


def collect(out, keepers, iterations):
    from torch.profiler import profile, ProfilerActivity, record_function

    with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as prof:
        for case, paths, graphs, full, held in keepers:
            for cap, p in paths.items():
                for label, fn in (
                    ("raw", p.raw_decode),
                    ("graph_raw", graphs[cap].replay),
                ):
                    with record_function(f"cap6/{case}/{cap}/{label}"):
                        fn()
                        torch.cuda.synchronize()
    prof.export_chrome_trace(str(out / "timeline.json"))
    trace = json.loads((out / "timeline.json").read_text())
    kernels = [e for e in trace["traceEvents"] if e.get("cat") == "kernel"]
    rows = []
    for region in trace["traceEvents"]:
        if region.get("cat") != "user_annotation" or not region["name"].startswith(
            "cap6/"
        ):
            continue
        case, cap, scope = region["name"].split("/")[1:]
        cap = int(cap)
        found = [
            k
            for k in kernels
            if region["ts"] <= k["ts"]
            and k["ts"] + k.get("dur", 0) <= region["ts"] + region["dur"]
        ]
        count = 2 * (iterations if scope == "graph_raw" else 1)
        if len(found) != count:
            raise AssertionError("missing decode kernels in trace")
        first = [k for k in found if "grouped_kernel_stage1" in k["name"]]
        if not first or any(k["args"].get("grid") != [8, 3, cap] for k in first):
            raise AssertionError("actual stage1 grid differs from tested cap")
        rows.append(
            {
                "case": case,
                "cap": cap,
                "scope": scope,
                "kernel_count": len(found),
                "stage1_grid": first[0]["args"]["grid"],
                "stage1_registers_per_thread": first[0]["args"].get(
                    "registers per thread"
                ),
                "stage1_shared_bytes": first[0]["args"].get("shared memory"),
            }
        )
    if len(rows) != 16:
        raise AssertionError("missing profile regions")
    return {
        "regions": rows,
        "timings_excluded_from_A_B": True,
        "hardware_counters": None,
        "nonempty_CTAs": "derived from original pinned source partition formula and actual split tensors, NOT measured counter",
    }


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--output", type=Path, required=True)
    a.add_argument("--source-lock", type=Path, required=True)
    a.add_argument("--seed", type=int, required=True)
    a.add_argument("--profile", action="store_true")
    args = a.parse_args()
    lockpath = Path("/var/tmp/maas-10-gpu-01a1a5ba/gpu0-research.lock")
    lockpath.parent.mkdir(parents=True, exist_ok=True)
    guard = lockpath.open("a")
    fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
    args.output.mkdir(parents=True, exist_ok=False)
    source = verify_sources(json.loads(args.source_lock.read_text()))
    torch.set_grad_enabled(False)
    torch.cuda.set_device(0)
    if torch.cuda.mem_get_info()[0] < 1024**3:
        raise RuntimeError("less than 1GiB free")
    torch.cuda.set_per_process_memory_fraction(0.20)
    torch.backends.cuda.matmul.allow_tf32 = False
    report = {
        "scope": "original SGLang GPU backend tensor path; no Engine/model/serving",
        "seed": args.seed,
        "torch": torch.__version__,
        "triton": md.version("triton"),
        "sglang": md.version("sglang"),
        "cuda": torch.version.cuda,
        "SM_count": torch.cuda.get_device_properties(0).multi_processor_count,
        "device": torch.cuda.get_device_name(),
        "sources": source,
        "harness_sources": {
            n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
            for n in ("run_split_cap6.py", "decode_path.py", "run_decode.py")
        },
        "Engine": False,
        "weights_used": False,
        "rounds": 9,
        "iterations": 40,
        "telemetry_before": telemetry(),
        "hot_path_GPU_to_CPU_sync_added": False,
    }
    numerical = []
    for dtype in (torch.float16, torch.bfloat16):
        for case, lengths in CELLS:
            for cap in (8, 6):
                p = make(lengths, cap, args.seed, dtype)
                numerical.append(
                    {"case": case, "dtype": str(dtype), "cap": cap, "check": p.check()}
                )
    with torch.cuda.stream(torch.cuda.Stream()) as _:
        p = make([1024] * 8, 6, args.seed)
        nondefault = p.check()
    torch.cuda.synchronize()
    report["correctness"] = {"cases": numerical, "nondefault_stream": nondefault}
    save(args.output / "correctness.json", report["correctness"])
    print("cap6 GPU correctness passed", flush=True)
    rows = []
    keepers = []
    with (args.output / "samples.jsonl").open("x") as log:
        for case, lengths in CELLS:
            paths = {cap: make(lengths, cap, args.seed) for cap in (8, 6)}
            hashes = {cap: fingerprint(p) for cap, p in paths.items()}
            if hashes[8] != hashes[6]:
                raise AssertionError("unequal A/B data or mapping")
            params = {cap: partition(p) for cap, p in paths.items()}
            same = (
                params[8]["splits"] == params[6]["splits"]
                and params[8]["chunk_lengths"] == params[6]["chunk_lengths"]
            )
            paths[8].check()
            paths[6].check()
            held = {}

            def forward(cap):
                v = paths[cap].forward()
                held[cap] = v
                return v

            graphs = {c: capture(p.raw_decode, 40) for c, p in paths.items()}
            full = {c: capture(lambda c=c: forward(c), 40) for c in (8, 6)}
            captured = dict(held)
            for p in paths.values():
                p.o.fill_(float("nan"))
            for v in captured.values():
                v.fill_(float("nan"))
            per = {str(c): {"raw": [], "backend": []} for c in (8, 6)}
            rng = random.Random(args.seed)
            order = []
            for round_id in range(9):
                caps = [8, 6]
                rng.shuffle(caps)
                order.append(caps)
                for c in caps:
                    for label, g in (("raw", graphs[c]), ("backend", full[c])):
                        val = graph_sample(g, 40)
                        per[str(c)][label].append(val)
                        log.write(
                            json.dumps(
                                {
                                    "case": case,
                                    "round": round_id,
                                    "cap": c,
                                    "scope": label,
                                    **val,
                                }
                            )
                            + "\n"
                        )
                        log.flush()
            for c, p in paths.items():
                ref = p.reference()
                check_finite_close(p.o, ref, 3e-3)
                check_finite_close(captured[c].reshape_as(ref), ref, 3e-3)
            row = {
                "case": case,
                "lengths": lengths,
                "partition": params,
                "same_partition": same,
                "input_hashes": hashes[8],
                "round_order": order,
                "samples": per,
                "median_us": {
                    str(c): {
                        label: summarize(
                            [v["event_us_per_call"] for v in per[str(c)][label]]
                        )
                        for label in ("raw", "backend")
                    }
                    for c in (8, 6)
                },
                "post_graph_finite_close": True,
                "telemetry_after": telemetry(),
            }
            rows.append(row)
            keepers.append((case, paths, graphs, full, captured))
            print(
                json.dumps(
                    {
                        "case": case,
                        "same_partition": same,
                        "cap8_raw": row["median_us"]["8"]["raw"]["median"],
                        "cap6_raw": row["median_us"]["6"]["raw"]["median"],
                    }
                ),
                flush=True,
            )
    report["measurements"] = rows
    if args.profile:
        report["profile"] = collect(args.output, keepers, 40)
    verify_sources(json.loads(args.source_lock.read_text()))
    report.update(
        correctness_status="passed",
        telemetry_after=telemetry(),
        peak_allocated_bytes=torch.cuda.max_memory_allocated(),
        caveats=[
            "shared unlocked desktop GPU; no significance or Engine gain claim",
            "cap change also changes scratch layout/reduction bound, not isolated empty-CTA causal proof",
            "only same_partition cells test the empty-CTA hypothesis without repartitioning",
            "profile timings excluded; CUPTI grid is measured, nonempty CTA counts are derived",
        ],
    )
    save(args.output / "report.json", report)
    print(json.dumps({"status": "passed", "Engine": False}), flush=True)


if __name__ == "__main__":
    main()
