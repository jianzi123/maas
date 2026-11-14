"""CPU TP/MoE equivalence and exact one-step speculative probability accounting."""

import numpy as np


def _finite(x):
    x = np.asarray(x, dtype=np.float64)
    if not np.isfinite(x).all():
        raise ValueError("finite")
    return x


def column_parallel(x, w, ranks):
    x, w = _finite(x), _finite(w)
    if (
        x.ndim != 2
        or w.ndim != 2
        or type(ranks) is not int
        or ranks <= 0
        or w.shape[1] % ranks
        or x.shape[1] != w.shape[0]
    ):
        raise ValueError("partition")
    return np.concatenate([x @ part for part in np.split(w, ranks, axis=1)], axis=1)


def row_parallel(x, w, ranks):
    x, w = _finite(x), _finite(w)
    if (
        x.ndim != 2
        or w.ndim != 2
        or type(ranks) is not int
        or ranks <= 0
        or w.shape[0] % ranks
        or x.shape[1] != w.shape[0]
    ):
        raise ValueError("partition")
    return sum(
        a @ b for a, b in zip(np.split(x, ranks, axis=1), np.split(w, ranks, axis=0))
    )


def moe_dispatch(x, weights, experts, gates, capacity=None):
    x, weights, gates = map(_finite, (x, weights, gates))
    experts = np.asarray(experts)
    if (
        x.ndim != 2
        or weights.ndim != 3
        or experts.ndim != 2
        or experts.shape != gates.shape
        or len(experts) != len(x)
    ):
        raise ValueError("MoE shapes")
    if weights.shape[1] != x.shape[1] or experts.dtype.kind not in "iu":
        raise ValueError("expert shape/type")
    if (
        (experts < 0).any()
        or (experts >= len(weights)).any()
        or (gates < 0).any()
        or not np.allclose(gates.sum(axis=1), 1, atol=1e-12, rtol=0)
    ):
        raise ValueError("route/gate")
    if any(len(set(row.tolist())) != len(row) for row in experts):
        raise ValueError("duplicate route")
    counts = np.bincount(experts.ravel(), minlength=len(weights))
    if capacity is not None and (
        type(capacity) is not int or capacity < 0 or (counts > capacity).any()
    ):
        raise ValueError("capacity overflow; no token drop")
    # Stable dispatch records preserve token and top-k slot for inverse routing.
    records = sorted(
        [
            (int(e), t, slot)
            for t, row in enumerate(experts)
            for slot, e in enumerate(row)
        ]
    )
    out = np.zeros((len(x), weights.shape[-1]))
    for e in range(len(weights)):
        routes = [(t, slot) for expert, t, slot in records if expert == e]
        if routes:
            tokens = np.array([t for t, _ in routes])
            slots = np.array([slot for _, slot in routes])
            transformed = x[tokens] @ weights[e]
            np.add.at(out, tokens, transformed * gates[tokens, slots, None])
    return _finite(out), counts.tolist()


def speculative_mass(p, q):
    p, q = _finite(p), _finite(q)
    if (
        p.ndim != 1
        or p.shape != q.shape
        or (p < 0).any()
        or (q < 0).any()
        or not np.isclose(p.sum(), 1, atol=1e-12, rtol=0)
        or not np.isclose(q.sum(), 1, atol=1e-12, rtol=0)
    ):
        raise ValueError("categorical distributions")
    accepted = np.minimum(p, q)
    reject = max(0.0, float(1 - accepted.sum()))
    positive = np.maximum(p - q, 0)
    # q=0 has no proposal mass; its p mass appears in the residual distribution.
    residual = positive / positive.sum() if positive.sum() > 1e-14 else np.zeros_like(p)
    result = accepted + reject * residual
    return {
        "accept_probability": float(accepted.sum()),
        "residual": residual.tolist(),
        "result_mass": result.tolist(),
    }


def ring_bytes_per_rank(payload_bytes, ranks):
    if type(ranks) is not int or ranks <= 0 or payload_bytes < 0:
        raise ValueError("ring")
    return 2 * (ranks - 1) / ranks * payload_bytes


def demo():
    rng = np.random.default_rng(29)
    x = rng.normal(size=(7, 8))
    w = rng.normal(size=(8, 6))
    weights = rng.normal(size=(4, 8, 5))
    experts = np.array([[0, 1], [2, 3], [1, 3], [0, 2], [2, 1], [3, 0], [1, 0]])
    gates = np.tile([0.7, 0.3], (len(x), 1))
    result, counts = moe_dispatch(x, weights, experts, gates)
    oracle = np.stack(
        [
            sum(gates[t, j] * (x[t] @ weights[e]) for j, e in enumerate(experts[t]))
            for t in range(len(x))
        ]
    )
    return {
        "tp_column_error": float(np.max(np.abs(column_parallel(x, w, 2) - x @ w))),
        "tp_row_error": float(np.max(np.abs(row_parallel(x, w, 2) - x @ w))),
        "moe_combine_error": float(np.max(np.abs(result - oracle))),
        "expert_assignments": counts,
        "speculative": speculative_mass([0.1, 0.7, 0.2], [0.4, 0.4, 0.2]),
        "ring_4_rank_8MiB_bytes_per_rank": ring_bytes_per_rank(8 * 1024**2, 4),
        "communication_executed": False,
    }
