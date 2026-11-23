"""Minimal QA-DEP-MANIFEST-001, never modify installer or execute product code."""
import argparse,importlib.util,json,shutil,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--installer',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
shutil.copyfile(a.installer/'VERSION.json',a.output/'VERSION.json')
for name in ('deploy/build-sources.lock.json','deploy/dependencies.lock.json','deploy/identities.json','deploy/charts/maas-platform/runtime-interface.json'):
 target=a.output/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.installer/'source'/name,target)
(a.output/'MANIFEST.sha256.json').write_text('{}',encoding='utf-8')
script=a.installer/'source/deploy/release/verify_bundle.py';r=subprocess.run([sys.executable,str(script),'--root',str(a.output)],capture_output=True,text=True,encoding='utf-8')
result={'expected':'nonzero; required source missing and empty manifest','actual_exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'source_files_present':4,'codeCommit':json.loads((a.output/'VERSION.json').read_bytes())['codeCommit']}
(a.output/'oracle.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result));raise SystemExit(1 if r.returncode==0 else 0)
