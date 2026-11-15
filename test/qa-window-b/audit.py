"""Window B independent offline audit. No GPU or cost execution."""
from pathlib import Path
import json,hashlib,subprocess,statistics,math,copy,tarfile,io
base=Path("wb-input");e=base/"evidence";import argparse
parser=argparse.ArgumentParser()
parser.add_argument("--output",type=Path,default=Path("wb-summary-final"))
out=parser.parse_args().output;out.mkdir(exist_ok=True)
def load(p):return json.loads(p.read_bytes())
def git(*args):return subprocess.check_output(["git","-C","maas",*args])
delivery=load(base/"delivery-manifest.json")
for row in delivery["packages"][:2]:assert hashlib.sha256((base/row["file"]).read_bytes()).hexdigest()==row["sha256"]
manifests={}
for directory,file in (("code","manifest.json"),("evidence","evidence-manifest.json")):
 m=load(base/directory/file);manifests[directory]=len(m["files"])
 for row in m["files"]:
  assert hashlib.sha256((base/directory/row["path"]).read_bytes()).hexdigest()==row["sha256"]
  if directory=="code":assert hashlib.sha256(git("show","bf319d6:"+row["path"])).hexdigest()==row["sha256"]
for ancestor,child in (("8dbf99e","dcc5a53"),("dcc5a53","7315b32"),("7315b32","bf319d6")):subprocess.run(["git","-C","maas","merge-base","--is-ancestor",ancestor,child],check=True)
changes=git("diff","--name-only","dcc5a53","7315b32").decode().splitlines()
assert all(p.startswith(("docs/performance/","tools/perf/")) for p in changes)
locks=set(git("diff","--name-only","7315b32","bf319d6").decode().splitlines())
assert locks=={"deploy/build-sources.lock.json","deploy/dependencies.lock.json","deploy/identities.json","deploy/charts/maas-platform/runtime-interface.json"}
lock=load(Path("wb-source/deploy/build-sources.lock.json"))
with tarfile.open(fileobj=io.BytesIO(git("archive","--format=tar","bf319d6"))) as archive:
 for component in ("backend","console"):
  assert lock[component]["sourceCommit"].startswith("7315b32")
  for path,h in lock[component]["files"].items():assert hashlib.sha256(archive.extractfile(path).read()).hexdigest()==h
paired=[];gates=[];ratio_rows=[]
for name in ("paired-native-first","paired-mature-first"):
 d=load(e/name/"window-b.json");assert d["status"]=="passed" and not d["profile_only"] and len(d["blocks"])==120
 for n,h in d["code_sha256"].items():assert hashlib.sha256(git("show","7315b32:tools/perf/operators/local_gpu/"+n)).hexdigest()==h
 for batch in (3,5,8):
  seen=[x for x in d["gates"] if x["batch"]==batch]
  assert {x["phase"] for x in seen}=={"before_cost","after_full","after_bare_graph"}
  assert len({x["logits_sha256"] for x in seen})==1 and len({x["KV_sha256"] for x in seen})==1
  assert all(x["all30_layers"] and x["finite_bitwise_equal"] for x in seen);gates.extend(seen)
  for scope in ("full","bare_graph"):
   vals=[]
   for cycle in range(10):
    pair=[x for x in d["blocks"] if (x["batch"],x["scope"],x["cycle"])==(batch,scope,cycle)]
    assert len(pair)==2 and {x["variant"] for x in pair}=={"native","mature"}
    expect=("native","mature") if cycle%2==0 else ("mature","native")
    assert all(x["position"]==expect.index(x["variant"]) for x in pair)
    for x in pair:
     for field in ("wall_with_sync_us","event_with_host_gaps_us","host_enqueue_us","host_thread_cpu_us","wait_us"):assert type(x[field]) in (int,float) and math.isfinite(x[field]) and x[field]>0
    p={x["variant"]:x for x in pair};ratio=p["mature"]["wall_with_sync_us"]/p["native"]["wall_with_sync_us"];vals.append(ratio);paired.append(ratio)
   ratio_rows.append(dict(process=name,batch=batch,scope=scope,all_ratios=vals,median_paired_ratio=statistics.median(vals),slower=sum(x>1 for x in vals)))
