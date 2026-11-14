"""Unprofiled native-forward call-cost study, artificial weights only.

No reference/poison/observer/snapshot inside timed rounds. Static native
ForwardBatch repeated; no semantic or serving throughput claim.
"""

import os

os.environ.update(
    HF_HUB_OFFLINE="1",
    TRANSFORMERS_OFFLINE="1",
    HF_DATASETS_OFFLINE="1",
    TOKENIZERS_PARALLELISM="false",
)
import argparse, fcntl, json, hashlib, time, contextlib
from pathlib import Path


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--variant", choices=("native", "mature"), required=True)
    a.add_argument("--output", type=Path, required=True)
    a.add_argument("--pair", type=int, required=True)
    args = a.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    lock = Path("/var/tmp/maas-10-gpu-01a1a5ba/gpu0-research.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    import torch, numpy as np, importlib.metadata as md
    from native_kv_binding import mature_kv_binding
    from run_decode import telemetry, verify_sources

    torch.set_grad_enabled(False)
    torch.cuda.set_device(0)
    if torch.cuda.mem_get_info()[0] < 1024**3:
        raise RuntimeError("less than1GiB free")
    torch.cuda.set_per_process_memory_fraction(0.20)
    verify_sources(
        json.loads(Path(__file__).with_name("decode-source-lock.json").read_text())
    )
    stack = contextlib.ExitStack()
    runner = None
    try:
        if args.variant == "mature":
            stack.enter_context(mature_kv_binding())
        import sglang.bench_one_batch as bench
        from sglang.srt.server_args import ServerArgs, PortArgs
        from sglang.srt.entrypoints.engine import _set_envs_and_config

        model = (
            Path.home()
            / ".cache/huggingface/hub/models--HuggingFaceTB--SmolLM-135M-Instruct/snapshots/fcc320f490e08fdb4b99d935b2c58d40bf35b0d0"
        )
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
        _set_envs_and_config(sa)
        torch.cuda.set_per_process_memory_fraction(0.20)
        torch.manual_seed(20261114)
        runner, _ = bench.load_model(sa, PortArgs.init_new(sa), 0)
        param = next(runner.model.parameters()).flatten()[:1024].detach().cpu()
        report = {
            "variant": args.variant,
            "pair": args.pair,
            "scope": "native_forward_call_cost_with_artificial_weights",
            "weights": "native_dummy_random",
            "Engine": False,
            "pretrained_performance_claim": False,
            "sampler_scheduler_serving_in_timing": False,
            "profiler_or_correctness_hooks_in_timing": False,
            "warmup": 10,
            "rounds": 9,
            "iterations": 10,
            "parameter_sample_sha256": hashlib.sha256(
                param.view(torch.uint8).numpy().tobytes()
            ).hexdigest(),
            "torch": torch.__version__,
            "sglang": md.version("sglang"),
            "telemetry_before": telemetry(),
            "code_sha256": {
                n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
                for n in ("bench_native_kv.py", "native_kv_binding.py")
            },
            "measurements": [],
        }
        for bs in (3, 5, 8):
            torch.cuda.synchronize()
            runner.req_to_token_pool.clear()
            runner.token_to_kv_pool_allocator.clear()
            np.random.seed(20261114 + bs)
            reqs = bench.prepare_synthetic_inputs_for_latency_test(bs, 12)
            ids, _, batch = bench.extend(reqs, runner)
            batch.output_ids = torch.arange(bs, device="cuda", dtype=torch.int64) + 321
            batch.prepare_for_decode()
            bench._maybe_prepare_mlp_sync_batch(batch, runner)
            fb = bench.ForwardBatch.init_new(batch.get_model_worker_batch(), runner)
            output, graph = runner.forward(fb)
            torch.cuda.synchronize()
            if not graph or not torch.isfinite(output.next_token_logits).all():
                raise AssertionError("initial graph invalid")
            fingerprint = hashlib.sha256(
                output.next_token_logits.detach()
                .cpu()
                .contiguous()
                .view(torch.uint8)
                .numpy()
                .tobytes()
            ).hexdigest()
            for _ in range(10):
                runner.forward(fb)
            torch.cuda.synchronize()
            begin, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(
                enable_timing=True
            )
            begin.record()
            end.record()
            end.synchronize()
            rows = []
            for round_id in range(9):
                t = time.perf_counter_ns()
                begin.record()
                for _ in range(10):
                    runner.forward(fb)
                end.record()
                end.synchronize()
                rows.append(
                    {
                        "round": round_id,
                        "event_with_host_gaps_us_per_call": begin.elapsed_time(end)
                        * 1000
                        / 10,
                        "wall_with_sync_us_per_call": (time.perf_counter_ns() - t)
                        / 1000
                        / 10,
                    }
                )
            if not torch.isfinite(output.next_token_logits).all():
                raise AssertionError("post timing nonfinite")
            report["measurements"].append(
                {
                    "batch": bs,
                    "capture_batch": runner.graph_runner.bs,
                    "logits_sha256": fingerprint,
                    "samples": rows,
                    "telemetry_after": telemetry(),
                }
            )
            print(
                json.dumps(
                    {
                        "variant": args.variant,
                        "pair": args.pair,
                        "batch": bs,
                        "timing_completed": True,
                    }
                ),
                flush=True,
            )
        report["peak_torch_bytes"] = torch.cuda.max_memory_allocated()
        report["caveats"] = [
            "events include Python/driver launch gaps, not pure GPU kernel durations",
            "artificial weights/native static batch call cost; not pretrained model performance or serving throughput",
            "shared unlocked desktop; process pairs sequential, not statistical significance proof",
            "no sampling/poison/reference in timed rounds; initialization and capture excluded",
        ]
        (args.output / "cost.json").write_text(json.dumps(report, indent=2) + "\n")
        return 0
    finally:
        stack.close()
        import torch.distributed as dist

        if dist.is_initialized():
            dist.destroy_process_group()


if __name__ == "__main__":
    raise SystemExit(main())
