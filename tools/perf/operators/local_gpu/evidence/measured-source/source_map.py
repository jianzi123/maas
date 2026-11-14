"""Pin wheel source to official v0.5.2 source and emit a navigable source map."""
import ast
import concurrent.futures
import hashlib
import importlib.metadata as md
import json
from pathlib import Path
import sys
import urllib.request

COMMIT = "b0d25e72c401f37b55d689ddbf05b8c583afe854"
PATHS = [
    "srt/entrypoints/engine.py", "srt/managers/tokenizer_manager.py",
    "srt/managers/scheduler.py", "srt/managers/schedule_batch.py",
    "srt/model_executor/model_runner.py", "srt/mem_cache/radix_cache.py",
    "srt/layers/attention/triton_backend.py", "srt/layers/layernorm.py", "srt/models/llama.py",
]
NAMES = {
    "generate", "generate_request", "_tokenize_one_request", "event_loop_normal",
    "get_next_batch_to_run", "get_new_batch_prefill", "run_batch", "process_batch_result",
    "prepare_for_extend", "prepare_for_decode", "forward", "forward_cuda",
    "forward_extend", "forward_decode", "_forward_raw", "match_prefix", "cache_finished_req",
}

def inspect(path, package, output):
    data = (package / path).read_bytes()
    saved = output / "wheel-source" / path
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_bytes(data)
    result = dict(path=path, wheel_sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
    url = f"https://raw.githubusercontent.com/sgl-project/sglang/{COMMIT}/python/sglang/{path}"
    result["url"] = url
    try:
        upstream = urllib.request.urlopen(url, timeout=30).read()
        result["upstream_sha256"] = hashlib.sha256(upstream).hexdigest()
        result["matches_upstream"] = upstream == data
    except Exception as e:
        result["upstream_error"] = str(e)
        result["matches_upstream"] = False
    result["symbols"] = []
    tree = ast.parse(data)
    def walk(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + child.name
                if child.name in NAMES:
                    result["symbols"].append(dict(name=name, line=child.lineno, end_line=child.end_lineno))
                walk(child, name + ".")
            else:
                walk(child, prefix)
    walk(tree)
    return result

def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    package = Path(md.distribution("sglang").locate_file("sglang"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda p: inspect(p, package, output), PATHS))
    result = dict(version=md.version("sglang"), tag="v0.5.2", commit=COMMIT,
                  evidence="installed_source_and_upstream_comparison", model_execution=False,
                  all_match=all(r["matches_upstream"] for r in records), files=records)
    (output / "source-map.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ("version", "commit", "all_match")}))
    for r in records:
        print(r["path"], r["matches_upstream"], r.get("upstream_error", ""))
    return 0 if result["all_match"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
