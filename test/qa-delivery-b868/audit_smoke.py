"""Trace existing installer smoke without altering its assertions/HTTP transport."""
import argparse,json,runpy,sys,time,urllib.parse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--script',type=Path,required=True);p.add_argument('--trace',type=Path,required=True);p.add_argument('args',nargs=argparse.REMAINDER);a=p.parse_args();script=a.script.resolve();rows=[];captures=a.trace.parent/(a.trace.stem+'-payloads');captures.mkdir(exist_ok=False)
def trace(frame,event,arg):
 if event!='return' or frame.f_code.co_name!='request' or frame.f_code.co_filename!=str(script):return
 values=frame.f_locals;method=values.get('method');path=values.get('path')
 if method is None or path is None:return
 row={'method':method,'path':path,'monotonic':time.monotonic()};response=values.get('reply',values.get('response'))
 if response is not None:row['status']=getattr(response,'status',None)
 raw=values.get('raw');url=urllib.parse.urlsplit(path)
 if isinstance(raw,bytes):
  if method=='GET' and path.startswith('/api/agent/v1/') and ('/events' in path or '/tool-calls' in path):
   filename=f'{len(rows):04d}'+('.sse' if path.endswith('/stream') else '.json');(captures/filename).write_bytes(raw);row['payload']=filename
  try:
   body=json.loads(raw)
   if isinstance(body,dict):
    for key in ('state','id','models_configured','profile'):
     if key in body:row[key]=body[key]
    if isinstance(body.get('run'),dict):row['accepted_run_id']=body['run'].get('id')
    if isinstance(body.get('data'),list):row['row_count']=len(body['data']);row['ledger_statuses']=[x.get('status') for x in body['data'] if isinstance(x,dict) and 'status'in x]
  except (ValueError,TypeError):pass
 rows.append(row)
code=0
try:
 sys.argv=[str(script),*(a.args[1:] if a.args[:1]==['--'] else a.args)];sys.setprofile(trace);runpy.run_path(str(script),run_name='__main__')
except SystemExit as e:code=e.code or 0
finally:
 sys.setprofile(None);a.trace.write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
raise SystemExit(code)
