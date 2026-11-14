"""Window A only: five structural/state processes and event/support checks, no cost benchmark."""
import argparse,os,subprocess,sys,time,signal,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--source",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args();a.source=a.source.resolve();a.output=a.output.resolve();a.output.mkdir(exist_ok=False)
cache=Path("/var/tmp/maas7-kv19-555c69ac1872");cache.mkdir(exist_ok=False)
env=dict(os.environ,PYTHONPATH=str(a.source),HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",HF_DATASETS_OFFLINE="1",PYTHONDONTWRITEBYTECODE="1")
for key,n in (("TRITON_CACHE_DIR","triton"),("CUDA_CACHE_PATH","cuda"),("XDG_CACHE_HOME","xdg")):
 (cache/n).mkdir();env[key]=str(cache/n)
records=[]
def run(name,args):
 before=subprocess.check_output(["/usr/lib/wsl/lib/nvidia-smi","--query-gpu=name,memory.free,clocks.sm,temperature.gpu,power.draw","--format=csv,noheader,nounits"]).decode();assert float(before.split(",")[1])>=1024
 with (a.output/(name+".log")).open("w") as log:
  proc=subprocess.Popen([str(v) for v in args],env=env,cwd=a.source,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);start=time.time()
  try:rc=proc.wait(timeout=600)
  except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait();rc=124
 records.append(dict(name=name,argv=[str(v) for v in args],pid=proc.pid,exit_code=rc,seconds=time.time()-start,before=before));(a.output/"commands.json").write_text(json.dumps(records,indent=2));print(json.dumps(records[-1]),flush=True)
 if rc:raise SystemExit(rc)
for variant in ("native","mature","late"):
 run("integration-"+variant,[sys.executable,a.source/"run_native_kv_integration.py","--variant",variant,"--output",a.output/variant,"--source-lock",a.source/"evidence/framework-v0.18/framework-source-lock.json"])
for variant in ("native","mature"):
 run("state-"+variant,[sys.executable,Path(__file__).with_name("state.py").resolve(),"--variant",variant,"--source",a.source,"--output",a.output/("state-"+variant)])
run("event-support",[sys.executable,Path(__file__).with_name("event_support.py").resolve(),"--source",a.source,"--output",a.output/"event-support"])
print("Window A complete; research lock released",flush=True)
