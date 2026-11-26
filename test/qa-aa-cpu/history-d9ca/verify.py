"""Independent CPU QA of 4bed4b4. Production pipes only use disabled plans."""
import argparse,copy,hashlib,io,json,os,subprocess,sys,time,zipfile,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--source",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--protected-pid",type=int,required=True);a=p.parse_args()
src=a.source.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
sys.path.insert(0,str(src))
from aa_protocol import make_plan,encode_lease,read_lease,check_budget,check_binding
from aa_worker import validate_job
from cadence_protocol import digest
from analyze_aa_window import analyze
checks=[];commands=[]
def require(x,msg="independent oracle mismatch"):
 if not x:raise AssertionError(msg)
def case(name,fn):
 try:fn();checks.append(dict(id=name,status="passed"))
 except Exception as e:checks.append(dict(id=name,status="failed",error=repr(e)))
def rejected(fn):
 try:fn()
 except (ValueError,KeyError,TypeError):return
 raise AssertionError("invalid metadata accepted")
plan=make_plan("QA_AA_DISABLED","4bed4b4be2ca294b9305cfb28fe1ab03f6164ec0",False)
planpath=out/"disabled-plan.json";planpath.write_text(json.dumps(plan))
lease=dict(window_id="QA_CPU_WINDOW",total_seconds=600,stop_new_seconds=540,driver_elapsed_at_send_ns=10000000000,soft_remaining_ns=529000000000,hard_remaining_ns=589000000000,protected_daemon_pid=a.protected_pid)
packet=encode_lease(lease)
job=dict(schema="P25-AA-job1",plan_sha256=digest(plan),process="REF",window_id=lease["window_id"],budget=lease,budget_lease_sha256=digest(lease),
 parent_pid=os.getpid(),research_lock_fd=7,launch_parent_elapsed_ns=0,soft_parent_deadline_ns=529000000000,hard_parent_deadline_ns=589000000000,bank_sha256=None,bank_path=None)
def positive():check_budget(lease);validate_job(plan,job);require(packet[-1:]==bytes((10,)));require(read_lease(io.StringIO(packet.decode()))==lease)
case("LEASE-01-shared-encode-read-valid",positive)
case("BUDGET-01-original-soft-positive",lambda:validate_job(plan,job))
def soft_bug():
 bad=copy.deepcopy(job);bad["soft_parent_deadline_ns"]=550000000000
 (out/"AA-CPU-01-job.json").write_text(json.dumps(bad,indent=2))
 rejected(lambda:validate_job(plan,bad))
case("AA-CPU-01-soft-increase-must-reject",soft_bug)
for name,field,value in (("hard-reset","hard_parent_deadline_ns",600000000000),("late-launch","launch_parent_elapsed_ns",529000000000),("plan-hash","plan_sha256","0"*64),("lease-hash","budget_lease_sha256","0"*64),("window","window_id","FOREIGN"),("phase","process","OTHER"),("REF-bank","bank_sha256","a"*64)):
 def test(field=field,value=value):
  x=copy.deepcopy(job);x[field]=value;rejected(lambda:validate_job(plan,x))
 case("JOB-"+name,test)
def hold():
 x=copy.deepcopy(job);x.update(process="HOLD",bank_sha256="b"*64,launch_parent_elapsed_ns=100000000000)
 validate_job(plan,x);require(x["budget"]==lease and x["budget_lease_sha256"]==digest(lease))
 x["hard_parent_deadline_ns"]=600000000000;rejected(lambda:validate_job(plan,x))
case("BUDGET-02-HOLD-shares-original-lease",hold)
for field,value in (("soft_remaining_ns",540000000000),("hard_remaining_ns",600000000000)):
 def test(field=field,value=value):
  x=copy.deepcopy(lease);x[field]=value;rejected(lambda:check_budget(x))
 case("LEASE-reject-"+field,test)
# Child import guard: actual validation entry points may not import GPU frameworks or touch resources.
guard=out/"guard";guard.mkdir()
(guard/"sitecustomize.py").write_text("""import sys,importlib.abc
class CPUOnly(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'torch','sglang','pynvml','aa_runtime'}:raise RuntimeError('QA forbidden GPU import')
sys.meta_path.insert(0,CPUOnly())
def audit(event,args):
 if event=='open' and str(args[0]).endswith('gpu0-research.lock'):raise RuntimeError('QA forbidden shared lock')
 if event=='subprocess.Popen' and 'nvidia-smi' in str(args):raise RuntimeError('QA forbidden resource query')
sys.addaudithook(audit)
""")
env=dict(os.environ,PYTHONPATH=str(guard)+os.pathsep+str(src),PYTHONDONTWRITEBYTECODE="1")
cli=[sys.executable,"-u",str(src/"run_aa_window.py"),"--plan",str(planpath),"--validate-lease-only"]
def own_kill(child):
 require(child.pid!=a.protected_pid and child.pid!=os.getpid(),"protected PID collision")
 child.kill();child.wait(timeout=3)
