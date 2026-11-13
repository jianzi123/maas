#!/usr/bin/env python3
"""Operator lab: NumPy CPU correctness by default; GPU execution is approval-gated."""
import argparse
import importlib.util
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import reference as ref


def read_plan(path):
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("plan_version") != "operator-lab-1.0":
        raise ValueError("unsupported operator plan")
    return plan


def require_gpu_approval(plan):
    limits = plan.get("gpu_limits", {})
    if (plan.get("execution_enabled") is not True or
            not isinstance(plan.get("approval_ref"), str) or not plan["approval_ref"].strip() or
            not isinstance(plan.get("target_environment"), str) or not plan["target_environment"].strip() or
            type(limits.get("max_estimated_data_bytes")) is not int or not 0 < limits["max_estimated_data_bytes"] <= 2**30 or
            type(limits.get("warmup")) is not int or not 1 <= limits["warmup"] <= 100 or
            type(limits.get("samples")) is not int or not 1 <= limits["samples"] <= 100):
        raise ValueError("GPU execution disabled or approvals/limits incomplete")


def inputs(case):
    rng = np.random.default_rng(case["seed"])
    shape = case["shape"]
    def make(s):
        if case["layout"] == "strided":
            data = rng.normal(0, .25, size=tuple(s[:-1]) + (s[-1]*2,))[..., ::2]
        else:
            data = rng.normal(0, .25, size=s)
        return data.astype(np.float64, copy=False)
    if case["op"] == "gemm":
        return (make((shape["m"], shape["k"])), make((shape["k"], shape["n"])))
    if case["op"] == "rmsnorm":
        return (make((shape["rows"], shape["d"])), make((shape["d"],)))
    return (make((shape["b"], shape["hq"], shape["sq"], shape["d"])),
            make((shape["b"], shape["hkv"], shape["sk"], shape["d"])),
            make((shape["b"], shape["hkv"], shape["sk"], shape["d"])))


def expected(case, values):
    if case["op"] == "gemm":
        return ref.gemm(*values)
    if case["op"] == "rmsnorm":
        return ref.rmsnorm(*values)
    return ref.attention_dense(*values, causal=case["causal"])


def cpu_reference(plan):
    rows = []
    for case in plan["cases"]:
        if not case["cpu_reference"]:
            continue
        values = inputs(case)
        golden = expected(case, values)
        if case["op"] == "gemm":
            actual = ref.gemm_scalar(*values)
        elif case["op"].startswith("attention"):
            actual = ref.attention_online(*values, causal=case["causal"], block=3)
        else:
            x, weight = values
            actual = np.array([row * (1 / math.sqrt(sum(float(v*v) for v in row) / len(row) + 1e-6))
                               * weight for row in x])
        rows.append({"id": case["id"], "dtype_executed": "float64",
                     "comparison": "independent_cpu_formula_vs_numpy_reference",
                     **ref.error_metrics(actual, golden, 1e-11, 1e-10)})
    return {"evidence_level": "synthetic_numpy_cpu_correctness", "gpu_executed": False,
            "gpu_timings": None, "cpu_timings": None, "cases": rows,
            "all_passed": all(row["passed"] for row in rows),
            "note": "No model, GPU, framework performance or low-precision quality conclusion"}


