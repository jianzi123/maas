"""Weight-free harness calling installed SGLang 0.5.2 backend methods and kernels.

Synthetic request state replaces model/scheduler setup, NOT any GPU implementation.
No patched upstream source, Engine, model forward, or serving is claimed.
"""

import math
from types import SimpleNamespace
import torch
from sglang.srt.layers.attention.triton_backend import TritonAttnBackend
from sglang.srt.layers.attention.triton_ops.decode_attention import decode_attention_fwd
from sglang.srt.layers.radix_attention import RadixAttention
from sglang.srt.mem_cache.memory_pool import MHATokenToKVPool
from sglang.srt.model_executor.forward_batch_info import ForwardMode


def validate(lengths, hq, hkv, dim, cap, dtype):
    if (
        not lengths
        or len(lengths) > 8
        or any(type(n) is not int or not 1 <= n <= 4097 for n in lengths)
    ):
        raise ValueError("bounded positive decode lengths required")
    if (
        sum(lengths) > 20000
        or type(hq) is not int
        or type(hkv) is not int
        or not 1 <= hkv <= hq <= 16
        or hq % hkv
    ):
        raise ValueError("bounded divisible head grouping required")
    if (
        dim not in (64, 80, 128)
        or cap not in (1, 2, 4, 8)
        or dtype not in (torch.float16, torch.bfloat16)
    ):
        raise ValueError("unsupported bounded dimension/splits/dtype")


