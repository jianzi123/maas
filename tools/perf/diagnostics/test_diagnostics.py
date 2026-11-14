"""Independent interval arithmetic, identity/clock and CLI regression cases."""

from pathlib import Path
import copy, json, subprocess, sys, tempfile, unittest

if __package__:
    from .validation import DiagnosticError, load_json
    from .report import compose, first_data_event
    from .timeline import union
    from .html_report import render
else:
    from validation import DiagnosticError, load_json
    from report import compose, first_data_event
    from timeline import union
    from html_report import render

PERF = Path(__file__).resolve().parents[1]
METRICS = PERF / "fixtures/synthetic.json"
SIDECAR = Path(__file__).with_name("fixtures") / "timeline.synthetic.json"


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.data, self.h = load_json(METRICS)
        self.side, _ = load_json(SIDECAR)

    def report(self):
        return compose(self.data, self.side, self.h)

    def event(self, id):
        return next(e for e in self.side["intervals"] if e["id"] == id)

    def row(self, id, report=None):
        return next(
            r
            for r in (report or self.report())["timeline"]["intervals"]
            if r["id"] == id
        )

    def test_original_denominators_and_usage_are_preserved(self):
        r = self.report()
        base = r["metric_report"]
        self.assertEqual(base["counts"]["sent"], 9)
        self.assertEqual(base["counts"]["rejected"], 1)
        self.assertEqual(base["counts"]["pending"], 1)
        self.assertEqual(base["counts"]["cancelled"], 1)
        self.assertEqual(base["usage"]["total_tokens"]["known_sum"], 41)
        self.assertEqual(
            base["diagnostic_reconciliation"]["unknown_held_not_actual"]["token"], "420"
        )

    def test_three_first_boundaries_do_not_become_one(self):
        row = self.report()["request_diagnostics"][0]
        self.assertEqual(row["client_protocol_data_wait_ms"], 10)
        self.assertEqual(row["client_visible_ttft_ms"], 100)
        self.assertEqual(row["go_server_first_chunk_ms"], 60)
        self.assertIsNone(row["worker_native_ttft_ms"])

    def test_nested_overlap_self_times_and_zero_are_exact(self):
        r = self.report()
        self.assertEqual(self.row("root", r)["exclusive_self_ms"], 5)
        self.assertEqual(self.row("go-span", r)["exclusive_self_ms"], 10)
        self.assertEqual(self.row("worker-span", r)["exclusive_self_ms"], 0)
        kernel = self.row("kernel", r)
        self.assertEqual((kernel["start_ms"], kernel["end_ms"]), (20, 100))
        self.assertEqual(
            (kernel["normalized_start_ms"], kernel["normalized_end_ms"]), (60, 140)
        )
        self.assertEqual(kernel["boot_id"], "gpu-context-boot")
        self.assertEqual(kernel["batch_id"], "gpu-batch0")
        self.assertIsNone(self.row("copy-shared", r)["exclusive_self_ms"])

    def test_union_is_not_inclusive_sum(self):
        self.assertEqual(union([(0, 100), (10, 80), (70, 120), (120, 120)]), 120)
        self.assertEqual(union([(0, 0)]), 0)
        self.assertEqual(union([]), 0)

    def test_longest_observed_chain_excludes_overlapping_collective(self):
        chain = self.report()["timeline"]["observed_dependency_chains"][0]
        self.assertEqual(chain["observed_active_dependency_chain_ms"], 165)
        self.assertEqual(chain["observed_chain_elapsed_ms"], 185)
        self.assertEqual(chain["known_dependency_gaps_ms"], 20)
        self.assertIn("kernel", chain["interval_ids"])
        self.assertNotIn("collective", chain["interval_ids"])

    def test_missing_end_and_missing_entire_layer_remain_unknown(self):
        r = self.report()
        self.assertIsNone(self.row("cancel-missing-end", r)["local_duration_ms"])
        self.assertIsNone(r["timeline"]["model_bottleneck"])
        self.assertIsNone(r["timeline"]["unattributed_ms"])
        self.assertIsNone(r["timeline"]["end_to_end_critical_path_ms"])
        stage = next(x for x in r["coverage_by_stage"] if x["stage"] == "kv.manage")
        self.assertEqual(stage["denominator"], 8)
        self.assertEqual(stage["known_requests"], 0)
        self.assertEqual(stage["missing_requests"], 8)

    def test_original_metric_coverage_is_not_lost_when_intervals_sparse(self):
        stage = next(
            x
            for x in self.report()["coverage_by_stage"]
            if x["stage"] == "client.content"
        )
        self.assertEqual(stage["known_requests"], 1)
        self.assertGreater(stage["existing_metric_only_requests"], 0)
        self.assertGreater(stage["combined_measurement_coverage"], stage["coverage"])

    def test_identity_mismatch_matrix_rejected(self):
        for field, value in [
            ("request_id", "unknown"),
            ("trace_id", "wrong"),
            ("binding_sha256", "0" * 64),
            ("runtime_metadata_ref", "wrong"),
            ("boot_id", "old-boot"),
            ("rank", 1),
            ("batch_id", "wrong"),
        ]:
            with self.subTest(field=field):
                side = copy.deepcopy(self.side)
                next(e for e in side["intervals"] if e["id"] == "kernel")[field] = value
                with self.assertRaises(DiagnosticError):
                    compose(self.data, side, self.h)

    def test_same_rank_wrong_runtime_instance_rejected(self):
        self.side["instances"][-1]["runtime_instance_id"] = "another-worker"
        with self.assertRaises(DiagnosticError):
            self.report()

    def test_batch_revision_mismatch_rejected(self):
        self.side["batches"][0]["binding_sha256"] = "0" * 64
        with self.assertRaises(DiagnosticError):
            self.report()

    def test_run_and_dataset_digest_mismatch_rejected(self):
        for mode in ("run", "digest"):
            side = copy.deepcopy(self.side)
            if mode == "run":
                side["registry"]["replicate"] = 2
            else:
                side["dataset_sha256"] = "1" * 64
            with self.assertRaises(DiagnosticError):
                compose(self.data, side, self.h)

    def test_unmapped_clock_preserves_local_durations_but_blocks_cross_edges(self):
        self.side["mappings"] = []
        r = self.report()
        self.assertEqual(self.row("kernel", r)["local_duration_ms"], 80)
        self.assertIsNone(self.row("root", r)["exclusive_self_ms"])
        self.assertTrue(r["timeline"]["blocked_edges"])
        self.assertTrue(
            all(
                c["observed_active_dependency_chain_ms"] < 165
                for c in r["timeline"]["observed_dependency_chains"]
            )
        )

    def test_real_unverified_clock_declaration_cannot_enable_cross_domain_path(self):
        self.data["synthetic"] = False
        self.side["synthetic"] = False
        self.side["evidence_kind"] = "controlled_export_unverified"
        r = self.report()
        self.assertTrue(r["timeline"]["blocked_edges"])
        self.assertEqual(
            self.row("kernel", r)["analysis_domain"], "synthetic-device-clock"
        )
        self.assertTrue(
            all(
                c["observed_active_dependency_chain_ms"] < 165
                for c in r["timeline"]["observed_dependency_chains"]
            )
        )
        self.assertFalse(r["benchmark_comparable"])

    def test_nonzero_error_mapping_is_not_exact_alignment(self):
        self.side["mappings"][-1]["max_error_ms"] = 5
        r = self.report()
        self.assertEqual(
            self.row("kernel", r)["analysis_domain"], "synthetic-device-clock"
        )
        self.assertEqual(self.row("kernel", r)["calibration"]["max_error_ms"], 5)
        self.assertTrue(r["timeline"]["blocked_edges"])

    def test_calibration_out_of_range_is_not_reused(self):
        self.side["mappings"][-1]["valid_to_ms"] = 10
        r = self.report()
        self.assertIsNone(self.row("kernel", r)["calibration"])
        self.assertEqual(self.row("kernel", r)["local_duration_ms"], 80)

    def test_shifted_local_origin_with_equivalent_mapping_is_invariant(self):
        for e in self.side["intervals"]:
            if e["clock_scope"] == "synthetic-device-clock":
                e["start_ms"] += 100
                if e["end_ms"] is not None:
                    e["end_ms"] += 100
        m = self.side["mappings"][-1]
        m["offset_ms"] -= 100
        m["valid_from_ms"] += 100
        m["valid_to_ms"] += 100
        self.assertEqual(
            self.report()["timeline"]["observed_dependency_chains"][0][
                "observed_active_dependency_chain_ms"
            ],
            165,
        )

    def test_mapping_chain_is_rejected(self):
        self.side["mappings"][0]["target"] = "synthetic-worker-clock"
        with self.assertRaises(DiagnosticError):
            self.report()

    def test_negative_nonfinite_and_reversed_intervals_rejected(self):
        for field, value in [
            ("start_ms", -1),
            ("end_ms", float("nan")),
            ("end_ms", 19),
        ]:
            side = copy.deepcopy(self.side)
            next(e for e in side["intervals"] if e["id"] == "kernel")[field] = value
            with self.assertRaises(DiagnosticError):
                compose(self.data, side, self.h)

    def test_parent_and_dependency_cycles_are_rejected(self):
        self.event("root")["parent_id"] = "go-span"
        with self.assertRaises(DiagnosticError):
            self.report()
        self.event("root")["parent_id"] = None
        self.event("admit")["predecessors"] = ["mysql"]
        with self.assertRaises(DiagnosticError):
            self.report()

    def test_temporal_overlap_cannot_be_a_sequential_dependency(self):
        self.event("collective")["predecessors"] = ["kernel"]
        with self.assertRaises(DiagnosticError):
            self.report()

    def test_parent_must_contain_comparable_child(self):
        self.event("go-span")["end_ms"] = 280
        with self.assertRaises(DiagnosticError):
            self.report()

    def test_cross_request_parent_and_unknown_evidence_rejected(self):
        self.event("cancel-missing-end")["parent_id"] = "go-span"
        with self.assertRaises(DiagnosticError):
            self.report()
        self.event("cancel-missing-end")["parent_id"] = None
        self.event("kernel")["evidence_ref"] = "missing"
        with self.assertRaises(DiagnosticError):
            self.report()

    def test_shared_batch_cannot_be_declared_exclusive_task(self):
        self.event("copy-shared")["segment_kind"] = "activity"
        with self.assertRaises(DiagnosticError):
            self.report()

    def test_inclusive_parent_cannot_be_used_as_dependency_task(self):
        self.event("prepare")["predecessors"] = ["go-span"]
        with self.assertRaises(DiagnosticError):
            self.report()

    def test_open_dependency_endpoint_is_a_gap_not_zero(self):
        self.event("kernel")["end_ms"] = None
        r = self.report()
        self.assertIsNone(self.row("kernel", r)["local_duration_ms"])
        self.assertTrue(
            any(
                e["from"] == "kernel" and e["reason"] == "missing_end"
                for e in r["timeline"]["blocked_edges"]
            )
        )

    def test_external_api_internals_are_unknown_not_reported_as_gpu(self):
        self.side["manifest"]["source_type"] = "external_api"
        with self.assertRaises(DiagnosticError):
            self.report()
        removed = {e["id"] for e in self.side["intervals"] if e["rank"] is not None}
        self.side["intervals"] = [
            e for e in self.side["intervals"] if e["id"] not in removed
        ]
        for e in self.side["intervals"]:
            e["predecessors"] = [p for p in e["predecessors"] if p not in removed]
        r = self.report()
        provider = next(
            x for x in r["coverage_by_stage"] if x["stage"] == "provider.internal"
        )
        self.assertEqual(provider["known_requests"], 0)
        self.assertEqual(provider["denominator"], 8)
        gpu = next(x for x in r["coverage_by_stage"] if x["stage"] == "gpu.kernel")
        self.assertEqual(gpu["denominator"], 0)
        self.assertIsNone(gpu["coverage"])

    def test_missing_manifest_policy_never_enables_real_run_or_comparison(self):
        r = self.report()
        self.assertIn("policy.confirmed_slo", r["manifest_missing"])
        self.assertFalse(r["real_execution_enabled"])
        self.assertFalse(r["benchmark_comparable"])

    def test_client_interval_conflicting_with_metric_is_rejected(self):
        self.event("content")["end_ms"] = 10
        with self.assertRaises(DiagnosticError):
            self.report()

    def test_fragmented_crlf_first_protocol_event_uses_complete_event(self):
        frames = [
            {"at_ms": 1, "wire": 'data: {"x":1}\r'},
            {"at_ms": 3, "wire": "\n\r"},
            {"at_ms": 5, "wire": "\n"},
        ]
        self.assertEqual(first_data_event(frames), 5)

    def test_empty_intervals_produce_gap_report_not_false_zero_bottleneck(self):
        self.side["intervals"] = []
        r = self.report()
        self.assertEqual(r["timeline"]["observed_dependency_chains"], [])
        self.assertTrue(r["collection_gaps"])
        self.assertIsNone(r["timeline"]["model_bottleneck"])

    def test_report_does_not_include_SSE_prompt_or_credential_body(self):
        r = self.report()
        encoded = json.dumps(r, ensure_ascii=False)
        self.assertNotIn('"frames"', encoded)
        self.assertNotIn('"wire"', encoded)
        self.assertNotIn("data: ", encoded)

    def test_timeout_cancel_and_unrecovered_denominators(self):
        terminal = next(t for t in self.data["terminals"] if t["result"] == "failed")
        terminal["result"] = "timed_out"
        terminal["error_code"] = "upstream_timeout"
        for o in self.data["observations"]:
            if o["request_id"] == terminal["request_id"]:
                o["outcome"] = "error"
        result = self.report()
        self.assertEqual(result["metric_report"]["counts"]["timed_out"], 1)
        self.assertEqual(result["metric_report"]["counts"]["sent"], 9)
        self.assertEqual(result["metric_report"]["counts"]["cancelled"], 1)
        self.assertEqual(result["recovery_groups"][0]["summary"]["unrecovered"], 1)

    def test_recovery_reuses_independent_observer_math_without_refund(self):
        result = self.report()
        group = result["recovery_groups"][0]["summary"]
        self.assertEqual(group["right_censor_durations_ms"], [90])
        self.assertEqual(group["actual_stop_unknown"], 1)
        self.assertEqual(
            result["metric_report"]["diagnostic_reconciliation"][
                "unknown_held_not_actual"
            ]["token"],
            "420",
        )
        self.assertTrue(result["recovery_missing_request_ids"])

    def test_invalid_recovery_order_is_rejected(self):
        row = self.side["recovery_observations"][0]
        row["release_ms"] = 20
        with self.assertRaises(ValueError):
            self.report()

    def test_manifest_known_version_must_match_selected_runtime(self):
        self.side["manifest"]["runtime"]["framework_commit"] = "wrong-engine"
        with self.assertRaises(DiagnosticError):
            self.report()

    def test_conflicting_evidence_hash_cannot_be_hidden_under_new_id(self):
        e = copy.deepcopy(self.side["evidence"][0])
        e["id"] = "another"
        e["sha256"] = "0" * 64
        self.side["evidence"].append(e)
        with self.assertRaises(DiagnosticError):
            self.report()

    def test_html_escapes_imported_values(self):
        r = self.report()
        r["evidence_kind"] = "<script>bad()</script>"
        page = render(r)
        self.assertNotIn("<script>bad", page)
        self.assertIn("&lt;script&gt;", page)

    def test_duplicate_json_and_nan_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "bad.json"
            for content in ('{"x":1,"x":2}', '{"x":NaN}'):
                p.write_text(content, encoding="utf-8")
                with self.assertRaises(DiagnosticError):
                    load_json(p)


