"""Offline v0.24 representativeness audit. Never imports torch or starts collectors."""
import argparse,csv,hashlib,io,json,statistics,sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
from cadence_protocol import digest,write_json
from reference_protocol import load,match,stratum

PARTS=("bookkeeping","boundary_io","unresolved_prefix","prepare","pre_query","query","post_query_or_wait")
def ensure(condition,message):
    if not condition:raise ValueError(message)

def decompose(row,previous,query,archive,root_done,clock):
    ensure(row["clock_scope"]==clock,"row clock")
    ensure(row["status"]=="measured" and row["calls_completed"]==10,"measured row")
    expected_done=previous["done_ns"] if previous else root_done
    ensure(row["previous_done_ns"]==expected_done and row["previous_id"]==(previous["id"] if previous else None),"continuous previous_done")
    times=[row[k] for k in ("previous_done_ns","prepare_begin_ns","ready_ns","submit_ns","enqueue_ns","done_ns","bookkeeping_end_ns")]
    ensure(all(isinstance(t,int) and not isinstance(t,bool) for t in times) and times==sorted(times),"timestamp order")
    before=row["prepare_begin_ns"]-row["previous_done_ns"]
    bookkeeping=previous["bookkeeping_end_ns"]-previous["done_ns"] if previous else 0
    archive_ns=0
    if row["role"]=="boundary_first":
        ensure(archive is not None and archive["id"]==row["io_id"],"boundary IO required")
        ensure(archive["clock_scope"]==clock and archive["reason"]=="pair-boundary","IO identity")
        ensure(expected_done+bookkeeping<=archive["begin_ns"]<=archive["end_ns"]<=row["prepare_begin_ns"],"IO nested/order")
        ensure(previous["id"] in archive["row_ids"],"previous row checkpoint")
        archive_ns=archive["end_ns"]-archive["begin_ns"]
    else:ensure(archive is None and row["io_id"] is None,"unexpected IO")
    ensure(0<=bookkeeping<=before and bookkeeping+archive_ns<=before,"prefix nesting")
    pre_query=query_ns=0
    if row["mode"]=="query":
        ensure(query is not None and query["id"]==row["query_id"] and query["row_id"]==row["id"],"query link")
        ensure(query["clock_scope"]==clock,"query clock")
        ensure(row["ready_ns"]<=query["begin_ns"]<=query["end_ns"]<=row["submit_ns"],"query nested/order")
        ensure(query["result"]["returncode"]==0,"query failed")
        pre_query=query["begin_ns"]-row["ready_ns"];query_ns=query["end_ns"]-query["begin_ns"]
        post=row["submit_ns"]-query["end_ns"]
    else:
        ensure(query is None and row["query_id"] is None,"unexpected query")
        post=row["submit_ns"]-row["ready_ns"]
    parts=dict(bookkeeping=bookkeeping,boundary_io=archive_ns,unresolved_prefix=before-bookkeeping-archive_ns,
               prepare=row["ready_ns"]-row["prepare_begin_ns"],pre_query=pre_query,query=query_ns,post_query_or_wait=post)
    gap=row["submit_ns"]-row["previous_done_ns"]
    ensure(sum(parts.values())==gap,"disjoint accounting")
    result={k:row[k] for k in ("id","phase","scope","batch","variant","role","mode","pair","cell","qualify","clock_scope","previous_id")}
    result.update({k+"_ns":v for k,v in parts.items()})
    result.update(gap_ns=gap,before_prepare_ns=before,
       ready_to_submit_ns=row["submit_ns"]-row["ready_ns"],
       host_enqueue_ns=row["enqueue_ns"]-row["submit_ns"],host_hot_wall_ns=row["done_ns"]-row["submit_ns"],
       stream_event_ns=row["event_ns"],thread_CPU_ns=row["thread_CPU_ns"],
       process_elapsed_ns=row["submit_ns"]-root_done,previous_mode=previous["mode"] if previous else "boot",
       root_bookkeeping_unobserved=previous is None,arithmetic_residual_ns=gap-sum(parts.values()),
       event_is_kernel_sum=False,physical_GPU_idle_known=False)
    return result

