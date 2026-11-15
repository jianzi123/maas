"""Independent raw E-LIT-01 audit. CPU only; no torch/CUDA imports or collection."""
import argparse,hashlib,json,statistics,math,csv,io,subprocess,shutil,collections
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=Path("elit-qa/audit"));a=p.parse_args()
out=a.output;out.mkdir(parents=True,exist_ok=False);root=Path("elit-input/evidence");source=Path("elit-source/tools/perf/operators/local_gpu")
def load(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(x):return sha(json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False).encode())
def lines(p):return [json.loads(x) for x in p.read_text().splitlines() if x]
def git(*args):return subprocess.check_output(["git","-C","maas",*args])
delivery=load(Path("elit-input/delivery-manifest.json"))
for r in delivery["packages"][:2]:assert sha(Path("elit-input",r["file"]).read_bytes())==r["sha256"]
counts={}
for directory,file in (("code","manifest.json"),("evidence","evidence-manifest.json")):
 m=load(Path("elit-input",directory,file));counts[directory]=len(m["files"])
 for r in m["files"]:
  assert sha(Path("elit-input",directory,r["path"]).read_bytes())==r["sha256"]
  if directory=="code":assert sha(git("show","5f8bd5d:"+r["path"]))==r["sha256"]
for parent,child in (("4fbb921","6477d5d"),("6477d5d","6933fed"),("6933fed","5f8bd5d")):
 subprocess.run(["git","-C","maas","merge-base","--is-ancestor",parent,child],check=True)
plan=load(root/"plan.json")
assert digest(plan)=="ab0ac451d9d4beffd6a879ff04bcdcd4000a256ec3194b710f5e7dabca49d9c9"
assert sha((root/"plan.json").read_bytes())=="c42a4755b426fe964b7423ffb6cf4001e75f42bc52bf9ff018de6184a58c52c7"
for n,h in plan["source_sha256"].items():
 assert sha((source/n).read_bytes())==h==sha(git("show","6477d5d:tools/perf/operators/local_gpu/"+n))
