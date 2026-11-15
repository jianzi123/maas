"""Independently recompute cap6 samples, partition and CUPTI grid."""
import json,math,statistics,sys,hashlib
from pathlib import Path
root=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(exist_ok=True)
def load(p):return json.loads(p.read_bytes())
results=[];regions=[]
for i in (1,2,3):
 r=load(root/("run"+str(i))/"report.json")
 assert r["rounds"]==9 and r["iterations"]==40 and r["seed"]==20261113+i and r["correctness_status"]=="passed"
 for m in r["measurements"]:
  for cap in ("8","6"):
   v=m["partition"][cap];lengths=m["lengths"];splits=v["splits"]
   chunks=[32*((((n+s-1)//s)+31)//32) for n,s in zip(lengths,splits)]
   assert chunks==v["chunk_lengths"] and v["launched_CTAs"]==8*3*int(cap)
   if m["case"]=="b8_l1024":assert splits==[6]*8 and chunks==[192]*8 and v["nonempty_CTAs"]==144
   for scope in ("raw","backend"):
    values=[v["event_us_per_call"] for v in m["samples"][cap][scope]]
    assert len(values)==9 and all(math.isfinite(x) and x>0 for x in values)
    assert statistics.median(values)==m["median_us"][cap][scope]["median"]
  for scope in ("raw","backend"):
   med={c:statistics.median([v["event_us_per_call"] for v in m["samples"][c][scope]]) for c in ("8","6")}
   results.append(dict(process=i,case=m["case"],scope=scope,cap8_us=med["8"],cap6_us=med["6"],ratio=med["6"]/med["8"],same_partition=m["same_partition"],partition=m["partition"]))
 if i==1:
  events=load(root/"run1/timeline.json")["traceEvents"]
  kernels=[e for e in events if e.get("cat")=="kernel"]
  for e in events:
   if e.get("cat")!="user_annotation" or not e["name"].startswith("cap6/"):continue
   _,case,cap,scope=e["name"].split("/")
   found=[k for k in kernels if e["ts"]<=k["ts"] and k["ts"]+k.get("dur",0)<=e["ts"]+e["dur"]]
   assert len(found)==(80 if scope=="graph_raw" else 2)
   stage=[k for k in found if "grouped_kernel_stage1" in k["name"]]
   assert all(k["args"]["grid"]==[8,3,int(cap)] for k in stage)
   regions.append(dict(region=e["name"],count=len(found),stage1_grid=stage[0]["args"]["grid"],CTA=24*int(cap)))
assert len(regions)==16
s=dict(commit="6517a152d67f21ce3fcb11bddf76cf79b3e6c42c",commands=load(root/"commands.json"),oracle=load(root/"oracle/results.json"),environment=load(root/"oracle/environment.json"),paired_medians=results,CUPTI=regions,Engine=False,cross_environment_absolute_comparison=False)
(out/"results.json").write_text(json.dumps(s,indent=2)+"\n")
lines=["| case / scope | cap6/cap8 (3 process medians) |","|---|---|"]
for case in ("b8_l512","b8_l1024","b8_l2048","b8_ragged"):
 for scope in ("raw","backend"):
  v=[r["ratio"] for r in results if r["case"]==case and r["scope"]==scope]
  lines.append("| "+case+" / "+scope+" | "+"/".join("%.4f"%x for x in v)+" |")
(out/"comparison.md").write_text("\n".join(lines)+"\n")
print("\n".join(lines))
print("CUPTI",len(regions),"wheel full independently verified",s["environment"]["full_wheel_reverified"])
