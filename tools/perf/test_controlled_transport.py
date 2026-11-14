"""Real loopback fixture tests; these do not test the MaaS call kernel."""
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import controlled_transport as lab


class ControlledTransportTests(unittest.TestCase):
    def run_case(self, variant, requests=12, concurrency=4):
        return lab.run_case(requests, concurrency, variant,
                            time.monotonic() + 10, time.monotonic_ns(),
                            first_ms=0, gap_ms=0)

    def test_fresh_connections_are_observed_not_assumed(self):
        case = self.run_case("fresh")
        self.assertTrue(case["complete"])
        self.assertEqual(case["accepted_tcp_connections"], 12)
        self.assertEqual(case["server_requests_seen"], 12)
        self.assertEqual(case["sent"], 12)
        self.assertTrue(all(row["new_connection_observed"] for row in case["rows"]))

    def test_reuse_is_bounded_by_workers(self):
        for concurrency in (1, 4):
            with self.subTest(concurrency=concurrency):
                case = self.run_case("reuse", concurrency=concurrency)
                self.assertTrue(case["complete"])
                self.assertEqual(case["accepted_tcp_connections"], concurrency)
                self.assertEqual(case["metrics"]["new_connections"]["client_visible_ttft_ms"]["count"],
                                 concurrency)
                self.assertEqual(case["metrics"]["reused_connections"]["client_visible_ttft_ms"]["count"],
                                 12 - concurrency)

    def test_sampling_has_no_fake_token_or_business_usage(self):
        case = lab.run_case(2, 1, "reuse", time.monotonic() + 10,
                            time.monotonic_ns(), first_ms=20, gap_ms=2)
        for row in case["rows"]:
            self.assertGreaterEqual(row["client_visible_ttft_ms"], 15)
            self.assertGreaterEqual(row["client_e2e_ms"], row["client_visible_ttft_ms"])
            self.assertIsNone(row["model_tokens"])
            self.assertIsNone(row["visible_tpot_proxy_ms"])
        self.assertTrue(case["cleanup"]["fixture_server_stopped_and_handlers_joined"])

    def test_deadline_preserves_unsent_and_no_fake_rate(self):
        case = lab.run_case(12, 4, "reuse", time.monotonic() - 1,
                            time.monotonic_ns(), first_ms=0, gap_ms=0)
        self.assertEqual(case["sent"], 0)
        self.assertEqual(case["unsent"], 12)
        self.assertEqual(case["accepted_tcp_connections"], 0)
        self.assertIsNone(case["observed_fixture_success_rps"])
        self.assertFalse(case["complete"])

    def test_fixture_cleanup_on_exception(self):
        with self.assertRaisesRegex(RuntimeError, "deliberate fixture failure"):
            with lab.fixture_server(0, 0, 2) as server:
                port = server.server_address[1]
                raise RuntimeError("deliberate fixture failure")
        with self.assertRaises(OSError):
            socket.create_connection((lab.HOST, port), timeout=.2)

    def test_caps_reject_before_any_request(self):
        for values in ((201, 1, 1, 0, 0, 10), (1, 8, 1, 0, 0, 10),
                       (1, 1, 4, 0, 0, 10), (1, 1, 1, float("nan"), 0, 10),
                       (1, 1, 1, 0, 0, 91)):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    lab.validate_config(*values)

    def test_lab_report_marks_fixture_and_measures_complete_window(self):
        report = lab.run_lab(4, (1,), 1, 0, 0, 10)
        self.assertTrue(report["complete"])
        self.assertEqual(report["total_sent"], 8)
        self.assertEqual(report["total_failed"], 0)
        self.assertTrue(report["synthetic"])
        self.assertFalse(report["platform_path_exercised"])
        self.assertEqual(report["paid_model_calls"], 0)
        self.assertIsNone(report["model_usage"])
        self.assertTrue(report["all_fixture_processes_joined"])
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            digest = lab.write_report(report, directory)
            saved = json.loads((Path(directory) / "transport-report.json").read_text(encoding="utf-8"))
            self.assertEqual(len(digest), 64)
            self.assertEqual(saved["evidence_level"], "measured_loopback_fixture_transport")
            self.assertTrue((Path(directory) / "transport-cases.csv").exists())

    def test_cli_has_no_arbitrary_endpoint_mode(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            output = Path(directory) / "no-report"
            result = subprocess.run([sys.executable, str(HERE / "controlled_transport.py"),
                "--output-dir", str(output), "--endpoint", "https://invalid.example/SYNTHETIC_SENTINEL"],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("SYNTHETIC_SENTINEL", result.stdout + result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
