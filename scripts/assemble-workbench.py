"""Assemble reviewed sources with the original deployment assembler, then overlay this backend commit."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "backendBase": "0559fa46b4a728d6f542daf19532e794f8549b31",
    "console": "30cfce951df8a858810a035efe51846a75a4ade6",
    "deployment": "e5647a2f2b44f53d39a80041be94b619f07c29d6",
    "qaCore": "ac94a373ec0a61c5fd4dc5380a7985a4fb47840f",
}

def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])

def export(revision, destination, staging):
    destination.mkdir()
    archive = staging / (destination.name + ".tar")
    subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", "--output", str(archive), revision], check=True)
    with tarfile.open(archive) as bundle:
        bundle.extractall(destination, filter="data")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("Output exists; choose a new directory.")
    if git("status", "--porcelain", "--untracked-files=no").strip():
        raise SystemExit("Commit tracked backend changes before assembling an identifiable candidate.")
    head = git("rev-parse", "HEAD").decode().strip()
    for revision in set(SOURCES.values()):
        if subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", revision], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            subprocess.run(["git", "-C", str(ROOT), "fetch", "origin", revision], check=True)
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    # Inputs are private to this invocation; previous exports/instances stay intact.
    with tempfile.TemporaryDirectory(prefix="workbench-inputs-", dir=cache) as temporary:
        staging = Path(temporary)
        for label, revision in [("base", SOURCES["backendBase"]), ("frontend", SOURCES["console"]), ("ops", SOURCES["deployment"]), ("current", head)]:
            export(revision, staging / label, staging)
        command = [sys.executable, str(staging / "ops/deploy/checks/source_context.py"), "--backend-root", str(staging / "base"), "--console-root", str(staging / "frontend"), "--output", str(output)]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        upstream = json.loads((staging / "ops/deploy/evidence/assembly-inspection.json").read_text(encoding="utf-8"))
        current = staging / "current"
        def backend_files(root):
            return {p.relative_to(root) for p in root.rglob("*") if p.is_file() and p.relative_to(root).parts[0] not in ("console", "deploy")}
        original = backend_files(staging / "base")
        latest = backend_files(current)
        for relative in original - latest:
            (output / relative).unlink()
        for relative in latest:
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(current / relative, target)
        example = yaml.safe_load((output / "config/samples/MAAS-2-modelrelease-externalapi-v0.4.example.yaml").read_text(encoding="utf-8"))
        example["metadata"] = {"namespace": "maas-local", "name": "local-created"}
        example["spec"]["modelAlias"] = "local-created"
        example["spec"]["source"]["externalAPI"]["upstreamModel"] = "local-example-v1"
        example = {key: example[key] for key in ("apiVersion", "kind", "metadata", "spec")}
        (output / "workbench-example.json").write_text(json.dumps(example, indent=2) + "\n", encoding="utf-8")
        # Never overlay console/deploy from the backend branch.
        manifest = {"backendCommit": head, "sources": SOURCES, "upstreamAssembly": upstream,
                    "scope": "local-management-candidate; not a refreshed deployment approval",
                    "files": {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.rglob("*")) if p.is_file()}}
        (output / "workbench-sources.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "backendCommit": head, "consoleCommit": SOURCES["console"], "deploymentCommit": SOURCES["deployment"]}))

if __name__ == "__main__":
    main()
