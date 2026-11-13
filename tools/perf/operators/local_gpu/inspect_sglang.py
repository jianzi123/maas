"""Inspect the isolated engine and existing HF snapshot without fetching weights."""
import hashlib
import importlib.metadata as md
import json
from pathlib import Path
import sys

from packaging.requirements import Requirement


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    result = {"python": sys.version, "prefix": sys.prefix, "packages": {}, "dependencies": []}
    for name in ("sglang", "sgl-kernel", "torch", "triton", "transformers", "flashinfer-python",
                 "outlines", "xgrammar", "torchao", "numpy", "compressed-tensors"):
        try:
            d = md.distribution(name)
            result["packages"][name] = {"version": d.version, "location": str(d.locate_file(""))}
        except md.PackageNotFoundError:
            result["packages"][name] = None
    for line in md.requires("sglang"):
        r = Requirement(line)
        if r.marker and not any(r.marker.evaluate({"extra": extra}) for extra in ("", "srt", "runtime-common")):
            continue
        try:
            installed = md.version(r.name)
        except md.PackageNotFoundError:
            installed = None
        result["dependencies"].append(dict(requirement=line, installed=installed,
                                           satisfies=installed is not None and installed in r.specifier))
    root = Path.home() / ".cache/huggingface/hub/models--HuggingFaceTB--SmolLM-135M-Instruct"
    snapshots = []
    for snapshot in sorted((root / "snapshots").glob("*")):
        files = [p for p in snapshot.iterdir() if p.is_file()]
        config = json.loads((snapshot / "config.json").read_text())
        snapshots.append(dict(path=str(snapshot), revision=snapshot.name,
                              weight_files_present=any(p.suffix in (".safetensors", ".bin", ".pt") for p in files),
                              dangling_links=[p.name for p in snapshot.iterdir() if p.is_symlink() and not p.exists()],
                              config={k: config.get(k) for k in ("architectures", "model_type", "hidden_size",
                                      "intermediate_size", "num_hidden_layers", "num_attention_heads",
                                      "num_key_value_heads", "max_position_embeddings", "torch_dtype")},
                              files=[dict(name=p.name, bytes=p.stat().st_size, sha256=sha(p)) for p in files]))
    result["existing_snapshots"] = snapshots
    package = Path(md.distribution("sglang").locate_file("sglang"))
    paths = ["srt/entrypoints/engine.py", "srt/managers/scheduler.py", "srt/managers/tokenizer_manager.py",
             "srt/managers/schedule_batch.py", "srt/model_executor/model_runner.py",
             "srt/mem_cache/radix_cache.py", "srt/layers/attention/triton_backend.py",
             "srt/layers/layernorm.py", "srt/models/llama.py"]
    result["source_files"] = [{"path": p, "sha256": sha(package / p)} for p in paths]
    (output / "environment.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
