"""AA-CPU-01 CPU regressions. All plans disabled, all children CPU-only."""
import copy,hashlib,io,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from aa_protocol import make_plan,encode_lease
from aa_worker import validate_job
from aa_control import control_scope,control_binding,make_job,validate_job_time,supervise_owned
from cadence_protocol import digest,write_json

class CPU01Tests(unittest.TestCase):
 def setUp(self):
  base=Path.cwd()/".cache/c01";base.mkdir(parents=True,exist_ok=True)
  self.tmp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.tmp.name).resolve()
  self.assertTrue(self.root.is_relative_to(base.resolve()))
  self.src=Path(__file__).resolve().parent
  self.plan=make_plan("AA_CPU01_DISABLED","4bed4b4be2ca294b9305cfb28fe1ab03f6164ec0",False)
  self.planpath=self.root/"plan.json";write_json(self.planpath,self.plan)
  self.lease={"window_id":"AA_CPU01","total_seconds":600,"stop_new_seconds":540,
   "driver_elapsed_at_send_ns":10000000000,"soft_remaining_ns":529000000000,
   "hard_remaining_ns":589000000000,"protected_daemon_pid":int(os.environ.get("AA_CPU_TEST_PROTECTED_PID",os.getpid()))}
  self.job={"schema":"P25-AA-job1","plan_sha256":digest(self.plan),"process":"REF",
    "window_id":"AA_CPU01","budget":self.lease,"budget_lease_sha256":digest(self.lease),
    "parent_pid":os.getpid(),"research_lock_fd":7,"launch_parent_elapsed_ns":0,
    "soft_parent_deadline_ns":529000000000,"hard_parent_deadline_ns":589000000000,
    "bank_sha256":None,"bank_path":None}
  guard=self.root/"guard";guard.mkdir()
  (guard/"sitecustomize.py").write_text("""import sys,importlib.abc
class CPUOnly(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'torch','sglang','pynvml','aa_runtime'}:raise RuntimeError('FORBIDDEN_GPU_IMPORT')
sys.meta_path.insert(0,CPUOnly())
def protect(event,args):
 if event=='open' and str(args[0]).endswith('gpu0-research.lock'):raise RuntimeError('FORBIDDEN_SHARED_LOCK')
 if event=='subprocess.Popen' and 'nvidia-smi' in str(args):raise RuntimeError('FORBIDDEN_GPU_QUERY')
sys.addaudithook(protect)
""")
  self.env=dict(os.environ,PYTHONPATH=str(guard)+os.pathsep+str(self.src),PYTHONDONTWRITEBYTECODE="1")
 def tearDown(self):self.tmp.cleanup()
 def test_original_529_positive_and_550_reject(self):
  validate_job(self.plan,self.job)
  bad=copy.deepcopy(self.job);bad["soft_parent_deadline_ns"]=550000000000
  with self.assertRaisesRegex(ValueError,"soft budget reset"):validate_job(self.plan,bad)
 def test_hard_increase_rejected(self):
  self.job["hard_parent_deadline_ns"]=600000000000
  with self.assertRaisesRegex(ValueError,"budget reset"):validate_job(self.plan,self.job)
 def test_smaller_deadlines_remain_legal(self):
  self.job.update(soft_parent_deadline_ns=528000000000,hard_parent_deadline_ns=588000000000)
  validate_job(self.plan,self.job)
 def test_hold_reuses_original_lease_by_value(self):
  c=control_scope("AA_CPU01",os.getpid(),time.monotonic_ns())
  ref=make_job(self.plan,"REF",self.lease,c,7)
  hold=make_job(self.plan,"HOLD",copy.deepcopy(self.lease),copy.deepcopy(c),7,"b"*64,"bank.json")
  for key in ("budget","budget_control","soft_parent_deadline_ns","hard_parent_deadline_ns","budget_lease_sha256"):
   self.assertEqual(ref[key],hold[key])
  self.assertGreaterEqual(hold["launch_parent_elapsed_ns"],ref["launch_parent_elapsed_ns"])
  self.assertEqual(hold["budget"]["driver_elapsed_at_send_ns"],10000000000)
 def test_hold_after_original_soft_cannot_reset(self):
  origin=time.monotonic_ns();c=control_scope("AA_CPU01",os.getpid(),origin)
  with self.assertRaisesRegex(ValueError,"late job"):
   make_job(self.plan,"HOLD",self.lease,c,7,"b"*64,"bank",origin+530000000000)
 def test_hold_control_origin_cannot_be_renewed(self):
  origin=time.monotonic_ns();c=control_scope("AA_CPU01",os.getpid(),origin)
  ref=make_job(self.plan,"REF",self.lease,c,7)
  reset=control_scope("AA_CPU01",os.getpid(),origin+1000)
  with self.assertRaisesRegex(ValueError,"original parent"):
   make_job(self.plan,"HOLD",self.lease,reset,7,"b"*64,"bank",origin+2000,ref["control_binding_sha256"])
 def test_legacy_job_is_not_execution_authority(self):
  with self.assertRaisesRegex(ValueError,"timed job2"):validate_job_time(self.job)
 def test_delayed_worker_rejected(self):
  origin=time.monotonic_ns();c=control_scope("AA_CPU01",os.getpid(),origin)
  job=make_job(self.plan,"REF",self.lease,c,7,now_ns=origin+1000)
  with self.assertRaisesRegex(ValueError,"late job"):validate_job_time(job,origin+529000000000,job["control_binding_sha256"])
 def test_foreign_control_domain_rejected(self):
  c=control_scope("AA_CPU01",os.getpid(),time.monotonic_ns())
  job=make_job(self.plan,"REF",self.lease,c,7);job["budget_control"]["domain"]="0"*64
  job["control_binding_sha256"]=control_binding(job["budget"],job["budget_control"])
  with self.assertRaisesRegex(ValueError,"foreign control"):validate_job_time(job,expected_binding=job["control_binding_sha256"])
 def test_future_origin_rejected(self):
  origin=time.monotonic_ns();c=control_scope("AA_CPU01",os.getpid(),origin)
  job=make_job(self.plan,"REF",self.lease,c,7,now_ns=origin+1000)
  with self.assertRaisesRegex(ValueError,"future control"):validate_job_time(job,origin-1,job["control_binding_sha256"])
 def worker_cli(self,job,existing):
  path=self.root/"job.json";write_json(path,job)
  report=self.root/"report.json"
  if existing:report.write_bytes(b"EXISTING_SUCCESS")
  before=report.read_bytes() if report.exists() else None
  cmd=[sys.executable,str(self.src/"aa_worker.py"),"--plan",str(self.planpath),"--job",str(path),"--validate-only","--output",str(report)]
  env=dict(self.env)
  if job.get("schema")=="P25-AA-job2":env["AA_PARENT_CONTROL_BINDING"]=getattr(self,"expected_parent_binding",job["control_binding_sha256"])
  r=subprocess.run(cmd,env=env,capture_output=True,timeout=4)
  self.assertNotIn(b"FORBIDDEN",r.stderr)
  self.assertEqual(report.read_bytes() if report.exists() else None,before)
  return r
 def test_real_bad_job_CLI_rejects_no_report(self):
  self.job["soft_parent_deadline_ns"]=550000000000
  r=self.worker_cli(self.job,False);self.assertNotEqual(r.returncode,0);self.assertIn(b"soft budget reset",r.stderr)
 def test_real_bad_job_CLI_preserves_existing_report(self):
  self.job["soft_parent_deadline_ns"]=550000000000
  self.assertNotEqual(self.worker_cli(self.job,True).returncode,0)
 def test_real_positive_CLI(self):
  r=self.worker_cli(self.job,False);self.assertEqual(r.returncode,0,r.stderr)
  self.assertTrue(json.loads(r.stdout)["metadata_only"])
 def test_job2_CLI_fresh_and_expired(self):
  c=control_scope("AA_CPU01",os.getpid(),time.monotonic_ns())
  job=make_job(self.plan,"REF",self.lease,c,7)
  self.assertEqual(self.worker_cli(job,False).returncode,0)
  job["budget_control"]["origin_ns"]-=530000000000
  job["control_binding_sha256"]=control_binding(job["budget"],job["budget_control"])
  self.assertNotEqual(self.worker_cli(job,True).returncode,0)
 def lease_cli(self,lease,delay=0,no_eof=False,timeout_ms=900,existing=False):
  target=self.root/"lease-report.json"
  if existing:target.write_bytes(b"EXISTING_SUCCESS")
  before=target.read_bytes() if target.exists() else None
  ready=self.root/"cpu-control-ready.json"
  cmd=[sys.executable,str(self.src/"run_aa_window.py"),"--plan",str(self.planpath),
       "--validate-lease-only","--control-timeout-ms",str(timeout_ms),"--control-ready-file",str(ready),"--output",str(target)]
  child=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=self.env)
  try:
   until=time.monotonic()+3
   while not ready.exists() and child.poll() is None and time.monotonic()<until:time.sleep(.005)
   self.assertTrue(ready.exists(),"CPU control readiness failed")
   if delay:time.sleep(delay)
   child.stdin.write(encode_lease(lease));child.stdin.flush()
   if no_eof:
    child.wait(timeout=3)
   child.stdin.close();child.stdin=None
   stdout,stderr=child.communicate(timeout=3)
  finally:
   if child.poll() is None:
    self.assertNotEqual(child.pid,self.lease["protected_daemon_pid"])
    child.kill()
   child.wait()
  self.assertNotIn(b"FORBIDDEN",stderr)
  self.assertEqual(target.read_bytes() if target.exists() else None,before)
  return child.returncode,stdout,stderr
 def test_real_HOLD_origin_reset_rejects_parent_binding(self):
  c=control_scope("AA_CPU01",os.getpid(),time.monotonic_ns())
  job=make_job(self.plan,"HOLD",self.lease,c,7,"b"*64,"bank")
  self.expected_parent_binding=job["control_binding_sha256"]
  job["budget_control"]["origin_ns"]+=1
  job["control_binding_sha256"]=control_binding(job["budget"],job["budget_control"])
  r=self.worker_cli(job,False)
  self.assertNotEqual(r.returncode,0);self.assertIn(b"original parent",r.stderr)
 def test_receive_delay_is_charged(self):
  rc,out,err=self.lease_cli(self.lease,delay=.18);self.assertEqual(rc,0,err)
  v=json.loads(out);self.assertGreater(v["control_receive_elapsed_ns"],50_000_000)
  self.assertEqual(v["soft_remaining_at_receive_ns"]+v["control_receive_elapsed_ns"],529000000000)
  self.assertEqual(v["driver_elapsed_at_send_ns"],10000000000)
 def test_expired_control_rejected(self):
  lease=dict(self.lease,driver_elapsed_at_send_ns=539800000000,
             soft_remaining_ns=100000000,hard_remaining_ns=60100000000)
  rc,out,err=self.lease_cli(lease,delay=.4,existing=True)
  self.assertNotEqual(rc,0);self.assertTrue(b"deadline" in err or b"late control" in err)
 def test_no_EOF_is_bounded_without_new_report(self):
  rc,out,err=self.lease_cli(self.lease,no_eof=True,timeout_ms=150)
  self.assertNotEqual(rc,0);self.assertIn(b"control channel deadline",err)
 def test_provisional_lease_shortens_EOF_deadline(self):
  lease=dict(self.lease,driver_elapsed_at_send_ns=539600000000,
             soft_remaining_ns=300000000,hard_remaining_ns=60300000000)
  start=time.monotonic();rc,out,err=self.lease_cli(lease,no_eof=True,timeout_ms=1800)
  self.assertNotEqual(rc,0);self.assertLess(time.monotonic()-start,1.4)
 def test_CPU_supervisor_collects_failure(self):
  protected=os.environ.get("AA_CPU_TEST_PROTECTED_PID")
  if protected is None:self.skipTest("set actual daemon PID to exercise owned process collection")
  c=subprocess.Popen([sys.executable,"-c","raise SystemExit(7)"])
  root=time.monotonic_ns()
  r=supervise_owned(c,lambda:time.monotonic_ns()-root,500000000,1200000000,int(protected),lambda p:None,
                    cleanup_grace_ns=100000000,record_reserve_ns=100000000)
  self.assertEqual(r["exit_code"],7);self.assertIsNotNone(c.poll())
 def test_CPU_supervisor_uses_one_origin_and_private_lock(self):
  protected=os.environ.get("AA_CPU_TEST_PROTECTED_PID")
  if protected is None:self.skipTest("set actual daemon PID to exercise owned process collection")
  with (self.root/"private-cpu.lock").open("w+b") as f:
   f.write(bytes((0,)));f.flush();f.seek(0)
   if os.name=="nt":
    import msvcrt
    msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
   else:
    import fcntl
    fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
   try:
    root=time.monotonic_ns();elapsed=lambda:time.monotonic_ns()-root
    first=subprocess.Popen([sys.executable,"-c","import time;time.sleep(.10)"])
    self.assertEqual(supervise_owned(first,elapsed,600000000,1400000000,int(protected),lambda c:None,
                     cleanup_grace_ns=50000000,record_reserve_ns=100000000)["exit_code"],0)
    second=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])
    r=supervise_owned(second,elapsed,600000000,1400000000,int(protected),lambda c:None,
                     cleanup_grace_ns=50000000,record_reserve_ns=100000000)
    self.assertTrue(r["forced_kill"]);self.assertIsNotNone(second.poll())
    self.assertLess(elapsed(),1400000000)
   finally:
    f.seek(0)
    if os.name=="nt":msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
    else:fcntl.flock(f,fcntl.LOCK_UN)
if __name__=="__main__":unittest.main()
