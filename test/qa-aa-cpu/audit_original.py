"""Read-only independent audit of original failed P25-AA attempt."""
from pathlib import Path
import argparse,json,hashlib,zipfile,subprocess,csv
p=argparse.ArgumentParser();p.add_argument("--source",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
src=a.source.resolve();e=src/"evidence/aa-v0.26-result";a.output.mkdir(parents=True,exist_ok=False)
def load(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def git(*args):return subprocess.check_output(["git","-C","maas",*args])
manifest=load(e/"manifest.json");assert len(manifest["files"])==28
for n,item in manifest["files"].items():assert sha((e/n).read_bytes())==item["sha256"]
frozen=a.output/"frozen";frozen.mkdir()
with zipfile.ZipFile(e/"frozen-producer.zip") as z:
 for n in z.namelist():
  target=frozen/n;target.resolve().relative_to(frozen.resolve());target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(n))
plan=load(e/"plan.json");assert plan["execution_checkout"].startswith("dea6485")
for n,h in plan["sources"].items():
 assert sha((frozen/n).read_bytes())==h==sha(git("show","dea6485:tools/perf/operators/local_gpu/"+n))
fixed=load(e/"transport-fix-disabled-plan.json");assert fixed["execution_enabled"] is False
for n,h in fixed["sources"].items():assert sha((src/n).read_bytes())==h==sha(git("show","4bed4b4:tools/perf/operators/local_gpu/"+n))
for x,y in (("03a31e1","dea6485"),("dea6485","8d0e7e9"),("8d0e7e9","4bed4b4")):subprocess.run(["git","-C","maas","merge-base","--is-ancestor",x,y],check=True)
cmd=["python",str(frozen/"analyze_aa_window.py"),"--plan",str(e/"plan.json"),"--root",str(e/"execution/window"),"--output",str(a.output/"reanalysis.json")]
cp=subprocess.run(cmd,capture_output=True,text=True);assert cp.returncode==2
r=load(a.output/"reanalysis.json");assert r==load(e/"execution/qualification.json")
assert r["planned_rows"]==128 and r["measured_rows"]==r["completed_calls"]==0 and r["status_counts"]=={"missing":128}
assert len({x["id"] for x in r["rows"]})==128 and len(r["alias_pairs"])==32
assert all(not x["complete"] and x["A_ns"] is None and x["Aprime_ns"] is None and x["Aprime_minus_A_ns"] is None and x["Aprime_over_A"] is None for x in r["alias_pairs"])
assert all(x["difference_ns"] is None and x["ratio"] is None for x in r["alias_ranges"].values())
with (e/"alias-pairs.csv").open(newline="") as f:
 pairs=list(csv.DictReader(f));assert len(pairs)==32
lease=load(e/"execution/lease.json")
reconstructed=json.dumps(lease).encode()+bytes((92,110))
assert reconstructed== (e/"transport-original-counterexample.bin").read_bytes()
try:json.loads(reconstructed)
except json.JSONDecodeError as err:assert err.pos==228;failure=str(err)
else:raise AssertionError("bad packet accepted by json")
assert b"char 228" in (e/"execution/foreground.log").read_bytes()
driver=load(e/"execution/driver.json");outcome=load(e/"batch-outcome.json")
assert outcome["attempts"]==1 and outcome["model_workers_started"]==0 and not outcome["repeatability_tested"]
result=dict(candidate="4bed4b4be2ca294b9305cfb28fe1ab03f6164ec0",execution="dea6485a4fa62426f610e0f15463513e63e880f6",fix="8d0e7e99bf5ba8294a38079c100b2d5291552c57",
 result_items=28,frozen_files=len(plan["sources"]),fixed_CPU_files=len(fixed["sources"]),reanalysis_exit=cp.returncode,report_exactly_equal=True,
 planned_rows=128,measured_rows=0,missing=128,invalid=0,planned_calls=1280,completed_calls=0,planned_pairs=32,observed_pairs=0,alias_differences=None,alias_ratios=None,matching_rate=None,
 failure_classification="parent startup JSON parsing before shared lock/resource query/worker",rebuilt_packet_json_error=failure,packet_is_reconstruction_not_captured_stdin=True,
 one_attempt_driver=driver,original_batch_outcome=outcome,GPU_executed_in_QA=False)
(a.output/"original-audit.json").write_text(json.dumps(result,indent=2))
(a.output/"replay-command.json").write_text(json.dumps(dict(argv=cmd,exit_code=cp.returncode,stdout=cp.stdout,stderr=cp.stderr),indent=2))
print(json.dumps({k:result[k] for k in ("result_items","frozen_files","fixed_CPU_files","reanalysis_exit","report_exactly_equal","planned_rows","measured_rows","missing","planned_pairs","observed_pairs","matching_rate")},indent=2))
