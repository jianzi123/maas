"""QA normalized evidence format, NOT the product API contract."""
import argparse,json,pathlib,sys
def check(t):
    errors=[]
    def need(ok,msg):
        if not ok:errors.append(msg)
    for key in ("product_sha","contract_version","environment","session_id","run_id","owner"):
        need(bool(t.get(key)),"missing "+key)
    need(t.get("evidence_kind") in ("controlled_model","real_chain","production"),"invalid evidence kind")
    need(t.get("raw_evidence_verified") is True,"raw source association not independently verified")
    events=t.get("events",[]);seen={};seq=0
    for ev in events:
        need(ev.get("session_id")==t.get("session_id") and ev.get("run_id")==t.get("run_id"),"event identity mismatch")
        identity=ev.get("id");need(bool(identity),"missing event ID")
        if identity in seen:
            need(seen[identity]==ev,"same event ID changed")
            continue
        seen[identity]=ev
        n=ev.get("sequence",0);need(isinstance(n,int) and n>seq,"event order invalid");seq=n
    for tool in t.get("tools",[]):
        need(bool(tool.get("call_id")) and bool(tool.get("args_hash")),"tool identity absent")
        n=tool.get("executions",-1)
        need(isinstance(n,int) and 0<=n<=1,"tool duplicate/invalid execution count")
        if not tool.get("authorized") or not tool.get("schema_valid"):
            need(n==0,"unauthorized/malformed tool executed")
        if tool.get("approval_required"):
            need(bool(tool.get("approval_id")),"approval identity absent")
            if tool.get("approval_state")!="approved":need(n==0,"unapproved tool executed")
            if n:
                need(tool.get("approved_args_hash")==tool.get("args_hash") and tool.get("approved_owner")==t.get("owner"),"approval binding mismatch")
        if tool.get("outcome")=="unknown":
            need(tool.get("replayed_after_recovery")==False,"unknown side effect replayed")
        if tool.get("result_fed_to_model"):
            need(n==1 and bool(tool.get("result_event_id")),"tool observation fabricated")
    children=t.get("model_requests",[]);ids=set()
    for child in children:
        rid=child.get("request_id")
        need(bool(rid) and rid not in ids,"duplicate/missing model request ID");ids.add(rid)
        need(child.get("attempts")==1 and child.get("request_rows")==1 and child.get("terminal_rows")==1 and child.get("summary_count")==1,"child request not uniquely settled")
        need(child.get("through_kernel_gateway")==True,"child model bypassed kernel/gateway")
        if child.get("usage_state")=="unknown":
            need(child.get("actual") is None and child.get("held_preserved")==True,"unknown usage invented/refunded")
    need(t.get("parent_business_debits")==0,"parent duplicated business ledger")
    for key in ("step_limit","time_limit_ms","budget_limit","tool_timeout_ms"):
        need(isinstance(t.get("limits",{}).get(key),(int,float)) and not isinstance(t.get("limits",{}).get(key),bool) and t["limits"][key]>0,"missing explicit "+key)
    need(t.get("event_reconnect_model_calls")==0 and t.get("event_reconnect_tool_executions")==0,"event replay caused execution")
    if t.get("edit_or_regenerate"):
        need(bool(t.get("original_message_id")) and bool(t.get("new_message_id")) and t["original_message_id"]!=t["new_message_id"],"message edit/regenerate lost lineage")
    if t.get("final_answer"):
        need(bool(children) and all(x.get("outcome") not in ("unknown","waiting") for x in t.get("tools",[])),"final answer over unresolved execution")
    return errors
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("trace",type=pathlib.Path);p.add_argument("--output",type=pathlib.Path,required=True);a=p.parse_args()
    try:errors=check(json.loads(a.trace.read_text(encoding="utf-8-sig")))
    except (OSError,ValueError,TypeError,KeyError):print("invalid evidence input");return 2
    if errors:
        print(json.dumps({"accepted":False,"errors":errors}));return 2
    if a.output.exists():print("output exists");return 2
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps({"scope":"normalized evidence invariants only","accepted":True,"not_product_acceptance":True},indent=2)+"\n",encoding="utf-8");return 0
if __name__=="__main__":sys.exit(main())
