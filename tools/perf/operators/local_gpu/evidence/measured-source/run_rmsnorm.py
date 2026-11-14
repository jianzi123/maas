"""Bounded real-GPU correctness, event timing and CUPTI timeline collection."""
import argparse
import hashlib
import importlib.metadata as md
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time
import warnings

import torch
from rmsnorm import bind, module, rmsnorm


def reference(x, w):
    d = x.detach().cpu().double()
    return (d * torch.rsqrt(d.square().mean(-1, keepdim=True) + 1e-5)
            * w.detach().cpu().double()).to(dtype=x.dtype, device=x.device)


def check_output(out, expected):
    if not torch.isfinite(out).all():
        raise AssertionError("nonfinite output: no successful timing report allowed")
    tolerance = 2e-3 if out.dtype == torch.float16 else 2e-5
    torch.testing.assert_close(out, expected, rtol=tolerance, atol=tolerance)
    return (out - expected).abs().max().item() if out.numel() else 0.0


def correctness(variants, mature=None):
    records = []
    for rows, width in ((0, 17), (1, 1), (1, 17), (3, 31), (7, 33),
                        (4, 127), (3, 129), (8, 257), (4, 1024), (5, 4097), (2, 8192)):
        for data in ("random", "zero", "small", "large"):
            x = torch.randn(rows, width, device="cuda")
            if data == "zero": x.zero_()
            if data == "small": x.mul_(1e-5 if x.dtype == torch.float16 else 1e-12)
            if data == "large": x.mul_(1e3 if x.dtype == torch.float16 else 1e8)
            w = torch.randn(width, device="cuda")
            expected = reference(x, w)
            for variant in variants:
                out = rmsnorm(x, w, variant=variant)
                records.append(dict(shape=[rows, width], data=data, variant=variant,
                                    max_abs=check_output(out, expected)))
            check_output(torch.nn.functional.rms_norm(x, (width,), w, eps=1e-5), expected)
            if mature and rows:
                records.append(dict(shape=[rows, width], data=data, variant="sgl_kernel",
                                    max_abs=check_output(mature(x, w, 1e-5), expected)))
    x = torch.randn(3, 33, device="cuda")
    w = torch.ones(33, device="cuda")
    negative = []
    for name, args in (
        ("layout", (x.t(), torch.ones(3, device="cuda"), 1e-5, "serial")),
        ("dtype", (x.bfloat16(), w.bfloat16(), 1e-5, "serial")),
        ("shape", (x, w[:2], 1e-5, "serial")),
        ("eps_nan", (x, w, float("nan"), "serial")),
        ("eps_zero", (x, w, 0., "serial")),
        ("grad", (x.clone().requires_grad_(), w, 1e-5, "serial")),
        ("variant", (x, w, 1e-5, "bogus")),
    ):
        try:
            rmsnorm(*args)
        except ValueError:
            negative.append(name)
        else:
            raise AssertionError(f"missing rejection: {name}")
    # IEEE exceptional inputs propagate; the benchmark gate must still reject.
    for value in (float("nan"), float("inf"), -float("inf")):
        for variant in variants:
            special = x.clone()
            special[0, 0] = value
            out = rmsnorm(special, w, variant=variant)
            try:
                check_output(out, reference(special, w))
            except AssertionError:
                negative.append(f"nonfinite_gate:{value}:{variant}")
            else:
                raise AssertionError("nonfinite gate failed")
    # Nondefault stream and registration checks are part of GPU correctness.
    stream = torch.cuda.Stream()
    with torch.cuda.stream(stream):
        for variant in variants:
            q = torch.randn(5, 129, device="cuda")
            v = torch.randn(129, device="cuda")
            check_output(rmsnorm(q, v, variant=variant), reference(q, v))
    stream.synchronize()
    opcheck = torch.library.opcheck(rmsnorm, (x, w, 1e-5, "serial"),
                                   test_utils=("test_schema", "test_faketensor"))
    return dict(cases=records, rejections=negative, opcheck=opcheck,
                nondefault_stream="passed", fp64_cpu_oracle=True)