class DecodePath:
    def __init__(
        self,
        lengths,
        hq=9,
        hkv=3,
        dim=64,
        cap=8,
        dtype=torch.float16,
        seed=20261113,
        logit_cap=0.0,
    ):
        validate(lengths, hq, hkv, dim, cap, dtype)
        if not math.isfinite(logit_cap) or logit_cap < 0:
            raise ValueError("invalid logit cap")
        self.lengths = tuple(lengths)
        self.hq = hq
        self.hkv = hkv
        self.dim = dim
        self.cap = cap
        self.layer = RadixAttention(hq, dim, dim**-0.5, hkv, 0, logit_cap=logit_cap)
        b = len(lengths)
        n = sum(lengths)
        capacity = n + 17
        g = torch.Generator(device="cuda").manual_seed(seed)
        self.pool = MHATokenToKVPool(capacity, 1, dtype, hkv, dim, 1, "cuda", False)
        self.pool.get_key_buffer(0).fill_(float("nan"))
        self.pool.get_value_buffer(0).fill_(float("nan"))
        physical = (torch.randperm(capacity, generator=g, device="cuda")[:n] + 1).to(
            torch.int64
        )
        self.logical_k = (
            torch.randn(n, hkv, dim, generator=g, device="cuda", dtype=dtype) * 0.2
        )
        self.logical_v = (
            torch.randn(n, hkv, dim, generator=g, device="cuda", dtype=dtype) * 0.2
        )
        self.q = torch.randn(b, hq, dim, generator=g, device="cuda", dtype=dtype) * 0.2
        self.pool.get_key_buffer(0)[physical] = self.logical_k
        self.pool.get_value_buffer(0)[physical] = self.logical_v
        table = torch.zeros(b + 2, max(lengths), dtype=torch.int32, device="cuda")
        offset = 0
        last = []
        for i, length in enumerate(lengths):
            table[i + 1, :length] = physical[offset : offset + length].int()
            last.append(offset + length - 1)
            offset += length
        last_idx = torch.tensor(last, device="cuda")
        self.new_k = self.logical_k[last_idx].contiguous()
        self.new_v = self.logical_v[last_idx].contiguous()
        self.locations = physical[last_idx].contiguous()
        self.physical = physical
        # Deliberately no ModelRunner/distributed bootstrap: this constructs only
        # the bounded state consumed by ORIGINAL metadata/forward methods.
        backend = TritonAttnBackend.__new__(TritonAttnBackend)
        backend.req_to_token = table
        backend.kv_indptr = torch.zeros(b + 1, dtype=torch.int32, device="cuda")
        backend.window_kv_indptr = None
        backend.sliding_window_size = None
        backend.token_to_kv_pool_allocator = None
        backend.num_head = hq
        backend.num_kv_head = hkv
        backend.v_head_dim = dim
        backend.device = "cuda"
        backend.max_kv_splits = cap
        backend.device_core_count = torch.cuda.get_device_properties(
            0
        ).multi_processor_count
        backend.static_kv_splits = False
        backend.decode_attention_fwd = decode_attention_fwd
        backend.forward_metadata = None
        self.backend = backend
        self.batch = SimpleNamespace(
            batch_size=b,
            spec_info=None,
            forward_mode=ForwardMode.DECODE,
            seq_lens=torch.tensor(lengths, dtype=torch.int32, device="cuda"),
            seq_lens_sum=n,
            req_pool_indices=torch.arange(1, b + 1, dtype=torch.int64, device="cuda"),
            token_to_kv_pool=self.pool,
            out_cache_loc=self.locations,
            attn_backend=backend,
        )
        self.rebuild_metadata()
        self.o = torch.empty_like(self.q)
        self.assert_mapping()

    def rebuild_metadata(self):
        self.backend.init_forward_metadata(self.batch)

    def assert_mapping(self):
        f = self.backend.forward_metadata
        torch.testing.assert_close(f.kv_indices, self.physical, rtol=0, atol=0)
        expected = torch.tensor(
            [0, *torch.tensor(self.lengths).cumsum(0).tolist()],
            dtype=torch.int32,
            device="cuda",
        )
        torch.testing.assert_close(f.kv_indptr, expected, rtol=0, atol=0)
        if not ((f.num_kv_splits >= 1) & (f.num_kv_splits <= self.cap)).all():
            raise AssertionError("invalid actual dynamic split choice")

    def write(self):
        self.pool.set_kv_buffer(self.layer, self.locations, self.new_k, self.new_v)

    def raw_decode(self):
        f = self.backend.forward_metadata
        decode_attention_fwd(
            self.q,
            self.pool.get_key_buffer(0),
            self.pool.get_value_buffer(0),
            self.o,
            f.kv_indptr,
            f.kv_indices,
            f.attn_logits,
            f.attn_lse,
            f.num_kv_splits,
            self.cap,
            self.layer.scaling,
            logit_cap=self.layer.logit_cap,
        )
        return self.o

    def forward(self):
        return self.layer(self.q, self.new_k, self.new_v, self.batch)

    def reference(self):
        # Independent FP64 GPU dense equation on LOGICAL K/V, no reuse of
        # backend gather/index or two-stage softmax; not included in timing.
        heads = torch.arange(self.hq, device="cuda") // (self.hq // self.hkv)
        out = []
        start = 0
        for i, length in enumerate(self.lengths):
            k = (
                self.logical_k[start : start + length][:, heads]
                .double()
                .transpose(0, 1)
            )
            v = (
                self.logical_v[start : start + length][:, heads]
                .double()
                .transpose(0, 1)
            )
            logits = (
                torch.einsum("hd,hnd->hn", self.q[i].double(), k) * self.layer.scaling
            )
            if self.layer.logit_cap:
                logits = self.layer.logit_cap * torch.tanh(
                    logits / self.layer.logit_cap
                )
            out.append(torch.einsum("hn,hnd->hd", torch.softmax(logits, -1), v))
            start += length
        return torch.stack(out).to(self.q.dtype)

    def check(self):
        ref = self.reference()
        # Poison only new-token slots, then demand actual pool WRITE fixes them.
        self.pool.get_key_buffer(0)[self.locations] = float("nan")
        self.pool.get_value_buffer(0)[self.locations] = float("nan")
        actual = self.forward().reshape_as(ref)
        tolerance = 3e-3 if self.q.dtype == torch.float16 else 2e-2
        check_finite_close(actual, ref, tolerance)
        raw = self.raw_decode()
        check_finite_close(raw, ref, tolerance)
        torch.testing.assert_close(
            self.pool.get_key_buffer(0)[self.locations], self.new_k, rtol=0, atol=0
        )
        torch.testing.assert_close(
            self.pool.get_value_buffer(0)[self.locations], self.new_v, rtol=0, atol=0
        )
        return {
            "max_abs": (actual.float() - ref.float()).abs().max().item(),
            "rtol_atol": tolerance,
            "mapping_and_new_KV_write": "passed",
            "finite": True,
        }

    def metadata(self):
        f = self.backend.forward_metadata
        return {
            "lengths": self.lengths,
            "hq": self.hq,
            "hkv": self.hkv,
            "dim": self.dim,
            "dtype": str(self.q.dtype),
            "page_size": 1,
            "cap": self.cap,
            "actual_dynamic_splits": f.num_kv_splits.cpu().tolist(),
            "q_shape": list(self.q.shape),
            "q_stride": list(self.q.stride()),
            "k_shape": list(self.pool.get_key_buffer(0).shape),
            "k_stride": list(self.pool.get_key_buffer(0).stride()),
            "kv_bytes": int(sum(self.pool.get_kv_size_bytes())),
            "scratch_bytes": f.attn_logits.nbytes + f.attn_lse.nbytes,
            "kv_indices_sha256": __import__("hashlib")
            .sha256(f.kv_indices.cpu().numpy().tobytes())
            .hexdigest(),
            "model_or_scheduler_initialized": False,
        }


def check_finite_close(actual, expected, tolerance):
    if not torch.isfinite(actual).all() or not torch.isfinite(expected).all():
        raise AssertionError("nonfinite output/reference: no timing report")
    torch.testing.assert_close(actual, expected, rtol=tolerance, atol=tolerance)
