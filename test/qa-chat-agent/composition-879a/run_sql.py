"""Own disposable MySQL + same-source Linux binaries. All resources cleaned in finally."""
import hashlib,json,os,secrets,socket,subprocess,time,urllib.request,urllib.error,uuid,io,http.client
from datetime import datetime
import http.client as wire_http
from pathlib import Path
src=Path(__file__).resolve().parents[3];root=src.parent;out=Path(os.environ['MAAS_QA_OUT']).resolve()
for name in ('agent.test','kernel.test','installation.test','maas-service'):assert (out/name).exists(),name
run='maas7-879a-'+uuid.uuid4().hex[:8];mysql=run+'-mysql';app=run+'-app';data=run+'-data';sock=run+'-socket';network=run+'-http';socket_path='/tmp/maas11-mysql.qa879a/mysql.sock'
resources=[];records=[];cases=[];sql_failures=[];private=out/'private';private.mkdir(exist_ok=False);password=secrets.token_hex(20);dbpass=secrets.token_hex(20);cookie='';csrf='';port=0
label='maas.qa.run='+run
mysqlid=json.loads((out/'environment.json').read_bytes())['mysql_image'];alpine=json.loads((out/'environment.json').read_bytes())['runner_image']
def command(args,name,check=True,stdin=None,timeout=45):
 start=time.time();p=subprocess.run(['docker',*args],input=stdin,capture_output=True,timeout=timeout)
 safe=[v.replace(dbpass,'[REDACTED]').replace(password,'[REDACTED]') for v in args]
 rec={'name':name,'command':['docker',*safe],'exit':p.returncode,'seconds':round(time.time()-start,3),'stdout':p.stdout.decode('utf-8','replace'),'stderr':p.stderr.decode('utf-8','replace')};records.append(rec)
 (out/'docker-commands.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
 if check and p.returncode:raise RuntimeError(name+': '+rec['stderr'][-1200:])
 return p
mounts=['--mount','type=volume,source='+sock+',target=/tmp/maas11-mysql.qa879a','--mount','type=bind,source='+str(out)+',target=/qa','--mount','type=bind,source='+str(src)+',target=/src,readonly']
def runbin(binary,args,name,expected=0,timeout=180):
 p=command(['run','--rm','--network=none','--memory=512m','--cpus=2',*mounts,'--workdir=/src/'+({'agent.test':'internal/agentruntime','kernel.test':'internal/kernel','installation.test':'cmd/workbench'}.get(binary,'')),'-e','MAAS_DISPOSABLE_MYSQL=1','-e','MAAS_MYSQL_TEST_SOCKET='+socket_path,'-e','MAAS_QA_SEED_DB=qa_product_879a','-e','MAAS_QA_ARTIFACT_DIR=/qa','-e','GOMAXPROCS=2',alpine,'/qa/'+binary,*args],name,check=False,timeout=timeout)
 (out/(name+'.log')).write_bytes(p.stdout+p.stderr)
 assert p.returncode==expected,(name,p.returncode,p.stdout[-1000:],p.stderr[-1000:])
 if binary.endswith('.test'):assert b'--- PASS: ' in p.stdout and b'no tests to run' not in p.stdout and b'--- SKIP:' not in p.stdout,name
 return p

def sql(query,name,user='root'):
 args=['exec','-i'];
 if user!='root':args+=['-e','MYSQL_PWD='+dbpass]
 args +=[mysql,'mysql','--protocol=socket','--socket='+socket_path,'--batch','--skip-column-names','-u'+user]
 return command(args,name,check=False,stdin=query.encode('utf-8'))
def ready_mysql():
 until=time.time()+75
 while time.time()<until:
  process=command(['exec',mysql,'cat','/proc/1/comm'],'mysql-final-process',False,timeout=10)
  if process.returncode!=0 or process.stdout.strip()!=b'mysqld':
   time.sleep(.2);continue
  p=command(['exec',mysql,'mysqladmin','--protocol=socket','--socket='+socket_path,'-uroot','ping','--silent'],'mysql-ready',False,timeout=10)
  if p.returncode==0:return
  time.sleep(.2)
 raise RuntimeError('own MySQL readiness timeout')
def http(method,path,body=None,auth=True,origin=True,csrf_header=True):
 headers={};
 headers['Host']='127.0.0.1:8080'
 if origin:headers['Origin']='http://127.0.0.1:'+str(port)
 if auth and cookie:headers['Cookie']=cookie
 if csrf_header and csrf:headers['X-CSRF-Token']=csrf
 raw=None if body is None else json.dumps(body).encode()
 if raw is not None:headers['Content-Type']='application/json'
 payload=raw or b''
 headers['Connection']='close';headers['Content-Length']=str(len(payload))
 request=(method+' '+path+' HTTP/1.1\r\n'+''.join(k+': '+v+'\r\n' for k,v in headers.items())+'\r\n').encode()+payload
 packet=subprocess.run(['docker','exec','-i',app,'/qa/qa-http-probe'],input=json.dumps({'method':method,'path':path,'headers':headers,'body':(raw or b'').decode('utf-8')}).encode(),capture_output=True,timeout=12)
 wire=json.loads(packet.stdout)
 if 'error' in wire:raise ConnectionError(wire['error'])
 class Response:
  status=wire['status']
  headers={k:v[0] for k,v in wire['headers'].items()}
  def read(self):return wire['body'].encode('utf-8')
 r=Response()
 b=r.read();status=r.status
 try:value=json.loads(b)
 except Exception:value={'raw':b.decode('utf-8','replace')[:300]}
 redacted=json.loads(json.dumps(value))
 if isinstance(redacted,dict) and 'csrf_token' in redacted:redacted['csrf_token_sha256']=hashlib.sha256(redacted.pop('csrf_token').encode()).hexdigest()
 cases.append({'kind':'HTTP','transport':'own-container loopback via net/http','method':method,'path':path,'status':status,'response':redacted})
 return status,value,r.headers

def same_session(current,original):
 return current['admin_id']==original['admin_id'] and current['csrf_token']==original['csrf_token'] and abs((datetime.fromisoformat(current['expires_at'].replace('Z','+00:00'))-datetime.fromisoformat(original['expires_at'].replace('Z','+00:00'))).total_seconds())<=0.000001

def ready_app():
 until=time.time()+25
 while time.time()<until:
  try:
   s,v,_=http('GET','/readyz',auth=False)
   if s==200:return
  except (urllib.error.URLError,TimeoutError,ConnectionError):pass
  time.sleep(.2)
 raise RuntimeError('own service readiness timeout')
try:
 for vol in (data,sock):command(['volume','create','--label',label,vol],'create-volume');resources.append(('volume',vol))
 command(['run','-d','--name',mysql,'--label',label,'--network=none','--memory=768m','--cpus=1','-e','MYSQL_ALLOW_EMPTY_PASSWORD=yes','--mount','type=volume,source='+data+',target=/var/lib/mysql','--mount','type=volume,source='+sock+',target=/tmp/maas11-mysql.qa879a',mysqlid,'--skip-networking','--mysqlx=OFF','--socket='+socket_path,'--innodb-buffer-pool-size=67108864','--performance-schema=OFF','--max-connections=24'],'start-own-mysql');resources.append(('container',mysql));ready_mysql()
 for binary,pattern,name in [('agent.test','^TestQAARLegacyAttemptConservative$','controlled-legacy-attempt'),('agent.test','^TestMySQLAR1CommandsRestartAndTwoReplicaClaim$','sql-session-store'),('kernel.test','^(TestMySQLAgentChildrenUseOneLedger|TestQAAgentMixedKnownUnknownLedger)$','sql-unique-ledger'),('installation.test','^(TestLocalRuntimeIdentities|TestInstallationComposition)$','sql-identities-installation')]:
  if os.environ.get('MAAS_QA_REUSE_SQL')=='1' and name in ('sql-session-store','controlled-legacy-attempt','sql-unique-ledger','sql-identities-installation'):continue # Passed on attempt1; preserved original evidence.
  try:runbin(binary,['-test.run='+pattern,'-test.v=true','-test.timeout=120s'],name)
  except AssertionError as e:sql_failures.append({'stage':name,'failure':str(e)})
 p=sql("CREATE DATABASE qa_product_879a; CREATE ROLE qa_product_role; CREATE USER 'qa_product_user'@'localhost' IDENTIFIED BY '"+dbpass+"'; GRANT SELECT ON qa_product_879a.* TO qa_product_role; GRANT qa_product_role TO 'qa_product_user'@'localhost'; SET DEFAULT ROLE qa_product_role TO 'qa_product_user'@'localhost';",'create-own-product-role');assert p.returncode==0
 for name,value in [('migration.dsn','root@unix('+socket_path+')/qa_product_879a?parseTime=true'),('runtime.dsn','qa_product_user:'+dbpass+'@unix('+socket_path+')/qa_product_879a?parseTime=true'),('bootstrap',password),('pepper',secrets.token_hex(32)),('cursor',secrets.token_hex(32))]:(private/name).write_text(value,encoding='utf-8')
 port=8080 # Internal loopback probe, no host port published.
 cfg=json.loads((src/'config/product.example.json').read_bytes());cfg.update(listen='0.0.0.0:8080',origin='http://127.0.0.1:'+str(port),cluster_id='qa-composition-879a',static_dir='/src/console',contract_file='/src/docs/contracts/agent-runtime/ar1-draft2/openapi.json');cfg['mysql']={'runtime_dsn_file':'/qa/private/runtime.dsn','migration_dsn_file':'/qa/private/migration.dsn'};cfg['auth']['password_file']='/qa/private/bootstrap';cfg['secrets']={'key_pepper_file':'/qa/private/pepper','cursor_key_file':'/qa/private/cursor'};cfg['agent']['concurrency']=2
 (out/'product.json').write_text(json.dumps(cfg),encoding='utf-8')
 failed=runbin('maas-service',['serve','--config','/qa/product.json'],'serve-before-migrate',expected=1);assert b'product_schema_not_ready' in failed.stderr
 runbin('maas-service',['migrate','--config','/qa/product.json'],'migrate-root')
 runbin('maas-service',['migrate','--config','/qa/product.json'],'migrate-repeat')
 p=sql('GRANT INSERT,UPDATE ON qa_product_879a.product_sessions TO qa_product_role; GRANT INSERT,UPDATE ON qa_product_879a.product_login_attempts TO qa_product_role; GRANT INSERT,UPDATE ON qa_product_879a.agent_sessions_v1 TO qa_product_role;','runtime-table-grants');assert p.returncode==0
 p=sql('SELECT CURRENT_USER(),CURRENT_ROLE(); CREATE TABLE qa_product_879a.must_not_create(id INT);','runtime-no-DDL',user='qa_product_user');assert p.returncode!=0 and b'1142' in p.stderr
 runtime_cfg=json.loads(json.dumps(cfg));runtime_cfg['mysql']['migration_dsn_file']='/qa/private/runtime.dsn';(out/'runtime-migrate.json').write_text(json.dumps(runtime_cfg),encoding='utf-8');runbin('maas-service',['migrate','--config','/qa/runtime-migrate.json'],'runtime-migrate-denied',expected=1)
 runbin('agent.test',['-test.run=^TestQASeedProductInFlight$','-test.v=true','-test.timeout=30s'],'sql-seed-inflight')
 seed=json.loads((out/'app-seed.json').read_bytes())
 command(['network','create','--internal','--label',label,network],'create-own-http-network');resources.append(('network',network))
 command(['run','-d','--name',app,'--label',label,'--network',network,'--memory=256m','--cpus=2',*mounts,'-e','GOMAXPROCS=2',alpine,'/qa/maas-service','serve','--config','/qa/product.json'],'start-own-formal-service');resources.append(('container',app));ready_app()
 s,_,_=http('GET','/api/admin/v1/session',auth=False);assert s==401
 s,_,_=http('POST','/api/admin/v1/session',{'username':'admin','password':password},auth=False,origin=False);assert s==403
 s,login,headers=http('POST','/api/admin/v1/session',{'username':'admin','password':password},auth=False);assert s==200;cookie=headers.get('Set-Cookie').split(';')[0];csrf=login['csrf_token'];assert 'HttpOnly' in headers.get('Set-Cookie') and 'SameSite=Strict' in headers.get('Set-Cookie')
 s,current,_=http('GET','/api/admin/v1/session');assert s==200 and same_session(current,login)
 s,_,_=http('POST','/api/agent/v1/sessions',{'client_operation_id':str(uuid.uuid4()),'title':'not configured','model_alias':'missing'},csrf_header=False);assert s==403
 s,empty,_=http('POST','/api/agent/v1/sessions',{'client_operation_id':str(uuid.uuid4()),'title':'no configured model','model_alias':'missing'});assert s==422 and empty['error']['code']=='model_not_configured'
 base='/api/agent/v1/sessions/'+seed['session_id'];s,snapshot,_=http('GET',base);assert s==200
 s,runstate,_=http('GET',base+'/runs/'+seed['run_id']);assert s==200 and runstate['state']=='needs_confirmation' and runstate['child_request_ids']==[seed['child_request_id']]
 before=sql("SELECT revision FROM qa_product_879a.agent_sessions_v1; SELECT COUNT(*) FROM qa_product_879a.generation_requests; SELECT COUNT(*) FROM qa_product_879a.usage_events;",'before-formal-restarts');assert before.returncode==0
 command(['restart','-t','12',app],'restart-own-service');ready_app();s,restored,_=http('GET','/api/admin/v1/session');assert s==200 and same_session(restored,login)
 command(['restart','-t','15',mysql],'restart-own-mysql');ready_mysql()
 until=time.time()+20
 while time.time()<until:
  status=command(['inspect','--format','{{.State.Status}} {{.State.ExitCode}}',app],'service-exit-after-db-restart').stdout.decode().strip()
  if status.startswith('exited'):break
  time.sleep(.2)
 assert status=='exited 0',status
 command(['start',app],'restart-service-after-db');ready_app();s,restored,_=http('GET','/api/admin/v1/session');assert s==200 and same_session(restored,login)
 s,original,_=http('GET',base+'/runs/'+seed['run_id']);assert s==200 and original['state']=='needs_confirmation' and original['child_request_ids']==[seed['child_request_id']]
 after=sql("SELECT revision FROM qa_product_879a.agent_sessions_v1; SELECT COUNT(*) FROM qa_product_879a.generation_requests; SELECT COUNT(*) FROM qa_product_879a.usage_events;",'after-formal-restarts');assert before.stdout==after.stdout and before.stdout.decode().splitlines()[-2:]==['0','0']
 duplicate=runbin('maas-service',['serve','--config','/qa/product.json'],'second-owner-denied',expected=1);assert b'runtime_already_owned' in duplicate.stderr
 result={'status':('PASS bounded SQL and formal empty-model recovery scope' if not sql_failures else 'PARTIAL: formal recovery passed, separate SQL failures remain'),'SQL_failures':sql_failures,'resource_run':run,'cookie_sha256':hashlib.sha256(cookie.encode()).hexdigest(),'csrf_sha256':hashlib.sha256(csrf.encode()).hexdigest(),'principal_id':login['admin_id'],'seed':seed,'before_after_SQL_equal':True,'new_generation_requests':0,'new_usage_events':0,'models_configured':0,'transport':'own container loopback HTTP; host/proxy/browser not validated','model_calls':0,'restart_cookie_and_csrf_equal':True,'HTTP_cases':cases,'limitations':['No configured model, real source, browser or final deployment package acceptance','Seed is a controlled prior crash checkpoint, not a claim of real upstream side effects','Product role tested only for empty-model auth/recovery; stock core roles separately tested by identities and Installation']}
 (out/'sql-and-formal-results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps({k:result[k] for k in ['status','resource_run','new_generation_requests','new_usage_events']}))
except BaseException as e:
 (out/'sql-and-formal-failure.json').write_text(json.dumps({'type':type(e).__name__,'message':str(e),'HTTP_cases':cases},indent=2),encoding='utf-8');raise
finally:
 cleanup=[]
 for kind,name in resources:
  if kind=='container':
   command(['logs',name],'final-logs-'+name,False)
   command(['inspect','--format','{{.State.Status}} {{.State.ExitCode}} OOM={{.State.OOMKilled}}',name],'final-state-'+name,False)
 for kind,name in reversed(resources):
  fmt='{{index .Config.Labels "maas.qa.run"}}' if kind=='container' else '{{index .Labels "maas.qa.run"}}'
  p=command(([kind] if kind!='container' else [])+['inspect','--format',fmt,name],'cleanup-verify-'+name,False)
  if p.returncode==0 and p.stdout.decode().strip()==run:
   args=['rm','-f',name] if kind=='container' else [kind,'rm',name]
   removed=command(args,'cleanup-remove-'+name,False);cleanup.append({'kind':kind,'name':name,'removed':removed.returncode==0})
  else:cleanup.append({'kind':kind,'name':name,'removed':False,'reason':'label inspection mismatch; no deletion'})
 for f in private.iterdir():f.unlink()
 private.rmdir()
 (out/'cleanup.json').write_text(json.dumps(cleanup,indent=2),encoding='utf-8')
