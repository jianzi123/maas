"""Additional CPU command records; AA-CPU-01 is one defect across function and CLI."""
from pathlib import Path
import argparse,subprocess,sys,json,os,copy
p=argparse.ArgumentParser();p.add_argument("--source",type=Path,required=True);p.add_argument("--root",type=Path,required=True);a=p.parse_args()
src=a.source.resolve();root=a.root.resolve();out=root/"followup";out.mkdir()
sys.path.insert(0,str(src))
from aa_worker import validate_job
from cadence_protocol import digest
plan=json.loads((root/"disabled-plan.json").read_bytes());job=json.loads((root/"valid-job.json").read_bytes())
env=dict(os.environ,PYTHONPATH=str(root/"guard")+os.pathsep+str(src),PYTHONDONTWRITEBYTECODE="1")
records=[]
def run(name,args):
 cp=subprocess.run([str(x) for x in args],env=env,capture_output=True,timeout=5)
 (out/(name+".stdout")).write_bytes(cp.stdout);(out/(name+".stderr")).write_bytes(cp.stderr)
 records.append(dict(case=name,argv=[str(x) for x in args],exit_code=cp.returncode,stdout=cp.stdout.decode(errors="replace"),stderr=cp.stderr.decode(errors="replace")))
 return cp
base=[sys.executable,src/"aa_worker.py","--plan",root/"disabled-plan.json","--validate-only"]
positive=run("worker-positive",base+["--job",root/"valid-job.json"]);assert positive.returncode==0
bad=run("AA-CPU-01-real-CLI",base+["--job",root/"AA-CPU-01-job.json"]);assert bad.returncode==0 and json.loads(bad.stdout)["validated"]
wrong=run("source-pin-reject",[sys.executable,src/"run_aa_window.py","--plan",root/"wrong-source-plan.json","--validate-only"]);assert wrong.returncode!=0 and b"frozen sources" in wrong.stderr
x=copy.deepcopy(job);x.update(process="HOLD",bank_sha256=None)
try:validate_job(plan,x)
except ValueError as e:assert "bank stage" in str(e)
else:raise AssertionError("HOLD missing bank accepted")
existing=out/"old-report.json";existing.write_bytes(b"QA existing report sentinel")
empty=out/"empty";empty.mkdir()
r=run("analyzer-no-overwrite",[sys.executable,src/"analyze_aa_window.py","--plan",root/"disabled-plan.json","--root",empty,"--output",existing])
assert r.returncode!=0 and b"FileExistsError" in r.stderr and existing.read_bytes()==b"QA existing report sentinel"
(root/"followup-commands.json").write_text(json.dumps(records,indent=2))
check=json.loads((root/"checks.json").read_bytes());check["checks"] += [dict(id="JOB-HOLD-missing-bank-reject",status="passed"),dict(id="REPORT-analyzer-exclusive-no-overwrite",status="passed")]
check.update(unique_cases=len(check["checks"]),passed=sum(x["status"]=="passed" for x in check["checks"]),failed=sum(x["status"]=="failed" for x in check["checks"]),AA_CPU_01_confirmed_by_real_validate_CLI=True)
(root/"final-checks.json").write_text(json.dumps(check,indent=2))
print(json.dumps({k:check[k] for k in ("unique_cases","passed","failed","AA_CPU_01_confirmed_by_real_validate_CLI")}))
