"""Optional Triton RMSNorm learning candidate, not tuned or GPU-validated here."""
import torch
import triton
import triton.language as tl


@triton.jit
def _rmsnorm(X, W, Y, D: tl.constexpr, EPS: tl.constexpr, BLOCK: tl.constexpr):
    row = tl.program_id(0)
    offsets = tl.arange(0, BLOCK)
    x = tl.load(X + row * D + offsets, offsets < D, other=0).to(tl.float32)
    w = tl.load(W + offsets, offsets < D, other=0).to(tl.float32)
    inv = tl.rsqrt(tl.sum(x * x, 0) / D + EPS)
    tl.store(Y + row * D + offsets, x * inv * w, offsets < D)


def rmsnorm(x, weight, eps=1e-6):
    if not x.is_cuda or not weight.is_cuda or x.device != weight.device or not x.is_contiguous() or not weight.is_contiguous() or eps <= 0:
        raise ValueError("Triton starter requires contiguous CUDA tensors")
    if x.ndim != 2 or weight.shape != (x.shape[-1],) or not 1 <= x.shape[-1] <= 8192:
        raise ValueError("unsupported RMSNorm shape")
    output = torch.empty_like(x)
    _rmsnorm[(x.shape[0],)](x, weight, output, x.shape[-1], eps,
                           triton.next_power_of_2(x.shape[-1]))
    return output
