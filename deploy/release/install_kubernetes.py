"""Run existing native manifests with a fresh mandatory audit Job.
Explicit approved kubeconfig/context/namespace; no cluster creation or receipt.
"""
import argparse,json,subprocess,uuid
from pathlib import Path
import yaml

def install(root,namespace,execute,external_database=False):
    documents={}
    for name in ('namespace','config','migration','application')+(() if external_database else ('mysql',)):
        documents[name]=list(yaml.safe_load_all((root/(name+'.yaml')).read_text(encoding='utf-8')))
        for doc in documents[name]:
            if not doc:continue
            expected=doc['metadata'].get('name') if doc['kind']=='Namespace' else doc['metadata'].get('namespace')
            if expected!=namespace:raise ValueError('manifest namespace differs from explicit namespace')
    for name in ('namespace','config'):execute(['apply','-f',str(root/(name+'.yaml'))])
    if not external_database:
        execute(['apply','-f',str(root/'mysql.yaml')]);execute(['rollout','status','statefulset/mysql','--timeout=300s'])
    if execute(['get','deployment','maas','--ignore-not-found','-o','name'],capture=True).strip():
        execute(['scale','deployment/maas','--replicas=0']);execute(['wait','--for=delete','pod','-l','app=maas','--timeout=90s'])
    jobs=json.loads(execute(['get','jobs','-o','json'],capture=True))['items']
    for old in jobs:
        if old.get('spec',{}).get('template',{}).get('metadata',{}).get('labels',{}).get('app')!='maas-migrate':continue
        if not any(c.get('type') in ('Complete','Failed') and c.get('status')=='True' for c in old.get('status',{}).get('conditions',[])):
            raise ValueError('inspect previous nonterminal migration; no parallel migration')
    job=documents['migration'][0];job['metadata']['name']+='-'+uuid.uuid4().hex[:8]
    (root/('migration-attempt-'+job['metadata']['name']+'.json')).write_text(json.dumps({'job':job['metadata']['name'],'namespace':namespace},indent=2)+'\n',encoding='utf-8')
    execute(['create','-f','-'],data=yaml.safe_dump(job))
    execute(['wait','--for=condition=complete','job/'+job['metadata']['name'],'--timeout=180s'])
    execute(['apply','-f',str(root/'application.yaml')])
    for name in ('maas','web'):execute(['rollout','status','deployment/'+name,'--timeout=180s'])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,default=Path('.'));p.add_argument('--kubeconfig',type=Path,required=True);p.add_argument('--context',required=True);p.add_argument('--namespace',required=True);p.add_argument('--kubectl',default='kubectl');p.add_argument('--external-database',action='store_true')
    a=p.parse_args();prefix=[a.kubectl,'--kubeconfig',str(a.kubeconfig.resolve()),'--context',a.context,'--request-timeout=15s','-n',a.namespace]
    def execute(args,capture=False,data=None):
        r=subprocess.run(prefix+args,input=data,text=True,capture_output=capture,timeout=330)
        if r.returncode:raise RuntimeError('native installation/audit step failed: exit '+str(r.returncode))
        return r.stdout if capture else None
    try:install(a.directory.resolve(),a.namespace,execute,a.external_database)
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.TimeoutExpired):
        print('Native install/audit failed; no application start follows. Retain original Job, data and Secrets; inspect before another attempt.');return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
