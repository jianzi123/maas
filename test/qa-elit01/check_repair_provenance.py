"""Read-only Git/ZIP/lock byte checks, not product acceptance or manifest execution."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

def digest(data):
    return hashlib.sha256(data).hexdigest()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--inputs", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    assert not a.output.exists()
    product = a.inputs / "product"
    manifest = json.loads((a.inputs / "input-manifest.json").read_bytes())
    head = manifest["product_head"]
    def archive(ref, names):
        # No shell. Require exact repository paths before passing them to git archive.
        tree = subprocess.check_output(["git","-C",str(a.repo),"ls-tree","-r","--name-only",ref]).decode().splitlines()
        assert set(names) <= set(tree)
        return zipfile.ZipFile(io.BytesIO(subprocess.check_output(["git","-C",str(a.repo),"archive","--format=zip",ref,*names])))
    paths = ["deploy/build-sources.lock.json","deploy/charts/maas-platform/runtime-interface.json", "deploy/dependencies.lock.json","deploy/identities.json"]
    lock, interface, dep, identity = [json.loads((product / name).read_bytes()) for name in paths]
    code = manifest["delivery"]
    assert all(lock[c]["sourceCommit"] == interface[c]["sourceCommit"] == code for c in ("backend","console"))
    assert identity["sourceCommit"] == code == dep["sourceBaseline"]["backendInspected"] == dep["sourceBaseline"]["consoleInspected"]
    assert dep["databaseIdentities"] == identity
    assert dep["sourceBaseline"]["sourceInventorySha256"] == digest((product / paths[0]).read_bytes())
    assert all(d["sourceCommit"] == code for d in dep["dependencies"] if d["id"] in ("core","operator","console"))
    inventory = {}
    for component in ("backend","console"):
        assert interface[component]["files"] == lock[component]["files"]
        for name, value in lock[component]["files"].items():
            assert name not in inventory or inventory[name] == value
            inventory[name] = value
    with archive(head, list(inventory)) as z:
        assert all(digest(z.read(name)) == value for name,value in inventory.items())
    delivery = product / "tools/perf/diagnostics/evidence/single-model-v0.23/delivery"
    package = json.loads((delivery / "delivery-manifest.json").read_bytes())
    packages = []
    for item in package["packages"]:
        data = (delivery / item["file"]).read_bytes()
        assert len(data) == item["bytes"] and digest(data) == item["sha256"]
        packages.append({"file":item["file"],"sha256":digest(data),"bytes":len(data)})
    with zipfile.ZipFile(delivery / "MAAS-10-single-model-v0.23-code.zip") as z:
        packaged = json.loads(z.read("manifest.json"))
        assert packaged["head"] == package["head"] and packaged["implementation"] == manifest["implementation"]
        files = [item["path"] for item in packaged["files"]]
        assert len(files) == len(set(files)) == 28
        assert set(z.namelist()) == set(files) | {"manifest.json","changes.patch","BASELINE.txt"}
        for item in packaged["files"]:
            value = z.read(item["path"])
            assert len(value) == item["bytes"] and digest(value) == item["sha256"]
        with archive(package["head"],files) as frozen:
            assert all(z.read(n) == frozen.read(n) for n in files)
        analyzer = "tools/perf/operators/local_gpu/analyze_kv_cadence.py"
        assert z.read(analyzer) == (product / analyzer).read_bytes()
        legacy = "tools/perf/operators/local_gpu/legacy_source/analyze_kv_cadence.v0.22.py.txt"
        assert (product / legacy).read_bytes() == (a.inputs / "legacy" / analyzer).read_bytes()
        source_hash = digest(z.read(analyzer))
    result = {"product_head":head,"execution_source_sha256":source_hash,
              "code_commit":manifest["implementation"],"archive_source_lock":package["head"],
              "archive_delivery":code,"final_lock":head,"four_lock_source_commit":code,
              "inventory_files_verified":len(inventory),"package_source_files_verified":len(files),
              "packages":packages,"four_lock_sha256":{name:digest((product/name).read_bytes()) for name in paths},
              "legacy_analyzer_bytes_preserved":True,"deploymentApproved":dep["deploymentApproved"],
              "result":"PASS: byte/provenance checks only"}
    a.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result))

if __name__ == "__main__":
    main()
