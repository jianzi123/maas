import copy
import unittest
from single_model import ARTIFACTS, combination_blockers
class CombinationTest(unittest.TestCase):
    def plan(self):
        return {"schemaVersion":"single-model-run-1.0","model":{"alias":"synthetic","sourceType":"ExternalAPI","profileRef":"synthetic","approvalRef":"synthetic"},"artifacts":[{"id":i,"version":"synthetic","digest":"sha256:"+"1"*64,"configDigest":"sha256:"+"2"*64,"evidenceRef":"synthetic"} for i in ARTIFACTS],"runtime":{k:"synthetic" for k in ("entrypoint","environmentRef","stopInstructionsRef","logLocationRef")},"observedCallable":True,"requestEvidence":{k:"synthetic" for k in ("requestId","publicationId","activationEpoch","logEvidenceRef","usageEvidenceRef")}}
    def test_complete_synthetic_inputs(self):self.assertEqual([],combination_blockers(self.plan()))
    def test_missing_profile(self):
        p=self.plan();p["model"]["profileRef"]=None
        self.assertIn("model.profileRef",combination_blockers(p))
    def test_mutable_artifact(self):
        p=self.plan();p["artifacts"][0]["digest"]="latest"
        self.assertTrue(any(x.startswith("artifact.") for x in combination_blockers(p)))
    def test_duplicate_artifacts(self):
        p=self.plan();p["artifacts"].append(copy.deepcopy(p["artifacts"][0]))
        self.assertIn("artifacts.inventory",combination_blockers(p))
    def test_private_requires_engine_and_weights(self):
        p=self.plan();p["model"]["sourceType"]="SelfHosted"
        self.assertIn("artifacts.inventory",combination_blockers(p))
    def test_no_callable_from_metadata(self):
        p=self.plan();p["observedCallable"]=False
        self.assertIn("runtime.callableUnobserved",combination_blockers(p))
    def test_request_correlation_required(self):
        p=self.plan();p["requestEvidence"]["requestId"]=None
        self.assertIn("requestEvidence.requestId",combination_blockers(p))