import copy
import unittest
from identities import EXPECTED, identity_blockers

class IdentityTest(unittest.TestCase):
    def plan(self):
        return {"productionWiringVerified": True, "connections": {
            name: {"roles":sorted(roles), "bindingStatus":"verified", "principalRef":"synthetic-"+name,
                   "grantEvidenceRef":"synthetic", "secretRef":{"namespace":"test", "name":"synthetic", "key":name}}
            for name,roles in EXPECTED.items()}}

    def test_separate_references_pass(self):
        self.assertEqual([], identity_blockers(self.plan(), "test"))

    def test_shared_principal_denied(self):
        p=self.plan()
        p["connections"]["publisher"]["principalRef"]=p["connections"]["core"]["principalRef"]
        self.assertIn("identities.sharedPrincipal", identity_blockers(p,"test"))

    def test_shared_secret_key_denied(self):
        p=self.plan()
        p["connections"]["publisher"]["secretRef"]=copy.deepcopy(p["connections"]["core"]["secretRef"])
        self.assertIn("identities.sharedSecretKey", identity_blockers(p,"test"))

    def test_cross_namespace_denied(self):
        p=self.plan()
        p["connections"]["historyReader"]["secretRef"]["namespace"]="other"
        self.assertIn("identities.historyReader.secretRef",identity_blockers(p,"test"))

    def test_reader_writer_role_denied(self):
        p=self.plan()
        p["connections"]["historyReader"]["roles"].append("maas_release_publisher")
        self.assertIn("identities.historyReader.roles",identity_blockers(p,"test"))

    def test_legacy_payload_role_denied(self):
        p=self.plan()
        p["connections"]["payloadReader"]["roles"]=["maas_release_history_payload_reader"]
        self.assertIn("identities.payloadReader.roles",identity_blockers(p,"test"))

    def test_missing_wiring_or_evidence_denied(self):
        p=self.plan()
        p["productionWiringVerified"]=False
        p["connections"]["payloadReader"]["grantEvidenceRef"]=None
        issues=identity_blockers(p,"test")
        self.assertIn("identities.productionWiring",issues)
        self.assertIn("identities.payloadReader.evidence",issues)

    def test_secret_body_denied(self):
        p=self.plan()
        p["connections"]["core"]["dsn"]="SYNTHETIC"
        self.assertIn("identities.core.unknownFields",identity_blockers(p,"test"))
