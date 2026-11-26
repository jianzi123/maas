"""Independent targeted extension of MAAS-7's original 39-case CPU matrix.

No --execute, author test invocation, GPU import/query, or shared research lock.
"""
import argparse,copy,hashlib,json,os,platform,subprocess,sys,time,traceback
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--protected-pid',type=int,required=True);p.add_argument('--only',help='comma-separated IDs; no unselected cases execute');a=p.parse_args()
src=a.source.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
checks=[];commands=[];children=[]
def need(ok,message='independent oracle mismatch'):
 if not ok:raise AssertionError(message)
def reject(fn,text):
 try:fn()
 except ValueError as e:need(text in str(e),str(e));return str(e)
 raise AssertionError('invalid control accepted: '+text)
def check(name,fn):
 if a.only and name not in a.only.split(','):return
 try:details=fn();checks.append({'id':name,'status':'PASS','details':details})
 except Exception as e:checks.append({'id':name,'status':'FAIL','error':repr(e),'trace':traceback.format_exc()})
 print(json.dumps(checks[-1]),flush=True)
guard=out/'guard';guard.mkdir()
guardtext="""import sys,importlib.abc
class CPUOnly(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'torch','sglang','pynvml','aa_runtime'}:raise RuntimeError('QA_FORBIDDEN_GPU_IMPORT')
sys.meta_path.insert(0,CPUOnly())
def audit(event,args):
 if event=='open' and str(args[0]).endswith('gpu0-research.lock'):raise RuntimeError('QA_FORBIDDEN_SHARED_LOCK')
 if event=='subprocess.Popen' and 'nvidia-smi' in str(args):raise RuntimeError('QA_FORBIDDEN_GPU_QUERY')
sys.addaudithook(audit)
"""
(guard/'sitecustomize.py').write_text(guardtext,encoding='utf-8')
exec(compile(guardtext,'qa_cpu_guard','exec'))
sys.path.insert(0,str(src))
from aa_protocol import make_plan,validate,encode_lease,CONFIG
from aa_worker import validate_job
from aa_control import control_scope,control_binding,make_job,validate_job_time,supervise_owned
from cadence_protocol import digest
plan=make_plan('MAAS7_CPU01_RETEST','82284e8fae1c8c11f437e2506aa125694b1f7f99',False);validate(plan)
need(plan['execution_enabled'] is False)
(out/'disabled-plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
lease={'window_id':'MAAS7_CPU_ONLY','total_seconds':600,'stop_new_seconds':540,'driver_elapsed_at_send_ns':10_000_000_000,'soft_remaining_ns':529_000_000_000,'hard_remaining_ns':589_000_000_000,'protected_daemon_pid':a.protected_pid}
job={'schema':'P25-AA-job1','plan_sha256':digest(plan),'process':'REF','window_id':lease['window_id'],'budget':lease,'budget_lease_sha256':digest(lease),'parent_pid':os.getpid(),'research_lock_fd':7,'launch_parent_elapsed_ns':0,'soft_parent_deadline_ns':529_000_000_000,'hard_parent_deadline_ns':589_000_000_000,'bank_sha256':None,'bank_path':None}
env=dict(os.environ,PYTHONPATH=str(guard)+os.pathsep+str(src),PYTHONDONTWRITEBYTECODE='1')
lock=(out/'private-cpu.lock').open('w+b');lock.write(b'Q');lock.flush();lock.seek(0)
if os.name=='nt':
 import msvcrt
 msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
else:
 import fcntl
 fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
def run(name,argv,extra=None):
 cmd=[str(x) for x in argv];need('--execute' not in cmd)
 cp=subprocess.run(cmd,capture_output=True,env=dict(env,**(extra or {})),timeout=5)
 (out/(name+'.stdout')).write_bytes(cp.stdout);(out/(name+'.stderr')).write_bytes(cp.stderr)
 need(b'QA_FORBIDDEN' not in cp.stderr,'forbidden operation attempted')
 commands.append({'case':name,'argv':cmd,'exit':cp.returncode,'stdout_file':name+'.stdout','stderr_file':name+'.stderr'})
 return cp
def worker(name,j,ok,message=None,existing=False,binding=None):
 folder=out/name;folder.mkdir();jp=folder/'job.json';jp.write_text(json.dumps(j,indent=2),encoding='utf-8');report=folder/'report.json'
 if existing:report.write_bytes(b'QA_SUCCESS_SENTINEL_DO_NOT_REPLACE')
 before=report.read_bytes() if report.exists() else None
 extra={}
 if j.get('schema')=='P25-AA-job2':extra['AA_PARENT_CONTROL_BINDING']=binding or j['control_binding_sha256']
 r=run(name,[sys.executable,src/'aa_worker.py','--plan',out/'disabled-plan.json','--job',jp,'--validate-only','--output',report],extra)
 need((r.returncode==0)==ok,'worker unexpected exit '+str(r.returncode))
 if message:need(message.encode() in r.stderr,r.stderr.decode(errors='replace'))
 need((report.read_bytes() if report.exists() else None)==before,'worker report generated/overwritten')
 return json.loads(r.stdout) if ok else {'exit':r.returncode,'reason':message,'report_unchanged':True}
def timed(origin=None,phase='REF'):
 c=control_scope(lease['window_id'],os.getpid(),origin or time.monotonic_ns())
 return make_job(plan,phase,lease,c,lock.fileno(),'b'*64 if phase=='HOLD' else None,'bank' if phase=='HOLD' else None)
def soft_original():
 validate_job(plan,job);bad=copy.deepcopy(job);bad['soft_parent_deadline_ns']=550_000_000_000
 message=reject(lambda:validate_job(plan,bad),'soft budget reset')
 positive=worker('legal529',job,True);need(positive['metadata_only'] and positive['GPU_imports'] is False)
 worker('bad550-fresh',bad,False,'soft budget reset');worker('bad550-existing',bad,False,'soft budget reset',True)
 return {'positive_soft':529,'bad_soft':550,'hard':589,'driver_elapsed':10,'function_reason':message,'CLI_negative_samples':2}
check('AA-CPU-01-original-function-and-CLI',soft_original)
def caps():
 for key,cap in [('soft_parent_deadline_ns',lease['soft_remaining_ns']),('hard_parent_deadline_ns',lease['hard_remaining_ns'])]:
  x=copy.deepcopy(job);x[key]=cap+1;reject(lambda:validate_job(plan,x),'budget reset')
 x=copy.deepcopy(job);x.update(soft_parent_deadline_ns=528_000_000_000,hard_parent_deadline_ns=588_000_000_000);validate_job(plan,x)
 return 'each cap+1ns rejected; original equals and smaller caps accepted'
check('BUDGET-corresponding-caps-and-short-control',caps)
def integer_caps():
 for k in ('soft_parent_deadline_ns','hard_parent_deadline_ns','launch_parent_elapsed_ns'):
  x=copy.deepcopy(job);x[k]=True;reject(lambda:validate_job(plan,x),'integer ns')
 return 'bool not integer ns'
check('BUDGET-integer-only',integer_caps)
check('JOB1-metadata-not-live-authority',lambda:reject(lambda:validate_job_time(job),'timed job2'))
def hold_shared():
 c=control_scope(lease['window_id'],os.getpid(),time.monotonic_ns());ref=make_job(plan,'REF',lease,c,lock.fileno());hold=make_job(plan,'HOLD',copy.deepcopy(lease),copy.deepcopy(c),lock.fileno(),'b'*64,'bank',expected_binding=ref['control_binding_sha256'])
 for k in ('budget','budget_control','budget_lease_sha256','control_binding_sha256','soft_parent_deadline_ns','hard_parent_deadline_ns'):need(ref[k]==hold[k],k)
 need(hold['launch_parent_elapsed_ns']>=ref['launch_parent_elapsed_ns'])
 (out/'shared-ref-hold.json').write_text(json.dumps({'ref':ref,'hold':hold},indent=2),encoding='utf-8')
 return 'one original lease/control/binding; original600/540 minus driver10 kept'
check('BUDGET-HOLD-original-control-and-caps',hold_shared)
def hold_reset():
 ref=timed();x=copy.deepcopy(ref);x['process']='HOLD';x['bank_sha256']='b'*64;x['budget_control']['origin_ns']=time.monotonic_ns();x['control_binding_sha256']=control_binding(x['budget'],x['budget_control']);x['launch_parent_elapsed_ns']=0
 reject(lambda:validate_job_time(x,expected_binding=ref['control_binding_sha256']),'original parent')
 return worker('hold-renewed-origin',x,False,'original parent',True,ref['control_binding_sha256'])
check('BUDGET-HOLD-origin-reset-rejected',hold_reset)
def hold_missing():
 x=copy.deepcopy(job);x['process']='HOLD';return reject(lambda:validate_job(plan,x),'bank stage')
check('JOB-HOLD-missing-bank-reject',hold_missing)
def live_job():
 x=timed();validate_job(plan,x);r=worker('job2-fresh',x,True);need(r['metadata_only'] is False and r['control_elapsed_ns']>=x['launch_parent_elapsed_ns']);return r
check('JOB2-live-local-positive',live_job)
def wrong_parent():return worker('job2-wrong-parent',timed(),False,'original parent',True,'0'*64)
check('JOB2-original-parent-binding',wrong_parent)
def wrong_domain():
 x=timed();x['budget_control']['domain']='0'*64;x['control_binding_sha256']=control_binding(x['budget'],x['budget_control']);return worker('job2-wrong-domain',x,False,'foreign control',True)
check('JOB2-local-domain-not-performance-clock',wrong_domain)
def expired():
 x=timed();x['budget_control']['origin_ns']-=530_000_000_000;x['control_binding_sha256']=control_binding(x['budget'],x['budget_control']);return worker('job2-expired',x,False,'late job',True)
check('JOB2-expired-rejected-before-work',expired)
def future_origin():
 x=timed();x['budget_control']['origin_ns']+=1_000_000_000;x['control_binding_sha256']=control_binding(x['budget'],x['budget_control']);return worker('job2-future',x,False,'future control')
check('JOB2-future-origin-rejected',future_origin)
def owner_window():
 for key,value in [('owner_pid',os.getpid()+1),('window_id','FOREIGN')]:
  x=timed();x['budget_control'][key]=value;x['control_binding_sha256']=control_binding(x['budget'],x['budget_control']);reject(lambda:validate_job(plan,x),'owner/window')
 return 'owner and window contradictions rejected'
check('JOB2-owner-and-window',owner_window)
def pipe(name,data,ok,delay=0,no_eof=False,limit=900,existing=False):
 folder=out/name;folder.mkdir();ready=folder/'ready.json';report=folder/'report.json'
 if existing:report.write_bytes(b'QA_SUCCESS_SENTINEL_DO_NOT_REPLACE')
 before=report.read_bytes() if report.exists() else None
 argv=[str(x) for x in [sys.executable,'-u',src/'run_aa_window.py','--plan',out/'disabled-plan.json','--validate-lease-only','--control-timeout-ms',limit,'--control-ready-file',ready,'--output',folder]]
 start=time.monotonic_ns();child=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env);children.append(child)
 try:
  until=time.monotonic()+3
  while not ready.exists() and child.poll() is None and time.monotonic()<until:time.sleep(.005)
  need(ready.exists(),'CPU ready not reached')
  if delay:time.sleep(delay)
  try:child.stdin.write(data);child.stdin.flush()
  except BrokenPipeError:pass
  if no_eof:
   child.wait(timeout=3);child.stdin.close();child.stdin=None;stdout,stderr=child.communicate(timeout=2)
  else:
   try:child.stdin.close()
   except BrokenPipeError:pass
   child.stdin=None;stdout,stderr=child.communicate(timeout=3)
 finally:
  if child.poll() is None:
   need(child.pid not in (a.protected_pid,os.getpid()),'protected PID collision');child.kill();child.wait(timeout=3)
 elapsed=time.monotonic_ns()-start
 (folder/'stdin.bin').write_bytes(data);(folder/'stdout.log').write_bytes(stdout);(folder/'stderr.log').write_bytes(stderr)
 commands.append({'case':name,'argv':argv,'pid':child.pid,'exit':child.returncode,'elapsed_ns':elapsed,'own_child_collected':child.poll() is not None,'stdin_sha256':hashlib.sha256(data).hexdigest(),'delay_seconds':delay,'EOF_sent':not no_eof})
 need(b'QA_FORBIDDEN' not in stderr,'forbidden operation attempted');need((child.returncode==0)==ok,'unexpected pipe exit')
 need((report.read_bytes() if report.exists() else None)==before,'pipe report generated/overwritten')
 if ok:
  r=json.loads(stdout);need(r['lease_validated'] and not r['GPU_imports']);need(r['driver_elapsed_at_send_ns']==10_000_000_000)
  need(r['soft_remaining_at_receive_ns']==529_000_000_000-r['control_receive_elapsed_ns']);need(r['hard_remaining_at_receive_ns']==589_000_000_000-r['control_receive_elapsed_ns']);return r
 return {'exit':child.returncode,'elapsed_ns':elapsed,'reason':stderr.decode(errors='replace')[-350:],'report_unchanged':True}
