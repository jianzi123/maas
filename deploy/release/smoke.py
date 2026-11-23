"""Same-origin offline-demo smoke; create then read-only verify after service/MySQL restart."""
import argparse, copy, hashlib, http.cookiejar, json, time, urllib.request, urllib.error, uuid
from pathlib import Path
from urllib.parse import urlsplit
p=argparse.ArgumentParser(description=__doc__)
p.add_argument("--base",required=True)
p.add_argument("--password-file",required=True,type=Path)
p.add_argument("--username",default="admin")
p.add_argument("--model",default="offline-controlled")
p.add_argument("--limits-file",type=Path)
p.add_argument("--phase",choices=["create","verify"],required=True)
p.add_argument("--record",required=True,type=Path)
p.add_argument("--output",required=True,type=Path)
p.add_argument("--offline-demo",action="store_true",required=True,help="Only use with the explicitly configured offline demo, never a real provider")
a=p.parse_args()
u=urlsplit(a.base)
if u.scheme not in ("http","https") or not u.netloc or u.username or u.password or u.path not in ("","/") or u.query or u.fragment:raise SystemExit("Explicit installed origin only")
if a.phase=="create" and a.record.exists():raise SystemExit("Existing record: inspect original session/command; create never overwrites/replays it")
base=a.base.rstrip("/")
jar=http.cookiejar.CookieJar()
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar),NoRedirect())
csrf="";checks=[]
def request(method,path,body=None,etag=None,status=200):
    h={"Origin":base,"Accept":"application/json"}
    if csrf:h["X-CSRF-Token"]=csrf
    if etag:h["If-Match"]=etag
    data=json.dumps(body).encode() if body is not None else None
    if data:h["Content-Type"]="application/json"
    req=urllib.request.Request(base+path,data=data,headers=h,method=method)
    try:
        reply=client.open(req,timeout=35)
    except urllib.error.HTTPError as e:reply=e
    with reply:
        raw=reply.read(2<<20);headers=reply.headers
        if reply.status!=status:raise RuntimeError("HTTP "+str(reply.status)+" for "+method+" "+path)
    checks.append({"method":method,"path":path,"status":status})
    return headers,raw
def get(path):
    h,b=request("GET",path);return h,json.loads(b)
