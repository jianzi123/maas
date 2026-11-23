import hashlib,json,os,subprocess
from pathlib import Path
repo=Path(__file__).resolve().parents[3];out=Path(os.environ['MAAS_QA_OUT']).resolve();out.mkdir(parents=True,exist_ok=False)
fixed=json.loads((Path(__file__).parent/'results.json').read_text(encoding='utf-8'))
locks={'deploy/build-sources.lock.json','deploy/charts/maas-platform/runtime-interface.json','deploy/dependencies.lock.json','deploy/identities.json'}
for name,value in fixed['product_original_files_sha256'].items():
 if name not in locks:assert hashlib.sha256((repo/name).read_bytes()).hexdigest()==value,name
info={'product_head':fixed['product_head'],'qa_head':subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD']).decode().strip()}
for key,tag in [('mysql_image','mysql:8.0.44'),('runner_image','alpine:latest')]:info[key]=subprocess.check_output(['docker','image','inspect',tag,'--format','{{.Id}}']).decode().strip()
(out/'environment.json').write_text(json.dumps(info,indent=2)+'\n',encoding='utf-8')
print(json.dumps(info))