def gpu_case(plan, case, backend, profile_directory=None, instrumented=False):
    require_gpu_approval(plan)  # always before importing torch or a CUDA candidate
    if (profile_directory is not None or instrumented) and plan["gpu_limits"]["samples"] < 4:
        raise ValueError("profiler's fixed 4-call window exceeds approved sample cap")
    import torch
    import torch.nn.functional as F
    if torch.version.cuda is None or not torch.cuda.is_available():
        raise ValueError("a compatible CUDA PyTorch build/device is required")
    if case["dtype"] not in ("float32", "float16", "bfloat16"):
        raise ValueError("unsupported dtype")
    if case["layout"] != "contiguous":
        raise ValueError("GPU starter only supports contiguous inputs; strided CPU oracle is separate")
    values = inputs(case)
    input_bytes = sum(v.size for v in values) * 8
    if case["op"].startswith("attention"):
        s = case["shape"]
        input_bytes += s["b"] * s["hq"] * s["sq"] * s["sk"] * 16
    if input_bytes > plan["gpu_limits"]["max_estimated_data_bytes"]:
        raise ValueError("estimated inputs/reference exceed approved memory")
    dtype = getattr(torch, case["dtype"])
    torch.backends.cuda.matmul.allow_tf32 = False
    tensors = [torch.as_tensor(v.copy(), device="cuda", dtype=dtype) for v in values]
    rounded = [t.to(device="cpu", dtype=torch.float64).numpy() for t in tensors]
    golden = expected(case, rounded)
    if case["op"] == "gemm":
        baseline = lambda: torch.mm(*tensors)
    elif case["op"] == "rmsnorm":
        baseline = lambda: F.rms_norm(tensors[0], (tensors[0].shape[-1],), tensors[1], 1e-6)
    else:
        _, _, _, mask = ref.attention_inputs(*rounded, causal=case["causal"])
        allowed = torch.as_tensor(mask, device="cuda", dtype=torch.bool)
        baseline = lambda: F.scaled_dot_product_attention(
            *tensors, attn_mask=allowed, dropout_p=0.0, is_causal=False,
            enable_gqa=case["shape"]["hq"] != case["shape"]["hkv"])
    if backend == "triton":
        if case["op"] != "rmsnorm":
            raise ValueError("Triton starter only implements RMSNorm")
        from triton_rmsnorm import rmsnorm
        candidate = lambda: rmsnorm(*tensors)
    else:
        candidate = baseline  # explicit harness control, never a novel optimization
    wall_start = time.perf_counter_ns()
    result = candidate()
    torch.cuda.synchronize()
    first_wall_ms = (time.perf_counter_ns() - wall_start) / 1e6
    atol, rtol = plan["tolerances"][case["dtype"]]
    correctness = ref.error_metrics(result.to(device="cpu", dtype=torch.float64).numpy(),
                                   golden, atol, rtol)
    if not correctness["passed"]:
        raise ValueError("candidate numerical check failed; no performance claim")
    for _ in range(plan["gpu_limits"]["warmup"]):
        baseline()
        candidate()
    torch.cuda.synchronize()
    shape = case["shape"]
    if case["op"] == "gemm":
        flops = 2 * shape["m"] * shape["n"] * shape["k"]
    elif case["op"].startswith("attention"):
        flops = 4 * shape["b"] * shape["hq"] * shape["sq"] * shape["sk"] * shape["d"]
    else:
        flops = None
    logical_bytes = (sum(t.numel() for t in tensors) + result.numel()) * result.element_size()
    metadata = {"logical_dense_flops_estimate": flops,
                "logical_io_bytes_estimate": logical_bytes,
                "io_is_not_measured_dram_traffic": True,
                "evidence_level": "approved_synthetic_gpu_operator",
                "case": case, "backend": backend,
                "comparison_role": "same_backend_control" if backend == "torch" else "candidate_vs_torch_native",
                "torch": torch.__version__, "cuda_build": torch.version.cuda,
                "device": torch.cuda.get_device_name(), "strides": [list(t.stride()) for t in tensors],
                "first_call_wall_ms": first_wall_ms, "correctness": correctness,
                "timings": None, "profiled_run": profile_directory is not None or instrumented}
    if instrumented:
        for _ in range(4):
            with torch.cuda.nvtx.range("maas_candidate"):
                candidate()
            torch.cuda.synchronize()
        metadata["note"] = "external profiler trace only; benchmark timings suppressed"
        return metadata
    if profile_directory is not None:
        directory = Path(profile_directory); directory.mkdir(parents=True, exist_ok=True)
        with torch.profiler.profile(
            activities=[torch.profiler.ProfilerActivity.CPU, torch.profiler.ProfilerActivity.CUDA],
            schedule=torch.profiler.schedule(wait=1, warmup=1, active=2, repeat=1),
            record_shapes=True, profile_memory=True,
            on_trace_ready=lambda p: p.export_chrome_trace(str(directory / "operator-trace.json"))
        ) as profiler:
            for _ in range(4):
                with torch.profiler.record_function("maas_candidate"):
                    candidate()
                torch.cuda.synchronize()
                profiler.step()
        return metadata  # no profiled time promoted to benchmark results
    timings = []
    torch.cuda.reset_peak_memory_stats()
    for sample in range(plan["gpu_limits"]["samples"]):
        order = (("baseline", baseline), ("candidate", candidate))
        if sample % 2:
            order = order[::-1]
        for label, fn in order:
            begin, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            torch.cuda.synchronize()
            started = time.perf_counter_ns()
            begin.record()
            with torch.cuda.nvtx.range("maas_candidate" if label == "candidate" else "maas_baseline"):
                output = fn()
            end.record()
            end.synchronize()
            timings.append({"sample": sample, "label": label,
                            "device_event_ms": begin.elapsed_time(end),
                            "host_wall_with_sync_ms": (time.perf_counter_ns()-started)/1e6})
            del output
    metadata.update(timings=timings, allocator_peak_bytes=torch.cuda.max_memory_allocated(),
                    note="operator timing only; not client TTFT/TPOT or SGLang/model speedup")
    return metadata


class SafeParser(argparse.ArgumentParser):
    def error(self, _):
        print("invalid operator arguments; values not echoed", file=sys.stderr)
        raise SystemExit(2)


def main():
    parser = SafeParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path(__file__).with_name("plan.json"))
    parser.add_argument("--mode", choices=["cpu-reference", "gpu"], default="cpu-reference")
    parser.add_argument("--case", default="gemm-tail")
    parser.add_argument("--backend", choices=["torch", "triton"], default="torch")
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument("--instrumented", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = read_plan(args.plan)
        if args.mode == "cpu-reference":
            report = cpu_reference(plan)
        else:
            require_gpu_approval(plan)
            case = next(v for v in plan["cases"] if v["id"] == args.case)
            report = gpu_case(plan, case, args.backend, args.profile_dir, args.instrumented)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n",
                               encoding="utf-8", newline="\n")
    except (ValueError, OSError, StopIteration, ImportError, RuntimeError):
        print("operator run rejected/unsupported; no new result or raw input echoed", file=sys.stderr)
        return 2
    print("CPU reference report written" if args.mode == "cpu-reference" else "approved GPU operator report written")
    return 1 if args.mode == "cpu-reference" and not report["all_passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
