"""Extract one real holdout and its three frozen references; never starts CUDA."""
import argparse,json
from pathlib import Path
from reference_protocol import load,stratum,match
from cadence_protocol import digest,write_json
def reproduce(plan,root,row_id):
 rows=[json.loads(s) for s in (root/"ledger.jsonl").read_text().splitlines()]
 byid={r["id"]:r for r in rows};row=byid[row_id]
 if not row["qualify"] or row["status"]!="measured":raise ValueError("measured holdout required")
 bank=json.loads((root/"frozen-targets.json").read_text())
 if bank["plan_sha256"]!=digest(plan) or row["bank_sha256"]!=digest(bank):raise ValueError("bank identity")
 refs=[r for r in rows if r["phase"]=="reference" and r["role"]!="cell_transition" and stratum(r)==stratum(row)]
 if len(refs)!=3:raise ValueError("reference coverage")
 queries={q["id"]:q for q in json.loads((root/"queries.json").read_text())}
 ios={i["id"]:i for i in json.loads((root/"io-events.json").read_text())}
 previous=byid.get(row["previous_id"])
 result={"schema":"reference-error-minrepro1","row":row,"prior_references":refs,
   "previous_row":previous,"common_target_ns":bank["targets_ns"][stratum(row)],
   "bank_sha256":digest(bank),"frozen_plan_sha256":digest(plan),
   "query":queries.get(row["query_id"]),"boundary_IO":ios.get(row["io_id"]),
   "host_intervals_ns":{"before_prepare":row["prepare_begin_ns"]-row["previous_done_ns"],
    "prepare":row["ready_ns"]-row["prepare_begin_ns"],
    "ready_to_submit":row["submit_ns"]-row["ready_ns"]},
   "root_cause":"unknown","physical_GPU_idle_measured":False,"GPU_execution":False}
 result["matching"]=match(row["submit_ns"]-row["previous_done_ns"],result["common_target_ns"])
 if previous:result["host_intervals_ns"]["preceding_bookkeeping"]=previous["bookkeeping_end_ns"]-previous["done_ns"]
 if result["query"]:result["host_intervals_ns"]["query"]=result["query"]["end_ns"]-result["query"]["begin_ns"]
 return result
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--plan",type=Path,required=True)
 p.add_argument("--root",type=Path,required=True);p.add_argument("--row",required=True);p.add_argument("--output",type=Path,required=True)
 a=p.parse_args();result=reproduce(load(a.plan),a.root,a.row);write_json(a.output,result,exclusive=True)
 print(json.dumps(result["matching"]))
if __name__=="__main__":main()
