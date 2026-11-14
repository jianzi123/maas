"""Validate before-capture mature KV binding, native control and late-binding negative control."""

import os

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1")
import argparse, json, sys, hashlib
from pathlib import Path
from contextlib import ExitStack


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--variant", choices=("native", "mature", "late"), required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--source-lock", type=Path, required=True)
    args = p.parse_args()
    import torch, numpy as np
    from sglang.srt.model_executor.model_runner import ModelRunner
    from native_kv_binding import mature_kv_binding
    import run_framework_dummy as baseline

    original_init = ModelRunner.__init__
    original_forward = ModelRunner.forward
    snapshots = {}
    capture_installs = []
    stack = ExitStack()

    def before_init(self, *aa, **kw):
        original_init(self, *aa, **kw)
        capture_installs.append(
            {
                "captures": sorted(self.graph_runner.graphs),
                "binding_at_capture": (
                    "mature" if args.variant == "mature" else "native"
                ),
            }
        )
        if args.variant == "late":
            stack.enter_context(mature_kv_binding())

    def observe(self, fb, *aa, **kw):
        value, graph = original_forward(self, fb, *aa, **kw)
        if graph:
            tensor = value.next_token_logits.detach().clone()
            snapshots[f"decode{len(snapshots):02d}"] = tensor.cpu().numpy()
        return value, graph

    try:
        if args.variant == "mature":
            stack.enter_context(mature_kv_binding())
        ModelRunner.__init__ = before_init
        ModelRunner.forward = observe
        sys.argv = [
            sys.argv[0],
            "--output",
            str(args.output),
            "--source-lock",
            str(args.source_lock),
            "--profile",
        ]
        code = baseline.main()
    finally:
        ModelRunner.__init__ = original_init
        ModelRunner.forward = original_forward
        stack.close()
    report = json.loads((args.output / "framework.json").read_text())
    if code:
        return code
    if len(snapshots) != 12:
        raise AssertionError("missing cross-variant snapshots")
    np.savez_compressed(args.output / "logits.npz", **snapshots)
    tr = json.loads((args.output / "timeline.json").read_text())
    kernels = [e for e in tr["traceEvents"] if e.get("cat") == "kernel"]
    regions = []
    for region in tr["traceEvents"]:
        if region.get("cat") != "user_annotation" or not region["name"].startswith(
            "framework/"
        ):
            continue
        found = [
            e
            for e in kernels
            if region["ts"] <= e["ts"]
            and e["ts"] + e.get("dur", 0) <= region["ts"] + region["dur"]
        ]
        writes = [e for e in found if "index_elementwise_kernel" in e["name"]]
        stores = [e for e in found if "store_kv_cache" in e["name"]]
        graph = region["name"].endswith("/graph")
        expected_mature = args.variant == "mature" or (
            args.variant == "late" and not graph
        )
        if expected_mature:
            if len(stores) != 30 or writes:
                raise AssertionError("mature KV not actually hit")
        elif len(writes) != 60 or stores:
            raise AssertionError("native KV control changed")
        regions.append(
            {
                "region": region["name"],
                "total_kernels": len(found),
                "index_writes": len(writes),
                "mature_stores": len(stores),
                "streams": sorted({e["args"]["stream"] for e in found}),
            }
        )
    if len(regions) != 4:
        raise AssertionError("missing structural trace regions")
    result = {
        "variant": args.variant,
        "status": "passed",
        "source_commit": report["source_commit"],
        "binding_installation": capture_installs,
        "trace_regions": regions,
        "expected_graph_fusion": args.variant == "mature",
        "late_binding_negative_control": args.variant == "late",
        "ModelRunner": True,
        "Engine": False,
        "weights": "artificial_random",
        "semantic_quality_or_pretrained_performance_claim": False,
        "snapshot_count": len(snapshots),
        "native_report": "framework.json",
        "code_sha256": {
            n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
            for n in (
                "run_native_kv_integration.py",
                "native_kv_binding.py",
                "run_framework_dummy.py",
            )
        },
    }
    (args.output / "integration.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "variant": args.variant,
                "integration": "passed",
                "graph_fused": args.variant == "mature",
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
