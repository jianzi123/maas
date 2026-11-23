"""Supplementary descriptive stratification; never filters unmatched or slow blocks."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
from cadence_protocol import digest,write_json
from analyze_kv_cadence import load_analysis_plan


def describe(xs):
    ys=sorted(xs)
    return {"count":len(xs),"min":ys[0],"median":statistics.median(ys),
            "p95_nearest_rank":ys[max(0,(len(ys)*95+99)//100-1)],"max":ys[-1]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan",type=Path,required=True)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--analysis",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    plan=load_analysis_plan(args.plan)
    analysis=json.loads(args.analysis.read_text())
    if analysis["plan_sha256"]!=digest(plan):raise ValueError("analysis plan mismatch")
    rows=[];runtimes=[]
    for run in plan["config"]["runs"]:
        folder=args.root/run["id"]
        rows.extend(json.loads(s) for s in (folder/"blocks.jsonl").read_text().splitlines() if s.strip())
        runtimes.append(json.loads((folder/"runtime-manifest.json").read_text()))
    if len({r["parameter_full_sha256"] for r in runtimes})!=1 or len({r["model_config_sha256"] for r in runtimes})!=1:
        raise ValueError("cross-process parameter/config identity mismatch")
    summaries=[]
    for run in ("R01","R02"):
        for scope in ("full","bare_graph"):
            for batch in (3,5,8):
                for policy in ("query_block","query_cluster","idle_matched"):
                    found=[r for r in rows if r["run_id"]==run and r["scope"]==scope and r["batch"]==batch and r["policy"]==policy]
                    measured=[r for r in found if r["status"]=="measured"]
                    clusters=[r for r in analysis["clusters"] if r["run_id"]==run and r["scope"]==scope and r["batch"]==batch and r["policy"]==policy]
                    row={"run_id":run,"scope":scope,"batch":batch,"policy":policy,
                        "planned_blocks":30,"measured_blocks":len(measured),
                        "complete_clusters":len(clusters),
                        "primary_cluster_ms_per_100_calls":describe([r["cluster_wall_ms_per_100_calls"] for r in clusters]),
                        "variants":{}}
                    for variant in ("native","mature"):
                        group=[r for r in measured if r["variant"]==variant]
                        row["variants"][variant]={k:describe([r[k]/10000 for r in group]) for k in ("event_ns","wall_ns","host_enqueue_ns","wait_ns")}
                        row["variants"][variant]["gap_matched"]=sum(r["gap_match"]["matched"] for r in group)
                        row["variants"][variant]["gap_total"]=len(group)
                    row["gap_error_ms"]=describe([r["gap_match"]["error_ns"]/1e6 for r in measured])
                    row["gap_abs_error_ms"]=describe([abs(r["gap_match"]["error_ns"])/1e6 for r in measured])
                    row["gap_matched"]=sum(r["gap_match"]["matched"] for r in measured)
                    summaries.append(row)
    contrasts=[]
    by_cluster={r["cluster_id"]:r for r in analysis["clusters"]}
    for triplet in analysis["triplets"]:
        if not triplet["complete"]:continue
        group={c["policy"]:by_cluster[c["cluster_id"]] for c in plan["schedule"]
               if c["triplet_id"]==triplet["triplet_id"]}
        for variant in ("native","mature"):
            values={p:c["variant_block_median_us_per_call"][variant]["event_ns"] for p,c in group.items()}
            contrasts.append({"triplet_id":triplet["triplet_id"],"run_id":triplet["run_id"],
                "scope":triplet["scope"],"batch":triplet["batch"],"rotation":triplet["rotation"],
                "variant":variant,"event_us_per_call":values,
                "event_ratio_vs_query_block":{p:v/values["query_block"] for p,v in values.items()},
                "unconditional_all_samples":True})
    matching=[]
    for run in ("R01","R02"):
        for scope in ("full","bare_graph"):
            for policy in ("query_block","idle_matched"):
                group=[r for r in rows if r["run_id"]==run and r["scope"]==scope and r["policy"]==policy and r["status"]=="measured"]
                matching.append({"run_id":run,"scope":scope,"policy":policy,"blocks":len(group),
                    "matched":sum(r["gap_match"]["matched"] for r in group),
                    "abs_error_ms":describe([abs(r["gap_match"]["error_ns"])/1e6 for r in group])})
    result={"plan_sha256":digest(plan),"summaries":summaries,"variant_policy_contrasts":contrasts,
        "matching":matching,"fully_gap_matched_full_triplets":sum(r["scope"]=="full" and r.get("idle_match_qualified",False) for r in analysis["triplets"]),
        "all_full_triplets":sum(r["scope"]=="full" for r in analysis["triplets"]),
        "cross_process_full_parameters_and_config_match":True,
        "code_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "no_filtered_performance_estimate":True,"root_cause_or_model_gain_claim":False}
    write_json(args.output,result,exclusive=True)
    print(json.dumps({"summary_cells":len(summaries),"stratified_triplets":len(contrasts),
        "gap_qualified_full_triplets":result["fully_gap_matched_full_triplets"],
        "planned_full_triplets":result["all_full_triplets"]}))


if __name__=="__main__":main()
