import copy
import json
import unittest
from preflight import blockers
from verify import ROOT, load_values

class InputGateTest(unittest.TestCase):
    def setUp(self):
        self.values = load_values(ROOT / "tests/fixtures/internal.yaml")
        self.interface = json.loads((ROOT / "charts/maas-platform/runtime-interface.json").read_text(encoding="utf-8"))
        self.lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))

    def check(self, values, lock):
        return blockers(values, lock, self.interface)

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
        lock["target"].update(rpo="PT0S", rto="PT1H", retention="approved-synthetic-policy")
        self.interface["backend"]["apiGroup"]=v["api"]["group"]
        for d in lock["dependencies"]:
            if d["id"] in ("core", "operator"): d["compiledAPIGroup"]=v["api"]["group"]
        self.interface["backend"]["core"]["deploymentReady"]=True
        self.interface["backend"]["operator"]["deploymentReady"]=True
        self.interface["console"]["productionSessionReady"]=True
        lock["migrationState"]={domain:[{"version":m["version"],"sha256":m["sha256"],"state":"Applied"} for m in self.interface["migrations"] if m["domain"]==domain] for domain in ("kernel","release")}
        for c in lock["gatewayComponents"]:
            c.update(status="approved",sourceCommit="1"*40,digest="sha256:"+"1234567890abcdef"*4,mirror="synthetic",abi="synthetic",identityRef="synthetic",evidenceRef="synthetic")
        identities=lock["databaseIdentities"]
        identities["productionWiringVerified"]=True
        lock["sourceBaseline"]["candidateState"]="merged"  # synthetic gate input only
        self.interface["backend"]["candidateState"]="merged"  # synthetic gate input only
        self.interface["console"]["candidateState"]="merged"  # synthetic gate input only
        for name,c in identities["connections"].items():
            c.update(bindingStatus="verified", principalRef="synthetic-"+name, grantEvidenceRef="synthetic-"+name, secretRef={"namespace":"test","name":"synthetic-"+name.lower(),"key":"dsn"})
        for name in v["core"]["databaseSecrets"]:
            v["core"]["databaseSecrets"][name]={k:identities["connections"][name]["secretRef"][k] for k in ("name","key")}
        return v, lock

    def test_secret_binding_mismatch_rejected(self):
        v, lock = self.complete(["ExternalAPI"])
        v["core"]["databaseSecrets"]["historyReader"]=copy.deepcopy(v["core"]["databaseSecrets"]["core"])
        self.assertIn("identities.historyReader.envBinding", self.check(v, lock))

    def test_unconsumed_reader_variable_rejected(self):
        v, lock = self.complete(["ExternalAPI"])
        self.interface["backend"]["core"]["environmentNames"].remove("MAAS_HISTORY_READER_DSN")
        self.assertIn("identities.historyReader.unconsumedVariable", self.check(v, lock))

    def test_candidate_unmerged_rejected(self):
        v, lock = self.complete(["ExternalAPI"])
        lock["sourceBaseline"]["candidateState"]="draft-unmerged"
        self.assertIn("source.candidateNotMerged", self.check(v, lock))

    def test_old_identity_source_rejected(self):
        v, lock = self.complete(["ExternalAPI"])
        lock["databaseIdentities"]["sourceCommit"]="0"*40
        self.assertIn("identities.sourceMismatch", self.check(v, lock))

    def test_source_inventory_digest_rejected(self):
        v, lock = self.complete(["ExternalAPI"])
        lock["sourceBaseline"]["sourceInventorySha256"]="0"*64
        self.assertIn("source.inventoryChecksum", self.check(v, lock))

    def test_publisher_template_source_rejected(self):
        v, lock = self.complete(["ExternalAPI"])
        lock["databaseIdentities"]["publisherCompletionContract"]["templateSha256"]="0"*64
        self.assertIn("identities.publisher.templateSource", self.check(v, lock))

    def test_qa_revision_mismatch_rejected(self):
        for name in ("qaCore", "qaEvidence"):
            v, lock = self.complete(["ExternalAPI"])
            lock["sourceBaseline"][name]="0"*40
            self.assertIn("source.inventoryRevision", self.check(v, lock))

    def test_manual_merge_claim_cannot_override_snapshot(self):
        v, lock = self.complete(["ExternalAPI"])
        self.interface["backend"]["candidateState"]="draft-unmerged"
        self.assertIn("source.candidateNotMerged", self.check(v, lock))

    def test_missing_operation_payload_connections_rejected(self):
        for name in ("operationReader", "payloadReader"):
            v, lock = self.complete(["ExternalAPI"])
            v["core"]["databaseSecrets"][name]["key"]=""
            self.assertIn("values.schema", self.check(v, lock))

    def test_reader_cannot_use_operations_write_role(self):
        v, lock = self.complete(["ExternalAPI"])
        lock["databaseIdentities"]["connections"]["historyReader"]["roles"]=["maas_release_operations_runtime"]
        self.assertIn("identities.historyReader.roles", self.check(v, lock))

    def test_pending_inputs_reject(self):
        self.assertIn("deploymentApproved", self.check(self.values, self.lock))

    def test_external_api_does_not_require_gpu(self):
        v, lock = self.complete(["ExternalAPI"])
        self.assertEqual([], self.check(v, lock))

    def test_self_hosted_still_requires_gpu(self):
        v, lock = self.complete(["SelfHosted"])
        self.assertIn("runtimeGate.LWS-SGLang-GPU", self.check(v, lock))
        self.assertIn("dependency.sglang", self.check(v, lock))

    def test_missing_inventory_cannot_pass(self):
        v, lock = self.complete(["ExternalAPI"])
        lock["dependencies"]=[]
        lock["runtimeGates"]={}
        issues=self.check(v, lock)
        self.assertIn("dependencies.inventory", issues)
        self.assertIn("runtimeGates.inventory", issues)

    def test_image_lock_mismatch_rejects(self):
        v, lock = self.complete(["ExternalAPI"])
        v["core"]["image"]["digest"]="sha256:"+"abcdef1234567890"*4
        self.assertIn("core.imageLockMismatch", self.check(v, lock))

    def test_compiled_group_cannot_be_changed_only_in_values(self):
        v, lock = self.complete(["ExternalAPI"])
        v["api"]["group"]="other.internal.test"
        self.assertIn("interface.compiledGroupMismatch", self.check(v, lock))

    def test_recovery_inputs_required(self):
        for key in ("rpo", "rto", "retention"):
            v, lock = self.complete(["ExternalAPI"])
            lock["target"][key]=None
            self.assertIn("target."+key, self.check(v, lock))

    def test_partial_or_changed_migrations_reject(self):
        for domain in ("kernel", "release"):
            for mutation in ("missing", "checksum", "applying"):
                v, lock = self.complete(["ExternalAPI"])
                rows=lock["migrationState"][domain]
                if mutation=="missing": rows.pop()
                elif mutation=="checksum": rows[0]["sha256"]="0"*64
                else: rows[0]["state"]="Applying"
                self.assertIn("migrationState."+domain, self.check(v, lock))

    def test_wrong_source_snapshot_rejects(self):
        v, lock = self.complete(["ExternalAPI"])
        lock["sourceBaseline"]["backendInspected"]="0"*40
        self.assertIn("interface.backendSourceMismatch", self.check(v, lock))

    def test_observed_controlled_snapshot_cannot_claim_production(self):
        v, lock = self.complete(["ExternalAPI"])
        observed=json.loads((ROOT / "charts/maas-platform/runtime-interface.json").read_text())
        issues=blockers(v, lock, observed)
        self.assertIn("interface.core.productionAdapterMissing", issues)
        self.assertIn("interface.operator.productionAdaptersMissing", issues)
        self.assertIn("interface.console.productionSessionMissing", issues)

    def test_missing_gateway_artifact_inventory_rejects(self):
        v, lock = self.complete(["ExternalAPI"])
        lock["gatewayComponents"]=[]
        self.assertIn("gatewayComponents.inventory", self.check(v, lock))

    def test_image_provenance_and_group_reject_mismatch(self):
        for field, reason in (("sourceCommit", "imageSourceMismatch"), ("compiledAPIGroup", "imageGroupMismatch")):
            v, lock = self.complete(["ExternalAPI"])
            next(d for d in lock["dependencies"] if d["id"]=="core")[field]="mismatched"
            self.assertIn("core."+reason, self.check(v, lock))

if __name__ == "__main__":
    unittest.main()
