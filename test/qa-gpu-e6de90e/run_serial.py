"""Foreground WSL supervisor: pinned GPU batch, private build/cache, sequential children."""
import argparse,difflib,hashlib,json,os,shutil,subprocess,sys,time,signal
from pathlib import Path
p=argparse.ArgumentParser()
for n in ("source","output"): p.add_argument("--"+n,type=Path,required=True)
a=p.parse_args(); a.source=a.source.resolve(); a.output=a.output.resolve()
a.output.mkdir(parents=True,exist_ok=False)
build=Path("/tmp/maas7-gpu-e6de90e-555c69ac1872"); build.mkdir(parents=True,exist_ok=False)
source=a.output/"qa-source"; shutil.copytree(a.source,source); changes=[]
for f in source.glob("*.py"):
 old=f.read_text(); new=old.replace("/tmp/maas-10-gpu-9bf1ab626448/aten-kv-build",str(build/"aten-kv-build"))
 if old!=new:
  f.write_text(new); changes.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile=f.name+"@e6de90e",tofile=f.name+"@QA-build-path-only"))
(a.output/"QA-build-path-only.patch").write_text("".join(changes))
env=dict(os.environ,PYTHONUNBUFFERED="1",PYTHONDONTWRITEBYTECODE="1",PYTHONPATH=str(source))
for k,d in (("TRITON_CACHE_DIR","triton"),("CUPY_CACHE_DIR","cupy"),("CUDA_CACHE_PATH","cuda"),("TORCH_EXTENSIONS_DIR","extensions"),("XDG_CACHE_HOME","xdg")):
 (build/d).mkdir(); env[k]=str(build/d)
records=[]
def telemetry():
 r=subprocess.run(["/usr/lib/wsl/lib/nvidia-smi","--query-gpu=timestamp,name,memory.free,memory.used,clocks.sm,temperature.gpu,power.draw,utilization.gpu","--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=10)
 assert r.returncode==0 and float(r.stdout.split(",")[2].strip())>=1024,"GPU gate failed"
 apps=subprocess.run(["/usr/lib/wsl/lib/nvidia-smi","--query-compute-apps=pid,process_name,used_gpu_memory","--format=csv,noheader"],capture_output=True,text=True,timeout=10)
 return dict(csv=r.stdout.strip(),compute_apps=apps.stdout.strip())
def execute(name,args,limit):
 before=telemetry(); start=time.time()
 with (a.output/(name+".log")).open("w") as f:
  proc=subprocess.Popen([str(v) for v in args],cwd=source,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
  try: rc=proc.wait(timeout=limit)
  except subprocess.TimeoutExpired:
   os.killpg(proc.pid,signal.SIGTERM)
   try: proc.wait(timeout=10)
   except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL); proc.wait()
   rc=124
 r=dict(name=name,argv=[str(v) for v in args],pid=proc.pid,exit_code=rc,limit_seconds=limit,elapsed_seconds=time.time()-start,before=before,after=telemetry())
 records.append(r); (a.output/"commands.json").write_text(json.dumps(records,indent=2)+"\n")
 print(json.dumps({k:r[k] for k in ("name","pid","exit_code","elapsed_seconds")}),flush=True); return rc
rc=execute("independent",[sys.executable,Path(__file__).with_name("oracle.py"),"--source",source,"--build",build/"aten-kv-build","--output",a.output/"independent"],600)
if rc: print("QA numerical gate failed; timing batch not run",flush=True); raise SystemExit(rc)
execute("graph",[sys.executable,source/"check_decode_graph.py","--output",a.output/"graph"],240)
execute("device-fault",[sys.executable,source/"check_kv_device_fault.py","--output",a.output/"device-fault"],180)
for study,script in (("split","run_decode.py"),("fusion","run_kv_fusion.py"),("mature","run_mature_kv.py")):
 for i,seed in enumerate((20261113,20261114,20261115),1):
  args=[sys.executable,source/script,"--source-lock",source/"decode-source-lock.json","--seed",seed,"--output",a.output/(study+str(i))]
  if i==1: args.append("--profile")
  execute(study+str(i),args,600)
artifacts={str(f.relative_to(build)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (build/"aten-kv-build").glob("*") if f.is_file() and f.suffix in (".so",".o",".ninja")}
(a.output/"build-provenance.json").write_text(json.dumps(dict(directory=str(build),files=artifacts,all_own_children_collected=True,cache_retained_for_reproducibility=True),indent=2)+"\n")
print("QA serial batch complete; no QA child running",flush=True)
raise SystemExit(int(any(r["exit_code"] for r in records)))
