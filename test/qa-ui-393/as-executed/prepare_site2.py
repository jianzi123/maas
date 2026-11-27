import json,secrets,socket,subprocess,uuid
from pathlib import Path
b=Path(__file__).resolve().parent;src=Path('C:/Users/a9786/AppData/Local/Temp/multica-codex-warm-2751329217/tmp/s393');project='maas7-ui393-'+uuid.uuid4().hex[:8];sock='/tmp/maas11-mysql.'+project+'/mysql.sock'
assert not (b/'site.json').exists(),'retain existing IDs, do not provision twice'
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
origin='http://127.0.0.1:'+str(port)
for group in ['runtime','migration']:(b/'private'/group).mkdir(parents=True,exist_ok=False)
(b/'config').mkdir();password=secrets.token_urlsafe(32);boot=secrets.token_urlsafe(24);pepper=secrets.token_hex(32);cursor=secrets.token_hex(32)
runtime={'maas_runtime_dsn':f'maas_runtime:{password}@unix({sock})/maas?parseTime=true','maas_key_pepper':pepper,'maas_cursor_key':cursor}
migration={**runtime,'maas_runtime_password':password,'maas_bootstrap_password':boot,'maas_migration_dsn':f'root@unix({sock})/maas?parseTime=true','mysql-client.cnf':f'[client]\nuser=root\nprotocol=socket\nsocket={sock}\n'}
for group,data in [('runtime',runtime),('migration',migration)]:
 for name,value in data.items():(b/'private'/group/name).write_text(value,encoding='utf-8')
c=json.loads((src/'config/product.offline.example.json').read_bytes());c.update(listen='0.0.0.0:8080',origin=origin,cluster_id=project,static_dir='/frontend',contract_file='/work/docs/contracts/agent-runtime/ar1-draft2/openapi.json');c['auth']['admin_id']=str(uuid.uuid4());c['offline_controlled'].update(enabled=True,require_approval=True,step_delay_ms=5000)
for name in ['runtime','migration']:(b/'config'/(name+'.json')).write_text(json.dumps(c,indent=2)+'\n',encoding='utf-8')
public={'schema_version':'maas.console/1','chat':{'enabled':True,'limits':c['agent']['limits'],'tools':[{'name':name,'revision':'1'} for name in ['bounded_arithmetic','list_visible_models']]}}
(b/'config/console-config.json').write_text(json.dumps(public,indent=2)+'\n',encoding='utf-8')
directory=str(Path(sock).parent).replace('\\','/');mounts=[str(src)+':/work:ro',str(b/'bin')+':/qa:ro','socket:'+directory,str(b/'config')+':/etc/maas:ro']
compose={'name':project,'services':{
'mysql':{'image':'mysql:8.0.44','environment':{'MYSQL_ALLOW_EMPTY_PASSWORD':'yes','MYSQL_DATABASE':'maas'},'command':['--skip-networking','--mysqlx=0','--socket='+sock,'--innodb-buffer-pool-size=64M','--performance-schema=OFF'],'mem_limit':'384m','volumes':['data:/var/lib/mysql','socket:'+directory],'healthcheck':{'test':['CMD','mysqladmin','--socket='+sock,'-uroot','ping','--silent'],'interval':'2s','timeout':'2s','retries':60}},
'installer':{'image':'mysql:8.0.44','profiles':['install'],'entrypoint':['/bin/bash','/install.sh'],'environment':{'MAAS_INSTALL_DATABASE':'maas'},'volumes':mounts+['private_migration:/run/secrets:ro',str(b/'bin/maas-service')+':/maas:ro',str(src/'deploy/release/migrate.sh')+':/install.sh:ro',str(src/'config/mysql/release-permissions.sql')+':/app/sql/release-permissions.sql:ro',str(src/'config/mysql/kernel-permissions.sql')+':/app/sql/kernel-permissions.sql:ro',str(src/'config/mysql/controlapi-projections.sql')+':/app/sql/controlapi-projections.sql:ro',str(src/'deploy/agent/session-role.sql')+':/app/sql/agent-runtime-role.sql:ro']},
'app':{'image':'alpine:latest','profiles':['site'],'entrypoint':['/qa/maas-service'],'command':['serve','--config','/etc/maas/runtime.json'],'environment':{'GOMAXPROCS':'1','GOMEMLIMIT':'128MiB'},'mem_limit':'192m','ports':['127.0.0.1:'+str(port)+':8080'],'volumes':mounts+['private_runtime:/run/secrets:ro',str(src/'console/dist')+':/frontend:ro']}
},'volumes':{'data':{},'socket':{},'private_runtime':{},'private_migration':{}}}
(b/'compose.json').write_text(json.dumps(compose,indent=2),encoding='utf-8');(b/'site.json').write_text(json.dumps({'project':project,'port':port,'origin':origin,'socket':sock,'base':str(b),'source':str(src),'product_ref':'393edc9c25a2bea55969af87d29158b2f0d74f94','code':'c99e5dfccfabec17b6a582892cd155a37a49b0a4','profile':'offline-controlled/5000ms/requireApproval','mysql_image':'mysql:8.0.44'},indent=2)+'\n',encoding='utf-8')
for group in ['runtime','migration']:
 name=project+'_private_'+group
 subprocess.run(['docker','volume','create','--label','com.docker.compose.project='+project,'--label','com.docker.compose.volume=private_'+group,name],check=True,capture_output=True)
 r=subprocess.run(['docker','run','--rm','--network','none','--label','com.docker.compose.project='+project,'-v',str(b/'private'/group)+':/from:ro','-v',name+':/to','alpine:latest','sh','-c','cp /from/* /to/ && chmod 600 /to/*'],capture_output=True,timeout=30);assert r.returncode==0,r.stderr[-200:]
print(json.dumps({'project':project,'port':port,'profile':'explicit offline; mode600 secrets; no real source'}))
