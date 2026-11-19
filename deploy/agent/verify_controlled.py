"""Owned foreground AR-1 controlled listener assembly validation; Linux/WSL only."""
import argparse, json, os, signal, socket, subprocess, time, uuid, hashlib, http.client
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("--binary",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
a=p.parse_args()
if os.name != "posix":p.error("Run this process supervisor in approved Linux/WSL")
out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
state=out/"private-state";state.mkdir(mode=0o700)
owner="4c421973-919f-4b8a-997f-909fc6fd010a"
with socket.socket() as reserve:reserve.bind(("127.0.0.1",0));port=reserve.getsockname()[1]
origin="http://127.0.0.1:"+str(port);proc=None;cookie=None;csrf=None;records=[]
def request(method,path,body=None,etag=None,expected=200,extra=None):
    h={"Origin":origin}
    if cookie:h["Cookie"]=cookie
    if csrf:h["X-CSRF-Token"]=csrf
    if etag:h["If-Match"]=etag
    if body is not None:h["content-type"]="application/json"
    h.update(extra or {})
    c=http.client.HTTPConnection("127.0.0.1",port,timeout=4)
    try:
        c.request(method,path,body=json.dumps(body).encode() if body is not None else None,headers=h)
        r=c.getresponse();headers={k.lower():v for k,v in r.getheaders()};raw=r.read()
        records.append({"method":method,"path":path,"status":r.status,"bodySha256":hashlib.sha256(raw).hexdigest()})
        assert r.status==expected,(path,r.status)
        return headers,raw
    finally:c.close()
def start():
    global proc
    log=open(out/"process.log","ab")
    proc=subprocess.Popen([str(a.binary.resolve()),"--state-dir",str(state),"--owner-id",owner,"--listen","127.0.0.1:"+str(port)],stdout=log,stderr=log)
    log.close()
    for _ in range(100):
        if proc.poll() is not None:raise RuntimeError("listener startup failed")
        try:
            with socket.create_connection(("127.0.0.1",port),timeout=0.1):return
        except OSError:time.sleep(0.05)
    raise RuntimeError("startup timeout")
def stop():
    global proc
    if proc and proc.poll() is None:
        proc.send_signal(signal.SIGINT)
        try:code=proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.terminate();proc.wait(timeout=5);raise RuntimeError("graceful shutdown failed")
        assert code==0,code
    assert not (state/".owner-lock").exists(),"lock retained after graceful exit"
def login():
    global cookie,csrf
    headers,raw=request("POST","/__maas/local-session",expected=200)
    cookie=headers["set-cookie"].split(";")[0];csrf=json.loads(raw)["csrf_token"]
def get(path):
    h,b=request("GET",path);return h,json.loads(b)
api="/api/agent/v1";result={"scope":"controlled-model-real-listener-localstore-tools-no-production-SQL"}
try:
    start();request("GET",api+"/sessions",expected=401);login()
    op=str(uuid.uuid4());h,b=request("POST",api+"/sessions",{"client_operation_id":op,"title":"ops-controlled","model_alias":"demo"},expected=201)
    sid=json.loads(b)["id"];etag=h["etag"];sp=api+"/sessions/"+sid
    limits={"max_steps":4,"max_model_calls":4,"max_tool_calls":8,"max_duration_ms":10000,"tool_timeout_ms":1000,"max_tool_output_bytes":8192,"max_context_tokens":32768,"no_progress_limit":3,"max_tokens":"100","max_money_atomic":"100","currency":"TST"}
    command=str(uuid.uuid4());h,b=request("POST",sp+"/runs",{"client_operation_id":command,"mode":"agent","operation":"send","text":"6x7 and visible models","referenced_message_id":None,"model_alias":"demo","limits":limits,"tools":[{"name":"bounded_arithmetic","revision":"1"},{"name":"list_visible_models","revision":"1"}]},etag,202)
    rid=json.loads(b)["run"]["id"];rp=sp+"/runs/"+rid
    for _ in range(100):
        _,run=get(rp)
        if run["state"] in ("completed","failed","needs_confirmation","cancelled"):break
        time.sleep(0.03)
    assert run["state"]=="completed",run["state"]
    _,page=get(rp+"/events?page_size=100");events=page["data"]
    assert len(run["child_request_ids"])==2
    assert len(events)>2
    _,snap=get(sp);assert snap["last_event_seq"]==run["last_event_seq"] and snap["resume_cursor"]==run["resume_cursor"]
    h,stream=request("GET",rp+"/events/stream")
    assert h["content-type"].startswith("text/event-stream") and h.get("x-accel-buffering")=="no"
    for event in events:assert ("id: "+event["cursor"]).encode() in stream
    cursor=events[0]["cursor"]
    _,body=request("GET",rp+"/events/stream",extra={"Last-Event-ID":cursor})
    assert events[0]["cursor"].encode() not in body
    request("GET",rp+"/events/stream?after="+cursor,extra={"Last-Event-ID":cursor},expected=400)
    _,again=get(rp);assert again["child_request_ids"]==run["child_request_ids"] and again["last_event_seq"]==run["last_event_seq"]
    stop();oldcookie=cookie;cookie=None;csrf=None
    start();request("GET",sp,expected=401);login();assert cookie!=oldcookie
    _,reopened=get(rp+"/events?page_size=100");assert reopened==page,"persisted envelopes changed"
    _,restored=get(rp);assert restored["child_request_ids"]==run["child_request_ids"] and restored["last_event_seq"]==run["last_event_seq"]
    _,snapshot=get(sp);assert snapshot["resume_cursor"]==snap["resume_cursor"]
    request("POST",rp+"/cancel",expected=202)
    _,aftercancel=get(rp);assert aftercancel["state"]=="completed","terminal cancellation corrupted state"
    request("DELETE","/__maas/local-session",expected=204);request("GET",sp,expected=401)
    result.update(passed=True,sessionId=sid,runId=rid,eventCount=len(events),childCount=2,reopenedEnvelopesIdentical=True,readsDidNotResubmit=True,terminalCancelOnly=True,activeCancelNotTested=True)
finally:
    stop()
    result["listenerStopped"]=proc is None or proc.poll() is not None
    result["lockReleased"]=not (state/".owner-lock").exists()
    (out/"http-metadata.json").write_text(json.dumps(records,indent=2)+"\n")
    (out/"result.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result))