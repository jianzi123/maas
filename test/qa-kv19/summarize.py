"""Independent raw trace and newly generated full logits/all-layer KV checks."""
import json,hashlib,collections,sys
from pathlib import Path
import numpy as np
root=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(exist_ok=True)
def load(p):return json.loads(p.read_bytes())
def equal(a,b):
 assert a.dtype==b.dtype and a.dtype in (np.float16,np.float32) and a.shape==b.shape and np.isfinite(a).all() and np.isfinite(b).all()
 assert np.array_equal(a.view(np.uint16 if a.dtype==np.float16 else np.uint32),b.view(np.uint16 if b.dtype==np.float16 else np.uint32))
regions=[];clones=[]
for variant in ("native","mature","late"):
 r=load(root/variant/"framework.json");integ=load(root/variant/"integration.json")
 assert integ["status"]=="passed" and len(r["records"])==12 and r["caps"]["planner_mem_fraction_static"]==.2
 assert all(x["before"]==x["after"]==dict(req_free=8,kv_free=512) for x in r["pool_checks"])
 es=load(root/variant/"timeline.json")["traceEvents"];ks=[e for e in es if e.get("cat")=="kernel"]
 for e in es:
  if e.get("cat")!="user_annotation" or not e["name"].startswith("framework/"):continue
  found=[k for k in ks if e["ts"]<=k["ts"] and k["ts"]+k.get("dur",0)<=e["ts"]+e["dur"]]
  writes=[k for k in found if "index_elementwise_kernel" in k["name"]];stores=[k for k in found if "store_kv_cache" in k["name"]]
  fused=variant=="mature" or (variant=="late" and not e["name"].endswith("/graph"))
  assert (len(writes),len(stores))==((0,30) if fused else (60,0))
  streams=collections.Counter(k["args"]["stream"] for k in writes+stores)
  assert len(streams)==(1 if fused or not e["name"].endswith("/graph") else 2)
  regions.append(dict(variant=variant,region=e["name"],total=len(found),index=len(writes),store=len(stores),write_streams=dict(streams)))
a=np.load(root/"native/logits.npz",allow_pickle=False)
for variant in ("mature","late"):
 b=np.load(root/variant/"logits.npz",allow_pickle=False);assert set(a.files)==set(b.files)=={"decode%02d"%i for i in range(12)}
 for k in a.files:equal(a[k],b[k]);clones.append(dict(variant=variant,key=k,bitwise=True,shape=list(a[k].shape)))
na=np.load(root/"state-native/kv-states.npz",allow_pickle=False);mb=np.load(root/"state-mature/kv-states.npz",allow_pickle=False)
def keys_equal(left,right):
 assert set(left)==set(right)=={t+"%02d"%i for t in ("k","v") for i in range(12)}
keys_equal(na.files,mb.files)
states=[];controls=[]
for k in sorted(na.files):
 equal(na[k],mb[k]);assert na[k].dtype==np.float16 and na[k].shape[0]==30
 states.append(dict(key=k,shape=list(na[k].shape),bitwise=True))
 try:equal(na[k],np.zeros_like(mb[k]))
 except AssertionError:controls.append(dict(key=k,mutation="zero",rejected=True))
 else:raise AssertionError("zero escaped")
for t in ("k","v"):
 for i in range(0,10,2):
  k=t+"%02d"%(i+1);old=t+"%02d"%i
  try:equal(na[k],mb[old])
  except AssertionError:controls.append(dict(key=k,mutation="stale",rejected=True))
  else:raise AssertionError("stale escaped")
# Additional comparator shape, dtype, finite, bit corruption and missing-key gates.
key="k00";ref=na[key]
bad=[("shape",ref.reshape(-1)),("dtype",ref.astype(np.float32))]
x=ref.copy();x.flat[0]=np.nan;bad.append(("nan",x))
x=ref.copy();x.view(np.uint16).flat[0]^=np.uint16(1);bad.append(("one-bit",x))
for name,x in bad:
 try:equal(ref,x)
 except AssertionError:controls.append(dict(key=key,mutation=name,rejected=True))
 else:raise AssertionError(name+" escaped")
missing=set(mb.files)-{key}
try:keys_equal(na.files,missing)
except AssertionError:controls.append(dict(mutation="missing-key",rejected=True))
else:raise AssertionError("missing key escaped")
n=load(root/"state-native/qa-state.json");m=load(root/"state-mature/qa-state.json")
assert n["parameter_sha256"]==m["parameter_sha256"]
for variant in ("native","mature"):
 state=load(root/("state-"+variant)/"qa-state.json");assert len(state["rows"])==12 and all(x["non_target_real_slots_bitwise_unchanged"] for x in state["rows"])
 fresh=np.load(root/("state-"+variant)/"independent-logits.npz",allow_pickle=False)
 regular=np.load(root/variant/"logits.npz",allow_pickle=False)
 for k in fresh.files:equal(fresh[k],regular[k])
event=load(root/"event-support/result.json");assert len(event["rows"])==2 and len(event["rejected"])==5 and event["original_method_restored"]
result=dict(candidate="19e63a1999c1c9b54e532f7d8afd6473bf2836bc",regions=regions,logit_comparisons=clones,KV_arrays=states,offline_negative_controls=controls,offline_controls_are_not_GPU_fault_injection=True,parameter_sha256=n["parameter_sha256"],event_support=event,commands=load(root/"commands.json"),stable_cost_gain=False,Engine=False)
(out/"results.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(dict(logits=len(clones),KV=len(states),negative_controls=len(controls),regions=regions),indent=2))
