import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("kv_pd_inputs",ROOT/"kv_pd.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class KVPDCapabilityInputs(unittest.TestCase):
    def plan(self):return m.read(ROOT/"experiments/kv-pd-v0.4.json")
    def test_fixed_comparison_and_candidate_are_separate(self):
        p=self.plan();self.assertTrue(m.validate_plan(p))
        p["comparison_engine"]=copy.deepcopy(p["deployment_candidate"])
        with self.assertRaises(ValueError):m.validate_plan(p)
    def test_execution_cannot_be_enabled_by_input(self):
        for key,value in [("execution_enabled",True),("synthetic",False),("approval_status","approved")]:
            p=self.plan();p[key]=value
            with self.assertRaises(ValueError):m.validate_plan(p)
    def test_geometry_is_model_specific_not_MLA_or_TP_average(self):
        p=self.plan();self.assertEqual(m.kv_bytes_per_token(p["model"]),57344)
        for key,value in [("kv_layout","MLA"),("tp",2),("kv_dtype","fp8")]:
            model=copy.deepcopy(p["model"]);model[key]=value
            with self.assertRaises(ValueError):m.kv_bytes_per_token(model)
    def test_new_page_boundary_uses_partial_tail(self):
        self.assertEqual(m.new_pages(17,18,16),0)
        self.assertEqual(m.new_pages(16,17,16),1)
        self.assertEqual(m.new_pages(31,33,16),1)
    def test_invalid_lengths_do_not_become_pages(self):
        for args in [(-1,16),(1,0),(True,16),(1.5,16)]:
            with self.assertRaises(ValueError):m.pages(*args)
        with self.assertRaises(ValueError):m.new_pages(18,17,16)
    def test_partial_prefix_is_not_shared_or_COW_claimed(self):
        self.assertEqual(m.aligned_prefix(15,16),0)
        self.assertEqual(m.aligned_prefix(17,16),16)
    def test_shared_prefix_counted_once_and_other_groups_not_merged(self):
        same=m.pooled_envelope(2048,256,1536,2,16)
        independent=2*m.pooled_envelope(2048,256,1536,1,16)
        self.assertEqual(same,192);self.assertEqual(independent,288)
    def test_first_generated_token_not_already_in_KV(self):
        p=self.plan();p["shapes"]=[dict(id="boundary",input_tokens=16,output_cap_tokens=1,shared_prefix_tokens=0)]
        row=next(x for x in m.shape_report(p) if x["page_tokens"]==16)
        self.assertEqual(row["conservative_full_envelope_pages"],2)
        self.assertEqual(row["max_committed_if_no_overallocation_pages"],1)
    def test_L_context_is_blocked_without_shortening(self):
        rows=m.shape_report(self.plan());L=next(x for x in rows if x["shape"]=="L" and x["page_tokens"]==16)
        self.assertEqual(L["conservative_full_envelope_pages"],544)
        self.assertFalse(L["fits_previous_4096_proposal"]);self.assertFalse(L["runtime_context_verified"])
    def test_quality_has_positive_and_wrong_truncated_cases(self):
        for x in m.read(ROOT/"experiments/quality-gold.json")["gold"]:
            self.assertTrue(m.quality_pass(x["id"],x["answer"]))
            self.assertFalse(m.quality_pass(x["id"],x["answer"],"length"))
        self.assertFalse(m.quality_pass("Q01","392"))
        self.assertFalse(m.quality_pass("Q02",'{"order_id":"A-17","quantity":3,"extra":1}'))
        self.assertFalse(m.quality_pass("Q04","净利润100万元"))
        self.assertFalse(m.quality_pass("Q06","猫GPU-7"))
    def test_code_grading_never_executes_imports_or_calls(self):
        self.assertTrue(m.quality_pass("Q07","def double(x):\n    return x*2"))
        for answer in ["import os\ndef double(x):\n return 2*x","def double(x):\n return __import__('os').system('x')","def double(x):\n return x+x","def double(x=1):\n return 2*x"]:
            self.assertFalse(m.quality_pass("Q07",answer))
    def test_SSE_fragmentation_and_error_scope(self):
        for x in m.read(ROOT/"experiments/protocol-vectors.json")["cases"]:
            for sizes in [(1,),(2,7,1),(65536,)]:
                self.assertEqual(m.public_stream_outcome(x["wire"].encode(),sizes),x["expected"])
    def test_source_error_payload_is_not_public_chunk(self):
        wire='data: {"error":{"message":"synthetic"}}\n\ndata: [DONE]\n\n'
        self.assertEqual(m.public_stream_outcome(wire.encode()),"invalid")
    def test_identity_mismatch_rejected(self):
        wire=m.read(ROOT/"experiments/protocol-vectors.json")["cases"][0]["wire"]
        wire=wire.replace('"model": "model-a"','"model": "other-model"',1)
        self.assertEqual(m.public_stream_outcome(wire.encode()),"invalid")
    def test_content_after_finish_and_oversize_event_rejected(self):
        wire=m.read(ROOT/"experiments/protocol-vectors.json")["cases"][0]["wire"]
        content=wire.split("\\r\\n\\r\\n")[0]+"\\r\\n\\r\\n"
        altered=wire.replace("data: [DONE]",content+"data: [DONE]")
        self.assertEqual(m.public_stream_outcome(altered.encode()),"invalid")
        self.assertEqual(m.public_stream_outcome(("data: "+("x"*262145)+"\\n\\n").encode()),"invalid")
        self.assertEqual(m.public_stream_outcome(b"data: \\xff\\n\\n"),"invalid")
    def test_fragment_sizes_must_progress(self):
        with self.assertRaises(ValueError):m.sse_events(b"data: [DONE]\\n\\n",(0,))
    def test_report_is_not_engine_or_quality_result(self):
        r=m.evaluate(self.plan())
        self.assertEqual(r["summary"]["failed"],0)
        self.assertFalse(r["real_execution_allowed"]);self.assertIsNone(r["actual_model_scores"])
        self.assertNotIn("torch",sys.modules)
    def test_runtime_guard_and_bad_plan_preserve_output(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/"report.json";out.write_bytes(b"old")
            r=subprocess.run([sys.executable,str(ROOT/"kv_pd.py"),"--require-runtime","--output",str(out)],capture_output=True)
            self.assertEqual(r.returncode,2);self.assertEqual(out.read_bytes(),b"old")
            bad=self.plan();bad["model"]["revision"]="wrong"
            inp=Path(folder)/"bad.json";inp.write_text(json.dumps(bad),encoding="utf-8")
            r=subprocess.run([sys.executable,str(ROOT/"kv_pd.py"),"--plan",str(inp),"--output",str(out)],capture_output=True)
            self.assertEqual(r.returncode,2);self.assertEqual(out.read_bytes(),b"old")

if __name__=="__main__":unittest.main()