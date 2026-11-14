"""CPU RoPE/RMSNorm and explicit symmetric groupwise W8 reference."""

import numpy as np


def _finite(x):
    x = np.asarray(x, dtype=np.float64)
    if not np.isfinite(x).all():
        raise ValueError("finite")
    return x


def rms_residual(x, residual, weight, epsilon):
    x, residual, weight = map(_finite, (x, residual, weight))
    if (
        x.ndim < 1
        or x.shape[-1] == 0
        or x.shape != residual.shape
        or weight.shape != (x.shape[-1],)
    ):
        raise ValueError("shape")
    if not np.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("epsilon")
    r = x + residual
    y = r / np.sqrt(np.mean(r * r, axis=-1, keepdims=True) + epsilon) * weight
    return _finite(r), _finite(y)


def rope(x, positions, base=10000.0, inverse=False):
    x = _finite(x)
    positions = _finite(positions)
    if (
        x.ndim != 2
        or x.shape[1] % 2
        or positions.shape != (x.shape[0],)
        or not np.isfinite(base)
        or base <= 1
    ):
        raise ValueError("RoPE shape/base")
    frequency = base ** (-np.arange(0, x.shape[1], 2, dtype=np.float64) / x.shape[1])
    angle = positions[:, None] * frequency[None, :] * (-1 if inverse else 1)
    c, s = np.cos(angle), np.sin(angle)
    even, odd = x[:, 0::2], x[:, 1::2]
    y = np.empty_like(x)
    y[:, 0::2] = even * c - odd * s
    y[:, 1::2] = even * s + odd * c
    return _finite(y)


def quantize_w8(weight, group_size):
    w = _finite(weight)
    if (
        w.ndim != 2
        or min(w.shape) <= 0
        or type(group_size) is not int
        or group_size <= 0
    ):
        raise ValueError("group")
    k, n = w.shape
    groups = (k + group_size - 1) // group_size
    q = np.empty(w.shape, dtype=np.int8)
    scales = np.empty((groups, n), dtype=np.float32)
    for g in range(groups):
        sl = slice(g * group_size, min((g + 1) * group_size, k))
        part = w[sl]
        amax = np.max(np.abs(part), axis=0)
        scale = np.where(amax == 0, 1.0, amax / 127).astype(np.float32)
        if not np.isfinite(scale).all() or (scale <= 0).any():
            raise ValueError("FP32 scale range")
        scales[g] = scale
        q[sl] = np.clip(np.rint(part / scale.astype(np.float64)), -127, 127).astype(
            np.int8
        )
    return q, scales


def dequantize_w8(q, scales, group_size):
    q = np.asarray(q)
    scales = _finite(scales)
    if (
        q.ndim != 2
        or q.dtype != np.int8
        or type(group_size) is not int
        or group_size <= 0
    ):
        raise ValueError("quant format")
    if (
        (q == -128).any()
        or scales.shape != ((q.shape[0] + group_size - 1) // group_size, q.shape[1])
        or (scales <= 0).any()
    ):
        raise ValueError("scale/format")
    return q.astype(np.float64) * scales[np.arange(q.shape[0]) // group_size]


def demo():
    rng = np.random.default_rng(19)
    x = rng.normal(size=(7, 8))
    positions = np.arange(13, 20)
    rotated = rope(x, positions)
    restored = rope(rotated, positions, inverse=True)
    r, y = rms_residual(x, np.ones_like(x), np.ones(8), 1e-6)
    w = rng.normal(size=(8, 5))
    q, s = quantize_w8(w, 3)
    wd = dequantize_w8(q, s, 3)
    measured = np.abs(x @ wd - x @ w)
    # Triangle inequality uses actual dequant error (including stored-scale rounding).
    bound = np.sum(np.abs(x), axis=1)[:, None] * np.max(np.abs(wd - w), axis=0)[None, :]
    return {
        "rope_roundtrip_max_error": float(np.max(np.abs(restored - x))),
        "rms_both_outputs_shapes": [list(r.shape), list(y.shape)],
        "weight_error_max": float(np.max(np.abs(wd - w))),
        "gemm_error_max": float(measured.max()),
        "triangle_bound_holds": bool(np.all(measured <= bound + 1e-12)),
        "weight_storage_bytes": q.nbytes + s.nbytes,
        "fp16_weight_bytes_for_comparison": w.size * 2,
        "model_quality_evaluated": False,
        "no_integer_gpu_matmul": True,
    }
