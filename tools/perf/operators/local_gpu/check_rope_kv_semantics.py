"""Fixed-wheel RoPE+KV semantics on artificial QKV views, NOT a model caller or benchmark."""
import os
os.environ.update(HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1")
import argparse
import fcntl
import hashlib
import importlib.metadata as md
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    guard=Path("/var/tmp/maas-10-gpu-01a1a5ba/gpu0-research.lock").open("a")
    fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
    import torch
    from sgl_kernel.elementwise import apply_rope_with_cos_sin_cache_inplace, FusedSetKVBufferArg
    from torch.profiler import profile,ProfilerActivity,record_function
    torch.set_grad_enabled(False);torch.cuda.set_device(0)
    if torch.cuda.mem_get_info()[0]<1024**3:raise RuntimeError("less than1GiB free")
    torch.cuda.set_per_process_memory_fraction(.20)
    torch.manual_seed(20261115)
    report={"scope":"direct mature library semantics; synthetic noncontiguous views, not native Llama caller",
        "semantic_quality_or_performance_claim":False,"cases":[],
        "torch":torch.__version__,"sgl_kernel":md.version("sgl-kernel"),
        "code_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    pos_cpu=torch.arange(128,dtype=torch.float64)
    freq=10000.0**(-torch.arange(0,64,2,dtype=torch.float64)/64)
    angle=pos_cpu[:,None]*freq[None,:]
    cache=torch.cat((angle.cos(),angle.sin()),dim=-1).float().cuda()
    stream=torch.cuda.Stream()
    with profile(activities=[ProfilerActivity.CPU,ProfilerActivity.CUDA]) as prof:
        for bs in (3,5,8):
            for nondefault in (False,True):
                stream_context=torch.cuda.stream(stream) if nondefault else torch.cuda.stream(torch.cuda.default_stream())
                with stream_context:
                    raw=torch.randn(bs,960,device="cuda",dtype=torch.float16)
                    reference=raw.clone();candidate=raw.clone()
                    qr,kr,vr=reference.split((576,192,192),dim=-1)
                    qc,kc,vc=candidate.split((576,192,192),dim=-1)
                    positions=torch.tensor(([0,127,5,63,1,126,64,2])[:bs],device="cuda",dtype=torch.int64)
                    loc=torch.arange(bs,device="cuda",dtype=torch.int64)*3+11+(64 if nondefault else 0)
                    rkey=torch.full((512,3,64),17.,device="cuda",dtype=torch.float16)
                    rval=rkey.clone();ckey=rkey.clone();cval=rkey.clone()
                    before_k=kc.clone();before_v=vc.clone()
                    # Finish data setup before the named operator scopes.
                    torch.cuda.synchronize()
                    with record_function(f"ropeKV/{bs}/{int(nondefault)}/reference"):
                        apply_rope_with_cos_sin_cache_inplace(positions,qr,kr,64,cache,True)
                        torch.ops.sgl_kernel.store_kv_cache(rkey,rval,loc,kr.view(bs,3,64),vr.view(bs,3,64))
                        torch.cuda.synchronize()
                    with record_function(f"ropeKV/{bs}/{int(nondefault)}/fused"):
                        apply_rope_with_cos_sin_cache_inplace(positions,qc,kc,64,cache,True,
                            FusedSetKVBufferArg(vc,ckey,cval,None,None,loc))
                        torch.cuda.synchronize()
                    for value in (qr,kr,qc,kc,rkey,rval,ckey,cval):
                        if not torch.isfinite(value).all():raise AssertionError("nonfinite")
                    # FP64 reference uses the actual FP32 cache provided to the library.
                    cos,sin=cache[positions].double().chunk(2,dim=-1)
                    def ref(x,heads):
                        x=x.double().view(bs,heads,64);a,b=x.chunk(2,dim=-1)
                        return torch.cat((a*cos[:,None]-b*sin[:,None],
                                          b*cos[:,None]+a*sin[:,None]),dim=-1)
                    expected_q=ref(raw[:,:576],9)
                    expected_k=ref(raw[:,576:768],3)
                    for got,expected in ((qc.view(bs,9,64),expected_q),(ckey[loc],expected_k)):
                        torch.testing.assert_close(got.double(),expected,rtol=.001,atol=.002)
                    torch.testing.assert_close(qc,qr,rtol=.001,atol=.002)
                    torch.testing.assert_close(ckey,rkey,rtol=.001,atol=.002)
                    if not torch.equal(cval,rval) or not torch.equal(vc,before_v):
                        raise AssertionError("V view/cache changed")
                    untouched=torch.ones(512,device="cuda",dtype=torch.bool);untouched[loc]=False
                    if not (ckey[untouched]==17).all() or not (cval[untouched]==17).all():
                        raise AssertionError("non-target slot changed")
                    report["cases"].append({"batch":bs,"nondefault_stream":nondefault,
                        "qkv_stride":list(raw.stride()),"q_stride":list(qc.stride()),"k_stride":list(kc.stride()),
                        "q_alias":qc.data_ptr()==candidate.data_ptr(),"k_alias":kc.data_ptr()==candidate.data_ptr()+576*2,
                        "key_input_unchanged":torch.equal(kc,before_k),
                        "key_input_matches_reference":torch.allclose(kc,kr,rtol=.001,atol=.002),
                        "q_max_abs_reference":(qc-qr).abs().max().item(),
                        "kcache_max_abs_reference":(ckey-rkey).abs().max().item(),
                        "v_bitwise_equal":True,"non_target_slots_unchanged":True,
                        "FP64_reference_rtol":.001,"FP64_reference_atol":.002})
    prof.export_chrome_trace(str(args.output/"timeline.json"))
    report["peak_torch_bytes"]=torch.cuda.max_memory_allocated()
    report["status"]="passed"
    (args.output/"rope-kv.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"cases":len(report["cases"]),"status":"passed",
        "key_input_unchanged":all(r["key_input_unchanged"] for r in report["cases"]),
        "key_matches_reference":all(r["key_input_matches_reference"] for r in report["cases"])}))
    return 0


if __name__=="__main__":raise SystemExit(main())
