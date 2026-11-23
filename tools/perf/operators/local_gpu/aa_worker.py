"""One inherited-lock P25-AA worker. --validate-only imports no GPU framework."""
import argparse,json,math,os,signal,time,uuid
from pathlib import Path
from cadence_protocol import digest,canonical,write_json
from aa_protocol import CONFIG,load,need,check_budget,check_binding
class WindowStopped(RuntimeError):pass
def validate_job(plan,job):
 need(job["plan_sha256"]==digest(plan) and job["process"] in ("REF","HOLD"),"job identity")
 check_budget(job["budget"])
 need(job["budget_lease_sha256"]==digest(job["budget"]) and job["window_id"]==job["budget"]["window_id"],"job budget origin")
 need(job["parent_pid"]>0 and job["research_lock_fd"]>=0,"parent/lock")
 need(0<=job["launch_parent_elapsed_ns"]<job["soft_parent_deadline_ns"]<job["hard_parent_deadline_ns"],"late launch/reset budget")
 need(job["hard_parent_deadline_ns"]<=job["budget"]["hard_remaining_ns"],"per-process budget reset")
 need((job["process"]=="REF" and job["bank_sha256"] is None) or (job["process"]=="HOLD" and job["bank_sha256"]),"bank stage")
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--plan",type=Path,required=True);p.add_argument("--job",type=Path)
 p.add_argument("--output",type=Path);p.add_argument("--execute",action="store_true");p.add_argument("--validate-only",action="store_true")
 a=p.parse_args();plan=load(a.plan);job=json.loads(a.job.read_text()) if a.job else None
 if job:validate_job(plan,job)
 if a.validate_only:
  print(json.dumps({"validated":True,"GPU_imports":False,"rows":128}));return 0
 need(a.execute and plan["execution_enabled"] and job is not None and a.output is not None,"explicit authorized execution required")
 need(os.name=="posix" and os.getppid()==job["parent_pid"],"worker must be child of supervisor")
 import fcntl
 fd=job["research_lock_fd"];st=os.fstat(fd);lockst=os.stat(CONFIG["resources"]["lock"])
 need((st.st_dev,st.st_ino)==(lockst.st_dev,lockst.st_ino),"inherited research lock")
 a.output.mkdir(parents=True,exist_ok=False)
 start=time.perf_counter_ns();clock=f"{job['window_id']}/{job['process']}/pid{os.getpid()}-{uuid.uuid4().hex[:8]}"
 def stop(signum,frame):raise WindowStopped("parent global stop-new deadline")
 signal.signal(signal.SIGUSR1,stop);signal.signal(signal.SIGTERM,stop)
 records=[];pending=[];ios=[];gates=[];cells=[];events=[];rt=None;failure=None;runtime=None;stage="initialization"
 expected=[r for r in plan["rows"] if r["process"]==job["process"]];previous_id=None;previous_done=None
 def checkpoint(reason):
  begin=time.perf_counter_ns();ids=[r["id"] for r in pending]
  with (a.output/"blocks.jsonl").open("a",encoding="utf-8") as f:
   for r in pending:f.write(canonical(r).decode()+"\n")
   f.flush();os.fsync(f.fileno())
  pending.clear();end=time.perf_counter_ns();item={"id":f"IO{len(ios)}","reason":reason,"row_ids":ids,
    "begin_ns":begin,"end_ns":end,"clock_scope":clock};ios.append(item);return item["id"]
 try:
  from aa_runtime import AARuntime
  rt=AARuntime(a.output)
  need(all(f["observer_removed"] for f in rt.capture_facts.values()),"capture observer remains")
  rt.metadata.update(runner_object=id(rt.runner),forward_function=id(rt.runner.forward.__func__),graph_replay_function=id(rt.torch.cuda.CUDAGraph.replay),execution_stream=rt.torch.cuda.current_stream(0).cuda_stream)
  runtime={"schema":"P25-AA-runtime1","window_id":job["window_id"],"process":job["process"],"pid":os.getpid(),"parent_pid":os.getppid(),"evidence_kind":"local_GPU_static_dummy",
    "clock_scope":clock,"job_sha256":digest(job),"plan_sha256":digest(plan),"metadata":rt.metadata,
    "budget_lease_sha256":job["budget_lease_sha256"],"root_observed_done_ns":time.perf_counter_ns(),
    "hot_query":False,"hot_profiler":False,"internal_capture_calls":"unknown"}
  previous_done=runtime["root_observed_done_ns"]
  write_json(a.output/"runtime.json",runtime,exclusive=True)
  bank=json.loads(Path(job["bank_path"]).read_text()) if job["process"]=="HOLD" else None
  if bank:
   need(digest(bank)==job["bank_sha256"] and bank["parameter_sha256"]==rt.parameter_sha,"cross-process parameters")
  for scope in CONFIG["scopes"]:
   for bs in CONFIG["batches"]:
    stage=f"{scope}/B{bs}";begin=time.perf_counter_ns();rt.resources();rt.scope=scope
    fb=rt.cell(bs);gates.append(rt.gate(fb,"before"));rt.warm(fb)
    inp=rt.input_state(fb);value_key={k:v for k,v in inp.items() if k!="path"}
    if bank:need(bank["input_values"][f"{scope}/B{bs}"]==value_key,"cross-process input values")
    dispatch={};bindings={}
    for v in CONFIG["implementations"]:
     g=rt.prepare(v,fb);fn=rt.runner.forward if scope=="full" else g.graphs[g.bs].replay
     dispatch[v]={"A":fn,"Aprime":fn}
     need(dispatch[v]["A"] is dispatch[v]["Aprime"],"alias object")
     bindings[v]=rt.binding(scope,v,fb,fn);bindings[v]["registry_identity_checked"]=True;check_binding(bindings[v])
    cell={"scope":scope,"batch":bs,"clock_scope":clock,"input_state":inp,"bindings":bindings,
          "begin_ns":begin,"ready_ns":time.perf_counter_ns()}
    cells.append(cell);write_json(a.output/"cells.json",cells)
    for scheduled in [r for r in expected if r["scope"]==scope and r["batch"]==bs]:
     ioid=None
     if scheduled["role"]=="boundary_first":
      ioid=checkpoint("pair-boundary");observe0=time.perf_counter_ns();resource=rt.resources()
      events.append({"kind":"resource_boundary","row_id":scheduled["id"],"begin_ns":observe0,
                     "end_ns":time.perf_counter_ns(),"resource":resource,"clock_scope":clock})
     prep=time.perf_counter_ns();v=scheduled["implementation"];rt.prepare(v,fb)
     selected=dispatch[v][scheduled["alias"]]
     need(dispatch[v]["A"] is dispatch[v]["Aprime"],"alias object changed")
     binding=rt.binding(scope,v,fb,selected);binding["registry_identity_checked"]=True;check_binding(binding)
     need(binding==bindings[v],"binding/graph/stream changed")
     ready=time.perf_counter_ns();submit=time.perf_counter_ns();cpu0=time.thread_time_ns()
     rt.begin.record();last=None
     for _ in range(10):last=selected()
     rt.end.record();enqueue=time.perf_counter_ns();cpu1=time.thread_time_ns()
     rt.end.synchronize();done=time.perf_counter_ns()
     value=rt.begin.elapsed_time(rt.end)*1e6
     need(math.isfinite(value) and value>0,"stream timing")
     used=bool(last[1]) if scope=="full" else True
     row=dict(scheduled,status="measured" if used else "invalid",graph_used=used,clock_scope=clock,previous_id=previous_id,previous_done_ns=previous_done,
        prepare_begin_ns=prep,ready_ns=ready,submit_ns=submit,enqueue_ns=enqueue,done_ns=done,
        stream_event_ns=value,thread_CPU_ns=cpu1-cpu0,calls_completed=10,io_id=ioid,
        binding_sha256=digest(binding),input_values_sha256=digest(value_key),
        budget_lease_sha256=job["budget_lease_sha256"],bank_sha256=job["bank_sha256"])
     previous_done=done;previous_id=row["id"];records.append(row);pending.append(row)
     canonical(row);row["bookkeeping_end_ns"]=time.perf_counter_ns()
     need(used,"eager fallback")
    gates.append(rt.gate(fb,"after"))
    need(rt.input_state(fb)==inp and rt.graph_identity()==rt.identity,"input/graph changed within cell")
    write_json(a.output/"gates.json",gates)
    print(json.dumps({"process":job["process"],"scope":scope,"batch":bs,"measured":len(records)}),flush=True)
  need(rt.parameter_hash()==rt.parameter_sha,"parameter changed")
  write_json(a.output/"final-invariants.json",{"parameter_sha256":rt.parameter_sha,"graphs_unchanged":rt.graph_identity()==rt.identity,
              "resource":rt.resources(),"peak_torch_bytes":rt.torch.cuda.max_memory_allocated()})
 except BaseException as e:
  failure={"stage":stage,"type":type(e).__name__,"message":str(e)}
 finally:
  signal.signal(signal.SIGUSR1,signal.SIG_IGN);signal.signal(signal.SIGTERM,signal.SIG_IGN)
  if rt:
   try:rt.close()
   except Exception as e:failure=failure or {"stage":"cleanup","type":type(e).__name__,"message":str(e)}
  seen={r["id"] for r in records}
  for r in expected:
   if r["id"] not in seen:
    item=dict(r,status="missing",calls_completed=0,reason=failure or "not completed",clock_scope=clock);records.append(item);pending.append(item)
  checkpoint("final")
  for name,value in (("io-events.json",ios),("gates.json",gates),("cells.json",cells),("events.json",events)):
   write_json(a.output/name,value)
  write_json(a.output/"worker-result.json",{"process":job["process"],"job_sha256":digest(job),"clock_scope":clock,
      "failure":failure,"elapsed_ns":time.perf_counter_ns()-start,"measured":sum(r["status"]=="measured" for r in records),
      "planned":len(expected),"budget_lease_sha256":job["budget_lease_sha256"],"additional_calls":rt.extra if rt else None})
 print(json.dumps({"process":job["process"],"failure":failure,"measured":sum(r["status"]=="measured" for r in records)}),flush=True)
 return 0 if failure is None else 2
if __name__=="__main__":raise SystemExit(main())
