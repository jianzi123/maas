import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("deepseek_milestone",ROOT/"deepseek_milestone.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class DeepSeekSingleSource(unittest.TestCase):
    def cases(self):return m.load(ROOT/"deepseek/protocol-vectors.json")["cases"]
    def case(self,prefix):return next(copy.deepcopy(x) for x in self.cases() if x["id"].startswith(prefix))
    def test_full_vector_matrix(self):
        r=m.evaluate();self.assertEqual(r["summary"]["failed"],0)
        self.assertEqual(len(r["source_case_results"]),23)
    def test_approval_fields_preserved_and_runtime_not_promoted(self):
        self.assertEqual(len(m.missing_approvals()),34)
        r=m.evaluate();self.assertFalse(r["real_execution_enabled"]);self.assertIsNone(r["actual_model_scores"])
    def test_normal_and_heartbeat_have_identical_parent_usage(self):
        a=m.inspect_case(self.case("DS01_"));b=m.inspect_case(self.case("DS02_"))
        self.assertEqual(a["final_usage_candidate"],b["final_usage_candidate"])
        self.assertEqual(a["final_usage_candidate"]["total_tokens"],19)
    def test_truncation_is_not_quality_success(self):
        self.assertEqual(m.inspect_case(self.case("DS03_"))["status"],"final_candidate_quality_truncated")
        self.assertFalse(m.kv.quality_pass("Q01","391","length"))
    def test_progress_second_finish_and_trailing_data_are_rejected(self):
        for id in ["DS05_","DS06_","DS07_","DS11_"]:
            self.assertEqual(m.inspect_case(self.case(id))["status"],"protocol_rejected")
    def test_cancel_or_deadline_never_returns_candidate(self):
        for id in ["DS08_","DS09_","DS18_","DS23_"]:
            r=m.inspect_case(self.case(id));self.assertEqual(r["status"],"interrupted");self.assertIsNone(r["final_usage_candidate"])
    def test_source_error_latched_in_stream_and_nonstream(self):
        for id in ["DS10_","DS21_"]:
            self.assertEqual(m.inspect_case(self.case(id))["status"],"protocol_rejected")
    def test_cache_alias_contradiction_not_silently_preferred(self):
        self.assertEqual(m.inspect_case(self.case("DS12_"))["status"],"protocol_rejected")
    def test_tools_or_thinking_mode_drift_blocks(self):
        for id in ["DS13_","DS14_"]:
            self.assertEqual(m.inspect_case(self.case(id))["status"],"protocol_rejected")
    def test_safety_is_output_subset_not_added_again(self):
        r=m.inspect_case(self.case("DS15_"))
        self.assertEqual(r["final_usage_candidate"]["total_tokens"],19)
        self.assertEqual(m.inspect_case(self.case("DS16_"))["status"],"protocol_rejected")
    def test_sglang_final_shape_is_not_deepseek_final_shape(self):
        self.assertEqual(m.inspect_case(self.case("DS17_"))["status"],"protocol_rejected")
    def test_nonstream_and_real_zero_distinct_from_missing(self):
        self.assertEqual(m.inspect_case(self.case("DS20_"))["status"],"final_candidate")
        self.assertEqual(m.inspect_case(self.case("DS19_"))["final_usage_candidate"]["total_tokens"],0)
        self.assertIsNone(m.inspect_case(self.case("DS04_"))["final_usage_candidate"])
    def test_source_binding_and_fingerprint_drift_rejected(self):
        c=self.case("DS01_");c["binding"]["upstream_model"]="other"
        self.assertEqual(m.inspect_case(c)["status"],"protocol_rejected")
        c=self.case("DS01_");c["response"]["wire"]=c["response"]["wire"].replace('"system_fingerprint": "synthetic-only"','"system_fingerprint": "other"',1)
        self.assertEqual(m.inspect_case(c)["status"],"protocol_rejected")
    def test_nonstream_whitespace_is_valid_but_not_a_token_event(self):
        c=self.case("DS20_");c["response"]["wire"]="\r\n\n"+c["response"]["wire"]
        self.assertEqual(m.inspect_case(c)["status"],"final_candidate")
    def test_source_nontext_role_or_extra_tool_extension_rejected(self):
        for old,new in [('"content": "391"','"content": [1]'),('"content": "391"','"role": "tool", "content": "391"'),('"content": "391"','"server_tool_event": {"state": "searching"}')]:
            c=self.case("DS01_");c["response"]["wire"]=c["response"]["wire"].replace(old,new,1)
            self.assertEqual(m.inspect_case(c)["status"],"protocol_rejected")
    def test_boolean_choice_index_not_integer_zero(self):
        c=self.case("DS20_");c["response"]["wire"]=c["response"]["wire"].replace('"index": 0','"index": false')
        self.assertEqual(m.inspect_case(c)["status"],"protocol_rejected")
    def test_run_gate_and_source_failure_preserve_old_report(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/"report.json";out.write_bytes(b"old")
            for extra in [["--require-approved-inputs"],["--source-root",folder]]:
                r=subprocess.run([sys.executable,str(ROOT/"deepseek_milestone.py"),*extra,"--output",str(out)],capture_output=True)
                self.assertEqual(r.returncode,2);self.assertEqual(out.read_bytes(),b"old")
if __name__=="__main__":unittest.main()