def pipe(name,data,expect,delay=None,no_eof=False,existing=False):
 folder=out/name;folder.mkdir();report=folder/"report.json"
 if existing:report.write_bytes(b"QA existing successful report sentinel")
 before=report.read_bytes() if report.exists() else None
 cmd=cli+["--output",str(folder)]
 start=time.perf_counter_ns();child=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
 try:
  if no_eof:
   child.stdin.write(data);child.stdin.flush()
   try:child.wait(timeout=.4)
   except subprocess.TimeoutExpired:pass
   else:raise AssertionError("accepted without EOF")
   own_kill(child);child.stdin.close();child.stdin=None;stdout,stderr=child.communicate(timeout=3)
   classification="control_channel_timeout_collected"
  elif delay:
   first,late=delay;child.stdin.write(first);child.stdin.flush();time.sleep(.2);child.stdin.write(late);child.stdin.close();child.stdin=None
   stdout,stderr=child.communicate(timeout=4);classification="validator"
  else:stdout,stderr=child.communicate(input=data,timeout=4);classification="validator"
 except BaseException:
  if child.poll() is None:own_kill(child)
  child.communicate();raise
 require(child.poll() is not None)
 (folder/"stdout.log").write_bytes(stdout);(folder/"stderr.log").write_bytes(stderr)
 elapsed=time.perf_counter_ns()-start
 commands.append(dict(case=name,argv=cmd,pid=child.pid,exit_code=child.returncode,classification=classification,elapsed_ns=elapsed,own_child_collected=True))
 if expect=="accept":require(child.returncode==0 and json.loads(stdout)["lease_validated"])
 elif expect=="reject":require(child.returncode!=0)
 else:require(classification=="control_channel_timeout_collected")
 require((report.read_bytes() if report.exists() else None)==before,"new report or overwrite")
 require(b"QA forbidden" not in stderr,"attempted forbidden operation")
cases=[("PIPE-LF-EOF",packet,"accept"),("PIPE-old-5c6e",packet[:-1]+bytes((92,110)),"reject"),("PIPE-empty",b"","reject"),("PIPE-truncated",packet[:30],"reject"),("PIPE-json-truncated-LF",packet[:30]+b"\n","reject"),("PIPE-multiframe",packet+packet,"reject"),("PIPE-extra-data",packet+b"trailing","reject"),("PIPE-extra-LF",packet+b"\n","reject")]
for name,data,expected in cases:case(name,lambda n=name,d=data,e=expected:pipe(n,d,e))
case("PIPE-no-EOF-bounded",lambda:pipe("noEOF",packet,"timeout",no_eof=True))
case("PIPE-delayed-control-rejected",lambda:pipe("late-data",None,"reject",delay=(packet,b"late")))
case("PIPE-delayed-EOF-valid-and-duration-kept",lambda:pipe("lateEOF",None,"accept",delay=(packet,b"")))
case("PIPE-no-overwrite-old-report",lambda:pipe("existing-report",packet+packet,"reject",existing=True))
# Real worker validate-only, disabled plan. No original --execute invocation anywhere.
jobpath=out/"valid-job.json";jobpath.write_text(json.dumps(job))
def worker_positive():
 cp=subprocess.run([sys.executable,str(src/"aa_worker.py"),"--plan",str(planpath),"--job",str(jobpath),"--validate-only"],env=env,capture_output=True,timeout=4)
 (out/"worker-valid.stdout").write_bytes(cp.stdout);(out/"worker-valid.stderr").write_bytes(cp.stderr)
 require(cp.returncode==0 and json.loads(cp.stdout)["GPU_imports"] is False)
