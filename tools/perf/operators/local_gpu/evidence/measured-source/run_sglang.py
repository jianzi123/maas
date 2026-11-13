"""Offline preflight and bounded SGLang generation; no automatic model fetch."""
import argparse
import importlib.metadata as md
import json
import os
from pathlib import Path
import time
import traceback

def weights_present(model):
    indices = list(model.glob("*.index.json"))
    if indices:
        shards = set()
        for index in indices:
            shards.update(json.loads(index.read_text()).get("weight_map", {}).values())
        return bool(shards) and all((model / name).is_file() for name in shards)
    return any(p.is_file() for p in model.glob("*.safetensors")) or (model / "pytorch_model.bin").is_file()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model-path", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--run", action="store_true")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    dest = args.output / "engine.json"
    if dest.exists():
        raise FileExistsError("use a fresh output directory")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
                      TOKENIZERS_PARALLELISM="false")
    os.environ["TRITON_CACHE_DIR"] = str(args.output / "triton-cache")
    os.environ["CUDA_CACHE_PATH"] = str(args.output / "cuda-cache")
    report = dict(sglang=md.version("sglang"), model_path=str(args.model_path),
                  offline=True, run_requested=args.run, generation_executed=False,
                  weights_present=weights_present(args.model_path), requests=[])
    engine = None
    try:
        import torch
        from sglang.srt.entrypoints.engine import Engine
        report["engine_import"] = "passed"
        report["torch"] = torch.__version__
        report["free_total_bytes"] = torch.cuda.mem_get_info()
        if not report["weights_present"]:
            report["status"] = "blocked_missing_model_weights"
            return 2
        if not args.run:
            report["status"] = "preflight_passed_generation_not_requested"
            return 0
        if report["free_total_bytes"][0] < 3 * 1024**3:
            raise RuntimeError("less than 3GiB free; stop without reclaiming others' memory")
        engine = Engine(model_path=str(args.model_path), tokenizer_path=str(args.model_path),
                        dtype="float16", trust_remote_code=False, tp_size=1,
                        attention_backend="triton", sampling_backend="pytorch",
                        disable_cuda_graph=True, mem_fraction_static=0.30,
                        max_total_tokens=2048, context_length=1024, max_running_requests=2,
                        random_seed=20261113, log_level="warning")
        prompt = "The capital of France is"
        sampling = dict(temperature=0.0, max_new_tokens=32, ignore_eos=True)
        for _ in range(2):
            engine.generate(prompt, sampling)
        for i in range(6):
            t = time.perf_counter()
            first = None
            final = None
            events = 0
            for item in engine.generate(prompt, sampling, stream=True):
                events += 1
                if first is None and item.get("text"):
                    first = time.perf_counter() - t
                final = item
            elapsed = time.perf_counter() - t
            meta = (final or {}).get("meta_info", {})
            tokens = meta.get("completion_tokens")
            report["requests"].append(dict(index=i, e2e_s=elapsed, first_visible_content_s=first,
                engine_reported_output_tokens=tokens, stream_events=events, text=(final or {}).get("text"),
                visible_tpot_proxy_s=((elapsed-first)/(tokens-1) if first is not None and tokens and tokens > 1 else None),
                meta=meta))
        report.update(status="completed", generation_executed=True)
        return 0
    except Exception as e:
        report.update(status="failed", error=repr(e), traceback=traceback.format_exc())
        return 2
    finally:
        if engine is not None:
            engine.shutdown()
        dest.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))

if __name__ == "__main__":
    raise SystemExit(main())
