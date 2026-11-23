import importlib.util,io,json,shutil,sys,zipfile,hashlib,subprocess
from pathlib import Path
root=Path.cwd();base=root/'inputs/delivery-b868';raw=base/'raw';inputs=json.loads((raw/'fetch-package-inputs.json').read_bytes());actual=Path(inputs['compose']['root']);short=actual.parent/'bc2-negative';short.mkdir(exist_ok=False)
def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
verify=module(actual/'source/deploy/release/verify_bundle.py','actual_bundle_validator');fetch=module(actual/'fetch_source.py','actual_fetch_validator');results=[]
for kind,item in inputs.items():
 p=Path(item['root']);result=verify.verify(p);assert result['passed'];manifest=json.loads((p/'SOURCE.sha256.json').read_bytes())
 for name,info in manifest.items():assert (p/'source'/name).stat().st_size==info['bytes'] and hashlib.sha256((p/'source'/name).read_bytes()).hexdigest()==info['sha256']
 results.append({'case':kind+' actual network source+bundle','passed':True,'files':len(manifest),'bundle_files':result['filesChecked']})
# Full manifest negative fixtures; actual complete source copies, never mutate original.
for name,mode in [('corrupt-source','corrupt'),('empty-manifest','empty'),('omitted-main-entry','omit')]:
 p=short/name;shutil.copytree(actual,p);main=p/'source/cmd/maas-service/main.go';main.write_bytes(main.read_bytes()+b'\n// QA corruption fixture\n')
 if mode=='empty':(p/'MANIFEST.sha256.json').write_text('{}',encoding='utf-8')
 if mode=='omit':
  d=json.loads((p/'MANIFEST.sha256.json').read_bytes());d.pop('source/cmd/maas-service/main.go');(p/'MANIFEST.sha256.json').write_text(json.dumps(d),encoding='utf-8')
 observed=verify.verify(p);results.append({'case':name,'expected':'reject corrupted/incomplete manifest','actual_passed':observed['passed'],'filesChecked':observed['filesChecked'],'oracle_passed':not observed['passed'],'failures':observed['failures']})
# Reuse the captured real GitHub archive only for deterministic negative inputs.
archive=(raw/'source-network-compose.zip').read_bytes();fetch.urllib.request.urlopen=lambda *a,**k:io.BytesIO(archive)
for name,mode in [('fetch-wrong-hash','hash'),('fetch-omitted-main','omit'),('fetch-traversal','traversal')]:
 p=short/name;p.mkdir()
 for f in actual.iterdir():
  if f.is_file():shutil.copyfile(f,p/f.name)
 manifest=json.loads((p/'SOURCE.sha256.json').read_bytes())
 if mode=='hash':manifest['cmd/maas-service/main.go']['sha256']='0'*64
 if mode=='omit':manifest.pop('cmd/maas-service/main.go')
 if mode=='traversal':manifest['../escape']={'bytes':0,'sha256':hashlib.sha256(b'').hexdigest()}
 (p/'SOURCE.sha256.json').write_text(json.dumps(manifest),encoding='utf-8');error=None;observed=None
 try:observed=fetch.fetch(p)
 except Exception as e:error=type(e).__name__+': '+str(e)
 results.append({'case':name,'expected':'reject without publishing source','actual':observed,'error':error,'source_published':(p/'source').exists(),'oracle_passed':not (p/'source').exists() and error is not None})
(raw/'bc2-artifact-positive-negative.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results))
