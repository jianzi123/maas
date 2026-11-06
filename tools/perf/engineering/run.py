"""Run fixed CPU engineering experiments. No GPU/API/model/cluster execution path."""

import argparse
import json
import os
from pathlib import Path
import uuid
import math

if __package__:
    from . import (
        attention_lab,
        layout_lab,
        transforms_lab,
        distributed_lab,
        kv_lab,
        scheduler_lab,
        statistics_lab,
        durable_lab,
    )
else:
    import attention_lab, layout_lab, transforms_lab, distributed_lab, kv_lab, scheduler_lab, statistics_lab, durable_lab

LABS = {
    "attention": attention_lab.demo,
    "layout": layout_lab.demo,
    "transforms": transforms_lab.demo,
    "distributed": distributed_lab.demo,
    "kv": kv_lab.demo,
    "scheduler": scheduler_lab.demo,
    "statistics": statistics_lab.demo,
}


def validate_numeric_reports(results):
    for name in ("attention", "layout", "transforms", "distributed"):
        if name not in results:
            continue
        data = results[name]
        if name == "attention":
            numbers = list(data["max_abs_error_by_block"].values())
        elif name == "layout":
            numbers = [data["max_abs_error"]]
        elif name == "transforms":
            numbers = [data["rope_roundtrip_max_error"]]
            if not data["triangle_bound_holds"]:
                raise ValueError("quantization inequality failed")
        else:
            numbers = [
                data["tp_column_error"],
                data["tp_row_error"],
                data["moe_combine_error"],
            ]
        if not all(math.isfinite(n) and n <= 1e-10 for n in numbers):
            raise ValueError("CPU correctness failed")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--lab", choices=["all", *LABS, "durable"], default="all")
    args = p.parse_args()
    if not __debug__:
        p.error("run without -O; invariant checks are required")
    # A fresh output prevents mistaking an old success report for a failed new run.
    if args.output.exists():
        p.error("choose a fresh output path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = {name: f() for name, f in LABS.items() if args.lab in ("all", name)}
    validate_numeric_reports(result)
    if args.lab in ("all", "durable"):
        directory = args.output.parent / ("crash-lab-" + uuid.uuid4().hex)
        result["durable"] = durable_lab.demo(directory)
        result["durable"]["local_evidence_directory"] = directory.name
    report = {
        "schema_version": "cpu-engineering-1.0",
        "evidence_kind": "cpu_algorithms_and_local_crash_lab",
        "synthetic_inputs": True,
        "gpu_executed": False,
        "model_executed": False,
        "cluster_accessed": False,
        "authority": "teaching_only_no_admission_settlement_refund_or_close_proof",
        "results": result,
    }
    encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
    temporary = args.output.with_name(
        args.output.name + "." + uuid.uuid4().hex + ".tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic no-replace publication on the local hard-link-capable filesystem.
        os.link(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(
        json.dumps(
            {"labs": list(result), "gpu_executed": False, "output": args.output.name}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
