"""Opt-in E-LIT-01: frozen three-policy pilot; old Window B entry is untouched.

Full cluster wall includes interventions; individual CUDA-event/host blocks do not.
Artificial weights/static native calls only. No model/serving speedup claim.
"""
import argparse
import contextlib
import hashlib
import importlib.metadata as md
import json
import os
from pathlib import Path
import statistics
import time
import uuid

from cadence_protocol import load_plan, digest, write_json, match_error

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_DATASETS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", type=Path, required=True, help="immutable cadence_protocol create output")
    p.add_argument("--run-id", required=True, choices=("R01", "R02"))
    p.add_argument("--output", type=Path, required=True, help="new directory; never overwrite")
    p.add_argument("--validate-only", action="store_true", help="validate metadata/source bytes without CUDA imports")
    args = p.parse_args()
    plan = load_plan(args.plan)
    clusters = [c for c in plan["schedule"] if c["run_id"] == args.run_id]
    if args.validate_only:
        print(json.dumps({"validated": True, "run_id": args.run_id, "clusters": len(clusters),
                          "blocks": sum(len(c["blocks"]) for c in clusters), "GPU_imports": False}))
        return 0
    if os.name != "posix":
        raise RuntimeError("GPU execution requires the authorized Linux/WSL environment")
    args.output.mkdir(parents=True, exist_ok=False)
    config = plan["config"]
    cap = config["resource_caps"]
    started = time.perf_counter()
    clock = f"{plan['experiment']}/{args.run_id}/pid{os.getpid()}-{uuid.uuid4().hex[:8]}"
    records, emitted, query_events, gates, cluster_reports, cells = {}, set(), [], [], [], []
    queries_emitted = 0
    guard = None
    torch = None
    failure = None
    current_cluster = None
    cluster_start = None
    stage = "lock"
    plan_sha = digest(plan)
    runtime = None

    def check_deadline():
        if time.perf_counter() - started >= cap["internal_stop_seconds"]:
            raise RuntimeError("deadline: stopped before external600s limit")

    def emit():
        nonlocal queries_emitted
        with (args.output / "blocks.jsonl").open("a", encoding="utf-8") as f:
            for key, row in records.items():
                if key not in emitted:
                    f.write(json.dumps(row, allow_nan=False) + "\n")
                    emitted.add(key)
            f.flush()
            os.fsync(f.fileno())
        with (args.output / "queries.jsonl").open("a", encoding="utf-8") as f:
            for row in query_events[queries_emitted:]:
                f.write(json.dumps(row, allow_nan=False) + "\n")
            queries_emitted = len(query_events)
            f.flush()
            os.fsync(f.fileno())
        write_json(args.output / "gates.json", gates)
        write_json(args.output / "clusters.json", cluster_reports)
        write_json(args.output / "cells.json", cells)

    try:
        import fcntl
        guard = Path(cap["research_lock"]).open("a")
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stage = "setup"
        import torch
        import numpy as np
        from native_kv_binding import mature_kv_binding
        from run_decode import telemetry, verify_sources
        from bench_kv_interleaved import host_state, sha
        from sglang.srt.model_executor.cuda_graph_runner import CudaGraphRunner, set_global_graph_memory_pool
        import sglang.bench_one_batch as bench
        from sglang.srt.server_args import ServerArgs, PortArgs
        from sglang.srt.entrypoints.engine import _set_envs_and_config

        torch.set_grad_enabled(False)
        torch.cuda.set_device(0)
        torch.cuda.set_per_process_memory_fraction(cap["allocator_fraction"])

        def resources():
            check_deadline()
            free, total = torch.cuda.mem_get_info()
            if free < cap["min_free_bytes"] or torch.cuda.memory_reserved() > total * cap["allocator_fraction"]:
                raise RuntimeError("resource_limit")
            return {"free_bytes": free, "total_bytes": total,
                    "allocated_bytes": torch.cuda.memory_allocated(),
                    "reserved_bytes": torch.cuda.memory_reserved()}

        resources()
        verify_sources(json.loads(Path(__file__).with_name("decode-source-lock.json").read_text()))
        package = Path(md.distribution("sglang").locate_file("sglang"))
        source_lock = json.loads((Path(__file__).parent / "evidence/framework-v0.18/framework-source-lock.json").read_text())
        for row in source_lock["files"]:
            if not row["official_match"] or sha(package / row["path"]) != row["sha256"]:
                raise RuntimeError("identity_error: framework source")
        model = Path.home() / ".cache/huggingface/hub/models--HuggingFaceTB--SmolLM-135M-Instruct/snapshots/fcc320f490e08fdb4b99d935b2c58d40bf35b0d0"
        sa = ServerArgs(model_path=str(model), tokenizer_path=str(model), load_format="dummy",
            dtype="float16", device="cuda", tp_size=1, mem_fraction_static=.20,
            max_total_tokens=512, context_length=128, max_running_requests=8,
            attention_backend="triton", sampling_backend="pytorch", cuda_graph_bs=[1, 2, 4, 8],
            cuda_graph_max_bs=8, disable_overlap_schedule=True, disable_custom_all_reduce=True,
            random_seed=20261114, trust_remote_code=False, log_level="warning")
        _set_envs_and_config(sa)
        torch.cuda.set_per_process_memory_fraction(.20)
        torch.manual_seed(20261114)
        runner, _ = bench.load_model(sa, PortArgs.init_new(sa), 0)
        contexts = {"native": (runner.attn_backend, runner.graph_runner)}
        backend = type(runner.attn_backend)(runner)
        runner.attn_backend = backend
        set_global_graph_memory_pool(torch.cuda.graph_pool_handle())
        with mature_kv_binding():
            graph = CudaGraphRunner(runner)
        contexts["mature"] = (backend, graph)
        if runner.server_args.triton_attention_num_kv_splits != 8:
            raise RuntimeError("identity_error: split cap")
        if any(len(m._forward_hooks) for m in runner.model.modules()):
            raise RuntimeError("identity_error: unexpected hook")

        def graph_identity():
            return {v: {"graph_ids": {str(b): id(g) for b, g in cg.graphs.items()},
                "sizes": sorted(cg.graphs),
                "inputs": {n: getattr(cg, n).data_ptr() for n in
                           ("input_ids", "positions", "seq_lens", "out_cache_loc", "req_pool_indices")},
                "kv_indices_ptr": be.cuda_graph_kv_indices.data_ptr(),
                "scratch_ptr": be.cuda_graph_attn_logits.data_ptr()}
                for v, (be, cg) in contexts.items()}

        identity = graph_identity()
        for n in ("kv_indices_ptr", "scratch_ptr"):
            if identity["native"][n] == identity["mature"][n]:
                raise RuntimeError("identity_error: shared backend state")

        def parameters_digest():
            h = hashlib.sha256()
            for name, value in runner.model.named_parameters():
                h.update(name.encode())
                h.update(str((tuple(value.shape), str(value.dtype))).encode())
                h.update(value.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes())
            return h.hexdigest()

        parameter_sha = parameters_digest()

        def activate(v, fb):
            runner.attn_backend, runner.graph_runner = contexts[v]
            fb.attn_backend = runner.attn_backend

        def make_cell(bs):
            runner.attn_backend, runner.graph_runner = contexts["native"]
            torch.cuda.synchronize()
            runner.req_to_token_pool.clear()
            runner.token_to_kv_pool_allocator.clear()
            np.random.seed(20261114 + bs)
            reqs = bench.prepare_synthetic_inputs_for_latency_test(bs, 12)
            _, _, batch = bench.extend(reqs, runner)
            batch.output_ids = torch.arange(bs, device="cuda", dtype=torch.int64) + 321
            batch.prepare_for_decode()
            bench._maybe_prepare_mlp_sync_batch(batch, runner)
            return bench.ForwardBatch.init_new(batch.get_model_worker_batch(), runner)

        def input_digest(fb):
            h = hashlib.sha256()
            for name in ("input_ids", "positions", "seq_lens", "out_cache_loc", "req_pool_indices"):
                value = getattr(fb, name)
                h.update(name.encode())
                h.update(value.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes())
            return h.hexdigest()

        snapshot_dir = args.output / "snapshots"
        snapshot_dir.mkdir()

        def store_array(a):
            raw_sha = hashlib.sha256(a.tobytes()).hexdigest()
            key = digest({"raw_sha256": raw_sha, "shape": list(a.shape), "dtype": str(a.dtype)})
            target = snapshot_dir / (key + ".npz")
            if not target.exists():
                np.savez_compressed(target, value=a)
            return {"path": str(target.relative_to(args.output)), "raw_sha256": raw_sha,
                    "shape": list(a.shape), "dtype": str(a.dtype)}

        def gate(fb, cell_id, phase):
            saved = {}
            arrays = {}
            for v in ("native", "mature"):
                activate(v, fb)
                output, used_graph = runner.forward(fb)
                if not used_graph:
                    raise RuntimeError("identity_error: not graph")
                loc = fb.out_cache_loc[:fb.batch_size]
                if not ((loc > 0) & (loc <= 512)).all():
                    raise RuntimeError("identity_error: invalid real locations")
                kv = torch.stack([torch.stack((
                    runner.token_to_kv_pool.get_key_buffer(i).index_select(0, loc),
                    runner.token_to_kv_pool.get_value_buffer(i).index_select(0, loc)))
                    for i in range(runner.start_layer, runner.end_layer)])
                arrays[v] = (output.next_token_logits.detach().clone().cpu().numpy(), kv.cpu().numpy())
                saved[v] = [store_array(a) for a in arrays[v]]
            row = {"cell_id": cell_id, "phase": phase, "snapshots": saved,
                   "all30_layers": True, "status": "checking"}
            gates.append(row)
            for a, b in zip(arrays["native"], arrays["mature"]):
                if not np.isfinite(a).all() or not np.isfinite(b).all():
                    row["status"] = "failed"
                    raise RuntimeError("numerical_error: nonfinite")
                if a.dtype != b.dtype or a.shape != b.shape or a.tobytes() != b.tobytes():
                    row["status"] = "failed"
                    raise RuntimeError("numerical_error: state mismatch")
            row["status"] = "passed"

        def prepare(v, fb):
            activate(v, fb)
            runner.graph_runner.replay_prepare(fb)
            torch.cuda.synchronize()
            expected_cap = next(x for x in (1, 2, 4, 8) if x >= fb.batch_size)
            if runner.graph_runner.bs != expected_cap or graph_identity() != identity:
                raise RuntimeError("identity_error: graph or pointer changed")
            return runner.graph_runner.bs

        def query(qid, kind):
            q0 = time.perf_counter_ns()
            result = telemetry()
            q1 = time.perf_counter_ns()
            row = {"query_id": qid, "kind": kind, "clock_scope": clock,
                   "begin_ns": q0, "end_ns": q1, "duration_ns": q1 - q0, "result": result}
            query_events.append(row)
            if result.get("returncode") != 0 or not result.get("csv"):
                raise RuntimeError("query_error")
            return row

        # Calibrate before any comparison block. All20 queries are retained.
        stage = "calibration"
        calibration_fb = make_cell(3)
        gate(calibration_fb, "calibration/B3", "before_calibration")
        calibration = []
        for i in range(config["calibration_samples_per_variant"]):
            for v in ("native", "mature"):
                torch.cuda.synchronize()
                previous = time.perf_counter_ns()
                prepare(v, calibration_fb)
                ready = time.perf_counter_ns()
                q = query(f"{args.run_id}/cal/{v}/{i}", "calibration")
                submit_proxy = time.perf_counter_ns()
                calibration.append({"variant": v, "sample": i, "previous_done_ns": previous,
                    "ready_ns": ready, "query_id": q["query_id"], "submit_proxy_ns": submit_proxy,
                    "total_gap_ns": submit_proxy - previous,
                    "query_duration_ns": q["duration_ns"]})
        targets = {v: int(statistics.median(r["total_gap_ns"] for r in calibration if r["variant"] == v))
                   for v in ("native", "mature")}
        if any(not 0 < t <= config["max_calibrated_target_ns"] for t in targets.values()):
            raise RuntimeError("resource_limit: calibrated idle exceeds frozen bound")
        write_json(args.output / "calibration.json", calibration, exclusive=True)
        runtime = {"schema": "ELIT01-runtime-v1", "run_id": args.run_id, "clock_scope": clock,
            "plan_sha256": plan_sha, "execution_checkout_commit": plan["execution_checkout_commit"],
            "source_sha256": plan["source_sha256"], "graph_identity": identity,
            "parameter_full_sha256": parameter_sha, "targets_ns": targets,
            "calibration_sha256": digest(calibration),
            "versions": {n: md.version(n) for n in ("torch", "triton", "sglang", "sgl-kernel")},
            "torch_version": torch.__version__, "cuda": torch.version.cuda,
            "GPU": torch.cuda.get_device_name(0), "initial_resources": resources(),
            "match_clock": "host perf_counter; last observed own-device completion to pre-event submission",
            "not_a_physical_GPU_idle_counter": True,
            "primary_scope": config["primary_scope"], "primary_metric": config["primary_metric"],
            "frozen_at_monotonic_ns": time.perf_counter_ns(),
            "model_config_sha256": sha(model / "config.json"),
            "profile_in_clean_blocks": False, "status": "frozen_before_comparison"}
        runtime_sha = digest(runtime)
        write_json(args.output / "runtime-manifest.json", runtime, exclusive=True)
        emit()

        stage = "comparison"
        for scope in ("full", "bare_graph"):
            for bs in config["batches"]:
                check_deadline()
                cell_id = f"{args.run_id}/{scope}/B{bs}"
                fb = make_cell(bs)
                gate(fb, cell_id, "before")
                input_sha = input_digest(fb)
                cell = {"cell_id": cell_id, "scope": scope, "batch": bs,
                        "KV_context_length": 13, "input_sha256": input_sha,
                        "runtime_manifest_sha256": runtime_sha, "frozen_before_cell": True,
                        "frozen_at_monotonic_ns": time.perf_counter_ns()}
                cell_sha = digest(cell)
                cells.append(cell)
                write_json(args.output / "cells.json", cells)
                for v in ("native", "mature"):
                    activate(v, fb)
                    for _ in range(config["warmup_calls_per_variant_per_cell"]):
                        runner.forward(fb)
                torch.cuda.synchronize()
                previous_done = time.perf_counter_ns()
                previous_kind = "cell_warmup_completion"
                begin, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
                begin.record(); end.record(); end.synchronize()
                previous_done = time.perf_counter_ns()
                previous_kind = "event_warmup_completion"
                subset = [c for c in clusters if c["scope"] == scope and c["batch"] == bs]
                for c in subset:
                    check_deadline()
                    resource_before = resources()
                    host_before = host_state(torch)
                    current_cluster = c
                    cluster_start = time.perf_counter_ns()
                    for b in c["blocks"]:
                        check_deadline()
                        v = b["variant"]
                        capture_bs = prepare(v, fb)
                        ready = time.perf_counter_ns()
                        fn = (lambda: runner.forward(fb)) if scope == "full" else contexts[v][1].graphs[capture_bs].replay
                        q = None
                        sleep_start = sleep_end = None
                        requested_sleep = 0
                        if c["policy"] == "query_block" or (c["policy"] == "query_cluster" and b["slot"] == 0):
                            q = query(b["block_id"] + "/query", c["policy"])
                        elif c["policy"] == "idle_matched":
                            sleep_start = time.perf_counter_ns()
                            requested_sleep = max(0, previous_done + targets[v] - sleep_start)
                            if requested_sleep:
                                time.sleep(requested_sleep / 1e9)
                            sleep_end = time.perf_counter_ns()
                        submit = time.perf_counter_ns()
                        cpu0 = time.thread_time_ns()
                        begin.record()
                        last = None
                        for _ in range(10):
                            last = fn()
                        end.record()
                        enqueue = time.perf_counter_ns()
                        cpu1 = time.thread_time_ns()
                        end.synchronize()
                        done = time.perf_counter_ns()
                        row = {"block_id": b["block_id"], "pair_id": b["pair_id"],
                            "cluster_id": c["cluster_id"], "triplet_id": c["triplet_id"],
                            "run_id": args.run_id, "clock_scope": clock,
                            "scope": scope, "batch": bs, "policy": c["policy"],
                            "rotation": c["rotation"], "strategy_position": c["strategy_position"],
                            "variant": v, "slot": b["slot"], "pair": b["pair"],
                            "calls_planned": 10, "calls_completed": 10, "status": "measured",
                            "runtime_manifest_sha256": runtime_sha, "cell_sha256": cell_sha,
                            "query_id": q["query_id"] if q else None,
                            "query_begin_ns": q["begin_ns"] if q else None,
                            "query_end_ns": q["end_ns"] if q else None,
                            "previous_done_ns": previous_done, "previous_kind": previous_kind,
                            "ready_ns": ready, "submit_ns": submit, "enqueue_end_ns": enqueue,
                            "done_ns": done, "preparation_ns": ready - previous_done,
                            "ready_to_submit_ns": submit - ready,
                            "sleep_begin_ns": sleep_start, "sleep_end_ns": sleep_end,
                            "sleep_requested_ns": requested_sleep,
                            "gap_match": match_error(submit - previous_done, targets[v], config),
                            "event_ns": begin.elapsed_time(end) * 1e6,
                            "host_enqueue_ns": enqueue - submit, "thread_cpu_ns": cpu1 - cpu0,
                            "wait_ns": done - enqueue, "wall_ns": done - submit,
                            "capture_batch": capture_bs}
                        records[b["block_id"]] = row
                        previous_done = done
                        previous_kind = "previous_measured_block_completion"
                        if scope == "full" and not last[1]:
                            row["status"] = "invalid"
                            raise RuntimeError("identity_error: full path stopped using graph")
                    cluster_end = previous_done
                    cluster_reports.append({"cluster_id": c["cluster_id"], "run_id": args.run_id,
                        "scope": scope, "batch": bs, "policy": c["policy"], "rotation": c["rotation"],
                        "triplet_id": c["triplet_id"], "status": "completed",
                        "planned_blocks": 10, "completed_blocks": 10,
                        "planned_calls": 100, "completed_calls": 100,
                        "begin_ns": cluster_start, "end_ns": cluster_end,
                        "elapsed_ns": cluster_end - cluster_start,
                        "resource_before": resource_before, "host_before": host_before})
                    current_cluster = None
                    emit()  # Cluster-boundary I/O is outside cluster wall; next block gap retains it.
                gate(fb, cell_id, "after")
                if input_digest(fb) != input_sha or graph_identity() != identity:
                    raise RuntimeError("identity_error: input or graph changed")
                print(json.dumps({"run": args.run_id, "cell": cell_id, "clusters_completed": len(subset)}), flush=True)
        if parameters_digest() != parameter_sha:
            raise RuntimeError("identity_error: parameters changed")
        resources()
    except Exception as error:
        failure = {"stage": stage, "type": type(error).__name__, "message": str(error)}
    finally:
        if torch is not None:
            try:
                import torch.distributed as dist
                if dist.is_initialized():
                    dist.destroy_process_group()
            except Exception as cleanup_error:
                failure = failure or {"stage": "cleanup", "type": type(cleanup_error).__name__, "message": str(cleanup_error)}
    if current_cluster is not None:
        n = sum(r.get("calls_completed", 0) for r in records.values()
                if r.get("cluster_id") == current_cluster["cluster_id"] and r["status"] == "measured")
        cluster_reports.append({"cluster_id": current_cluster["cluster_id"], "status": "incomplete",
            "planned_blocks": 10, "planned_calls": 100, "completed_calls": n,
            "begin_ns": cluster_start, "end_ns": time.perf_counter_ns(), "failure": failure})
    for c in clusters:
        for b in c["blocks"]:
            if b["block_id"] not in records:
                records[b["block_id"]] = dict(b, cluster_id=c["cluster_id"], triplet_id=c["triplet_id"],
                    run_id=args.run_id, scope=c["scope"], batch=c["batch"], policy=c["policy"],
                    rotation=c["rotation"], strategy_position=c["strategy_position"],
                    clock_scope=clock, status="missing", calls_completed=0,
                    missing_reason=failure or {"stage": "unknown", "message": "not observed"})
    emit()
    completed = sum(r["status"] == "measured" for r in records.values())
    if failure is None and (completed != len(records) or len(cluster_reports) != 54
                            or len(query_events) != 218 or len(gates) != 13
                            or any(g["status"] != "passed" for g in gates)):
        failure = {"stage": "coverage", "type": "AssertionError", "message": "frozen coverage not met"}
    result = {"schema": "ELIT01-result-v1", "run_id": args.run_id, "clock_scope": clock,
        "plan_sha256": plan_sha, "status": "completed" if failure is None else "failed",
        "collection_complete": failure is None, "stable_gain_claim": False, "failure": failure,
        "planned_blocks": sum(len(c["blocks"]) for c in clusters), "measured_blocks": completed,
        "missing_or_invalid_blocks": len(records) - completed,
        "query_events": len(query_events), "runtime_manifest": "runtime-manifest.json" if runtime else None,
        "peak_torch_bytes": torch.cuda.max_memory_allocated() if torch is not None and torch.cuda.is_initialized() else None,
        "scope_limit": "artificial-weight static calls; composite strategy comparison, no model/serving gain",
        "elapsed_seconds": time.perf_counter() - started}
    write_json(args.output / "run.json", result)
    print(json.dumps({"run_id": args.run_id, "status": result["status"],
                      "measured": completed, "missing_or_invalid": len(records) - completed,
                      "failure": failure}), flush=True)
    if guard is not None:
        guard.close()
    return 0 if failure is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
