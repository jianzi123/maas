"""Verify an extracted installer without contacting Docker, a cluster, or models."""
import argparse, hashlib, json
from pathlib import Path
def verify(root, source_only=False):
    root=Path(root).resolve()
    manifest=json.loads((root/"MANIFEST.sha256.json").read_text(encoding="utf-8"))
    failures=[]
    for name,want in manifest.items():
        if source_only and not (name.startswith("source/") or name=="VERSION.json"):continue
        p=(root/name).resolve()
        if not p.is_relative_to(root) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=want:
            failures.append(name)
    version=json.loads((root/"VERSION.json").read_text(encoding="utf-8"))
    for name in ("build-sources.lock.json","dependencies.lock.json","identities.json","charts/maas-platform/runtime-interface.json"):
        if not (root/"source/deploy"/name).is_file():failures.append("missing-source-lock:"+name)
    lock_path=root/"source/deploy/build-sources.lock.json"
    if lock_path.is_file():
        lock=json.loads(lock_path.read_text())
        if lock.get("backend",{}).get("sourceCommit") != version["codeCommit"] or lock.get("console",{}).get("sourceCommit") != version["codeCommit"]:
            failures.append("component-source-version")
    for name,want in version.get("sourceLockSha256",{}).items():
        if hashlib.sha256((root/"source"/name).read_bytes()).hexdigest()!=want:failures.append("source-lock:"+name)
    return {"repositoryCommit":version["repositoryCommit"],"codeCommit":version["codeCommit"],"filesChecked":len(manifest),"passed":not failures,"failures":failures}
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--root",default=".")
    r=verify(p.parse_args().root);print(json.dumps(r));raise SystemExit(0 if r["passed"] else 1)