"""Direct graph KV-state equivalence, separate from all timing/profile."""

import os

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1")
import argparse, sys, json, hashlib, contextlib
from pathlib import Path


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--variant", choices=("native", "mature"), required=True)
    a.add_argument("--output", type=Path, required=True)
    a.add_argument("--source-lock", type=Path, required=True)
    args = a.parse_args()
    import torch, numpy as np
    from sglang.srt.model_executor.model_runner import ModelRunner
    from native_kv_binding import mature_kv_binding
    import run_framework_dummy as baseline

    original = ModelRunner.forward
    states = {}
    index = [0]

    def observed(self, fb, *aa, **kw):
        result, graph = original(self, fb, *aa, **kw)
        if graph:
            loc = fb.out_cache_loc[: fb.batch_size]
            if not (loc > 0).all():
                raise AssertionError("state check excludes dummy slots")
            layers = range(self.start_layer, self.end_layer)
            k = torch.stack(
                [
                    self.token_to_kv_pool.get_key_buffer(i).index_select(0, loc)
                    for i in layers
                ]
            )
            v = torch.stack(
                [
                    self.token_to_kv_pool.get_value_buffer(i).index_select(0, loc)
                    for i in layers
                ]
            )
            states[f"k{index[0]:02d}"] = k.detach().cpu().numpy()
            states[f"v{index[0]:02d}"] = v.detach().cpu().numpy()
            index[0] += 1
        return result, graph

    try:
        with contextlib.ExitStack() as stack:
            if args.variant == "mature":
                stack.enter_context(mature_kv_binding())
            ModelRunner.forward = observed
            sys.argv = [
                sys.argv[0],
                "--output",
                str(args.output),
                "--source-lock",
                str(args.source_lock),
            ]
            code = baseline.main()
    finally:
        ModelRunner.forward = original
    if code:
        return code
    if index[0] != 12:
        raise AssertionError("missing KV graph states")
    np.savez_compressed(args.output / "kv-states.npz", **states)
    report = {
        "variant": args.variant,
        "graph_states": 12,
        "layers": 30,
        "arrays": 24,
        "scope": "actual graph-written raw token locations, all30 layers; not full unused pool",
        "code_sha256": {
            n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
            for n in (
                "check_native_kv_state.py",
                "native_kv_binding.py",
                "run_framework_dummy.py",
            )
        },
        "timing_or_model_quality_claim": False,
    }
    (args.output / "kv-state.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps({"KV_state_capture": "passed", "variant": args.variant}), flush=True
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
