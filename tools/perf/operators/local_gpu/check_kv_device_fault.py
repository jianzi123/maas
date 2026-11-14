"""Isolated child verifies asynchronous device bounds fault, not memcheck."""

import argparse, json, subprocess, sys
from pathlib import Path


def child():
    import torch
    from kv_extension import FusedKV

    torch.set_grad_enabled(False)
    torch.cuda.set_device(0)
    torch.cuda.set_per_process_memory_fraction(0.05)
    ext = FusedKV("/tmp/maas-10-gpu-9bf1ab626448/aten-kv-build")
    kc = torch.zeros(2, 1, 64, device="cuda", dtype=torch.float16)
    vc = torch.zeros_like(kc)
    k = torch.ones(1, 1, 64, device="cuda", dtype=torch.float16)
    v = k.clone()
    loc = torch.tensor([-1], dtype=torch.int64, device="cuda")
    try:
        # Intentional low-level bypass of prebind validation in a disposable process.
        torch.ops.maas_decode_kv.write(
            kc, vc, loc, k, v, ext.handle, torch.cuda.current_stream().cuda_stream
        )
        torch.cuda.synchronize()
    except RuntimeError as exc:
        message = str(exc)
        if any(
            word in message.lower()
            for word in ("illegal instruction", "device-side assert", "launch failure")
        ):
            print(
                json.dumps(
                    {"expected_async_device_error": True, "message": message[:700]}
                ),
                flush=True,
            )
            return 42
        raise
    raise AssertionError("bad row was silently accepted")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--child", action="store_true")
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    if a.child:
        return child()
    if a.output is None:
        raise ValueError("output required")
    a.output.mkdir(parents=True, exist_ok=False)
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    (a.output / "child.log").write_text(r.stdout + r.stderr)
    result = {
        "expected_child_exit": 42,
        "actual_child_exit": r.returncode,
        "isolated_child_context": True,
        "compute_sanitizer_executed": False,
        "performance_or_engine_result": False,
    }
    if r.returncode != 42 or '"expected_async_device_error": true' not in r.stdout:
        raise AssertionError("expected isolated device fault not observed")
    (a.output / "device-fault.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
