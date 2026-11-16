from pathlib import Path
import json,subprocess,tarfile,io,hashlib
r=Path(__file__).resolve().parents[2];code='ada28d8f3552d18a3f9cfc448b4b54e1dabc0b93';head='00a3e62c539b726113fa21686e29096be88820e2'
locks=['deploy/build-sources.lock.json','deploy/charts/maas-platform/runtime-interface.json','deploy/dependencies.lock.json','deploy/identities.json']
changed=subprocess.check_output(['git','-C',str(r),'diff','--name-only',code,head]).decode().splitlines();assert set(changed)==set(locks)
data=json.loads((r/locks[0]).read_text(encoding='utf-8'))
archive=subprocess.check_output(['git','-C',str(r),'archive',code]);tar=tarfile.open(fileobj=io.BytesIO(archive));counts={}
for group in ['backend','console']:
 assert data[group]['sourceCommit']==code
 for p,h in data[group]['files'].items():assert hashlib.sha256(tar.extractfile(p).read()).hexdigest()==h,p
 counts[group]=len(data[group]['files'])
dep=json.loads((r/'deploy/dependencies.lock.json').read_text(encoding='utf-8'));ids=json.loads((r/'deploy/identities.json').read_text(encoding='utf-8'));assert dep['deploymentApproved'] is False and ids['productionWiringVerified'] is False
out={'code_sha':code,'four_lock_head':head,'exact_four_metadata_changes':changed,'source_hash_matches':counts,'deploymentApproved':False,'productionWiringVerified':False,'factory_production_consumers':subprocess.check_output(['git','-C',str(r),'grep','-n','OpenRelayTLS',head,'--','cmd']).decode() if False else 'not supplied by this increment; confirmed static diff'}
(r/'artifacts/qa-locks.json').write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out))