case("WORKER-real-validate-only",worker_positive)
# Pure CPU fixture data generator; NONE of the author's 22 test methods is invoked.
os.chdir(out)
from test_aa_window import AATests
fixture=AATests("runTest");fixture.setUp()
backup=out/"synthetic-fixture";shutil.copytree(fixture.root,backup)
try:
 baseline=analyze(fixture.plan,fixture.root)
 case("SYNTHETIC-complete-not-GPU-qualified",lambda:require(baseline["criteria_satisfied"] and not baseline["engineering_repeatability_qualified"]))
 mutations=[("clock",lambda r:r.__setitem__("clock_scope","OTHER")),("binding-hash",lambda r:r.__setitem__("binding_sha256","0"*64)),("bank-hash",lambda r:r.__setitem__("bank_sha256","0"*64)),("input-hash",lambda r:r.__setitem__("input_values_sha256","0"*64))]
 for name,mut in mutations:
  def test(name=name,mut=mut):
   root=out/("synthetic-"+name);shutil.copytree(backup,root)
   rows=[json.loads(x) for x in (root/"HOLD/blocks.jsonl").read_text().splitlines()];mut(rows[-1])
   (root/"HOLD/blocks.jsonl").write_text("".join(json.dumps(x)+"\n" for x in rows))
   require(not analyze(fixture.plan,root)["integrity_valid"])
  case("METADATA-"+name,test)
 b=copy.deepcopy(fixture.cells["REF"][0]["bindings"]["native"])
 def alias_bad():
  x=copy.deepcopy(b);x["aliases"]["Aprime"]["callable_object"]+=1;rejected(lambda:check_binding(x))
 case("IDENTITY-alias-callable-reject",alias_bad)
 def graph_bad():
  x=copy.deepcopy(b);x["graph_object"]+=1;rejected(lambda:check_binding(x))
 case("IDENTITY-graph-reject",graph_bad)
 def late_bank():
  root=out/"synthetic-late-bank";shutil.copytree(backup,root);parent=json.loads((root/"parent.json").read_text());parent["lifecycle"][1]["start_ns"]=1
  (root/"parent.json").write_text(json.dumps(parent));require(not analyze(fixture.plan,root)["integrity_valid"])
 case("METADATA-late-bank-reject",late_bank)
 def source_bad():
  x=copy.deepcopy(plan);x["sources"]["aa_worker.py"]="0"*64
  path=out/"wrong-source-plan.json";path.write_text(json.dumps(x))
  cp=subprocess.run([sys.executable,str(src/"run_aa_window.py"),"--plan",str(path),"--validate-only"],env=env,capture_output=True,timeout=4)
  require(cp.returncode!=0)
 case("IDENTITY-frozen-source-reject",source_bad)
finally:fixture.tearDown()
# Timeout/failure collection uses ONLY QA-owned CPU child processes, not production GPU supervision.
for mode in ("timeout","failure"):
 def cpu_child(mode=mode):
  cmd=[sys.executable,"-c","import time;time.sleep(30)" if mode=="timeout" else "raise SystemExit(7)"]
  start=time.perf_counter_ns();child=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  if mode=="timeout":
   try:child.wait(timeout=.15)
   except subprocess.TimeoutExpired:own_kill(child)
   else:raise AssertionError("stub unexpectedly exited")
  stdout,stderr=child.communicate(timeout=4);require(child.poll() is not None)
  if mode=="failure":require(child.returncode==7)
  empty=out/("stub-"+mode);empty.mkdir();report=analyze(plan,empty)
  require(report["planned_rows"]==128 and report["status_counts"]=={"missing":128} and len(report["alias_pairs"])==32)
  require(all(x["Aprime_minus_A_ns"] is None and x["Aprime_over_A"] is None for x in report["alias_pairs"]))
  (empty/"report.json").write_text(json.dumps(report,indent=2))
  commands.append(dict(case="CPU-stub-"+mode,pid=child.pid,exit_code=child.returncode,elapsed_ns=time.perf_counter_ns()-start,own_child_collected=True,pure_CPU_stub=True))
 case("LIFECYCLE-stub-"+mode,cpu_child)
# Measured control delay remains in QA wall clock; production parent starts its local clock after read_lease.
(out/"checks.json").write_text(json.dumps(dict(candidate="4bed4b4be2ca294b9305cfb28fe1ab03f6164ec0",checks=checks,unique_cases=len(checks),passed=sum(x["status"]=="passed" for x in checks),failed=sum(x["status"]=="failed" for x in checks),GPU_executed=False,original_test_methods_run=0),indent=2))
(out/"commands.json").write_text(json.dumps(commands,indent=2))
print(json.dumps(dict(unique_cases=len(checks),passed=sum(x["status"]=="passed" for x in checks),failures=[x for x in checks if x["status"]!="passed"]),indent=2))
raise SystemExit(int(any(x["status"]=="failed" for x in checks)))
