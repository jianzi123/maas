import copy,hashlib,json,subprocess,sys
from pathlib import Path
from jsonschema import Draft202012Validator,ValidationError
b=Path(__file__).resolve().parent;src=Path('C:/Users/a9786/AppData/Local/Temp/multica-codex-warm-2751329217/tmp/s393');raw=b/'raw';root=src/'docs/contracts/agent-runtime/ar1-draft2';contract=json.loads((root/'openapi.json').read_bytes());event_schema=json.loads((root/'session-event.schema.json').read_bytes());cases=[]
# The supplied entry is an allowed read-only sample validator. Its execution is
# recorded separately from our negative controls and lineage assertions below.
r=subprocess.run([sys.executable,str(src/'test/controlled/maas20/fc1-tools/validate-traces.py')],cwd=src,capture_output=True,timeout=30);(raw/'provided-trace-validator.stdout').write_bytes(r.stdout);(raw/'provided-trace-validator.stderr').write_bytes(r.stderr);assert r.returncode==0,r.stderr[-300:]
provided=json.loads(r.stdout);assert sum(x['http_samples'] for x in provided['cases'])==34;assert sum(x['persisted_events'] for x in provided['cases'])==42
for n in ['complete','invalid_second_tool']:
 p=src/'test/controlled/maas20/fc1-tools/wire'/(n+'.json');d=json.loads(p.read_bytes());records=d['original_child_records'];ids=[x['data'][0]['request_id'] for x in records];assert len(ids)==len(set(ids))==(2 if n=='complete' else 1)
 for rec in records:assert rec['data_complete'] and len(rec['data'])==1
 # The consumer data is from retained controlled producer samples, not a new
 # model/Higress execution. Keep original sample hashes and counts verbatim.
 cases.append({'id':'TRACE-'+n,'status':'PASS','sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'http':len(d['http']),'events':len(d['persisted_session']['events']),'distinct_original_child_ids':ids})
 if n=='complete':sample=d
v=Draft202012Validator({'$ref':'#/components/schemas/Conversation','components':contract['components']});valid=next(x['body'] for x in sample['http'] if x['path']=='/api/agent/v1/sessions');v.validate(valid);bad=copy.deepcopy(valid);bad['qa_unapproved_field']=True
try:v.validate(bad)
except ValidationError as e:assert e.validator=='additionalProperties';cases.append({'id':'STRICT-HTTP-extra-field-rejected','status':'PASS'})
else:raise AssertionError('HTTP unexpected field accepted')
event=sample['persisted_session']['events'][0]['ar1'];ev=Draft202012Validator(event_schema);ev.validate(event);bad=copy.deepcopy(event);bad['qa_unapproved_field']=True
try:ev.validate(bad)
except ValidationError as e:assert e.validator=='additionalProperties';cases.append({'id':'STRICT-EVENT-extra-field-rejected','status':'PASS'})
else:raise AssertionError('Event unexpected field accepted')
for n in ['openapi.json','session-event.schema.json']:
 original=subprocess.check_output(['git','-C',str(Path.cwd()/'maas'),'show','4402c456:docs/contracts/agent-runtime/ar1-draft2/'+n]);assert original==(root/n).read_bytes()
(raw/'trace-independent-results.json').write_text(json.dumps({'product_ref':'393edc9c25a2bea55969af87d29158b2f0d74f94','provided_validator_execution':provided,'independent_checks':cases,'public_schema_unchanged_from_4402':True,'live_supplier_calls':0,'classification':'retained controlled HTTP/MySQL producer samples; not independently regenerated runtime'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'http_samples':34,'events':42,'independent_checks':len(cases),'passed':len(cases),'public_schema_unchanged':True}))