packet=encode_lease(lease)
check('PIPE-LF-EOF',lambda:pipe('pipe-good',packet,True))
check('PIPE-old-5c6e',lambda:pipe('pipe-old-5c6e',packet[:-1]+b'\\n',False))
check('PIPE-empty',lambda:pipe('pipe-empty',b'',False))
check('PIPE-truncated',lambda:pipe('pipe-truncated',packet[:30]+b'\n',False))
def extra_frames():
 return [pipe('pipe-extra-'+str(n),data,False) for n,data in enumerate([packet+packet,packet+b'\n',packet+b'trailing'])]
check('PIPE-extra-frame-LF-and-data',extra_frames)
def delay_kept():
 r=pipe('pipe-delayed-EOF',packet,True,delay=.15,limit=1200);need(r['control_receive_elapsed_ns']>=150_000_000,'receive wait erased');return r
check('PIPE-ready-wait-charged-and-driver-kept',delay_kept)
def no_eof():
 r=pipe('pipe-noEOF',packet,False,no_eof=True,limit=220);need('TimeoutError' in r['reason'],'not self-bounded channel timeout');return r
check('PIPE-no-EOF-self-bounded',no_eof)
def first_tightens():
 s=copy.deepcopy(lease);s.update(soft_remaining_ns=160_000_000,hard_remaining_ns=1_000_000_000)
 r=pipe('pipe-first-tightens',encode_lease(s),False,no_eof=True,limit=1000);need(r['elapsed_ns']<850_000_000,'first line did not tighten ceiling');need('TimeoutError' in r['reason']);return r
