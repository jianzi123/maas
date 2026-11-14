"""Regression tests for same-snapshot assembly, not application/production acceptance."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unified_sources import assemble_repository


class UnifiedSourceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.write(".gitattributes", "* text eol=lf\n")
        self.write(".gitignore", ".cache/\n")
        self.write("main.go", "package main\n")
        self.write("console/src/App.vue", "old frontend\n")
        self.write("deploy/server.py", "server = 'current'\n")
        self.commit("old snapshot")
        self.write("console/src/App.vue", "current frontend with recovery fixes\n")
        self.code = self.commit("current unified code")
        files = {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.root.rglob("*") if p.is_file() and ".git" not in p.relative_to(self.root).parts}
        lock = {name: {"sourceCommit": self.code, "files": {p: digest for p, digest in files.items()
                 if (p.startswith("console/") if name == "console" else not p.startswith(("console/", "deploy/")))}}
                for name in ("backend", "console")}
        self.write("deploy/build-sources.lock.json", json.dumps(lock))
        self.delivery = self.commit("lock metadata only")
        self.output = Path(self.temporary.name) / "assembled"

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8", newline="\n")

    def commit(self, title):
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", title)
        return self.git("rev-parse", "HEAD")

    def test_all_components_are_the_current_snapshot(self):
        result = assemble_repository(self.root, self.output)
        self.assertEqual((self.output / "console/src/App.vue").read_text(), "current frontend with recovery fixes\n")
        manifest = json.loads((self.output / "workbench-sources.json").read_text())
        self.assertEqual(set(manifest["components"].values()), {self.delivery})
        self.assertEqual(result["backendCommit"], result["consoleCommit"])
        self.assertEqual(manifest["sourceCodeCommit"], self.code)
        self.assertFalse((self.output / ".git").exists())

    def test_untracked_private_file_and_cache_are_not_exported(self):
        self.write("private.secret", "must remain outside the build\n")
        self.write(".cache/session.json", "not source\n")
        assemble_repository(self.root, self.output)
        self.assertFalse((self.output / "private.secret").exists())
        self.assertFalse((self.output / ".cache").exists())

    def test_dirty_tracked_code_rejected_without_output(self):
        self.write("console/src/App.vue", "uncommitted frontend\n")
        with self.assertRaises(ValueError):
            assemble_repository(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_preserved(self):
        self.output.mkdir()
        (self.output / "marker").write_text("keep")
        with self.assertRaises(FileExistsError):
            assemble_repository(self.root, self.output)
        self.assertEqual((self.output / "marker").read_text(), "keep")

    def test_tampered_source_inventory_rejected(self):
        path = self.root / "deploy/build-sources.lock.json"
        lock = json.loads(path.read_text())
        lock["console"]["files"]["console/src/App.vue"] = "0" * 64
        path.write_text(json.dumps(lock))
        self.commit("bad metadata")
        with self.assertRaises(ValueError):
            assemble_repository(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_changed_deployment_code_requires_a_new_code_lock(self):
        self.write("deploy/server.py", "server = 'changed after lock'\n")
        self.commit("new deployment runtime code")
        with self.assertRaises(ValueError):
            assemble_repository(self.root, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
