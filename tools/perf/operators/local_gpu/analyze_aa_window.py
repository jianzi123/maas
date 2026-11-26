"""Offline P25-AA engineering qualification. No GPU imports or collection."""
import argparse,json,math,statistics
from collections import Counter
from pathlib import Path
from cadence_protocol import digest,write_json
from aa_protocol import CONFIG,need,load,match,stratum,check_binding,check_budget
def read(root,name,default):
 p=Path(root)/name
 return json.loads(p.read_text()) if p.exists() else default
def identity_rows(plan,root,issues=None):
    found={}
    for proc in ("REF","HOLD"):
        path=Path(root)/proc/"blocks.jsonl"
        if not path.exists():continue
        for line_number,line in enumerate(path.read_text().splitlines(),1):
            try:
                r=json.loads(line);need(r["id"] in {x["id"] for x in plan["rows"] if x["process"]==proc},"unknown row identity")
                need(r["id"] not in found,"duplicate row identity")
                found[r["id"]]=r
            except (ValueError,KeyError,TypeError) as e:
                if issues is None:raise
                issues.append(f"{proc}/line{line_number}: {e}")
    return [found.get(r["id"],dict(r,status="missing",calls_completed=0,reason="planned identity not observed")) for r in plan["rows"]]
def bank_from_reference(plan,root,frozen_ns,window_id):
    records=[r for r in identity_rows(plan,root) if r["process"]=="REF"]
    need(len(records)==56 and all(r["status"]=="measured" for r in records),"reference incomplete")
    runtime=read(Path(root)/"REF","runtime.json",{})
    end=read(Path(root)/"REF","final-invariants.json",{})
    need(end.get("graphs_unchanged") and end.get("parameter_sha256")==runtime["metadata"]["parameter_full_sha256"],"reference final invariants")
    cells=read(Path(root)/"REF","cells.json",[]);need(len(cells)==4,"reference input cells")
    gates=read(Path(root)/"REF","gates.json",[]);need(len(gates)==8,"reference gates")
    from analyze_kv_cadence import validate_gate
    for gate in gates:validate_gate(gate,Path(root)/"REF")
    targets={}
    for r in records:
        if r["role"]=="cell_transition":continue
        targets.setdefault(stratum(r),[]).append(r["stream_event_ns"])
    need(len(targets)==16 and all(len(v)==3 and all(math.isfinite(x) and x>0 for x in v) for v in targets.values()),"reference target coverage")
    return {"schema":"P25-AA-bank1","window_id":window_id,"plan_sha256":digest(plan),"frozen_parent_elapsed_ns":frozen_ns,
       "reference_rows_sha256":digest(records),"reference_ids":[r["id"] for r in records],
       "prior_stream_ns":{k:statistics.median(v) for k,v in targets.items()},
       "parameter_sha256":runtime["metadata"]["parameter_full_sha256"],
       "input_values":{f"{c['scope']}/B{c['batch']}":{k:v for k,v in c["input_state"].items() if k!="path"} for c in cells},
       "common_for_aliases":True,"abs_ns":250000,"relative":.05}

