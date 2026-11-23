"""Actual SGLang A/A dispatch. Observers exist only during graph capture."""
import hashlib,inspect,json,os
from contextlib import contextmanager
from pathlib import Path
import importlib.metadata as md
os.environ.update(HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",HF_DATASETS_OFFLINE="1",TOKENIZERS_PARALLELISM="false")
from reference_runtime import ReferenceRuntime
@contextmanager
def capture_caller_probe(torch,facts,implementation):
 from sglang.srt.mem_cache.memory_pool import MHATokenToKVPool
 original=MHATokenToKVPool.set_kv_buffer
 fact={"capturing_calls":0,"layers":set(),"capture_sizes":set(),"method":original.__qualname__,
       "source_sha256":hashlib.sha256(inspect.getsource(original).encode()).hexdigest()}
 def observe(pool,layer,loc,k,v,*rest,**kwargs):
  if torch.cuda.is_current_stream_capturing():
   fact["capturing_calls"]+=1;fact["layers"].add(int(layer.layer_id));fact["capture_sizes"].add(int(loc.numel()))
  return original(pool,layer,loc,k,v,*rest,**kwargs)
 MHATokenToKVPool.set_kv_buffer=observe
 try:yield
 finally:
  MHATokenToKVPool.set_kv_buffer=original
  fact["layers"]=sorted(fact["layers"]);fact["capture_sizes"]=sorted(fact["capture_sizes"])
  fact["observer_removed"]=MHATokenToKVPool.set_kv_buffer is original
  facts[implementation]=fact
 if fact["layers"]!=list(range(30)) or fact["capture_sizes"]!=[1,2,4,8] or not fact["capturing_calls"]:
  raise RuntimeError("capture_caller_not_proven")
class AARuntime(ReferenceRuntime):
    def __init__(self,out):
        import torch,numpy as np
        from aa_protocol import CONFIG
        env=CONFIG["environment"]
        if any(md.version(n)!=env[n] for n in ("torch","triton","sglang","sgl-kernel")):raise RuntimeError("pinned_package_version")
        if torch.__version__!=env["torch_build"] or torch.version.cuda!=env["CUDA"]:raise RuntimeError("pinned_CUDA_build")
        if os.environ.get("CUDA_VISIBLE_DEVICES") not in (None,"","0"):raise RuntimeError("physical_GPU0_mapping")
        torch_source=Path(md.distribution("torch").locate_file("torch/cuda/graphs.py"))
        if hashlib.sha256(torch_source.read_bytes()).hexdigest()!=env["torch_graphs_sha256"]:raise RuntimeError("pinned_torch_graphs_source")
        from native_kv_binding import mature_kv_binding
        from run_decode import verify_sources,telemetry
        from sglang.srt.model_executor.cuda_graph_runner import CudaGraphRunner,set_global_graph_memory_pool
        import sglang.bench_one_batch as bench
        from sglang.srt.server_args import ServerArgs,PortArgs
        from sglang.srt.entrypoints.engine import _set_envs_and_config
        self.torch,self.np,self.bench,self.telemetry=torch,np,bench,telemetry
        self.capture_facts={};self.extra={"warmup_returned":0,"warmup_cells_synchronized":0,"gate_forward_returned":0,"input_snapshots":0};self.out=Path(out);(self.out/"snapshots").mkdir()
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
        with capture_caller_probe(torch,self.capture_facts,'native'):
            self.runner,_=bench.load_model(sa,PortArgs.init_new(sa),0)
        r=self.runner;self.contexts={"native":(r.attn_backend,r.graph_runner)}
        backend=type(r.attn_backend)(r);r.attn_backend=backend
        set_global_graph_memory_pool(torch.cuda.graph_pool_handle())
        with mature_kv_binding():
            with capture_caller_probe(torch,self.capture_facts,'mature'):graph=CudaGraphRunner(r)
        self.contexts["mature"]=(backend,graph)
        if r.server_args.triton_attention_num_kv_splits!=8 or any(len(m._forward_hooks) for m in r.model.modules()):
            raise RuntimeError("unexpected_model_instrumentation_or_cap")
        self.identity=self.graph_identity()
        for f in ("indices","scratch"):
            if self.identity["native"][f]==self.identity["mature"][f]:raise RuntimeError("shared_graph_state")
        self.parameter_sha=self.parameter_hash()
        self.metadata={"capture_facts":self.capture_facts,"sglang_commit":lock["commit"],"versions":{n:md.version(n) for n in ("torch","triton","sglang","sgl-kernel")},
            "torch":torch.__version__,"cuda":torch.version.cuda,"GPU":torch.cuda.get_device_name(0),
            "SMs":torch.cuda.get_device_properties(0).multi_processor_count,"initial_resources":initial_resources,
            "CC":list(torch.cuda.get_device_capability()),"model_config_sha256":hashlib.sha256((model/"config.json").read_bytes()).hexdigest(),
            "weights":"native DummyModelLoader random parameters","parameter_full_sha256":self.parameter_sha,
            "graph_identity":self.identity,"Engine":False,"serving":False}
        self.begin,self.end=torch.cuda.Event(enable_timing=True),torch.cuda.Event(enable_timing=True)
        self.begin.record();self.end.record();self.end.synchronize()

    def graph_identity(self):
        result=super().graph_identity()
        for v,(_,g) in self.contexts.items():
            result[v]["pools"]={str(b):list(x.pool()) for b,x in g.graphs.items()}
        return result
    def binding(self,scope,variant,fb,fn):
        backend,g=self.contexts[variant];cap=next(b for b in (1,2,4,8) if b>=fb.batch_size)
        graph=g.graphs[cap];identity=self.graph_identity()[variant]
        shared={"callable_object":id(fn),"callable_self":id(fn.__self__),"callable_function":id(fn.__func__),
            "method":fn.__func__.__qualname__,"graph_object":id(graph),"stream":self.torch.cuda.current_stream(0).cuda_stream,
            "inputs":identity["inputs"],"scratch":identity["scratch"],"indices":identity["indices"],"pool":list(graph.pool())}
        expected=self.runner.forward if scope=="full" else graph.replay
        if fn.__self__ is not expected.__self__ or fn.__func__ is not expected.__func__:raise RuntimeError("alias_wrapper")
        return {"batch":fb.batch_size,"padded_batch":cap,"implementation":variant,"scope":scope,
          "aliases":{"A":shared.copy(),"Aprime":shared.copy()},"callable_object":id(fn),"graph_object":id(graph),
          "custom_wrapper":False,"eager":False,"capture_caller_verified":self.capture_facts[variant]["observer_removed"]}

    def input_state(self,fb):
        from cadence_protocol import digest
        self.extra["input_snapshots"]+=1
        t=self.torch;r=self.runner
        if fb.seq_lens.detach().cpu().tolist()!=[13]*fb.batch_size:raise RuntimeError("KV_context")
        loc=r.req_to_token_pool.req_to_token.index_select(0,fb.req_pool_indices.to(t.int64))[:,:13].reshape(-1).to(t.int64)
        if fb.batch_size==3:loc=t.cat((t.zeros(1,device="cuda",dtype=t.int64),loc))
        loc=t.unique(loc,sorted=True)
        if not ((loc>=0)&(loc<=512)).all():raise RuntimeError("readable_KV_slots")
        slots=loc.detach().cpu().tolist()
        kv=t.stack([t.stack((r.token_to_kv_pool.get_key_buffer(i).index_select(0,loc),
                            r.token_to_kv_pool.get_value_buffer(i).index_select(0,loc))) for i in range(30)]).cpu().numpy()
        if not self.np.isfinite(kv).all():raise RuntimeError("input_KV_nonfinite")
        sha=hashlib.sha256(kv.tobytes()).hexdigest()
        key=digest({"raw":sha,"slots":slots,"shape":list(kv.shape),"dtype":str(kv.dtype)})
        folder=self.out/"inputs";folder.mkdir(exist_ok=True);path=folder/(key+".npz")
        if not path.exists():self.np.savez_compressed(path,value=kv)
        return {"token_metadata_sha256":self.input_hash(fb),"KV_sha256":sha,"read_slots":slots,
          "KV_shape":list(kv.shape),"KV_dtype":str(kv.dtype),"path":path.relative_to(self.out).as_posix()}

    def warm(self,fb):
        for v in ("native","mature"):
            self.activate(v,fb)
            for _ in range(12):
                self.runner.forward(fb);self.extra["warmup_returned"]+=1
        self.torch.cuda.synchronize();self.extra["warmup_cells_synchronized"]+=1

    def gate(self,fb,phase):
        from cadence_protocol import digest
        from analyze_kv_cadence import validate_gate
        arrays={};refs={}
        for v in ("native","mature"):
            self.activate(v,fb);output,used=self.runner.forward(fb);self.extra["gate_forward_returned"]+=1
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

    def cell(self,bs):
        fb=super().cell(bs)
        # Slot0 is reserved padding; initialize outside gates/hot blocks in BOTH processes.
        for i in range(30):
            self.runner.token_to_kv_pool.get_key_buffer(i)[0].zero_()
            self.runner.token_to_kv_pool.get_value_buffer(i)[0].zero_()
        self.torch.cuda.synchronize()
        self.extra["padding_slot_initializations"]=self.extra.get("padding_slot_initializations",0)+1
        return fb
