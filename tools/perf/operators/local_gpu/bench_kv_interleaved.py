"""Window B: interleaved native CUDA graphs, shared weights, isolated graph state.

Artificial weights/static ForwardBatch call cost only. No Engine/serving claim.
Original v0.19 cost files and runner are never rewritten.
"""
import os
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_DATASETS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import argparse
import contextlib
import fcntl
import hashlib
import importlib.metadata as md
import json
from pathlib import Path
import resource
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def host_state(torch):
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {"monotonic_ns": time.perf_counter_ns(), "loadavg": os.getloadavg(),
            "cpu_user_s": usage.ru_utime, "cpu_sys_s": usage.ru_stime,
            "voluntary_switches": usage.ru_nvcsw, "involuntary_switches": usage.ru_nivcsw,
            "allocated_bytes": torch.cuda.memory_allocated(),
            "reserved_bytes": torch.cuda.memory_reserved()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-first", choices=("native", "mature"), required=True)
    parser.add_argument("--profile-only", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    guard = Path("/var/tmp/maas-10-gpu-01a1a5ba/gpu0-research.lock").open("a")
    fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
    import torch
    import numpy as np
    from native_kv_binding import mature_kv_binding
    from run_decode import telemetry, verify_sources
    from sglang.srt.model_executor.cuda_graph_runner import (
        CudaGraphRunner, set_global_graph_memory_pool)
    import sglang.bench_one_batch as bench
    from sglang.srt.server_args import ServerArgs, PortArgs
    from sglang.srt.entrypoints.engine import _set_envs_and_config

    torch.set_grad_enabled(False)
    torch.cuda.set_device(0)
    if torch.cuda.mem_get_info()[0] < 1024**3:
        raise RuntimeError("less than1GiB free")
    torch.cuda.set_per_process_memory_fraction(0.20)
    verify_sources(json.loads(Path(__file__).with_name("decode-source-lock.json").read_text()))
    pkg = Path(md.distribution("sglang").locate_file("sglang"))
    lock = json.loads((Path(__file__).parent / "evidence/framework-v0.18/framework-source-lock.json").read_text())
    for row in lock["files"]:
        if not row["official_match"] or sha(pkg / row["path"]) != row["sha256"]:
            raise ValueError("framework source mismatch")
    model = Path.home() / ".cache/huggingface/hub/models--HuggingFaceTB--SmolLM-135M-Instruct/snapshots/fcc320f490e08fdb4b99d935b2c58d40bf35b0d0"
    sa = ServerArgs(model_path=str(model), tokenizer_path=str(model), load_format="dummy",
        dtype="float16", device="cuda", tp_size=1, mem_fraction_static=0.20,
        max_total_tokens=512, context_length=128, max_running_requests=8,
        attention_backend="triton", sampling_backend="pytorch", cuda_graph_bs=[1,2,4,8],
        cuda_graph_max_bs=8, disable_overlap_schedule=True, disable_custom_all_reduce=True,
        random_seed=20261114, trust_remote_code=False, log_level="warning")
    _set_envs_and_config(sa)
    torch.cuda.set_per_process_memory_fraction(0.20)
    torch.manual_seed(20261114)
    report = {"scope": "artificial-weight static native-forward / bare graph diagnostic",
        "Engine": False, "pretrained_or_serving_claim": False,
        "pid": os.getpid(), "capture_first": args.capture_first,
        "profile_only": args.profile_only,
        "source_commit": lock["commit"],
        "code_sha256": {n: sha(Path(__file__).with_name(n)) for n in
            ("bench_kv_interleaved.py", "native_kv_binding.py")},
        "environment": {k: os.environ.get(k) for k in
            ("CUDA_LAUNCH_BLOCKING","CUDA_MODULE_LOADING","CUDA_DEVICE_MAX_CONNECTIONS",
             "OMP_NUM_THREADS","MKL_NUM_THREADS","LD_PRELOAD","PYTORCH_CUDA_ALLOC_CONF")},
        "versions": {n: md.version(n) for n in ("torch","triton","sglang","sgl-kernel")},
        "telemetry_initial": telemetry(), "host_initial": host_state(torch),
        "torch_threads": torch.get_num_threads(), "affinity": sorted(os.sched_getaffinity(0)),
        "initialization": [], "gates": [], "cold_calls": [], "blocks": []}
    runner = None
    contexts = {}
    try:
        t = time.perf_counter()
        ctx = mature_kv_binding() if args.capture_first == "mature" else contextlib.nullcontext()
        with ctx:
            runner, _ = bench.load_model(sa, PortArgs.init_new(sa), 0)
        contexts[args.capture_first] = (runner.attn_backend, runner.graph_runner)
        report["initialization"].append({"variant":args.capture_first,
            "seconds":time.perf_counter()-t,"scope":"model load + native graph capture"})
        other = "mature" if args.capture_first == "native" else "native"
        t = time.perf_counter()
        # Keep both native graph states alive: a fresh backend has separate metadata
        # and scratch. A separate CUDA graph pool avoids private graph allocations aliasing.
        backend = type(runner.attn_backend)(runner)
        runner.attn_backend = backend
        set_global_graph_memory_pool(torch.cuda.graph_pool_handle())
        ctx = mature_kv_binding() if other == "mature" else contextlib.nullcontext()
        with ctx:
            graph = CudaGraphRunner(runner)
        contexts[other] = (backend, graph)
        report["initialization"].append({"variant":other,
            "seconds":time.perf_counter()-t,"scope":"new backend + separate native graph capture; same model/KV"})
        if any(len(m._forward_hooks) for m in runner.model.modules()):
            raise AssertionError("unexpected model forward hooks")
        if runner.server_args.triton_attention_num_kv_splits != 8:
            raise AssertionError("cap8 changed")
        report["parameter_sample_sha256"] = hashlib.sha256(
            next(runner.model.parameters()).flatten()[:1024].detach().cpu().numpy().tobytes()).hexdigest()
        report["graph_state"] = {}
        for name,(be,g) in contexts.items():
            report["graph_state"][name] = {"sizes": sorted(g.graphs),
                "input_ptr":g.input_ids.data_ptr(), "kv_indices_ptr":be.cuda_graph_kv_indices.data_ptr(),
                "scratch_ptr":be.cuda_graph_attn_logits.data_ptr()}
        for field in ("input_ptr","kv_indices_ptr","scratch_ptr"):
            if report["graph_state"]["native"][field] == report["graph_state"]["mature"][field]:
                raise AssertionError("graph states must be isolated")

        def activate(name, fb=None):
            runner.attn_backend, runner.graph_runner = contexts[name]
            if fb is not None:
                fb.attn_backend = runner.attn_backend

        def snapshot(name, fb):
            activate(name,fb)
            output, used = runner.forward(fb)
            if not used:
                raise AssertionError("native graph not used")
            loc=fb.out_cache_loc[:fb.batch_size]
            if not (loc>0).all():
                raise AssertionError("state gate excludes padding slot")
            kv = torch.stack([torch.stack((
                runner.token_to_kv_pool.get_key_buffer(i).index_select(0,loc),
                runner.token_to_kv_pool.get_value_buffer(i).index_select(0,loc)))
                for i in range(runner.start_layer,runner.end_layer)])
            logits=output.next_token_logits.detach().clone().cpu().numpy()
            kv=kv.cpu().numpy()
            if not np.isfinite(logits).all() or not np.isfinite(kv).all():
                raise AssertionError("nonfinite state")
            return logits,kv

        def gate(fb,phase):
            a=snapshot("native",fb);b=snapshot("mature",fb)
            for x,y in zip(a,b):
                if x.dtype!=y.dtype or x.shape!=y.shape or x.tobytes()!=y.tobytes():
                    raise AssertionError("interleaved state mismatch")
            report["gates"].append({"phase":phase,"batch":fb.batch_size,
                "logits_sha256":hashlib.sha256(a[0].tobytes()).hexdigest(),
                "KV_sha256":hashlib.sha256(a[1].tobytes()).hexdigest(),
                "all30_layers":True,"finite_bitwise_equal":True})

        for bs in ((3,) if args.profile_only else (3,5,8)):
            activate("native")
            torch.cuda.synchronize()
            runner.req_to_token_pool.clear()
            runner.token_to_kv_pool_allocator.clear()
            np.random.seed(20261114+bs)
            reqs=bench.prepare_synthetic_inputs_for_latency_test(bs,12)
            _,_,batch=bench.extend(reqs,runner)
            batch.output_ids=torch.arange(bs,device="cuda",dtype=torch.int64)+321
            batch.prepare_for_decode()
            bench._maybe_prepare_mlp_sync_batch(batch,runner)
            fb=bench.ForwardBatch.init_new(batch.get_model_worker_batch(),runner)
            gate(fb,"before_cost")
            # Record every first-call wall sample in alternating order; outside steady rounds.
            for cold in range(12):
                order=("native","mature") if cold%2==0 else ("mature","native")
                for name in order:
                    activate(name,fb);torch.cuda.synchronize()
                    t=time.perf_counter_ns();runner.forward(fb);torch.cuda.synchronize()
                    report["cold_calls"].append({"batch":bs,"cycle":cold,"variant":name,
                        "wall_us":(time.perf_counter_ns()-t)/1000})
            if args.profile_only:
                from torch.profiler import profile, ProfilerActivity, record_function
                with profile(activities=[ProfilerActivity.CPU,ProfilerActivity.CUDA]) as prof:
                    for name in ("native","mature"):
                        activate(name,fb)
                        with record_function("windowB/full/"+name):
                            runner.forward(fb)
                        torch.cuda.synchronize()
                        runner.graph_runner.replay_prepare(fb)
                        torch.cuda.synchronize()
                        with record_function("windowB/bare/"+name):
                            runner.graph_runner.graphs[runner.graph_runner.bs].replay()
                        torch.cuda.synchronize()
                prof.export_chrome_trace(str(args.output/"timeline.json"))
                gate(fb,"after_profile")
                break
            begin,end=torch.cuda.Event(enable_timing=True),torch.cuda.Event(enable_timing=True)
            begin.record();end.record();end.synchronize()
            for scope in ("full","bare_graph"):
                for cycle in range(10):
                    order=("native","mature") if cycle%2==0 else ("mature","native")
                    for name in order:
                        activate(name,fb)
                        runner.graph_runner.replay_prepare(fb)
                        torch.cuda.synchronize()
                        cap=runner.graph_runner.bs
                        # Switching, telemetry, reference/host snapshots are outside this block.
                        gpu_before=telemetry();cpu_before=host_state(torch)
                        fn=(lambda: runner.forward(fb)) if scope=="full" else contexts[name][1].graphs[cap].replay
                        t=time.perf_counter_ns();ct=time.thread_time_ns()
                        begin.record()
                        for _ in range(10):fn()
                        end.record()
                        enqueue=time.perf_counter_ns();cpu_end=time.thread_time_ns()
                        end.synchronize();stop=time.perf_counter_ns()
                        row={"batch":bs,"capture_batch":cap,"scope":scope,"cycle":cycle,
                            "position":order.index(name),"variant":name,"iterations":10,
                            "event_with_host_gaps_us":begin.elapsed_time(end)*100,
                            "host_enqueue_us":(enqueue-t)/10000,
                            "host_thread_cpu_us":(cpu_end-ct)/10000,
                            "wait_us":(stop-enqueue)/10000,"wall_with_sync_us":(stop-t)/10000,
                            "gpu_before":gpu_before,"host_before":cpu_before,
                            "host_after":host_state(torch)}
                        report["blocks"].append(row)
                gate(fb,"after_"+scope)
            print(json.dumps({"batch":bs,"paired_blocks_completed":True}),flush=True)
        report["telemetry_final"]=telemetry()
        report["host_final"]=host_state(torch)
        report["peak_torch_bytes"]=torch.cuda.max_memory_allocated()
        report["status"]="passed"
        report["limitations"]=["same native ModelRunner/model/req+KV pool; separate native graphs/backends/pools",
            "static inputs; repeated forwards do not advance scheduler/token sequence",
            "CUDA events include host gaps; bare graph bypasses replay preparation, not a serving optimization",
            "all correctness and profiler work excluded from clean blocks",
            "CPU affinity/frequency/power are observations, not locked experimental controls"]
        (args.output/"window-b.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
        return 0
    finally:
        import torch.distributed as dist
        if dist.is_initialized():dist.destroy_process_group()


if __name__=="__main__":
    raise SystemExit(main())
