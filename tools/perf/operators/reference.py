"""NumPy float64 correctness oracles; no GPU/framework timing claims."""
import numpy as np


def gemm(a, b):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if a.ndim != 2 or b.ndim != 2 or a.shape[1] != b.shape[0]:
        raise ValueError("incompatible GEMM shapes")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("nonfinite input")
    return a @ b


def gemm_scalar(a, b):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if a.ndim != 2 or b.ndim != 2 or a.shape[1] != b.shape[0]:
        raise ValueError("incompatible GEMM shapes")
    return np.array([[sum(float(a[i, k]) * float(b[k, j]) for k in range(a.shape[1]))
                      for j in range(b.shape[1])] for i in range(a.shape[0])])


def grouped_gemm(pairs):
    return [gemm(a, b) for a, b in pairs]


def rmsnorm(x, weight, eps=1e-6):
    x, weight = np.asarray(x, dtype=np.float64), np.asarray(weight, dtype=np.float64)
    if x.ndim != 2 or min(x.shape) <= 0 or weight.shape != (x.shape[-1],) or not np.isfinite(eps) or eps <= 0:
        raise ValueError("invalid RMSNorm shape/epsilon")
    if not np.isfinite(x).all() or not np.isfinite(weight).all():
        raise ValueError("nonfinite input")
    return x / np.sqrt(np.mean(x * x, axis=-1, keepdims=True) + eps) * weight


def attention_inputs(q, k, v, causal=True, mask=None):
    q, k, v = [np.asarray(t, dtype=np.float64) for t in (q, k, v)]
    if any(t.ndim != 4 for t in (q, k, v)):
        raise ValueError("expected B,H,S,D")
    b, hq, sq, d = q.shape
    bk, hk, sk, dk = k.shape
    if min(b, hq, sq, d, hk, sk) <= 0 or bk != b or k.shape != v.shape or dk != d or hq % hk:
        raise ValueError("unsupported MHA/GQA shape")
    if causal and sq > sk:
        raise ValueError("causal query must be suffix of KV sequence")
    if not all(np.isfinite(t).all() for t in (q, k, v)):
        raise ValueError("nonfinite input")
    allowed = np.ones((sq, sk), dtype=bool)
    if causal:
        # Bottom-right alignment: decode Sq=1 may attend all cached keys.
        allowed &= np.arange(sk)[None, :] <= (sk - sq + np.arange(sq))[:, None]
    if mask is not None:
        mask = np.asarray(mask)
        if mask.dtype != np.bool_ or mask.shape != (sq, sk):
            raise ValueError("mask must be bool Sq,Sk")
        allowed &= mask
    repeat = hq // hk
    return q, np.repeat(k, repeat, axis=1), np.repeat(v, repeat, axis=1), allowed


def attention_dense(q, k, v, causal=True, mask=None):
    q, k, v, allowed = attention_inputs(q, k, v, causal, mask)
    scores = q @ k.swapaxes(-1, -2) / np.sqrt(q.shape[-1])
    scores = np.where(allowed, scores, -np.inf)
    peak = scores.max(axis=-1, keepdims=True)
    peak = np.where(np.isfinite(peak), peak, 0)
    weights = np.exp(scores - peak)
    denominator = weights.sum(axis=-1, keepdims=True)
    probabilities = np.divide(weights, denominator, out=np.zeros_like(weights), where=denominator != 0)
    return probabilities @ v


def attention_online(q, k, v, causal=True, mask=None, block=3):
    """Independent online-softmax oracle, not a claimed optimized kernel."""
    if type(block) is not int or block <= 0:
        raise ValueError("invalid KV block")
    q, k, v, allowed = attention_inputs(q, k, v, causal, mask)
    output = np.zeros_like(q)
    for bi in range(q.shape[0]):
        for hi in range(q.shape[1]):
            for qi in range(q.shape[2]):
                maximum, total = -np.inf, 0.0
                accumulator = np.zeros(q.shape[-1])
                for start in range(0, k.shape[2], block):
                    end = min(start + block, k.shape[2])
                    valid = allowed[qi, start:end]
                    if not valid.any():
                        continue
                    score = k[bi, hi, start:end] @ q[bi, hi, qi] / np.sqrt(q.shape[-1])
                    score = np.where(valid, score, -np.inf)
                    new_maximum = max(maximum, float(score.max()))
                    rescale = np.exp(maximum - new_maximum) if total else 0.0
                    weights = np.exp(score - new_maximum)
                    accumulator = accumulator * rescale + weights @ v[bi, hi, start:end]
                    total = total * rescale + float(weights.sum())
                    maximum = new_maximum
                if total:
                    output[bi, hi, qi] = accumulator / total
    return output


def error_metrics(actual, expected, atol, rtol):
    actual, expected = np.asarray(actual), np.asarray(expected)
    if actual.shape != expected.shape:
        raise ValueError("output shape mismatch")
    finite = bool(np.isfinite(actual).all() and np.isfinite(expected).all())
    absolute = np.abs(actual - expected)
    return {"passed": finite and bool(np.all(absolute <= atol + rtol * np.abs(expected))),
            "max_abs": float(absolute.max(initial=0)),
            "max_rel_floor_1e-12": float((absolute / np.maximum(np.abs(expected), 1e-12)).max(initial=0)),
            "atol": atol, "rtol": rtol}
