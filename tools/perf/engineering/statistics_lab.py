"""Run-level paired bootstrap and a right-censored recovery estimator; CPU synthetic data."""

import numpy as np


def paired_gain(baseline, candidate, resamples=2000, seed=41):
    a, b = np.asarray(baseline, dtype=float), np.asarray(candidate, dtype=float)
    if (
        a.ndim != 1
        or a.shape != b.shape
        or len(a) < 2
        or not np.isfinite(a).all()
        or not np.isfinite(b).all()
        or min(a.min(), b.min()) <= 0
    ):
        raise ValueError("positive finite paired run metrics")
    if type(resamples) is not int or not 100 <= resamples <= 20000:
        raise ValueError("bounded resamples")
    logs = np.log(b / a)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(logs), size=(resamples, len(logs)))
    samples = np.expm1(logs[indices].mean(axis=1))
    return {
        "estimand": "geometric mean of paired run ratios minus 1",
        "gain": float(np.expm1(logs.mean())),
        "percentile_95": np.quantile(samples, [0.025, 0.975]).tolist(),
        "paired_runs": len(a),
        "seed": seed,
        "resamples": resamples,
        "independence_or_stationarity_not_established_by_bootstrap": True,
    }


def kaplan_meier(durations, recovered):
    times = np.asarray(durations, dtype=float)
    events = np.asarray(recovered)
    if (
        times.ndim != 1
        or times.shape != events.shape
        or len(times) == 0
        or not np.isfinite(times).all()
        or (times < 0).any()
        or events.dtype.kind != "b"
    ):
        raise ValueError("finite times and boolean recovery events")
    survival = 1.0
    rows = []
    for t in np.unique(times):
        risk = int(np.sum(times >= t))
        done = int(np.sum((times == t) & events))
        censored = int(np.sum((times == t) & ~events))
        survival *= 1 - done / risk
        rows.append(
            {
                "time": float(t),
                "at_risk": risk,
                "recovered": done,
                "censored": censored,
                "survival": float(survival),
            }
        )
    median = next((r["time"] for r in rows if r["survival"] <= 0.5), None)
    p95 = next((r["time"] for r in rows if r["survival"] <= 0.05), None)
    return {
        "rows": rows,
        "median": median,
        "p95": p95,
        "requires_noninformative_censoring_and_defined_recovery_event": True,
    }


def demo():
    paired = paired_gain([100, 96, 103, 99, 101], [111, 105, 115, 108, 113])
    km = kaplan_meier(
        [1, 2, 2, 3, 4, 5], np.array([True, True, False, True, False, False])
    )
    return {
        "paired": paired,
        "recovery": km,
        "all_inputs_synthetic": True,
        "performance_claim_or_approved_policy": False,
    }
