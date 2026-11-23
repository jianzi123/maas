"""P25-AA opt-in protocol. Pure standard library; no GPU imports."""
import argparse,copy,datetime,hashlib,json,re
from pathlib import Path
from cadence_protocol import digest,canonical,write_json
CONFIG={"environment":{"torch":"2.8.0","torch_build":"2.8.0+cu128","CUDA":"12.8","triton":"3.4.0","sglang":"0.5.2","sgl-kernel":"0.3.9.post2","torch_graphs_sha256":"b707ce7ada16e40bed7e588da0ef46b2b31a74a20ad77f4d100a5b89f13f44b9"},"scopes":["full","bare_graph"],"batches":[3,8],"implementations":["native","mature"],
 "aliases":["A","Aprime"],"roles":["boundary_first","interior"],"calls":10,
 "counts":{"reference":48,"holdout":64,"transition":16,"blocks":128,"calls":1280,"alias_pairs":32},
 "capture_order":["native","mature"],"cap":8,"prefill":12,"KV_context":13,"warmup_per_impl_cell":12,
 "stream_abs_tolerance_ns":250000,"stream_relative_tolerance":0.05,
 "legacy_host_gap":{"abs_ns":250000,"relative":0.05,"max_target_ns":500000000,"qualified_by_AA":False},
 "resources":{"GPU":0,"allocator_fraction":0.20,"planner_fraction":0.20,"req":8,"KV":512,"context":128,
  "min_free_bytes":1073741824,"parent_total_seconds":600,"parent_stop_new_seconds":540,
  "child_cleanup_grace_seconds":10,"final_record_reserve_seconds":20,
  "lock":"/var/tmp/maas-10-gpu-01a1a5ba/gpu0-research.lock"},
 "stages":[{"id":"REF","phase":"reference","blocks":56},{"id":"HOLD","phase":"holdout","blocks":72}],
 "extra_calls":{"warmup":192,"gate_forward":32,"extend_prefill":8,"internal_capture":"unknown, all consume parent budget","registry_prepare":16,"readable_input_snapshots":16},
 "claim":"window measurement repeatability only; not zero alias bias/statistical equivalence/NM gain",
 "hot_query":False,"hot_profiler":False,"extra_hot_sync":False,"third_worker":False}
FILES=("test_aa_window.py","aa_protocol.py","aa_runtime.py","aa_worker.py","run_aa_window.py","analyze_aa_window.py","launch_aa_window.py",
 "reference_runtime.py","native_kv_binding.py","analyze_kv_cadence.py","run_decode.py","decode_path.py",
 "cadence_protocol.py","decode-source-lock.json","evidence/framework-v0.18/framework-source-lock.json")
def need(ok,message):
 if not ok:raise ValueError(message)
