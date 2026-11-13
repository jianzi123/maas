"""Compare current SGLang double write, packaged mature fusion, teaching prototype."""

import argparse, hashlib, importlib.metadata as md, json, random, time
from pathlib import Path
import torch, sgl_kernel
from decode_path import DecodePath
from kv_extension import FusedKV
from run_decode import (
    CELLS,
    capture,
    graph_sample,
    save,
    summarize,
    telemetry,
    verify_sources,
)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--output", type=Path, required=True)
    a.add_argument("--source-lock", type=Path, required=True)
    a.add_argument("--seed", type=int, required=True)
    a.add_argument("--profile", action="store_true")
    args = a.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    verify_sources(json.loads(args.source_lock.read_text()))
    torch.set_grad_enabled(False)
    torch.cuda.set_device(0)
    if torch.cuda.mem_get_info()[0] < 1024**3:
        raise RuntimeError("less than 1GiB free")
    torch.cuda.set_per_process_memory_fraction(0.2)
    ext = FusedKV("/tmp/maas-10-gpu-9bf1ab626448/aten-kv-build")
    package = md.distribution("sgl-kernel")
    memory = Path(package.locate_file("sgl_kernel/memory.py"))
    report = {
        "evidence": "actual_GPU_mature_KV_control_in_SGLang_tensor_path",
        "seed": args.seed,
        "sgl_kernel": package.version,
        "sglang": md.version("sglang"),
        "torch": torch.__version__,
        "mature_API": "torch.ops.sgl_kernel.store_kv_cache (direct, no fallback wrapper)",
        "memory_wrapper_sha256": hashlib.sha256(memory.read_bytes()).hexdigest(),
        "installed_binary_provenance": "packaged wheel/version, NOT claimed as SGLang b0d25e7 source",
        "sources": {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in (
                "run_mature_kv.py",
                "run_decode.py",
                "decode_path.py",
                "kv_extension.py",
                "kv_aten.cpp",
                "kv_fused.cu",
            )
        },
        "Engine": False,
        "model_or_serving": False,
        "telemetry_before": telemetry(),
        "rounds": 7,
        "iterations": 30,
    }

    def writers(p):
        original = p.pool.set_kv_buffer

        def mature(layer, loc, k, v):
            if layer.layer_id != 0:
                raise ValueError("one-layer harness")
            # The Python convenience wrapper catches RuntimeError and falls back to
            # index_put. Use the raw op and fail instead of hiding unsupported cases.
            return torch.ops.sgl_kernel.store_kv_cache(
                p.pool.get_key_buffer(0), p.pool.get_value_buffer(0), loc, k, v
            )

        return {"original": original, "mature": mature, "prototype": ext.bind(p)}

    checks = []
    unsupported = []
    for dtype in (torch.float16, torch.bfloat16):
        for lengths, d in (([1], 64), ([17, 33], 80), ([33, 129, 257], 128)):
            p = DecodePath(lengths, dim=d, dtype=dtype, seed=args.seed)
            p.pool.set_kv_buffer = writers(p)["mature"]
            try:
                checked = p.check()
            except RuntimeError as exc:
                if d != 80 or "must be divisible by 128" not in str(exc):
                    raise
                unsupported.append(
                    {
                        "dtype": str(dtype),
                        "dim": d,
                        "error": str(exc),
                        "fallback_used": False,
                        "performance_result": None,
                    }
                )
            else:
                checks.append({"dtype": str(dtype), "dim": d, "check": checked})
    stream = torch.cuda.Stream()
    with torch.cuda.stream(stream):
        p = DecodePath([33, 129], seed=args.seed)
        p.pool.set_kv_buffer = writers(p)["mature"]
        checks.append({"nondefault_stream": True, "check": p.check()})
    stream.synchronize()
    report["mature_correctness"] = checks
    report["mature_unsupported"] = unsupported
    print("mature GPU correctness passed", flush=True)
    matrix = []
    last = None
    with (args.output / "samples.jsonl").open("x") as log:
        for cell, lengths in CELLS:
            p = DecodePath(lengths, seed=args.seed)
            ws = writers(p)
            functions = {}
            held = {}
            for name, writer in ws.items():
                p.pool.set_kv_buffer = writer
                p.check()
                functions["write_" + name] = lambda w=writer: w(
                    p.layer, p.locations, p.new_k, p.new_v
                )

                def forward(w=writer, n=name):
                    p.pool.set_kv_buffer = w
                    result = p.forward()
                    held[n] = result
                    return result

                functions["backend_" + name] = forward
            graphs = {name: capture(fn, 30) for name, fn in functions.items()}
            captured_outputs = dict(held)
            data = {name: [] for name in functions}
            order_log = []
            rng = random.Random(args.seed)
            for round_id in range(7):
                order = list(ws)
                rng.shuffle(order)
                order_log.append(order)
                for name in order:
                    for scope in ("write", "backend"):
                        label = scope + "_" + name
                        value = graph_sample(graphs[label], 30)
                        data[label].append(value)
                        log.write(
                            json.dumps(
                                {
                                    "cell": cell,
                                    "round": round_id,
                                    "label": label,
                                    **value,
                                }
                            )
                            + "\n"
                        )
                        log.flush()
            # Gate actual captured outputs, not only pre-capture eager correctness.
            ref = p.reference()
            from decode_path import check_finite_close

            for name, out in captured_outputs.items():
                check_finite_close(out.reshape_as(ref), ref, 3e-3)
            row = {
                "cell": cell,
                "metadata": p.metadata(),
                "round_order": order_log,
                "samples": data,
                "graph_us": {
                    name: summarize([x["event_us_per_call"] for x in values])
                    for name, values in data.items()
                },
                "captured_outputs_finite_close": True,
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
            last = (p, functions, graphs, captured_outputs)
    report["measurements"] = matrix
    if args.profile:
        from torch.profiler import profile, ProfilerActivity, record_function

        p, fn, graphs, outs = last
        with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as prof:
            for name in (
                "write_original",
                "write_mature",
                "write_prototype",
                "backend_original",
                "backend_mature",
                "backend_prototype",
            ):
                with record_function("mature_control/" + name):
                    for _ in range(3):
                        fn[name]()
                    torch.cuda.synchronize()
        prof.export_chrome_trace(str(args.output / "timeline.json"))
        trace = json.loads((args.output / "timeline.json").read_text())
        kernels = [x for x in trace["traceEvents"] if x.get("cat") == "kernel"]
        regions = []
        for event in trace["traceEvents"]:
            if event.get("cat") != "user_annotation" or not event["name"].startswith(
                "mature_control/"
            ):
                continue
            label = event["name"].split("/", 1)[1]
            observed = [
                x
                for x in kernels
                if event["ts"] <= x["ts"]
                and x["ts"] + x.get("dur", 0) <= event["ts"] + event["dur"]
            ]
            expected = (
                (2 if label == "write_original" else 1)
                if label.startswith("write")
                else (4 if label == "backend_original" else 3)
            )
            if len(observed) != 3 * expected:
                raise AssertionError("unexpected actual mature-control kernel count")
            regions.append(
                {
                    "region": label,
                    "kernels": sorted({x["name"] for x in observed}),
                    "count": len(observed),
                }
            )
        if len(regions) != 6:
            raise AssertionError("missing mature trace")
        report["profile"] = {
            "regions": regions,
            "durations_not_used_in_A_B": True,
            "silent_fallback_used": False,
        }
    report["telemetry_after"] = telemetry()
    report["correctness_status"] = "passed"
    report["Engine_speedup_claim"] = False
    report["caveats"] = [
        "captured-output gate included here; first two studies retained separately",
        "shared desktop/unlocked clocks, three processes requested separately",
        "mature op is raw store_kv_cache; no RuntimeError fallback allowed",
        "manual graph and static validated positions, not Engine capture/stream lifecycle",
        "prototype not adopted without superiority over packaged mature kernel",
    ]
    save(args.output / "report.json", report)
    print(
        json.dumps(
            {"status": "passed", "mature_direct_op_verified": True, "Engine": False}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
