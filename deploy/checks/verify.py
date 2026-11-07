#!/usr/bin/env python3
"""Local Helm/schema/permission checks. Never contacts a Kubernetes API."""
import argparse
import copy
import hashlib
import importlib.metadata
import ipaddress
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import sys
from datetime import datetime, timezone
import yaml
from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "maas-platform"
RESULTS = []

def record(label, passed):
    RESULTS.append({"check": label, "passed": bool(passed)})
    if not passed:
        raise RuntimeError("check failed: " + label)

def merge(base, patch):
    out = copy.deepcopy(base)
    for key, value in patch.items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else copy.deepcopy(value)
    return out

def load_values(path=None):
    base = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    return merge(base, yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}) if path else base

def validate_network(values):
    for component, policy in values["network"].items():
        for direction in ("ingress", "egress"):
            for rule in policy[direction]:
                for peer in rule["from" if direction == "ingress" else "to"]:
                    if "ipBlock" in peer:
                        net = ipaddress.ip_network(peer["ipBlock"]["cidr"], strict=True)
                        if net.prefixlen == 0:
                            raise ValueError("unrestricted CIDR")
                        # Platform components cannot reach public upstreams directly.
                        private = [ipaddress.ip_network(c) for c in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")]
                        test = [ipaddress.ip_network("192.0.2.0/24")]
                        if direction == "egress" and not any(net.version == n.version and net.subnet_of(n) for n in private + test):
                            raise ValueError("platform external egress forbidden")
    return True

def run(helm, args, expect_success=True):
    if os.name == 'nt' and Path(helm[0]).name.lower() in ('wsl', 'wsl.exe'):
        args = [('/mnt/' + Path(a).drive[0].lower() + '/' + Path(a).relative_to(Path(a).anchor).as_posix()) if Path(a).is_absolute() else a for a in args]
    p = subprocess.run(helm + args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
    if (p.returncode == 0) != expect_success:
        # Fixtures contain no secrets. Avoid echoing arbitrary user config/Helm errors.
        raise RuntimeError("unexpected helm result for " + args[0])
    return p.stdout

def inspect_manifest(text, prefix):
    docs = [d for d in yaml.safe_load_all(text) if d]
    kinds = [d["kind"] for d in docs]
    record(prefix + ": no Secret/CRD/database/PVC/workload-model creation", not set(kinds) & {"Secret", "CustomResourceDefinition", "PersistentVolumeClaim", "StatefulSet", "LeaderWorkerSet", "ModelRelease"})
    record(prefix + ": expected deployments", kinds.count("Deployment") == 3)
    record(prefix + ": explicit policies", kinds.count("NetworkPolicy") == 3)
    deployments = {d["metadata"]["name"].split("-")[-1]: d for d in docs if d["kind"] == "Deployment"}
    for name, d in deployments.items():
        pod = d["spec"]["template"]["spec"]
        c = pod["containers"][0]
        record(prefix + ": " + name + " image pinned", "@sha256:" in c["image"])
        record(prefix + ": " + name + " nonroot+readonly", pod["securityContext"]["runAsNonRoot"] and c["securityContext"]["readOnlyRootFilesystem"] and not c["securityContext"]["allowPrivilegeEscalation"])
        record(prefix + ": " + name + " exec readiness", c["readinessProbe"]["exec"]["command"][0] == "/maas-probe" and c["readinessProbe"]["exec"]["command"][1].endswith("/readyz"))
        record(prefix + ": " + name + " token isolation", pod["automountServiceAccountToken"] == (name == "operator"))
        record(prefix + ": " + name + " no env literals", not c.get("env") and not c.get("envFrom"))
    op = deployments["operator"]["spec"]["template"]["spec"]
    record(prefix + ": operator no business credentials", {v["name"] for v in op["volumes"]} == {"tmp", "webhook-tls"})
    for d in docs:
        if d["kind"] in ("Role", "ClusterRole"):
            for rule in d["rules"]:
                record(prefix + ": RBAC narrow " + ",".join(rule["resources"]), "*" not in json.dumps(rule) and not set(rule["resources"]) & {"secrets", "namespaces", "customresourcedefinitions", "persistentvolumeclaims"})
        if d["kind"] == "ClusterRole":
            record(prefix + ": cluster read only", all(set(r["verbs"]) <= {"get", "list", "watch"} for r in d["rules"]))
        if d["kind"] == "Service":
            record(prefix + ": private service " + d["metadata"]["name"], d["spec"]["type"] == "ClusterIP")
        if d["kind"] == "NetworkPolicy":
            record(prefix + ": deny default " + d["metadata"]["name"], set(d["spec"]["policyTypes"]) == {"Ingress", "Egress"})
        if d["kind"] == "ValidatingWebhookConfiguration":
            record(prefix + ": webhook fail closed", all(w["failurePolicy"] == "Fail" and w["sideEffects"] == "None" and w["clientConfig"].get("caBundle") for w in d["webhooks"]))
        if d["kind"] == "Ingress":
            backends = [p["backend"]["service"]["name"] for r in d["spec"]["rules"] for p in r["http"]["paths"]]
            record(prefix + ": TLS and Go entry", bool(d["spec"]["tls"]) and all(b.endswith(("-core", "-console")) for b in backends))
    # Service and policy selectors must match their own Deployment labels.
    for d in docs:
        if d["kind"] not in ("Service", "NetworkPolicy"):
            continue
        selector = d["spec"]["selector"] if d["kind"] == "Service" else d["spec"]["podSelector"]["matchLabels"]
        matches = [x for x in deployments.values() if all(x["spec"]["template"]["metadata"]["labels"].get(k) == v for k,v in selector.items())]
        record(prefix + ": selector " + d["metadata"]["name"], len(matches) == 1)
    return len(docs)

def verify(helm):
    schema = json.loads((CHART / "values.schema.json").read_text())
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    base = load_values()
    record("default schema", validator.is_valid(base))
    run(helm, ["lint", str(CHART), "--strict"])
    default_docs = run(helm, ["template", "review", str(CHART)])
    record("disabled default renders no workloads", not list(filter(None, yaml.safe_load_all(default_docs))))
    fixture = load_values(ROOT / "tests/fixtures/internal.yaml")
    record("internal fixture schema", validator.is_valid(fixture))
    negative = {
        "missing digest": {"core": {"image": {"digest": ""}}},
        "mutable tag": {"core": {"image": {"repository": "registry.invalid/core:latest"}}},
        "inline key": {"core": {"apiKey": "SYNTHETIC-KEY"}},
        "missing command": {"core": {"command": []}},
        "missing credentials": {"core": {"existingSecret": ""}},
        "missing webhook CA": {"operator": {"webhookCABundle": ""}},
        "cluster scope not acknowledged": {"operator": {"acknowledgeClusterWatch": False}},
        "missing API group": {"api": {"group": ""}},
        "install dependency bypass": {"higress": {"strategy": "install"}},
        "unrestricted peer": {"network": {"core": {"egress": [{"to": [{}], "ports": [{"port": 443, "protocol": "TCP"}]}]}}},
        "implicit port allow": {"network": {"core": {"egress": [{"to": [{"ipBlock": {"cidr": "10.0.0.0/8"}}]}]}}},
        "invalid readiness": {"core": {"probes": {"readyPath": ""}}},
        "missing TLS": {"ingress": {"existingTLSSecret": ""}},
    }
    with tempfile.TemporaryDirectory(prefix="maas-chart-", dir=ROOT) as temp:
        for label, patch in negative.items():
            values = merge(fixture, patch)
            record("schema rejects " + label, not validator.is_valid(values))
            path = Path(temp) / "negative.yaml"
            path.write_text(yaml.safe_dump(values), encoding="utf-8")
            run(helm, ["template", "review", str(CHART), "-f", str(path)], expect_success=False)
        for label, patch in {
            "placeholder group unacknowledged": {"api": {"reviewPlaceholderAcknowledged": False}},
            "hybrid missing gateway egress": {"mode": "hybrid", "higress": {"externalEgressPolicyRef": ""}},
            "ingress without core": {"core": {"enabled": False}},
            "wrong compiled API group": {"api": {"group": "other.internal.test"}},
            "controlled API mistaken for service": {"core": {"command": ["/control-api"]}},
            "core readiness aliases liveness": {"core": {"probes": {"readyPath": "/healthz"}}},
        }.items():
            path = Path(temp) / "guard.yaml"
            path.write_text(yaml.safe_dump(merge(fixture, patch)), encoding="utf-8")
            run(helm, ["template", "review", str(CHART), "-f", str(path)], expect_success=False)
            record("template rejects " + label, True)
    counts = {}
    for profile in ("internal", "hybrid"):
        path = ROOT / "tests/fixtures" / (profile + ".yaml")
        values = load_values(path)
        record(profile + " schema", validator.is_valid(values))
        record(profile + " network semantics", validate_network(values))
        run(helm, ["lint", str(CHART), "--strict", "-f", str(path)])
        counts[profile] = inspect_manifest(run(helm, ["template", "review", str(CHART), "--namespace", "maas-review", "-f", str(path)]), profile)
    for cidr in ("0.0.0.0/0", "::/0", "8.8.8.8/32", "not-a-cidr"):
        values = merge(fixture, {"network": {"core": {"egress": [{"to": [{"ipBlock": {"cidr": cidr}}], "ports": [{"port": 443, "protocol": "TCP"}]}]}}})
        try:
            validate_network(values)
        except ValueError:
            record("network rejects " + cidr, True)
        else:
            record("network rejects " + cidr, False)
    return counts

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helm", default="helm", help="single executable path")
    parser.add_argument("--helm-command", help="command prefix, e.g. 'wsl -d Ubuntu-22.04 -- helm'")
    args = parser.parse_args()
    helm = shlex.split(args.helm_command) if args.helm_command else [args.helm]
    counts = verify(helm)
    files = {}
    for p in sorted(ROOT.rglob("*")):
        if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts and "evidence" not in p.relative_to(ROOT).parts:
            files[p.relative_to(ROOT).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "scope": "local-static-and-synthetic-render-only",
              "helm": run(helm, ["version", "--short"]).strip(), "python": sys.version.split()[0],
              "packages": {p: importlib.metadata.version(p) for p in ("PyYAML", "jsonschema")},
              "checks_passed": len(RESULTS), "checks": RESULTS, "rendered_documents": counts,
              "files_sha256": files,
              "not_executed": ["cluster-install-upgrade-rollback", "server-dry-run-CEL-webhook", "real-RBAC-Secret-H1-H4", "model-GPU-paid-API", "backup-restore-HA", "A01-A34-runtime"]}
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence/verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"checks_passed": len(RESULTS), "documents": counts, "scope": report["scope"]}))

if __name__ == "__main__":
    main()