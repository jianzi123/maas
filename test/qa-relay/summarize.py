from pathlib import Path
import json,re,hashlib,subprocess,datetime
r=Path(__file__).resolve().parents[2];a=r/'artifacts'
raw=json.loads((a/'qa-relay-evidence.json').read_text(encoding='utf-8'));cases=raw['cases']
text=(a/'qa-targeted.txt').read_text(encoding='utf-8');pairs=re.findall(r'--- (PASS|FAIL|SKIP): (\S+) ',text)
leaves={n:k for k,n in pairs if not any(m.startswith(n+'/') for _,m in pairs)}
groups={name:{k:v for k,v in leaves.items() if k.startswith(prefix)} for name,prefix in [('independent_sql','TestQARelayErrorAndSampling/'),('independent_functions','TestQASamplerLimits/'),('author_sql','TestMySQLRelaySampling/') ]}
groups['author_bounded_queue']={k:v for k,v in leaves.items() if k=='TestSamplerBoundedDrop'}
assert [len(groups[x]) for x in groups]==[19,9,10,1]
assert len(cases)==19
samples=[x['sample'] for x in cases if x['sample'] is not None]
assert len(samples)==17 and sum(x['dropped'] for x in cases)==1
assert sum(x['case']=='sampling_disabled' for x in cases)==1
assert all(x['passed'] for x in cases) and set(leaves.values())=={'PASS'}
for case in cases:
 if case['terminal']['result']!='succeeded':
  assert case['terminal']['budget_accounting']['token_actual'] is None
  assert case['terminal']['budget_accounting']['cost_actual_atomic'] is None
  assert case['token']['Known']=='0' and case['token']['Held']=='140'
  assert case['money']['Known']=='0' and case['money']['Held']=='520000'
allowed={'schema_version','run_id','request_id','instance_id','boot_id','clock_scope','source_revision','publication_id','release_revision','first_protocol_ms','first_content_received_ms','first_content_write_ok_ms','first_content_flush_attempt_ms','end_ms','result','return_error'}
for row in samples:
 assert set(row)==allowed
 assert row['clock_scope']==row['instance_id']+'/'+row['boot_id']+'/'+row['request_id']
 assert row['source_revision']=='c7e863b-qa-controlled'
 assert all(row[k] is None or 0<=row[k]<=row['end_ms'] for k in ['first_protocol_ms','first_content_received_ms','first_content_write_ok_ms','first_content_flush_attempt_ms'])
export={'schema_version':'maas-go-relay-export-1.0','evidence_kind':'independent_controlled_go_http_mysql','samples':samples,'missing_identity':['trace_id','experiment_ref','cell_id','replicate','complete_binding_sha256','runtime_metadata_ref'],'missing_components':['real_higress','worker','gpu','client_receive','cross_clock_calibration']}
(a/'qa-go-relay-source.json').write_text(json.dumps(export,indent=2),encoding='utf-8',newline='\n')
for marker in ['QA_PRIVATE_PROVIDER_ERROR','QA_PRIVATE_KEY_MARKER','QA_MUST_NOT_LEAK']:
 assert marker not in json.dumps(export)
manifest={'product_commit':'c7e863b11fb34ee2828c947393444e1e5a9baf08','worktree_head_at_summary':subprocess.check_output(['git','-C',str(r),'rev-parse','HEAD'],text=True).strip(),'qa_test_overlay_sha256':hashlib.sha256((r/'test/qa-relay/relay_test.go.in').read_bytes()).hexdigest(),'source_sha256':{p:hashlib.sha256((r/p).read_bytes()).hexdigest() for p in ['internal/kernel/relay_forward.go','internal/kernel/relay.go','internal/kernel/public_response.go','internal/kernel/content.go','internal/kernel/relay_sample.go','internal/kernel/relay_sampling_mysql_test.go']},'raw_case_evidence_sha256':hashlib.sha256((a/'qa-relay-evidence.json').read_bytes()).hexdigest(),'export_sha256':hashlib.sha256((a/'qa-go-relay-source.json').read_bytes()).hexdigest(),'source_revision_preserved':'c7e863b-qa-controlled','denominator':{'executions':19,'sampling_disabled':1,'offer_attempts_from_forward':18,'exported_summary':17,'dropped':1,'prefilled_queue_sentinel_is_not_business_request':True},'complete_sidecar_ready':False,'no_cross_request_or_component_subtraction':True,'injections_ms':raw['timing_injections_ms']}
(a/'qa-source-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8',newline='\n')
result={'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'product_sha':manifest['product_commit'],'groups':groups,'denominator':manifest['denominator'],'requests':{x['case']:x['request_id'] for x in cases},'no_new_product_failure':True,'prior_usage_reader_qa001_002_003':'RETAINED_NOT_RERUN','full_80':'NOT_RERUN','d1_consumer_e1':'NOT_EXECUTED','production_callable':False}
(a/'qa-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
(r/'test/qa-relay/results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
print(json.dumps({'groups':{k:len(v) for k,v in groups.items()},'denominator':manifest['denominator'],'failed':0,'samples':len(samples)}))