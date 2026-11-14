"""Native ModelRunner + DummyModelLoader structural capture/replay study.

No pretrained weights, full Engine, online scheduler or serving is claimed.
Original bench Req/ScheduleBatch/ForwardBatch helpers are used.
"""

import os

os.environ.update(
    HF_HUB_OFFLINE="1",
    TRANSFORMERS_OFFLINE="1",
    HF_DATASETS_OFFLINE="1",
    TOKENIZERS_PARALLELISM="false",
)
import argparse, fcntl, hashlib, importlib.metadata as md, json, traceback, time
from pathlib import Path


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--output", type=Path, required=True)
    a.add_argument("--source-lock", type=Path, required=True)
    a.add_argument("--profile", action="store_true")
    args = a.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    guard = Path("/var/tmp/maas-10-gpu-01a1a5ba/gpu0-research.lock").open("a")
    fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
    report = {
        "scope": "actual native ModelRunner / original batch helpers / original CudaGraphRunner",
        "weights": "artificial random weights via native DummyModelLoader",
        "pretrained_weights": False,
        "weight_download": False,
        "semantic_quality_claim": False,
        "Engine_constructed": False,
        "online_scheduler_or_serving": False,
        "ModelRunner_constructed": False,
        "records": [],
        "pool_checks": [],
        "rope_observations": [],
        "kv_observations": [],
        "instrumentation": "extra eager references/sync/poison/CPU snapshots; no performance baseline claim",
    }
    runner = None
    hooks = []
    try:
        import torch, numpy as np

        torch.set_grad_enabled(False)
        torch.cuda.set_device(0)
        if torch.cuda.mem_get_info()[0] < 1024**3:
            raise RuntimeError("less than1GiB free")
        torch.cuda.set_per_process_memory_fraction(0.20)
        package = Path(md.distribution("sglang").locate_file("sglang"))
        lock = json.loads(args.source_lock.read_text())
        for row in lock["files"]:
            if (
                not row["official_match"]
                or hashlib.sha256((package / row["path"]).read_bytes()).hexdigest()
                != row["sha256"]
            ):
                raise ValueError("framework source mismatch")
        report.update(
            torch=torch.__version__,
            cuda=torch.version.cuda,
            sglang=md.version("sglang"),
            sgl_kernel=md.version("sgl-kernel"),
            device=torch.cuda.get_device_name(),
            source_commit=lock["commit"],
            source_files=len(lock["files"]),
            runner_source_sha256=hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        )
        import sglang.bench_one_batch as bench
        from sglang.srt.server_args import ServerArgs, PortArgs
        from sglang.srt.entrypoints.engine import _set_envs_and_config
        from sglang.srt.model_loader.loader import DummyModelLoader

        model = (
            Path.home()
            / ".cache/huggingface/hub/models--HuggingFaceTB--SmolLM-135M-Instruct/snapshots/fcc320f490e08fdb4b99d935b2c58d40bf35b0d0"
        )
        if not (model / "config.json").is_file():
            raise FileNotFoundError("existing local config missing")
        report["local_files"] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in model.iterdir()
            if p.is_file() and p.suffix in (".json", ".txt", ".model")
        }
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
        report["caps"] = {
            "allocator_fraction": 0.20,
            "planner_mem_fraction_static": 0.20,
            "max_total_tokens": 512,
            "context_length": 128,
            "max_batch": 8,
            "capture_bs": [1, 2, 4, 8],
            "outer_timeout_s": 600,
        }
        _set_envs_and_config(sa)
        torch.cuda.set_per_process_memory_fraction(0.20)
        original_loader = DummyModelLoader.load_model

        def observed_loader(self, *aa, **kw):
            loaded = original_loader(self, *aa, **kw)
            report["native_dummy_loader_called"] = True
            return loaded

        DummyModelLoader.load_model = observed_loader
        started = time.perf_counter()
        try:
            runner, tokenizer = bench.load_model(sa, PortArgs.init_new(sa), 0)
        finally:
            DummyModelLoader.load_model = original_loader
        report["ModelRunner_constructed"] = True
        g = runner.graph_runner
        if g is None:
            raise AssertionError("native graph runner missing")
        report.update(
            model_type=type(runner.model).__name__,
            parameter_count=sum(p.numel() for p in runner.model.parameters()),
            graph_type=type(g).__name__,
            captured_sizes=sorted(g.graphs),
            setup_s=time.perf_counter() - started,
            backend=type(runner.attn_backend).__name__,
            engine_default_kv_splits=runner.server_args.triton_attention_num_kv_splits,
        )
        if report["engine_default_kv_splits"] != 8:
            raise AssertionError("default cap changed")
        stable = {
            name: getattr(g, name).data_ptr()
            for name in ("input_ids", "seq_lens", "out_cache_loc", "req_pool_indices")
        }

        def rope_hook(module, inputs, output):
            if len(report["rope_observations"]) >= 4:
                return
            q, k = inputs[1:3]
            report["rope_observations"].append(
                {
                    "class": type(module).__name__,
                    "q_shape": list(q.shape),
                    "q_stride": list(q.stride()),
                    "k_shape": list(k.shape),
                    "k_stride": list(k.stride()),
                    "dtype": str(q.dtype),
                    "q_output_alias": output[0].data_ptr() == q.data_ptr(),
                    "k_output_alias": output[1].data_ptr() == k.data_ptr(),
                    "scope": "eager native module caller; hooks installed AFTER graph capture",
                }
            )

        for module in runner.model.modules():
            if "RotaryEmbedding" in type(module).__name__:
                hooks.append(module.register_forward_hook(rope_hook))
        pool = runner.token_to_kv_pool
        original_kv = pool.set_kv_buffer

        def kv_observer(layer, loc, k, v, *aa, **kw):
            if len(report["kv_observations"]) < 4:
                report["kv_observations"].append(
                    {
                        "layer": layer.layer_id,
                        "tokens": loc.numel(),
                        "k_shape": list(k.shape),
                        "k_stride": list(k.stride()),
                        "dtype": str(k.dtype),
                        "scope": "eager actual MHATokenToKVPool caller",
                    }
                )
            result = original_kv(layer, loc, k, v, *aa, **kw)
            if "manual_mature_KV_probe" not in report:
                # Independent destination, ACTUAL native QKV view input. This is
                # an explicit manual probe, not evidence default caller uses it.
                probe = {
                    "scope": "manual direct op on actual layer0 prefill view; NOT default caller",
                    "k_shape": list(k.shape),
                    "k_stride": list(k.stride()),
                    "input_contiguous": k.is_contiguous(),
                    "fallback_used": False,
                }
                kc = torch.full_like(pool.get_key_buffer(layer.layer_id), float("nan"))
                vc = torch.full_like(
                    pool.get_value_buffer(layer.layer_id), float("nan")
                )
                try:
                    with torch.profiler.profile(
                        activities=[
                            torch.profiler.ProfilerActivity.CPU,
                            torch.profiler.ProfilerActivity.CUDA,
                        ]
                    ) as manual_prof:
                        torch.ops.sgl_kernel.store_kv_cache(kc, vc, loc, k, v)
                        torch.cuda.synchronize()
                    torch.testing.assert_close(kc[loc], k, rtol=0, atol=0)
                    torch.testing.assert_close(vc[loc], v, rtol=0, atol=0)
                    manual_prof.export_chrome_trace(
                        str(args.output / "manual-mature-view.json")
                    )
                    data = json.loads(
                        (args.output / "manual-mature-view.json").read_text()
                    )
                    probe.update(
                        status="supported_bitwise_equal",
                        kernel_names=sorted(
                            {
                                e["name"]
                                for e in data["traceEvents"]
                                if e.get("cat") == "kernel"
                            }
                        ),
                        kernel_count=sum(
                            e.get("cat") == "kernel" for e in data["traceEvents"]
                        ),
                        op_counts={e.key: e.count for e in manual_prof.key_averages()},
                    )
                except RuntimeError as exc:
                    if not any(
                        word in str(exc).lower()
                        for word in ("contiguous", "divisible", "dtype")
                    ):
                        raise
                    probe.update(status="unsupported", error=str(exc))
                report["manual_mature_KV_probe"] = probe
            return result

        pool.set_kv_buffer = kv_observer
        native_forward = runner.forward
        current_label = ["setup"]
        from torch.profiler import record_function, profile, ProfilerActivity

        def observed_forward(fb, *aa, **kw):
            mode = fb.forward_mode
            if not mode.is_decode():
                return native_forward(fb, *aa, **kw)
            raw_bs = fb.batch_size
            wanted = next(bs for bs in sorted(g.graphs) if bs >= raw_bs)
            g.output_buffers[wanted].next_token_logits.fill_(float("nan"))
            # Poison reusable attention scratch; valid programs must overwrite it.
            for name in ("cuda_graph_attn_logits", "cuda_graph_attn_lse"):
                tensor = getattr(runner.attn_backend, name, None)
                if tensor is not None:
                    tensor.fill_(float("nan"))
            with record_function("framework/" + current_label[0] + "/graph"):
                result, used_graph = native_forward(fb, *aa, **kw)
                torch.cuda.synchronize()
            logits = result.next_token_logits.detach().clone()
            if (
                not used_graph
                or logits.shape[0] != raw_bs
                or not torch.isfinite(logits).all()
            ):
                raise AssertionError("graph dispatch/finite/raw slicing failure")
            graph_splits = (
                runner.attn_backend.cuda_graph_num_kv_splits[: g.bs].cpu().tolist()
            )
            padded_lens = g.seq_lens[raw_bs : g.bs].cpu().tolist()
            padded_locs = g.out_cache_loc[raw_bs : g.bs].cpu().tolist()
            if padded_lens and any(x != g.seq_len_fill_value for x in padded_lens):
                raise AssertionError("bad padding seq lens")
            if any(padded_locs):
                raise AssertionError("padding overwrote non-dummy cache slot")
            saved = runner.graph_runner
            runner.graph_runner = None
            try:
                with record_function(
                    "framework/" + current_label[0] + "/eager_reference"
                ):
                    eager, eager_graph = native_forward(fb, *aa, **kw)
                    torch.cuda.synchronize()
            finally:
                runner.graph_runner = saved
            if eager_graph:
                raise AssertionError("eager control still used graph")
            torch.testing.assert_close(
                logits, eager.next_token_logits, rtol=0.02, atol=5e-7
            )
            if any(getattr(g, n).data_ptr() != p for n, p in stable.items()):
                raise AssertionError("graph input buffer reallocated")
            report["records"].append(
                {
                    "label": current_label[0],
                    "raw_batch": raw_bs,
                    "captured_batch": g.bs,
                    "padding": g.bs - raw_bs,
                    "seq_lens": fb.seq_lens.cpu().tolist(),
                    "graph_splits": graph_splits,
                    "eager_splits": runner.attn_backend.forward_metadata.num_kv_splits.cpu().tolist(),
                    "padding_seq_lens": padded_lens,
                    "padding_cache_locations": padded_locs,
                    "max_abs_graph_eager": (
                        logits.float() - eager.next_token_logits.float()
                    )
                    .abs()
                    .max()
                    .item(),
                    "logit_max_abs": logits.abs().max().item(),
                    "logits_sha256": hashlib.sha256(
                        logits.cpu().contiguous().view(torch.uint8).numpy().tobytes()
                    ).hexdigest(),
                    "output_aliases_native_graph_buffer": result.next_token_logits.data_ptr()
                    == g.output_buffers[g.bs].next_token_logits.data_ptr(),
                    "scratch_poison_gate_passed": True,
                    "input_buffers_stable": True,
                }
            )
            return result, used_graph

        runner.forward = observed_forward

        def sizes():
            return {
                "req_free": runner.req_to_token_pool.available_size(),
                "kv_free": runner.token_to_kv_pool_allocator.available_size(),
            }

        def free_indices(batch, indices):
            ids = batch.req_pool_indices.cpu().tolist()
            lens = batch.seq_lens.cpu().tolist()
            locations = [
                runner.req_to_token_pool.req_to_token[ids[i], : lens[i]].clone()
                for i in indices
            ]
            all_loc = torch.cat(locations)
            if all_loc.unique().numel() != all_loc.numel() or not (all_loc > 0).all():
                raise AssertionError("invalid release mapping")
            runner.token_to_kv_pool_allocator.free(all_loc)
            runner.req_to_token_pool.free([ids[i] for i in indices])

        def scenario(bs, index):
            torch.cuda.synchronize()
            runner.req_to_token_pool.clear()
            runner.token_to_kv_pool_allocator.clear()
            before = sizes()
            np.random.seed(20261114 + index)
            reqs = bench.prepare_synthetic_inputs_for_latency_test(bs, 12)
            ids, _, batch = bench.extend(reqs, runner)
            for step in range(2):
                current_label[0] = f"bs{bs}/step{step}"
                forced = (
                    torch.arange(bs, device="cuda", dtype=torch.int64)
                    + 123
                    + index * 17
                    + step * 31
                )
                ids, _ = bench.decode(forced, batch, runner)
            if bs == 8:
                for keep in (3, 1):
                    remove = list(range(keep, len(batch.reqs)))
                    free_indices(batch, remove)
                    batch.output_ids = ids
                    batch.filter_batch(keep_indices=list(range(keep)))
                    current_label[0] = f"shrink{keep}/step"
                    ids, _ = bench.decode(
                        torch.arange(keep, device="cuda", dtype=torch.int64)
                        + 333
                        + keep,
                        batch,
                        runner,
                    )
            free_indices(batch, list(range(len(batch.reqs))))
            torch.cuda.synchronize()
            after = sizes()
            if before != after:
                raise AssertionError("native pool release did not reconcile")
            report["pool_checks"].append(
                {
                    "initial_batch": bs,
                    "before": before,
                    "after": after,
                    "reconciled": True,
                }
            )

        # Trace only the B3/pad4 case. Other batches retain numerical/lifecycle gates.
        prof = None
        for index, bs in enumerate((1, 3, 2, 5, 8)):
            if args.profile and bs == 3:
                with profile(
                    activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA],
                    record_shapes=True,
                ) as prof:
                    scenario(bs, index)
            elif bs == 2:
                user_stream = torch.cuda.Stream()
                with torch.cuda.stream(user_stream):
                    scenario(bs, index)
                user_stream.synchronize()
                report["native_nondefault_stream_scenario_passed"] = True
            else:
                scenario(bs, index)
        if prof is not None:
            prof.export_chrome_trace(str(args.output / "timeline.json"))
            tr = json.loads((args.output / "timeline.json").read_text())
            kernels = [e for e in tr["traceEvents"] if e.get("cat") == "kernel"]
            report["native_op_counts"] = {
                e.key: e.count for e in prof.key_averages() if "sgl_kernel::" in e.key
            }
            report["actual_kernel_names"] = sorted({e["name"] for e in kernels})
            report["kernel_counts"] = len(kernels)
            report["profile_scope"] = (
                "B3/pad4 only; instrumentation/reference sync, no performance baseline"
            )
        if len(report["records"]) != 12 or {
            r["captured_batch"] for r in report["records"]
        } != {1, 2, 4, 8}:
            raise AssertionError("missing dynamic replay cases")
        if len({r["logits_sha256"] for r in report["records"]}) < 3:
            raise AssertionError("no observed input-sensitive outputs")
        report.update(
            status="passed",
            peak_torch_bytes=torch.cuda.max_memory_allocated(),
            semantic_quality_claim=False,
        )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "ModelRunner": True,
                    "Engine": False,
                    "replay_cases": len(report["records"]),
                    "captured_sizes": report["captured_sizes"],
                    "peak_torch_bytes": report["peak_torch_bytes"],
                }
            ),
            flush=True,
        )
        return 0
    except Exception as exc:
        report.update(
            status="failed", error=repr(exc), traceback=traceback.format_exc()
        )
        print(traceback.format_exc(), flush=True)
        return 2
    finally:
        save(args.output / "framework.json", report)
        for hook in hooks:
            hook.remove()
        try:
            import torch.distributed as dist

            if dist.is_initialized():
                dist.destroy_process_group()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
