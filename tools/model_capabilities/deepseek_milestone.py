"""MAAS-18 DeepSeek-only approval checklist and offline compatibility input checks."""
import argparse
import importlib.util
import json
import hashlib
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def load(p):return json.loads(p.read_text(encoding="utf-8-sig"))
def import_local(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
finality=import_local("maas9_deepseek_finality",ROOT/"usage_finality.py")
kv=import_local("maas9_deepseek_quality",ROOT/"kv_pd.py")

def missing_approvals():
    inputs=load(ROOT/"deepseek/approval-inputs.json")
    return [{"card":f["card"],"field":f["field"],"owner":f["owner"],"blocks":f["blocks"]}
            for f in inputs["fields"] if f["approved_value"] is None or f["approval_record_ref"] is None]

def normalized(raw):
    p=finality.profile_by_id("deepseek-chat-document-snapshot")
    u=finality.normalized_usage(raw,p)
    canonical=raw.get("prompt_cache_hit_tokens")
    alias=finality.path_get(raw,"prompt_tokens_details.cached_tokens")
    if alias is not None and (type(alias) is not int or alias<0):raise ValueError("cache alias type")
    if canonical is not None and alias is not None and canonical!=alias:raise ValueError("cache aliases disagree")
    if u["reasoning_tokens"] not in (None,0):raise ValueError("non-thinking mode drift")
    safety=finality.path_get(raw,"completion_tokens_details.safety_tokens")
    if safety is not None and (type(safety) is not int or safety<0 or (u["output_tokens"] is not None and safety>u["output_tokens"])):raise ValueError("safety subset")
    tools=raw.get("server_tool_use")
    if tools is not None:
        if not isinstance(tools,dict) or any(type(v) is not int or v!=0 for v in tools.values()):raise ValueError("unsupported extra billed operation")
    return u

def inspect_case(case):
    result={"id":case["id"],"status":"protocol_rejected","final_usage_candidate":None,
            "real_call_executed":False,"ledger_write_authority":False,"quality_result":None}
    try:
        if case["synthetic"] is not True or case["actual_provider_run"] is not False or case["mode"]!="non-thinking":raise ValueError("controlled mode")
        response=case["response"];binding=case["binding"];kind=response["kind"]
        if response["http_status"]!=200:
            result["status"]="upstream_http_error";return result
        timing=case.get("fixture_timing_ms")
        interrupted=response["transport_end"]!="clean"
        if timing:
            if any(type(timing[k]) is not int or timing[k]<0 for k in ["observed_end","total_deadline"]):raise ValueError("timing")
            interrupted|=timing["observed_end"]>timing["total_deadline"]
        candidate=None;finish=None
        if kind=="json":
            if response["content_type"]!="application/json":raise ValueError("HTTP content type")
            root=json.loads(response["wire"])
            if not isinstance(root,dict) or "error" in root or root.get("object")!="chat.completion":raise ValueError("root")
            if root.get("id")!=binding["upstream_id"] or root.get("model")!=binding["upstream_model"]:raise ValueError("source binding")
            choices=root["choices"]
            if len(choices)!=1 or type(choices[0].get("index")) is not int or choices[0]["index"]!=0:raise ValueError("single choice")
            choice=choices[0];finish=choice["finish_reason"];msg=choice["message"]
            if msg.get("role")!="assistant" or type(msg.get("content")) is not str or any(msg.get(k) for k in ["reasoning_content","tool_calls","server_tool_calls","server_tool_event","annotations","title"]):raise ValueError("text subset")
            if root.get("usage") is not None:candidate=normalized(root["usage"])
        elif kind=="stream":
            if response["content_type"]!="text/event-stream":raise ValueError("HTTP content type")
            done=False;created=None;fingerprint=None
            for event_type,data in kv.sse_events(response["wire"].encode()):
                if done:raise ValueError("data in same source capture after DONE")
                if data=="[DONE]":
                    if event_type!="message" or finish is None:raise ValueError("DONE order")
                    done=True;continue
                chunk=json.loads(data)
                if event_type=="error" or "error" in chunk:raise ValueError("source error")
                if event_type!="message" or chunk.get("object")!="chat.completion.chunk":raise ValueError("source chunk")
                if chunk.get("id")!=binding["upstream_id"] or chunk.get("model")!=binding["upstream_model"]:raise ValueError("source binding")
                if type(chunk.get("created")) is not int or chunk["created"]<0:raise ValueError("created")
                if created is not None and created!=chunk["created"]:raise ValueError("source metadata drift")
                created=chunk["created"]
                fp=chunk.get("system_fingerprint")
                if fp is not None:
                    if not isinstance(fp,str) or (fingerprint is not None and fingerprint!=fp):raise ValueError("fingerprint drift")
                    fingerprint=fp
                choices=chunk["choices"]
                if len(choices)!=1 or type(choices[0].get("index")) is not int or choices[0]["index"]!=0:raise ValueError("single source choice")
                c=choices[0];delta=c["delta"]
                if not isinstance(delta,dict) or delta.get("reasoning_content") or delta.get("tool_calls"):raise ValueError("unsupported mode")
                if "role" in delta and delta["role"] not in (None,"assistant"):raise ValueError("source role")
                if "content" in delta and delta["content"] is not None and type(delta["content"]) is not str:raise ValueError("source text")
                if any(delta.get(k) for k in ["server_tool_calls","server_tool_event","annotations","title"]):raise ValueError("undeclared extension")
                if finish is not None:raise ValueError("second finish or content after finish")
                finish=c.get("finish_reason")
                raw=chunk.get("usage")
                if finish is None:
                    if raw is not None:raise ValueError("provider profile does not declare progress usage")
                else:
                    if delta.get("content"):raise ValueError("finish has new content")
                    if raw is not None:candidate=normalized(raw)
            if not done:interrupted=True
        else:raise ValueError("kind")
        if finish is not None and finish not in ["stop","length"]:raise ValueError("error finish")
        if interrupted:
            result["status"]="interrupted";return result
        if finish is None:raise ValueError("missing finish")
        if candidate is None or all(v is None for v in candidate.values()):
            result["status"]="usage_unavailable";return result
        result.update(status="final_candidate_quality_truncated" if finish=="length" else "final_candidate",final_usage_candidate=candidate)
        return result
    except (ValueError,KeyError,TypeError,AttributeError,UnicodeError):
        return result

def evaluate(source_root=None):
    checks=[];results=[]
    def check(name,passed,scope):checks.append({"name":name,"passed":bool(passed),"scope":scope})
    inputs=load(ROOT/"deepseek/approval-inputs.json");proposal=load(ROOT/"deepseek/candidate-review.json")
    check("retained_34_EXT_fields",len(inputs["fields"])==34 and len({(x["card"],x["field"]) for x in inputs["fields"]})==34,"checklist_integrity")
    check("no_pending_approval_promoted",proposal["execution_enabled"] is False and proposal["approved_model"] is None and proposal["bound_verified"] is False and proposal["price_snapshot"] is None,"approval_boundary")
    for case in load(ROOT/"deepseek/protocol-vectors.json")["cases"]:
        result=inspect_case(case);results.append(result)
        check(case["id"],result["status"]==case["expected"],"synthetic_source_protocol")
    quality=load(ROOT/"deepseek/minimum-quality.json")
    for c in quality["cases"]:
        check(c["id"]+"/gold",kv.quality_pass(c["id"],c["gold"]),"quality_method_only")
        check(c["id"]+"/length_not_scored",not kv.quality_pass(c["id"],c["gold"],"length"),"quality_method_only")
    sources=load(ROOT/"deepseek/document-evidence.json")["sources"]
    if source_root:
        for src in sources:
            if src["status"]=="captured":
                p=source_root/(src["id"]+".html")
                check("document_sha/"+src["id"],p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==src["sha256"],"official_document_integrity_not_account_validation")
    return {"version":"0.7","milestone":"MAAS-18","summary":{"total":len(checks),"passed":sum(c["passed"] for c in checks),"failed":sum(not c["passed"] for c in checks)},
            "checks":checks,"source_case_results":results,"missing_approval_inputs":missing_approvals(),"real_execution_enabled":False,
            "actual_model_scores":None,"joint_adapter_approval":"pending_architecture_backend_QA_and_member_inputs",
            "not_executed":["supplier_API_or_account_metadata","Secret_access","Go_Higress_real_adapter","MySQL_finalization_or_cancel_integration","browser_model_quality","production_or_target_deployment"]}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--source-root",type=Path);p.add_argument("--output",type=Path);p.add_argument("--require-approved-inputs",action="store_true");args=p.parse_args()
    try:
        report=evaluate(args.source_root)
        if report["summary"]["failed"] or args.require_approved_inputs:
            print("offline check failed or real source approval remains pending",file=sys.stderr);return 2
        if args.output:
            if args.output.resolve() in {x.resolve() for x in ROOT.rglob("*") if x.is_file()}:raise ValueError("input overwrite")
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+"\n").encode())
        print(json.dumps(report["summary"]));return 0
    except Exception as exc:
        print("DeepSeek input rejected: "+type(exc).__name__,file=sys.stderr);return 2
if __name__=="__main__":sys.exit(main())