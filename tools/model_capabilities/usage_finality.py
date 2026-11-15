"""Source-backed offline usage-finality oracle. No authorization, settlement or inference."""
import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
# Reuse complete UTF-8/SSE assembly from the reviewed local tool.
import importlib.util
_spec=importlib.util.spec_from_file_location("maas9_kv_pd",ROOT/"kv_pd.py")
_kv=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_kv)

def read(p):return json.loads(p.read_text(encoding="utf-8-sig"))

def profile_by_id(name):
    return next(x for x in read(ROOT/"finality/profiles.json")["profiles"] if x["id"]==name)

def validate_profile(p):
    if p["approval_status"]!="pending" or p["execution_enabled"] is not False or p["public_override_allowed"] is not False or p["authority"]!="none":raise ValueError("source specimen only")
    if p["usage_semantics"]!="cumulative" or p["supported_choices"]!=1 or p["logical_boundary"]!="DONE_then_accepted_transport_end":raise ValueError("unimplemented source mode")
    if p["final_marker"] not in ["usage_only_after_finish","finish_with_usage"]:raise ValueError("unknown final marker")
    if type(p["allow_progress_usage"]) is not bool:raise ValueError("progress flag")

def path_get(raw,path):
    if path is None:return None
    value=raw
    for key in path.split("."):
        if not isinstance(value,dict):return None
        value=value.get(key)
    return value

def normalized_usage(raw,p):
    if not isinstance(raw,dict):raise ValueError("usage object")
    out={"input_tokens":raw.get("prompt_tokens"),"output_tokens":raw.get("completion_tokens"),"total_tokens":raw.get("total_tokens"),
         "input_cached_tokens":path_get(raw,p["cache_path"]),"reasoning_tokens":path_get(raw,p["reasoning_path"])}
    for value in out.values():
        if value is not None and (type(value) is not int or value<0 or value>9007199254740991):raise ValueError("invalid count")
    i,o,t,c,r=out.values()
    if all(v is not None for v in [i,o,t]) and i+o!=t:raise ValueError("parent contradiction")
    if i is not None and c is not None and c>i:raise ValueError("cache subset")
    if o is not None and r is not None and r>o:raise ValueError("reasoning subset")
    miss=raw.get("prompt_cache_miss_tokens")
    if miss is not None and (type(miss) is not int or miss<0):raise ValueError("cache miss")
    if i is not None and c is not None and miss is not None and c+miss!=i:raise ValueError("cache parents")
    return out

def parent_monotone(old,new):
    return all(old[k] is None or new[k] is None or new[k]>=old[k] for k in ["input_tokens","output_tokens","total_tokens"])