schedule=plan["schedule"];assert len(schedule)==108
planned={b["block_id"]:(b,c) for c in schedule for b in c["blocks"]};assert len(planned)==1080
rows=[];matches=collections.Counter();groups={};strata={};queries_total=0;npz_refs=0;unique_npz=set();gate_count=0;params=[];clocks=[];full_cost=[]
for run in ("R01","R02"):
 folder=root/run;runtime=load(folder/"runtime-manifest.json");cal=load(folder/"calibration.json");cells=load(folder/"cells.json")
 assert runtime["run_id"]==run and runtime["plan_sha256"]==digest(plan) and runtime["source_sha256"]==plan["source_sha256"]
 assert runtime["execution_checkout_commit"].startswith("6477d5d") and digest(cal)==runtime["calibration_sha256"]
 params.append((runtime["parameter_full_sha256"],runtime["model_config_sha256"]));clocks.append(runtime["clock_scope"])
 q=lines(folder/"queries.jsonl");qm={x["query_id"]:x for x in q};assert len(qm)==len(q)==218;queries_total+=len(q)
 for x in q:
  assert x["clock_scope"]==runtime["clock_scope"] and x["end_ns"]>=x["begin_ns"] and x["duration_ns"]==x["end_ns"]-x["begin_ns"]
  assert x["result"]["returncode"]==0
  parsed=list(csv.reader(io.StringIO(x["result"]["csv"])));assert len(parsed)==1 and len(parsed[0])==len(x["result"]["fields"])==8
 for variant in ("native","mature"):
  samples=[x for x in cal if x["variant"]==variant];assert len(samples)==10
  assert int(statistics.median(x["submit_proxy_ns"]-x["previous_done_ns"] for x in samples))==runtime["targets_ns"][variant]
 for x in cal:
  query=qm[x["query_id"]]
  assert x["previous_done_ns"]<=x["ready_ns"]<=query["begin_ns"]<=query["end_ns"]<=x["submit_proxy_ns"]<=runtime["frozen_at_monotonic_ns"]
  assert x["total_gap_ns"]==x["submit_proxy_ns"]-x["previous_done_ns"] and x["query_duration_ns"]==query["duration_ns"]
 cm={c["cell_id"]:c for c in cells};assert len(cm)==6
 ledger=lines(folder/"blocks.jsonl");assert len(ledger)==540
 previous={}
 for r in ledger:
  b,c=planned[r["block_id"]]
  assert all(r[k]==b[k] for k in ("pair_id","variant","slot","pair","calls_planned"))
  assert all(r[k]==c[k] for k in ("cluster_id","triplet_id","run_id","scope","batch","policy","rotation","strategy_position"))
  assert r["run_id"]==run and r["clock_scope"]==runtime["clock_scope"] and r["runtime_manifest_sha256"]==digest(runtime)
  cell=cm[f"{run}/{r['scope']}/B{r['batch']}"];assert r["cell_sha256"]==digest(cell) and cell["runtime_manifest_sha256"]==digest(runtime)
  prior,ready,submit,enq,done=[r[k] for k in ("previous_done_ns","ready_ns","submit_ns","enqueue_end_ns","done_ns")]
  assert runtime["frozen_at_monotonic_ns"]<=cell["frozen_at_monotonic_ns"]<=prior<=ready<=submit<=enq<=done
  chain=(r["scope"],r["batch"])
  if chain in previous:assert prior==previous[chain] and r["previous_kind"]=="previous_measured_block_completion"
  previous[chain]=done
  assert r["wall_ns"]==done-submit and r["host_enqueue_ns"]==enq-submit and r["wait_ns"]==done-enq
  assert r["preparation_ns"]==ready-prior and r["ready_to_submit_ns"]==submit-ready
  assert r["status"]=="measured" and r["calls_completed"]==r["calls_planned"]==10
  assert all(type(r[k]) in (int,float) and math.isfinite(r[k]) and r[k]>0 for k in ("event_ns","wall_ns","host_enqueue_ns","wait_ns","thread_cpu_ns"))
  target=runtime["targets_ns"][r["variant"]];error=submit-prior-target;tol=max(250000,.05*target);matched=abs(error)<=tol
  expected=dict(actual_gap_ns=submit-prior,target_gap_ns=target,error_ns=error,relative_error=error/target,tolerance_ns=tol,matched=matched)
  assert r["gap_match"]==expected
  if r["policy"]=="query_block" or (r["policy"]=="query_cluster" and r["slot"]==0):
   query=qm[r["query_id"]];assert r["query_id"]==r["block_id"]+"/query"
   assert ready<=query["begin_ns"]==r["query_begin_ns"]<=query["end_ns"]==r["query_end_ns"]<=submit
  else:assert r["query_id"] is None
  if r["policy"]=="idle_matched":
   assert ready<=r["sleep_begin_ns"]<=r["sleep_end_ns"]<=submit
   assert r["sleep_requested_ns"]==max(0,prior+target-r["sleep_begin_ns"])
  if r["policy"]!="query_cluster":matches[(r["policy"],"total")]+=1;matches[(r["policy"],"matched")]+=matched
  key=(run,r["scope"],r["batch"],r["policy"],r["variant"],"boundary" if r["slot"]==0 else "within")
  strata.setdefault(key,[]).append(error)
  groups.setdefault(r["cluster_id"],[]).append(matched);rows.append(r)
 clusters=load(folder/"clusters.json");assert len(clusters)==54
 for c in clusters:
  lr=[r for r in ledger if r["cluster_id"]==c["cluster_id"]];assert len(lr)==10 and sum(r["calls_completed"] for r in lr)==100
  assert c["elapsed_ns"]==c["end_ns"]-c["begin_ns"] and c["end_ns"]==lr[-1]["done_ns"] and c["begin_ns"]<=lr[0]["ready_ns"]
  assert c["elapsed_ns"]>=sum(r["wall_ns"] for r in lr)
  full_cost.append(dict(cluster_id=c["cluster_id"],scope=c["scope"],full_cluster_ms_per_100_calls=c["elapsed_ns"]/1e6,cost_us_per_call=c["elapsed_ns"]/100/1000))
 gates=load(folder/"gates.json");assert len(gates)==13
 identities=set()
 for gate in gates:
  identity=(run,gate["cell_id"],gate["phase"]);assert identity not in identities;identities.add(identity)
  assert gate["status"]=="passed" and gate["all30_layers"] and set(gate["snapshots"])=={"native","mature"}
  vectors={}
  for variant,refs in gate["snapshots"].items():
   assert len(refs)==2
   vectors[variant]=[]
   for idx,ref in enumerate(refs):
    path=(folder/ref["path"]).resolve();path.relative_to(folder.resolve())
    with np.load(path,allow_pickle=False) as archive:
     assert archive.files==["value"];arr=archive["value"];assert np.isfinite(arr).all() and list(arr.shape)==ref["shape"] and str(arr.dtype)==ref["dtype"]
     assert sha(arr.tobytes())==ref["raw_sha256"]
     assert arr.dtype==(np.float32 if idx==0 else np.float16)
     assert arr.ndim==(2 if idx==0 else 5) and (idx==0 or tuple(arr.shape[:2])==(30,2))
     vectors[variant].append(arr.copy());npz_refs+=1;unique_npz.add((run,str(path)))
  for n,m in zip(vectors["native"],vectors["mature"]):assert n.dtype==m.dtype and n.shape==m.shape and n.tobytes()==m.tobytes()
  gate_count+=1
