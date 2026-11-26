"""P25-AA parent: one control origin, two serial workers, one shared budget."""
import argparse,json,os,signal,subprocess,sys,time
from pathlib import Path
from cadence_protocol import digest,write_json
from aa_protocol import CONFIG,load,need
from aa_control import control_scope,control_binding,receive_lease,make_job,supervise_owned
from aa_worker import validate_job

def main():
 origin=time.monotonic_ns() # Before ready and before any lease/EOF wait.
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--plan",type=Path,required=True)
 p.add_argument("--output",type=Path);p.add_argument("--execute",action="store_true");p.add_argument("--validate-only",action="store_true")
 p.add_argument("--validate-lease-only",action="store_true");p.add_argument("--control-timeout-ms",type=int);p.add_argument("--control-ready-file",type=Path)
 a=p.parse_args();plan=load(a.plan)
 timeout=None if a.control_timeout_ms is None else a.control_timeout_ms*1_000_000
 if a.validate_lease_only:
  if a.control_ready_file:write_json(a.control_ready_file,{"CPU_control_ready":True,"GPU_imports":False},exclusive=True)
  lease,timing=receive_lease(sys.stdin,origin,timeout)
  need(not any(n in sys.modules for n in ("torch","sglang","pynvml")),"GPU import in lease validation")
  print(json.dumps({"lease_validated":True,"GPU_imports":False,"window_id":lease["window_id"],**timing}));return 0
 if a.validate_only:
  print(json.dumps({"validated":True,"GPU_imports":False,"rows":128,"max_workers":2,"total_seconds":600}));return 0
 need(a.execute and plan["execution_enabled"] and a.output and os.name=="posix","explicit authorized POSIX window required")
 need(a.control_timeout_ms is None and a.control_ready_file is None,"CPU receive options are validation-only")
 a.output.mkdir(parents=True,exist_ok=False)
 write_json(a.output/"ready.json",{"pid":os.getpid(),"plan_sha256":digest(plan),"GPU_started":False},exclusive=True)
 lifecycle=[];failure=None;guard=None;bank=None;work=None;lease=None;control=None;timing=None;binding=None
 def elapsed():return time.monotonic_ns()-origin
 def stop_new():need(lease is not None and elapsed()<lease["soft_remaining_ns"],"global stop-new deadline")
 def own_stop(child):
  need(child.pid!=lease["protected_daemon_pid"] and child.args[1].endswith("aa_worker.py"),"unexpected/protected owned child")
  os.kill(child.pid,signal.SIGUSR1)
 try:
  lease,timing=receive_lease(sys.stdin,origin)
  control=control_scope(lease["window_id"],os.getpid(),origin)
  binding=control_binding(lease,control)
  write_json(a.output/"control.json",{"budget":lease,"budget_control":control,"control_binding_sha256":binding,"receive":timing},exclusive=True)
  stop_new() # Stale control cannot touch the shared research lock.
  import fcntl
  guard=Path(CONFIG["resources"]["lock"]).open("a");fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
  for phase in ("REF","HOLD"):
   stop_new();pre0=elapsed()
   result=subprocess.run(["/usr/lib/wsl/lib/nvidia-smi","--query-gpu=index,name,memory.free,memory.total,driver_version",
     "--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=5)
   pre={"begin_ns":pre0,"end_ns":elapsed(),"returncode":result.returncode,"csv":result.stdout.strip(),
        "clock_scope":f"{lease['window_id']}/parent/pid{os.getpid()}","phase":phase}
   write_json(a.output/(phase+"-preflight.json"),pre,exclusive=True);need(result.returncode==0,"GPU preflight query failed")
   values=result.stdout.strip().splitlines()[0].split(",")
   need(int(values[0])==0 and float(values[2])*1048576>=1073741824,"startup GPU0/free memory")
   stop_new()
   job=make_job(plan,phase,lease,control,guard.fileno(),digest(bank) if bank else None,
                str((a.output/"bank.json").resolve()) if bank else None,expected_binding=binding)
   validate_job(plan,job)
   jobpath=a.output/(phase+"-job.json");write_json(jobpath,job,exclusive=True)
   cmd=[sys.executable,str(Path(__file__).with_name("aa_worker.py")),"--plan",str(a.plan.resolve()),
        "--job",str(jobpath.resolve()),"--output",str((a.output/phase).resolve()),"--execute"]
   stop_new();launched=elapsed()
   with (a.output/(phase+"-stdout.log")).open("w",encoding="utf-8") as log:
    work=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,pass_fds=(guard.fileno(),),env=dict(os.environ,PYTHONUNBUFFERED="1",AA_PARENT_CONTROL_BINDING=binding))
    finished=supervise_owned(work,elapsed,job["soft_parent_deadline_ns"],job["hard_parent_deadline_ns"],
                             lease["protected_daemon_pid"],own_stop)
   lifecycle.append({"process":phase,"pid":work.pid,"start_ns":launched,"end_ns":elapsed(),
       "command":cmd,**finished,"clock_scope":f"{lease['window_id']}/parent/pid{os.getpid()}"})
   work=None;need(finished["exit_code"]==0,"worker failed/stopped: "+phase)
   if phase=="REF":
    stop_new()
    from analyze_aa_window import bank_from_reference
    bank=bank_from_reference(plan,a.output,elapsed(),lease["window_id"])
    write_json(a.output/"bank.json",bank,exclusive=True)
 except BaseException as e:failure={"type":type(e).__name__,"message":str(e)}
 finally:
  if work is not None and work.poll() is None:
   need(work.pid!=lease["protected_daemon_pid"],"protected owned child");work.kill();work.wait()
  write_json(a.output/"parent.json",{"schema":"P25-AA-parent2","pid":os.getpid(),
      "window_id":lease["window_id"] if lease else None,"plan_sha256":digest(plan),
      "clock_scope":f"parent/pid{os.getpid()}","budget":lease,"budget_control":control,
      "control_receive":timing,"control_binding_sha256":binding,"lifecycle":lifecycle,"failure":failure,"elapsed_ns":elapsed(),"worker_count":len(lifecycle)})
  if guard:guard.close()
 print(json.dumps({"collection_complete":failure is None and len(lifecycle)==2,"failure":failure}),flush=True)
 return 0 if failure is None else 2
if __name__=="__main__":raise SystemExit(main())