def classify(case,p=None,widths=(1,7,3)):
    p=dict(profile_by_id(case["profile_id"]) if p is None else p)
    result={"status":"profile_rejected","reason":None,"final_usage_candidate":None,"progress_snapshots":0,"final_snapshots":0,"late_observations":0,
            "production_authority":False,"ledger_writes":0,"slot_release_authority":False,"quality_verified":False}
    try:
        validate_profile(p)
        if p["id"]!=case["profile_id"]:raise ValueError("profile identity mismatch")
    except (ValueError,KeyError,TypeError):
        result["reason"]="profile_mode_or_approval_not_supported";return result
    try:
        response=case["response"];binding=case["binding"]
        if response["http_status"]!=200 or response["content_type"]!="text/event-stream":raise ValueError("response framing")
        events=_kv.sse_events(response["sse"].encode(),widths)
        seen_finish=False;seen_done=False;candidate=None;last_progress=None
        for event_type,data in events:
            if seen_done:
                # Logical boundary already observed: a late observation cannot rewrite the candidate.
                result["late_observations"]+=1;continue
            if data=="[DONE]":
                if event_type!="message" or not seen_finish:raise ValueError("DONE before finish")
                seen_done=True;continue
            chunk=json.loads(data)
            if event_type=="error" or "error" in chunk:raise ValueError("upstream error latched")
            if event_type!="message" or not isinstance(chunk,dict):raise ValueError("event type")
            if chunk.get("object")!="chat.completion.chunk" or type(chunk.get("created")) is not int:raise ValueError("chunk framing")
            if chunk.get("id")!=binding["upstream_id"] or chunk.get("model")!=binding["upstream_model"]:raise ValueError("source identity changed")
            choices=chunk.get("choices")
            if not isinstance(choices,list) or len(choices)>1:raise ValueError("single choice required")
            finish=False;content=False
            if choices:
                c=choices[0]
                if type(c.get("index")) is not int or c["index"]!=0 or not isinstance(c.get("delta"),dict):raise ValueError("choice shape")
                f=c.get("finish_reason")
                if f not in [None,"stop","length"]:raise ValueError("unsupported/error finish")
                finish=f is not None
                content=any(c["delta"].get(k) for k in ["content","reasoning_content","tool_calls"])
                if finish and content:raise ValueError("finish marker with new content outside specimen")
                if seen_finish and content:raise ValueError("content after finish")
                if finish:seen_finish=True
            raw=chunk.get("usage")
            if raw is None:continue
            value=normalized_usage(raw,p)
            final_marker=(not choices and seen_finish) if p["final_marker"]=="usage_only_after_finish" else (bool(choices) and finish)
            if final_marker:
                if candidate is not None and value!=candidate:raise ValueError("conflicting final snapshots")
                if last_progress is not None and not parent_monotone(last_progress,value):raise ValueError("final parents decrease")
                candidate=value;result["final_snapshots"]+=1
            else:
                if not choices or finish:raise ValueError("unexpected final framing")
                if candidate is not None:raise ValueError("progress after final before boundary")
                if not p["allow_progress_usage"]:raise ValueError("profile does not declare progress usage")
                if last_progress is not None and not parent_monotone(last_progress,value):raise ValueError("progress parents decrease")
                last_progress=value;result["progress_snapshots"]+=1
        if response["transport_end"] not in ["clean","cancelled","deadline","eof"]:raise ValueError("transport disposition")
        if not seen_done or response["transport_end"]!="clean":
            result.update(status="interrupted",reason="normal_boundary_not_accepted");return result
        if candidate is None or all(v is None for v in candidate.values()):
            result.update(status="usage_unavailable",reason="no_source_final_snapshot");return result
        result.update(status="final_candidate",reason="source_marker_and_boundary_only_not_settlement",final_usage_candidate=candidate);return result
    except (ValueError,UnicodeError,TypeError,KeyError,AttributeError):
        result.update(status="protocol_rejected",reason="invalid_upstream_sequence_or_usage");return result

def terminal_disposition(vector):
    """Pure uniqueness expectation; no database or event consumer execution."""
    if vector["stored_event_id"]==vector["incoming_event_id"] and vector["stored_hash"]==vector["incoming_hash"]:return "idempotent_ack_no_mutation"
    return "conflict_409_no_mutation"

def upstream_usage_probe(tag):
    """Execute only the hash-pinned upstream UsageProcessor class with value-object stubs."""
    name=f"{tag}/usage_processor.py"
    entry=next(x for x in read(ROOT/"finality/source-evidence.json")["files"] if x["file"]==name)
    raw=(ROOT/"finality/source-samples"/(tag+"-usage-processor.py.txt")).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=entry["sha256"]:raise ValueError("upstream specimen changed")
    tree=ast.parse(raw.decode())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="UsageProcessor")
    module=ast.Module(body=[ast.ImportFrom(module="__future__",names=[ast.alias(name="annotations")],level=0),cls],type_ignores=[])
    # No module imports, model objects, top-level code or torch dependencies.
    class Fields:
        def __init__(self,**kwargs):self.values=kwargs
    namespace={"final":lambda x:x,"UsageInfo":Fields,"PromptTokensDetails":Fields}
    exec(compile(ast.fix_missing_locations(module),"<fixed-source-UsageProcessor>","exec"),namespace)
    processor=namespace["UsageProcessor"]
    if tag=="v0.5.6":
        progress=processor.calculate_token_usage(prompt_tokens=12,completion_tokens=5).values
        final=processor.calculate_streaming_usage({0:12},{0:7},{0:4},1,True).values
    else:
        progress=processor.calculate_token_usage(prompt_tokens=12,completion_tokens=5,reasoning_tokens=2).values
        final=processor.calculate_streaming_usage({0:12},{0:3},{0:7},{0:4},1,True).values
    def flatten(value):
        if isinstance(value,Fields):return {k:flatten(v) for k,v in value.values.items()}
        if isinstance(value,dict):return {k:flatten(v) for k,v in value.items()}
        return value
    return {"tag":tag,"progress":flatten(progress),"final":flatten(final),"evidence":"hash_pinned_arithmetic_with_stub_fields_not_engine_execution"}

