"""P25-AA parent: one inherited research lock, two serial workers, one budget."""
import argparse,json,os,signal,subprocess,sys,time,uuid
from pathlib import Path
from cadence_protocol import digest,write_json
from aa_protocol import CONFIG,load,need,check_budget,read_lease
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--plan",type=Path,required=True)
 p.add_argument("--output",type=Path);p.add_argument("--execute",action="store_true");p.add_argument("--validate-only",action="store_true")
 p.add_argument("--validate-lease-only",action="store_true")
 a=p.parse_args();plan=load(a.plan)
 if a.validate_lease_only:
  lease=read_lease(sys.stdin)
  need(not any(n in sys.modules for n in ("torch","sglang","pynvml")),"GPU import in lease validation")
  print(json.dumps({"lease_validated":True,"GPU_imports":False,"window_id":lease["window_id"]}));return 0
 if a.validate_only:
  print(json.dumps({"validated":True,"GPU_imports":False,"rows":128,"max_workers":2,"total_seconds":600}));return 0
 need(a.execute and plan["execution_enabled"] and a.output and os.name=="posix","explicit authorized POSIX window required")
 a.output.mkdir(parents=True,exist_ok=False)
 write_json(a.output/"ready.json",{"pid":os.getpid(),"plan_sha256":digest(plan),"GPU_started":False},exclusive=True)
 lease=read_lease(sys.stdin)
 start=time.perf_counter_ns();clock=f"{lease['window_id']}/parent/pid{os.getpid()}"
 lifecycle=[];failure=None;guard=None;bank=None;work=None
 def elapsed():return time.perf_counter_ns()-start
 def stop_new():need(elapsed()<lease["soft_remaining_ns"],"global stop-new deadline")
 def own_signal(child,sig):
  need(child.pid!=lease["protected_daemon_pid"],"protected daemon PID")
  need(child.args[1].endswith("aa_worker.py"),"unexpected owned child")
  os.kill(child.pid,sig)
 try:
  import fcntl
  guard=Path(CONFIG["resources"]["lock"]).open("a")
  fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB);stop_new()
  for phase in ("REF","HOLD"):
   stop_new()
   # Identical real resource observation before EACH fresh process, outside hot work.
   pre0=elapsed()
   result=subprocess.run(["/usr/lib/wsl/lib/nvidia-smi","--query-gpu=index,name,memory.free,memory.total,driver_version",
     "--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=5)
   pre={"begin_ns":pre0,"end_ns":elapsed(),"returncode":result.returncode,"csv":result.stdout.strip(),
        "clock_scope":clock,"phase":phase}
   write_json(a.output/(phase+"-preflight.json"),pre,exclusive=True)
   need(result.returncode==0,"GPU preflight query failed")
   values=result.stdout.strip().splitlines()[0].split(",")
   need(int(values[0])==0 and float(values[2])*1048576>=1073741824,"startup GPU0/free memory")
   stop_new()
   job={"schema":"P25-AA-job1","plan_sha256":digest(plan),"window_id":lease["window_id"],"process":phase,
        "parent_pid":os.getpid(),"research_lock_fd":guard.fileno(),"budget":lease,"budget_lease_sha256":digest(lease),
        "launch_parent_elapsed_ns":elapsed(),"soft_parent_deadline_ns":lease["soft_remaining_ns"],
        "hard_parent_deadline_ns":lease["hard_remaining_ns"],"bank_sha256":digest(bank) if bank else None,
        "bank_path":str((a.output/"bank.json").resolve()) if bank else None}
   jobpath=a.output/(phase+"-job.json");write_json(jobpath,job,exclusive=True)
   cmd=[sys.executable,str(Path(__file__).with_name("aa_worker.py")),"--plan",str(a.plan.resolve()),
        "--job",str(jobpath.resolve()),"--output",str((a.output/phase).resolve()),"--execute"]
   stop_new();launched=elapsed()
   with (a.output/(phase+"-stdout.log")).open("w",encoding="utf-8") as log:
    work=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,pass_fds=(guard.fileno(),),env=dict(os.environ,PYTHONUNBUFFERED="1"))
    sent=False;soft_signal_ns=None;forced=False
    while work.poll() is None:
     now=elapsed()
     if now>=lease["soft_remaining_ns"] and not sent:
      own_signal(work,signal.SIGUSR1);sent=True;soft_signal_ns=now
     force_at=min(lease["soft_remaining_ns"]+10_000_000_000,lease["hard_remaining_ns"]-20_000_000_000)
     if now>=force_at:
      own_signal(work,signal.SIGKILL);forced=True;break
     time.sleep(.05)
    rc=work.wait()
   lifecycle.append({"process":phase,"pid":work.pid,"start_ns":launched,"end_ns":elapsed(),
       "command":cmd,"exit_code":rc,"soft_signal_ns":soft_signal_ns,"forced_kill":forced,"clock_scope":clock})
   work=None
   need(rc==0,"worker failed/stopped: "+phase)
   if phase=="REF":
    stop_new()
    from analyze_aa_window import bank_from_reference
    bank=bank_from_reference(plan,a.output,elapsed(),lease["window_id"])
    write_json(a.output/"bank.json",bank,exclusive=True)
 except BaseException as e:
  failure={"type":type(e).__name__,"message":str(e)}
 finally:
  if work is not None and work.poll() is None:
   own_signal(work,signal.SIGKILL);work.wait()
  write_json(a.output/"parent.json",{"schema":"P25-AA-parent1","pid":os.getpid(),"window_id":lease["window_id"],
      "plan_sha256":digest(plan),"clock_scope":clock,"budget":lease,"lifecycle":lifecycle,
      "failure":failure,"elapsed_ns":elapsed(),"worker_count":len(lifecycle)})
  if guard:guard.close()
 print(json.dumps({"collection_complete":failure is None and len(lifecycle)==2,"failure":failure}),flush=True)
 return 0 if failure is None else 2
if __name__=="__main__":raise SystemExit(main())