def measure(fn, repeats=5, iterations=100):
    for _ in range(20): fn()
    torch.cuda.synchronize()
    # Captured raw kernel sequence excludes Python launch gaps. Allocations and
    # zero-copy binding are outside timing; this is not user dispatch latency.
    graph = torch.cuda.CUDAGraph()
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message="The CUDA Graph is empty.*")
        with torch.cuda.graph(graph):
            for _ in range(iterations): fn()
    graph.replay()
    torch.cuda.synchronize()
    event_samples, wall_samples = [], []
    for _ in range(repeats):
        start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
        start.record()
        graph.replay()
        end.record()
        end.synchronize()
        event_samples.append(start.elapsed_time(end) * 1000 / iterations)
        t = time.perf_counter_ns()
        for _ in range(iterations): fn()
        torch.cuda.synchronize()
        wall_samples.append((time.perf_counter_ns() - t) / iterations / 1000)
    return dict(graph_event_us=event_samples, graph_event_median_us=statistics.median(event_samples),
                eager_raw_launch_wall_us=wall_samples,
                eager_raw_launch_wall_median_us=statistics.median(wall_samples))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", default=["serial"])
    parser.add_argument("--sgl-kernel", action="store_true")
    parser.add_argument("--dtype", choices=("float32", "float16"), default="float32")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if any((args.output / name).exists() for name in ("report.json", "timeline.json")):
        raise FileExistsError("use a fresh output directory; preserve prior evidence")
    torch.manual_seed(20261113)
    torch.set_grad_enabled(False)
    torch.set_default_dtype(getattr(torch, args.dtype))
    torch.cuda.set_device(0)
    free, total = torch.cuda.mem_get_info()
    if free < 512 * 1024**2:
        raise RuntimeError("less than 512MiB free; stop without reclaiming others' memory")
    torch.cuda.set_per_process_memory_fraction(.15)
    report = dict(evidence="real_local_gpu_operator", engine_speedup_claim=False,
                  python=platform.python_version(), torch=torch.__version__, cuda=torch.version.cuda,
                  cupy=md.version("cupy-cuda12x"), gpu=torch.cuda.get_device_name(),
                  capability=torch.cuda.get_device_capability(), memory_before=[free, total],
                  seed=20261113, dtype=args.dtype, layout="contiguous_row_major",
                  eps=1e-5, warmup=20, repeats=5, iterations=100,
                  clock_power="unlocked/shared desktop GPU", nvrtc_options=["--std=c++17", "--fmad=false"],
                  sources={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in Path(__file__).parent.glob("*.*") if p.suffix in (".cu", ".py")})
    t = time.perf_counter()
    mature = None
    if args.sgl_kernel:
        from sgl_kernel import rmsnorm as mature
        report["sgl_kernel"] = md.version("sgl-kernel")
    report["correctness"] = correctness(args.variants, mature)
    suffix = "_half" if args.dtype == "float16" else ""
    report["kernel_attributes"] = {v: module(0).get_function("rms_" + v + suffix).attributes for v in args.variants}
    report["compile_and_correctness_s"] = time.perf_counter() - t
    cells = []
    last = None
    for rows, width in ((1, 1024), (32, 1024), (256, 1024), (256, 4096)):
        x = torch.randn(rows, width, device="cuda")
        w = torch.randn(width, device="cuda")
        expected = reference(x, w)
        functions = {}
        keepalive = []
        for variant in args.variants:
            out = torch.empty_like(x)
            fn = bind(x, w, out, variant=variant)
            fn()
            check_output(out, expected)
            functions[variant] = fn
            keepalive.append(out)
        functions["torch_native"] = lambda: torch.nn.functional.rms_norm(x, (width,), w, eps=1e-5)
        if mature:
            functions["sgl_kernel"] = lambda: mature(x, w, 1e-5)
        # Frozen input, fixed order; raw samples retained, no statistical CI claim.
        for name, fn in functions.items():
            cells.append(dict(shape=[rows, width], implementation=name, **measure(fn)))
        last = (functions, keepalive)
    report["measurements"] = cells
    report["torch_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
    from torch.profiler import ProfilerActivity, profile, record_function
    with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as prof:
        for name, fn in last[0].items():
            with record_function("rmsnorm/" + name):
                for _ in range(3): fn()
        torch.cuda.synchronize()
    prof.export_chrome_trace(str(args.output / "timeline.json"))
    trace = json.loads((args.output / "timeline.json").read_text())
    report["actual_cuda_kernels"] = sorted({e["name"] for e in trace["traceEvents"]
                                             if e.get("cat") == "kernel"})
    for variant in args.variants:
        if "rms_" + variant + suffix not in report["actual_cuda_kernels"]:
            raise RuntimeError("requested CUDA kernel missing from actual CUPTI trace")
    kernels = [dict(name=e.key, count=e.count, device_time_total_us=e.device_time_total)
               for e in prof.key_averages() if e.device_time_total > 0]
    report["profile"] = kernels
    report["correctness_status"] = "passed"
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    print(json.dumps({"status": "passed", "measurements": [
        {k: cell[k] for k in ("shape", "implementation", "graph_event_median_us",
                              "eager_raw_launch_wall_median_us")} for cell in cells],
        "actual_cuda_kernels": report["actual_cuda_kernels"]}, indent=2))


if __name__ == "__main__":
    main()
