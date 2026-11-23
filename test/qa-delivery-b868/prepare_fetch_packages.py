import hashlib,json,zipfile
from pathlib import Path
base=Path.cwd()/'inputs/delivery-b868';short=Path('C:/Users/a9786/AppData/Local/Temp/multica-task-448786089')
items={'compose':('01a20985-7d04-74d6-8024-0230cf25cabe','193530','e4c64dd8be2ab6ed1c174cbb167e1f402315f223a0a052709d6d4b3d1d955e9e'),'kubernetes':('01a20985-861d-7418-89e6-7b361549b24b','191904','89a947b18240786042eab150932e54aa05e22d95c211ae589ced4dc47c5093b8')}
result={}
for kind,(id,size,want) in items.items():
 file=next((base/'new-packages').glob('maas-'+kind+'-bc2f7b37e540-fetch.zip'));assert file.stat().st_size==int(size) and hashlib.sha256(file.read_bytes()).hexdigest()==want
 root=short/('bc2-'+kind);root.mkdir(exist_ok=True)
 with zipfile.ZipFile(file) as z:
  for name in z.namelist():assert(root/name).resolve().is_relative_to(root.resolve())
  z.extractall(root)
 manifest=json.loads((root/'MANIFEST.sha256.json').read_bytes())
 for name,value in manifest.items():
  if not name.startswith('source/'):assert hashlib.sha256((root/name).read_bytes()).hexdigest()==value,name
 assert not (root/'source').exists()
 version=json.loads((root/'VERSION.json').read_bytes());assert version['repositoryCommit']=='bc2f7b37e540511644794a30cac4a4b88fddd96c'
 result[kind]={'root':str(root),'bytes':int(size),'sha256':want,'attachment_id':id,'installer_manifest':len(manifest),'source_manifest':len(json.loads((root/'SOURCE.sha256.json').read_bytes()))}
(base/'raw/fetch-package-inputs.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
