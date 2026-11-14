"""Independent cap6 QA; same advisory research lock and private caches."""
import argparse,fcntl,hashlib,importlib.metadata as md,json,os,subprocess,sys,time,signal,statistics
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("--source",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--oracle",action="store_true")
a=p.parse_args(); a.source=a.source.resolve();a.output=a.output.resolve()
def save(p,x): p.write_text(json.dumps(x,indent=2,allow_nan=False)+"\n")
if a.oracle:
 a.output.mkdir(parents=True,exist_ok=False)
 guard=open("/var/tmp/maas-10-gpu-01a1a5ba/gpu0-research.lock","a");fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
 sys.path.insert(0,str(a.source))
 import torch
 from run_split_cap6 import make,CELLS
 from run_decode import verify_sources
 torch.set_grad_enabled(False);torch.set_num_threads(2);torch.cuda.set_device(0)
 assert torch.cuda.mem_get_info()[0]>=1024**3;torch.cuda.set_per_process_memory_fraction(.2)
 sources=verify_sources(json.loads((a.source/"decode-source-lock.json").read_text()))
 packages={}
 for n in ("torch","triton","sglang","sgl-kernel","cupy-cuda12x","numpy","transformers","pycryptodomex"):
  try:
   d=md.distribution(n);packages[n]=dict(version=d.version,location=str(d.locate_file("")))
  except md.PackageNotFoundError: packages[n]=dict(unavailable=True)
 pkg=md.distribution("sgl-kernel");checks=[]
 for f in pkg.files:
  if str(f).endswith(".so") or str(f)=="sgl_kernel/memory.py":
   import base64
   h=hashlib.sha256(Path(pkg.locate_file(f)).read_bytes()).digest()
   assert f.hash and f.hash.mode=="sha256" and base64.urlsafe_b64encode(h).decode().rstrip("=")==f.hash.value
   checks.append(dict(path=str(f),sha256=h.hex(),RECORD=True))
 wheels=[]
 for w in Path("/var/tmp/maas-10-gpu-01a1a5ba").rglob("sgl_kernel*.whl"):
  h=hashlib.sha256(w.read_bytes()).hexdigest();wheels.append(dict(path=str(w),bytes=w.stat().st_size,sha256=h,expected_match=h=="fddc3a23e0ba9252381cdefaee20ebfb2722d0ea07648dde73dc7c8e1933e339"))
  assert h=="fddc3a23e0ba9252381cdefaee20ebfb2722d0ea07648dde73dc7c8e1933e339"
 save(a.output/"environment.json",dict(python=sys.version,prefix=sys.prefix,packages=packages,six_sources=sources,wheel_RECORD=checks,available_wheel_hashes=wheels,full_wheel_reverified=bool(wheels),previous_environment="/tmp/maas-10-gpu-9bf1ab626448",cross_environment_timings_compared=False))
 def ref(p):
  q=p.q.cpu().double();k=p.logical_k.cpu().double();v=p.logical_v.cpu().double();out=[];start=0
  for b,n in enumerate(p.lengths):
   heads=[]
   for h in range(p.hq):
    kh=h//(p.hq//p.hkv);prob=torch.softmax(k[start:start+n,kh].mv(q[b,h])*p.dim**-.5,0)
    heads.append(v[start:start+n,kh].T.mv(prob))
   out.append(torch.stack(heads));start+=n
  return torch.stack(out)
 def check(p,out):
  expected=ref(p);got=out.reshape(expected.shape).cpu().double();tol=.003 if p.q.dtype==torch.float16 else .02
  assert torch.isfinite(got).all();torch.testing.assert_close(got,expected,rtol=tol,atol=tol)
  for c,n in ((p.pool.get_key_buffer(0),p.new_k),(p.pool.get_value_buffer(0),p.new_v)):
   assert torch.equal(c[p.locations].contiguous().view(torch.uint8),n.contiguous().view(torch.uint8))
  return dict(max_abs=float((got-expected).abs().max()),tolerance=tol,KV_bitwise=True)
 rows=[]
 for dtype in (torch.float16,torch.bfloat16):
  for case,lengths in CELLS:
   for cap in (8,6):
    stream=torch.cuda.Stream()
    with torch.cuda.stream(stream):
     p=make(lengths,cap,20261117,dtype);out=p.forward()
    stream.synchronize();val=check(p,out);check(p,p.raw_decode())
    # Both captured raw and captured backend must consume changed inputs.
    with torch.cuda.stream(stream):
     for _ in range(3):p.forward();p.raw_decode()
    stream.synchronize()
    rawg=torch.cuda.CUDAGraph();fullg=torch.cuda.CUDAGraph()
    with torch.cuda.graph(rawg,stream=stream):p.raw_decode()
    with torch.cuda.graph(fullg,stream=stream):out=p.forward()
    with torch.cuda.stream(stream):
     p.q.mul_(1.03125);p.new_k.add_(.03125);p.new_v.sub_(.0625)
     ix=torch.tensor([sum(lengths[:i+1])-1 for i in range(len(lengths))],device="cuda")
     p.logical_k[ix]=p.new_k;p.logical_v[ix]=p.new_v
     p.pool.get_key_buffer(0)[p.locations]=float("nan");p.pool.get_value_buffer(0)[p.locations]=float("nan");out.fill_(float("nan"))
     fullg.replay()
    stream.synchronize();check(p,out)
    with torch.cuda.stream(stream):p.o.fill_(float("nan"));rawg.replay()
    stream.synchronize();check(p,p.o)
    rows.append(dict(case=case,dtype=str(dtype),cap=cap,nondefault_stream=True,raw_and_backend_graph_changed_QKV_poison=True,**val))
    print(case,str(dtype),cap,"PASS",flush=True)
 save(a.output/"results.json",dict(checks=rows,numerical_passed=len(rows),changed_graphs_passed=2*len(rows),Engine=False))
 raise SystemExit(0)
a.output.mkdir(parents=True,exist_ok=False)
cache=Path("/var/tmp/maas7-cap6-555c69ac1872");cache.mkdir(exist_ok=False)
env=dict(os.environ,PYTHONUNBUFFERED="1",PYTHONDONTWRITEBYTECODE="1")
for k,n in (("TRITON_CACHE_DIR","triton"),("CUDA_CACHE_PATH","cuda"),("CUPY_CACHE_DIR","cupy"),("XDG_CACHE_HOME","xdg")):
 (cache/n).mkdir();env[k]=str(cache/n)
records=[]
def run(name,args):
 before=subprocess.check_output(["/usr/lib/wsl/lib/nvidia-smi","--query-gpu=timestamp,memory.free,clocks.sm,temperature.gpu,power.draw","--format=csv,noheader,nounits"]).decode()
 assert float(before.split(",")[1])>=1024
 with (a.output/(name+".log")).open("w") as log:
  child=subprocess.Popen([str(v) for v in args],env=env,cwd=a.source,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);start=time.time()
  try: rc=child.wait(timeout=600)
  except subprocess.TimeoutExpired:
   os.killpg(child.pid,signal.SIGTERM)
   try:child.wait(timeout=10)
   except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
   rc=124
 records.append(dict(name=name,pid=child.pid,argv=[str(v) for v in args],exit_code=rc,seconds=time.time()-start,telemetry_before=before))
 save(a.output/"commands.json",records);print(json.dumps(records[-1]),flush=True)
 return rc
if run("oracle",[sys.executable,Path(__file__).resolve(),"--source",a.source,"--output",a.output/"oracle","--oracle"]):raise SystemExit(1)
for i,seed in enumerate((20261114,20261115,20261116),1):
 args=[sys.executable,a.source/"run_split_cap6.py","--source-lock",a.source/"decode-source-lock.json","--seed",seed,"--output",a.output/("run"+str(i))]
 if i==1:args.append("--profile")
 run("run"+str(i),args)
print("All own children collected",flush=True)
raise SystemExit(int(any(r["exit_code"] for r in records)))
