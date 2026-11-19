"""Read-only loopback probe; paths/status come from reviewed contract, not guesses."""
import argparse,json,os,pathlib,urllib.request,urllib.error,urllib.parse
def main():
    p=argparse.ArgumentParser();p.add_argument("plan",type=pathlib.Path);p.add_argument("--output",type=pathlib.Path,required=True);a=p.parse_args()
    plan=json.loads(a.plan.read_text(encoding="utf-8-sig"))
    if not plan.get("contract_approved") or not plan.get("product_sha"):p.error("reviewed contract and fixed product SHA required")
    origin=urllib.parse.urlsplit(plan["base"])
    if origin.scheme not in ("http","https") or origin.hostname not in ("127.0.0.1","localhost","::1") or origin.username or origin.query or origin.fragment or origin.path not in ("","/"):p.error("authorized loopback origin required")
    cookie=os.environ.get("MAAS_QA_SESSION_COOKIE")
    if not cookie:p.error("approved temporary session must be supplied via environment")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    client=urllib.request.build_opener(NoRedirect)
    results=[]
    for case in plan["reads"]:
        path=case["path"]
        if not path.startswith("/") or path.startswith("//") or urllib.parse.urlsplit(path).scheme:p.error("same-origin relative GET paths required")
        req=urllib.request.Request(plan["base"].rstrip("/")+path,headers={"Cookie":cookie,"Accept":"application/json"},method="GET")
        try:
            with client.open(req,timeout=5) as response:status=response.status;response.read(1<<20)
        except urllib.error.HTTPError as err:status=err.code;err.close()
        except OSError:status=0
        results.append({"case":case["id"],"status":status,"expected":case["status"],"passed":status==case["status"]})
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps({"scope":"read status only; not persistence/execution acceptance","results":results},indent=2)+"\n",encoding="utf-8")
    return int(any(not x["passed"] for x in results))
if __name__=="__main__":raise SystemExit(main())
