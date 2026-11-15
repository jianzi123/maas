from pathlib import Path
import json,re,hashlib,zipfile
r=Path(__file__).resolve().parents[2];a=r/'artifacts'
s=(a/'qa-targeted.txt').read_text(encoding='utf-8');pairs=re.findall(r'--- (PASS|FAIL|SKIP): (\S+) ',s);leaf={n:k for k,n in pairs if not any(m.startswith(n+'/') for _,m in pairs)}
groups={'original':{k:v for k,v in leaf.items() if k.startswith('TestMAAS17')},'independent_stream':{k:v for k,v in leaf.items() if k.startswith('TestQAR1R2/')},'independent_rollback':{k:v for k,v in leaf.items() if k.startswith('TestQAR1TransactionRollback/')},'independent_publisher':{k:v for k,v in leaf.items() if k=='TestQAR3PublisherProjection'}}
assert [len(x) for x in groups.values()]==[5,7,2,1]
assert set(leaf.values())=={'PASS'}
expected='4dac0037a305c2ab8bdc14491962e9ae2ec1fb7bb56994f0276489023132b0cc'
assert hashlib.sha256((r/'internal/kernel/maas17_review_test.go').read_bytes()).hexdigest()==expected
assert hashlib.sha256((r/'test/qa-r123/original-oracle.go.txt').read_bytes()).hexdigest()==expected
rows=json.loads((a/'qa-relay-evidence.json').read_text(encoding='utf-8'));assert len(rows)==7 and all(x['passed'] for x in rows)
for x in rows:
 assert x['calls']==1
 if x['terminal']['result']!='succeeded':
  assert x['terminal']['budget_accounting']['token_actual'] is None
  assert x['terminal']['budget_accounting']['cost_actual_atomic'] is None
assert s.count('mysql 1143')==3 and s.count('mysql 1142')==4
result={'product_sha':'ac94a373ec0a61c5fd4dc5380a7985a4fb47840f','oracle_sha256':expected,'groups':groups,'permission_denials':{'1143':3,'1142':4},'stream_requests':{x['case']:x['request_id'] for x in rows},'R1':'CONTROLLED_PASS','R2':'CONTROLLED_PASS','R3':'CONTROLLED_PASS','old_scopes':'RETAINED_NOT_RERUN','full_A01_A34':'NOT_ACCEPTED','production_callable':False}
(a/'qa-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
(r/'test/qa-r123/results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
print(json.dumps({'counts':{k:len(v) for k,v in groups.items()},'failures':0,'permission_denials':result['permission_denials'],'requests':result['stream_requests']}))