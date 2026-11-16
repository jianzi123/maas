"""Offline single-model combination check; no service, cluster or model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from verify import ROOT, CHART, load_values
from preflight import blockers
sys.path.insert(0, str(ROOT.parent / "scripts"))
from unified_sources import snapshot, verify as verify_sources

ARTIFACTS = {"higress-gateway", "higress-controller", "H1-H4-wasm", "H2-envoy-reporter", "H3-instance-agent", "secret-agent"}
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")

def combination_blockers(plan):
    out=[]
    if plan.get("schemaVersion") != "single-model-run-1.0": out.append("combination.version")
    model=plan.get("model",{})
    for key in ("alias","profileRef","approvalRef"):
        if not model.get(key): out.append("model."+key)
    if model.get("sourceType") not in ("ExternalAPI","SelfHosted"): out.append("model.sourceType")
    required=ARTIFACTS | ({"engine","weights-tokenizer","lws-controller"} if model.get("sourceType")=="SelfHosted" else set())
    artifacts=plan.get("artifacts",[])
    if {a.get("id") for a in artifacts} != required or len(artifacts)!=len(required):
        out.append("artifacts.inventory")
    for a in artifacts:
        if not a.get("version") or not a.get("evidenceRef") or not all(DIGEST.fullmatch(a.get(k) or "") for k in ("digest","configDigest")):
            out.append("artifact."+str(a.get("id")))
    for key in ("entrypoint","environmentRef","stopInstructionsRef","logLocationRef"):
        if not plan.get("runtime",{}).get(key):out.append("runtime."+key)
    # An observed callable assertion is never manufactured by this check.
    if plan.get("observedCallable") is not True:out.append("runtime.callableUnobserved")
    for key in ("requestId","publicationId","activationEpoch","logEvidenceRef","usageEvidenceRef"):
        value=plan.get("requestEvidence",{}).get(key)
        if value is None or value == "":out.append("requestEvidence."+key)
    return out

def inspect(repo, revision, values, combination):
    with snapshot(repo, revision) as (commit, source):
        code, checks=verify_sources(repo,commit,source)
        # Always consume the four locks from the verified snapshot, not the caller's working tree.
        lock=json.loads((source/"deploy/dependencies.lock.json").read_text(encoding="utf-8"))
        interface=json.loads((source/"deploy/charts/maas-platform/runtime-interface.json").read_text(encoding="utf-8"))
        from identities import binding_blockers
        issues=blockers(values,lock,interface)+binding_blockers(values,lock["databaseIdentities"],interface)+combination_blockers(combination)
        hashes={p:hashlib.sha256((source/p).read_bytes()).hexdigest() for p in (
            "deploy/build-sources.lock.json","deploy/dependencies.lock.json","deploy/identities.json","deploy/charts/maas-platform/runtime-interface.json")}
        return {"scope":"offline-combination-not-runtime-acceptance","repositoryCommit":commit,"sourceCodeCommit":code,
                "sourceChecks":checks,"lockSha256":hashes,"ready":not issues,"blockers":issues}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ref",default="HEAD")
    p.add_argument("--values",required=True)
    p.add_argument("--combination",default=str(ROOT/"single-model/combination.json"))
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    try:
        result=inspect(ROOT.parent,a.ref,load_values(a.values),json.loads(Path(a.combination).read_text(encoding="utf-8")))
    except (ValueError, OSError) as e:
        result={"scope":"offline-combination-not-runtime-acceptance","ready":False,"blockers":["sources.invalid"],"errorType":type(e).__name__}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({"ready":result["ready"],"blockerCount":len(result["blockers"])}))
    raise SystemExit(0 if result["ready"] else 1)
if __name__=="__main__":main()