def hash_json(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
api="/api/agent/v1"
try:
    if a.phase=="verify":
        record=json.loads(a.record.read_text(encoding="utf-8"))
        if record.get("pendingCommand") or record.get("pendingApproval") or not isinstance(record.get("runs"),list) or not record["runs"]:
            raise RuntimeError("Incomplete smoke record: inspect original commands; no business records verified")
        for saved in record["runs"]:
            if not saved.get("children") or len(saved["children"])!=len(saved.get("usageHashes",[])) or saved.get("state","completed") not in ("completed","cancelled"):
                raise RuntimeError("Incomplete smoke record: original child usage and terminal state required")
    request("GET","/healthz")
    _,ready=get("/readyz")
    if ready.get("profile")!="offline-controlled" or ready.get("persistence")!="mysql":raise RuntimeError("normal MySQL offline profile required; no model POST sent")
    h,b=request("POST","/api/admin/v1/session",{"username":a.username,"password":a.password_file.read_text().strip()})
    csrf=json.loads(b)["csrf_token"]
    if a.phase=="create":
        _,cap=get(api+"/capabilities")
        selected=next((m for m in cap["model_modes"] if m["model_alias"]==a.model),None)
        if selected is None:raise RuntimeError("demo model absent")
        if selected.get("approval_state") not in ("controlled","offline-demo"):raise RuntimeError("offline smoke refuses a real or unmarked provider")
        if a.limits_file:
            installed=json.loads(a.limits_file.read_text(encoding="utf-8"))
        else:
            _,installed=get("/console-config.json")
        if installed.get("schema_version")!="maas.console/1" or installed.get("chat",{}).get("enabled") is not True or not isinstance(installed["chat"].get("limits"),dict):
            raise RuntimeError("enabled same-version public installation limits required before any model command")
        installed_limits=installed["chat"]["limits"]
        creation=str(uuid.uuid4())
        a.record.parent.mkdir(parents=True,exist_ok=True)
        record={"creationOperationId":creation,"runs":[]}
        a.record.write_text(json.dumps(record,indent=2)+"\n")
        h,b=request("POST",api+"/sessions",{"client_operation_id":creation,"title":"Installer offline demo","model_alias":a.model},status=201)
        sid=json.loads(b)["id"];sp=api+"/sessions/"+sid;runs=[]
        record["sessionId"]=sid
        a.record.write_text(json.dumps(record,indent=2)+"\n")
        for mode in ("chat","agent"):
            _,snap=get(sp);etag='"'+snap["conversation"]["revision"]+'"'
            limits=copy.deepcopy(installed_limits)
            if mode=="chat":limits.update(max_model_calls=1,max_tool_calls=0)
            op=str(uuid.uuid4())
            body={"client_operation_id":op,"mode":mode,"operation":"send","text":"6 times 7 and list visible models" if mode=="agent" else "Hello from the MySQL installer","referenced_message_id":None,"model_alias":a.model,"limits":limits,"tools":[] if mode=="chat" else [{"name":"bounded_arithmetic","revision":"1"},{"name":"list_visible_models","revision":"1"}]}
            record["pendingCommand"]={"client_operation_id":op,"bodyHash":hash_json(body)}
            a.record.write_text(json.dumps(record,indent=2)+"\n")
            _,b=request("POST",sp+"/runs",body,etag,status=202);rid=json.loads(b)["run"]["id"];rp=sp+"/runs/"+rid
            record["pendingCommand"]["run_id"]=rid
            a.record.write_text(json.dumps(record,indent=2)+"\n")
            decisions=set();deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                _,run=get(rp)
                if run["state"]=="waiting_approval":
                    _,page=get(rp+"/events?page_size=100")
                    for event in page["data"]:
                        if event["type"]!="approval.required":continue
                        approval=event["data"]
                        if approval["id"] in decisions:continue
                        if approval["tool_name"] not in ("bounded_arithmetic","list_visible_models"):raise RuntimeError("unapproved extension tool")
                        decision={"decision_id":str(uuid.uuid4()),"decision":"allow","args_sha256":approval["args_sha256"],"tool_revision":approval["tool_revision"],"policy_revision":approval["policy_revision"]}
                        record["pendingApproval"]={"id":approval["id"],"decision_id":decision["decision_id"]}
                        a.record.write_text(json.dumps(record,indent=2)+"\n")
                        request("POST",rp+"/approvals/"+approval["id"]+"/decision",decision,status=200)
                        decisions.add(approval["id"])
                if run["state"] in ("completed","failed","needs_confirmation","cancelled"):break
                time.sleep(0.1)
            if run["state"]!="completed":raise RuntimeError(mode+" did not complete")
            _,events=get(rp+"/events?page_size=100")
            _,sse=request("GET",rp+"/events/stream")
            for e in events["data"]:
                if ("id: "+e["cursor"]).encode() not in sse:raise RuntimeError("SSE cursor mismatch")
            _,tools=get(rp+"/tool-calls?page_size=100")
            if mode=="agent" and {t["name"] for t in tools["data"]}!={"bounded_arithmetic","list_visible_models"}:raise RuntimeError("two safe tools not executed")
            # Re-submit the SAME command and stale ETag: only original run may return.
            _,again=request("POST",sp+"/runs",body,etag,status=202)
            if json.loads(again)["run"]["id"]!=rid:raise RuntimeError("idempotent POST created another run")
            usages=[]
            for child in run["child_request_ids"]:
                _,row=get("/api/admin/v1/usage/requests?request_id="+child)
                if len(row["data"])!=1:raise RuntimeError("authoritative child usage unavailable")
                usages.append(hash_json(row["data"]))
            runs.append({"id":rid,"mode":mode,"eventsHash":hash_json(events),"toolsHash":hash_json(tools),"children":run["child_request_ids"],"usageHashes":usages,"lastSeq":run["last_event_seq"]})
            record["runs"]=runs
            record.pop("pendingCommand",None)
            record.pop("pendingApproval",None)
            a.record.write_text(json.dumps(record,indent=2)+"\n")
    else:
        sid=record["sessionId"];sp=api+"/sessions/"+sid
        for saved in record["runs"]:
            rp=sp+"/runs/"+saved["id"]
            _,run=get(rp);_,events=get(rp+"/events?page_size=100");_,tools=get(rp+"/tool-calls?page_size=100")
            if run["state"]!=saved.get("state","completed") or run["child_request_ids"]!=saved["children"] or run["last_event_seq"]!=saved["lastSeq"]:raise RuntimeError("run changed after restart")
            if hash_json(events)!=saved["eventsHash"] or hash_json(tools)!=saved["toolsHash"]:raise RuntimeError("history changed after restart")
            for child,want in zip(saved["children"],saved["usageHashes"]):
                _,row=get("/api/admin/v1/usage/requests?request_id="+child)
                if hash_json(row["data"])!=want:raise RuntimeError("usage changed after restart")
    request("DELETE","/api/admin/v1/session",status=204)
    csrf=""
    result={"passed":True,"phase":a.phase,"checks":checks,"scope":"explicit-offline-demo-MySQL-product","sessionId":sid}
except Exception as e:
    result={"passed":False,"phase":a.phase,"checks":checks,"errorType":type(e).__name__,"reason":str(e) if isinstance(e,RuntimeError) else "transport-or-input-failed"}
if csrf:
    try:request("DELETE","/api/admin/v1/session",status=204)
    except Exception:pass
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps({k:v for k,v in result.items() if k!="checks"}))
raise SystemExit(0 if result["passed"] else 1)