def validate_row(row,scheduled,runtime,cell,job,previous,io):
 need(all(row.get(k)==v for k,v in scheduled.items()),"schedule row changed")
 need(row["clock_scope"]==runtime["clock_scope"],"cross-clock row")
 need(row["budget_lease_sha256"]==job["budget_lease_sha256"],"row budget reset")
 need(row["bank_sha256"]==job["bank_sha256"],"row bank")
 need(row.get("graph_used") is True and math.isfinite(row["stream_event_ns"]) and row["stream_event_ns"]>0,"eager/nonfinite stream")
 values={k:v for k,v in cell["input_state"].items() if k!="path"}
 need(row["input_values_sha256"]==digest(values),"row input mismatch")
 binding=cell["bindings"][row["implementation"]];check_binding(binding)
 need(binding.get("registry_identity_checked") is True,"registry identity not checked")
 observed=binding["aliases"]["A"];actual=runtime["metadata"]["graph_identity"][row["implementation"]];cap=str(binding["padded_batch"])
 need(observed["graph_object"]==actual["graphs"][cap] and observed["inputs"]==actual["inputs"]
      and observed["scratch"]==actual["scratch"] and observed["indices"]==actual["indices"] and observed["pool"]==actual["pools"][cap],"runtime graph identity")
 need(observed["stream"]==runtime["metadata"]["execution_stream"],"stream changed")
 if row["scope"]=="full":
  need(observed["callable_self"]==runtime["metadata"]["runner_object"] and observed["callable_function"]==runtime["metadata"]["forward_function"],"full caller changed")
 else:need(observed["callable_self"]==observed["graph_object"] and observed["callable_function"]==runtime["metadata"]["graph_replay_function"],"graph replay caller changed")
 need(row["binding_sha256"]==digest(binding),"alias/graph/input binding changed")
 input_values={k:v for k,v in cell["input_state"].items() if k!="path"}
 need(row["input_values_sha256"]==digest(input_values),"input identity changed")
 expect_done=previous["done_ns"] if previous else runtime["root_observed_done_ns"]
 need(row["previous_done_ns"]==expect_done and row["previous_id"]==(previous["id"] if previous else None),"previous_done reset")
 order=[row[k] for k in ("previous_done_ns","prepare_begin_ns","ready_ns","submit_ns","enqueue_ns","done_ns","bookkeeping_end_ns")]
 need(all(isinstance(x,int) for x in order) and order==sorted(order),"row clock/order")
 need(row["calls_completed"]==10 and math.isfinite(row["stream_event_ns"]) and row["stream_event_ns"]>0,"event/calls")
 need(row.get("graph_used") is True,"eager/graph invalid")
 need(cell["clock_scope"]==runtime["clock_scope"] and cell["ready_ns"]<=row["prepare_begin_ns"],"cell clock/order")
 if row["role"]=="boundary_first":
  need(io is not None and io["clock_scope"]==runtime["clock_scope"] and
       row["previous_done_ns"]<=io["begin_ns"]<=io["end_ns"]<=row["prepare_begin_ns"],"boundary IO")
 else:need(io is None and row["io_id"] is None,"unexpected IO")