def stratum(r):return f"{r['scope']}/B{r['batch']}/{r['implementation']}/{r['role']}"
def rows(exp):
 out=[]
 for pi,phase in enumerate(("reference","holdout")):
  proc="REF" if pi==0 else "HOLD"
  for scope in CONFIG["scopes"]:
   for bi,b in enumerate(CONFIG["batches"]):
    cell=f"{proc}/{scope}/B{b}"
    for v in CONFIG["implementations"]:
     out.append(dict(id=f"{exp}/{cell}/transition/{v}",process=proc,phase=phase,scope=scope,batch=b,cell=cell,
        implementation=v,role="cell_transition",alias="A",pair=None,qualify=False,calls=10))
    seen={}
    for pair in range(6 if pi==0 else 8):
     order=list(CONFIG["implementations"])
     if (pair+bi+pi)%2:order.reverse()
     for pos,v in enumerate(order):
      role="boundary_first" if pos==0 else "interior"
      key=(v,role);n=seen.get(key,0);seen[key]=n+1
      flip=(bi+CONFIG["implementations"].index(v)+pos)%2
      alias=CONFIG["aliases"][(n%2)^((n//2)%2)^flip]
      r=dict(id=f"{exp}/{cell}/p{pair}/{v}",process=proc,phase=phase,scope=scope,batch=b,cell=cell,
        implementation=v,role=role,alias=alias,pair=None,qualify=pi==1,calls=10)
      if pi:r["pair"]=f"{exp}/{stratum(r)}/pair{n//2}"
      out.append(r)
 return out
def sources():return {n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in FILES}
def make_plan(exp,commit,enabled=False):
 need(re.fullmatch("[A-Za-z0-9_-]{1,64}",exp) and re.fullmatch("[0-9a-f]{40}",commit),"identity")
 return {"schema":"P25-AA-plan1","experiment":exp,"execution_checkout":commit,
  "execution_enabled":enabled,"created_UTC":datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "config":copy.deepcopy(CONFIG),"rows":rows(exp),"sources":sources()}
def validate(plan):
 need(set(plan)=={"schema","experiment","execution_checkout","execution_enabled","created_UTC","config","rows","sources"},"plan fields")
 need(plan["schema"]=="P25-AA-plan1" and isinstance(plan["execution_enabled"],bool),"plan schema")
 need(re.fullmatch("[A-Za-z0-9_-]{1,64}",plan["experiment"]) and re.fullmatch("[0-9a-f]{40}",plan["execution_checkout"]),"plan identity")
 need(canonical(plan["config"])==canonical(CONFIG) and canonical(plan["rows"])==canonical(rows(plan["experiment"])),"frozen config/order")
 need(plan["sources"]==sources(),"frozen sources")
 return plan
def load(path):return validate(json.loads(Path(path).read_text()))
def match(value,target):
 need(isinstance(target,(int,float)) and target>0,"target")
 limit=max(CONFIG["stream_abs_tolerance_ns"],CONFIG["stream_relative_tolerance"]*target)
 return {"target_stream_ns":target,"error_ns":value-target,"limit_ns":limit,"matched":abs(value-target)<=limit}
def check_budget(lease):
 need(lease["window_id"] and lease["total_seconds"]==600 and lease["stop_new_seconds"]==540,"budget origin")
 need(0<=lease["driver_elapsed_at_send_ns"]<600_000_000_000,"driver elapsed")
 need(0<lease["soft_remaining_ns"]<=540_000_000_000-lease["driver_elapsed_at_send_ns"],"budget reset soft")
 need(lease["soft_remaining_ns"]<lease["hard_remaining_ns"]<=600_000_000_000-lease["driver_elapsed_at_send_ns"],"budget reset hard")
def encode_lease(lease):
 check_budget(lease)
 return json.dumps(lease,sort_keys=True).encode("utf-8")+bytes((10,))
def read_lease(stream):
 line=stream.readline()
 need(line.endswith(chr(10)),"lease framing requires actual LF")
 need(stream.read()=="","exactly one lease frame required")
 lease=json.loads(line);check_budget(lease);return lease
def check_binding(b):
 need(set(b["aliases"])=={"A","Aprime"} and b["aliases"]["A"]==b["aliases"]["Aprime"],"alias identity")
 a=b["aliases"]["A"];need(a["callable_object"]==b["callable_object"] and a["graph_object"]==b["graph_object"],"graph/callable")
 need(b["padded_batch"]==({3:4,8:8}[b["batch"]]) and not b["custom_wrapper"] and not b["eager"],"padding/path")
 need(b["capture_caller_verified"] is True,"capture caller missing")
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--create",action="store_true");p.add_argument("--experiment");p.add_argument("--checkout")
 p.add_argument("--enable-authorized-window",action="store_true");p.add_argument("--plan",type=Path,required=True)
 a=p.parse_args();v=make_plan(a.experiment,a.checkout,a.enable_authorized_window) if a.create else load(a.plan)
 validate(v)
 if a.create:a.plan.parent.mkdir(parents=True,exist_ok=True);write_json(a.plan,v,exclusive=True)
 print(json.dumps({"plan_sha256":digest(v),"blocks":128,"execution_enabled":v["execution_enabled"],"GPU_imports":False}))
if __name__=="__main__":main()
