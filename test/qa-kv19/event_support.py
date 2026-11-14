"""Explicit producer/write/read events and pre-mutation rejection; not a model test."""
import argparse,sys,fcntl,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--source",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args();a.output.mkdir(exist_ok=False)
guard=open("/var/tmp/maas-10-gpu-01a1a5ba/gpu0-research.lock","a");fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
sys.path.insert(0,str(a.source))
import torch
from types import SimpleNamespace
from native_kv_binding import mature_kv_binding
from sglang.srt.mem_cache.memory_pool import MHATokenToKVPool
torch.set_grad_enabled(False);torch.cuda.set_per_process_memory_fraction(.2)
pool=MHATokenToKVPool(32,1,torch.float16,3,64,1,"cuda",False);layer=SimpleNamespace(layer_id=0)
producer,writer,reader=[torch.cuda.Stream() for _ in range(3)]
original=MHATokenToKVPool.set_kv_buffer;rows=[];rejected=[]
with mature_kv_binding():
 for phase in (0,1):
  with torch.cuda.stream(producer):
   base=torch.full((12,960),float(phase+2),device="cuda",dtype=torch.float16)
   k=base[:,576:768].view(12,3,64);v=base[:,768:960].view(12,3,64)
   loc=torch.arange(1+phase*12,13+phase*12,device="cuda",dtype=torch.int64)
   ready=torch.cuda.Event();ready.record()
  with torch.cuda.stream(writer):
   writer.wait_event(ready);pool.set_kv_buffer(layer,loc,k,v);written=torch.cuda.Event();written.record()
  with torch.cuda.stream(reader):
   reader.wait_event(written)
   ok=(pool.get_key_buffer(0)[loc]==k).all() & (pool.get_value_buffer(0)[loc]==v).all()
   done=torch.cuda.Event();done.record()
  done.synchronize();assert bool(ok) and k.stride()==(960,64,1) and not k.is_contiguous()
  rows.append(dict(phase=phase,locations=loc.cpu().tolist(),stride=list(k.stride()),explicit_producer_write_read_events=True,no_global_synchronize=True))
 before=(pool.get_key_buffer(0).clone(),pool.get_value_buffer(0).clone())
 tests=[("k_scale",dict(k_scale=1.0)),("v_scale",dict(v_scale=1.0)),("layer",dict(layer_id_override=99))]
 for name,kwargs in tests:
  try:pool.set_kv_buffer(layer,loc,k,v,**kwargs)
  except ValueError:rejected.append(name)
  else:raise AssertionError("unsupported accepted")
 for name in ("dtype","quantized"):
  old=pool.store_dtype
  if name=="quantized":pool.store_dtype=torch.uint8
  try:
   try:pool.set_kv_buffer(layer,loc,k.float() if name=="dtype" else k,v)
   except ValueError:rejected.append(name)
   else:raise AssertionError("unsupported accepted")
  finally:pool.store_dtype=old
 assert torch.equal(before[0].view(torch.uint8),pool.get_key_buffer(0).view(torch.uint8))
 assert torch.equal(before[1].view(torch.uint8),pool.get_value_buffer(0).view(torch.uint8))
assert MHATokenToKVPool.set_kv_buffer is original
try:
 with mature_kv_binding():raise RuntimeError("QA intentional context exit")
except RuntimeError:pass
assert MHATokenToKVPool.set_kv_buffer is original
(a.output/"result.json").write_text(json.dumps(dict(rows=rows,rejected=rejected,cache_unchanged_after_rejection=True,original_method_restored=True,only_FP16_positive=True),indent=2))
