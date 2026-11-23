"""Windows foreground launcher with a single600s wall clock and conservative lease."""
import argparse,json,os,subprocess,sys,time,uuid,datetime
from pathlib import Path
from cadence_protocol import digest,write_json
from aa_protocol import load,need,encode_lease
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--plan",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
 p.add_argument("--execute",action="store_true");p.add_argument("--validate-only",action="store_true");p.add_argument("--protected-daemon-pid",type=int)
 a=p.parse_args();plan=load(a.plan)
 if a.validate_only:
  print(json.dumps({"validated":True,"GPU_imports":False,"two_worker_parent_budget":600}));return 0
 need(os.name=="nt" and a.execute and plan["execution_enabled"] and a.protected_daemon_pid,"explicit authorized Windows launch required")
 need(not a.output.exists(),"one-shot output already exists")
 root=Path(__file__).resolve().parents[4]
 head=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
 need(head==plan["execution_checkout"] and not subprocess.check_output(["git","-C",str(root),"status","--porcelain"]),"clean frozen execution checkout")
 a.output.mkdir(parents=True,exist_ok=False)
 def linux(path):
  text=str(path.resolve()).replace("\\","/")
  return "/mnt/"+text[0].lower()+text[2:]
 command=["wsl.exe","-d","Ubuntu-22.04","--","/var/tmp/maas-10-gpu-01a1a5ba/bin/python",
    linux(Path(__file__).with_name("run_aa_window.py")),"--plan",linux(a.plan),"--output",linux(a.output/"window"),"--execute"]
 window_id=f"{plan['experiment']}-{uuid.uuid4().hex[:12]}"
 start=time.perf_counter_ns()
 record={"schema":"P25-AA-driver1","window_id":window_id,"plan_sha256":digest(plan),"execution_checkout":head,
    "command":command,"UTC_start":datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "parent_total_seconds":600,"stop_new_seconds":540,"attempts":1}
 write_json(a.output/"driver.json",record,exclusive=True)
 child=None;failure=None;rc=2
 try:
  with (a.output/"foreground.log").open("w",encoding="utf-8") as log:
   child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT)
   record["owned_WSL_pid"]=child.pid;write_json(a.output/"driver.json",record)
   ready=a.output/"window/ready.json"
   while not ready.exists() and child.poll() is None and time.perf_counter_ns()-start<540_000_000_000:time.sleep(.1)
   elapsed=time.perf_counter_ns()-start
   need(ready.exists(),"supervisor not ready before stop-new")
   lease={"window_id":window_id,"total_seconds":600,"stop_new_seconds":540,"driver_elapsed_at_send_ns":elapsed,
     "soft_remaining_ns":540_000_000_000-elapsed-1_000_000_000,
     "hard_remaining_ns":600_000_000_000-elapsed-1_000_000_000,"protected_daemon_pid":a.protected_daemon_pid}
   write_json(a.output/"lease.json",lease,exclusive=True)
   child.stdin.write(encode_lease(lease));child.stdin.flush();child.stdin.close()
   remaining=max(.1,(600_000_000_000-(time.perf_counter_ns()-start))/1e9)
   try:rc=child.wait(timeout=remaining)
   except subprocess.TimeoutExpired:
    need(child.pid!=a.protected_daemon_pid,"protected daemon PID");child.kill();child.wait();rc=124
 except BaseException as e:failure={"type":type(e).__name__,"message":str(e)}
 finally:
  if child:
   if child.stdin and not child.stdin.closed:child.stdin.close()
   if child.poll() is None:
    try:child.wait(timeout=max(.1,(600_000_000_000-(time.perf_counter_ns()-start))/1e9))
    except subprocess.TimeoutExpired:
     need(child.pid!=a.protected_daemon_pid,"protected daemon PID");child.kill();child.wait()
   rc=child.returncode
  record.update(exit_code=rc,wall_elapsed_ns=time.perf_counter_ns()-start,own_process_collected=True,
     failure=failure,UTC_end=datetime.datetime.now(datetime.timezone.utc).isoformat())
  record["within_600s"]=record["wall_elapsed_ns"]<=600_000_000_000
  write_json(a.output/"driver.json",record)
 from analyze_aa_window import analyze
 report=analyze(plan,a.output/"window")
 record["wall_elapsed_ns"]=time.perf_counter_ns()-start;record["within_600s"]=record["wall_elapsed_ns"]<=600_000_000_000
 write_json(a.output/"driver.json",record)
 if not record["within_600s"] or failure:
  report["integrity_valid"]=False;report["engineering_repeatability_qualified"]=False
  report["errors"].append("outer driver budget/failure")
 write_json(a.output/"qualification.json",report,exclusive=True)
 print(json.dumps({"driver":record,"qualified":report["engineering_repeatability_qualified"],"measured":report["measured_rows"],"matched":report["holdout_matched"]}))
 return rc if record["within_600s"] and failure is None else 2
if __name__=="__main__":raise SystemExit(main())
