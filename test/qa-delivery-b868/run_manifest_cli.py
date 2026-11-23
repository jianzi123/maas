import json,subprocess,sys
from pathlib import Path
base=Path.cwd()/'inputs/delivery-b868';raw=base/'raw';root=Path(json.loads((raw/'fetch-package-inputs.json').read_bytes())['compose']['root']);negative=root.parent/'bc2-negative';rows=[]
for name in ('corrupt-source','empty-manifest','omitted-main-entry'):
 target=negative/name;cmd=[sys.executable,str(root/'source/deploy/release/verify_bundle.py'),'--root',str(target)];p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8');(raw/(name+'-actual-cli.stdout')).write_text(p.stdout,encoding='utf-8');(raw/(name+'-actual-cli.stderr')).write_text(p.stderr,encoding='utf-8');rows.append({'case':name,'expected_exit':'nonzero','actual_exit':p.returncode,'command':cmd})
(raw/'actual-manifest-cli-results.json').write_text(json.dumps(rows,indent=2),encoding='utf-8');print(json.dumps(rows))
