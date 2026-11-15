"""Independently inspect native structure, output negative controls and raw CUPTI."""
from pathlib import Path
import json,hashlib,collections,subprocess
root=Path("native-qa");out=Path("native-summary");out.mkdir(exist_ok=True)
def load(p):return json.loads(p.read_bytes())
r=load(root/"native/framework.json");assert r["status"]=="passed" and r["native_dummy_loader_called"] and r["parameter_count"]==134515008
assert r["captured_sizes"]==[1,2,4,8] and r["engine_default_kv_splits"]==8
assert len(r["records"])==12 and r["native_nondefault_stream_scenario_passed"]
assert all(x["rejected"] for x in r["qa_negative_controls"]) and len(r["qa_negative_controls"])==19
for row in r["records"]:
 assert row["captured_batch"]==next(x for x in (1,2,4,8) if x>=row["raw_batch"])
 assert row["clone_preserved_before_reference"] and row["input_buffers_stable"] and row["output_aliases_native_graph_buffer"]
 assert all(x==0 for x in row["padding_cache_locations"])
 assert all(x>0 for x in row["qa_live_cache_locations"])
for x in r["pool_checks"]:assert x["before"]==x["after"]==dict(req_free=8,kv_free=512)
pool=load(root/"pool-no-clear/result/framework.json")
assert pool["status"]=="QA_pool_reuse_passed" and pool["qa_no_clear_used"]
assert pool["qa_after"]==dict(req_free=8,kv_free=512) and len(pool["qa_reused_KV_slots"])==512
events=load(root/"native/timeline.json")["traceEvents"];kernels=[e for e in events if e.get("cat")=="kernel"];regions=[]
for e in events:
 if e.get("cat")!="user_annotation" or not e["name"].startswith("framework/"):continue
 found=[k for k in kernels if e["ts"]<=k["ts"] and k["ts"]+k.get("dur",0)<=e["ts"]+e["dur"]]
 writes=[k for k in found if "index_elementwise" in k["name"]]
 streams=collections.Counter(k["args"].get("stream") for k in writes)
 assert len(writes)==60
 assert len(streams)==(2 if e["name"].endswith("/graph") else 1)
 assert not any("store_kv_cache" in k["name"] for k in found)
 regions.append(dict(region=e["name"],kernel_count=len(found),KV_write_count=len(writes),KV_streams=dict(streams)))
assert len(regions)==4
assert not any("store_kv_cache" in x for x in r["native_op_counts"])
manual=load(root/"native/manual-mature-view.json")["traceEvents"]
manual_kernels=[x for x in manual if x.get("cat")=="kernel"]
assert len(manual_kernels)==1 and "store_kv_cache" in manual_kernels[0]["name"]
probe=r["manual_mature_KV_probe"];assert probe["k_shape"]==[12,3,64] and probe["k_stride"]==[960,64,1] and not probe["fallback_used"]
assert "aten::contiguous" not in probe["op_counts"] and "aten::clone" not in probe["op_counts"]
history={}
for key,src in (("native2","measured-source.py"),("native1","failed-observer-source.py")):
 report=load(Path("native-input/debug")/key/"framework.json")
 h=hashlib.sha256((Path("native-input/debug")/key/src).read_bytes()).hexdigest()
 assert h==report["runner_source_sha256"]
 history[key]=dict(status=report["status"],sha256=h)
orig=subprocess.check_output(["git","-C","maas","show","b5e705d:tools/perf/operators/local_gpu/run_framework_dummy.py"])
assert hashlib.sha256(orig).hexdigest()==load(Path("native-input/evidence/native3/framework.json"))["runner_source_sha256"]
m=load(Path("native-input/code/manifest-sha256.json"))
for p,h in m.items():
 if p.startswith("increment/"):assert hashlib.sha256(subprocess.check_output(["git","-C","maas","show","b5e705d:"+p[len("increment/"):]])).hexdigest()==h
s=dict(commit="b5e705d2f0ce61d4aeda81ee7a852eb01df7cb5f",structure_steps=12,negative_controls=r["qa_negative_controls"],CUPTI_regions=regions,
 pool_no_clear=pool,history_sources=history,original_sha256=hashlib.sha256(orig).hexdigest(),parameters=r["parameter_count"],peak_torch_bytes=r["peak_torch_bytes"],logit_maxima=[x["logit_max_abs"] for x in r["records"]],max_graph_eager_difference=max(x["max_abs_graph_eager"] for x in r["records"]),Engine=False,semantic_quality=False)
(out/"results.json").write_text(json.dumps(s,indent=2)+"\n")
print(json.dumps(dict(steps=12,negative_controls=len(r["qa_negative_controls"]),regions=regions,pool_no_clear="passed",history=history),indent=2))
