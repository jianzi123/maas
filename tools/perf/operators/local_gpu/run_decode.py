"""Bounded GPU SGLang decode/KV study; no weights, Engine or serving.

Run in the existing pinned WSL venv. CUDA graph microbench, eager component
measurements and CUPTI are distinct. Original kernels and backend methods run.
"""

import argparse, gc, hashlib, importlib.metadata as md, json, math, platform
from pathlib import Path
import random, statistics, subprocess, time, warnings
import torch
from decode_path import DecodePath, check_finite_close, validate

CAPS = (8, 1, 4)
CELLS = (
    ("short", [33]),
    ("long", [4097]),
    ("mixed", [17, 257, 1023, 2049]),
    ("batch8", [1024] * 8),
)


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def telemetry():
    cmd = [
        "/usr/lib/wsl/lib/nvidia-smi",
        "--id=0",
        "--query-gpu=timestamp,pstate,memory.free,memory.used,clocks.sm,temperature.gpu,power.draw,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return {
            "returncode": p.returncode,
            "csv": p.stdout.strip(),
            "fields": [
                "timestamp",
                "pstate",
                "free_MiB",
                "used_MiB",
                "SM_MHz",
                "temp_C",
                "power_W",
                "util_pct",
            ],
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"unavailable": True}


def verify_sources(lock):
    root = Path(md.distribution("sglang").locate_file("sglang"))
    if (
        md.version("sglang") != "0.5.2"
        or lock["commit"] != "b0d25e72c401f37b55d689ddbf05b8c583afe854"
        or not lock["all_match"]
    ):
        raise ValueError("requires pinned SGLang source")
    for row in lock["files"]:
        if not row["matches_upstream"] or row["sha256"] != row["upstream_sha256"]:
            raise ValueError("unverified source")
        if (
            hashlib.sha256((root / row["path"]).read_bytes()).hexdigest()
            != row["sha256"]
        ):
            raise ValueError("installed source changed")
    return [{"path": r["path"], "sha256": r["sha256"]} for r in lock["files"]]


def fingerprint(p):
    return {
        name: hashlib.sha256(
            t.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()
        ).hexdigest()
        for name, t in (
            ("q", p.q),
            ("logical_k", p.logical_k),
            ("logical_v", p.logical_v),
            ("physical", p.physical),
        )
    }


def correctness(seed):
    rows = []
    rejected = []
    cases = (
        ([1, 17], 8, 8, 64, 0.0),
        ([31, 33, 129], 9, 3, 64, 0.0),
        ([257], 8, 1, 80, 0.0),
        ([1, 17], 8, 2, 128, 1.5),
    )
    for dtype in (torch.float16, torch.bfloat16):
        for lengths, hq, hkv, d, cap_logits in cases:
            for cap in (1, 8):
                p = DecodePath(lengths, hq, hkv, d, cap, dtype, seed, cap_logits)
                rows.append(
                    {
                        "metadata": p.metadata(),
                        "check": p.check(),
                        "logit_cap": cap_logits,
                    }
                )
                del p
                gc.collect()
    # Actual original backend/kernel on an independently created nondefault stream.
    stream = torch.cuda.Stream()
    with torch.cuda.stream(stream):
        p = DecodePath([33, 129], seed=seed)
        check = p.check()
    stream.synchronize()
    rows.append({"nondefault_stream": True, "check": check})
    # Exceptional inputs never produce performance success.
    for value in (float("nan"), float("inf"), -float("inf")):
        p.q[0, 0, 0] = value
        try:
            check_finite_close(p.raw_decode(), p.reference(), 3e-3)
        except AssertionError:
            rejected.append("finite_gate:" + str(value))
        else:
            raise AssertionError("nonfinite output accepted")
    del p
    for name, args in (
        ("zero_length", ([0], 9, 3, 64, 8, torch.float16)),
        ("too_long", ([4098], 9, 3, 64, 8, torch.float16)),
        ("head_mismatch", ([33], 9, 2, 64, 8, torch.float16)),
        ("invalid_cap", ([33], 9, 3, 64, 0, torch.float16)),
        ("wrong_dtype", ([33], 9, 3, 64, 8, torch.int32)),
    ):
        try:
            validate(*args)
        except ValueError:
            rejected.append(name)
        else:
            raise AssertionError("missing prelaunch rejection")
    return {
        "cases": rows,
        "rejected": rejected,
        "reference": "independent logical-order GPU FP64 equation",
        "tail_unreferenced_KV_slots_poisoned_with_NaN": True,
        "context_includes_new_token": True,
        "future_tokens_not_present": True,
    }


def capture(fn, iterations):
    for _ in range(8):
        fn()
    torch.cuda.synchronize()
    g = torch.cuda.CUDAGraph()
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message="The CUDA Graph is empty.*")
        with torch.cuda.graph(g):
            for _ in range(iterations):
                fn()
    g.replay()
    torch.cuda.synchronize()
    return g


