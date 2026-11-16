"""Real Git snapshots for INT-13-S1; no service or deployment acceptance."""
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import preflight
from single_model import inspect
from source_context import inventory
from unified_sources import snapshot
from verify import ROOT, load_values


class SnapshotGateTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.write(".gitattributes", "* text eol=lf\n")
        self.write(".gitignore", ".cache/\n")
        self.write("main.go", "package main\n")
        self.write("console/App.vue", "snapshot A\n")
        self.values = load_values(ROOT / "charts/maas-platform/values-internal.yaml")
        self.plan = json.loads((ROOT / "single-model/combination.json").read_text(encoding="utf-8"))
        self.template_interface = json.loads((ROOT / "charts/maas-platform/runtime-interface.json").read_text(encoding="utf-8"))
        self.template_lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
        self.qa = json.loads((ROOT / "build-sources.lock.json").read_text(encoding="utf-8"))["qa"]
        self.ref_a = self.lock_snapshot("A")
        # Model the caller's working-tree roots without changing project files.
        self.roots = ExitStack()
        self.addCleanup(self.roots.close)
        self.roots.enter_context(patch.object(preflight, "ROOT", self.repo / "deploy"))
        self.roots.enter_context(patch.object(preflight, "CHART", self.repo / "deploy/charts/maas-platform"))

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8", newline="\n")

    def write_json(self, name, value):
        self.write(name, json.dumps(value, indent=2) + "\n")

    def commit(self, title):
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", title)
        return self.git("rev-parse", "HEAD")

    def lock_snapshot(self, title, schema=None):
        self.write_json("deploy/charts/maas-platform/values.schema.json", schema or {"type": "object"})
        code = self.commit("code " + title)
        with snapshot(self.repo, code) as (_, source):
            files = {name: inventory(source, name) for name in ("backend", "console")}
        inv = {name: {"sourceCommit": code, "files": files[name]} for name in files}
        inv["qa"] = copy.deepcopy(self.qa)
        self.write_json("deploy/build-sources.lock.json", inv)
        interface = copy.deepcopy(self.template_interface)
        lock = copy.deepcopy(self.template_lock)
        for name in files:
            interface[name].update(sourceCommit=code, files=files[name])
        lock["databaseIdentities"]["sourceCommit"] = code
        lock["sourceBaseline"].update(backendInspected=code, consoleInspected=code)
        lock["sourceBaseline"]["sourceInventorySha256"] = hashlib.sha256((self.repo / "deploy/build-sources.lock.json").read_bytes()).hexdigest()
        self.write_json("deploy/charts/maas-platform/runtime-interface.json", interface)
        self.write_json("deploy/dependencies.lock.json", lock)
        self.write_json("deploy/identities.json", lock["databaseIdentities"])
        return self.commit("locks " + title)

    def check(self, ref):
        return inspect(self.repo, ref, self.values, self.plan)

    def test_cross_ref_inventory_preserves_real_blockers(self):
        expected = self.check(self.ref_a)
        self.write("console/App.vue", "snapshot B\n")
        ref_b = self.lock_snapshot("B")
        self.assertNotEqual(ref_b, self.ref_a)
        actual = self.check(self.ref_a)
        self.assertEqual(actual, expected)
        self.assertTrue(all(row["passed"] for row in actual["sourceChecks"]))
        self.assertNotIn("source.inventoryChecksum", actual["blockers"])
        self.assertNotIn("source.inventoryRevision", actual["blockers"])
        self.assertIn("deploymentApproved", actual["blockers"])
        self.assertIn("runtime.callableUnobserved", actual["blockers"])
        self.assertFalse(actual["ready"])

    def test_cross_ref_schema_comes_from_requested_snapshot(self):
        expected = self.check(self.ref_a)
        self.write("console/App.vue", "snapshot B\n")
        ref_b = self.lock_snapshot("B strict schema", {"not": {}})
        self.assertEqual(self.check(self.ref_a), expected)
        self.assertNotIn("values.schema", expected["blockers"])
        self.assertIn("values.schema", self.check(ref_b)["blockers"])

    def test_default_caller_still_uses_worktree_schema(self):
        self.write_json("deploy/charts/maas-platform/values.schema.json", {"not": {}})
        lock = json.loads((self.repo / "deploy/dependencies.lock.json").read_text())
        self.assertIn("values.schema", preflight.blockers(self.values, lock))

    def test_default_caller_still_detects_worktree_inventory_damage(self):
        lock = json.loads((self.repo / "deploy/dependencies.lock.json").read_text())
        self.write("deploy/build-sources.lock.json", "{}")
        issues = preflight.blockers(self.values, lock)
        self.assertIn("source.inventoryChecksum", issues)
        self.assertIn("source.inventoryMissingOrInvalid", issues)

    def test_snapshot_inventory_checksum_damage_rejected(self):
        path = "deploy/build-sources.lock.json"
        inv = json.loads((self.repo / path).read_text())
        inv["qa"]["diagnosticMarker"] = "tampered bytes"
        self.write_json(path, inv)
        damaged = self.commit("damaged inventory checksum")
        self.assertIn("source.inventoryChecksum", self.check(damaged)["blockers"])

    def test_snapshot_qa_revision_damage_rejected_with_matching_checksum(self):
        path = "deploy/build-sources.lock.json"
        inv = json.loads((self.repo / path).read_text())
        inv["qa"]["evidenceCommit"] = "0" * 40
        self.write_json(path, inv)
        lock = json.loads((self.repo / "deploy/dependencies.lock.json").read_text())
        lock["sourceBaseline"]["sourceInventorySha256"] = hashlib.sha256((self.repo / path).read_bytes()).hexdigest()
        self.write_json("deploy/dependencies.lock.json", lock)
        result = self.check(self.commit("damaged QA revision"))
        self.assertNotIn("source.inventoryChecksum", result["blockers"])
        self.assertIn("source.inventoryRevision", result["blockers"])

    def test_snapshot_source_changed_after_lock_rejected(self):
        self.write("console/App.vue", "unlocked source damage\n")
        damaged = self.commit("source changed after lock")
        with self.assertRaisesRegex(ValueError, "Code changed after"):
            self.check(damaged)

    def test_snapshot_inventory_source_hash_damage_rejected(self):
        path = "deploy/build-sources.lock.json"
        inv = json.loads((self.repo / path).read_text())
        inv["console"]["files"]["console/App.vue"] = "0" * 64
        self.write_json(path, inv)
        damaged = self.commit("wrong source hash")
        with self.assertRaisesRegex(ValueError, "source bytes"):
            self.check(damaged)


if __name__ == "__main__":
    unittest.main()