def feasible_chunks(case):
    """Integer precheck with decode first; not a scheduler or activation-memory model."""
    def number(x):
        if type(x) is not int or x<0:raise ValueError("resource integer")
        return x
    page=number(case["page"])
    if not page:raise ValueError("page size")
    free=number(case["free_pages"])-number(case["inflight_reserved_pages"])
    number(case["protected_pages"])  # reported separately, NEVER added to free capacity
    lengths=[number(x) for x in case["decode_lengths"]]
    decode_pages=sum(_kv.new_pages(x,x+1,page) for x in lengths)
    token_room=number(case["batch_token_budget"])-len(lengths)
    before=number(case["prefill_before"])
    return [number(c) for c in case["candidates"] if number(c)>0 and c<=token_room and _kv.new_pages(before,before+c,page)<=free-decode_pages]

def evaluate(source_root=None):
    checks=[]
    def check(name,passed,scope):checks.append(dict(name=name,passed=bool(passed),scope=scope))
    verdicts=[]
    for case in read(ROOT/"finality/protocol-vectors.json")["cases"]:
        p=dict(profile_by_id(case["profile_id"]));p.update(case.get("profile_override_for_negative_test",{}))
        actual=classify(case,p)
        total=None if actual["final_usage_candidate"] is None else actual["final_usage_candidate"]["total_tokens"]
        check(case["id"]+"/classification",actual["status"]==case["expected"]["status"] and total==case["expected"]["candidate_total_tokens"],"synthetic_protocol_oracle")
        check(case["id"]+"/no_authority",actual["production_authority"] is False and actual["ledger_writes"]==0,"diagnostic_boundary")
        verdicts.append({"id":case["id"],**actual})
    for v in read(ROOT/"finality/terminal-delivery-vectors.json")["cases"]:check(v["id"],terminal_disposition(v)==v["expected"],"terminal_uniqueness_expectation_not_SQL")
    scheduling=read(ROOT/"finality/scheduling-inputs.json")
    check("scheduling/common_engine_pin",scheduling["comparison_engine"]["commit"]==_kv.PIN and scheduling["execution_enabled"] is False,"comparison_input_only")
    for c in scheduling["cases"]:check(c["id"],feasible_chunks(c)==c["expected_feasible"],"integer_feasibility_not_scheduler")
    probes=[upstream_usage_probe(tag) for tag in ["v0.5.6","v0.5.18"]]
    for probe in probes:check(probe["tag"]+"/real_source_arithmetic",probe["progress"]["total_tokens"]==17 and probe["final"]["total_tokens"]==19,"isolated_upstream_function")
    if source_root:
        for entry in read(ROOT/"finality/source-evidence.json")["files"]:
            path=source_root/entry["file"]
            check("source_sha/"+entry["file"],path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==entry["sha256"],"cached_source_integrity")
    return {"version":"0.5","scope":"offline_sources_and_synthetic_vectors","summary":{"total":len(checks),"passed":sum(x["passed"] for x in checks),"failed":sum(not x["passed"] for x in checks)},
            "checks":checks,"verdicts":verdicts,"source_function_probes":probes,"execution_enabled":False,"actual_model_scores":None,
            "not_executed":["real_provider_or_engine_call","Higress_adapter","Go_relay_integration","MySQL_terminal_dedup_or_settlement","production_profile_approval","GPU_or_model_quality_or_performance"]}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--source-root",type=Path);p.add_argument("--output",type=Path);args=p.parse_args()
    try:
        r=evaluate(args.source_root)
        if r["summary"]["failed"]:return 2
        if args.output:
            if args.output.resolve() in {x.resolve() for x in ROOT.rglob("*") if x.is_file()}:raise ValueError("input overwrite")
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_bytes((json.dumps(r,ensure_ascii=False,indent=2)+"\n").encode())
        print(json.dumps(r["summary"]));return 0
    except Exception as exc:
        print("offline finality input rejected: "+type(exc).__name__,file=sys.stderr);return 2
if __name__=="__main__":sys.exit(main())