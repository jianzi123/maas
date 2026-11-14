"""Actual CPU tiled GEMM plus theoretical address/occupancy calculations."""

import numpy as np


def tiled_gemm(a, b, tile=(8, 8, 4)):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if a.ndim != 2 or b.ndim != 2 or a.shape[1] != b.shape[0]:
        raise ValueError("GEMM shape")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("finite")
    if len(tile) != 3 or any(type(t) is not int or t <= 0 for t in tile):
        raise ValueError("tile")
    tm, tn, tk = tile
    m, k = a.shape
    n = b.shape[1]
    c = np.zeros((m, n))
    for i in range(0, m, tm):
        for j in range(0, n, tn):
            acc = np.zeros((min(tm, m - i), min(tn, n - j)))
            for start in range(0, k, tk):
                # Real partial slices implement tail masks, preserving strided inputs.
                acc += (
                    a[i : i + tm, start : start + tk]
                    @ b[start : start + tk, j : j + tn]
                )
            c[i : i + tm, j : j + tn] = acc
    if not np.isfinite(c).all():
        raise ValueError("output overflow")
    return c


def sectors(byte_addresses, element_bytes=4, sector_bytes=32):
    if element_bytes <= 0 or sector_bytes <= 0 or any(x < 0 for x in byte_addresses):
        raise ValueError("address")
    return len(
        {
            byte // sector_bytes
            for a in byte_addresses
            for byte in range(a, a + element_bytes)
        }
    )


def bank_conflict_degree(word_addresses, banks=32):
    # Same WORD read is broadcast in this simplified 32-bit read model.
    if banks <= 0 or any(a < 0 for a in word_addresses):
        raise ValueError("word/banks")
    per_bank = [set() for _ in range(banks)]
    for a in word_addresses:
        per_bank[a % banks].add(a)
    return max(map(len, per_bank), default=0)


def register_bound(
    registers_per_sm, thread_limit, threads_per_block, regs_per_thread, max_blocks
):
    if (
        min(
            registers_per_sm,
            thread_limit,
            threads_per_block,
            regs_per_thread,
            max_blocks,
        )
        <= 0
    ):
        raise ValueError("positive")
    blocks = min(
        registers_per_sm // (threads_per_block * regs_per_thread),
        thread_limit // threads_per_block,
        max_blocks,
    )
    return {
        "blocks": blocks,
        "active_threads": blocks * threads_per_block,
        "occupancy_upper_bound": blocks * threads_per_block / thread_limit,
        "ignores_register_granularity_sharedmem_and_warp_limits": True,
    }


def intensity(m, n, k, bytes_per_element=4):
    if min(m, n, k, bytes_per_element) <= 0:
        raise ValueError("positive shapes")
    return 2 * m * n * k / (bytes_per_element * (m * k + k * n + m * n))


def demo():
    rng = np.random.default_rng(7)
    a = rng.normal(size=(37, 58))[:, ::2]
    b = rng.normal(size=(58, 53))[::2, :]
    expected = a @ b
    c = tiled_gemm(a, b, (16, 16, 16))
    return {
        "strided_gemm_shape": [37, 53, 29],
        "max_abs_error": float(np.max(np.abs(c - expected))),
        "aligned_warp_sectors": sectors([i * 4 for i in range(32)]),
        "offset4_warp_sectors": sectors([4 + i * 4 for i in range(32)]),
        "stride32_bank_degree": bank_conflict_degree([i * 32 for i in range(32)]),
        "stride33_bank_degree": bank_conflict_degree([i * 33 for i in range(32)]),
        "broadcast_bank_degree": bank_conflict_degree([0] * 32),
        "register_model": register_bound(65536, 2048, 256, 64, 32),
        "M1_intensity": intensity(1, 4096, 4096),
        "M128_intensity": intensity(128, 4096, 4096),
        "address_model_not_measured_gpu_transactions": True,
    }
