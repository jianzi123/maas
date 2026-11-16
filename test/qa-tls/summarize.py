from pathlib import Path
import re,json
r=Path(__file__).resolve().parents[2];s=(r/'artifacts/qa-tls.txt').read_text(encoding='utf-8');pairs=re.findall(r'--- (PASS|FAIL|SKIP): (\S+) ',s);leaf={n:k for k,n in pairs if not any(m.startswith(n+'/') for _,m in pairs)}
qa={k:v for k,v in leaf.items() if k.startswith('TestQATLSFactory/')};author={k:v for k,v in leaf.items() if k.startswith('TestRelayTLSRuntime/')}
assert len(qa)==38 and len(author)==13,(len(qa),len(author))
assert set(leaf.values())=={'PASS'}
result={'head':'00a3e62c539b726113fa21686e29096be88820e2','code':'ada28d8f3552d18a3f9cfc448b4b54e1dabc0b93','independent':qa,'author_rerun':author,'scope':'TLS factory/client.Do component; temporary local PKI; no Relay.Forward/business DB or real Higress','production_callable':False,'historical_business_qa':'RETAINED_NOT_RERUN','real_model':'NOT_EXECUTED'}
(r/'artifacts/qa-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n');(r/'test/qa-tls/results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n');print(json.dumps({'independent':len(qa),'author':len(author),'failure':0}))