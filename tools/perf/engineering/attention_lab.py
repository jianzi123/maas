"""CPU implementations of online-softmax attention; not a GPU backend."""

from dataclasses import dataclass
import math
import numpy as np


@dataclass
class State:
    maximum: float
    denominator: float
    numerator: np.ndarray


def empty_state(d):
    return State(-math.inf, 0.0, np.zeros(d, dtype=np.float64))


def block_state(scores, values, allowed):
    scores = np.asarray(scores, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    allowed = np.asarray(allowed, dtype=bool)
    if (
        scores.ndim != 1
        or values.ndim != 2
        or len(scores) != len(values)
        or allowed.shape != scores.shape
    ):
        raise ValueError("block shape")
    if not np.isfinite(scores).all() or not np.isfinite(values).all():
        raise ValueError("finite inputs required")
    if not allowed.any():
        return empty_state(values.shape[1])
    chosen = scores[allowed]
    m = float(chosen.max())
    p = np.exp(chosen - m)
    return State(m, float(p.sum()), p @ values[allowed])


def merge(a, b):
    if a.numerator.shape != b.numerator.shape:
        raise ValueError("state dimensions")
    if a.denominator == 0:
        return State(b.maximum, b.denominator, b.numerator.copy())
    if b.denominator == 0:
        return State(a.maximum, a.denominator, a.numerator.copy())
    m = max(a.maximum, b.maximum)
    wa, wb = math.exp(a.maximum - m), math.exp(b.maximum - m)
    return State(
        m, wa * a.denominator + wb * b.denominator, wa * a.numerator + wb * b.numerator
    )


def finish(state):
    if state.denominator == 0:
        return np.zeros_like(state.numerator)
    result = state.numerator / state.denominator
    if not np.isfinite(result).all():
        raise ValueError("nonfinite result")
    return result


def _validate(q, k, v, mask):
    q, k, v = map(lambda x: np.asarray(x, dtype=np.float64), (q, k, v))
    if q.ndim != 3 or k.ndim != 3 or v.shape != k.shape:
        raise ValueError("use [head,position,dim]; K and V same shape")
    hq, sq, d = q.shape
    hk, sk, dk = k.shape
    if min(hq, hk, d) <= 0 or d != dk or hq % hk:
        raise ValueError("GQA dimensions")
    if np.shape(mask) != (sq, sk):
        raise ValueError("mask shape")
    if not all(np.isfinite(x).all() for x in (q, k, v)):
        raise ValueError("finite inputs")
    return q, k, v, np.asarray(mask, dtype=bool)


def dense(q, k, v, mask):
    q, k, v, mask = _validate(q, k, v, mask)
    out = np.zeros_like(q)
    # Independent full-matrix oracle. All-masked rows explicitly stay zero.
    for h in range(q.shape[0]):
        kh = h // (q.shape[0] // k.shape[0])
        scores = q[h] @ k[kh].T / math.sqrt(q.shape[-1])
        if not np.isfinite(scores).all():
            raise ValueError("score overflow")
        for row in range(q.shape[1]):
            take = mask[row]
            if take.any():
                s = scores[row, take]
                p = np.exp(s - s.max())
                p /= p.sum()
                out[h, row] = p @ v[kh, take]
    if not np.isfinite(out).all():
        raise ValueError("nonfinite result")
    return out


def streaming(q, k, v, mask, block=3):
    if not isinstance(block, int) or isinstance(block, bool) or block <= 0:
        raise ValueError("positive block")
    q, k, v, mask = _validate(q, k, v, mask)
    out = np.zeros_like(q)
    for h in range(q.shape[0]):
        kh = h // (q.shape[0] // k.shape[0])
        for row in range(q.shape[1]):
            state = empty_state(q.shape[-1])
            for begin in range(0, k.shape[1], block):
                end = min(begin + block, k.shape[1])
                scores = k[kh, begin:end] @ q[h, row] / math.sqrt(q.shape[-1])
                if not np.isfinite(scores).all():
                    raise ValueError("score overflow")
                state = merge(
                    state, block_state(scores, v[kh, begin:end], mask[row, begin:end])
                )
            out[h, row] = finish(state)
    return out


def suffix_mask(sq, sk):
    if sq < 0 or sk < sq:
        raise ValueError("suffix requires 0<=Sq<=Sk")
    return np.arange(sk)[None, :] <= (sk - sq + np.arange(sq))[:, None]


def gather_pages(storage, page_table, length):
    """Storage [physical_page,head,token_in_page,dim]; verify table before gather."""
    x = np.asarray(storage)
    if x.ndim != 4 or length < 0:
        raise ValueError("page shape/length")
    needed = (length + x.shape[2] - 1) // x.shape[2]
    if len(page_table) < needed:
        raise ValueError("short table")
    table = page_table[:needed]
    if any(type(p) is not int or p < 0 or p >= len(x) for p in table):
        raise ValueError("bad page")
    if not needed:
        return np.empty((x.shape[1], 0, x.shape[3]), dtype=x.dtype)
    return np.concatenate([x[p] for p in table], axis=1)[:, :length, :]


def demo():
    rng = np.random.default_rng(20261106)
    q = rng.normal(size=(4, 3, 5))
    k = rng.normal(size=(2, 11, 5))
    v = rng.normal(size=k.shape)
    mask = suffix_mask(3, 11)
    mask[0] = False
    expected = dense(q, k, v, mask)
    errors = {
        str(b): float(np.max(np.abs(streaming(q, k, v, mask, b) - expected)))
        for b in (1, 2, 4, 16)
    }
    state = merge(
        block_state(
            np.array([0, math.log(2)]), np.array([[1, 0], [0, 1]]), [True, True]
        ),
        block_state(np.array([math.log(3)]), np.array([[1, 1]]), [True]),
    )
    return {
        "max_abs_error_by_block": errors,
        "worked_row": finish(state).tolist(),
        "all_masked_zero": bool(np.all(expected[:, 0] == 0)),
        "gpu_backend": False,
    }
