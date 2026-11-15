"""CPU-only minimal ELIT-QA-01: complete gate identities, absent vectors."""
import argparse,shutil,subprocess,sys,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--source",type=Path,required=True);p.add_argument("--evidence",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=False)
for run in ("R01","R02"):shutil.copytree(a.evidence/run,a.output/run)
g=a.output/"R01/gates.json";value=json.loads(g.read_bytes());value[0]["snapshots"]={"native":[],"mature":[]};g.write_text(json.dumps(value))
report=a.output/"unexpected-success.json"
cmd=[sys.executable,str(a.source.resolve()/"analyze_kv_cadence.py"),"--plan",str((a.evidence/"plan.json").resolve()),"--root",str(a.output.resolve()),"--output",str(report.resolve())]
r=subprocess.run(cmd,capture_output=True,text=True)
result=dict(expected="nonzero exit and no success report",actual_exit=r.returncode,success_report=report.exists(),stdout=r.stdout,stderr=r.stderr)
(a.output/"oracle.json").write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
raise SystemExit(1 if r.returncode==0 or report.exists() else 0)
