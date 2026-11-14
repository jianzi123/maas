"""Research-only runtime binding; packaged mature op, no disk source patch."""

from contextlib import contextmanager
import torch


@contextmanager
def mature_kv_binding():
    from sglang.srt.mem_cache.memory_pool import MHATokenToKVPool

    original = MHATokenToKVPool.set_kv_buffer

    def mature(
        self, layer, loc, k, v, k_scale=None, v_scale=None, layer_id_override=None
    ):
        if k_scale is not None or v_scale is not None:
            raise ValueError("research binding excludes KV scales")
        if (
            self.dtype not in (torch.float16, torch.bfloat16)
            or self.store_dtype != self.dtype
        ):
            raise ValueError("research binding excludes quantized cache")
        if k.dtype != self.dtype or v.dtype != self.dtype:
            raise ValueError("research binding forbids implicit conversion")
        index = (
            layer.layer_id if layer_id_override is None else layer_id_override
        ) - self.start_layer
        if not 0 <= index < len(self.k_buffer):
            raise ValueError("layer outside local cache")
        # No wrapper fallback, contiguous conversion, host data read, or stream cache.
        torch.ops.sgl_kernel.store_kv_cache(
            self.k_buffer[index], self.v_buffer[index], loc, k, v
        )

    MHATokenToKVPool.set_kv_buffer = mature
    try:
        yield
    finally:
        MHATokenToKVPool.set_kv_buffer = original
