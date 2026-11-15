from pathlib import Path
import json,re,datetime
r=Path(__file__).resolve().parents[2];a=r/'artifacts'
def leaves(file):
 pairs=re.findall(r'--- (PASS|FAIL|SKIP): (\S+) ',(a/file).read_text(encoding='utf-8'))
 return {n:k for k,n in pairs if not any(other.startswith(n+'/') for _,other in pairs)}
first=leaves('qa-targeted.txt');retest=leaves('qa-partial-retest.txt')
assert len(retest)==1 and next(iter(retest.values()))=='PASS'
final=first|retest
ownUsage={k:v for k,v in final.items() if k.startswith('TestQAUsageAuthority/')}
reader={k:v for k,v in final.items() if k.startswith('TestQAProjectionIdentity/')}
authorSQL={k:v for k,v in final.items() if k.startswith('TestMySQLUsageAuthority/') or k=='TestMySQLProjectionIdentity'}
pure={k:v for k,v in final.items() if k.startswith('TestUsageAuthority/') or k=='TestProjectionMissingDoesNotFallback'}
assert [len(ownUsage),len(reader),len(authorSQL),len(pure)]==[20,12,8,7]
assert set(final.values())=={'PASS'}
initial=json.loads((a/'qa-usage-evidence.json').read_text(encoding='utf-8'))
last=json.loads((a/'qa-usage-partial-retest.json').read_text(encoding='utf-8'))
merged={x['case']:x for x in initial};merged.update({x['case']:x for x in last})
assert len(merged)==19 and all(x['passed'] for x in merged.values())
for x in merged.values():
 if x['expected_success']:
  assert x['tokens']['Known']=='19' and x['money']['Known']=='72800'
  assert x['terminal']['budget_accounting']['cost_actual_atomic']=='72800'
 else:
  assert x['tokens']['Held']=='140' and x['money']['Held']=='520000'
  assert x['terminal']['budget_accounting']['token_actual'] is None
  assert x['terminal']['budget_accounting']['cost_actual_atomic'] is None
result={'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'product_sha':'d2d7869fe16b8968d6ca5b00a63560c322b84dc1','base_sha':'925d8c55be9ce823d100bf90a5c78cf19ea66d58','independent_usage':ownUsage,'independent_reader':reader,'affected_author_mysql':authorSQL,'affected_author_functions':pure,'initial_oracle_failure':'final_partial_not_backfilled incorrectly required known input=12 to be null; corrected against existing per-field partial/null rule; original log kept; only that case rerun','final_usage_evidence':list(merged.values()),'QA-003':'PRIOR_CONTROLLED_CLOSE_RETAINED','production_callable':False,'A01_A34':'NOT_FULLY_ACCEPTED','browser':'NOT_RERUN','full_80_mysql':'NOT_RERUN','full_go_vet_build':'NOT_RERUN'}
(a/'qa-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
(r/'test/qa-usage/results.json').write_text(json.dumps({k:v for k,v in result.items() if k!='final_usage_evidence'},ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
print(json.dumps({'independent_usage':len(ownUsage),'independent_reader':len(reader),'author_sql':len(authorSQL),'author_functions':len(pure),'failed_final':0,'raw_initial_oracle_failures':sum(v=='FAIL' for v in first.values()),'only_retested':list(retest)}))