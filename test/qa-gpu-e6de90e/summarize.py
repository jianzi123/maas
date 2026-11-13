"""Summarize raw QA samples and independently recount CUPTI kernel regions."""
import collections,hashlib,json,math,statistics,sys
from pathlib import Path
root=Path(sys.argv[1]); out=Path(sys.argv[2]); out.mkdir(parents=True,exist_ok=True)
def load(p): return json.loads(p.read_bytes())
commands=load(root/"commands.json")
rows=[]; profiles=[]; validation=[]
for study in ("split","fusion","mature"):
 for i in (1,2,3):
  directory=root/(study+str(i)); r=load(directory/"report.json")
  assert r["seed"]==20261112+i and r["rounds"]==7 and r["correctness_status"]=="passed"
  assert len(r["measurements"])==4
  for m in r["measurements"]:
   if study=="split":
    seen=[]
    for v in m["variants"]:
     md=v["metadata"]; assert len(md["lengths"])<=8 and max(md["lengths"])<=4097 and sum(md["lengths"])<=20000
     seen.append(v["input_hashes"])
     for scope in ("raw_decode","backend"):
      values=[s["event_us_per_call"] for s in v[scope+"_graph_samples"]]
      assert len(values)==7 and all(math.isfinite(x) and x>0 for x in values)
      median=statistics.median(values)
      assert abs(median-v[scope+"_graph_us"]["median"])<1e-8
      rows.append(dict(study=study,process=i,seed=r["seed"],cell=m["id"],variant="cap"+str(v["cap"]),scope=scope,median_us=median,min_us=min(values),max_us=max(values),values=values,actual_splits=md["actual_dynamic_splits"]))
    assert all(x==seen[0] for x in seen),"not identical inputs across cap variants"
   else:
    key="graph_samples" if study=="fusion" else "samples"
    for label,samples in m[key].items():
     values=[s["event_us_per_call"] for s in samples]
     assert len(values)==7 and all(math.isfinite(x) and x>0 for x in values)
     rows.append(dict(study=study,process=i,seed=r["seed"],cell=m["cell"],variant=label.split("_",1)[1],scope=label.split("_",1)[0],median_us=statistics.median(values),min_us=min(values),max_us=max(values),values=values,actual_splits=m["metadata"]["actual_dynamic_splits"]))
  validation.append(dict(study=study,process=i,seed=r["seed"],correctness="passed",independent_process=True))
  if i==1:
   trace=load(directory/"timeline.json")["traceEvents"]
   kernels=[e for e in trace if e.get("cat")=="kernel" and e.get("ph")=="X"]
   annotations=[e for e in trace if e.get("cat")=="user_annotation" and e.get("ph")=="X"]
   report_regions=r["profile"]["regions"]
   for region in report_regions:
    target=region["region"]
    marker=next(e for e in annotations if e["name"]==target or e["name"]=="fusion/"+target or e["name"]=="mature_control/"+target)
    matched=[e for e in kernels if marker["ts"]<=e["ts"]<=marker["ts"]+marker["dur"]]
    count=region.get("kernel_count",region.get("count")); assert len(matched)==count,(study,target,len(matched),count)
    profiles.append(dict(study=study,region=target,kernel_count=len(matched),kernels=dict(collections.Counter(e["name"] for e in matched)),trace_sha256=hashlib.sha256((directory/"timeline.json").read_bytes()).hexdigest(),profile_duration_not_used_in_AB=True))
def vals(study,cell,variant,scope): return [x["median_us"] for x in rows if (x["study"],x["cell"],x["variant"],x["scope"])==(study,cell,variant,scope)]
summary=dict(source_commit="e6de90ef16c64e97d2fd645e78367709abf9e2b3",performance_processes=validation,independent_oracle=load(root/"independent/success.json"),original_graph_checks=len(load(root/"graph/graph-correctness.json")["checks"]),device_fault=load(root/"device-fault/device-fault.json"),process_records=commands,raw_sample_medians=rows,CUPTI_independent_recount=profiles,Engine=False,Sanitizer=False,statistical_significance_claim=False,cross_study_absolute_comparison=False)
(out/"results.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
lines=["| study/cell | variant A (3 process median us) | variant B | B/A |","|---|---|---|---|"]
for cell in ("short","long","mixed","batch8"):
 for study,va,vb,scope in (("split","cap8","cap1","raw_decode"),("fusion","original","fused","backend"),("mature","mature","prototype","backend")):
  x=vals(study,cell,va,scope); y=vals(study,cell,vb,scope)
  lines.append("| "+study+"/"+cell+" | "+va+": "+"/".join(f"{v:.3f}" for v in x)+" | "+vb+": "+"/".join(f"{v:.3f}" for v in y)+" | "+"/".join(f"{b/a:.3f}" for a,b in zip(x,y))+" |")
(out/"comparison.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
print(json.dumps(dict(processes=len(validation),CUPTI_regions=len(profiles),sample_groups=len(rows),exit_codes=[r["exit_code"] for r in commands],split_long_cap1_over_cap8=[b/a for a,b in zip(vals("split","long","cap8","raw_decode"),vals("split","long","cap1","raw_decode"))]),indent=2))
print("\n".join(lines))
