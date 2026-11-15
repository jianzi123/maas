import hashlib
from pathlib import Path
import tempfile
import unittest
from source_context import compare, assemble


class SourceContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backend = self.root / 'backend'
        self.frontend = self.root / 'frontend'
        self.write(self.backend, 'internal/kernel/relay_forward.go', b'reviewed relay')
        self.write(self.backend, 'console/src/api/client.ts', b'old client')
        self.write(self.backend, 'console/.env.workbench', b'old flag')
        self.write(self.frontend, 'console/src/api/client.ts', b'reviewed client')
        self.lock = {'backend': {'sourceCommit': 'backend', 'files': {'internal/kernel/relay_forward.go': self.digest(b'reviewed relay')}},
                     'console': {'sourceCommit': 'frontend', 'files': {'console/src/api/client.ts': self.digest(b'reviewed client')}},
                     'qa': {'targetCommit': 'core', 'scope': 'synthetic-test'}}

    def write(self, root, path, data):
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def digest(self, data):
        return hashlib.sha256(data).hexdigest()

    def test_assembly_replaces_entire_console_tree(self):
        out = self.root / 'out'
        report = assemble(self.backend, self.frontend, out, self.lock)
        self.assertTrue(all(r['passed'] for r in report['assembled']))
        self.assertEqual((out/'console/src/api/client.ts').read_bytes(), b'reviewed client')
        self.assertFalse((out/'console/.env.workbench').exists())

    def test_backend_console_cannot_claim_frontend_candidate(self):
        r = compare(self.backend, self.lock['console']['files'], 'console')
        self.assertFalse(r['passed'])
        self.assertIn('console/src/api/client.ts', r['changed'])

    def test_unlisted_go_input_rejected(self):
        self.write(self.backend, 'internal/kernel/extra.go', b'unreviewed')
        r = compare(self.backend, self.lock['backend']['files'], 'backend')
        self.assertIn('internal/kernel/extra.go', r['unexpected'])
        self.assertFalse(r['passed'])

    def test_relay_bytes_changed_rejected(self):
        self.write(self.backend, 'internal/kernel/relay_forward.go', b'old relay')
        self.assertFalse(compare(self.backend, self.lock['backend']['files'], 'backend')['passed'])

    def test_existing_destination_preserved(self):
        out = self.root/'existing'
        out.mkdir()
        (out/'marker').write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            assemble(self.backend, self.frontend, out, self.lock)
        self.assertEqual((out/'marker').read_bytes(), b'keep')
