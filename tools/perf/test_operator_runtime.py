"""CPU oracle and disabled-execution tests; never imports a GPU framework."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

HERE=Path(__file__).resolve().parent
OPS=HERE/"operators"
sys.path.insert(0,str(HERE));sys.path.insert(0,str(OPS))
import reference as ref
import bench
import runtime_metrics as metrics


class OperatorRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.plan=bench.read_plan(OPS/"plan.json")

    def test_gemm_known_answer_and_scalar_tail(self):
        self.assertEqual(ref.gemm([[1,2],[3,4]],[[5],[6]]).tolist(),[[17],[39]])
        rng=np.random.default_rng(7)
        for m,n,k in [(1,1,1),(3,7,5),(17,19,13)]:
            a,b=rng.normal(size=(m,k)),rng.normal(size=(k,n))
            np.testing.assert_allclose(ref.gemm(a,b),ref.gemm_scalar(a,b),atol=1e-12)

    def test_grouped_gemm_and_incompatible_shape(self):
        result=ref.grouped_gemm([(np.ones((2,3)),np.ones((3,4))),(np.ones((1,5)),np.ones((5,2)))])
        np.testing.assert_equal(result[0],np.full((2,4),3))
        np.testing.assert_equal(result[1],np.full((1,2),5))
        with self.assertRaises(ValueError):ref.gemm(np.ones((2,3)),np.ones((4,2)))

    def test_decode_uses_bottom_right_causal_alignment(self):
        q=np.zeros((1,1,1,1));k=np.zeros((1,1,3,1));v=np.array([0,2,4]).reshape(1,1,3,1)
        self.assertEqual(float(ref.attention_dense(q,k,v).item()),2)
        self.assertEqual(float(ref.attention_online(q,k,v).item()),2)

    def test_prefill_suffix_positions_are_not_upper_left(self):
        q=np.zeros((1,1,2,1));k=np.zeros((1,1,3,1));v=np.arange(1,4).reshape(1,1,3,1)
        np.testing.assert_allclose(ref.attention_dense(q,k,v).ravel(),[1.5,2])

    def test_gqa_head_mapping(self):
        q=np.zeros((1,4,1,1));k=np.zeros((1,2,2,1))
        v=np.array([10,10,20,20]).reshape(1,2,2,1)
        np.testing.assert_equal(ref.attention_dense(q,k,v).ravel(),[10,10,20,20])

    def test_all_masked_row_is_zero_not_nan(self):
        q=np.ones((1,1,2,3));k=np.ones((1,1,2,3));v=np.ones((1,1,2,3))
        mask=np.array([[False,False],[True,False]])
        a=ref.attention_dense(q,k,v,mask=mask)
        np.testing.assert_equal(a[0,0,0],0)
        np.testing.assert_allclose(a,ref.attention_online(q,k,v,mask=mask))
        np.testing.assert_equal(a[0,0,1],1)

    def test_online_oracle_noncontiguous_and_block_tails(self):
        rng=np.random.default_rng(9)
        q=rng.normal(size=(2,4,3,10))[...,::2]
        k=rng.normal(size=(2,2,7,10))[...,::2];v=rng.normal(size=(2,2,7,10))[...,::2]
        for block in (1,2,4,8):
            np.testing.assert_allclose(ref.attention_dense(q,k,v),
                ref.attention_online(q,k,v,block=block),atol=1e-12)

    def test_invalid_attention_and_nan_rejected(self):
        q=np.zeros((1,3,1,2));k=np.zeros((1,2,3,2))
        with self.assertRaises(ValueError):ref.attention_dense(q,k,k)
        q=np.full((1,2,1,2),np.nan)
        with self.assertRaises(ValueError):ref.attention_dense(q,k,k)

    def test_rmsnorm_zero_and_shape(self):
        np.testing.assert_equal(ref.rmsnorm(np.zeros((3,7)),np.ones(7)),0)
        with self.assertRaises(ValueError):ref.rmsnorm(np.ones((2,3)),np.ones(2))
        with self.assertRaises(ValueError):ref.rmsnorm(np.ones((2,3)),np.ones(3),0)
        with self.assertRaises(ValueError):ref.rmsnorm(np.full((2,3),np.nan),np.ones(3))

    def test_error_policy_detects_wrong_results_and_nan(self):
        self.assertFalse(ref.error_metrics([1],[2],1e-5,1e-4)["passed"])
        self.assertFalse(ref.error_metrics([np.nan],[1],1e-5,1e-4)["passed"])
        self.assertTrue(ref.error_metrics([1.000001],[1],1e-5,1e-4)["passed"])

    def test_cpu_suite_has_no_gpu_timings_or_quality_claim(self):
        result=bench.cpu_reference(self.plan)
        self.assertEqual(len(result["cases"]),8)
        self.assertTrue(result["all_passed"])
        self.assertFalse(result["gpu_executed"])
        self.assertIsNone(result["gpu_timings"])

    def test_gpu_guard_precedes_framework_import(self):
        original=__import__
        def guarded(name,*args,**kwargs):
            if name=="torch":raise AssertionError("torch must not be imported")
            return original(name,*args,**kwargs)
        with patch("builtins.__import__",side_effect=guarded):
            with self.assertRaises(ValueError):
                bench.gpu_case(self.plan,self.plan["cases"][0],"torch")
            small=copy.deepcopy(self.plan)
            small.update(execution_enabled=True,approval_ref="synthetic-test-only",target_environment="synthetic-test")
            small["gpu_limits"]={"warmup":1,"samples":1,"max_estimated_data_bytes":1024}
            with self.assertRaisesRegex(ValueError,"sample cap"):
                bench.gpu_case(small,small["cases"][0],"torch",instrumented=True)

    def test_gpu_cli_refuses_disabled_plan_without_report(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            output=Path(directory)/"not-created.json"
            proc=subprocess.run([sys.executable,str(OPS/"bench.py"),"--mode","gpu","--output",str(output)],
                                capture_output=True,text=True)
            self.assertEqual(proc.returncode,2)
            self.assertFalse(output.exists())
            self.assertNotIn("OMP:",proc.stderr)

    def test_profiler_dry_run_and_execute_guard(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            cmd=[sys.executable,str(OPS/"profile_operator.py"),"--tool","ncu","--output-dir",directory]
            proc=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            result=json.loads(proc.stdout)
            self.assertTrue(result["dry_run"])
            self.assertFalse(result["execution_enabled"])
            self.assertIn("--instrumented",result["argv"])
            proc=subprocess.run(cmd+["--execute"],capture_output=True,text=True)
            self.assertEqual(proc.returncode,2)
            proc=subprocess.run(cmd+["--unexpected","SYNTHETIC_SECRET_SENTINEL"],capture_output=True,text=True)
            self.assertEqual(proc.returncode,2)
            self.assertNotIn("SYNTHETIC_SECRET_SENTINEL",proc.stdout+proc.stderr)

    def test_fixed_mixed_sequence_and_hash(self):
        import hashlib
        path=HERE/"runtime/J02-mixed-sequence.json"
        sequence=json.loads(path.read_text(encoding="utf-8"))
        labels=[entry["shape"] for entry in sequence["entries"]]
        self.assertEqual({s:labels.count(s) for s in "SML"},{"S":120,"M":60,"L":20})
        self.assertFalse(sequence["execution_enabled"])
        plan=json.loads((HERE/"experiments/first-batch-v0.4.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["runtime_extension"]["J02"]["sha256"],hashlib.sha256(path.read_bytes()).hexdigest())

    def row(self,release=20):
        return {"observer_scope":"independent-fixture-clock","independent_observer":True,
                "cancel_ms":0,"stop_ms":None,"safe_ms":10,"evidence_ms":15,
                "release_ms":release,"successor_ms":25 if release is not None else None}

    def test_unrecovered_samples_are_censored_not_dropped(self):
        result=metrics.recovery_summary([self.row(),self.row(None)],100)
        self.assertEqual(result["count"],2);self.assertEqual(result["unrecovered"],1)
        self.assertEqual(result["cancel_to_release_observed_ms"]["denominator"],2)
        self.assertEqual(result["cancel_to_release_observed_ms"]["coverage"],.5)
        self.assertEqual(result["right_censor_durations_ms"],[None,100])
        self.assertEqual(result["actual_stop_unknown"],2)

    def test_recovery_requires_independent_clock_and_order(self):
        other=self.row();other["observer_scope"]="another-clock"
        with self.assertRaises(ValueError):metrics.recovery_summary([self.row(),other],100)
        bad=self.row();bad["independent_observer"]=False
        with self.assertRaises(ValueError):metrics.recovery_summary([bad],100)
        with self.assertRaises(ValueError):metrics.recovery_summary([self.row(11)],100)

    def test_held_integral_missing_is_not_zero(self):
        result=metrics.held_area([{"at_ms":0,"held":"10"},{"at_ms":5,"held":None},
                                  {"at_ms":10,"held":"0"}],0,20,"token")
        self.assertEqual(result["known_integral"],"50")
        self.assertEqual(result["missing_duration_ms"],5)
        self.assertIsNone(result["actual_usage"])

    def test_money_integral_preserves_large_integer_precision(self):
        value=10**37+1
        result=metrics.held_area([{"at_ms":0,"held":str(value)}],0,3,"money:TST")
        self.assertEqual(result["known_integral"],str(value*3))
        self.assertEqual(result["known_integral_in_seconds"],str((value*3)//1000)+".003")

    def test_bad_held_input_and_currency_rejected(self):
        for unit in ("USD","money:T1T"):
            with self.assertRaises(ValueError):metrics.held_area([],0,10,unit)
        with self.assertRaises(ValueError):metrics.held_area([{"at_ms":0,"held":"-1"}],0,10,"token")
        with self.assertRaises(ValueError):metrics.held_area([{"at_ms":5,"held":"1"},{"at_ms":4,"held":"1"}],0,10,"token")


if __name__=="__main__":unittest.main()
