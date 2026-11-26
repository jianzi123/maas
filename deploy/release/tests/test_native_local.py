"""Fixture tests of orchestration gates; these are NOT Kubernetes installation tests."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "kubernetes/local_verify.py"
spec = importlib.util.spec_from_file_location("native_local", MODULE)
native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)


class NativeGates(unittest.TestCase):
    def test_render_is_namespaced_and_never_adopts_prod(self):
        original = [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "maas"}},
                    {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "maas", "namespace": "maas"}, "spec": {"image": "maas:__IMAGE_TAG__"}}]
        result = native.scoped_documents(original, "maas8-fixture", "abc")
        self.assertEqual(result[0]["metadata"]["labels"][native.OWNER], native.ISSUE)
        self.assertEqual(result[1]["metadata"]["namespace"], "maas8-fixture")
        self.assertEqual(original[1]["metadata"]["namespace"], "maas")
        with self.assertRaises(ValueError): native.scoped_documents(original, "production", "abc")
        with self.assertRaises(ValueError): native.scoped_documents([{"kind": "ClusterRole", "metadata": {"name": "foreign"}}], "maas8-fixture", "abc")

    def test_low_memory_or_missing_engine_never_creates_cluster(self):
        for memory, engine in ((512, 0), (8192, 1)):
            with self.subTest(memory=memory, engine=engine), tempfile.TemporaryDirectory() as d:
                r = native.Runner(d)
                def run(args, name, *unused, **kw):
                    code = engine if name == "engine" else 0
                    r.steps.append({"step": name, "exitCode": code})
                    return code, "unix:///var/run/docker.sock" if name == "docker-endpoint" else "fixture-version", ""
                with patch.dict(native.os.environ, {}, clear=True), patch.object(r, "run", side_effect=run) as calls, patch.object(native, "free_memory_mib", return_value=memory):
                    with self.assertRaisesRegex(RuntimeError, "local_environment_gate_failed"):
                        native.create(r, type("Args", (), {"minimum_free_mib": 4096})())
                self.assertEqual(calls.call_count, 4)
                self.assertFalse(json.loads((Path(d) / "evidence/environment.json").read_text())["clusterInstalled"])

    def test_remote_docker_never_contacted(self):
        with tempfile.TemporaryDirectory() as d:
            r = native.Runner(d)
            def run(args, name, *unused, **kw):
                r.steps.append({"step": name, "exitCode": 0}); return 0, "fixture-version", ""
            with patch.dict(native.os.environ, {"DOCKER_HOST": "ssh://foreign.example", "DOCKER_CONTEXT": ""}), patch.object(r, "run", side_effect=run) as calls, patch.object(native, "free_memory_mib", return_value=8192):
                result = r.probe(4096)
            self.assertFalse(result["canCreateLocalCluster"])
            self.assertFalse(any(c.args[1] == "engine" for c in calls.call_args_list))

    def test_owned_record_rejects_foreign_kubeconfig_before_commands(self):
        with tempfile.TemporaryDirectory() as d:
            r = native.Runner(d)
            (Path(d) / "owner.json").write_text(json.dumps({"issue": native.ISSUE, "cluster": "maas8-fixture", "namespace": "maas8-fixture", "createdHere": True, "kubeconfig": "/foreign/config"}))
            with patch.object(r, "run") as command, self.assertRaises(ValueError): r.owned()
            command.assert_not_called()

    def test_required_002_applying_missing_and_checksum_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); migrations = root / "internal/app/migrations"; migrations.mkdir(parents=True)
            for index in (1, 2): (migrations / (str(index).zfill(3) + "_fixture.sql")).write_text("CREATE TABLE fixture" + str(index) + "(id INT);")
            hashes = {i: hashlib.sha256((migrations / (str(i).zfill(3) + "_fixture.sql")).read_bytes()).hexdigest() for i in (1, 2)}
            good = "\n".join(str(i) + "\tApplied\t" + hashes[i] for i in (1, 2))
            self.assertEqual(native.migration_check(root, good), [1, 2])
            for bad in (good.replace("2\tApplied", "2\tApplying"), good.splitlines()[0], good.replace(hashes[2], "0" * 64), good + "\n" + good.splitlines()[0]):
                with self.subTest(marker=bad), self.assertRaises(ValueError): native.migration_check(root, bad)

    def test_negative_sql_needs_permission_error_not_transport_failure(self):
        self.assertTrue(native.sql_probe_passed("no_ddl", False, {"failed": 1}, "", "ERROR 1142 (42000): denied"))
        self.assertFalse(native.sql_probe_passed("no_ddl", False, {"failed": 1}, "", "ERROR 2002: cannot connect"))
        roles = "maas_runtime@%\t" + ",".join("`" + r + "`@`%`" for r in ("maas_kernel_runtime", "maas_release_reader", "maas_agent_session_runtime", "maas_product_auth_runtime"))
        self.assertTrue(native.sql_probe_passed("account", True, {"succeeded": 1}, roles, ""))
        self.assertFalse(native.sql_probe_passed("account", True, {"succeeded": 1}, roles + ",`maas_release_history_reader`@`%`", ""))

    def test_offline_cannot_mix_real_models_or_management(self):
        self.assertEqual(native.profile_check({"models": []}), "external-api")
        self.assertEqual(native.profile_check({"offline_controlled": {"enabled": True}, "models": []}), "offline-controlled")
        for other in ({"models": [{"alias": "supplier"}]}, {"management": {"enabled": True}}):
            with self.assertRaises(ValueError): native.profile_check({"offline_controlled": {"enabled": True}, **other})

    def test_command_timeout_has_original_partial_output(self):
        with tempfile.TemporaryDirectory() as d:
            r = native.Runner(d)
            with patch.object(native.subprocess, "run", side_effect=subprocess.TimeoutExpired(["fixture"], 1, output=b"partial", stderr=b"bounded")):
                code, out, err = r.run(["fixture"], "deadline", timeout=1, check=False)
            self.assertEqual((code, out), (124, "partial"))
            self.assertIn("command_deadline_exceeded", err)
            self.assertEqual(r.steps[0]["exitCode"], 124)

    def test_install_stops_scheduler_and_blocks_app_on_migration_failure(self):
        for failed in (True, False):
            with self.subTest(migration_failed=failed), tempfile.TemporaryDirectory() as d:
                r = native.Runner(d); events = []
                state = {"source": d, "tag": "fixture", "revision": "a" * 40, "cluster": "maas8-fixture", "namespace": "maas8-fixture"}
                def kub(args, name, **kw):
                    events.append(name)
                    if name == "migration-complete" and failed: raise RuntimeError("migration-complete: exit 1")
                    return 0, "deployment.apps/maas" if name == "existing-app" else "", ""
                with patch.object(r, "owned", return_value=state), patch.object(r, "run", return_value=(0, state["revision"], "")), patch.object(r, "kub", side_effect=kub), patch.object(r, "schema", side_effect=lambda *a: events.append("schema-check")):
                    if failed:
                        with self.assertRaises(RuntimeError): native.install(r)
                        self.assertNotIn("apply-app", events)
                        self.assertIn("migration-log", events)
                    else:
                        self.assertTrue(native.install(r)["nativeInstalled"])
                        self.assertLess(events.index("old-scheduler-gone"), events.index("apply-migration"))
                        self.assertLess(events.index("schema-check"), events.index("apply-app"))

    def test_source_labels_block_before_any_resource_write(self):
        with tempfile.TemporaryDirectory() as d:
            r = native.Runner(d)
            state = {"source": d, "tag": "fixture", "revision": "a" * 40, "cluster": "maas8-fixture", "namespace": "maas8-fixture"}
            with patch.object(r, "owned", return_value=state), patch.object(r, "run", return_value=(0, "wrong-sha", "")), patch.object(r, "kub") as kub:
                with self.assertRaises(ValueError): native.install(r)
            kub.assert_not_called()


if __name__ == "__main__": unittest.main()
