"""Compare actual native-graph KV snapshots; reject corrupted/stale candidates.

CPU analysis only. Snapshots must come from check_native_kv_state.py.
This does not measure timing or pretrained model quality.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def require_equal(reference, candidate):
    if reference.dtype != np.float16 or candidate.dtype != reference.dtype:
        raise AssertionError("expected matching float16 snapshots")
    if candidate.shape != reference.shape:
        raise AssertionError("KV snapshot shape mismatch")
    if not np.isfinite(reference).all() or not np.isfinite(candidate).all():
        raise AssertionError("nonfinite KV snapshot")
    if not np.array_equal(reference.view(np.uint16), candidate.view(np.uint16)):
        raise AssertionError("KV bits differ")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    keys = {f"{kind}{i:02d}" for kind in ("k", "v") for i in range(12)}
    rows, controls = [], []
    batches = [1, 1, 3, 3, 2, 2, 5, 5, 8, 8, 3, 1]
    with np.load(args.reference, allow_pickle=False) as a, np.load(
        args.candidate, allow_pickle=False
    ) as b:
        if set(a.files) != keys or set(b.files) != keys:
            raise AssertionError("incomplete KV state set")
        for key in sorted(keys):
            ref, cand = a[key], b[key]
            expected = (30, batches[int(key[1:])], 3, 64)
            if ref.shape != expected:
                raise AssertionError(f"{key}: expected {expected}, got {ref.shape}")
            require_equal(ref, cand)
            rows.append({"state": key, "shape": list(ref.shape), "bitwise_equal": True})
            try:
                require_equal(ref, np.zeros_like(cand))
            except AssertionError:
                controls.append({"state": key, "mutation": "zero", "rejected": True})
            else:
                raise AssertionError(f"{key}: zero candidate escaped")
        for kind in ("k", "v"):
            for i in range(0, 10, 2):
                key, stale = f"{kind}{i+1:02d}", f"{kind}{i:02d}"
                try:
                    require_equal(a[key], b[stale])
                except AssertionError:
                    controls.append(
                        {"state": key, "mutation": f"stale:{stale}", "rejected": True}
                    )
                else:
                    raise AssertionError(f"{key}: stale candidate escaped")
    report = {
        "status": "passed", "source": "real local GPU native ModelRunner, artificial weights",
        "scope": "all30 layers, actual graph-written locations; unused KV pool excluded",
        "arrays": rows, "negative_controls": controls,
        "negative_controls_scope": "offline snapshot mutations, not mutated GPU kernels",
        "finite_and_bitwise_equal": True,
        "inputs_sha256": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in (("reference", args.reference), ("candidate", args.candidate))
        },
        "comparison_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "timing_or_model_quality_claim": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"arrays": len(rows), "negative_controls": len(controls),
                      "finite_and_bitwise_equal": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
