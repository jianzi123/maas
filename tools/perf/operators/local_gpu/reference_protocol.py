"""E-LIT-01 representative-template qualification only; no CUDA imports here."""
import argparse,copy,datetime,hashlib,json,re
from pathlib import Path
from cadence_protocol import canonical,digest,write_json

FILES=("reference_protocol.py","reference_runtime.py","bench_cadence_reference.py",
       "analyze_cadence_reference.py","analyze_kv_cadence.py","cadence_protocol.py",
       "native_kv_binding.py","run_decode.py","bench_kv_interleaved.py",
       "decode-source-lock.json","evidence/framework-v0.18/framework-source-lock.json")
CONFIG={
 "scopes":["full","bare_graph"],"batches":[3,8],"variants":["native","mature"],
 "roles":["boundary_first","interior"],"KV_context_length":13,"prefill_length":12,
 "calls_per_block":10,"warmup_calls_per_variant":12,
 "reference_pairs_per_cell":6,"holdout_pairs_per_cell":8,
 "reference_samples_per_stratum":3,"holdout_samples_per_stratum_per_mode":2,
 "match_abs_ns":250000,"match_relative":0.05,"max_target_ns":500000000,
 "qualification":"all64 planned holdout rows must be measured, intact and within common per-stratum target",
 "target_rule":"median of3 reference query completion-to-submit gaps per(scope,B,variant,role); same target for both modes",
 "transition_rule":"2 timed transitions per cell/phase, planned and retained, excluded from qualification by design",
 "previous_done_rule":"initialize once at boot event; thereafter update ONLY to actual recorded hot-block completion; never reset at cell/freeze/IO",
 "boundary_rule":"same real ledger write+flush+fsync and resource/host checks before boundary_first, no archive between interior pair",
 "bookkeeping_rule":"same raw row construction, CUDA elapsed read and canonical serialization for every phase/mode; no matching calculations in chain",
 "counts":{"reference":48,"holdout":64,"transition":16,"total_blocks":128,"hot_calls":1280,"strata":16},
 "resources":{"GPU":0,"allocator_fraction":0.20,"planner_fraction":0.20,"req":8,"KV":512,"context":128,
              "min_free_bytes":1073741824,"total_GPU_wall_seconds":600,"internal_stop_seconds":540,
              "lock":"/var/tmp/maas-10-gpu-01a1a5ba/gpu0-research.lock","default_cap":8},
 "no_main_comparison":True,"no_retry_or_extra_sampling":True}

def schedule(exp):
 result=[]
 modes=("query","idle","idle","query","query","idle","idle","query")
 for phase in ("reference","holdout"):
  for scope in CONFIG["scopes"]:
   for bi,b in enumerate(CONFIG["batches"]):
    cell=f"{phase}/{scope}/B{b}"
    for v in CONFIG["variants"]:
     result.append({"id":f"{exp}/{cell}/transition/{v}","phase":phase,"scope":scope,"batch":b,
       "cell":cell,"variant":v,"role":"cell_transition","mode":"none","pair":None,"calls":10,"qualify":False})
    n=6 if phase=="reference" else 8
    for pair in range(n):
     order=list(CONFIG["variants"])
     if (pair+bi+(phase=="holdout"))%2:order.reverse()
     for pos,v in enumerate(order):
      mode="query" if phase=="reference" else modes[(pair+4*bi)%8]
      result.append({"id":f"{exp}/{cell}/p{pair}/{v}","phase":phase,"scope":scope,"batch":b,
       "cell":cell,"variant":v,"role":"boundary_first" if pos==0 else "interior",
       "mode":mode,"pair":pair,"calls":10,"qualify":phase=="holdout"})
 return result

def stratum(row):
 return f"{row['scope']}/B{row['batch']}/{row['variant']}/{row['role']}"

def make_plan(exp,commit):
 if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",exp) or not re.fullmatch(r"[0-9a-f]{40}",commit):
  raise ValueError("identity")
 return {"schema":"ELIT01-reference-window1","experiment":exp,"checkout":commit,
  "created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "config":copy.deepcopy(CONFIG),"rows":schedule(exp),
  "sources":{n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in FILES}}

def validate(p):
 if set(p)!={"schema","experiment","checkout","created_utc","config","rows","sources"} or p["schema"]!="ELIT01-reference-window1":
  raise ValueError("schema/fields")
 if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",p["experiment"]) or not re.fullmatch(r"[0-9a-f]{40}",p["checkout"]):
  raise ValueError("identity")
 datetime.datetime.fromisoformat(p["created_utc"])
 if canonical(p["config"])!=canonical(CONFIG) or canonical(p["rows"])!=canonical(schedule(p["experiment"])):
  raise ValueError("frozen config/schedule")
 if set(p["sources"])!=set(FILES):raise ValueError("sources")
 for n,h in p["sources"].items():
  if hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest()!=h:raise ValueError("source bytes: "+n)
 return p

def load(path):return validate(json.loads(Path(path).read_text(encoding="utf-8")))

def match(gap,target):
 err=gap-target
 limit=max(CONFIG["match_abs_ns"],CONFIG["match_relative"]*target)
 return {"gap_ns":gap,"target_ns":target,"error_ns":err,"limit_ns":limit,"matched":abs(err)<=limit}

def main():
 a=argparse.ArgumentParser(description=__doc__)
 a.add_argument("--create",action="store_true");a.add_argument("--experiment");a.add_argument("--checkout")
 a.add_argument("--plan",type=Path,required=True)
 x=a.parse_args()
 p=make_plan(x.experiment,x.checkout) if x.create else load(x.plan)
 validate(p)
 if x.create:x.plan.parent.mkdir(parents=True,exist_ok=True);write_json(x.plan,p,exclusive=True)
 print(json.dumps({"plan_sha256":digest(p),"planned_rows":len(p["rows"]),"qualification_only":True}))
if __name__=="__main__":main()
