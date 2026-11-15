"""Meaningful offline guards; no inference library import or endpoint access."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from jsonschema.exceptions import ValidationError
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('model_capability_check',ROOT/'check.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class CapabilityInputs(unittest.TestCase):
    def candidate(self): return mod.read(ROOT/'profiles/sglang-r1-distill-qwen7b-candidate.json')
    def test_all_profiles_are_non_executable(self):
        report=mod.inspect()
        self.assertEqual(report['summary']['failed'],0)
        self.assertFalse(report['real_execution_allowed'])
        self.assertTrue(all(p['real_execution_allowed'] is False and p['lock_conditions'] for p in report['profiles']))
    def test_cannot_promote_candidate_by_boolean(self):
        p=self.candidate();p['execution_enabled']=True
        with self.assertRaises(ValidationError): mod.validate_profile(p)
    def test_cannot_claim_verified_token_bound(self):
        p=self.candidate();p['hard_budget'].update(status='verified',input_upper_tokens=4096,output_upper_tokens=1024)
        with self.assertRaises(ValidationError): mod.validate_profile(p)
    def test_unknown_top_level_field_rejected(self):
        p=self.candidate();p['api_key']='FORBIDDEN_SYNTHETIC_FIELD'
        with self.assertRaises(ValidationError): mod.validate_profile(p)
    def test_unknown_nested_credential_field_rejected(self):
        p=self.candidate();p['configuration']['api_key']='SYNTHETIC_FORBIDDEN'
        with self.assertRaises(ValidationError):mod.validate_profile(p)
    def test_selfhosted_cannot_drop_engine_identity(self):
        p=self.candidate();p['engine']=None
        with self.assertRaises(ValidationError):mod.validate_profile(p)
    def test_group_gpu_math_does_not_treat_groups_as_tp(self):
        p=self.candidate();p['configuration']['groups']=2
        self.assertTrue(mod.validate_profile(p))
        p['configuration']['pods_per_group']=2
        with self.assertRaises(ValueError): mod.validate_profile(p)
    def test_external_profile_cannot_request_workload(self):
        p=mod.read(ROOT/'profiles/deepseek-external-candidate.json');p['engine']={'name':'SGLang'}
        with self.assertRaises((ValueError,ValidationError)):mod.validate_profile(p)
    def test_usage_paths_are_source_specific(self):
        raw={'prompt_tokens':12,'completion_tokens':7,'total_tokens':19,'reasoning_tokens':3,'prompt_tokens_details':{'cached_tokens':4}}
        self.assertEqual(mod.project_usage('sglang-v0.5.18',raw)['reasoning_tokens'],3)
        self.assertIsNone(mod.project_usage('deepseek-documentation-candidate',raw)['reasoning_tokens'])
    def test_missing_cache_is_not_zero(self):
        self.assertIsNone(mod.project_usage('sglang-v0.5.18',{'prompt_tokens':12})['input_cached_tokens'])
        self.assertEqual(mod.project_usage('sglang-v0.5.18',{'prompt_tokens':0})['input_tokens'],0)
    def test_subsets_not_added(self):
        raw={'prompt_tokens':12,'completion_tokens':7,'total_tokens':19,'reasoning_tokens':3,'prompt_tokens_details':{'cached_tokens':4}}
        self.assertEqual(mod.project_usage('sglang-v0.5.18',raw)['total_tokens'],19)
    def test_anomalous_fixture_is_not_silently_repaired(self):
        for raw in [{'prompt_tokens':12,'completion_tokens':7,'total_tokens':18},{'prompt_tokens':-1},{'prompt_tokens':12,'prompt_tokens_details':{'cached_tokens':13}},{'completion_tokens':7,'reasoning_tokens':8}]:
            with self.subTest(raw=raw),self.assertRaises(ValueError):mod.project_usage('sglang-v0.5.18',raw)
    def test_long_perf_cell_does_not_fit_4096_proposal(self):
        sizes={x['shape']:x for x in mod.perf_shapes(self.candidate())}
        self.assertTrue(sizes['M']['fits_proposal_arithmetic_only'])
        self.assertFalse(sizes['L']['fits_proposal_arithmetic_only'])
        self.assertEqual(sizes['L']['planned_input_plus_output'],8704)
    def test_d1_is_separate_not_a_current_reader_upgrade(self):
        r=mod.inspect();checks={x['name']:x['passed'] for x in r['checks']}
        self.assertTrue(checks['U08.proposal-3.1/strict_current_rejects'])
        u=mod.read(ROOT/'vectors/U08.proposal-3.1.json')
        self.assertEqual(u['budget_accounting']['token_actual'],'19')
        self.assertIsNone(u['budget_accounting']['cost_actual_atomic'])
        self.assertEqual(u['budget_accounting']['money']['unknown_held'],'520000')
    def test_corrupt_local_evidence_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'model-config.json').write_text('{}')
            r=mod.inspect(p)
            self.assertGreater(r['summary']['failed'],0)
    def test_cli_real_lock_failure_preserves_output(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'output.json';out.write_bytes(b'keep-old')
            r=subprocess.run([sys.executable,str(ROOT/'check.py'),'--require-locked','--output',str(out)],capture_output=True)
            self.assertEqual(r.returncode,2);self.assertEqual(out.read_bytes(),b'keep-old')
    def test_cli_success_and_input_overwrite_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'report.json'
            r=subprocess.run([sys.executable,str(ROOT/'check.py'),'--output',str(out)],capture_output=True)
            self.assertEqual(r.returncode,0);self.assertFalse(json.loads(out.read_text())['real_execution_allowed'])
        target=ROOT/'profiles/controlled-fixture-only.json';before=target.read_bytes()
        r=subprocess.run([sys.executable,str(ROOT/'check.py'),'--output',str(target)],capture_output=True)
        self.assertEqual(r.returncode,2);self.assertEqual(before,target.read_bytes())

if __name__=='__main__':unittest.main()