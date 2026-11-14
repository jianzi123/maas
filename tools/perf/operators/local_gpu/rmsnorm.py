"""NVRTC CUDA C++ -> driver JIT -> PyTorch operator; inference FP32/FP16 lab.

No host extension/nvcc is required. CuPy owns compilation, PyTorch owns tensor
storage and stream lifetime. This is a standalone operator, not an engine patch.
"""
import functools
import math
from pathlib import Path

import cupy as cp
import numpy as np
import torch


@functools.lru_cache(maxsize=8)
def module(device):
    with cp.cuda.Device(device):
        compiled = cp.RawModule(code=Path(__file__).with_suffix(".cu").read_text(),
                                backend="nvrtc", options=("--std=c++17", "--fmad=false"))
        compiled.compile()
        return compiled


def validate(x, weight, eps, variant):
    if (x.device.type != "cuda" or weight.device != x.device or
            x.dtype not in (torch.float32, torch.float16) or weight.dtype != x.dtype):
        raise ValueError("same-device CUDA FP32/FP16 required")
    if x.ndim != 2 or weight.ndim != 1 or x.shape[1] != weight.numel():
        raise ValueError("expected x[rows,width], weight[width]")
    if not x.is_contiguous() or not weight.is_contiguous():
        raise ValueError("contiguous layout required")
    if x.requires_grad or weight.requires_grad:
        raise ValueError("inference only; gradients unsupported")
    if (not math.isfinite(eps) or eps <= 0 or not 1 <= x.shape[1] <= 8192
            or x.numel() > 1048576):
        raise ValueError("positive finite eps, width <=8192, elements <=1048576 required")
    if variant not in ("serial", "block"):
        raise ValueError("unknown variant")


def bind(x, weight, out, eps=1e-5, variant="serial"):
    """Bind zero-copy views once, for raw-launch timing; caller retains tensors."""
    validate(x, weight, eps, variant)
    if out.shape != x.shape or out.dtype != x.dtype or out.device != x.device or not out.is_contiguous():
        raise ValueError("output metadata mismatch")
    device = x.device.index
    stream = cp.cuda.ExternalStream(torch.cuda.current_stream(device).cuda_stream)
    with cp.cuda.Device(device), stream:
        args = (cp.from_dlpack(x), cp.from_dlpack(weight), cp.from_dlpack(out),
                np.int32(x.shape[0]), np.int32(x.shape[1]), np.float32(eps))
        suffix = "_half" if x.dtype == torch.float16 else ""
        kernel = module(device).get_function("rms_" + variant + suffix)
    grid, block = (((x.shape[0] + 63) // 64,), (64,)) if variant == "serial" else ((x.shape[0],), (256,))

    def launch():
        if x.shape[0]:
            # Resolve at invocation: graph capture switches PyTorch to its own
            # stream. Reusing the binding stream silently creates an empty graph.
            current = cp.cuda.ExternalStream(torch.cuda.current_stream(device).cuda_stream)
            with cp.cuda.Device(device), current:
                kernel(grid, block, args)
    return launch


@torch.library.custom_op("maas_local::rmsnorm", mutates_args=(), device_types="cuda")
def rmsnorm(x: torch.Tensor, weight: torch.Tensor, eps: float = 1e-5,
            variant: str = "serial") -> torch.Tensor:
    validate(x, weight, eps, variant)
    out = torch.empty_like(x)
    bind(x, weight, out, eps, variant)()
    return out


@rmsnorm.register_fake
def _(x, weight, eps=1e-5, variant="serial"):
    return torch.empty_like(x)