class CliTests(unittest.TestCase):
    def command(self, timeline, output):
        return [
            sys.executable,
            str(Path(__file__).with_name("run.py")),
            "--metrics-input",
            str(METRICS),
            "--timeline-input",
            str(timeline),
            "--output-dir",
            str(output),
        ]

    def test_json_html_and_existing_report_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            first = subprocess.run(
                self.command(SIDECAR, output),
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            before = (output / "report.json").read_bytes()
            self.assertTrue((output / "report.html").exists())
            again = subprocess.run(
                self.command(SIDECAR, output),
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(again.returncode, 2)
            self.assertEqual((output / "report.json").read_bytes(), before)

    def test_failed_identity_creates_no_report_and_echoes_no_sensitive_sentinel(self):
        with tempfile.TemporaryDirectory() as directory:
            side = json.loads(SIDECAR.read_text(encoding="utf-8"))
            side["intervals"][0]["trace_id"] = "PRIVATE_SENTINEL_X"
            p = Path(directory) / "side.json"
            p.write_text(json.dumps(side), encoding="utf-8")
            output = Path(directory) / "out"
            result = subprocess.run(
                self.command(p, output), capture_output=True, text=True, timeout=15
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())
            self.assertNotIn("PRIVATE_SENTINEL_X", result.stdout + result.stderr)

    def test_protocol_version_mismatch_fails_before_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics = json.loads(METRICS.read_text(encoding="utf-8"))
            metrics["protocols"]["ticket"] = 2
            p = Path(directory) / "metrics.json"
            p.write_text(json.dumps(metrics), encoding="utf-8")
            output = Path(directory) / "out"
            args = self.command(SIDECAR, output)
            args[args.index("--metrics-input") + 1] = str(p)
            result = subprocess.run(args, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
