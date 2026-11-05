import copy
import json
import unittest
from preflight import blockers
from verify import ROOT, load_values

class InputGateTest(unittest.TestCase):
    def setUp(self):
        self.values = load_values(ROOT / "tests/fixtures/internal.yaml")
        self.lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))

    def complete(self, sources):
        v, lock = copy.deepcopy(self.values), copy.deepcopy(self.lock)
        v["api"]["group"] = "serving.internal.test"
        v["api"]["reviewPlaceholderAcknowledged"] = False
        lock["deploymentApproved"] = True
        lock["target"].update(cluster="synthetic", kubernetesVersion="synthetic", apiGroup=v["api"]["group"], authorizationRef="synthetic-only", namespace="test", modelSources=sources)
        for component in ("operator", "core", "console"):
            v[component]["image"] = {"repository":"registry.internal.test/maas/"+component,"digest":"sha256:"+"1234567890abcdef"*4}
        for d in lock["dependencies"]:
            if d["id"] in ("lws-chart-controller-crd", "sglang", "gpu-driver-device-plugin", "weights-tokenizer"):
                continue
            d.update(status="approved", version="synthetic", evidenceRef="synthetic", digest="sha256:"+"1234567890abcdef"*4, mirror="registry.internal.test/maas/"+d["id"])
        for key in lock["runtimeGates"]:
            if key != "LWS-SGLang-GPU":
                lock["runtimeGates"][key]="verified"
        return v, lock

    def test_pending_inputs_reject(self):
        self.assertIn("deploymentApproved", blockers(self.values, self.lock))

    def test_external_api_does_not_require_gpu(self):
        v, lock = self.complete(["ExternalAPI"])
        self.assertEqual([], blockers(v, lock))

    def test_self_hosted_still_requires_gpu(self):
        v, lock = self.complete(["SelfHosted"])
        self.assertIn("runtimeGate.LWS-SGLang-GPU", blockers(v, lock))
        self.assertIn("dependency.sglang", blockers(v, lock))

    def test_missing_inventory_cannot_pass(self):
        v, lock = self.complete(["ExternalAPI"])
        lock["dependencies"]=[]
        lock["runtimeGates"]={}
        issues=blockers(v, lock)
        self.assertIn("dependencies.inventory", issues)
        self.assertIn("runtimeGates.inventory", issues)

    def test_image_lock_mismatch_rejects(self):
        v, lock = self.complete(["ExternalAPI"])
        v["core"]["image"]["digest"]="sha256:"+"abcdef1234567890"*4
        self.assertIn("core.imageLockMismatch", blockers(v, lock))

if __name__ == "__main__":
    unittest.main()