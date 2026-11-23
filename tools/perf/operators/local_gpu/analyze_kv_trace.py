"""CUPTI correlation joins for Window B; profiled times are not clean A/B samples."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def intervals_union(events):
    merged=[]
    for a,b in sorted((e["ts"],e["ts"]+e["dur"]) for e in events):
        if merged and a<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],b)
        else:merged.append([a,b])
    return sum(b-a for a,b in merged)


def region_row(events,region):
    api=[e for e in events if e.get("cat")=="cuda_runtime" and
         region["ts"]<=e["ts"]<=region["ts"]+region["dur"]]
    graph_corr={e["args"]["correlation"] for e in api if e["name"]=="cudaGraphLaunch"}
    if len(graph_corr)!=1:raise ValueError("expected one graph launch per region")
    graph=[e for e in events if e.get("cat")=="kernel" and
           e.get("args",{}).get("correlation") in graph_corr]
    if not graph:raise ValueError("missing correlated graph kernels")
    writes=sum("index_elementwise_kernel" in e["name"] for e in graph)
    stores=sum("store_kv_cache" in e["name"] for e in graph)
    mature="mature" in region["name"]
    if (writes,stores)!=((0,30) if mature else (60,0)):
        raise ValueError("graph binding changed")
    counts=Counter();durations=Counter()
    for e in graph:
        counts[e["name"]]+=1;durations[e["name"]]+=e["dur"]
    span=max(e["ts"]+e["dur"] for e in graph)-min(e["ts"] for e in graph)
    return {"region":region["name"],"cudaGraphLaunch_correlations":sorted(graph_corr),
        "graph_kernel_count":len(graph),"index_writes":writes,"mature_stores":stores,
        "streams":sorted({e["args"]["stream"] for e in graph}),
        "profiled_graph_envelope_us":span,"profiled_busy_union_us":intervals_union(graph),
        "profiled_kernel_duration_sum_us":sum(e["dur"] for e in graph),
        "top_profiled_kernels":[{"name":n,"count":counts[n],"duration_sum_us":d}
                                for n,d in durations.most_common(8)]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    data=json.loads(args.trace.read_text())["traceEvents"]
    regions=[e for e in data if e.get("cat")=="user_annotation" and e.get("name","").startswith("windowB/")]
    if len(regions)!=4:raise ValueError("missing named profile regions")
    rows=[region_row(data,r) for r in regions]
    result={"scope":"separate profiler process; correlation-linked graph nodes only",
        "profiled_times_used_as_clean_cost":False,"regions":rows,
        "trace_sha256":hashlib.sha256(args.trace.read_bytes()).hexdigest(),
        "analysis_code_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps([{"region":r["region"],"kernels":r["graph_kernel_count"],
                       "index":r["index_writes"],"store":r["mature_stores"]} for r in rows]))
    return 0


if __name__=="__main__":raise SystemExit(main())
