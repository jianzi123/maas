"""Model-specific offline page/quality/protocol inputs. Not a KV allocator or scheduler."""
import argparse
import ast
import codecs
import hashlib
import json
import re
import sys
from pathlib import Path
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parent
PIN="7ae368efde14f0b2abe769a5fbb99b8154b2a9b7"
MODEL_PIN="916b56a44061fd5cd7d6a8fb632557ed4f724f60"

def read(path):return json.loads(path.read_text(encoding="utf-8-sig"))

def nat(value,positive=False):
    if type(value) is not int or value<(1 if positive else 0):raise ValueError("integer required")
    return value

def pages(tokens,page):return (nat(tokens)+nat(page,True)-1)//page

def new_pages(before,after,page):
    if nat(after)<nat(before):raise ValueError("sequence decreased")
    return pages(after,page)-pages(before,page)

def aligned_prefix(prefix,page):return nat(prefix)//nat(page,True)*page

def kv_bytes_per_token(model):
    if model["kv_layout"]!="GQA" or model["tp"]!=1 or model["kv_dtype"]!="bfloat16":raise ValueError("TP1 BF16 GQA only")
    return 2*nat(model["layers"],True)*nat(model["kv_heads"],True)*nat(model["head_dim"],True)*nat(model["bytes_per_element"],True)

def pooled_envelope(input_tokens,output_cap,shared_prefix,requests,page):
    """Same exact full-page prefix reused in one group. No actual cache hit claim."""
    nat(input_tokens,True);nat(output_cap,True);nat(requests,True)
    if not 0<=nat(shared_prefix)<=input_tokens:raise ValueError("prefix")
    aligned=aligned_prefix(shared_prefix,page)
    return aligned//page+requests*pages(input_tokens+output_cap-aligned,page)

def validate_plan(plan):
    if plan["execution_enabled"] is not False or plan["synthetic"] is not True or plan["approval_status"]!="pending":raise ValueError("pending controlled inputs only")
    if plan["comparison_engine"]["commit"]!=PIN or plan["comparison_engine"]["tag"]!="v0.5.6":raise ValueError("comparison version")
    m=plan["model"]
    if m["id"]!="deepseek-ai/DeepSeek-R1-Distill-Qwen-7B" or m["revision"]!=MODEL_PIN:raise ValueError("model revision")
    kv_bytes_per_token(m)
    if plan["context"]["verified_service_tokens"] is not None:raise ValueError("unverified context")
    if any(plan["feature_scope"][x] for x in ["speculative_decoding","PD_disaggregation","HiCache_offload","hybrid_SWA_MLA_MoE"]):raise ValueError("feature scope")
    if not 1<=len(plan["shapes"])<=64 or len({x["id"] for x in plan["shapes"]})!=len(plan["shapes"]):raise ValueError("shapes")
    for p in plan["page_sizes"]:
        nat(p,True)
        if p>65536 or p&(p-1):raise ValueError("bounded power-of-two page")
    for x in plan["shapes"]:
        for key in ["input_tokens","output_cap_tokens"]:
            if nat(x[key],True)>1000000:raise ValueError("shape bound")
        if not 0<=nat(x["shared_prefix_tokens"])<=x["input_tokens"]:raise ValueError("prefix bound")
    return plan

def shape_report(plan):
    validate_plan(plan);out=[];token_bytes=kv_bytes_per_token(plan["model"])
    for p in plan["page_sizes"]:
        for x in plan["shapes"]:
            i,o,h=x["input_tokens"],x["output_cap_tokens"],x["shared_prefix_tokens"];horizon=i+o
            out.append({"shape":x["id"],"page_tokens":p,"kv_bytes_per_token_geometry_only":token_bytes,"page_bytes_geometry_only":p*token_bytes,
                "conservative_full_envelope_pages":pages(horizon,p),"max_committed_if_no_overallocation_pages":pages(horizon-1,p),
                "prefix_reusable_full_page_tokens":aligned_prefix(h,p),"prefix_tail_recompute_tokens":h-aligned_prefix(h,p),
                "two_requests_same_prefix_full_envelope_pages":pooled_envelope(i,o,h,2,p),
                "fits_previous_4096_proposal":horizon<=plan["context"]["previous_service_proposal"],
                "runtime_context_verified":False,"GPU_memory_or_throughput_result":None})
    return out