def graph_sample(g, iterations):
    a, b = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    start = time.perf_counter_ns()
    a.record()
    g.replay()
    b.record()
    b.synchronize()
    return {
        "event_us_per_call": a.elapsed_time(b) * 1000 / iterations,
        "synchronized_replay_wall_us_per_call": (time.perf_counter_ns() - start)
        / 1000
        / iterations,
    }


def eager_sample(fn, iterations=5):
    torch.cuda.synchronize()
    a, b = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    t = time.perf_counter_ns()
    a.record()
    for _ in range(iterations):
        fn()
    b.record()
    b.synchronize()
    return {
        "event_with_host_launch_gaps_us_per_call": a.elapsed_time(b)
        * 1000
        / iterations,
        "synchronized_wall_us_per_call": (time.perf_counter_ns() - t)
        / 1000
        / iterations,
    }


def summarize(values):
    ordered = sorted(values)
    return {
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "q25": ordered[len(ordered) // 4],
        "q75": ordered[(len(ordered) * 3) // 4],
    }


def collect_profile(output, paths, graphs, iterations):
    from torch.profiler import ProfilerActivity, profile, record_function

    with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as prof:
        for cap, p in paths.items():
            for stage, fn in (
                ("metadata", p.rebuild_metadata),
                ("kv_write", p.write),
                ("raw_decode", p.raw_decode),
                ("backend_forward", p.forward),
            ):
                # Metadata replacement is intentional here; do not benchmark this trace.
                with record_function(f"decode/cap{cap}/{stage}"):
                    for _ in range(3):
                        fn()
                    torch.cuda.synchronize()
            with record_function(f"decode/cap{cap}/graph_raw_{iterations}"):
                graphs[cap].replay()
                torch.cuda.synchronize()
    prof.export_chrome_trace(str(output / "timeline.json"))
    trace = json.loads((output / "timeline.json").read_text())
    kernels = [e for e in trace["traceEvents"] if e.get("cat") == "kernel"]
    regions = [
        e
        for e in trace["traceEvents"]
        if e.get("cat") == "user_annotation" and e["name"].startswith("decode/")
    ]
    records = []
    for region in regions:
        observed = [
            e
            for e in kernels
            if region["ts"] <= e["ts"]
            and e["ts"] + e.get("dur", 0) <= region["ts"] + region["dur"]
        ]
        names = {}
        for event in observed:
            item = names.setdefault(event["name"], {"count": 0, "duration_us": 0.0})
            item["count"] += 1
            item["duration_us"] += event.get("dur", 0)
        records.append(
            {
                "region": region["name"],
                "cpu_range_with_sync_us": region["dur"],
                "kernel_count": len(observed),
                "kernels": names,
            }
        )
        expected = (
            2 * iterations
            if "/graph_raw_" in region["name"]
            else (6 if region["name"].endswith("/raw_decode") else 1)
        )
        if len(observed) < expected:
            raise RuntimeError("missing actual kernels / empty captured graph")
    return {
        "regions": records,
        "kernel_names": sorted({e["name"] for e in kernels}),
        "hardware_counters": None,
        "device_time_is_profiled_not_steady_benchmark": True,
        "graph_evidence": "actual CUPTI kernel count within synchronized graph replay region; not Engine CudaGraphRunner",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--source-lock", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=20261113)
    ap.add_argument("--rounds", type=int, default=7)
    ap.add_argument("--iterations", type=int, default=30)
    ap.add_argument("--profile", action="store_true")
    args = ap.parse_args()
    if not 3 <= args.rounds <= 11 or not 4 <= args.iterations <= 50:
        raise ValueError("bounded experiment caps")
    args.output.mkdir(parents=True, exist_ok=False)
    lock = json.loads(args.source_lock.read_text())
    source = verify_sources(lock)
    torch.set_grad_enabled(False)
    torch.cuda.set_device(0)
    free, total = torch.cuda.mem_get_info()
    if free < 1024**3:
        raise RuntimeError("less than 1GiB free; do not reclaim others")
    torch.cuda.set_per_process_memory_fraction(0.20)
    torch.backends.cuda.matmul.allow_tf32 = False
    report = {
        "evidence": "actual_installed_SGLang_backend_GPU_tensor_harness",
        "sglang": md.version("sglang"),
        "torch": torch.__version__,
        "triton": md.version("triton"),
        "cuda": torch.version.cuda,
        "device": torch.cuda.get_device_name(),
        "capability": torch.cuda.get_device_capability(),
        "SM_count": torch.cuda.get_device_properties(0).multi_processor_count,
        "free_total_before": [free, total],
        "seed": args.seed,
        "rounds": args.rounds,
        "graph_iterations": args.iterations,
        "sources": source,
        "harness_sources": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(__file__).parent.glob("*decode*.py")
        },
        "clock_policy": "unlocked shared desktop GPU; snapshots only, no frequency control",
        "scope": "original RadixAttention.forward -> AttentionBackend.forward -> TritonAttnBackend.forward_decode + MHATokenToKVPool",
        "state_boundary": "backend state assembled with __new__, synthetic batch/request table; metadata/forward/KV/kernel code original",
        "model_runner_initialized": False,
        "Engine_initialized": False,
        "serving_executed": False,
        "model_weights_used": False,
        "model_quality_tested": False,
        "engine_speedup_claim": False,
        "telemetry_before": telemetry(),
    }
    t = time.perf_counter()
    report["correctness"] = correctness(args.seed)
    report["correctness_setup_s"] = time.perf_counter() - t
    save(args.output / "correctness.json", report["correctness"])
    print("GPU correctness passed", flush=True)
    matrix = []
    last = None
    samples = (args.output / "samples.jsonl").open("x")
    try:
        for label, lengths in CELLS:
            phase_start = time.perf_counter()
            before = telemetry()
            paths = {cap: DecodePath(lengths, cap=cap, seed=args.seed) for cap in CAPS}
            checks = {str(cap): p.check() for cap, p in paths.items()}
            hashes = {str(cap): fingerprint(p) for cap, p in paths.items()}
            if len({json.dumps(v, sort_keys=True) for v in hashes.values()}) != 1:
                raise AssertionError("A/B inputs or physical mapping differ")
            captured_metadata = {
                cap: p.backend.forward_metadata for cap, p in paths.items()
            }
            graphs = {
                cap: capture(p.raw_decode, args.iterations) for cap, p in paths.items()
            }
            # Full forward separately includes KV writes and output allocation.
            fullgraphs = {
                cap: capture(p.forward, args.iterations) for cap, p in paths.items()
            }
            setup_s = time.perf_counter() - phase_start
            percap = {cap: [] for cap in CAPS}
            fullcap = {cap: [] for cap in CAPS}
            randomizer = random.Random(args.seed)
            order_log = []
            for round_id in range(args.rounds):
                order = list(CAPS)
                randomizer.shuffle(order)
                order_log.append(order)
                for cap in order:
                    raw = graph_sample(graphs[cap], args.iterations)
                    full = graph_sample(fullgraphs[cap], args.iterations)
                    percap[cap].append(raw)
                    fullcap[cap].append(full)
                    samples.write(
                        json.dumps(
                            {
                                "cell": label,
                                "round": round_id,
                                "cap": cap,
                                "raw_decode_graph": raw,
                                "backend_graph": full,
                            }
                        )
                        + "\n"
                    )
                    samples.flush()
            components = {}
            for cap, p in paths.items():
                components[str(cap)] = {
                    name: eager_sample(fn)
                    for name, fn in (
                        ("metadata", p.rebuild_metadata),
                        ("kv_write", p.write),
                        ("raw_decode", p.raw_decode),
                        ("backend_forward", p.forward),
                    )
                }
            rows = []
            for cap, p in paths.items():
                rows.append(
                    {
                        "cap": cap,
                        "metadata": p.metadata(),
                        "input_hashes": hashes[str(cap)],
                        "check": checks[str(cap)],
                        "raw_decode_graph_samples": percap[cap],
                        "backend_graph_samples": fullcap[cap],
                        "raw_decode_graph_us": summarize(
                            [x["event_us_per_call"] for x in percap[cap]]
                        ),
                        "backend_graph_us": summarize(
                            [x["event_us_per_call"] for x in fullcap[cap]]
                        ),
                    }
                )
            cell = {
                "id": label,
                "lengths": lengths,
                "warmup_compile_capture_setup_s": setup_s,
                "round_order": order_log,
                "variants": rows,
                "eager_components": components,
                "telemetry_before": before,
                "telemetry_after": telemetry(),
            }
            matrix.append(cell)
            print(
                json.dumps(
                    {
                        "cell": label,
                        "raw_graph_us": {
                            str(r["cap"]): r["raw_decode_graph_us"]["median"]
                            for r in rows
                        },
                    }
                ),
                flush=True,
            )
            last = (paths, graphs, fullgraphs, captured_metadata)
    finally:
        samples.close()
    report["measurements"] = matrix
    report["torch_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
    if args.profile:
        report["profile"] = collect_profile(
            args.output, last[0], last[1], args.iterations
        )
    verify_sources(lock)
    report["telemetry_after"] = telemetry()
    report["correctness_status"] = "passed"
    report["caveats"] = [
        "no hardware counters; no DRAM/occupancy bottleneck claim",
        "same seed/input/physical mapping across caps; dynamic split upper bound is sole A/B factor",
        "graph interval includes graph execution gaps, not pure kernel duration",
        "eager intervals include host launch gaps; component timings overlap, do not add",
        "3 independent processes requested separately; rounds within a process are not independent runs",
        "this changes no engine configuration or upstream kernel; no model/Engine/serving benefit inferred",
    ]
    save(args.output / "report.json", report)
    print(
        json.dumps(
            {
                "status": "passed",
                "cells": len(matrix),
                "profile": args.profile,
                "engine_speedup_claim": False,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Preserve raw failure in foreground stderr; successful report only written last.
        raise
