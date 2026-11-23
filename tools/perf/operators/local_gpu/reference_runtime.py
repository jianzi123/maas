"""Authorized native SGLang runtime for the reference window; no disk framework edits."""
import os
os.environ.update(HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",
                  HF_DATASETS_OFFLINE="1",TOKENIZERS_PARALLELISM="false")
import hashlib,json
from pathlib import Path
import importlib.metadata as md

class ReferenceRuntime:
    def __init__(self,out):
        import torch,numpy as np
        from native_kv_binding import mature_kv_binding
        from run_decode import verify_sources,telemetry
        from sglang.srt.model_executor.cuda_graph_runner import CudaGraphRunner,set_global_graph_memory_pool
        import sglang.bench_one_batch as bench
        from sglang.srt.server_args import ServerArgs,PortArgs
        from sglang.srt.entrypoints.engine import _set_envs_and_config
        self.torch,self.np,self.bench,self.telemetry=torch,np,bench,telemetry
        self.out=Path(out);(self.out/"snapshots").mkdir()
        torch.set_grad_enabled(False);torch.cuda.set_device(0)
        torch.cuda.set_per_process_memory_fraction(.20)
        initial_resources=self.resources()
        verify_sources(json.loads(Path(__file__).with_name("decode-source-lock.json").read_text()))
        lock=json.loads((Path(__file__).parent/"evidence/framework-v0.18/framework-source-lock.json").read_text())
        package=Path(md.distribution("sglang").locate_file("sglang"))
        for r in lock["files"]:
            if not r["official_match"] or hashlib.sha256((package/r["path"]).read_bytes()).hexdigest()!=r["sha256"]:
                raise RuntimeError("framework_source_mismatch")
        model=Path.home()/".cache/huggingface/hub/models--HuggingFaceTB--SmolLM-135M-Instruct/snapshots/fcc320f490e08fdb4b99d935b2c58d40bf35b0d0"
        sa=ServerArgs(model_path=str(model),tokenizer_path=str(model),load_format="dummy",
            dtype="float16",device="cuda",tp_size=1,mem_fraction_static=.20,
            max_total_tokens=512,context_length=128,max_running_requests=8,
            attention_backend="triton",sampling_backend="pytorch",cuda_graph_bs=[1,2,4,8],
            cuda_graph_max_bs=8,disable_overlap_schedule=True,disable_custom_all_reduce=True,
            random_seed=20261114,trust_remote_code=False,log_level="warning")
        _set_envs_and_config(sa);torch.cuda.set_per_process_memory_fraction(.20);torch.manual_seed(20261114)
        self.runner,_=bench.load_model(sa,PortArgs.init_new(sa),0)
        r=self.runner;self.contexts={"native":(r.attn_backend,r.graph_runner)}
        backend=type(r.attn_backend)(r);r.attn_backend=backend
        set_global_graph_memory_pool(torch.cuda.graph_pool_handle())
        with mature_kv_binding():graph=CudaGraphRunner(r)
        self.contexts["mature"]=(backend,graph)
        if r.server_args.triton_attention_num_kv_splits!=8 or any(len(m._forward_hooks) for m in r.model.modules()):
            raise RuntimeError("unexpected_model_instrumentation_or_cap")
        self.identity=self.graph_identity()
        for f in ("indices","scratch"):
            if self.identity["native"][f]==self.identity["mature"][f]:raise RuntimeError("shared_graph_state")
        self.parameter_sha=self.parameter_hash()
        self.metadata={"sglang_commit":lock["commit"],"versions":{n:md.version(n) for n in ("torch","triton","sglang","sgl-kernel")},
            "torch":torch.__version__,"cuda":torch.version.cuda,"GPU":torch.cuda.get_device_name(0),
            "SMs":torch.cuda.get_device_properties(0).multi_processor_count,"initial_resources":initial_resources,
            "CC":list(torch.cuda.get_device_capability()),"model_config_sha256":hashlib.sha256((model/"config.json").read_bytes()).hexdigest(),
            "weights":"native DummyModelLoader random parameters","parameter_full_sha256":self.parameter_sha,
            "graph_identity":self.identity,"Engine":False,"serving":False}
        self.begin,self.end=torch.cuda.Event(enable_timing=True),torch.cuda.Event(enable_timing=True)
        self.begin.record();self.end.record();self.end.synchronize()
    def resources(self):
        t=self.torch;free,total=t.cuda.mem_get_info()
        if free<1073741824 or t.cuda.memory_reserved()>total*.20:raise RuntimeError("resource_limit")
        return {"free":free,"total":total,"allocated":t.cuda.memory_allocated(),"reserved":t.cuda.memory_reserved()}
    def graph_identity(self):
        return {v:{"graphs":{str(b):id(g) for b,g in cg.graphs.items()},
            "inputs":{n:getattr(cg,n).data_ptr() for n in ("input_ids","positions","seq_lens","out_cache_loc","req_pool_indices")},
            "indices":be.cuda_graph_kv_indices.data_ptr(),"scratch":be.cuda_graph_attn_logits.data_ptr()}
            for v,(be,cg) in self.contexts.items()}
    def parameter_hash(self):
        h=hashlib.sha256()
        for name,value in self.runner.model.named_parameters():
            h.update(name.encode());h.update(str((tuple(value.shape),str(value.dtype))).encode())
            h.update(value.detach().cpu().contiguous().view(self.torch.uint8).numpy().tobytes())
        return h.hexdigest()
    def activate(self,v,fb):
        self.runner.attn_backend,self.runner.graph_runner=self.contexts[v]
        fb.attn_backend=self.runner.attn_backend
    def cell(self,bs):
        r=self.runner;t=self.torch;b=self.bench
        r.attn_backend,r.graph_runner=self.contexts["native"]
        t.cuda.synchronize();r.req_to_token_pool.clear();r.token_to_kv_pool_allocator.clear()
        self.np.random.seed(20261114+bs)
        reqs=b.prepare_synthetic_inputs_for_latency_test(bs,12)
        _,_,batch=b.extend(reqs,r)
        batch.output_ids=t.arange(bs,device="cuda",dtype=t.int64)+321
        batch.prepare_for_decode();b._maybe_prepare_mlp_sync_batch(batch,r)
        return b.ForwardBatch.init_new(batch.get_model_worker_batch(),r)
    def input_hash(self,fb):
        h=hashlib.sha256()
        for n in ("input_ids","positions","seq_lens","out_cache_loc","req_pool_indices"):
            h.update(n.encode());h.update(getattr(fb,n).detach().cpu().contiguous().view(self.torch.uint8).numpy().tobytes())
        return h.hexdigest()
    def prepare(self,v,fb):
        self.activate(v,fb);g=self.runner.graph_runner
        g.replay_prepare(fb);self.torch.cuda.synchronize()
        if g.bs!=next(b for b in (1,2,4,8) if b>=fb.batch_size) or self.graph_identity()!=self.identity:
            raise RuntimeError("graph_identity")
        return g
    def warm(self,fb):
        for v in ("native","mature"):
            self.activate(v,fb)
            for _ in range(12):self.runner.forward(fb)
        self.torch.cuda.synchronize()
    def gate(self,fb,phase):
        from cadence_protocol import digest
        from analyze_kv_cadence import validate_gate
        arrays={};refs={}
        for v in ("native","mature"):
            self.activate(v,fb);output,used=self.runner.forward(fb)
            if not used:raise RuntimeError("not_graph")
            loc=fb.out_cache_loc[:fb.batch_size]
            if not ((loc>0)&(loc<=512)).all():raise RuntimeError("real_loc_bound")
            kv=self.torch.stack([self.torch.stack((
                self.runner.token_to_kv_pool.get_key_buffer(i).index_select(0,loc),
                self.runner.token_to_kv_pool.get_value_buffer(i).index_select(0,loc)))
                for i in range(self.runner.start_layer,self.runner.end_layer)])
            arrays[v]=(output.next_token_logits.detach().clone().cpu().numpy(),kv.cpu().numpy());refs[v]=[]
            for value in arrays[v]:
                sha=hashlib.sha256(value.tobytes()).hexdigest()
                key=digest({"sha":sha,"shape":list(value.shape),"dtype":str(value.dtype)})
                path=self.out/"snapshots"/(key+".npz")
                if not path.exists():self.np.savez_compressed(path,value=value)
                refs[v].append({"path":path.relative_to(self.out).as_posix(),"raw_sha256":sha,
                                "shape":list(value.shape),"dtype":str(value.dtype)})
        gate={"cell_id":f"R01/{self.scope}/B{fb.batch_size}","phase":phase,"all30_layers":True,"status":"passed","snapshots":refs}
        validate_gate(gate,self.out)
        return gate
    def close(self):
        import torch.distributed as dist
        if dist.is_initialized():dist.destroy_process_group()
