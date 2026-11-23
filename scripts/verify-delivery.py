"""Verify both deployment ZIPs against one source lock and the committed tree.

Run from the delivery checkout after packaging. Does not start services, inspect
Secret values, or infer deployment/model acceptance from archive integrity.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
LOCK = "deploy/build-sources.lock.json"
METADATA = (LOCK, "deploy/dependencies.lock.json", "deploy/identities.json",
            "deploy/charts/maas-platform/runtime-interface.json")


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify(path, ref):
    expected_locks = {name: git("show", f"{ref}:{name}") for name in METADATA}
    lock = json.loads(expected_locks[LOCK])
    code = lock["backend"]["sourceCommit"]
    if lock["console"]["sourceCommit"] != code:
        raise ValueError("frontend/backend source commits differ")
    git("merge-base", "--is-ancestor", code, ref)
    with zipfile.ZipFile(path) as archive:
        files = {}
        for info in archive.infolist():
            name = info.filename
            parts = PurePosixPath(name).parts
            if "\\" in name or name.startswith("/") or ".." in parts:
                raise ValueError("unsafe archive path")
            if info.is_dir():
                continue
            if name in files:
                raise ValueError("duplicate archive member")
            if any(p in {".git", "node_modules", ".cache", "mysql-data"} for p in parts):
                raise ValueError("runtime data or local cache packaged")
            if parts[-1] == ".env":
                raise ValueError("live .env packaged; use .env.example")
            files[name] = info
        candidates = [name[:-len(LOCK)] for name in files if name.endswith(LOCK)]
        if len(candidates) != 1:
            raise ValueError("expected exactly one complete source lock")
        prefix = candidates[0]
        version_names=[n for n in files if n=="VERSION.json"]
        version=json.loads(archive.read(version_names[0])) if version_names else {}
        fetched=version.get("sourceMode")=="fetch"
        retrieval=json.loads(archive.read("SOURCE.sha256.json")) if fetched else None
        if fetched:
            if version["repositoryCommit"]!=git("rev-parse",ref).decode().strip() or version["codeCommit"]!=code:
                raise ValueError("retrieval version differs from delivery")
            if archive.read("fetch_source.py")!=git("show",f"{ref}:deploy/release/fetch_source.py"):
                raise ValueError("source retrieval program differs from delivery")
        for name, expected in expected_locks.items():
            if archive.read(prefix + name) != expected:
                raise ValueError("metadata differs from committed delivery: " + name)
        counts = {}
        for component in ("backend", "console"):
            inventory = lock[component]["files"]
            for name, expected in inventory.items():
                actual=retrieval[name]["sha256"] if fetched else digest(archive.read(prefix + name))
                if actual != expected:
                    raise ValueError("source inventory mismatch: " + name)
            counts[component] = len(inventory)
        # Deployment files are excluded from the code inventories; compare their
        # exact bytes separately, including the image recipes and migrations.
        deployment = git("ls-tree", "-r", "--name-only", ref, "deploy").decode().splitlines()
        if fetched:
            expected_paths=set(lock["backend"]["files"])|set(lock["console"]["files"])|set(deployment)
            if set(retrieval)!=expected_paths:
                raise ValueError("retrieval manifest does not cover the exact source tree")
            for row in git("ls-tree","-r","-l","-z",ref).decode().split('\0'):
                if not row:continue
                metadata,name=row.split('\t',1)
                if int(metadata.split()[-1])!=retrieval[name]["bytes"]:
                    raise ValueError("retrieval source size mismatch: "+name)
        for name in deployment:
            expected=git("show", f"{ref}:{name}")
            mismatch=retrieval[name]["sha256"]!=digest(expected) if fetched else archive.read(prefix + name)!=expected
            if mismatch:
                raise ValueError("deployment file differs from delivery: " + name)
        readmes = [n for n in files if PurePosixPath(n).name.lower() == "readme.md"]
        if not readmes:
            raise ValueError("missing README")
    return {"archive": str(path.resolve()), "sha256": digest(path.read_bytes()),
            "bytes": path.stat().st_size, "deliveryCommit": git("rev-parse", ref).decode().strip(),
            "sourceCodeCommit": code, "sourcePrefix": prefix, "verifiedSourceFiles": counts,
            "verifiedDeploymentFiles": len(deployment), "sourceMode":"fetch" if fetched else "full", "integrityPassed": True,
            "scope": "archive/source integrity only; runtime, SQL, QA and real model evidence are separate"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compose", type=Path)
    parser.add_argument("kubernetes", type=Path)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = [verify(path, args.ref) for path in (args.compose, args.kubernetes)]
    if rows[0]["sourceCodeCommit"] != rows[1]["sourceCodeCommit"]:
        raise ValueError("packages do not share one source code commit")
    result = json.dumps({"packages": rows}, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding="utf-8", newline="\n")
    print(result)


if __name__ == "__main__":
    main()
