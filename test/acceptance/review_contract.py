"""Independent static review. No HTTP/server/model claims are made."""
import argparse, copy, hashlib, importlib.metadata, json, pathlib, sys
from jsonschema import Draft202012Validator, FormatChecker

p=argparse.ArgumentParser()
p.add_argument('--draft',type=pathlib.Path,required=True)
p.add_argument('--output',type=pathlib.Path,required=True)
args=p.parse_args()
root=args.draft
sub=root/'query-recovery-v0.4.2-draft'
load=lambda path: json.loads(path.read_text(encoding='utf-8-sig'))
api=load(sub/'contracts/MAAS-2-openapi-v0.4.2-draft.json')
base=load(sub/'baseline/v0.4-openapi.json')
schemas=api['components']['schemas']
checks=[]
def check(name, value):
    checks.append({'name':name,'passed':bool(value)})
def valid(schema,value):
    full={**schemas[schema],'components':{'schemas':schemas}}
    return Draft202012Validator(full,format_checker=FormatChecker()).is_valid(value)
for item in load(sub/'MANIFEST.sha256.json'):
    raw=(root/item['path']).read_bytes()
    check('manifest '+item['path'],len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256'])
for case in load(sub/'examples/schema-cases.json'):
    check('source shape '+case['name'],valid(case['schema'],case['value'])==case['expected_valid'])
check('draft identity',api['info']['version']=='0.4.2-draft.1')
check('budget unchanged',all(schemas[k]==base['components']['schemas'][k] for k in ['BudgetLimits','BudgetPolicyInput','Usage','RequestRecord']))
check('explicit policy required','budget_policy' in schemas['KeyCreate']['required'])
desc=api['paths']['/api/admin/v1/keys']['post']['responses']['201']['description']
check('J01 no implicit quota','default 100' not in desc and 'explicitly supplied budget_policy' in desc)
limits={'requests':'0','tokens':None,'money':None}
check('zero is legal blocked dimension',valid('BudgetLimits',limits))
check('null disabled dimensions legal',valid('BudgetLimits',dict.fromkeys(limits)))
for dimension in limits:
    v=dict(limits); v.pop(dimension)
    check('dimension explicit '+dimension,not valid('BudgetLimits',v))
cases=load(sub/'examples/schema-cases.json')
lookups=[x['value'] for x in cases if x['schema']=='RequestLookupPage' and x['expected_valid']]
recorded=next(x for x in lookups if x['lookup']['resolution']=='recorded')
unknown=next(x for x in lookups if x['lookup']['resolution']=='unknown')
for count in [0,2]:
    v=copy.deepcopy(recorded); v['data']=v['data']*count
    check('exact recorded rejects row count '+str(count),not valid('RequestLookupPage',v))
for mutation in ['cursor','complete','row']:
    v=copy.deepcopy(unknown)
    if mutation=='cursor': v['next_cursor']='next'
    if mutation=='complete': v['data_complete']=True
    if mutation=='row': v['data']=recorded['data']
    check('unknown rejects '+mutation,not valid('RequestLookupPage',v))
# Exact row/query and history UID equality require consumer/server predicates.
def exact_consumer(query_id, page):
    return (valid('RequestLookupPage',page) and page['lookup']['request_id']==query_id
            and all(x['request_id']==query_id for x in page['data']))
v=copy.deepcopy(recorded); v['data'][0]['request_id']='99999999-9999-4999-8999-999999999999'
check('wrong original row rejected semantically',not exact_consumer(recorded['lookup']['request_id'],v))
v=copy.deepcopy(recorded); v.pop('lookup')
check('legacy ordinary envelope rejected',not exact_consumer(recorded['lookup']['request_id'],v))
history=next(x['value'] for x in cases if x['schema']=='ReleaseRevisionPage' and x['expected_valid'] and x['value']['resource_state']=='present')
for state,reason in [('deleted','cr_deleted'),('replaced','cr_replaced'),('unknown','state_unavailable')]:
    v=copy.deepcopy(history); v['resource_state']=state; v['resource_version']=None
    for row in v['data']:
        row['is_active']=False
        row['rollback_eligibility']={'state':'eligible','reason_codes':[],'checked_at':v['generated_at'],'evaluated_resource_version':'7'}
    check(state+' cannot be eligible',not valid('ReleaseRevisionPage',v))
# Verify minimum HTTP contract promises without claiming any route was executed.
route=api['paths']['/api/admin/v1/usage/requests']['get']
check('exact query session protected',route['security']==[{'AdminSession':[]}])
for code in ['400','401','403','404','503']:
    check('exact HTTP documented '+code,code in route['responses'])
history_route=api['paths']['/api/admin/v1/model-releases/{namespace}/{name}/revisions']['get']
check('history UID mandatory',any(x['name']=='cr_uid' and x.get('required') for x in history_route['parameters']))
check('history session protected',history_route['security']==[{'AdminSession':[]}])
check('rollback UID optional for compatibility','expected_cr_uid' in schemas['ReleaseRollbackInput']['properties'] and 'expected_cr_uid' not in schemas['ReleaseRollbackInput']['required'])
result={'kind':'independent_static_contract_review','python':sys.version.split()[0],
        'jsonschema':importlib.metadata.version('jsonschema'),'checks':checks,
        'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks),
        'limits':['No SQL/HTTP/browser executed by this script','Authority of rejection/retention/approval evidence remains unverified','Semantic predicates are QA oracles, not product implementation']}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ['checks','limits']}))
sys.exit(bool(result['failed']))
