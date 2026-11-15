"""Export one committed repository snapshot, with its code inventory verified."""
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LOCK_FILES = frozenset({
    "deploy/build-sources.lock.json",
    "deploy/charts/maas-platform/runtime-interface.json",
    "deploy/dependencies.lock.json",
    "deploy/identities.json",
})


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE)


def clean(repo):
    if git(repo, "status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("Commit tracked changes before exporting an identifiable snapshot.")


@contextmanager
def snapshot(repo, revision="HEAD"):
    commit = git(repo, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}").decode().strip()
    cache = repo / ".cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="unified-source-", dir=cache) as temporary:
        source = Path(temporary)
        archive = git(repo, "archive", "--format=tar", commit)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            bundle.extractall(source, filter="data")
        if any(p.is_symlink() for p in source.rglob("*")):
            raise ValueError("Source snapshots must contain regular files, not symlinks.")
        yield commit, source


def verify(repo, commit, source):
    # Reuse the deployment input comparator; no split-branch overlay is performed.
    sys.path.insert(0, str(ROOT / "deploy/checks"))
    from source_context import compare
    lock = json.loads((source / "deploy/build-sources.lock.json").read_text(encoding="utf-8"))
    code = lock["backend"]["sourceCommit"]
    if code != lock["console"]["sourceCommit"]:
        raise ValueError("Backend and console must be locked to the same repository code commit.")
    if subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", code, commit], capture_output=True).returncode:
        raise ValueError("The locked code commit is not part of this repository snapshot.")
    changed = set(git(repo, "diff", "--name-only", code, commit).decode().splitlines())
    if changed - LOCK_FILES:
        raise ValueError("Code changed after the inventory was locked; regenerate the source lock.")
    checks = [compare(source, lock[name]["files"], name) for name in ("backend", "console")]
    if not all(row["passed"] for row in checks):
        raise ValueError("Committed source bytes do not match the complete source inventory.")
    return code, checks


def assemble_repository(repo, output, revision="HEAD"):
    requested = Path(output)
    if requested.exists() or requested.is_symlink():
        raise FileExistsError("Output exists; choose a new directory.")
    repo, output = Path(repo).resolve(), requested.resolve()
    if output == repo or output in repo.parents:
        raise ValueError("Output cannot replace the source repository.")
    clean(repo)
    with snapshot(repo, revision) as (commit, source):
        code, checks = verify(repo, commit, source)
        files = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(source.rglob("*")) if p.is_file()}
        shutil.copytree(source, output)
        generated = {}
        sample = source / "config/samples/MAAS-2-modelrelease-externalapi-v0.4.example.yaml"
        if sample.exists():
            import yaml
            example = yaml.safe_load(sample.read_text(encoding="utf-8"))
            example["metadata"] = {"namespace": "maas-local", "name": "local-created"}
            example["spec"]["modelAlias"] = "local-created"
            example["spec"]["source"]["externalAPI"]["upstreamModel"] = "local-example-v1"
            example = {key: example[key] for key in ("apiVersion", "kind", "metadata", "spec")}
            data = (json.dumps(example, indent=2) + "\n").encode()
            (output / "workbench-example.json").write_bytes(data)
            generated["workbench-example.json"] = hashlib.sha256(data).hexdigest()
        manifest = {
            "schemaVersion": "unified-repository-source-1.0",
            "repositoryCommit": commit,
            "repositoryTree": git(repo, "rev-parse", commit + "^{tree}").decode().strip(),
            "sourceCodeCommit": code,
            "components": {name: commit for name in ("backend", "console", "deployment", "tools", "qa")},
            "scope": "one committed source snapshot; local management only; not deployment approval",
            "sourceChecks": checks, "files": files, "generatedFiles": generated,
        }
        (output / "workbench-sources.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"output": str(output), "repositoryCommit": commit, "sourceCodeCommit": code,
            "backendCommit": commit, "consoleCommit": commit, "deploymentCommit": commit}
