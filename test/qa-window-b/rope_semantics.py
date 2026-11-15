"""Short independent six-cell RoPE+KV library semantics, no caller or timing."""
import argparse,fcntl,json,os,hashlib,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);a=p.parse_args();a.output.mkdir(exist_ok=False)
guard=open("/var/tmp/maas-10-gpu-01a1a5ba/gpu0-research.lock","a");fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
import torch,numpy as np,importlib.metadata as md
from sgl_kernel.elementwise import apply_rope_with_cos_sin_cache_inplace as rope,FusedSetKVBufferArg
from torch.profiler import profile,ProfilerActivity,record_function
torch.set_grad_enabled(False);torch.set_num_threads(2);torch.cuda.set_device(0)
assert torch.cuda.mem_get_info()[0]>=1024**3;torch.cuda.set_per_process_memory_fraction(.20)
torch.manual_seed(20261117)
pos=torch.arange(128,dtype=torch.float64);freq=10000.**(-torch.arange(0,64,2,dtype=torch.float64)/64)
angle=pos[:,None]*freq;cache_cpu=torch.cat((angle.cos(),angle.sin()),-1).float()
cache=cache_cpu.cuda();ready=torch.cuda.Event();ready.record()
rows=[];snapshots={};stream=torch.cuda.Stream();start=time.time()
with profile(activities=[ProfilerActivity.CPU,ProfilerActivity.CUDA]) as prof:
 for bs in (3,5,8):
  for nd in (False,True):
   s=stream if nd else torch.cuda.default_stream()
   with torch.cuda.stream(s):
    s.wait_event(ready)
    raw=torch.randn(bs,960,device="cuda",dtype=torch.float16)
    reference=raw.clone();candidate=raw.clone()
    qr,kr,vr=reference.split((576,192,192),-1);qc,kc,vc=candidate.split((576,192,192),-1)
    before_k=kc.clone();before_v=vc.clone()
    positions=torch.tensor([0,127,5,63,1,126,64,2][:bs],dtype=torch.int64,device="cuda")
    loc=torch.arange(bs,device="cuda",dtype=torch.int64)*3+11+(64 if nd else 0)
    rk=torch.full((512,3,64),17.,device="cuda",dtype=torch.float16);rv=rk.clone();ck=rk.clone();cv=rk.clone()
    setup=torch.cuda.Event();setup.record()
   setup.synchronize()
   with torch.cuda.stream(s):
    with record_function("QA_RoPE/%s/%s/separate"%(bs,int(nd))):
     rope(positions,qr,kr,64,cache,True)
     torch.ops.sgl_kernel.store_kv_cache(rk,rv,loc,kr.view(bs,3,64),vr.view(bs,3,64))
     done=torch.cuda.Event();done.record();done.synchronize()
    with record_function("QA_RoPE/%s/%s/fused"%(bs,int(nd))):
     rope(positions,qc,kc,64,cache,True,FusedSetKVBufferArg(vc,ck,cv,None,None,loc))
     done=torch.cuda.Event();done.record();done.synchronize()
   arr=raw.cpu().numpy().astype(np.float64);c=cache_cpu.numpy().astype(np.float64)[positions.cpu().numpy()];cos,sin=np.split(c,2,-1)
   def oracle(x,heads):
    x=x.reshape(bs,heads,64);lo,hi=np.split(x,2,-1)
    return np.concatenate((lo*cos[:,None]-hi*sin[:,None],hi*cos[:,None]+lo*sin[:,None]),-1)
   expected_q=oracle(arr[:,:576],9);expected_k=oracle(arr[:,576:768],3)
   np.testing.assert_allclose(qc.cpu().numpy().reshape(bs,9,64),expected_q,rtol=.001,atol=.002)
   np.testing.assert_allclose(ck[loc].cpu().numpy(),expected_k,rtol=.001,atol=.002)
   assert torch.equal(qc.contiguous().view(torch.uint8),qr.contiguous().view(torch.uint8))
   assert torch.equal(ck.view(torch.uint8),rk.view(torch.uint8))
   assert torch.equal(cv.view(torch.uint8),rv.view(torch.uint8)) and torch.equal(vc.contiguous().view(torch.uint8),before_v.contiguous().view(torch.uint8))
   mask=torch.ones(512,device="cuda",dtype=torch.bool);mask[loc]=False
   assert (ck[mask]==17).all() and (cv[mask]==17).all()
   name="b%s_s%s"%(bs,int(nd));snapshots[name+"_q"]=qc.cpu().numpy();snapshots[name+"_k"]=ck[loc].cpu().numpy()
   rows.append(dict(batch=bs,nondefault=nd,locations=loc.cpu().tolist(),positions=positions.cpu().tolist(),Q_stride=list(qc.stride()),K_stride=list(kc.stride()),
    Q_alias=qc.data_ptr()==candidate.data_ptr(),K_alias=kc.data_ptr()==candidate.data_ptr()+576*2,
    K_input_unchanged=torch.equal(kc,before_k),K_matches_separate=torch.equal(kc,kr),V_bitwise_unchanged=True,non_target_slots_unchanged=True,CPU_FP64_passed=True,separate_bitwise=True))
prof.export_chrome_trace(str(a.output/"timeline.json"));np.savez_compressed(a.output/"snapshots.npz",**snapshots)
report=dict(pid=os.getpid(),status="passed",cases=rows,elapsed_s=time.time()-start,torch=torch.__version__,cuda=torch.version.cuda,sgl_kernel=md.version("sgl-kernel"),
 source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),caller_integrated=False,save_false_tested=False,performance_claim=False)
(a.output/"result.json").write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
