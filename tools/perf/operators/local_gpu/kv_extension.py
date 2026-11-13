"""Task-local g++/ATen + NVRTC research binding; no nvcc claim."""

from pathlib import Path
import os
import torch
import cupy as cp


class FusedKV:
    def __init__(self, build_directory):
        build = Path(build_directory)
        build.mkdir(parents=True, exist_ok=True)
        # Process-local build controls; never write global environment/config.
        os.environ["MAX_JOBS"] = "1"
        from torch.utils.cpp_extension import load

        root = Path(__file__).parent
        nvidia = Path("/usr/local/lib/python3.10/dist-packages/nvidia/cuda_runtime")
        runtime = nvidia / "lib/libcudart.so.12"
        if not (nvidia / "include/cuda.h").is_file() or not runtime.is_file():
            raise RuntimeError("existing CUDA headers/runtime unavailable")
        self.library = load(
            name="maas_decode_kv_aten",
            sources=[str(root / "kv_aten.cpp")],
            with_cuda=False,
            is_python_module=False,
            build_directory=str(build),
            extra_include_paths=[str(nvidia / "include")],
            extra_cflags=["-O2", "-std=c++17"],
            extra_ldflags=["-L/usr/lib/wsl/lib", "-lcuda"],
            verbose=True,
        )
        self.module = cp.RawModule(
            code=(root / "kv_fused.cu").read_text(),
            options=("--std=c++17",),
            name_expressions=None,
        )
        self.kernel = self.module.get_function("kv_fused_u16")
        self.handle = int(self.kernel.kernel.ptr)

        @torch.library.register_fake("maas_decode_kv::write")
        def fake(kc, vc, locations, k, v, kernel_handle, stream_handle):
            return None

        self.fake = fake

    def write(self, pool, layer, locations, k, v):
        if layer.layer_id != 0:
            raise ValueError("one-layer research harness")
        with torch.cuda.device(pool.get_key_buffer(0).device):
            return torch.ops.maas_decode_kv.write(
                pool.get_key_buffer(0),
                pool.get_value_buffer(0),
                locations,
                k,
                v,
                self.handle,
                torch.cuda.current_stream().cuda_stream,
            )

    def bind(self, path):
        # Validate data-dependent bounds/uniqueness ONCE outside timing. Never
        # accept an arbitrary live request stream under this static-tensor binding.
        loc = path.locations
        rows = path.pool.get_key_buffer(0).shape[0]
        if not ((loc >= 0) & (loc < rows)).all() or loc.unique().numel() != loc.numel():
            raise ValueError("unique in-bounds fixed locations required")

        def writer(layer, locations, k, v):
            if locations.data_ptr() != loc.data_ptr():
                raise ValueError("fixed binding locations changed")
            return self.write(path.pool, layer, locations, k, v)

        return writer
