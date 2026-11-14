"""Actual host C++ process regressions for the gate included by gemm.cu."""
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
OPS = HERE / "operators"
spec = importlib.util.spec_from_file_location("gemm_host_check", OPS / "check_gemm_host.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class GemmHostValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.compiler = host.compiler_path()
        except RuntimeError as error:
            raise unittest.SkipTest(str(error))
        cls.temp = tempfile.TemporaryDirectory(prefix="host-cpp-", dir=HERE)
        cls.binary, build = host.compile_fixture(cls.temp.name, cls.compiler)
        if build.returncode:
            cls.temp.cleanup()
            raise RuntimeError("host C++ build failed:\n" + build.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def check(self, scenario):
        result = host.run_scenario(self.binary, scenario)
        self.assertTrue(result["passed"], result)

    def test_candidate_and_baseline_nan_inf_fail_before_continuation(self):
        for scenario in host.REJECT_CASES[:6]:
            with self.subTest(scenario=scenario):
                self.check(scenario)

    def test_reference_nan_inf_and_late_nan_fail(self):
        for scenario in host.REJECT_CASES[6:10]:
            with self.subTest(scenario=scenario):
                self.check(scenario)

    def test_finite_errors_on_both_outputs_fail(self):
        for scenario in ("candidate_wrong", "baseline_wrong"):
            with self.subTest(scenario=scenario):
                self.check(scenario)

    def test_invalid_tolerances_and_overflow_fail(self):
        for scenario in ("atol_nan", "rtol_inf", "negative_tolerance", "tolerance_overflow"):
            with self.subTest(scenario=scenario):
                self.check(scenario)

    def test_normal_tolerance_zero_and_boundary_pass(self):
        for scenario in host.PASS_CASES:
            with self.subTest(scenario=scenario):
                self.check(scenario)

    def test_original_one_element_nan_fixture_is_rejected(self):
        self.check("original_nan_fixture")

    def test_finite_math_only_build_is_rejected(self):
        _, build = host.compile_fixture(self.temp.name, self.compiler, fast_math=True)
        self.assertNotEqual(build.returncode, 0)
        self.assertIn("requires IEEE finite checks", build.stderr)


if __name__ == "__main__":
    unittest.main()