check('PIPE-first-line-tightens-only',first_tightens)
def late_input():
 s=copy.deepcopy(lease);s.update(soft_remaining_ns=160_000_000,hard_remaining_ns=1_000_000_000)
 r=pipe('pipe-late-input',encode_lease(s),False,delay=.25,limit=1100);need('late control' in r['reason'] or 'TimeoutError' in r['reason']);return r
check('PIPE-late-valid-frame-rejected',late_input)
def no_extend():
 r=pipe('pipe-cannot-extend',packet,False,no_eof=True,limit=220);need(r['elapsed_ns']<850_000_000,'valid large cap expanded receive limit');return r
check('PIPE-first-line-cannot-expand',no_extend)
check('PIPE-failure-preserves-success-report',lambda:pipe('pipe-old-report',packet+packet,False,existing=True))
def wrong_source():
 wrong=copy.deepcopy(plan);wrong['sources']['aa_worker.py']='0'*64;path=out/'wrong-source-plan.json';path.write_text(json.dumps(wrong),encoding='utf-8')
 r=run('source-pin',[sys.executable,src/'run_aa_window.py','--plan',path,'--validate-only']);need(r.returncode!=0 and b'frozen sources' in r.stderr);return 'rejected by source pin, distinct from bad550 soft rejection'
