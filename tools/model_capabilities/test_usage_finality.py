import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("usage_finality_oracle",ROOT/"usage_finality.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class UsageFinality(unittest.TestCase):
    def cases(self):return {x["id"]:x for x in m.read(ROOT/"finality/protocol-vectors.json")["cases"]}
    def case(self,prefix):return next(copy.deepcopy(v) for k,v in self.cases().items() if k.startswith(prefix))
    def test_all_hand_expected_vectors(self):
        r=m.evaluate();self.assertEqual(r["summary"]["failed"],0)
        self.assertFalse(r["execution_enabled"]);self.assertIsNone(r["actual_model_scores"])
    def test_17_to_19_progress_is_not_conflicting_final(self):
        r=m.classify(self.case("F01_"))
        self.assertEqual(r["status"],"final_candidate");self.assertEqual(r["progress_snapshots"],2)
        self.assertEqual(r["final_snapshots"],1);self.assertEqual(r["final_usage_candidate"]["total_tokens"],19)
    def test_monotonic_progress_with_finish_and_DONE_still_not_final(self):
        r=m.classify(self.case("F02_"));self.assertEqual(r["status"],"usage_unavailable")
        self.assertEqual(r["progress_snapshots"],2);self.assertIsNone(r["final_usage_candidate"])
    def test_identical_final_and_increasing_conflict_are_different(self):
        self.assertEqual(m.classify(self.case("F03_"))["status"],"final_candidate")
        self.assertEqual(m.classify(self.case("F04_"))["status"],"protocol_rejected")
    def test_subset_conflict_is_not_accepted_by_parent_monotonicity(self):
        for prefix in ["F05_","F06_"]:
            self.assertEqual(m.classify(self.case(prefix))["status"],"protocol_rejected")
    def test_no_boundary_or_cancellation_prevents_candidate(self):
        for prefix in ["F07_","F08_","F09_","F29_"]:
            r=m.classify(self.case(prefix));self.assertEqual(r["status"],"interrupted");self.assertIsNone(r["final_usage_candidate"])
    def test_upstream_error_then_DONE_never_recovered(self):
        self.assertEqual(m.classify(self.case("F10_"))["status"],"protocol_rejected")
    def test_late_progress_does_not_reopen_closed_logical_boundary(self):
        r=m.classify(self.case("F13_"));self.assertEqual(r["status"],"final_candidate")
        self.assertEqual(r["late_observations"],1);self.assertEqual(r["final_usage_candidate"]["total_tokens"],19)
        self.assertEqual(r["ledger_writes"],0)
    def test_before_boundary_progress_after_final_is_rejected(self):
        self.assertEqual(m.classify(self.case("F12_"))["status"],"protocol_rejected")
    def test_supplier_final_shape_cannot_be_exchanged(self):
        self.assertEqual(m.classify(self.case("F20_"))["status"],"final_candidate")
        self.assertEqual(m.classify(self.case("F23_"))["status"],"protocol_rejected")
    def test_source_056_does_not_verify_reasoning_default_zero(self):
        r=m.classify(self.case("F19_"));self.assertIsNone(r["final_usage_candidate"]["reasoning_tokens"])
        p=m.upstream_usage_probe("v0.5.6");self.assertNotIn("reasoning_tokens",p["final"])
    def test_source_518_arithmetic_includes_hidden_subset_but_not_twice(self):
        p=m.upstream_usage_probe("v0.5.18")
        self.assertEqual(p["progress"]["total_tokens"],17);self.assertEqual(p["final"]["total_tokens"],19)
        self.assertEqual(p["final"]["reasoning_tokens"],3)
    def test_missing_and_explicit_zero_remain_distinct(self):
        r=m.classify(self.case("F26_"));self.assertIsNone(r["final_usage_candidate"]["input_cached_tokens"])
        r=m.classify(self.case("F18_"));self.assertEqual(r["final_usage_candidate"]["total_tokens"],0)
        self.assertIsNone(m.classify(self.case("F11_"))["final_usage_candidate"])
    def test_all_fragmentations_give_same_classification(self):
        for c in self.cases().values():
            p=dict(m.profile_by_id(c["profile_id"]));p.update(c.get("profile_override_for_negative_test",{}))
            expected=m.classify(c,p)
            for widths in [(1,),(65536,),(2,3,5)]:
                self.assertEqual(m.classify(c,p,widths),expected)
    def test_trusted_profile_cannot_be_promoted_or_guessed_incremental(self):
        c=self.case("F01_")
        for changes in [{"approval_status":"approved"},{"execution_enabled":True},{"usage_semantics":"incremental"},{"supported_choices":2}]:
            p=dict(m.profile_by_id(c["profile_id"]));p.update(changes)
            self.assertEqual(m.classify(c,p)["status"],"profile_rejected")
    def test_eof_partial_utf8_or_bad_identity_rejected(self):
        c=self.case("F01_");c["response"]["sse"]=c["response"]["sse"][:-2]
        self.assertEqual(m.classify(c)["status"],"protocol_rejected")
        self.assertEqual(m.classify(self.case("F14_"))["status"],"protocol_rejected")
    def test_decode_and_inflight_reservations_precede_chunk(self):
        cases=m.read(ROOT/"finality/scheduling-inputs.json")["cases"]
        self.assertEqual(m.feasible_chunks(cases[0]),[1,16])
        self.assertEqual(m.feasible_chunks(cases[1]),[])
        self.assertEqual(m.feasible_chunks(cases[2]),[])
        self.assertEqual(m.feasible_chunks(cases[3]),[1,2])
    def test_protected_pages_are_not_free_or_fairness_proof(self):
        c=copy.deepcopy(m.read(ROOT/"finality/scheduling-inputs.json")["cases"][1])
        c["protected_pages"]=10**6
        self.assertEqual(m.feasible_chunks(c),[])
        c["free_pages"]=-1
        with self.assertRaises(ValueError):m.feasible_chunks(c)
    def test_terminal_delivery_is_separate_no_mutation_expectation(self):
        for v in m.read(ROOT/"finality/terminal-delivery-vectors.json")["cases"]:
            self.assertEqual(m.terminal_disposition(v),v["expected"])
    def test_cli_input_overwrite_and_bad_source_preserve_output(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/"report.json";out.write_bytes(b"old")
            r=subprocess.run([sys.executable,str(ROOT/"usage_finality.py"),"--source-root",folder,"--output",str(out)],capture_output=True)
            self.assertEqual(r.returncode,2);self.assertEqual(out.read_bytes(),b"old")
        path=ROOT/"finality/profiles.json";old=path.read_bytes()
        r=subprocess.run([sys.executable,str(ROOT/"usage_finality.py"),"--output",str(path)],capture_output=True)
        self.assertEqual(r.returncode,2);self.assertEqual(path.read_bytes(),old)
if __name__=="__main__":unittest.main()