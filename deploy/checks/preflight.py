#!/usr/bin/env python3
"""Read-only input gate. Success is input completeness, never deployment authorization."""
import argparse
import json
from pathlib import Path
from jsonschema import Draft7Validator
from verify import CHART, ROOT, load_values, validate_network
from identities import identity_blockers

def blockers(values, lock, interface=None):
    if interface is None:
        interface = json.loads((CHART / "runtime-interface.json").read_text(encoding="utf-8"))
    result = identity_blockers(lock.get("databaseIdentities", {}), lock.get("target", {}).get("namespace"))
    schema = json.loads((CHART / "values.schema.json").read_text())
    if not Draft7Validator(schema).is_valid(values):
        result.append("values.schema")
        return result
    try:
        validate_network(values)
    except ValueError:
        result.append("network.constraints")
    if not lock.get("deploymentApproved"):
        result.append("deploymentApproved")
    for key in ("cluster", "kubernetesVersion", "apiGroup", "authorizationRef", "namespace", "rpo", "rto", "retention"):
        if not lock.get("target", {}).get(key):
            result.append("target." + key)
    sources = lock.get("target", {}).get("modelSources")
    if not isinstance(sources, list) or not sources or not set(sources) <= {"ExternalAPI", "SelfHosted"}:
        result.append("target.modelSources")
        sources = ["ExternalAPI", "SelfHosted"]
    expected = ["kubernetes","helm","platform-chart","operator","core","console","mysql","redis","higress-chart","higress-images-envoy","higress-crds","higress-H1-H4-wasm","modelrelease-crd","lws-chart-controller-crd","sglang","gpu-driver-device-plugin","weights-tokenizer","dns-cni-csi","tls-mtls-ca","build-runtime-images","monitor-backup-tooling"]
    if {d["id"] for d in lock.get("dependencies", [])} != set(expected):
        result.append("dependencies.inventory")
    if set(lock.get("runtimeGates", {})) != set(["core-entrypoint-health-metrics","release-adapters-H1-H4","secret-agent-instance-channel","protected-validation-key-budget","mysql-migrations-roles","redis-rebuild-epoch","network-cni-egress","backup-restore-fencing","LWS-SGLang-GPU"]):
        result.append("runtimeGates.inventory")
    if values["api"]["group"] in ("", "serving.maas.example") or values["api"]["reviewPlaceholderAcknowledged"]:
        result.append("api.group.pending")
    if values["api"]["group"] != lock.get("target", {}).get("apiGroup"):
        result.append("api.group.mismatch")
    if lock.get("sourceBaseline", {}).get("backendInspected") != interface["backend"]["sourceCommit"]:
        result.append("interface.backendSourceMismatch")
    if lock.get("sourceBaseline", {}).get("consoleInspected") != interface["console"]["sourceCommit"]:
        result.append("interface.consoleSourceMismatch")
    if values["api"]["group"] != interface["backend"]["apiGroup"]:
        result.append("interface.compiledGroupMismatch")
    if not interface["backend"]["core"]["deploymentReady"]:
        result.append("interface.core.productionAdapterMissing")
    if not interface["backend"]["operator"]["deploymentReady"]:
        result.append("interface.operator.productionAdaptersMissing")
    if not interface["console"]["productionSessionReady"]:
        result.append("interface.console.productionSessionMissing")
    for domain in ("kernel", "release"):
        expected_rows = [{"version":m["version"], "sha256":m["sha256"], "state":"Applied"} for m in interface["migrations"] if m["domain"] == domain]
        actual = lock.get("migrationState", {}).get(domain, [])
        if actual != expected_rows:
            result.append("migrationState." + domain)
    for name in ("operator", "core", "console"):
        w = values[name]
        if not w["enabled"]:
            result.append(name + ".disabled")
        if w["enabled"] and (".invalid/" in w["image"]["repository"] or len(set(w["image"]["digest"].split(":")[-1])) == 1):
            result.append(name + ".syntheticImage")
    for key in ("namespace", "gatewayService"):
        if not values["higress"][key]:
            result.append("higress." + key)
    if values["mode"] == "hybrid" and (not values["higress"]["externalEgressPolicyRef"] or "PENDING" in values["higress"]["externalEgressPolicyRef"] or "synthetic" in values["higress"]["externalEgressPolicyRef"]):
        result.append("higress.externalEgressPolicyRef")
    by_id = {d["id"]: d for d in lock.get("dependencies", [])}
    for name in ("operator", "core", "console"):
        w = values[name]
        item = by_id.get(name, {})
        expected_source = interface["console" if name == "console" else "backend"]["sourceCommit"]
        if w["enabled"] and item.get("sourceCommit") != expected_source:
            result.append(name + ".imageSourceMismatch")
        if name != "console" and w["enabled"] and item.get("compiledAPIGroup") != interface["backend"]["apiGroup"]:
            result.append(name + ".imageGroupMismatch")
        if w["enabled"] and (item.get("digest") != w["image"]["digest"] or item.get("mirror") != w["image"]["repository"]):
            result.append(name + ".imageLockMismatch")
    for item in lock.get("dependencies", []):
        if not set(item.get("requiredFor", sources)) & set(sources):
            continue
        if item.get("status") != "approved" or not item.get("version") or not item.get("evidenceRef"):
            result.append("dependency." + item["id"])
        if item.get("artifact") and (not item.get("digest") or not item.get("mirror")):
            result.append("artifact." + item["id"])
    components = lock.get("gatewayComponents", [])
    if {c.get("id") for c in components} != {"H1-H4-wasm", "H2-envoy-reporter", "H3-instance-agent", "secret-agent-local-channel"}:
        result.append("gatewayComponents.inventory")
    for component in components:
        if component.get("status") != "approved" or not all(component.get(k) for k in ("sourceCommit", "digest", "mirror", "abi", "identityRef", "evidenceRef")):
            result.append("gatewayComponent." + str(component.get("id")))
    for key, state in lock.get("runtimeGates", {}).items():
        if key == "LWS-SGLang-GPU" and "SelfHosted" not in sources:
            continue
        if state != "verified":
            result.append("runtimeGate." + key)
    return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--values", required=True)
    p.add_argument("--lock", default=str(ROOT / "dependencies.lock.json"))
    args = p.parse_args()
    lock = json.loads(Path(args.lock).read_text(encoding="utf-8"))
    result = blockers(load_values(args.values), lock)
    print(json.dumps({"ready": not result, "blockers": result, "scope": "offline-input-completeness-only"}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result else 0)

if __name__ == "__main__":
    main()