def summary(rows,field):
    values=[r[field] for r in rows]
    return {"n":len(values),"sum_ns":sum(values),"min_ns":min(values),"median_ns":statistics.median(values),
            "mean_ns":float(Fraction(sum(values),len(values))),"max_ns":max(values)}

def delta(refs,holds,field):
    return Fraction(sum(r[field] for r in holds),len(holds))-Fraction(sum(r[field] for r in refs),len(refs))

def verify_inputs(source,manifest):
    checks={}
    for rel,expected in manifest["files"].items():
        p=(source/rel).resolve()
        ensure(p.is_relative_to(source.resolve()),"manifest escaped source")
        data=p.read_bytes();sha=hashlib.sha256(data).hexdigest()
        ensure(sha==expected["sha256"] and len(data)==expected["bytes"],"input hash "+rel)
        checks[rel]=sha
    return checks

def audit(source):
    source=Path(source);manifest=json.loads((source/"evidence-manifest.json").read_text())
    before=verify_inputs(source,manifest);plan=load(source/"plan.json")
    ensure(manifest["execution_commit"]==plan["checkout"],"execution identity")
    window=source/"window"
    rows=[json.loads(s) for s in (window/"ledger.jsonl").read_text().splitlines()]
    ensure(len(rows)==128 and len({r["id"] for r in rows})==128,"128 unique denominator")
    ensure([r["id"] for r in rows]==[r["id"] for r in plan["rows"]],"frozen row order")
    runtime=json.loads((window/"runtime-manifest.json").read_text());clock=runtime["clock_scope"]
    bank=json.loads((window/"frozen-targets.json").read_text())
    ensure(bank["plan_sha256"]==digest(plan) and runtime["plan_sha256"]==digest(plan),"plan binding")
    qs=json.loads((window/"queries.json").read_text());ios=json.loads((window/"io-events.json").read_text())
    qmap={q["id"]:q for q in qs};imap={i["id"]:i for i in ios}
    ensure(len(qmap)==len(qs)==80 and len(imap)==len(ios),"observer identities")
    records=[];previous=None
    for row,scheduled in zip(rows,plan["rows"]):
        ensure(all(row.get(k)==v for k,v in scheduled.items()),"row schedule")
        r=decompose(row,previous,qmap.get(row["query_id"]),imap.get(row["io_id"]),runtime["root_observed_done_ns"],clock)
        if row["qualify"]:
            ensure(row["bank_sha256"]==digest(bank),"bank hash")
            r.update(match(r["gap_ns"],bank["targets_ns"][stratum(row)]))
        records.append(r);previous=row
    strata=[]
    for key in sorted(bank["targets_ns"]):
        refs=[r for r in records if r["phase"]=="reference" and r["role"]!="cell_transition" and stratum(r)==key]
        holds=[r for r in records if r["qualify"] and r["mode"]=="query" and stratum(r)==key]
        idles=[r for r in records if r["qualify"] and r["mode"]=="idle" and stratum(r)==key]
        ensure(len(refs)==3 and len(holds)==len(idles)==2,"stratum denominator")
        d={p:delta(refs,holds,p+"_ns") for p in PARTS};dg=delta(refs,holds,"gap_ns")
        ensure(sum(d.values())==dg,"mean difference accounting")
        target=bank["targets_ns"][key];limit=match(target,target)["limit_ns"]
        strata.append({"stratum":key,"reference_ids":[r["id"] for r in refs],
          "holdout_query_ids":[r["id"] for r in holds],"holdout_idle_ids":[r["id"] for r in idles],
          "reference":{p:summary(refs,p+"_ns") for p in (*PARTS,"gap","before_prepare")},
          "holdout_query":{p:summary(holds,p+"_ns") for p in (*PARTS,"gap","before_prepare")},
          "holdout_idle":{p:summary(idles,p+"_ns") for p in (*PARTS,"gap","before_prepare")},
          "query_matches":sum(r["matched"] for r in holds),"idle_matches":sum(r["matched"] for r in idles),
          "prior_target_ns":target,"prior_tolerance_ns":limit,
          "reference_span_ns":max(r["gap_ns"] for r in refs)-min(r["gap_ns"] for r in refs),
          "reference_span_exceeds_full_prior_band":max(r["gap_ns"] for r in refs)-min(r["gap_ns"] for r in refs)>2*limit,
          "query_minus_reference_mean_ns":{k:float(v) for k,v in d.items()},
          "mean_gap_change_ns":float(dg),"mean_difference_exactly_additive":True})
    primary=[r for r in records if r["role"]!="cell_transition"]
    refs=[r for r in primary if r["phase"]=="reference"]
    holds=[r for r in primary if r["phase"]=="holdout" and r["mode"]=="query"]
    matched=[r for r in records if r["qualify"] and r["matched"]]
    bad=[r for r in records if r["qualify"] and not r["matched"]]
    aggregate={"reference_query":{p:summary(refs,p+"_ns") for p in (*PARTS,"gap","before_prepare")},
               "holdout_query":{p:summary(holds,p+"_ns") for p in (*PARTS,"gap","before_prepare")},
               "query_minus_reference_mean_ns":{p:float(delta(refs,holds,p+"_ns")) for p in PARTS},
               "mean_gap_change_ns":float(delta(refs,holds,"gap_ns"))}
    ensure(sum(delta(refs,holds,p+"_ns") for p in PARTS)==delta(refs,holds,"gap_ns"),"aggregate arithmetic")
    telemetry=[]
    for q in qs:
        values=next(csv.reader(io.StringIO(q["result"]["csv"])))
        ensure(len(values)==len(q["result"]["fields"]),"telemetry width")
        payload=dict(zip(q["result"]["fields"],[v.strip() for v in values]))
        telemetry.append({"row_id":q["row_id"],"clock_scope":q["clock_scope"],
           "host_begin_ns":q["begin_ns"],"host_end_ns":q["end_ns"],"payload":payload,
           "wall_timestamp_not_calibrated_to_monotonic":True})
    events=json.loads((window/"events.json").read_text());boundary=[e for e in events if e["kind"]=="boundary_observation"]
    byid={r["id"]:r for r in rows}
    for e in boundary:
        r=byid[e["row_id"]];i=imap[r["io_id"]]
        ensure(e["clock_scope"]==clock and i["end_ns"]<=e["host"]["monotonic_ns"]<=r["prepare_begin_ns"],"host observer clock/link")
    ensure(len(boundary)==56,"boundary observation denominator")
    after=verify_inputs(source,manifest);ensure(before==after,"source changed during audit")
    before_query=[r for r in records if r["mode"]=="query"]
    bound=plan["config"]["max_target_ns"]
    band_top=bound+max(plan["config"]["match_abs_ns"],plan["config"]["match_relative"]*bound)
    overdue=[r["id"] for r in before_query if r["gap_ns"]>bound]
    outside_band=[r["id"] for r in before_query if r["gap_ns"]>band_top]
    for q in qs:
        fields=next(csv.reader([q["result"]["csv"]]))
        ensure(len(fields)==8,"telemetry CSV width")
    ensure(not any(m in sys.modules for m in ("torch","sglang","pynvml")),"GPU module imported")
    ensure(len(matched)==34 and len(bad)==30,"original qualification preserved")
    return {"schema":"reference-representativeness-audit1","source_delivery_commit":"dbb062606a2ce4ebfdd7218b17151f071ea043b4",
       "execution_commit":plan["checkout"],"plan_sha256":digest(plan),"bank_sha256":digest(bank),
       "inputs_sha256":before,"inputs_unchanged":True,"GPU_execution":False,
       "primary_interpretation":"descriptive single-process audit; no causal or stable-gain claim",
       "planned_rows":128,"measured_rows":128,"reference_query":48,"holdout_query":32,"holdout_idle":32,"transitions":16,
       "original_qualified":False,"original_matched_holdout":34,"original_unmatched":30,
       "unmatched_above":sum(r["error_ns"]>0 for r in bad),"unmatched_below":sum(r["error_ns"]<0 for r in bad),
       "strata":strata,"aggregate":aggregate,"rows":records,"telemetry":telemetry,
       "telemetry_coverage":{"reference_query":48,"holdout_query":32,"holdout_idle":0,"transition":0,
          "sampling_missingness_depends_on_policy":True,
          "query_duration_ns":summary([r for r in records if r["mode"]=="query"],"query_ns"),
          "SM_MHz_counts":dict(Counter(t["payload"]["SM_MHz"] for t in telemetry))},
       "boundary_observations":boundary,
       "boundary_loadavg_1m":{"min":min(e["host"]["loadavg"][0] for e in boundary),"max":max(e["host"]["loadavg"][0] for e in boundary),
                            "CPU_saturation_or_owner_unknown":True},
       "counterfactual_feasibility_not_an_experiment":{"same_host_deadline_at_most_500ms":{"known_query_chains_exceeding_bound":overdue,
            "count":len(overdue),"max_target_ns":bound,"max_target_plus_original_tolerance_ns":band_top,
            "beyond_largest_original_match_band":outside_band,"band_count":len(outside_band),
            "eligible":False,"not_interventional_simulation":True,
            "reason":"algebraic coverage of existing costs only; cannot force observed out-of-band chains inside any original admissible fixed target without changing chain or dropping data"}},
       "qualification_changed":False,"bank_rewritten":False,"executable_comparison_plan_created":False}

