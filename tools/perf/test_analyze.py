"""Behavioral assertions over fixed, explicitly synthetic inputs."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze

spec = importlib.util.spec_from_file_location("fixture_builder", HERE / "fixtures/build_fixture.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class OfflineMetricsTests(unittest.TestCase):
    def setUp(self):
        self.data = analyze.load_json(HERE / "fixtures/synthetic.json")

    def report(self):
        return analyze.analyze(self.data)

    def row(self, index, report=None):
        return (report or self.report())["rows"][index - 1]

    def subset(self, indices):
        ids = {builder.uid(300 + i) for i in indices}
        for field in ("requests", "observations", "terminals", "gateway_observations"):
            self.data[field] = [v for v in self.data[field] if v["request_id"] in ids]

    def test_fixed_fixture_regenerates_identically(self):
        self.assertEqual(self.data, builder.build())

    def test_fixed_counts_and_denominators(self):
        r = self.report()
        self.assertEqual(r["counts"], dict(sent=9, admitted=8, succeeded=4, failed=2,
            cancelled=1, timed_out=0, interrupted=0, pending=1, rejected=1))
        self.assertEqual(r["rates"]["success_rps"], 4)
        self.assertAlmostEqual(r["rates"]["technical_error_over_sent"], 2 / 9)
        self.assertAlmostEqual(r["rates"]["rejection_over_sent"], 1 / 9)
        self.assertEqual(r["rates"]["admitted_nonsuccess_over_admitted"], 3 / 8)

    def test_first_content_ignores_role_empty_heartbeat_usage(self):
        r = self.row(1)
        self.assertEqual(r["client_visible_ttft_ms"], 100)
        self.assertEqual(r["server_first_chunk_ms"], 60)
        self.assertEqual(r["client_e2e_ms"], 200)
        self.assertEqual(r["chunk_gap_ms"], [80])
        self.assertAlmostEqual(r["visible_tpot_proxy_ms"], 80 / 3)
        self.assertEqual(r["engine_generated_tpot_ms"], 30)

    def test_usage_only_and_real_zero_are_not_missing(self):
        r = self.report()
        self.assertIsNone(self.row(2, r)["client_visible_ttft_ms"])
        self.assertIsNone(self.row(2, r)["visible_tpot_proxy_ms"])
        self.assertEqual(r["usage"]["total_tokens"]["known_sum"], 41)
        self.assertEqual(r["usage"]["total_tokens"]["known_requests"], 4)
        self.assertEqual(r["usage"]["total_tokens"]["missing_admitted"], 4)
        self.assertEqual(r["usage"]["input_tokens"]["known_sum"], 26)
        self.assertEqual(r["usage"]["output_tokens"]["known_sum"], 15)

    def test_all_unknown_is_null_not_zero(self):
        self.subset([4])
        r = self.report()
        self.assertIsNone(r["usage"]["total_tokens"]["known_sum"])
        self.assertIsNone(r["usage"]["total_tokens"]["known_per_second"])
        self.assertIsNone(r["diagnostic_reconciliation"]["money_by_frozen_price"][0]["known_sum_atomic"])

    def test_only_real_zero_stays_zero(self):
        self.subset([2])
        r = self.report()
        self.assertEqual(r["usage"]["total_tokens"]["known_sum"], 0)
        self.assertEqual(r["usage"]["total_tokens"]["coverage"], 1)
        self.assertEqual(r["diagnostic_reconciliation"]["money_by_frozen_price"][0]["known_sum_atomic"], "0")

    def test_held_is_never_actual_and_pending_is_explicit(self):
        r = self.report()["diagnostic_reconciliation"]
        self.assertEqual(r["unknown_held_not_actual"]["token"], "420")
        self.assertEqual(r["money_by_frozen_price"][0]["unknown_held_atomic"], "1560000")
        self.assertEqual(r["money_by_frozen_price"][0]["known_sum_atomic"], "157600")
        self.assertEqual(r["terminal_records"], 7)
        self.assertEqual(r["pending"], 1)
        self.assertTrue(r["balanced"])

    def test_rejection_has_no_binding_or_finalized_event(self):
        self.assertIsNone(self.row(3)["invocation_binding"])
        self.assertEqual(self.row(3)["result"], "rejected")
        bad = copy.deepcopy(self.data["terminals"][0])
        bad["event_id"] = builder.uid(998)
        bad["request_id"] = self.data["requests"][2]["request_id"]
        self.data["terminals"].append(bad)
        with self.assertRaises(analyze.InputError):
            self.report()

    def test_raw_eof_and_stream_error_are_failures(self):
        self.assertEqual(self.row(4)["result"], "failed")
        self.assertEqual(self.row(5)["result"], "failed")
        self.assertIsNone(self.row(4)["client_e2e_ms"])
        self.assertEqual(self.row(4)["termination_ms"], 300)
        self.assertEqual(self.row(6)["result"], "cancelled")

    def test_normal_done_required_for_success(self):
        self.data["requests"][0]["frames"].pop()
        with self.assertRaises(analyze.InputError):
            self.report()

    def test_error_then_done_cannot_be_success(self):
        self.data["requests"][0]["frames"].insert(-1, builder.wire(190, {"error": {}}))
        with self.assertRaises(analyze.InputError):
            self.report()

    def test_single_token_tpot_is_null_and_slo_tpot_not_applicable(self):
        self.assertIsNone(self.row(7)["visible_tpot_proxy_ms"])
        self.assertTrue(self.row(7)["within_slo_and_quality"])

    def test_goodput_and_coverage(self):
        r = self.report()
        self.assertEqual(r["goodput"]["eligible"], 3)
        self.assertEqual(r["goodput"]["count"], 2)
        self.assertEqual(r["goodput"]["rps"], 2)
        self.assertAlmostEqual(r["goodput"]["pass_over_sent"], 2 / 9)
        self.data["slo"] = None
        self.assertIsNone(self.report()["goodput"]["rps"])

    def test_no_slo_pass_for_unknown_quality(self):
        self.data["requests"][0]["quality_pass"] = None
        self.assertIsNone(self.row(1)["within_slo_and_quality"])
        self.assertEqual(self.report()["goodput"]["count"], 1)

    def test_all_and_success_distributions_keep_failures_and_missing(self):
        r = self.report()["distributions"]
        self.assertEqual(r["all_sent_observed"]["client_visible_ttft_ms"]["count"], 5)
        self.assertEqual(r["all_sent_observed"]["client_visible_ttft_ms"]["missing"], 4)
        self.assertAlmostEqual(r["all_sent_observed"]["client_visible_ttft_ms"]["p95"], 344)
        self.assertEqual(r["success"]["client_visible_ttft_ms"]["denominator"], 4)
        self.assertEqual(r["success"]["client_visible_ttft_ms"]["p50"], 100)
        self.assertEqual(r["success"]["client_visible_ttft_ms"]["p95"], 370)

    def test_identical_duplicates_do_not_change_denominators(self):
        for field in ("requests", "observations", "terminals"):
            self.data[field].append(copy.deepcopy(self.data[field][0]))
        r = self.report()
        self.assertEqual(r["counts"]["sent"], 9)
        self.assertEqual(r["duplicates_ignored"], 3)

    def test_conflicting_duplicate_is_rejected(self):
        duplicate = copy.deepcopy(self.data["observations"][0])
        duplicate["outcome"] = "error"
        self.data["observations"].append(duplicate)
        with self.assertRaises(analyze.InputError):
            self.report()

    def test_two_terminal_ids_for_one_request_rejected(self):
        duplicate = copy.deepcopy(self.data["terminals"][0])
        duplicate["event_id"] = builder.uid(999)
        self.data["terminals"].append(duplicate)
        with self.assertRaises(analyze.InputError):
            self.report()

    def test_versions_are_strict_no_downgrade(self):
        for field, value in (("terminal", "2.0"), ("observation", "0.9"), ("ticket", 2)):
            with self.subTest(field=field):
                data = copy.deepcopy(self.data)
                data["protocols"][field] = value
                with self.assertRaises(analyze.InputError):
                    analyze.analyze(data)
        self.data["terminals"][0]["schema_version"] = "2.0"
        with self.assertRaises(analyze.InputError):
            self.report()

    def test_closed_schema_cannot_accept_trace_in_terminal(self):
        self.data["terminals"][0]["trace_id"] = "a" * 32
        with self.assertRaises(analyze.InputError):
            self.report()

    def test_request_keeps_old_revision_when_desired_changes(self):
        r = self.report()
        self.assertEqual(self.row(1, r)["invocation_binding"]["release_revision"], "c" * 64)
        self.assertEqual(self.row(8, r)["invocation_binding"]["release_revision"], "e" * 64)
        self.assertEqual(len(r["revision_groups"]), 3)

    def test_runtime_publication_mismatch_rejected(self):
        self.data["runtime_metadata"][0]["publication_id"] = builder.uid(999)
        with self.assertRaises(analyze.InputError):
            self.report()

    def test_gateway_route_digest_mismatch_rejected(self):
        self.data["gateway_observations"][0]["route_binding_sha256"] = "f" * 64
        with self.assertRaises(analyze.InputError):
            self.report()

    def test_terminal_invocation_mismatch_rejected(self):
        self.data["terminals"][0]["invocation_binding"]["activation_epoch"] = 9
        with self.assertRaises(analyze.InputError):
            self.report()

    def test_nested_stage_durations_never_summed(self):
        r = self.report()
        self.assertEqual(r["stages_inclusive_only"]["higress.ext_auth"]["p50"], 150)
        self.assertIsNone(r["inclusive_stage_sum_ms"])
        self.assertIsNone(r["unattributed_ms"])

    def test_nonstream_client_ttft_is_unavailable(self):
        self.data["requests"][0].update(stream=False, frames=[], visible_tokens=None, tokenizer_sha256=None)
        self.assertIsNone(self.row(1)["client_visible_ttft_ms"])
        self.assertEqual(self.row(1)["client_e2e_ms"], 200)

    def test_fragmented_crlf_sse_timestamp_uses_complete_event(self):
        parsed = analyze.sse_metrics([
            builder.wire(10, raw='data: {"choices":[{"delta":{"content":"x"}}]}\r'),
            builder.wire(20, raw="\n\r\n"),
            builder.wire(30, raw="data: [DONE]\r\n\r\n")])
        self.assertEqual(parsed["content_times"], [20])
        self.assertTrue(parsed["done"])

    def test_sse_multiple_events_and_multiline_json(self):
        parsed = analyze.sse_metrics([builder.wire(20, raw=
            ': hi\n\ndata: {"choices":\ndata: [{"delta":{"content":"x"}}]}\n\ndata: [DONE]\n\n')])
        self.assertEqual(parsed["content_times"], [20])

    def test_reported_timing_and_tpot_count_must_match(self):
        self.data["observations"][0]["timing"].update(
            tpot_ms=80 / 3, tpot_scope="visible_proxy", token_sample_count=2)
        self.data["observations"][0]["timing"]["missing_fields"].remove("tpot_ms")
        with self.assertRaises(analyze.InputError):
            self.report()

    def test_outside_window_nonfinite_and_bool_counts_rejected(self):
        for change in ("window", "nan", "count"):
            with self.subTest(change=change):
                data = copy.deepcopy(self.data)
                if change == "window":
                    data["window"]["end_ms"] = 50
                elif change == "nan":
                    data["observations"][0]["timing"]["tpot_ms"] = float("nan")
                else:
                    data["requests"][0]["visible_tokens"] = True
                with self.assertRaises(analyze.InputError):
                    analyze.analyze(data)

    def test_missing_client_record_not_extrapolated_as_full_coverage(self):
        self.data["observations"].pop()
        with self.assertRaises(analyze.InputError):
            self.report()

    def test_snapshot_conservation_and_usage_total_checked(self):
        for field in ("budget", "usage"):
            with self.subTest(field=field):
                data = copy.deepcopy(self.data)
                if field == "budget":
                    data["terminals"][0]["budget_accounting"]["token"]["released"] = "999"
                else:
                    data["terminals"][0]["usage"]["total_tokens"] = 99
                with self.assertRaises(analyze.InputError):
                    analyze.analyze(data)

    def test_empty_run_denominators_not_fake_zero_ratios(self):
        for key in ("requests", "observations", "terminals", "runtime_metadata", "gateway_observations"):
            self.data[key] = []
        r = self.report()
        self.assertIsNone(r["rates"]["rejection_over_sent"])
        self.assertIsNone(r["usage"]["total_tokens"]["known_sum"])
        self.assertEqual(r["counts"]["sent"], 0)

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / "bad.json"
            path.write_text('{"synthetic":true,"synthetic":false}', encoding="utf-8")
            with self.assertRaises(analyze.InputError):
                analyze.load_json(path)

    def test_schema_snapshots_match_provenance_and_are_local(self):
        provenance = analyze.load_json(HERE / "contracts/provenance.json")
        import hashlib
        for name, item in provenance["files"].items():
            self.assertEqual(hashlib.sha256((HERE / "contracts" / name).read_bytes()).hexdigest(), item["sha256"])

    def test_analysis_opens_no_network_socket(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            self.assertEqual(self.report()["counts"]["sent"], 9)

    def test_expected_input_hash_matches_fixed_fixture_bytes(self):
        import hashlib
        expected = analyze.load_json(HERE / "fixtures/expected-report.json")
        self.assertEqual(expected["input_sha256"],
            hashlib.sha256((HERE / "fixtures/synthetic.json").read_bytes()).hexdigest())

    def test_report_format_and_fixed_expected_output(self):
        expected = analyze.load_json(HERE / "fixtures/expected-report.json")
        schema = analyze.load_json(HERE / "report.schema.json")
        self.assertTrue(analyze.Draft202012Validator(schema).is_valid(expected))
        actual = self.report()
        expected.pop("input_sha256")
        self.assertEqual(actual, expected)

    def test_money_currencies_are_not_added_together(self):
        rid = self.data["requests"][7]["request_id"]
        terminal = next(t for t in self.data["terminals"] if t["request_id"] == rid)
        obs = next(o for o in self.data["observations"] if o["request_id"] == rid)
        for item in (terminal["invocation_binding"], obs["invocation_binding"],
                     terminal["reservation_plan"], terminal["budget_accounting"]):
            item["price_snapshot_id"] = builder.uid(777)
            item["price_version"] = "synthetic-price-v2"
        terminal["reservation_plan"]["currency"] = "ABC"
        terminal["budget_accounting"]["currency"] = "ABC"
        groups = self.report()["diagnostic_reconciliation"]["money_by_frozen_price"]
        self.assertEqual({g["currency"] for g in groups}, {"TST", "ABC"})
        self.assertEqual(len(groups), 2)

    def test_source_and_actual_token_accounting_mismatches_rejected(self):
        for field in ("source", "token_actual"):
            with self.subTest(field=field):
                data = copy.deepcopy(self.data)
                if field == "source":
                    data["terminals"][0]["reservation_plan"]["source_id"] = builder.uid(778)
                else:
                    data["terminals"][0]["budget_accounting"]["token_actual"] = "999"
                with self.assertRaises(analyze.InputError):
                    analyze.analyze(data)

    def test_single_client_clock_scope_accepts_uniform_relabel(self):
        for request in self.data["requests"]:
            request["clock_scope"] = "one-imported-client-clock"
        for observation in self.data["observations"]:
            observation["clock_scope"] = "one-imported-client-clock"
        report = self.report()
        self.assertEqual(report["counts"]["sent"], 9)
        self.assertEqual(report["rates"]["success_rps"], 4)
        self.assertEqual(self.row(1, report)["client_visible_ttft_ms"], 100)

    def test_mixed_client_clock_scopes_rejected_for_all_sent_states(self):
        # Include a success, a rejection and an unfinished request in the guard.
        for index in (0, 2, 8):
            with self.subTest(index=index):
                data = copy.deepcopy(self.data)
                request = data["requests"][index]
                request["clock_scope"] = "other-client-monotonic"
                client = next(o for o in data["observations"]
                              if o["producer"] == "client" and
                              o["request_id"] == request["request_id"])
                client["clock_scope"] = request["clock_scope"]
                with self.assertRaisesRegex(analyze.InputError, "mixed client clock scopes"):
                    analyze.analyze(data)

    def test_request_client_observation_clock_mismatch_rejected(self):
        for change_request in (True, False):
            with self.subTest(change_request=change_request):
                data = copy.deepcopy(self.data)
                record = data["requests"][0] if change_request else data["observations"][0]
                record["clock_scope"] = "mismatched-client-clock"
                with self.assertRaisesRegex(analyze.InputError, "client coverage/clock mismatch"):
                    analyze.analyze(data)

    def test_server_clock_scope_keeps_own_duration_legal(self):
        server = copy.deepcopy(self.data["observations"][0])
        server.update(observation_id=builder.uid(901), producer="go",
                      clock_scope="independent-go-monotonic", span_id="d" * 16,
                      stages=[{"name": "go.key_validate", "duration_ms": 7,
                               "provenance": "measured"}])
        self.data["observations"].append(server)
        report = self.report()
        self.assertEqual(report["stages_inclusive_only"]["go.key_validate"]["p50"], 7)
        self.assertEqual(self.row(1, report)["server_first_chunk_ms"], 60)
        self.assertEqual(self.row(1, report)["client_visible_ttft_ms"], 100)
        self.assertEqual(report["rates"]["success_rps"], 4)

    def test_engine_clock_scope_uses_own_origin_for_tpot(self):
        request = self.data["requests"][0]
        request["engine_clock_scope"] = "independent-engine-monotonic"
        request["engine_token_times_ms"] = [
            timestamp + 1000000 for timestamp in request["engine_token_times_ms"]]
        engine = copy.deepcopy(self.data["observations"][0])
        engine.update(observation_id=builder.uid(902), producer="engine",
                      clock_scope=request["engine_clock_scope"], span_id="e" * 16,
                      stages=[{"name": "engine.decode", "duration_ms": 180,
                               "provenance": "measured"}])
        self.data["observations"].append(engine)
        report = self.report()
        self.assertEqual(self.row(1, report)["engine_generated_tpot_ms"], 30)
        self.assertEqual(self.row(1, report)["client_visible_ttft_ms"], 100)
        self.assertEqual(report["stages_inclusive_only"]["engine.decode"]["p50"], 180)
        self.assertEqual(report["rates"]["success_rps"], 4)

    def test_invalid_client_clock_scopes_rejected(self):
        for value in ("", None):
            with self.subTest(scope=value):
                data = copy.deepcopy(self.data)
                data["requests"][0]["clock_scope"] = value
                data["observations"][0]["clock_scope"] = value
                with self.assertRaises(analyze.InputError):
                    analyze.analyze(data)

    def test_cli_mixed_clock_scopes_exit_two_without_new_or_changed_report(self):
        data = copy.deepcopy(self.data)
        data["requests"][0]["clock_scope"] = "SYNTHETIC_SCOPE_SENTINEL"
        data["observations"][0]["clock_scope"] = "SYNTHETIC_SCOPE_SENTINEL"
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            source = Path(directory) / "mixed.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            output = Path(directory) / "report.json"
            for existing in (False, True):
                with self.subTest(existing_report=existing):
                    if existing:
                        output.write_bytes(b"unchanged-existing-report")
                    proc = subprocess.run([sys.executable, str(HERE / "analyze.py"),
                        "--input", str(source), "--output", str(output)],
                        capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 2)
                    self.assertEqual(proc.stdout, "")
                    self.assertNotIn("SYNTHETIC_SCOPE_SENTINEL", proc.stdout + proc.stderr)
                    if existing:
                        self.assertEqual(output.read_bytes(), b"unchanged-existing-report")
                    else:
                        self.assertFalse(output.exists())

    def test_cli_reports_synthetic_and_redacts_invalid_payload(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            output = Path(directory) / "report.json"
            proc = subprocess.run([sys.executable, str(HERE / "analyze.py"), "--input",
                str(HERE / "fixtures/synthetic.json"), "--output", str(output)],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("synthetic", proc.stdout)
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["synthetic"])
            bad = Path(directory) / "bad.json"
            data = copy.deepcopy(self.data)
            data["secret-value-must-not-echo"] = "SENSITIVE_SENTINEL"
            bad.write_text(json.dumps(data), encoding="utf-8")
            output.unlink()
            proc = subprocess.run([sys.executable, str(HERE / "analyze.py"), "--input",
                str(bad), "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn("SENSITIVE_SENTINEL", proc.stdout + proc.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