check('SOURCE-current-disabled-plan-and-negative-pin',wrong_source)
def analyzer_no_overwrite():
 target=out/'existing-analysis.json';target.write_bytes(b'QA_SUCCESS_SENTINEL_DO_NOT_REPLACE');empty=out/'empty-analysis';empty.mkdir()
 r=run('analyzer-no-overwrite',[sys.executable,src/'analyze_aa_window.py','--plan',out/'disabled-plan.json','--root',empty,'--output',target]);need(r.returncode!=0 and b'FileExistsError' in r.stderr);need(target.read_bytes()==b'QA_SUCCESS_SENTINEL_DO_NOT_REPLACE');return 'old followup report guard preserved'
check('REPORT-analyzer-exclusive-no-overwrite',analyzer_no_overwrite)
def owned_collection(failing):
 code="print('CPU_READY',flush=True);raise SystemExit(7)" if failing else "import time;print('CPU_READY',flush=True);time.sleep(30)"
 c=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env);children.append(c)
 need(c.stdout.readline()==b'CPU_READY\n','CPU fixture readiness');origin=time.monotonic_ns()
 result=supervise_owned(c,lambda:time.monotonic_ns()-origin,60_000_000,250_000_000,a.protected_pid,lambda child:None,cleanup_grace_ns=40_000_000,record_reserve_ns=0)
 stdout,stderr=c.communicate(timeout=2);need(c.poll() is not None and not stdout and not stderr)
 need(result['exit_code']==7 if failing else result['forced_kill'] is True,'wrong child collection')
 commands.append({'case':'owned-failure' if failing else 'owned-timeout','pid':c.pid,'argv':c.args,**result,'own_child_collected':True,'private_lock':'private-cpu.lock'})
 return result
check('OWNED-CPU-failure-collected',lambda:owned_collection(True))
check('OWNED-CPU-timeout-collected',lambda:owned_collection(False))
lock.close()
need(all(c.poll() is not None for c in children),'uncollected own child')
summary={'product_ref':'82284e8fae1c8c11f437e2506aa125694b1f7f99','product_code':'0cea087d21cac94d41f2f93443a48c3a7eaef00f','source_sha256':plan['sources'],'plan_sha256':digest(plan),'execution_enabled':False,'platform':platform.platform(),'python':sys.version,'checks':checks,'unique':len(checks),'passed':sum(c['status']=='PASS' for c in checks),'failed':sum(c['status']=='FAIL' for c in checks),'commands':commands,'own_cpu_children_collected':len(children),'GPU_executions':0,'shared_research_lock_touches':0,'author_tests_invoked':0}
(out/'results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:summary[k] for k in ('unique','passed','failed','own_cpu_children_collected')}));raise SystemExit(1 if summary['failed'] else 0)
