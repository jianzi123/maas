"""One600s reference/calibration/freeze/holdout window. No main comparison."""
import argparse,json,os,time,statistics,uuid
from pathlib import Path
from cadence_protocol import canonical,digest,write_json
from reference_protocol import load,stratum,CONFIG

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("--plan",type=Path,required=True)
 p.add_argument("--output",type=Path,required=True)
 p.add_argument("--validate-only",action="store_true")
 a=p.parse_args();plan=load(a.plan)
 if a.validate_only:
  print(json.dumps({"validated":True,"rows":128,"GPU_imports":False}));return 0
 if os.name!="posix":raise RuntimeError("authorized Linux/WSL required")
 a.output.mkdir(parents=True,exist_ok=False)
 start=time.perf_counter();records=[];pending=[];queries=[];ios=[];gates=[];cells=[];events=[]
 failure=None;rt=None;guard=None;bank=None;runtime=None;bank_sha=None;stage="lock";prev_id=None;prev_done=None
 clock=f"{plan['experiment']}/R01/pid{os.getpid()}-{uuid.uuid4().hex[:8]}"
 def deadline():
  if time.perf_counter()-start>=CONFIG["resources"]["internal_stop_seconds"]:raise RuntimeError("deadline")
 def flush(reason):
  begin=time.perf_counter_ns();ids=[r["id"] for r in pending]
  with (a.output/"ledger.jsonl").open("a",encoding="utf-8") as f:
   for row in pending:f.write(canonical(row).decode()+"\n")
   f.flush();os.fsync(f.fileno())
  pending.clear();end=time.perf_counter_ns()
  event={"id":f"io{len(ios)}","reason":reason,"begin_ns":begin,"end_ns":end,"row_ids":ids,"clock_scope":clock}
  ios.append(event);return event["id"]
 try:
  import fcntl
  guard=Path(CONFIG["resources"]["lock"]).open("a")
  fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
  deadline()
  import subprocess
  pre=subprocess.run(["/usr/lib/wsl/lib/nvidia-smi","--query-gpu=index,name,memory.free,memory.total,driver_version","--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=5)
  write_json(a.output/"GPU-preflight.json",{"returncode":pre.returncode,"csv":pre.stdout.strip(),"fields":["index","name","free_MiB","total_MiB","driver"]},exclusive=True)
  if pre.returncode!=0:raise RuntimeError("GPU_preflight")
  line=pre.stdout.strip().splitlines()[0].split(",")
  if int(line[0])!=0 or float(line[2])*1048576<1073741824:raise RuntimeError("preflight_resource_limit")
  from reference_runtime import ReferenceRuntime
  rt=ReferenceRuntime(a.output)
  prev_done=time.perf_counter_ns()
  runtime={"schema":"reference-runtime1","plan_sha256":digest(plan),"clock_scope":clock,
      "metadata":rt.metadata,"root_observed_done_ns":prev_done,"root_kind":"only_initial_boot_event_observation",
      "frozen_ns":time.perf_counter_ns(),"capture_first":"native","profile_in_hot_blocks":False}
  write_json(a.output/"runtime-manifest.json",runtime,exclusive=True)
  for phase in ("reference","holdout"):
   if phase=="holdout":
    stage="freeze";flush("reference-final-checkpoint")
    targets={}
    for key in sorted({stratum(r) for r in records if r["phase"]=="reference" and r["role"]!="cell_transition"}):
     samples=[r["submit_ns"]-r["previous_done_ns"] for r in records
              if r["phase"]=="reference" and r["role"]!="cell_transition" and stratum(r)==key]
     if len(samples)!=3:raise RuntimeError("reference_coverage")
     target=int(statistics.median(samples))
     if not 0<target<=CONFIG["max_target_ns"]:raise RuntimeError("reference_target_bound")
     targets[key]=target
    if len(targets)!=16:raise RuntimeError("reference_strata")
    bank={"schema":"reference-bank1","clock_scope":clock,"plan_sha256":digest(plan),
       "targets_ns":targets,"reference_row_ids":[r["id"] for r in records if r["phase"]=="reference" and r["role"]!="cell_transition"],
       "reference_rows_sha256":digest([r for r in records if r["phase"]=="reference"]),
       "frozen_ns":time.perf_counter_ns(),"match_abs_ns":CONFIG["match_abs_ns"],"match_relative":CONFIG["match_relative"],
       "same_target_for_query_and_idle":True}
    bank_sha=digest(bank)
    write_json(a.output/"frozen-targets.json",bank,exclusive=True)
    events.append({"kind":"freeze_complete","end_ns":time.perf_counter_ns(),"previous_done_unchanged":prev_done})
   stage=phase
   for scope in CONFIG["scopes"]:
    for bs in CONFIG["batches"]:
     deadline();setup_start=time.perf_counter_ns();rt.resources();rt.scope=scope
     fb=rt.cell(bs);gates.append(rt.gate(fb,phase+"-before"));inp=rt.input_hash(fb);rt.warm(fb)
     cell={"phase":phase,"scope":scope,"batch":bs,"input_sha256":inp,
           "begin_ns":setup_start,"ready_ns":time.perf_counter_ns(),"clock_scope":clock}
     cells.append(cell)
     write_json(a.output/"cells.json",cells)
     for scheduled in [r for r in plan["rows"] if r["cell"]==f"{phase}/{scope}/B{bs}"]:
      deadline();io_id=None
      if scheduled["role"]=="boundary_first":
       io_id=flush("pair-boundary")
       resource_state=rt.resources()
       from bench_kv_interleaved import host_state
       # Same real boundary guard/observer in reference and holdout.
       host=host_state(rt.torch)
       events.append({"kind":"boundary_observation","row_id":scheduled["id"],"host":host,"resource":resource_state,"clock_scope":clock})
      prepare_begin=time.perf_counter_ns()
      g=rt.prepare(scheduled["variant"],fb);ready=time.perf_counter_ns()
      fn=(lambda:rt.runner.forward(fb)) if scope=="full" else g.graphs[g.bs].replay
      qid=None;sleep_start=sleep_end=None;requested=0
      if scheduled["mode"]=="query":
       q0=time.perf_counter_ns();result=rt.telemetry();q1=time.perf_counter_ns()
       qid=scheduled["id"]+"/query"
       queries.append({"id":qid,"row_id":scheduled["id"],"begin_ns":q0,"end_ns":q1,
           "clock_scope":clock,"result":result})
       if result.get("returncode")!=0 or not result.get("csv"):raise RuntimeError("query_error")
      elif scheduled["mode"]=="idle":
       target=bank["targets_ns"][stratum(scheduled)]
       sleep_start=time.perf_counter_ns();requested=max(0,prev_done+target-sleep_start)
       if requested:time.sleep(requested/1e9)
       sleep_end=time.perf_counter_ns()
      submit=time.perf_counter_ns();cpu0=time.thread_time_ns()
      rt.begin.record();last=None
      for _ in range(10):last=fn()
      rt.end.record();enqueue=time.perf_counter_ns();cpu1=time.thread_time_ns()
      rt.end.synchronize();done=time.perf_counter_ns()
      row=dict(scheduled,clock_scope=clock,status="measured",previous_id=prev_id,
         previous_done_ns=prev_done,prepare_begin_ns=prepare_begin,ready_ns=ready,
         submit_ns=submit,enqueue_ns=enqueue,done_ns=done,calls_completed=10,
         event_ns=rt.begin.elapsed_time(rt.end)*1e6,thread_CPU_ns=cpu1-cpu0,
         query_id=qid,io_id=io_id,sleep_begin_ns=sleep_start,sleep_end_ns=sleep_end,
         sleep_requested_ns=requested,input_sha256=inp,bank_sha256=bank_sha)
      prev_done=done;prev_id=row["id"] # ONLY update; never reset at cell/IO/freeze.
      records.append(row);pending.append(row)
      if scope=="full" and not last[1]:
       row["status"]="invalid";raise RuntimeError("not_native_graph")
      # Identical real bookkeeping path and serialization in both stages/modes.
      canonical(row)
      row["bookkeeping_end_ns"]=time.perf_counter_ns()
     gates.append(rt.gate(fb,phase+"-after"))
     if rt.input_hash(fb)!=inp or rt.graph_identity()!=rt.identity:raise RuntimeError("cell_identity")
     write_json(a.output/"gates.json",gates)
     print(json.dumps({"phase":phase,"scope":scope,"batch":bs,"rows_so_far":len(records)}),flush=True)
  if rt.parameter_hash()!=rt.parameter_sha:raise RuntimeError("parameters_changed")
  final_resources=rt.resources();deadline()
  write_json(a.output/"final-invariants.json",{"parameters_unchanged":True,"graphs_unchanged":rt.graph_identity()==rt.identity,"resources":final_resources})
 except Exception as error:
  failure={"stage":stage,"type":type(error).__name__,"message":str(error)}
 finally:
  if rt is not None:
   try:rt.close()
   except Exception as e:failure=failure or {"stage":"cleanup","type":type(e).__name__,"message":str(e)}
 # Preserve planned missing identities and all query/IO timing, also on failure.
 seen={r["id"] for r in records}
 for scheduled in plan["rows"]:
  if scheduled["id"] not in seen:
   row=dict(scheduled,status="missing",calls_completed=0,missing_reason=failure or "not_observed",clock_scope=clock)
   records.append(row);pending.append(row)
 flush("final")
 write_json(a.output/"queries.json",queries);write_json(a.output/"io-events.json",ios)
 write_json(a.output/"gates.json",gates);write_json(a.output/"cells.json",cells);write_json(a.output/"events.json",events)
 from analyze_cadence_reference import evaluate
 report=evaluate(plan,records,bank, runtime,queries,ios,gates,a.output,check_files=True)
 report["failure"]=failure
 report["collection_complete"]=failure is None and report["measured_rows"]==128 and len(gates)==16
 report["qualified"]=report["qualified"] and report["collection_complete"]
 report["process_elapsed_seconds"]=time.perf_counter()-start
 report["peak_torch_bytes"]=rt.torch.cuda.max_memory_allocated() if rt else None
 write_json(a.output/"qualification.json",report)
 if report["qualified"]:
  candidate={"schema":"reference-qualified-main-candidate1","execution_enabled":False,
    "source_plan_sha256":digest(plan),"target_bank_sha256":digest(bank),"requires_independent_gate_QA":True,
    "main_comparison_authorized":False,"proposed_scopes":["full"],"proposed_batches":[3,8],
    "proposed_runs":2,"proposed_rotations":3,"policy_levels":["query_block","query_cluster","idle_matched"],
    "blocks_per_cluster_total":4,"calls_per_block":10,"reuse_exact_template_sources":plan["sources"],
    "must_predeclare_new_schedule_before_execution":True}
  write_json(a.output/"next-main-candidate.json",candidate,exclusive=True)
 if guard is not None:guard.close()
 print(json.dumps({"measured":report["measured_rows"],"holdout_matched":report["matched_holdout"],
   "holdout_planned":64,"qualified":report["qualified"],"failure":failure}),flush=True)
 return 0 if failure is None else 2

if __name__=="__main__":raise SystemExit(main())
