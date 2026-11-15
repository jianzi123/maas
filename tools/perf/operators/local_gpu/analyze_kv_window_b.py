"""Read-only strict analysis of Window B blocks and retained v0.19 controls."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def median(xs):
    return statistics.median(xs)


def spread(xs):
    xs=sorted(xs)
    return {"min":xs[0],"median":median(xs),"max":xs[-1]}


def main():
    a=argparse.ArgumentParser()
    a.add_argument("--input",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    args=a.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    rows=[];sources=[];metadata=[]
    for name in ("paired-native-first","paired-mature-first"):
        path=args.input/name/"window-b.json"
        d=json.loads(path.read_text(encoding="utf-8"))
        if d["status"]!="passed" or d["profile_only"] or len(d["gates"])!=9:
            raise ValueError("missing successful paired gates")
        if len(d["blocks"])!=120:raise ValueError("incomplete blocks")
        sources.append({"path":str(path.relative_to(args.input)),
                        "sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        metadata.append({k:d[k] for k in ("pid","capture_first","initialization","peak_torch_bytes",
                                          "environment","versions","graph_state")})
        for bs in (3,5,8):
            for scope in ("full","bare_graph"):
                found=[r for r in d["blocks"] if r["batch"]==bs and r["scope"]==scope]
                if len(found)!=20:raise ValueError("incomplete scope")
                ratios=[]
                for i in range(10):
                    pair={r["variant"]:r for r in found if r["cycle"]==i}
                    if set(pair)!={"native","mature"}:raise ValueError("pair identities missing")
                    expected=("native","mature") if i%2==0 else ("mature","native")
                    if any(pair[v]["position"]!=expected.index(v) for v in expected):
                        raise ValueError("pair order changed")
                    for r in pair.values():
                        for k in ("wall_with_sync_us","event_with_host_gaps_us","host_enqueue_us","host_thread_cpu_us","wait_us"):
                            value=r[k]
                            if not isinstance(value,(float,int)) or not 0<value<float("inf"):
                                raise ValueError("nonfinite/nonpositive measurement")
                    ratios.append(pair["mature"]["wall_with_sync_us"]/pair["native"]["wall_with_sync_us"])
                row={"process":name,"batch":bs,"scope":scope,"paired_cycles":10,
                     "mature_over_native":spread(ratios),"mature_slower_pairs":sum(x>1 for x in ratios),
                     "ratios_all":ratios,"per_variant":{}}
                for v in ("native","mature"):
                    subset=[r for r in found if r["variant"]==v]
                    row["per_variant"][v]={k:spread([r[k] for r in subset]) for k in
                        ("wall_with_sync_us","event_with_host_gaps_us","host_enqueue_us","host_thread_cpu_us","wait_us")}
                rows.append(row)
    controls=[]
    for v in ("native","mature"):
        path=args.input/f"isolated-{v}/cost.json"
        d=json.loads(path.read_text(encoding="utf-8"))
        if len(d["measurements"])!=3:raise ValueError("missing isolated batch")
        for r in d["measurements"]:
            if len(r["samples"])!=9:raise ValueError("missing isolated sample")
            controls.append({"variant":v,"batch":r["batch"],"capture_batch":r["capture_batch"],
                "wall_us":spread([x["wall_with_sync_us_per_call"] for x in r["samples"]]),
                "event_us":spread([x["event_with_host_gaps_us_per_call"] for x in r["samples"]])})
        sources.append({"path":str(path.relative_to(args.input)),
                        "sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    report={"scope":"author Window B; artificial weights/static native ForwardBatch",
            "paired_processes":metadata,"rows":rows,"isolated_controls":controls,
            "sources":sources,"source_coverage":{"paired_blocks":240,"paired_cycles":120,
                "paired_state_gates":18,"isolated_blocks":54},
            "stable_gain_established":False,"historical_drift_cause":"unknown",
            "evidence":"bare graph also has long event/wait while host submission is short",
            "causal_limit":"two capture orders are also two process/time windows; not a causal randomization of order",
            "observer_limit":"nvidia-smi sampled outside every clean block; cadence differs from v0.19",
            "statistical_limit":"within-process repeated blocks are dependent; no population CI/significance claim"}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"coverage":report["source_coverage"],
        "adverse_pairs":sum(r["mature_slower_pairs"] for r in rows),
        "stable_gain_established":False}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
