"""Compile/register the ATen-host/NVRTC-device fusion and verify real GPU output."""

import argparse, json, torch, time
from pathlib import Path
from decode_path import DecodePath
from kv_extension import FusedKV

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    torch.set_grad_enabled(False)
    torch.cuda.set_device(0)
    torch.cuda.set_per_process_memory_fraction(0.2)
    t = time.perf_counter()
    ext = FusedKV("/tmp/maas-10-gpu-9bf1ab626448/aten-kv-build")
    path = DecodePath([17, 33], cap=8)
    path.pool.set_kv_buffer = ext.bind(path)
    result = path.check()
    opcheck = torch.library.opcheck(
        torch.ops.maas_decode_kv.write.default,
        (
            path.pool.get_key_buffer(0),
            path.pool.get_value_buffer(0),
            path.locations,
            path.new_k,
            path.new_v,
            ext.handle,
            torch.cuda.current_stream().cuda_stream,
        ),
        test_utils=("test_schema", "test_faketensor"),
    )
    result.update(
        build_and_check_s=time.perf_counter() - t,
        opcheck=opcheck,
        host_route="g++ ATen dispatcher",
        device_route="NVRTC; nvcc NOT executed",
        library=ext.library,
    )
    (a.output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
