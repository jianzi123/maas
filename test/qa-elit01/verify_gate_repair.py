"""Independent CPU/offline ELIT-QA-01 repair oracle; no producer manifests executed."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import numpy as np

HEAD = "4ab8a277efe5edb9219d83cc9aea204add36af8e"
OLD = "5f8bd5d83968f9ed5e674593bb8d19078c4575ad"
PLAN_FILE = "c42a4755b426fe964b7423ffb6cf4001e75f42bc52bf9ff018de6184a58c52c7"
PLAN_CANONICAL = "ab0ac451d9d4beffd6a879ff04bcdcd4000a256ec3194b710f5e7dabca49d9c9"
TOOL = Path("tools/perf/operators/local_gpu")

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True, help="immutable exports from prepare_elit_retest.py")
    parser.add_argument("--output", type=Path, required=True, help="new, exclusive output directory")
    args = parser.parse_args()
    inputs, out = args.inputs.resolve(), args.output.resolve()
    out.mkdir(exist_ok=False, parents=True)
    evidence = inputs / "evidence"
    before = {str(p.relative_to(inputs)): sha(p) for p in inputs.rglob("*") if p.is_file()}
    provenance = json.loads((inputs / "input-manifest.json").read_text(encoding="utf-8"))
    assert provenance["product_head"] == HEAD
    assert sha(evidence / "plan.json") == PLAN_FILE
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    invocations = []
    def invoke(label, source, data, report):
        cmd = [sys.executable, str(source / TOOL / "analyze_kv_cadence.py"),
               "--plan", str(evidence / "plan.json"), "--root", str(data), "--output", str(report)]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        log = {"label": label, "command": cmd, "exit": result.returncode,
               "stdout": result.stdout, "stderr": result.stderr, "report_exists": report.exists()}
        write(out / (label + ".log.json"), log)
        invocations.append(log)
        return log
    def dataset(label):
        dest = out / label
        dest.mkdir()
        for run in ("R01", "R02"):
            shutil.copytree(evidence / run, dest / run)
        return dest
    def edit(data, mutation):
        path = data / "R01/gates.json"
        gates = json.loads(path.read_bytes())
        mutation(gates[0]["snapshots"], data / "R01")
        write(path, gates)
    results = []
    # The unmodified complete archive must still pass under the new analyzer.
    positive = out / "original-success.json"
    log = invoke("P00-original", inputs / "product", evidence, positive)
    assert log["exit"] == 0 and positive.exists(), log
    report = json.loads(positive.read_bytes())
    strict = [t for t in report["triplets"] if t["scope"] == "full"]
    invariants = {"planned_blocks": report["planned_blocks"], "planned_calls": report["planned_calls"],
                  "planned_clusters": report["planned_clusters"], "complete_clusters": len(report["clusters"]),
                  "block_status_counts": report["block_status_counts"], "full_strict": [sum(t["idle_match_qualified"] for t in strict), len(strict)],
                  "plan_sha256": report["plan_sha256"], "plan_file_sha256": sha(evidence / "plan.json")}
    assert invariants == {"planned_blocks":1080, "planned_calls":10800, "planned_clusters":108,
                          "complete_clusters":108, "block_status_counts":{"measured":1080},
                          "full_strict":[0,18], "plan_sha256":PLAN_CANONICAL, "plan_file_sha256":PLAN_FILE}, invariants
    results.append({"id":"P00", "name":"original archive", "pass":True, "invariants":invariants})
    # Preserve a real old-CLI failure artifact; historical observations are not repair passes.
    old = dataset("H00-old-empty-gate")
    edit(old, lambda s, _: s.update(native=[], mature=[]))
    old_report = old / "unexpected-success.json"
    legacy = invoke("H00-old-empty-gate", inputs / "legacy", old, old_report)
    assert legacy["exit"] == 0 and old_report.exists(), legacy
    results.append({"id":"H00", "name":"legacy defect control", "historical_defect_reproduced":True,
                    "repair_pass":False, "report_sha256":sha(old_report)})
    def replace_role(side, role, other):
        return lambda s, _: s[side].__setitem__(role, copy.deepcopy(s[side][other]))
    def change_array(kind):
        def change(s, folder):
            ref = s["native"][0]
            with np.load(folder / ref["path"], allow_pickle=False) as z:
                value = z["value"].copy()
            if kind == "nonfinite": value[0,0] = np.nan
            elif kind == "bitwise": value[0,0] += np.float32(1)
            elif kind == "dtype": value = value.astype(np.float64)
            rel = "snapshots/" + hashlib.sha256(value.tobytes()).hexdigest() + ".npz"
            np.savez_compressed(folder / rel, value=value)
            s["native"][0] = dict(path=rel, raw_sha256=hashlib.sha256(value.tobytes()).hexdigest(), shape=list(value.shape), dtype=str(value.dtype))
        return change
    cases = [
        ("N01", "both empty", lambda s,_: s.update(native=[],mature=[]), "requires logits and KV"),
        ("N02", "native empty", lambda s,_: s.update(native=[]), "requires logits and KV"),
        ("N03", "mature empty", lambda s,_: s.update(mature=[]), "requires logits and KV"),
        ("N04", "native missing", lambda s,_: s.pop("native"), "variants incomplete"),
        ("N05", "mature missing", lambda s,_: s.pop("mature"), "variants incomplete"),
        ("N06", "native short 1 vs 2", lambda s,_: s.update(native=s["native"][:1]), "requires logits and KV"),
        ("N07", "mature short 2 vs 1", lambda s,_: s.update(mature=s["mature"][:1]), "requires logits and KV"),
        ("N08", "native lacks logits", replace_role("native",0,1), "logits role/shape/dtype"),
        ("N09", "mature lacks KV", replace_role("mature",1,0), "KV role/shape/dtype"),
        ("N10", "roles reversed", lambda s,_: s.update(native=list(reversed(s["native"])),mature=list(reversed(s["mature"]))), "logits role/shape/dtype"),
        ("N11", "nonfinite actual logits with matching metadata", change_array("nonfinite"), "finite/hash mismatch"),
        ("N12", "different finite native logits with valid hash", change_array("bitwise"), "bitwise mismatch"),
        ("N13", "wrong raw hash", lambda s,_: s["native"][0].update(raw_sha256="0"*64), "finite/hash mismatch"),
        ("N14", "wrong shape metadata", lambda s,_: s["native"][0].update(shape=[1,1]), "finite/hash mismatch"),
        ("N15", "actual FP64 logits with matching metadata", change_array("dtype"), "logits role/shape/dtype"),
    ]
    for ident, name, mutation, error in cases:
        data = dataset(ident)
        edit(data, mutation)
        fresh = data / "must-not-exist.json"
        rejected = invoke(ident + "-fresh", inputs / "product", data, fresh)
        saved = data / "existing-success.json"
        shutil.copyfile(positive, saved)
        expected_hash = sha(saved)
        protected = invoke(ident + "-existing", inputs / "product", data, saved)
        checks = {"fresh_nonzero":rejected["exit"] != 0, "no_new_success":not fresh.exists(),
                  "expected_validation_error":error in rejected["stderr"],
                  "existing_nonzero":protected["exit"] != 0,
                  "exclusive_error":"FileExistsError" in protected["stderr"],
                  "existing_success_unchanged":sha(saved) == expected_hash}
        results.append({"id":ident, "name":name, "pass":all(checks.values()), "checks":checks,
                        "fresh_exit":rejected["exit"], "existing_exit":protected["exit"], "expected_error":error,
                        "existing_success_sha256":expected_hash})
        write(out / "case-results.json", results)
        print(json.dumps({"id":ident, "pass":all(checks.values())}), flush=True)
    after = {str(p.relative_to(inputs)): sha(p) for p in inputs.rglob("*") if p.is_file()}
    unchanged = before == after
    result = {"defect":"ELIT-QA-01/P2", "product_head":HEAD, "old_delivery":OLD,
              "implementation":provenance["implementation"], "delivery":provenance["delivery"],
              "prior_qa":"df4d45cb2c477650404da9da72a0fb0074a86b59", "unique_current_cases":16,
              "passed_current_cases":sum(c.get("pass",False) for c in results),
              "historical_controls":1, "actual_cli_invocations":len(invocations), "cases":results,
              "inputs_unchanged":unchanged, "input_files_verified":len(before), "GPU_executions":0, "model_calls":0,
              "environment":{"python":sys.version,"numpy":np.__version__,"platform":platform.platform(),"utc":datetime.now(timezone.utc).isoformat()},
              "scope":"offline archived gate validation only; no new performance or causal qualification"}
    result["status"] = "CLOSED in offline gate scope" if unchanged and result["passed_current_cases"] == 16 else "OPEN"
    write(out / "results.json", result)
    write(out / "input-manifest.json", provenance)
    write(out / "output-hashes.json", {str(p.relative_to(out)):sha(p) for p in out.rglob("*") if p.is_file()})
    print(json.dumps({k:result[k] for k in ("status","unique_current_cases","passed_current_cases","actual_cli_invocations","inputs_unchanged")}))
    return 0 if result["status"].startswith("CLOSED") else 1

if __name__ == "__main__":
    raise SystemExit(main())
