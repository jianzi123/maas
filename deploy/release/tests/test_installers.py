import hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
RELEASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RELEASE))
from verify_bundle import verify
class InstallerTest(unittest.TestCase):
    def test_bundle_bytes_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"VERSION.json").write_text(json.dumps({"repositoryCommit":"a"*40,"codeCommit":"b"*40}))
            for name in ("build-sources.lock.json","dependencies.lock.json","identities.json","charts/maas-platform/runtime-interface.json"):
                p=root/"source/deploy"/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({"backend":{"sourceCommit":"b"*40},"console":{"sourceCommit":"b"*40}}) if name=="build-sources.lock.json" else "{}")
            file=root/"README.md";file.write_text("source-bound installer")
            (root/"MANIFEST.sha256.json").write_text(json.dumps({"README.md":hashlib.sha256(file.read_bytes()).hexdigest()}))
            self.assertTrue(verify(root)["passed"])
            file.write_text("tampered")
            self.assertFalse(verify(root)["passed"])
            self.assertTrue(verify(root,source_only=True)["passed"])
    def test_manifest_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"VERSION.json").write_text(json.dumps({"repositoryCommit":"a","codeCommit":"b"}))
            (root/"MANIFEST.sha256.json").write_text(json.dumps({"../outside":"bad"}))
            self.assertFalse(verify(root)["passed"])
    def test_actual_config_generator_separates_secrets_and_refuses_overwrite(self):
        source=RELEASE.parents[1]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            cmd=[sys.executable,str(RELEASE/"configure.py"),"--format","compose","--directory",str(root),"--source",str(source),"--port","18081"]
            r=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            secret=root/".secrets/migration/maas_bootstrap_password"
            password=secret.read_text()
            self.assertNotIn(password,r.stdout+r.stderr)
            self.assertFalse((root/".secrets/runtime/maas_migration_dsn").exists())
            public=json.loads((root/"config/console-config.json").read_text())
            private=json.loads((root/"config/product.json").read_text())
            self.assertEqual(set(public),{"schema_version","chat"})
            self.assertEqual(public["chat"]["limits"],private["agent"]["limits"])
            self.assertTrue(public["chat"]["enabled"])
            self.assertEqual(private["mysql"]["runtime_dsn_file"],"/run/secrets/maas_runtime_dsn")
            second=subprocess.run(cmd,capture_output=True,text=True)
            self.assertNotEqual(second.returncode,0)
            self.assertEqual(secret.read_text(),password)
    def test_invalid_origin_never_creates_secrets(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            r=subprocess.run([sys.executable,str(RELEASE/"configure.py"),"--format","compose","--directory",str(root),"--source",str(RELEASE.parents[1]),"--origin","https://user:pass@example.invalid/path"],capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0)
            self.assertFalse((root/".secrets").exists())
    def test_offline_is_explicit_and_projects_real_policy(self):
        for profile in ("external-api","offline-controlled"):
            with self.subTest(profile=profile),tempfile.TemporaryDirectory() as d:
                root=Path(d)
                r=subprocess.run([sys.executable,str(RELEASE/"configure.py"),"--format","compose","--directory",str(root),"--source",str(RELEASE.parents[1]),"--profile",profile],capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stderr)
                private=json.loads((root/"config/product.json").read_text())
                public=json.loads((root/"config/console-config.json").read_text())
                self.assertEqual(private.get("offline_controlled",{}).get("enabled",False),profile=="offline-controlled")
                self.assertEqual(public["chat"]["limits"],private["agent"]["limits"])
                self.assertEqual(len(public["chat"]["tools"]),2 if profile=="offline-controlled" else 0)
                self.assertFalse(private.get("management",{}).get("enabled",False))
    def test_incomplete_smoke_record_cannot_pass_without_verifying_data(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);record=root/"partial.json";output=root/"result.json"
            for partial in ({"sessionId":"owned","runs":[],"pendingCommand":{"run_id":"unknown"}},
                            {"sessionId":"owned","runs":[{"children":[],"usageHashes":[]}]}):
                record.write_text(json.dumps(partial))
                command=[sys.executable,str(RELEASE/"smoke.py"),"--base","http://127.0.0.1:1","--password-file",str(root/"must-not-be-read"),"--offline-demo","--phase","verify","--record",str(record),"--output",str(output)]
                result=subprocess.run(command,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                report=json.loads(output.read_text())
                self.assertFalse(report["passed"])
                self.assertEqual(report["checks"],[])
                self.assertIn("Incomplete smoke record",report["reason"])
if __name__=="__main__":unittest.main()