def quality_pass(case_id,answer,finish_reason="stop"):
    """Gold-sample check. Never executes generated code or grades hidden reasoning."""
    if type(answer) is not str or finish_reason!="stop":return False
    text=answer.strip()
    if case_id=="Q01":return text=="391" or bool(re.fullmatch(r"\\boxed\{391\}",text))
    if case_id=="Q02":
        try:return json.loads(text)=={"order_id":"A-17","quantity":3}
        except (ValueError,TypeError):return False
    if case_id=="Q03":return text=="青杉"
    if case_id=="Q04":return any(x in text for x in ["资料不足","未披露","无法确定","未提供"]) and not re.search(r"\d",text)
    if case_id=="Q05":return text=="蓝色"
    if case_id=="Q06":return "猫🙂GPU-7" in text
    if case_id=="Q08":return text=="42"
    if case_id=="Q07":
        fence=chr(96)*3
        if text.startswith(fence+"python\n") and text.endswith("\n"+fence):text=text[10:-4]
        try:
            tree=ast.parse(text)
            if len(tree.body)!=1 or not isinstance(tree.body[0],ast.FunctionDef):return False
            f=tree.body[0]
            if f.name!="double" or f.decorator_list or f.returns or len(f.body)!=1:return False
            a=f.args
            if len(a.args)!=1 or a.args[0].arg!="x" or a.args[0].annotation or a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults:return False
            ret=f.body[0]
            if not isinstance(ret,ast.Return) or not isinstance(ret.value,ast.BinOp) or not isinstance(ret.value.op,ast.Mult):return False
            pair=(ret.value.left,ret.value.right)
            return any(isinstance(a,ast.Constant) and type(a.value) is int and a.value==2 and isinstance(b,ast.Name) and b.id=="x" for a,b in [pair,pair[::-1]])
        except (SyntaxError,ValueError,TypeError):return False
    raise ValueError("unknown quality case")

def sse_events(raw,widths=(1,7,3)):
    if not widths or any(type(x) is not int or x<=0 for x in widths):raise ValueError("fragment widths")
    if len(raw)>4*1024*1024:raise ValueError("offline capture size")
    decoder=codecs.getincrementaldecoder("utf-8")();text="";offset=0;idx=0
    while offset<len(raw):
        width=widths[idx%len(widths)];text+=decoder.decode(raw[offset:offset+width]);offset+=width;idx+=1
    text+=decoder.decode(b"",final=True);text=text.replace("\r\n","\n")
    if not text.endswith("\n\n"):raise ValueError("incomplete event")
    events=[]
    for block in text.split("\n\n"):
        if len(block)>262144:raise ValueError("event size")
        data=[];kind="message"
        for line in block.splitlines():
            if line.startswith("event:"):kind=line[6:].strip()
            if line.startswith("data:"):data.append(line[5:].lstrip(" "))
        if data:events.append((kind,"\n".join(data)))
    return events

def public_stream_outcome(raw,widths=(1,7,3)):
    """Public shape only; never evidence of accounting commit or engine exit."""
    api=read(ROOT/"evidence/current-openapi.json")
    def validator(name):return Draft202012Validator({"$ref":"#/components/schemas/"+name,"components":api["components"]})
    chunk=validator("ChatChunk");error=validator("Error")
    try:
        events=sse_events(raw,widths);finish=False;failed=False;done=False;identity=None
        for index,(kind,data) in enumerate(events):
            if done or failed:return "invalid"
            if data=="[DONE]":
                if kind!="message" or not finish or index!=len(events)-1:return "invalid"
                done=True;continue
            value=json.loads(data)
            if kind=="error":
                if not error.is_valid(value):return "invalid"
                failed=True
            elif kind=="message":
                if not chunk.is_valid(value):return "invalid"
                key=(value["id"],value["model"])
                if identity is not None and identity!=key:return "invalid"
                identity=key
                if finish and any(c["delta"] or c["finish_reason"] is not None for c in value["choices"]):return "invalid"
                if any(c["finish_reason"] is not None for c in value["choices"]):finish=True
            else:return "invalid"
        return "error_shape_only" if failed else "completed_shape_only" if done else "invalid"
    except (UnicodeError,ValueError,KeyError,TypeError):return "invalid"

