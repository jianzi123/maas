"""Single-factor fused-KV write study through the original SGLang backend."""

import argparse, gc, hashlib, json, os, random, subprocess, sys, time
from pathlib import Path
import torch
from decode_path import DecodePath
from kv_extension import FusedKV
from run_decode import (
    capture,
    graph_sample,
    eager_sample,
    save,
    summarize,
    telemetry,
    verify_sources,
    CELLS,
)


def functions(p, ext):
    original = p.pool.set_kv_buffer
    fused = ext.bind(p)

    def forward_original():
        p.pool.set_kv_buffer = original
        return p.forward()

    def forward_fused():
        p.pool.set_kv_buffer = fused
        return p.forward()

    return (
        {
            "write_original": lambda: original(p.layer, p.locations, p.new_k, p.new_v),
            "write_fused": lambda: fused(p.layer, p.locations, p.new_k, p.new_v),
            "backend_original": forward_original,
            "backend_fused": forward_fused,
        },
        original,
        fused,
    )


def correctness(ext, seed):
    records = []
    for dtype in (torch.float16, torch.bfloat16):
        for d, lengths in ((64, [1]), (80, [17, 33]), (128, [33, 129, 257])):
            p = DecodePath(lengths, dim=d, dtype=dtype, seed=seed)
            p.pool.set_kv_buffer = ext.bind(p)
            records.append(
                {"dtype": str(dtype), "lengths": lengths, "dim": d, "check": p.check()}
            )
            del p
            gc.collect()
    stream = torch.cuda.Stream()
    with torch.cuda.stream(stream):
        p = DecodePath([33, 129], seed=seed)
        p.pool.set_kv_buffer = ext.bind(p)
        records.append({"nondefault_stream": True, "check": p.check()})
    stream.synchronize()
    op = torch.ops.maas_decode_kv.write
    kc = p.pool.get_key_buffer(0)
    vc = p.pool.get_value_buffer(0)
    base = (kc, vc, p.locations, p.new_k, p.new_v, ext.handle)
    bad = [
        ("locations_dtype", (kc, vc, p.locations.int(), p.new_k, p.new_v, ext.handle)),
        (
            "source_dtype",
            (kc, vc, p.locations, p.new_k.float(), p.new_v.float(), ext.handle),
        ),
        (
            "source_stride",
            (kc, vc, p.locations, p.new_k.transpose(1, 2), p.new_v, ext.handle),
        ),
        ("cache_alias", (kc, kc, p.locations, p.new_k, p.new_v, ext.handle)),
        (
            "grad",
            (
                kc,
                vc,
                p.locations,
                p.new_k.clone().requires_grad_(),
                p.new_v,
                ext.handle,
            ),
        ),
        ("null_handle", (*base[:-1], 0)),
    ]
    rejected = []
    for name, args in bad:
        try:
            op(*args, torch.cuda.current_stream().cuda_stream)
        except RuntimeError:
            rejected.append(name)
        else:
            raise AssertionError("missing host validation: " + name)
    p.locations[0] = -1
    try:
        ext.bind(p)
    except ValueError:
        rejected.append("prebind_index_bounds")
    else:
        raise AssertionError("missing bounds validation")
    p.locations[0] = p.physical[32]
    if p.locations.numel() > 1:
        p.locations[1] = p.locations[0]
        try:
            ext.bind(p)
        except ValueError:
            rejected.append("prebind_duplicate")
        else:
            raise AssertionError("missing duplicate validation")
    return {
        "records": records,
        "host_rejected": rejected,
        "bitwise_KV_write_verified": True,
        "reference": "independent GPU FP64 decode plus exact cache comparison",
    }