assert len(paired)==120 and sum(x>1 for x in paired)==33 and len(gates)==18
controls=sum(len(m["samples"]) for v in ("native","mature") for m in load(e/("isolated-"+v)/"cost.json")["measurements"]);assert controls==54
# Strict analyzer success plus four independently mutated inputs, no GPU.
analyzer=Path("wb-source/tools/perf/operators/local_gpu/analyze_kv_window_b.py").resolve()
commands=[]
def run_analyzer(source,target):
 cp=subprocess.run(["python",str(analyzer),"--input",str(source.resolve()),"--output",str(target.resolve())],capture_output=True,text=True)
 commands.append(dict(input=str(source),exit_code=cp.returncode,stdout=cp.stdout,stderr=cp.stderr,report_exists=target.exists()))
 return cp.returncode
assert run_analyzer(e,out/"author-analyzer.json")==0
for mode in ("missing","nan","duplicate","profile"):
 path=out/("negative-"+mode);path.mkdir(exist_ok=False)
 for n in ("paired-native-first","paired-mature-first","isolated-native","isolated-mature"):
  (path/n).mkdir();filename="window-b.json" if n.startswith("paired") else "cost.json"
  d=load(e/n/filename)
  if n=="paired-native-first":
   if mode=="missing":d["blocks"].pop()
   elif mode=="nan":d["blocks"][0]["wall_with_sync_us"]=float("nan")
   elif mode=="duplicate":d["blocks"][1]["variant"]=d["blocks"][0]["variant"]
   else:d["profile_only"]=True
  (path/n/filename).write_text(json.dumps(d))
 target=path/"success.json";assert run_analyzer(path,target)!=0 and not target.exists()
def graph_rows(path,prefix,variant=None):
 events=load(path)["traceEvents"];rows=[]
 for region in events:
  if region.get("cat")!="user_annotation" or not region.get("name","").startswith(prefix):continue
  if variant is not None and not region["name"].endswith("/graph"):continue
  api=[x for x in events if x.get("cat")=="cuda_runtime" and x["name"]=="cudaGraphLaunch" and region["ts"]<=x["ts"]<=region["ts"]+region["dur"]]
  assert len(api)==1;corr=api[0]["args"]["correlation"]
  pure=[x for x in events if x.get("cat")=="kernel" and x.get("args",{}).get("correlation")==corr]
  all_region=[x for x in events if x.get("cat")=="kernel" and region["ts"]<=x["ts"] and x["ts"]+x.get("dur",0)<=region["ts"]+region["dur"]]
  mature=(variant=="mature") if variant else "mature" in region["name"]
  assert len(pure)==(334 if mature else 364)
  assert sum("store_kv_cache" in x["name"] for x in pure)==(30 if mature else 0)
  assert sum("index_elementwise_kernel" in x["name"] for x in pure)==(0 if mature else 60)
  rows.append(dict(region=region["name"],pure_graph=len(pure),region_total=len(all_region),outside_graph=len(all_region)-len(pure),correlation=corr))
 return rows
new_trace=graph_rows(e/"profile-native-first/timeline.json","windowB/")
old_trace=[]
for v in ("native","mature"):old_trace+=graph_rows(Path("kv19-qa")/v/"timeline.json","framework/",v)
assert len(new_trace)==4 and len(old_trace)==4 and all(x["outside_graph"]==14 for x in old_trace)
for row in load(e/"retained-costs.json"):
 assert hashlib.sha256(git("show","19e63a1:"+row["path"])).hexdigest()==row["sha256"]
 assert hashlib.sha256((e/"retained-v0.19"/Path(row["path"]).name).read_bytes()).hexdigest()==row["sha256"]
r=dict(candidate="bf319d6172d595140bf7ff86a67c589b1d5877b6",provenance=delivery["provenance"],manifests=manifests,source_inventory={k:len(lock[k]["files"]) for k in ("backend","console")},
 clean_blocks=240,paired_cycles=120,adverse_pairs=33,gates=18,independent_control_blocks=controls,ratios=ratio_rows,analyzer_commands=commands,new_pure_graph=new_trace,old_region_correction=old_trace,
 stable_gain_established=False,drift_cause="unknown",GPU_cost_rerun=False)
(out/"audit.json").write_text(json.dumps(r,indent=2)+"\n")
print(json.dumps({k:r[k] for k in ("manifests","source_inventory","clean_blocks","paired_cycles","adverse_pairs","gates","independent_control_blocks","old_region_correction")},indent=2))
