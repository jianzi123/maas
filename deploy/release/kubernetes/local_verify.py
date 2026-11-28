"""Opt-in native-YAML verification on a NEW, task-owned local kind cluster.

No current-context fallback, target clusters, paid models, image pushes or cleanup
of foreign resources. Every command has a deadline. Reports distinguish command
execution from fixtures/static validation. See LOCAL-VERIFICATION.md.
"""
import argparse
import ctypes
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

import yaml

ISSUE = "01a1a543-995c-71da-9aee-495935be2083"
OWNER = "maas.multica.ai/owner-issue"
NAME = re.compile(r"maas8-[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?")
NODE = "kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"


def decode(data):
    if not data:
        return ""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\0" in data[:80]:
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8", errors="replace")


def free_memory_mib():
    if os.name == "nt":
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total", "available", "page_total", "page_available",
                    "virtual_total", "virtual_available", "extended")]
        value = Memory(); value.length = ctypes.sizeof(value)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            raise RuntimeError("host_memory_unavailable")
        return value.available // (1024 * 1024)
    memory = Path("/proc/meminfo")
    if memory.is_file():
        for line in memory.read_text().splitlines():
            if line.startswith("MemAvailable:"):
                available = int(line.split()[1]) // 1024
                if "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower():
                    # WSL's free VM pages do not imply that its Windows host has RAM.
                    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"], capture_output=True, timeout=10)
                    if result.returncode:
                        raise RuntimeError("wsl_host_memory_unavailable")
                    available = min(available, int(decode(result.stdout).strip()) // 1024)
                return available
    raise RuntimeError("host_memory_unavailable")


def profile_check(config):
    offline = config.get("offline_controlled", {}).get("enabled", False)
    if offline and (config.get("models") or config.get("management", {}).get("enabled")):
        raise ValueError("offline_profile_cannot_mix_models_or_management")
    return "offline-controlled" if offline else "external-api"


def local_docker_endpoint(host):
    return host.startswith("unix:///") or host.lower().startswith("npipe:////./pipe/")


def migration_check(source, text):
    expected = {int(p.name.split("_")[0]): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (source / "internal/app/migrations").glob("[0-9]*_*.sql")}
    if not expected:
        raise ValueError("required_migration_sources_missing")
    rows = {}
    for line in text.splitlines():
        version, state, sha = line.split("\t")
        if int(version) in rows:
            raise ValueError("duplicate_migration_version")
        rows[int(version)] = (state, sha)
    bad = [v for v, sha in expected.items() if rows.get(v) != ("Applied", sha)]
    if bad:
        raise ValueError("required_migrations_not_applied:" + ",".join(map(str, bad)))
    return sorted(expected)


def scoped_documents(documents, namespace, tag):
    if not NAME.fullmatch(namespace):
        raise ValueError("owned_namespace_prefix_required")
    result = []
    for original in documents:
        if not original:
            continue
        doc = json.loads(json.dumps(original).replace("__IMAGE_TAG__", tag))
        if doc["kind"] not in {"Namespace", "ConfigMap", "Secret", "Service", "StatefulSet", "NetworkPolicy", "Deployment", "Job"}:
            raise ValueError("resource_kind_outside_native_installer_scope")
        if doc["kind"] == "Namespace":
            doc["metadata"]["name"] = namespace
            doc["metadata"].setdefault("labels", {})[OWNER] = ISSUE
        else:
            doc["metadata"]["namespace"] = namespace
        result.append(doc)
    return result


class Runner:
    def __init__(self, root, docker="docker", kubectl="kubectl", kind="kind"):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs = self.root / "evidence"; self.logs.mkdir(exist_ok=True)
        self.docker, self.kubectl, self.kind = docker, kubectl, kind
        self.steps = []

    def run(self, args, name, timeout=30, data=None, check=True, log=True):
        started = time.monotonic()
        try:
            proc = subprocess.run(list(map(str, args)), input=data.encode() if data else None,
                                  capture_output=True, timeout=timeout)
            code, out, err = proc.returncode, decode(proc.stdout), decode(proc.stderr)
        except subprocess.TimeoutExpired as e:
            code, out, err = 124, decode(e.stdout), decode(e.stderr) + "\ncommand_deadline_exceeded"
        except OSError as e:
            code, out, err = 127, "", type(e).__name__ + ": executable unavailable"
        row = {"step": name, "argv": list(map(str, args)), "exitCode": code,
               "seconds": round(time.monotonic() - started, 3)}
        self.steps.append(row)
        if log:
            (self.logs / (name + ".stdout.txt")).write_text(out, encoding="utf-8")
            (self.logs / (name + ".stderr.txt")).write_text(err, encoding="utf-8")
        self.save()
        if check and code:
            raise RuntimeError(name + ": exit " + str(code))
        return code, out, err

    def save(self):
        (self.logs / "commands.json").write_text(json.dumps(self.steps, indent=2) + "\n", encoding="utf-8")

    def probe(self, minimum):
        memory = free_memory_mib()
        # kind inherits these environment variables. Refuse remote Docker before
        # making an API connection; never print context credentials or URLs.
        if os.environ.get("DOCKER_HOST") and not os.environ.get("DOCKER_CONTEXT"):
            local = local_docker_endpoint(os.environ["DOCKER_HOST"])
        else:
            command = [self.docker, "context", "inspect"]
            if os.environ.get("DOCKER_CONTEXT"):
                command.append(os.environ["DOCKER_CONTEXT"])
            code, host, _ = self.run(command + ["--format", '{{(index .Endpoints "docker").Host}}'], "docker-endpoint", 10, check=False, log=False)
            local = code == 0 and local_docker_endpoint(host.strip())
        engine, out = 1, ""
        if local:
            engine, out, _ = self.run([self.docker, "version", "--format", "{{.Server.Version}}"], "engine", 20, check=False)
        for tool, name in ((self.kubectl, "kubectl"), (self.kind, "kind")):
            self.run([tool, "version", "--client=true", "-o", "json"] if name == "kubectl" else [tool, "version"], name, 10, check=False)
        result = {"scope": "local-environment-only-no-cluster-writes", "availableMemoryMiB": memory, "localDockerEndpoint": local,
                  "minimumFreeMiB": minimum, "engineAvailable": engine == 0 and bool(out.strip()),
                  "resourcesAvailable": memory >= minimum, "clusterInstalled": False}
        result["canCreateLocalCluster"] = result["engineAvailable"] and result["resourcesAvailable"] and self.steps[-1]["exitCode"] == 0 and self.steps[-2]["exitCode"] == 0
        (self.logs / "environment.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result

    def owned(self):
        state = json.loads((self.root / "owner.json").read_text(encoding="utf-8"))
        kubeconfig = (self.root / "kubeconfig").resolve()
        if state.get("issue") != ISSUE or not NAME.fullmatch(state.get("cluster", "")) or not NAME.fullmatch(state.get("namespace", "")) or state.get("kubeconfig") != str(kubeconfig) or not state.get("createdHere"):
            raise ValueError("owned_cluster_record_required")
        self.state = state
        self.k = [self.kubectl, "--kubeconfig", str(kubeconfig), "--context", "kind-" + state["cluster"], "--request-timeout=15s"]
        return state

    def kub(self, args, name, **kw):
        return self.run(self.k + ["-n", self.state["namespace"]] + args, name, **kw)

    def assert_namespace(self):
        _, raw, _ = self.kub(["get", "namespace", self.state["namespace"], "-o", "json"], "namespace-owner")
        if json.loads(raw)["metadata"].get("labels", {}).get(OWNER) != ISSUE:
            raise ValueError("foreign_namespace_refused")

    def sql(self, text, name):
        # Only the owned bundled MySQL. Credentials never enter argv or reports.
        return self.kub(["exec", "-i", "mysql-0", "--", "sh", "-c",
                         'export MYSQL_PWD="$(cat /run/mysql-secret/root-password)"; exec mysql -uroot --batch --skip-column-names maas'],
                        name, data=text, timeout=40)[1]

    def schema(self, source):
        text = self.sql("SELECT version,state,sha256 FROM product_schema_migrations ORDER BY version;", "migration-states")
        return migration_check(source, text)

    def snapshot(self, name):
        raw = self.sql("SELECT 'requests',COUNT(*) FROM generation_requests;\nSELECT 'usage',COUNT(*),COUNT(DISTINCT request_id) FROM usage_events;\nSELECT session_id,revision,SHA2(CAST(document AS CHAR),256) FROM agent_sessions_v1 ORDER BY session_id;", name)
        _, pvc, _ = self.kub(["get", "pvc", "data-mysql-0", "-o", "json"], name + "-pvc")
        item = json.loads(pvc)
        if item.get("status", {}).get("phase") != "Bound":
            raise RuntimeError("mysql_pvc_not_bound")
        return {"ledgerDocumentSha256": hashlib.sha256(raw.encode()).hexdigest(),
                "pvcUID": item["metadata"]["uid"], "volumeName": item["spec"]["volumeName"]}


def source_identity(r, source):
    _, sha, _ = r.run(["git", "-C", str(source), "rev-parse", "HEAD"], "source-ref")
    _, dirty, _ = r.run(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=normal"], "source-clean")
    if dirty.strip():
        raise ValueError("commit_source_before_runtime_validation")
    head = sha.strip()
    sys.path.insert(0, str(source / "scripts"))
    from unified_sources import LOCK_FILES, snapshot, verify as verify_source
    # Compare an exported tree, not caches/.git from the build working directory.
    with snapshot(source, head) as (_, exported):
        revision, checks = verify_source(source, head, exported)
        lock = json.loads((exported / "deploy/build-sources.lock.json").read_text(encoding="utf-8"))
        actual = {p.relative_to(exported).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (exported / "deploy").rglob("*")
                  if p.is_file() and p.relative_to(exported).as_posix() not in LOCK_FILES}
        deployment = {"component": "deployment", "expected": len(lock["deployment"]["files"]),
                      "matched": len(actual) if actual == lock["deployment"]["files"] else 0,
                      "passed": actual == lock["deployment"]["files"] and lock["deployment"]["sourceCommit"] == revision}
        if not deployment["passed"]:
            raise ValueError("deployment_inventory_mismatch")
    (r.logs / "source-locks.json").write_text(json.dumps({"repositoryCommit": head, "sourceCodeCommit": revision, "checks": checks + [deployment]}, indent=2) + "\n", encoding="utf-8")
    return head, revision, revision[:12]


def render_native(r, source, namespace, tag):
    for name in ("namespace.yaml", "mysql.yaml", "migration.yaml", "application.yaml"):
        docs = yaml.safe_load_all((source / "deploy/release/kubernetes" / name).read_text(encoding="utf-8"))
        (r.root / name).write_text(yaml.safe_dump_all(scoped_documents(docs, namespace, tag), sort_keys=False), encoding="utf-8")


def prepare(r, args):
    source = args.source.resolve()
    if (r.root / "config.yaml").exists() or (r.root / ".secrets").exists():
        raise ValueError("existing_installation_identity_never_overwritten")
    if not NAME.fullmatch(args.cluster) or not NAME.fullmatch(args.namespace):
        raise ValueError("maas8_owned_names_required")
    head, revision, tag = source_identity(r, source)
    r.run([sys.executable, str(source / "deploy/release/configure.py"), "--format", "kubernetes", "--directory", str(r.root), "--source", str(source), "--profile", args.profile, "--port", str(args.port)], "generate-config")
    config = json.loads((r.root / "config/product.json").read_text(encoding="utf-8"))
    if profile_check(config) == "offline-controlled":
        config["offline_controlled"]["step_delay_ms"] = 5000
        for name in ("product.json", "migration.json"):
            (r.root / "config" / name).write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    # Render the ORIGINAL native resources. Never render secrets to stdout.
    docs = list(yaml.safe_load_all((r.root / "config.yaml").read_text(encoding="utf-8")))
    for d in docs:
        if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "maas-config":
            d["data"].update({"product.json": json.dumps(config), "migration.json": json.dumps(config)})
    (r.root / "config.yaml").write_text(yaml.safe_dump_all(scoped_documents(docs, args.namespace, tag), sort_keys=False), encoding="utf-8")
    os.chmod(r.root / "config.yaml", 0o600)
    render_native(r, source, args.namespace, tag)
    state = {"issue": ISSUE, "cluster": args.cluster, "namespace": args.namespace, "createdHere": False,
             "kubeconfig": str(r.root / "kubeconfig"), "source": str(source), "repositoryCommit": head, "revision": revision, "tag": tag, "port": args.port, "profile": args.profile}
    (r.root / "owner.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    kind_config = {"kind": "Cluster", "apiVersion": "kind.x-k8s.io/v1alpha4", "networking": {"apiServerAddress": "127.0.0.1"}, "nodes": [{"role": "control-plane", "image": NODE}]}
    (r.root / "kind.yaml").write_text(yaml.safe_dump(kind_config), encoding="utf-8")
    return {"prepared": True, "clusterInstalled": False, "revision": revision}


def create(r, args):
    env = r.probe(args.minimum_free_mib)
    if not env["canCreateLocalCluster"]:
        raise RuntimeError("local_environment_gate_failed: see evidence/environment.json; no cluster created")
    state = json.loads((r.root / "owner.json").read_text(encoding="utf-8"))
    if state["issue"] != ISSUE or not NAME.fullmatch(state["cluster"]) or state["createdHere"]:
        raise ValueError("fresh_owned_cluster_record_required")
    _, clusters, _ = r.run([r.kind, "get", "clusters"], "existing-clusters")
    if state["cluster"] in clusters.splitlines():
        raise ValueError("existing_cluster_never_adopted")
    r.run([r.kind, "create", "cluster", "--name", state["cluster"], "--config", str(r.root / "kind.yaml"), "--kubeconfig", str(r.root / "kubeconfig"), "--wait", "120s"], "create-owned-kind", 300)
    state["createdHere"] = True
    (r.root / "owner.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return {"clusterCreated": True, "applicationInstalled": False}


def install(r):
    state = r.owned(); source = Path(state["source"])
    # Image availability and source labels are checked BEFORE writing resources.
    for component in ("app", "web", "migrate"):
        image = "maas-" + component + ":" + state["tag"]
        _, label, _ = r.run([r.docker, "image", "inspect", image, "--format", '{{index .Config.Labels "org.opencontainers.image.revision"}}'], "image-" + component)
        if label.strip() != state["revision"]:
            raise ValueError("image_source_revision_mismatch")
        r.run([r.kind, "load", "docker-image", "--name", state["cluster"], image], "load-" + component, 180)
    r.run([r.kind, "load", "docker-image", "--name", state["cluster"], "mysql:8.4.7"], "load-mysql", 180)
    code, raw, _ = r.kub(["get", "namespace", state["namespace"], "--ignore-not-found", "-o", "json"], "check-namespace", check=False)
    if code or (raw.strip() and json.loads(raw)["metadata"].get("labels", {}).get(OWNER) != ISSUE):
        raise ValueError("existing_namespace_owner_not_verified")
    for name in ("namespace", "config", "mysql"):
        r.kub(["apply", "-f", str(r.root / (name + ".yaml"))], "apply-" + name)
    r.kub(["rollout", "status", "statefulset/mysql", "--timeout=300s"], "mysql-ready", timeout=330)
    # Old scheduler is stopped before every migration, including upgrades.
    code, raw, _ = r.kub(["get", "deployment", "maas", "--ignore-not-found", "-o", "name"], "existing-app", check=False)
    if code:
        raise RuntimeError("cannot_check_old_scheduler")
    if raw.strip():
        r.kub(["scale", "deployment/maas", "--replicas=0"], "stop-old-scheduler")
        r.kub(["wait", "--for=delete", "pod", "-l", "app=maas", "--timeout=90s"], "old-scheduler-gone", timeout=110)
    # Never consume a previous Job's Complete as a fresh install authorization.
    # Refuse active/ambiguous predecessor migrations before another explicit run.
    _, raw, _ = r.kub(["get", "jobs", "-o", "json"], "existing-migration-jobs", log=False)
    for old in json.loads(raw)["items"]:
        if old.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {}).get("app") != "maas-migrate":continue
        terminal = any(c.get("type") in ("Complete", "Failed") and c.get("status") == "True" for c in old.get("status", {}).get("conditions", []))
        if not terminal:raise RuntimeError("prior_migration_job_not_terminal_inspect_original")
    manifest = yaml.safe_load((r.root / "migration.yaml").read_text(encoding="utf-8"))
    job = "maas-migrate-" + state["tag"] + "-" + uuid.uuid4().hex[:8]
    manifest["metadata"]["name"] = job
    (r.logs / (job + ".json")).write_text(json.dumps({"job": job, "repositoryCommit": state.get("repositoryCommit"), "sourceCodeCommit": state["revision"]}, indent=2) + "\n", encoding="utf-8")
    r.kub(["create", "-f", "-"], "apply-migration", data=yaml.safe_dump(manifest))
    try:
        r.kub(["wait", "--for=condition=complete", "job/" + job, "--timeout=180s"], "migration-complete", timeout=200)
    finally:
        r.kub(["logs", "job/" + job], "migration-log", check=False)
    r.schema(source)
    r.kub(["apply", "-f", str(r.root / "application.yaml")], "apply-app")
    for name in ("maas", "web"):
        r.kub(["rollout", "status", "deployment/" + name, "--timeout=180s"], name + "-ready", timeout=200)
    return {"nativeInstalled": True, "requiredMigrationsApplied": True, "modelAcceptance": False}


def upgrade(r, args):
    state = r.owned(); r.assert_namespace()
    source = args.source.resolve()
    head, revision, tag = source_identity(r, source)
    if state["revision"] == revision:
        raise ValueError("same_version_upgrade_not_new_work")
    # Build new images first. Refuse missing/mislabeled images before stopping the
    # old scheduler or touching installation identities and workload manifests.
    for component in ("app", "web", "migrate"):
        _, label, _ = r.run([r.docker, "image", "inspect", "maas-" + component + ":" + tag, "--format", '{{index .Config.Labels "org.opencontainers.image.revision"}}'], "upgrade-image-" + component)
        if label.strip() != revision:
            raise ValueError("upgrade_image_source_mismatch")
    backup = r.root / ("owner-before-" + tag + ".json")
    if backup.exists():
        raise ValueError("previous_upgrade_record_requires_inspection")
    backup.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    # config.yaml, secrets, original origin/IDs/budgets/keys and PVC are retained.
    render_native(r, source, state["namespace"], tag)
    state.update(source=str(source), repositoryCommit=head, revision=revision, tag=tag)
    (r.root / "owner.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return install(r)


def stop(r):
    r.owned(); r.assert_namespace()
    # Default stop retains the owner record, cluster, PVC, Secret and all data.
    r.kub(["scale", "deployment/maas", "deployment/web", "--replicas=0"], "stop-app")
    r.kub(["wait", "--for=delete", "pod", "-l", "app=maas", "--timeout=90s"], "stop-scheduler-gone", timeout=110)
    r.kub(["scale", "statefulset/mysql", "--replicas=0"], "stop-mysql")
    return {"stopped": True, "pvcAndSecretsRetained": True}


def sql_probe_passed(label, allowed, status, out, err):
    if not allowed:
        return status.get("failed") == 1 and bool(re.search(r"ERROR\s+(1044|1142|1143|1227)\b", out + err))
    passed = status.get("succeeded") == 1
    if label == "account":
        roles = re.findall(r"`([^`]+)`@`%`", out)
        expected = {"maas_kernel_runtime", "maas_release_reader", "maas_agent_session_runtime", "maas_product_auth_runtime"}
        passed = passed and out.startswith("maas_runtime@%\t") and len(roles) == 4 and set(roles) == expected
    return passed


def runtime_permissions(r):
    """Real SQL probes use the exact runtime client file, never an app-root fallback."""
    cases = [
        ("account", "SELECT CURRENT_USER(),CURRENT_ROLE();", True),
        ("session_select", "SELECT session_id,owner_id,revision,document FROM agent_sessions_v1 LIMIT 0;", True),
        ("session_cas", "UPDATE agent_sessions_v1 SET revision=revision,document=document WHERE 1=0;", True),
        ("no_ddl", "CREATE TABLE maas8_forbidden_probe(id INT);", False),
        ("no_credentials", "SELECT User FROM mysql.user LIMIT 0;", False),
        ("no_payload", "SELECT spec_bytes FROM retained_release_snapshots LIMIT 0;", False),
        ("no_operations", "SELECT * FROM release_management_operations LIMIT 0;", False),
    ]
    results = []
    for index, (label, sql, allowed) in enumerate(cases):
        name = "maas8-sql-" + str(index)
        job = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name, "namespace": r.state["namespace"]},
               "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 90, "template": {"metadata": {"labels": {"app": "maas-migrate"}},
               "spec": {"restartPolicy": "Never", "automountServiceAccountToken": False,
                        "securityContext": {"runAsUser": 65532, "runAsGroup": 65532, "runAsNonRoot": True},
                        "containers": [{"name": "sql", "image": "maas-migrate:" + r.state["tag"], "imagePullPolicy": "Never",
                            "command": ["mysql", "--defaults-extra-file=/run/secrets/runtime-client.cnf", "--batch", "--skip-column-names", "maas", "-e", sql],
                            "resources": {"requests": {"cpu": "10m", "memory": "32Mi"}, "limits": {"cpu": "200m", "memory": "128Mi"}},
                            "volumeMounts": [{"name": "client", "mountPath": "/run/secrets", "readOnly": True}]}],
                        "volumes": [{"name": "client", "secret": {"secretName": "maas-migration", "defaultMode": 292}}]}}}}
        # Refuse an old run's Job: no automatic replay of a potentially executed probe.
        _, existing, _ = r.kub(["get", "job", name, "--ignore-not-found", "-o", "name"], "sql-existing-" + label)
        if existing.strip():
            raise RuntimeError("existing_sql_probe_requires_manual_inspection:" + name)
        r.kub(["create", "-f", "-"], "sql-create-" + label, data=yaml.safe_dump(job))
        deadline = time.monotonic() + 100
        status = {}
        while time.monotonic() < deadline:
            _, raw, _ = r.kub(["get", "job", name, "-o", "json"], "sql-status-" + label)
            status = json.loads(raw).get("status", {})
            if status.get("succeeded") or status.get("failed"):
                break
            time.sleep(1)
        _, out, err = r.kub(["logs", "job/" + name], "sql-log-" + label, check=False)
        passed = sql_probe_passed(label, allowed, status, out, err)
        results.append({"check": label, "allowed": allowed, "passed": bool(passed)})
        (r.logs / "runtime-permissions.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        if not passed:
            raise RuntimeError("runtime_permission_probe_failed:" + label)
        r.kub(["delete", "job", name, "--wait=true", "--timeout=30s"], "sql-cleanup-" + label, timeout=45)
    return results


def verify(r):
    state = r.owned(); r.assert_namespace(); source = Path(state["source"])
    config = json.loads((r.root / "config/product.json").read_text(encoding="utf-8"))
    if profile_check(config) != "offline-controlled" or config["origin"] != "http://localhost:" + str(state["port"]):
        raise ValueError("verification_requires_explicit_owned_loopback_offline_profile")
    r.schema(source)
    _, raw, _ = r.kub(["get", "deployment", "maas", "-o", "json"], "runtime-pod-spec")
    pod = json.loads(raw)["spec"]["template"]["spec"]
    secrets = {v["secret"]["secretName"] for v in pod.get("volumes", []) if "secret" in v}
    if secrets != {"maas-runtime"} or pod["securityContext"]["runAsUser"] != 65532 or not pod["containers"][0]["securityContext"]["readOnlyRootFilesystem"]:
        raise RuntimeError("runtime_migration_secret_separation_invalid")
    runtime_permissions(r)
    # A listening foreign process must never be mistaken for our forwarded service.
    with socket.socket() as port:
        port.bind(("127.0.0.1", state["port"]))
    log = (r.logs / "port-forward.log").open("wb")
    try:
        forward = subprocess.Popen(r.k + ["-n", state["namespace"], "port-forward", "--address=127.0.0.1", "service/web", str(state["port"]) + ":8080"], stdout=log, stderr=subprocess.STDOUT)
    except OSError:
        log.close()
        raise
    origin = config["origin"]; csrf = ""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kw):
            return None
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect())
    def request(method, path, data=None):
        headers = {"Origin": origin, "Content-Type": "application/json"}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        req = urllib.request.Request(origin + path, data=json.dumps(data).encode() if data is not None else None, headers=headers, method=method)
        with client.open(req, timeout=10) as response:
            data = response.read()
            return json.loads(data) if data else None
    def healthy():
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            if forward.poll() is not None:
                raise RuntimeError("owned_port_forward_exited")
            try:
                ready = request("GET", "/readyz")
                if ready.get("profile") == "offline-controlled" and ready.get("persistence") == "mysql":
                    return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(.5)
        raise RuntimeError("owned_site_not_ready")
    def replay(record, output):
        r.run([sys.executable, str(source / "deploy/release/smoke.py"), "--base", origin,
               "--password-file", str(r.root / ".secrets/migration/maas_bootstrap_password"),
               "--offline-demo", "--phase", "verify", "--record", str(record), "--output", str(r.logs / output)], "replay-" + output, 120)
    password = r.root / ".secrets/migration/maas_bootstrap_password"
    history, cancelled = r.logs / "chat-agent-record.json", r.logs / "cancel-record.json"
    try:
        healthy()
        if not history.exists():
            r.run([sys.executable, str(source / "deploy/release/smoke.py"), "--base", origin, "--password-file", str(password), "--offline-demo", "--phase", "create", "--record", str(history), "--output", str(r.logs / "chat-agent-create.json")], "chat-agent-create", 180)
        else:
            replay(history, "resume-history.json")
        if not cancelled.exists():
            r.run([sys.executable, str(source / "scripts/smoke-product-cancel.py"), "--url", origin, "--password-file", str(password), "--record", str(cancelled)], "cancel-admitted-child", 100)
        else:
            replay(cancelled, "resume-cancel.json")
        login = request("POST", "/api/admin/v1/session", {"username": "admin", "password": password.read_text().strip()})
        csrf = login["csrf_token"]
        before = r.snapshot("before-restarts")
        for action in ("application", "mysql-pvc"):
            if action == "application":
                r.kub(["rollout", "restart", "deployment/maas"], "restart-app")
            else:
                r.kub(["delete", "pod", "mysql-0", "--wait=true", "--timeout=90s"], "restart-mysql-pod", timeout=110)
                r.kub(["rollout", "status", "statefulset/mysql", "--timeout=300s"], "mysql-pvc-ready", timeout=330)
            r.kub(["rollout", "status", "deployment/maas", "--timeout=180s"], action + "-app-ready", timeout=200)
            healthy()
            current = request("GET", "/api/admin/v1/session")
            if any(current[k] != login[k] for k in ("admin_id", "csrf_token")):
                raise RuntimeError("same_cookie_principal_not_restored")
            replay(history, action + "-history.json")
            replay(cancelled, action + "-cancel.json")
            after = r.snapshot(action + "-after")
            if before != after:
                raise RuntimeError("restart_changed_original_ledger_document_or_pvc")
            r.schema(source)
        return {"passed": True, "scope": "native-k8s-explicit-offline-no-real-provider", "sameIdentity": True,
                "pvcAndOriginalDocumentUnchanged": True, "snapshot": before, "newGenerationOnReplay": 0}
    finally:
        if csrf:
            try:
                request("DELETE", "/api/admin/v1/session")
            except (OSError, urllib.error.URLError):
                pass
        forward.terminate()
        try:
            forward.wait(timeout=10)
        except subprocess.TimeoutExpired:
            forward.kill(); forward.wait(timeout=10)
        log.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["probe", "prepare", "create", "install", "upgrade", "verify", "stop"])
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[3])
    p.add_argument("--docker", default=shutil.which("docker") or "docker")
    p.add_argument("--kubectl", default=shutil.which("kubectl") or "kubectl")
    p.add_argument("--kind", default=shutil.which("kind") or "kind")
    p.add_argument("--minimum-free-mib", type=int, default=4096)
    p.add_argument("--cluster", default="maas8-native-1126")
    p.add_argument("--namespace", default="maas8-native-1126")
    p.add_argument("--port", type=int, default=18686)
    p.add_argument("--profile", choices=["external-api", "offline-controlled"], default="external-api")
    a = p.parse_args(); r = Runner(a.root, a.docker, a.kubectl, a.kind)
    try:
        if a.action == "probe":
            result = r.probe(a.minimum_free_mib)
            code = 0 if result["canCreateLocalCluster"] else 2
        elif a.action == "prepare": result, code = prepare(r, a), 0
        elif a.action == "create": result, code = create(r, a), 0
        elif a.action == "install": result, code = install(r), 0
        elif a.action == "upgrade": result, code = upgrade(r, a), 0
        elif a.action == "verify": result, code = verify(r), 0
        else: result, code = stop(r), 0
    except (OSError, ValueError, RuntimeError, KeyError) as e:
        # Do not stringify arbitrary parser/transport errors that may contain DSNs.
        result, code = {"passed": False, "action": a.action, "reason": str(e) if isinstance(e, RuntimeError) else type(e).__name__, "applicationAcceptance": False}, 1
    (r.logs / (a.action + "-result.json")).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result)); return code


if __name__ == "__main__":
    raise SystemExit(main())