def profile_fusion(output, fn, graphs, iterations):
    from torch.profiler import profile, ProfilerActivity, record_function

    with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as prof:
        for label, f in fn.items():
            with record_function("fusion/" + label):
                for _ in range(3):
                    f()
                torch.cuda.synchronize()
        for label, g in graphs.items():
            if label.startswith("backend"):
                with record_function("fusion/graph_" + label):
                    g.replay()
                    torch.cuda.synchronize()
    prof.export_chrome_trace(str(output / "timeline.json"))
    trace = json.loads((output / "timeline.json").read_text())
    kernels = [e for e in trace["traceEvents"] if e.get("cat") == "kernel"]
    rows = []
    expected = {
        "write_original": 6,
        "write_fused": 3,
        "backend_original": 12,
        "backend_fused": 9,
        "graph_backend_original": 4 * iterations,
        "graph_backend_fused": 3 * iterations,
    }
    for e in trace["traceEvents"]:
        if e.get("cat") != "user_annotation" or not e["name"].startswith("fusion/"):
            continue
        label = e["name"][len("fusion/") :]
        observed = [
            k
            for k in kernels
            if e["ts"] <= k["ts"] and k["ts"] + k.get("dur", 0) <= e["ts"] + e["dur"]
        ]
        if len(observed) != expected[label]:
            raise AssertionError(
                f"unexpected real kernel count {label}: {len(observed)}"
            )
        rows.append(
            {
                "region": label,
                "kernel_count": len(observed),
                "kernels": sorted({k["name"] for k in observed}),
            }
        )
    if len(rows) != 6:
        raise AssertionError("missing trace regions")
    return {"regions": rows, "hardware_counters": None, "not_Engine_graph": True}


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--output", type=Path, required=True)
    a.add_argument("--source-lock", type=Path, required=True)
    a.add_argument("--seed", type=int, default=20261113)
    a.add_argument("--profile", action="store_true")
    args = a.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source_lock = json.loads(args.source_lock.read_text())
    verify_sources(source_lock)
    torch.set_grad_enabled(False)
    torch.cuda.set_device(0)
    if torch.cuda.mem_get_info()[0] < 1024**3:
        raise RuntimeError("less than 1GiB free")
    torch.cuda.set_per_process_memory_fraction(0.2)
    torch.backends.cuda.matmul.allow_tf32 = False
    t = time.perf_counter()
    ext = FusedKV("/tmp/maas-10-gpu-9bf1ab626448/aten-kv-build")
    report = {
        "evidence": "local_fused_KV_hook_in_original_SGLang_backend_tensor_harness",
        "seed": args.seed,
        "sglang": "0.5.2",
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "compiler": "g++ ATen host + NVRTC device; NOT nvcc",
        "cpp_abi": torch._C._GLIBCXX_USE_CXX11_ABI,
        "extension_sha256": hashlib.sha256(Path(ext.library).read_bytes()).hexdigest(),
        "harness_sources": {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in (
                "run_kv_fusion.py",
                "run_decode.py",
                "decode_path.py",
                "kv_extension.py",
            )
        },
        "sources": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(__file__).parent.glob("kv_*")
            if p.is_file()
        },
        "library": ext.library,
        "telemetry_before": telemetry(),
        "experimental_factor": "replace ONLY two ATen KV index writes by one bitwise copy kernel",
        "decode_cap": 8,
        "Engine_initialized": False,
        "model_weights_used": False,
        "serving": False,
        "inference_only": True,
        "binding": "fixed immutable unique locations prevalidated outside timing",
    }
    report["correctness"] = correctness(ext, args.seed)
    report["build_and_correctness_s"] = time.perf_counter() - t
    save(args.output / "correctness.json", report["correctness"])
    print("fused KV GPU correctness passed", flush=True)
    matrix = []
    last = None
    iterations = 30
    rounds = 7
    with (args.output / "samples.jsonl").open("x") as log:
        for cell, lengths in CELLS:
            p = DecodePath(lengths, seed=args.seed)
            fn, original, fused = functions(p, ext)
            p.pool.set_kv_buffer = original
            p.check()
            p.pool.set_kv_buffer = fused
            p.check()
            graphs = {label: capture(f, iterations) for label, f in fn.items()}
            samples = {label: [] for label in fn}
            order_log = []
            rng = random.Random(args.seed)
            for round_id in range(rounds):
                # Pair write scopes and backend scopes, alternate which variant first.
                order = ["original", "fused"]
                rng.shuffle(order)
                order_log.append(order)
                for suffix in order:
                    for scope in ("write", "backend"):
                        label = scope + "_" + suffix
                        item = graph_sample(graphs[label], iterations)
                        samples[label].append(item)
                        log.write(
                            json.dumps(
                                {
                                    "cell": cell,
                                    "round": round_id,
                                    "label": label,
                                    **item,
                                }
                            )
                            + "\n"
                        )
                        log.flush()
            eager = {label: eager_sample(f) for label, f in fn.items()}
            row = {
                "cell": cell,
                "metadata": p.metadata(),
                "round_order": order_log,
                "graph_samples": samples,
                "graph_us": {
                    label: summarize([x["event_us_per_call"] for x in values])
                    for label, values in samples.items()
                },
                "eager": eager,
                "telemetry_after": telemetry(),
            }
            matrix.append(row)
            print(
                json.dumps(
                    {
                        "cell": cell,
                        "graph_us": {
                            k: v["median"] for k, v in row["graph_us"].items()
                        },
                    }
                ),
                flush=True,
            )
            last = (p, fn, graphs, original)
    report["measurements"] = matrix
    report["iterations"] = iterations
    report["rounds"] = rounds
    if args.profile:
        report["profile"] = profile_fusion(args.output, last[1], last[2], iterations)
    report["peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
    report["telemetry_after"] = telemetry()
    report["engine_speedup_claim"] = False
    report["caveats"] = [
        "local pool method hook only; no ModelRunner/scheduler/model generation integration",
        "manual torch graphs, not SGLang CudaGraphRunner; same default no-alt-stream KV branch",
        "no arbitrary live request indices: immutable prevalidated tensor binding",
        "samples within one process are not independent replications",
        "sampled CUPTI times excluded from performance comparison; shared desktop GPU",
        "compute-sanitizer not available; host validation is not device memcheck",
    ]
    report["correctness_status"] = "passed"
    save(args.output / "report.json", report)
    print(
        json.dumps(
            {
                "status": "passed",
                "fused_backend_integrated_in_harness": True,
                "Engine": False,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
