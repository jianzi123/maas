"""Independent QA: CPU FP64 equation, KV bytes, nondefault stream and changed graphs."""
import argparse,base64,hashlib,importlib.metadata as md,json,sys
from pathlib import Path
p=argparse.ArgumentParser()
for n in ("source","output","build"): p.add_argument("--"+n,type=Path,required=True)
a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=False); sys.path.insert(0,str(a.source))
import torch
from decode_path import DecodePath
from kv_extension import FusedKV
from run_decode import verify_sources
torch.set_grad_enabled(False); torch.set_num_threads(2); torch.cuda.set_device(0)
assert torch.cuda.mem_get_info()[0]>=1024**3
torch.cuda.set_per_process_memory_fraction(.2)
def save(n,x): (a.output/n).write_text(json.dumps(x,indent=2,allow_nan=False)+"\n")
lock=json.loads((a.source/"decode-source-lock.json").read_text()); sources=verify_sources(lock)
pkg=md.distribution("sgl-kernel"); record={str(f):f for f in pkg.files}; provenance=[]
expected=json.loads((a.source/"evidence/decode-v0.16/mature-package-provenance.json").read_text())
for row in expected["files"]:
 h=hashlib.sha256(Path(pkg.locate_file(row["path"])).read_bytes()).digest(); rf=record[row["path"]].hash
 assert rf.mode=="sha256" and base64.urlsafe_b64encode(h).decode().rstrip("=")==rf.value and h.hex()==row["sha256"]
 provenance.append(dict(path=row["path"],sha256=h.hex(),RECORD_matches=True))
d=torch.cuda.get_device_properties(0)
save("environment.json",dict(python=sys.version,versions={n:md.version(n) for n in ("torch","sglang","sgl-kernel","triton","cupy-cuda12x")},GPU=d.name,SM=d.multi_processor_count,CC=[d.major,d.minor],total_bytes=d.total_memory,allocator_fraction=.2,six_sources=sources,source_commit=lock["commit"],wheel_files=provenance,wheel_claim="installed RECORD and fixed binary self consistency, not upstream source attestation"))
ext=FusedKV(a.build)
def reference(p):
 q=p.q.cpu().double(); k=p.logical_k.cpu().double(); v=p.logical_v.cpu().double(); out=[]; start=0
 for b,n in enumerate(p.lengths):
  heads=[]
  for h in range(p.hq):
   kh=h//(p.hq//p.hkv); scores=k[start:start+n,kh].mv(q[b,h])*p.dim**-.5
   heads.append(v[start:start+n,kh].T.mv(torch.softmax(scores,dim=0)))
  out.append(torch.stack(heads)); start+=n
 return torch.stack(out)
def check(p,out):
 ref=reference(p); got=out.reshape(ref.shape).cpu().double()
 assert torch.isfinite(got).all() and torch.isfinite(ref).all()
 tol=.003 if p.q.dtype==torch.float16 else .02
 torch.testing.assert_close(got,ref,rtol=tol,atol=tol)
 for cache,new in ((p.pool.get_key_buffer(0),p.new_k),(p.pool.get_value_buffer(0),p.new_v)):
  assert torch.equal(cache[p.locations].contiguous().view(torch.uint8),new.contiguous().view(torch.uint8))
  assert torch.isnan(cache[0]).all()
 return dict(max_abs=float((got-ref).abs().max()),tolerance=tol,KV_bitwise=True,unused_slot_poisoned=True)
def writer(p,name):
 if name=="original": return p.pool.set_kv_buffer
 if name=="prototype": return ext.bind(p)
 def direct(layer,loc,k,v): return torch.ops.sgl_kernel.store_kv_cache(p.pool.get_key_buffer(0),p.pool.get_value_buffer(0),loc,k,v)
 return direct
checks=[]; unsupported=[]
for dtype in (torch.float16,torch.bfloat16):
 for dim,lengths in ((64,[1,17]),(80,[17,33]),(128,[31,33,129])):
  for sn in ("current","nondefault"):
   for name in ("original","prototype","mature-direct"):
    stream=torch.cuda.current_stream() if sn=="current" else torch.cuda.Stream()
    with torch.cuda.stream(stream):
     p=DecodePath(lengths,dim=dim,dtype=dtype,seed=20261119); p.pool.set_kv_buffer=writer(p,name)
     p.pool.get_key_buffer(0)[p.locations]=float("nan"); p.pool.get_value_buffer(0)[p.locations]=float("nan")
     try: out=p.forward(); stream.synchronize()
     except RuntimeError as e:
      if name!="mature-direct" or dim!=80 or "must be divisible by 128" not in str(e): raise
      unsupported.append(dict(dtype=str(dtype),dim=dim,stream=sn,error=str(e),fallback=False)); continue
     checks.append(dict(dtype=str(dtype),dim=dim,lengths=lengths,stream=sn,writer=name,**check(p,out)))
    print("QA numeric",dtype,dim,sn,name,flush=True)
save("correctness.json",dict(checks=checks,unsupported=unsupported,oracle="independent CPU FP64 head-by-head equation, no source gather/LSE/reference",Engine=False))
graphs=[]
for dtype in (torch.float16,torch.bfloat16):
 for name in ("original","prototype","mature-direct"):
  stream=torch.cuda.Stream()
  with torch.cuda.stream(stream):
   p=DecodePath([33,129],dtype=dtype,seed=20261120); p.pool.set_kv_buffer=writer(p,name)
   for _ in range(5): p.forward()
  stream.synchronize(); g=torch.cuda.CUDAGraph()
  with torch.cuda.graph(g,stream=stream): out=p.forward()
  with torch.cuda.stream(stream):
   p.new_k.add_(.03125); p.new_v.sub_(.0625); p.q.mul_(1.03125)
   ix=torch.tensor([32,161],device="cuda"); p.logical_k[ix]=p.new_k; p.logical_v[ix]=p.new_v
   p.pool.get_key_buffer(0)[p.locations]=float("nan"); p.pool.get_value_buffer(0)[p.locations]=float("nan"); out.fill_(float("nan")); g.replay()
  stream.synchronize()
  graphs.append(dict(dtype=str(dtype),writer=name,stream="nondefault",changed_Q_K_V=True,poisoned_output_and_target_KV=True,**check(p,out)))
  print("QA changed graph",dtype,name,flush=True)
save("graphs.json",dict(checks=graphs,Engine_capture_mode=False))
save("success.json",dict(numerical_passed=len(checks),unsupported=len(unsupported),graph_passed=len(graphs),Engine=False,Sanitizer=False))
