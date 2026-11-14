import json, pathlib, hashlib, subprocess
root=pathlib.Path(__file__).resolve().parents[2]
p=root/"test/qa-ui16"
arch=root.parent/"UI16-independent-evidence"
def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))
first,extra=read(p/"independent-results-first.json"),read(p/"independent-results-extra.json")
passed=[x["fullName"] for d in (first,extra) for r in d["testResults"] for x in r["assertionResults"] if x["status"]=="passed"]
assert len(passed)==18 and len(set(passed))==18
go,fx,focus=[read(arch/sub/"results.json") for sub in ("go","fixture","independent")]
assert len(go["checks"])==24 and len(fx["checks"])==24 and len(focus["checks"])==4 and len(focus["metrics"])==15
assert all(d["failure"] is None and not d["errors"] for d in (go,fx,focus))
assert go["generationPosts"]==0 and fx["generationPosts"]==1
assert sum(r["method"]=="DELETE" for r in go["responses"])==1
data={
 "candidate":"b73d96be97e3666d3470106d5b6d13fd91c5c9f7",
 "unified_base":"8dbf99ef59c847da775b83d0eeb7dc8f8bf48a9a",
 "code_source":"f182ee2380424f70fc004657c0d9ed4a165c4132",
 "node":subprocess.check_output(["node","--version"],text=True).strip(),
 "edge":"157.0.4341.46","go":"go1.26.0 linux/amd64","mysql":"8.4.7","envtest":"v1.36.0",
 "package_lock_sha256":hashlib.sha256((root/"console/package-lock.json").read_bytes()).hexdigest(),
 "dependency_versions":{n:read(root/"console/node_modules"/n/"package.json")["version"] for n in ("vitest","jsdom","vue","vite","playwright-core")},
 "results":{"synthetic_component_unique_passed":18,"synthetic_component_unique_failed":0,"extra_run_filtered_cases":15,"fixture_browser_passed":24,"actual_management_browser_passed":24,"additional_edge_actions_passed":4,"additional_layout_samples":15},
 "component_cases":passed,
 "real_delete_operation_id":next(r["path"].split("/")[-1] for r in reversed(go["responses"]) if "/release-operations/" in r["path"]),
 "real_cleanup":read(arch/"go/cleanup.json"),
 "full_A01_A34_acceptance":"NOT_ACCEPTED"
}
(p/"summary.json").write_text(json.dumps(data,ensure_ascii=True,indent=2),encoding="utf8")
manifest={str(f.relative_to(arch)):{"bytes":f.stat().st_size,"sha256":hashlib.sha256(f.read_bytes()).hexdigest()} for f in sorted(arch.rglob("*")) if f.is_file() and f.name!="manifest.json"}
(arch/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf8")
print(json.dumps(data["results"]))
print("raw_artifacts",len(manifest))