import copy,json,runpy,sys,urllib.request
from pathlib import Path
base=Path.cwd()/'inputs/delivery-b868';raw=base/'raw';info=json.loads((raw/'fetch-package-inputs.json').read_bytes());script=Path(info['compose']['root'])/'source/deploy/release/smoke.py';complete=json.loads((raw/'offline-record.json').read_bytes());cancelled=json.loads((raw/'cancel-record.json').read_bytes())
fixtures=[('empty',{'sessionId':complete['sessionId'],'runs':[]},False),('pending-empty',json.loads((raw/'pending-command-negative-record.json').read_bytes()),False),('pending-complete',dict(copy.deepcopy(complete),pendingCommand={'run_id':complete['runs'][0]['id']}),False),('missing-usage',copy.deepcopy(complete),False),('completed-original',complete,True),('cancelled-original',cancelled,True)];fixtures[3][1]['runs'][0]['usageHashes']=[]
class NetworkSentinel(Exception):pass
results=[]
for label,value,expect in fixtures:
 record=raw/('bc2-record-'+label+'.json');record.write_text(json.dumps(value,indent=2),encoding='utf-8');before=record.read_bytes();output=raw/('bc2-verify-'+label+'.json');calls=[]
 original=urllib.request.OpenerDirector.open
 def blocked(self,req,*a,**k):calls.append({'method':req.get_method(),'path':req.selector});raise NetworkSentinel('QA preflight boundary, no network performed')
 urllib.request.OpenerDirector.open=blocked
 old=sys.argv;sys.argv=[str(script),'--base','http://127.0.0.1:9','--password-file','__not_read__','--offline-demo','--phase','verify','--record',str(record),'--output',str(output)];code=0
 try:runpy.run_path(str(script),run_name='__main__')
 except SystemExit as e:code=e.code or 0
 finally:sys.argv=old;urllib.request.OpenerDirector.open=original
 assert record.read_bytes()==before
 result=json.loads(output.read_bytes());accepted=len(calls)==1 and result['errorType']=='NetworkSentinel'
 passed=accepted if expect else code!=0 and not calls and result.get('reason','').startswith('Incomplete smoke record')
 assert passed,(label,result,calls)
 results.append({'case':label,'expected_preflight_accept':expect,'preflight_accepted':accepted,'actual_exit':code,'network_attempts_intercepted':len(calls),'actual_network':0,'record_and_ids_unchanged':True,'passed':passed,'scope':'preflight only; complete GET path evidence reused from unchanged b868 body'})
(raw/'bc2-record-guard-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results))