def render_tables(report):
    lines=["# v0.25 离线代表性审计","",
      "只重算固定v0.24原件。旧qualified=false、34/64与全部分母保持；均值差为描述性分解，不是因果效应或新门槛。","",
      "|分层|Δgap ms|Δprefix ms|Δprepare ms|Δquery ms|Δquery前后 ms|Q匹配|I匹配|",
      "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for s in report["strata"]:
        d=s["query_minus_reference_mean_ns"]
        prefix=d["bookkeeping"]+d["boundary_io"]+d["unresolved_prefix"]
        residual=d["pre_query"]+d["post_query_or_wait"]
        lines.append(f'|{s["stratum"]}|{s["mean_gap_change_ns"]/1e6:.6f}|{prefix/1e6:.6f}|{d["prepare"]/1e6:.6f}|{d["query"]/1e6:.6f}|{residual/1e6:.6f}|{s["query_matches"]}/2|{s["idle_matches"]}/2|')
    lines+=["","Δ均为holdout query(n=2/层)−reference query(n=3/层)；每层的精确有理数均值差可加总。表中显示值四舍五入不参与判定。median/min/max及每条原始区间见audit.json/rows.csv。","",
      "|分层|Δbookkeeping ms|Δ真实归档IO ms|Δ未细分prefix ms|",
      "|---|---:|---:|---:|"]
    for s in report["strata"]:
        d=s["query_minus_reference_mean_ns"];lines.append(f'|{s["stratum"]}|{d["bookkeeping"]/1e6:.6f}|{d["boundary_io"]/1e6:.6f}|{d["unresolved_prefix"]/1e6:.6f}|')
    return "\n".join(lines)+"\n"

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--root",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    ensure(not a.output.exists(),"new output directory required")
    report=audit(a.root);a.output.mkdir(parents=True,exist_ok=False)
    write_json(a.output/"audit.json",report,exclusive=True)
    fields=list(report["rows"][0]);ensure(all(set(r)==set(fields) for r in report["rows"] if not r["qualify"]),"row fields")
    fields=sorted({k for r in report["rows"] for k in r})
    with (a.output/"rows.csv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fields);w.writeheader();w.writerows(report["rows"])
    (a.output/"tables.md").write_text(render_tables(report),encoding="utf-8",newline="\n")
    write_json(a.output/"audit-source.json",{"source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "GPU_imported":False,"input_root":str(a.root),"input_count":len(report["inputs_sha256"])},exclusive=True)
    print(json.dumps({"rows":128,"strata":len(report["strata"]),"unmatched":30,
       "GPU_execution":False,"input_unchanged":True,"aggregate":report["aggregate"]["query_minus_reference_mean_ns"]}))
if __name__=="__main__":main()
