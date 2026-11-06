"""Worked fictional shapes and budgets; no actual GPU/model capacity claim."""
import json
import math


def calculate():
    layers, kv_heads, head_dim, element_bytes = 24, 4, 64, 2
    per_token = 2 * layers * kv_heads * head_dim * element_bytes
    page_tokens, sequence_tokens = 16, 1024 + 256
    page_bytes = per_token * page_tokens
    kv_budget_bytes = (8192 - 4096 - 512 - 256 - 256 - 1024) * 1024**2
    physical_pages = kv_budget_bytes // page_bytes
    sequence_pages = math.ceil(sequence_tokens / page_tokens)
    m, n, k, tile = 37, 53, 29, 16
    return {"fictional_example": True, "kv_bytes_per_token": per_token,
            "sequence_mib": sequence_tokens * per_token // 1024**2,
            "page_kib": page_bytes // 1024, "kv_budget_mib": kv_budget_bytes // 1024**2,
            "physical_pages": physical_pages, "pages_per_sequence": sequence_pages,
            "kv_only_upper_bound_sequences": physical_pages // sequence_pages,
            "graph_extra_mib": 384,
            "kv_budget_after_graph_mib": 1664,
            "kv_only_sequences_after_graph": (1664*1024**2 // page_bytes) // sequence_pages,
            "safe_platform_concurrency": None,
            "gemm_useful_flops": 2*m*n*k,
            "gemm_blocks": math.ceil(m/tile)*math.ceil(n/tile),
            "gemm_k_tiles": math.ceil(k/tile),
            "shared_tile_bytes_per_block": 2*tile*tile*4,
            "gemm_tail_rows_cols_k": [m % tile, n % tile, k % tile],
            "bluegreen_group_gpu_example": {"current": 2*2*2, "overlap": 2*2*2*2},
            "gpu_or_framework_measured": False}


if __name__ == "__main__":
    print(json.dumps(calculate(), indent=2))
