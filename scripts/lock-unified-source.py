"""Lock all components to one committed code snapshot; writes only four metadata files."""
import argparse
import copy
import hashlib
import json
import sys
from unified_sources import ROOT, clean, git, snapshot


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()
    clean(ROOT)
    sys.path.insert(0, str(ROOT / "deploy/checks"))
    from source_context import inventory
    with snapshot(ROOT, args.ref) as (commit, source):
        deploy = ROOT / "deploy"
        interface = json.loads((source / "deploy/charts/maas-platform/runtime-interface.json").read_text(encoding="utf-8"))
        identities = json.loads((source / "deploy/identities.json").read_text(encoding="utf-8"))
        dependencies = json.loads((source / "deploy/dependencies.lock.json").read_text(encoding="utf-8"))
        previous = json.loads((source / "deploy/build-sources.lock.json").read_text(encoding="utf-8"))
        qa = copy.deepcopy(previous["qa"])
        qa["postQaChanges"] = git(ROOT, "diff", "--name-only", qa["targetCommit"], commit).decode().splitlines()
        qa["postQaChangesAreLocalServiceAndDocsOnly"] = False
        qa["scope"] = "Historical R1-R3 controlled QA at targetCommit only; not unified-candidate or production acceptance"
        inventories = {name: inventory(source, name) for name in ("backend", "console")}
        source_lock = {
            "schemaVersion": "1.0", "sourceMode": "single-repository-code-commit",
            **{name: {"sourceCommit": commit, "files": inventories[name]} for name in inventories},
            "qa": qa,
        }
        inventory_path = deploy / "build-sources.lock.json"
        write(inventory_path, source_lock)
        for name in inventories:
            interface[name]["sourceCommit"] = commit
            interface[name]["files"] = inventories[name]
            interface[name]["candidateState"] = "integrated-unmerged"
        interface["sourceMode"] = "single-repository-code-commit"
        interface["localWorkbench"]["sourceMode"] = "one Git snapshot; generated manifest records export commit and code lock"
        # Preserve every real production readiness flag and the actual DSN interface.
        identities["sourceCommit"] = commit
        identities["publisherCompletionContract"]["evidence"] = qa
        write(deploy / "identities.json", identities)
        dependencies["databaseIdentities"] = identities
        baseline = dependencies["sourceBaseline"]
        baseline.update(backendInspected=commit, consoleInspected=commit,
                        candidateState="integrated-unmerged", candidatePR=None,
                        integrationBranch="integrate/MAAS-17-unified-20261114",
                        sourceInventorySha256=hashlib.sha256(inventory_path.read_bytes()).hexdigest())
        baseline["upstreamPRs"] = {"backend": "https://github.com/jianzi123/maas/pull/6",
                                  "deployment": "https://github.com/jianzi123/maas/pull/5",
                                  "performance": "https://github.com/jianzi123/maas/pull/7"}
        for dependency in dependencies["dependencies"]:
            if dependency["id"] in ("core", "operator", "console"):
                dependency["sourceCommit"] = commit
                dependency["note"] = "Unified source snapshot; image/production readiness remain independently pending"
        write(deploy / "dependencies.lock.json", dependencies)
        write(deploy / "charts/maas-platform/runtime-interface.json", interface)
    print(json.dumps({"sourceCodeCommit": commit, "backendFiles": len(inventories["backend"]),
                      "consoleFiles": len(inventories["console"]), "deploymentApproved": dependencies["deploymentApproved"]}))


if __name__ == "__main__":
    main()
