import hashlib,json,os,subprocess,sys,tempfile,unittest,shutil
from pathlib import Path
RELEASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RELEASE))
from verify_bundle import verify
from fetch_source import METADATA, fetch

def valid_bundle(root):
    files={'cmd/maas-service/main.go':'package main','go.mod':'module fixture','go.sum':'fixture',
           'console/package.json':'{}','console/src/main.ts':'fixture',
           'deploy/release/compose/README.md':'source-bound installer',
           'deploy/release/compose/compose.yaml':'services: {}','deploy/release/VALIDATION.md':'fixture'}
    for name,text in files.items():
        p=root/'source'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    code='b'*40
    lock={}
    for component,prefix in (('backend',None),('console','console/'),('deployment','deploy/')):
        names=[n for n in files if n.startswith(prefix)] if prefix else [n for n in files if not n.startswith(('console/','deploy/'))]
        lock[component]={'sourceCommit':code,'files':{n:hashlib.sha256((root/'source'/n).read_bytes()).hexdigest() for n in names}}
    for name in METADATA:
        p=root/'source'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(lock) if name==METADATA[0] else '{}')
    sources={p.relative_to(root/'source').as_posix():{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in (root/'source').rglob('*') if p.is_file()}
    raw=json.dumps(sources).encode();(root/'SOURCE.sha256.json').write_bytes(raw)
    version={'repositoryCommit':'a'*40,'codeCommit':code,'sourceMode':'full','installer':'compose',
             'sourceLockSha256':{n:hashlib.sha256((root/'source'/n).read_bytes()).hexdigest() for n in METADATA},
             'sourceManifestSha256':hashlib.sha256(raw).hexdigest(),'sourceFileCount':len(sources)}
    (root/'VERSION.json').write_text(json.dumps(version));(root/'README.md').write_text('source-bound installer')
    (root/'VALIDATION.md').write_text('fixture');(root/'compose.yaml').write_text('services: {}')
    manifest={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    (root/'MANIFEST.sha256.json').write_text(json.dumps(manifest))

class InstallerTest(unittest.TestCase):
    def test_bundle_bytes_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            valid_bundle(root);file=root/'README.md'
            self.assertTrue(verify(root)["passed"])
            file.write_text("tampered")
            self.assertFalse(verify(root)["passed"])
            self.assertTrue(verify(root,source_only=True)["passed"])
    def test_manifest_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);valid_bundle(root)
            p=root/'MANIFEST.sha256.json';m=json.loads(p.read_text());m['../outside']='bad';p.write_text(json.dumps(m))
            self.assertFalse(verify(root)["passed"])
    def test_empty_and_nonempty_omitted_source_fail_in_both_modes(self):
        for empty in (True,False):
            with self.subTest(empty=empty),tempfile.TemporaryDirectory() as d:
                root=Path(d);valid_bundle(root);p=root/'MANIFEST.sha256.json'
                m={} if empty else json.loads(p.read_text())
                m.pop('source/cmd/maas-service/main.go',None);p.write_text(json.dumps(m))
                (root/'source/cmd/maas-service/main.go').write_text('corrupted but omitted')
                self.assertFalse(verify(root)['passed'])
                self.assertFalse(verify(root,source_only=True)['passed'])
    def test_fetch_omission_rejected_without_publishing_partial_source(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);valid_bundle(root)
            for name in METADATA:
                to=root/'metadata'/name;to.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/'source'/name,to)
            p=root/'SOURCE.sha256.json';m=json.loads(p.read_text());m.pop('cmd/maas-service/main.go')
            raw=json.dumps(m).encode();p.write_bytes(raw)
            p=root/'VERSION.json';v=json.loads(p.read_text());v.update(sourceManifestSha256=hashlib.sha256(raw).hexdigest(),sourceFileCount=len(m));p.write_text(json.dumps(v))
            source=(root/'source').resolve();self.assertEqual(source.parent,root.resolve());shutil.rmtree(source)
            with patch('fetch_source.urllib.request.urlopen',side_effect=AssertionError('network must not start')):
                with self.assertRaises(ValueError):fetch(root)
            self.assertFalse(source.exists())
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
