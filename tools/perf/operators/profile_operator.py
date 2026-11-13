#!/usr/bin/env python3
"""Print bounded operator profiler argv by default. Never launches an arbitrary target."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from bench import read_plan, require_gpu_approval, SafeParser


def command(tool, plan, case, output, backend="torch"):
    root=Path(__file__).resolve().parent
    target=[sys.executable,str(root/"bench.py"),"--plan",str(Path(plan).resolve()),
            "--mode","gpu","--case",case,"--backend",backend,
            "--output",str(Path(output)/"operator.json")]
    if tool=="torch":
        return target+["--profile-dir",str(Path(output)/"torch-trace")]
    target += ["--instrumented"]  # suppress all benchmark timing in external profiler runs
    if tool=="nsys":
        return ["nsys","profile","--trace=cuda,nvtx,osrt","--sample=none",
                "--cpuctxsw=none","-o",str(Path(output)/"timeline")]+target
    return ["ncu","--set","basic","--nvtx","--nvtx-include","maas_candidate/",
            "--launch-count","5","--target-processes","all","-o",
            str(Path(output)/"kernel")]+target


def main():
    parser=SafeParser(description=__doc__)
    parser.add_argument("--tool",choices=["torch","nsys","ncu"],required=True)
    parser.add_argument("--plan",type=Path,default=Path(__file__).with_name("plan.json"))
    parser.add_argument("--case",default="gemm-tail")
    parser.add_argument("--backend",choices=["torch","triton"],default="torch")
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--execute",action="store_true")
    args=parser.parse_args()
    cmd=command(args.tool,args.plan,args.case,args.output_dir,args.backend)
    if not args.execute:
        print(json.dumps({"dry_run":True,"argv":cmd,
                          "execution_enabled":read_plan(args.plan)["execution_enabled"],
                          "note":"profiler replay/overhead invalidates normal benchmark timing; use trace only"}))
        return 0
    try:
        plan=read_plan(args.plan);require_gpu_approval(plan)
        if args.tool!="torch":
            executable=shutil.which(args.tool)
            if executable is None or Path(executable).suffix.lower() in (".bat",".cmd"):
                raise ValueError("require actual profiler executable on PATH, not a shell wrapper")
            cmd[0]=executable
        args.output_dir.mkdir(parents=True,exist_ok=True)
        return subprocess.run(cmd,check=False).returncode
    except (OSError,ValueError):
        print("profiler execution blocked by approval/tool conditions",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