assert len(set(x["block_id"] for x in rows))==1080 and sum(x["calls_completed"] for x in rows)==10800
assert len(set(params))==1 and len(set(clocks))==2 and queries_total==436 and gate_count==26
assert matches[("query_block","matched")]==72 and matches[("idle_matched","matched")]==342
full=[c for c in schedule if c["scope"]=="full"];triplet_ids={c["triplet_id"] for c in full}
qualified=0
for tid in triplet_ids:
 cs=[c for c in full if c["triplet_id"]==tid];assert {c["policy"] for c in cs}=={"query_block","query_cluster","idle_matched"}
 qualified+=all(all(groups[c["cluster_id"]]) for c in cs if c["policy"]!="query_cluster")
assert len(triplet_ids)==18 and qualified==0
# Exercise the original CLI using real data and independent derived corruptions.
analyzer=(source/"analyze_kv_cadence.py").resolve();plan_path=(root/"plan.json").resolve();commands=[]
def cli(folder,target):
 cp=subprocess.run(["python",str(analyzer),"--plan",str(plan_path),"--root",str(folder.resolve()),"--output",str(target.resolve())],capture_output=True,text=True)
 commands.append(dict(case=folder.name,exit_code=cp.returncode,stdout=cp.stdout,stderr=cp.stderr,success_report=target.exists()))
 return cp.returncode
assert cli(root,out/"normal.json")==0
for mode in ("clock","nan","matching","duplicate","empty_gate","hidden_R02"):
 folder=out/mode;folder.mkdir()
 for run in ("R01","R02"):
  if mode=="hidden_R02" and run=="R02":continue
  shutil.copytree(root/run,folder/run)
 if mode in ("clock","nan","matching","duplicate"):
  data=lines(folder/"R01/blocks.jsonl")
  if mode=="clock":data[0]["clock_scope"]="foreign"
  elif mode=="nan":data[0]["wall_ns"]=float("nan")
  elif mode=="matching":data[0]["gap_match"]["matched"]=not data[0]["gap_match"]["matched"]
  else:data.append(data[0].copy())
  (folder/"R01/blocks.jsonl").write_text("".join(json.dumps(x)+"\n" for x in data))
 if mode=="empty_gate":
  data=load(folder/"R01/gates.json");data[0]["snapshots"]={"native":[],"mature":[]};(folder/"R01/gates.json").write_text(json.dumps(data))
 target=folder/"report.json";rc=cli(folder,target)
 if mode in ("clock","nan","matching","duplicate"):assert rc!=0 and not target.exists()
 elif mode=="hidden_R02":
  assert rc==0;z=load(target);assert z["planned_blocks"]==1080 and z["block_status_counts"]=={"measured":540,"missing":540}
 # empty_gate outcome is recorded as a possible new fail-open, never waived.
r=dict(candidate="5f8bd5d83968f9ed5e674593bb8d19078c4575ad",manifests=counts,canonical_plan_sha256=digest(plan),clusters=108,measured_blocks=1080,missing=0,invalid=0,calls=10800,query_events=436,gate_events=gate_count,snapshot_references=npz_refs,unique_snapshot_paths=len(unique_npz),matching={p:dict(matched=matches[(p,"matched")],total=matches[(p,"total")]) for p in ("query_block","idle_matched")},strict_full_groups=dict(qualified=qualified,denominator=18),strata=[dict(run=k[0],scope=k[1],batch=k[2],policy=k[3],variant=k[4],role=k[5],count=len(v),median_error_ns=statistics.median(v),max_abs_error_ns=max(map(abs,v))) for k,v in strata.items()],cluster_costs=full_cost,commands=commands,empty_gate_rejected=next(x for x in commands if x["case"]=="empty_gate")["exit_code"]!=0,gate_timestamp_limitation="run/cell/phase references exist, but no separate per-gate monotonic timestamp; equal content hashes do not identify a collection event",GPU_executed=False,root_cause_or_gain_established=False)
r["overall"]="needs_fix" if not r["empty_gate_rejected"] else "passed"
r["open_defect"]="ELIT-QA-01: missing all vectors in one gate accepted by original analyzer" if not r["empty_gate_rejected"] else None
(out/"results.json").write_text(json.dumps(r,indent=2)+"\n")
print(json.dumps({k:r[k] for k in ("clusters","measured_blocks","calls","query_events","gate_events","snapshot_references","unique_snapshot_paths","matching","strict_full_groups","empty_gate_rejected")},indent=2))

raise SystemExit(0 if r["empty_gate_rejected"] else 1)
