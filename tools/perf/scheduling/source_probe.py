"""Execute unchanged pinned PrefillAdder AST methods against explicit host doubles."""

import argparse, ast, hashlib, json, types
from pathlib import Path
from enum import Enum


class AddReqResult(Enum):
    CONTINUE = 0
    NO_TOKEN = 1
    OTHER = 2


def load(root, row):
    path = Path(root) / row["commit"] / row["path"]
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise ValueError("source hash mismatch")
    tree = ast.parse(data)
    owner = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PrefillAdder"
    )
    names = (
        "rem_total_tokens",
        "cur_rem_tokens",
        "ceil_paged_tokens",
        "_update_prefill_budget",
        "add_chunked_req",
    )
    selected = [
        n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name in names
    ]
    env = {"AddReqResult": AddReqResult, "CLIP_MAX_NEW_TOKENS": 4096}
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            ast.ClassDef(
                name="Extracted",
                bases=[],
                keywords=[],
                body=selected,
                decorator_list=[],
            ),
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), env)
    return env["Extracted"], [
        {
            "name": n.name,
            "line": n.lineno,
            "end": n.end_lineno,
            "source_body_sha256": hashlib.sha256(
                ast.get_source_segment(data.decode(), n).encode()
            ).hexdigest(),
        }
        for n in selected
    ]


def probe(root):
    lock = json.loads(
        Path(__file__).with_name("source-lock.json").read_text(encoding="utf-8")
    )
    reports = []
    for row in lock["files"]:
        data = (Path(root) / row["commit"] / row["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("source hash mismatch")
    for row in lock["files"]:
        if not row["path"].endswith("managers/schedule_policy.py"):
            continue
        T, anchors = load(root, row)
        cases = []
        for extend, budget in [(32, 16), (16, 32), (33, 17)]:
            adder = T.__new__(T)
            adder.page_size = 16
            for name in (
                "is_hybrid_swa",
                "is_hybrid_gdn_cache",
                "is_hybrid_ssm_cache",
                "is_all_swa",
            ):
                setattr(adder, name, False)
            adder.dllm_config = None
            adder.prefill_delayer_single_pass = None
            adder.token_to_kv_pool_allocator = types.SimpleNamespace(
                available_size=lambda: 512
            )
            adder.tree_cache = types.SimpleNamespace(evictable_size=lambda: 0)
            adder.rem_total_token_offset = adder.cur_rem_token_offset = 0
            adder.rem_input_tokens = 512
            adder.rem_chunk_tokens = budget
            adder.rem_mamba_slots = None
            adder.can_run_list = []
            adder.log_hit_tokens = adder.log_input_tokens = 0
            adder._mamba_gap_budget_for_req = lambda req: 0
            req = types.SimpleNamespace(
                extend_input_len=extend,
                fill_ids=list(range(extend)),
                full_untruncated_fill_ids=list(range(extend)),
                prefix_indices=[],
                retracted_stain=False,
                sampling_params=types.SimpleNamespace(max_new_tokens=16),
            )

            def set_range(begin, end):
                req.extend_range = types.SimpleNamespace(length=end - begin)
                req.extend_input_len = end - begin
                req.fill_ids = req.full_untruncated_fill_ids[:end]

            req.set_extend_range = set_range
            pending = adder.add_chunked_req(req)
            chosen = req.extend_input_len
            if chosen != min(extend, budget):
                raise RuntimeError("source probe mismatch")
            cases.append(
                {
                    "input_remaining": extend,
                    "chunk_budget": budget,
                    "selected": chosen,
                    "prefill_still_pending": pending is not None,
                    "total_offset": adder.rem_total_token_offset,
                    "current_offset": adder.cur_rem_token_offset,
                    "remaining_input": adder.rem_input_tokens,
                    "remaining_chunk": adder.rem_chunk_tokens,
                }
            )
        reports.append(
            {
                "commit": row["commit"],
                "path": row["path"],
                "sha256": row["sha256"],
                "exact_ast_methods": anchors,
                "cases": cases,
            }
        )
    return {
        "all_locked_files_verified": len(lock["files"]),
        "source_only_not_engine_executed": True,
        "unchanged_AST_executed": True,
        "reports": reports,
        "explicit_doubles": [
            "ordinary nonhybrid allocator/cache capacities",
            "Mamba gap=0",
            "no prefill-delayer",
            "synthetic Req range interface",
        ],
        "not_full_scheduler_or_gpu": True,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    result = probe(a.source_root)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    print(
        json.dumps(
            {
                "source_versions": len(result["reports"]),
                "cases": sum(len(r["cases"]) for r in result["reports"]),
            }
        )
    )


if __name__ == "__main__":
    main()
