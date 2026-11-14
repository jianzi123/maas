"""Verify captured decode outputs, including changed live KV inputs after capture."""

import argparse, json
from pathlib import Path
import torch
from decode_path import DecodePath, check_finite_close
from kv_extension import FusedKV
from run_decode import capture, CELLS, save

if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--output", type=Path, required=True)
    args = a.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_grad_enabled(False)
    torch.cuda.set_device(0)
    torch.cuda.set_per_process_memory_fraction(0.2)
    ext = FusedKV("/tmp/maas-10-gpu-9bf1ab626448/aten-kv-build")
    rows = []
    for cell, lengths in CELLS:
        for cap in (8, 1, 4):
            p = DecodePath(lengths, cap=cap)
            g = capture(p.raw_decode, 30)
            p.o.fill_(float("nan"))
            g.replay()
            torch.cuda.synchronize()
            check_finite_close(p.o, p.reference(), 3e-3)
            rows.append(
                {
                    "cell": cell,
                    "cap": cap,
                    "scope": "raw_decode",
                    "poisoned_output_updated": True,
                }
            )
        # Retain last output of the full backend graph for explicit inspection.
        p = DecodePath(lengths)
        original = p.pool.set_kv_buffer
        fused = ext.bind(p)
        for label, writer in (("original", original), ("fused", fused)):
            p.pool.set_kv_buffer = writer
            held = []

            def fn():
                out = p.forward()
                if held:
                    held[0] = out
                else:
                    held.append(out)
                return out

            g = capture(fn, 30)
            # Graph must consume changed inputs and rewrite the new-token slots,
            # rather than pass from a stale pre-capture tensor.
            p.new_k.add_(0.03125)
            p.new_v.sub_(0.0625)
            last = []
            start = 0
            for n in lengths:
                last.append(start + n - 1)
                start += n
            ix = torch.tensor(last, device="cuda")
            p.logical_k[ix] = p.new_k
            p.logical_v[ix] = p.new_v
            p.pool.get_key_buffer(0)[p.locations] = float("nan")
            p.pool.get_value_buffer(0)[p.locations] = float("nan")
            held[0].fill_(float("nan"))
            g.replay()
            torch.cuda.synchronize()
            ref = p.reference()
            check_finite_close(held[0].reshape_as(ref), ref, 3e-3)
            torch.testing.assert_close(
                p.pool.get_key_buffer(0)[p.locations], p.new_k, rtol=0, atol=0
            )
            torch.testing.assert_close(
                p.pool.get_value_buffer(0)[p.locations], p.new_v, rtol=0, atol=0
            )
            rows.append(
                {
                    "cell": cell,
                    "cap": 8,
                    "scope": "backend_" + label,
                    "changed_live_inputs_verified": True,
                    "poisoned_output_and_KV_rewritten": True,
                }
            )
    save(
        args.output / "graph-correctness.json",
        {
            "checks": rows,
            "passed": True,
            "scope": "independent captured-output correctness; no new performance claim",
            "iterations_per_graph": 30,
        },
    )
    print(json.dumps({"graph_checks": len(rows), "passed": True}), flush=True)