def analyze(plan,root):
 from aa_worker import validate_job
 errors=[]
 rows=identity_rows(plan,root,errors);parent=read(root,"parent.json",{});bank=read(root,"bank.json",None)
 details=[];valid_ids=set();runtimes={};clocks=[]
 def error(message):errors.append(message)
 try:
  driver=read(Path(root).parent,"driver.json",{})
  need(driver["plan_sha256"]==digest(plan) and driver["window_id"]==parent["budget"]["window_id"]
       and driver["own_process_collected"] and driver["within_600s"] and driver.get("failure") is None,"outer driver budget/failure")
  need(parent["plan_sha256"]==digest(plan),"parent plan");check_budget(parent["budget"])
  need(parent["elapsed_ns"]<=parent["budget"]["hard_remaining_ns"],"parent hard budget")
  life=parent["lifecycle"];need(len(life)<=2 and [l["process"] for l in life]==["REF","HOLD"][:len(life)],"worker lifecycle/third process")
  need(all(l["start_ns"]<parent["budget"]["soft_remaining_ns"] and l["end_ns"]<=parent["budget"]["hard_remaining_ns"] for l in life),"lifecycle budget reset")
  if len(life)==2:need(life[0]["end_ns"]<bank["frozen_parent_elapsed_ns"]<life[1]["start_ns"],"late bank freeze/overlap")
  need(parent.get("failure") is None,"parent collection failure")
 except (ValueError,KeyError,TypeError) as e:error(str(e))
 for proc in ("REF","HOLD"):
  folder=Path(root)/proc;runtime=read(folder,"runtime.json",None);job=read(root,proc+"-job.json",None)
  result=read(folder,"worker-result.json",None);cells=read(folder,"cells.json",[]);io=read(folder,"io-events.json",[])
  cmap={(c["scope"],c["batch"]):c for c in cells};imap={i["id"]:i for i in io}
  if runtime is None or job is None or result is None:
   error(proc+" missing runtime/job/result");continue
  runtimes[proc]=runtime;clocks.append(runtime["clock_scope"])
  try:
   validate_job(plan,job);need(job["budget"]==parent["budget"] and runtime["job_sha256"]==digest(job),"job/budget identity")
   need(runtime["process"]==proc and runtime["plan_sha256"]==digest(plan) and
        runtime["budget_lease_sha256"]==digest(parent["budget"]),"runtime binding")
   life_item=next(l for l in parent["lifecycle"] if l["process"]==proc)
   need(job["parent_pid"]==parent["pid"]==runtime["parent_pid"] and runtime["pid"]==life_item["pid"],"process lifecycle identity")
   if job.get("schema")=="P25-AA-job2":
    need(job["budget_control"]==parent["budget_control"]==runtime["budget_control"],"shared control origin changed")
    need(job["control_binding_sha256"]==parent["control_binding_sha256"]==runtime["control_binding_sha256"],"original control binding changed")
    need(0<=parent["control_receive"]["control_receive_elapsed_ns"]<=job["launch_parent_elapsed_ns"]
         <=runtime["control_elapsed_at_start_ns"]<job["soft_parent_deadline_ns"],"control wait/start time lost")
   need(result["failure"] is None and result["job_sha256"]==digest(job),"worker failure")
   need(len(cells)==4 and len(cmap)==4,"input cell coverage")
   end=read(folder,"final-invariants.json",{})
   need(end["graphs_unchanged"] and end["parameter_sha256"]==runtime["metadata"]["parameter_full_sha256"],"final graph/parameter")
   facts=runtime["metadata"]["capture_facts"]
   need(set(facts)=={"native","mature"} and all(f["observer_removed"] and f["layers"]==list(range(30))
       and f["capture_sizes"]==[1,2,4,8] and f["capturing_calls"]>0 for f in facts.values()),"actual capture caller")
   need(facts["native"]["source_sha256"]!=facts["mature"]["source_sha256"]
        and "mature_kv_binding" in facts["mature"]["method"],"mature capture caller not distinct")
   gates=read(folder,"gates.json",[])
   expected_gates={(f"R01/{scope}/B{b}",edge) for scope in CONFIG["scopes"] for b in CONFIG["batches"] for edge in ("before","after")}
   need(len(gates)==8 and {(g["cell_id"],g["phase"]) for g in gates}==expected_gates,"complete numerical gate coverage")
   from analyze_kv_cadence import validate_gate
   for gate in gates:validate_gate(gate,folder)
   import numpy as np,hashlib
   for c in cells:
    value=c["input_state"];path=(folder/value["path"]).resolve()
    need(path.is_relative_to(folder.resolve()),"input path")
    with np.load(path,allow_pickle=False) as f:
     kv=f["value"];need(list(kv.shape)==value["KV_shape"]==[30,2,len(value["read_slots"]),3,64] and str(kv.dtype)==value["KV_dtype"]=="float16" and
       np.isfinite(kv).all() and hashlib.sha256(kv.tobytes()).hexdigest()==value["KV_sha256"],"readable KV input")
    for b in c["bindings"].values():check_binding(b)
  except (ValueError,KeyError,TypeError,OSError) as e:error(proc+": "+str(e))
  previous=None
  for row in [r for r in rows if r["process"]==proc]:
   if row["status"]!="measured":continue
   try:
    cell=cmap.get((row["scope"],row["batch"]));need(cell is not None,"missing cell")
    validate_row(row,next(s for s in plan["rows"] if s["id"]==row["id"]),runtime,cell,job,previous,imap.get(row["io_id"]))
    need(row["binding_sha256"]==digest(cell["bindings"][row["implementation"]]),"binding hash")
    valid_ids.add(row["id"])
   except (ValueError,KeyError,TypeError) as e:error(row["id"]+": "+str(e))
   previous=row
 if len(clocks)==2:
  try:need(clocks[0]!=clocks[1],"shared process clock identity")
  except ValueError as e:error(str(e))
 for row in rows:
  item=dict(row,row_integrity_valid=row["id"] in valid_ids)
  if row["qualify"] and row["id"] in valid_ids and bank is not None:
   try:item.update(match(row["stream_event_ns"],bank["prior_stream_ns"][stratum(row)]))
   except (ValueError,KeyError,TypeError) as e:error(str(e))
  details.append(item)
 if bank is not None:
  try:
   expected=bank_from_reference(plan,root,bank["frozen_parent_elapsed_ns"],bank["window_id"])
   need(bank==expected and bank["window_id"]==parent["budget"]["window_id"],"common bank/reference mismatch")
   need(runtimes["HOLD"]["metadata"]["parameter_full_sha256"]==bank["parameter_sha256"],"cross-process parameter")
   need(read(root,"HOLD-job.json",{})["bank_sha256"]==digest(bank),"holdout wrong bank")
   for key in ("sglang_commit","versions","GPU","CC","model_config_sha256"):
    need(runtimes["REF"]["metadata"][key]==runtimes["HOLD"]["metadata"][key],"cross-process environment")
   holdcells=read(Path(root)/"HOLD","cells.json",[])
   need({f"{c['scope']}/B{c['batch']}":{k:v for k,v in c["input_state"].items() if k!="path"} for c in holdcells}==bank["input_values"],"cross-process input values")
   need(read(root,"HOLD-job.json",{})["bank_sha256"]==digest(bank),"holdout bank hash")
  except (ValueError,KeyError,TypeError) as e:error(str(e))
 else:error("reference bank missing")
 pairs=[]
 for key in sorted({r["pair"] for r in plan["rows"] if r["qualify"]}):
  planned=[r for r in details if r["pair"]==key]
  a=next(r for r in planned if r["alias"]=="A");b=next(r for r in planned if r["alias"]=="Aprime")
  complete=all(r["row_integrity_valid"] for r in planned)
  pairs.append({"pair":key,"stratum":stratum(a),"A_id":a["id"],"Aprime_id":b["id"],"complete":complete,
   "A_ns":a.get("stream_event_ns"),"Aprime_ns":b.get("stream_event_ns"),
   "Aprime_minus_A_ns":b["stream_event_ns"]-a["stream_event_ns"] if complete else None,
   "Aprime_over_A":b["stream_event_ns"]/a["stream_event_ns"] if complete else None})
 holds=[r for r in details if r["qualify"]];matched=sum(r.get("matched",False) for r in holds)
 ranges={}
 for key in sorted({p["stratum"] for p in pairs}):
  observed=[p for p in pairs if p["stratum"]==key and p["complete"]]
  ranges[key]={"planned_pairs":2,"complete_pairs":len(observed),
    "difference_ns":[min(p["Aprime_minus_A_ns"] for p in observed),max(p["Aprime_minus_A_ns"] for p in observed)] if observed else None,
    "ratio":[min(p["Aprime_over_A"] for p in observed),max(p["Aprime_over_A"] for p in observed)] if observed else None}
 criteria_satisfied=not errors and matched==64 and all(r["status"]=="measured" for r in rows)
 real=len(runtimes)==2 and all(r.get("evidence_kind")=="local_GPU_static_dummy" for r in runtimes.values())
 qualified=criteria_satisfied and real
 failed=next((r for r in details if r["qualify"] and not r.get("matched",False)),None)
 return {"schema":"P25-AA-report1","plan_sha256":digest(plan),"engineering_repeatability_qualified":qualified,"criteria_satisfied":criteria_satisfied,"evidence_kind":"local_GPU_static_dummy" if real else "synthetic_or_incomplete",
   "planned_rows":128,"measured_rows":sum(r["status"]=="measured" for r in rows),"holdout_planned":64,"holdout_matched":matched,
   "planned_calls":1280,"completed_calls":sum(r.get("calls_completed",0) for r in rows),"status_counts":dict(Counter(r["status"] for r in rows)),
   "integrity_valid":not errors,"errors":errors,"rows":details,"alias_pairs":pairs,"alias_ranges":ranges,
   "minimum_counterexample":failed,"zero_alias_bias_established":False,"statistical_equivalence_established":False,
   "arbitrary_KV_gain_resolvable":False,"old_query_template_qualified":False,"NM_gain_established":False,
   "claim":"only repeatability of the observed window at the engineering threshold",
   "trace_needed_if_failed":"separate authorized timeline of enqueue/stream queue/prepare and scheduler; no automatic profiler rerun"}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--plan",type=Path,required=True);p.add_argument("--root",type=Path,required=True)
 p.add_argument("--output",type=Path,required=True);a=p.parse_args();v=analyze(load(a.plan),a.root)
 write_json(a.output,v,exclusive=True)
 print(json.dumps({k:v[k] for k in ("engineering_repeatability_qualified","measured_rows","holdout_matched","integrity_valid")}))
 return 0 if v["integrity_valid"] else 2
if __name__=="__main__":raise SystemExit(main())
