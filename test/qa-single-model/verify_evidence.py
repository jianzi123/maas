"""Read-only QA oracle for a future single-model run; never sends model requests."""
import argparse,json,pathlib,sys
SCENARIOS=("publish","key_budget","stream","cancel","upstream_error","original_id","known_usage","unknown_usage","quota","revoked","duplicate_terminal")
def verify(m):
    errors=[]
    required=("backend_sha","frontend_sha","deployment_digest","profile_revision","model","source_id","price_revision","environment","evidence_kind")
    for key in required:
        if not m.get(key):errors.append("missing manifest identity: "+key)
    if m.get("evidence_kind") not in ("controlled","real_upstream","production"):errors.append("invalid evidence_kind")
    cases=m.get("cases",{})
    for name in SCENARIOS:
        c=cases.get(name,{})
        if c.get("status")!="PASS":errors.append(name+": not executed/pass");continue
        if not c.get("raw_evidence"):errors.append(name+": missing raw evidence")
        if name=="publish":
            if not c.get("operation_id") or not c.get("cr_uid") or not c.get("publication_id"):errors.append(name+": missing release identity")
            if c.get("actual_gateway_route") is not True or c.get("validation_verified") is not True:errors.append(name+": 202/CR state is not Callable evidence")
            continue
        if name=="key_budget":
            if not c.get("key_id") or c.get("explicit_budget") is not True or c.get("secret_redacted") is not True:errors.append(name+": invalid key evidence")
            continue
        if not c.get("request_id"):errors.append(name+": missing original request ID")
        if c.get("fixed_source") is not True:errors.append(name+": source not verified")
        if name in ("quota","revoked"):
            if c.get("upstream_attempts")!=0 or c.get("business_reservations")!=0:errors.append(name+": rejected request dispatched/reserved")
            continue
        if c.get("upstream_attempts")!=1:errors.append(name+": missing/duplicate generation")
        if c.get("request_rows")!=1 or c.get("terminal_rows")!=1 or c.get("summary_count")!=1:errors.append(name+": nonunique durable accounting")
        if name in ("cancel","upstream_error"):
            if c.get("normal_done") is not False:errors.append(name+": normal DONE on failure")
            if not c.get("termination_reason"):errors.append(name+": missing termination")
        if name=="stream" and (c.get("normal_done_count")!=1 or c.get("terminal_committed_before_done") is not True):errors.append(name+": DONE/commit order")
        if name=="original_id" and (c.get("lookup_request_id")!=c.get("request_id") or c.get("lookup_rows")!=1 or c.get("query_writes")!=0):errors.append(name+": lookup identity/write mismatch")
        if name=="known_usage":
            if c.get("finality_verified") is not True or c.get("token_actual") is None or c.get("matched_price_revision")!=m.get("price_revision"):errors.append(name+": snapshot is not authoritative usage")
        if name=="unknown_usage":
            if c.get("token_actual") is not None or c.get("money_actual") is not None or c.get("held_preserved") is not True or c.get("slot_release_changed_finance") is not False:errors.append(name+": unknown became zero/refund")
        if name=="duplicate_terminal" and c.get("replayed_event_same_hash") is not True:errors.append(name+": missing replay proof")
    return errors
def main():
    p=argparse.ArgumentParser();p.add_argument("manifest",type=pathlib.Path);p.add_argument("--output",type=pathlib.Path,required=True);a=p.parse_args()
    m=json.loads(a.manifest.read_text(encoding="utf-8-sig"))
    errs=verify(m)
    report={"kind":"offline_evidence_oracle_only","accepted":not errs,"errors":errs,"evidence_kind":m.get("evidence_kind"),"not_production_acceptance":True}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"accepted":not errs,"missing_or_failed":len(errs)}));return 2 if errs else 0
if __name__=="__main__":sys.exit(main())