def evaluate(plan,source_root=None):
    validate_plan(plan);inputs=ROOT/"experiments";checks=[]
    def check(name,ok):checks.append({"name":name,"passed":bool(ok)})
    v=read(inputs/"page-vectors.json")
    for idx,x in enumerate(v["new_page_cases"]):check("page_boundary_"+str(idx),new_pages(x["before"],x["after"],x["page"])==x["expected"])
    for idx,x in enumerate(v["shared_prefix_cases"]):
        aligned=aligned_prefix(x["prefix"],x["page"]);check("prefix_alignment_"+str(idx),aligned==x["reusable_tokens"] and x["prefix"]-aligned==x["recompute_tail"])
    rows=shape_report(plan)
    for shape,want in v["expected_full_envelope_pages_at_16"].items():check("shape_envelope_"+shape,next(x for x in rows if x["shape"]==shape and x["page_tokens"]==16)["conservative_full_envelope_pages"]==want)
    check("geometry_57344",kv_bytes_per_token(plan["model"])==v["bytes_per_kv_token"])
    check("shared_M_once",pooled_envelope(2048,256,1536,2,16)==v["two_M_shared_envelope_pages"])
    check("private_M_twice",pooled_envelope(2048,256,0,2,16)==v["two_M_private_envelope_pages"])
    for q in read(inputs/"quality-gold.json")["gold"]:check(q["id"]+"_gold_sample",quality_pass(q["id"],q["answer"]))
    for c in read(inputs/"protocol-vectors.json")["cases"]:check(c["id"]+"_public_sse",public_stream_outcome(c["wire"].encode())==c["expected"])
    source=read(inputs/"sglang-v0.5.6-source-map.json")
    check("source_pin_matches_perf",source["engine_commit"]==PIN and sum(x.get("matches_perf_evidence") is True for x in source["files"])==8)
    if source_root:
        for x in source["files"]:
            path=source_root/x["path"];check("source_sha_"+x["path"],path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==x["sha256"])
    return {"report_version":"0.4","evidence_kind":"synthetic_inputs_and_fixed_source_audit","real_execution_allowed":False,
        "comparison_engine":plan["comparison_engine"],"model":plan["model"],"shape_analysis":rows,"checks":checks,
        "summary":{"total":len(checks),"passed":sum(x["passed"] for x in checks),"failed":sum(not x["passed"] for x in checks)},
        "quality_scope":"synthetic_gold_method_checks_only","actual_model_scores":None,"execution_enabled":False,
        "blocks":plan["blocks"],"not_executed":["SGLang_or_tokenizer_import","actual_KV_allocator_or_scheduler","CUDA_stream_order","GPU_model_quality","runtime_cancellation","same_group_capacity","platform_or_model_performance"]}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--plan",type=Path,default=ROOT/"experiments/kv-pd-v0.4.json")
    p.add_argument("--source-root",type=Path);p.add_argument("--output",type=Path);p.add_argument("--require-runtime",action="store_true");args=p.parse_args()
    try:
        report=evaluate(read(args.plan),args.source_root)
        if args.require_runtime or report["summary"]["failed"]:return 2
        if args.output:
            if args.output.resolve()==args.plan.resolve() or args.output.resolve() in {x.resolve() for x in ROOT.rglob("*") if x.is_file()}:raise ValueError("input overwrite")
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+"\n").encode())
        print(json.dumps(report["summary"]));return 0
    except Exception as exc:
        print("offline input rejected: "+type(exc).__name__,file=sys.stderr);return 2
if __name__=="__main__":sys.exit(main())