"""Normal-product authentication persistence smoke; no Session/Run or model execution."""
import argparse, http.cookiejar, json, os, subprocess, time, urllib.request, urllib.error
from pathlib import Path
from urllib.parse import urlsplit
p=argparse.ArgumentParser(description=__doc__)
p.add_argument("--base",required=True);p.add_argument("--password-file",type=Path,required=True)
p.add_argument("--compose",type=Path,required=True);p.add_argument("--project",required=True)
p.add_argument("--restart",action="store_true");p.add_argument("--output",type=Path,required=True)
a=p.parse_args();u=urlsplit(a.base)
if u.username or u.password or u.path not in ("","/") or u.query or u.fragment:raise SystemExit("explicit origin only")
if a.restart and u.hostname not in ("localhost","127.0.0.1","::1"):raise SystemExit("Restart smoke is local-only")
private=json.loads((a.compose.parent/"config/product.json").read_text(encoding="utf-8"))
if private["origin"].rstrip("/")!=a.base.rstrip("/"):raise SystemExit("Compose/config origin differs from requested target")
base=a.base.rstrip("/");csrf=""
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),NoRedirect())
def req(method,path,data=None):
    headers={"Origin":base}
    if csrf:headers["X-CSRF-Token"]=csrf
    if data is not None:headers["Content-Type"]="application/json"
    r=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers,method=method)
    try:response=client.open(r,timeout=5)
    except urllib.error.HTTPError as e:response=e
    with response:
        raw=response.read();return response.status,json.loads(raw) if response.headers.get_content_type()=="application/json" and raw else None
def healthy():
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        try:
            if req("GET","/readyz")[0]==200:return
        except (OSError,urllib.error.URLError):pass
        time.sleep(.5)
    raise RuntimeError("readyz did not recover")
def linux(path):
    path=path.resolve()
    return "/mnt/"+path.drive[0].lower()+"/"+path.relative_to(path.anchor).as_posix() if os.name=="nt" else str(path)
def restart(service):
    prefix=["wsl","-d","Ubuntu-22.04","--exec","docker"] if os.name=="nt" else ["docker"]
    r=subprocess.run(prefix+["compose","-p",a.project,"--project-directory",linux(a.compose.parent),"-f",linux(a.compose),"restart",service],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120)
    if r.returncode:raise RuntimeError("owned Compose restart failed: "+service)
    healthy()
result={"scope":"normal-service-MySQL-login-only-no-model-or-Agent-history","passed":False}
try:
    healthy()
    status,session=req("POST","/api/admin/v1/session",{"username":"admin","password":a.password_file.read_text().strip()})
    if status!=200:raise RuntimeError("normal login failed")
    csrf=session["csrf_token"]
    status,caps=req("GET","/api/agent/v1/capabilities")
    if status!=200:raise RuntimeError("shared Agent identity unavailable")
    result["configuredModels"]=len(caps["model_modes"])
    result["adminId"]=session["admin_id"]
    for service in (("maas","mysql") if a.restart else ()):
        restart(service)
        status,current=req("GET","/api/admin/v1/session")
        if status!=200 or current["admin_id"]!=session["admin_id"] or current["csrf_token"]!=csrf:raise RuntimeError("same login did not survive "+service)
        status,reloaded=req("GET","/api/agent/v1/capabilities")
        if status!=200 or reloaded!=caps:raise RuntimeError("capabilities changed after "+service)
        result[service+"RestartIdentityStable"]=True
    status,_=req("DELETE","/api/admin/v1/session")
    if status!=204 or req("GET","/api/admin/v1/session")[0]!=401:raise RuntimeError("logout persistence failed")
    result["passed"]=True
except Exception as e:
    result["errorType"]=type(e).__name__
    if isinstance(e,RuntimeError):result["reason"]=str(e)
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
print(json.dumps(result));raise SystemExit(0 if result["passed"] else 1)