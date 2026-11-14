"""Offline structural probe using original bench.load_model / extend / decode."""

import os

os.environ.update(
    HF_HUB_OFFLINE="1",
    TRANSFORMERS_OFFLINE="1",
    HF_DATASETS_OFFLINE="1",
    TOKENIZERS_PARALLELISM="false",
)
import argparse, fcntl, json, traceback, time, hashlib
from pathlib import Path


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--output", type=Path, required=True)
    args = a.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    lock = Path("/var/tmp/maas-10-gpu-01a1a5ba/gpu0-research.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    report = {
        "weights": "artificial_random_native_DummyModelLoader",
        "pretrained_weights": False,
        "network_model_download": False,
        "Engine_constructed": False,
        "ModelRunner_constructed": False,
    }
    try:
        import torch

        torch.set_grad_enabled(False)
        torch.cuda.set_device(0)
        if torch.cuda.mem_get_info()[0] < 1024**3:
            raise RuntimeError("less than1GiB free")
        torch.cuda.set_per_process_memory_fraction(0.20)
        import sglang.bench_one_batch as bench
        from sglang.srt.server_args import ServerArgs, PortArgs
        from sglang.srt.entrypoints.engine import _set_envs_and_config

        model = (
            Path.home()
            / ".cache/huggingface/hub/models--HuggingFaceTB--SmolLM-135M-Instruct/snapshots/fcc320f490e08fdb4b99d935b2c58d40bf35b0d0"
        )
        if not (model / "config.json").is_file():
            raise FileNotFoundError("existing local config missing")
        report["config_sha256"] = hashlib.sha256(
            (model / "config.json").read_bytes()
        ).hexdigest()
        config = json.loads((model / "config.json").read_text())
        report["model_architecture"] = config["architectures"]
        sa = ServerArgs(
            model_path=str(model),
            tokenizer_path=str(model),
            load_format="dummy",
            dtype="float16",
            device="cuda",
            tp_size=1,
            mem_fraction_static=0.20,
            max_total_tokens=512,
            context_length=128,
            max_running_requests=8,
            attention_backend="triton",
            sampling_backend="pytorch",
            cuda_graph_bs=[1, 2, 4, 8],
            cuda_graph_max_bs=8,
            disable_overlap_schedule=True,
            disable_custom_all_reduce=True,
            random_seed=20261114,
            trust_remote_code=False,
            log_level="warning",
        )
        report["requested"] = {
            "allocator_fraction": 0.20,
            "planner_mem_fraction_static": 0.20,
            "max_total_tokens": 512,
            "context_length": 128,
            "capture_bs": [1, 2, 4, 8],
            "max_running_requests": 8,
            "load_format": "dummy",
            "attention_backend": "triton",
        }
        _set_envs_and_config(sa)
        torch.cuda.set_per_process_memory_fraction(0.20)
        start = time.perf_counter()
        runner, tokenizer = bench.load_model(sa, PortArgs.init_new(sa), 0)
        report.update(
            ModelRunner_constructed=True,
            runner_type=type(runner).__name__,
            model_type=type(runner.model).__name__,
            parameter_count=sum(p.numel() for p in runner.model.parameters()),
            setup_s=time.perf_counter() - start,
            capture_sizes=(
                list(runner.graph_runner.graphs) if runner.graph_runner else []
            ),
        )
        reqs = bench.prepare_synthetic_inputs_for_latency_test(3, 12)
        ids, logits, batch = bench.extend(reqs, runner)
        report["prefill_finite"] = bool(torch.isfinite(logits).all())
        ids, logits = bench.decode(ids, batch, runner)
        torch.cuda.synchronize()
        report.update(
            decode_finite=bool(torch.isfinite(logits).all()),
            logits_shape=list(logits.shape),
            captured_batch_size=runner.graph_runner.bs,
            raw_batch_size=runner.graph_runner.raw_bs,
            peak_torch_bytes=torch.cuda.max_memory_allocated(),
            status="passed",
        )
        print(json.dumps(report), flush=True)
        return 0
    except Exception as exc:
        report.update(
            status="failed", error=repr(exc), traceback=traceback.format_exc()
        )
        print(traceback.format_exc(), flush=True)
        return 2
    finally:
        (args.output / "probe.json").write_text(json.dumps(report, indent=2) + "\n")
        try:
            import torch.distributed as dist

            if dist.is_initialized():
                dist.destroy_process_group()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
