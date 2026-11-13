"""Synthetic wiring/negative tests; actual Go export is separate delivery evidence."""

import copy, hashlib, json, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

if __package__:
    from .relay_import import build_report, normalize, SOURCE_PATHS, verify_source_files
    from .validation import DiagnosticError
    from .html_report import render
else:
    from relay_import import build_report, normalize, SOURCE_PATHS, verify_source_files
    from validation import DiagnosticError
    from html_report import render

HERE = Path(__file__).parent
COMMIT = "c7e863b11fb34ee2828c947393444e1e5a9baf08"


def fixture():
    """This is a synthetic record; finite zero is intentional."""
    rid = "00000000-0000-4000-8000-000000000001"
    instance = "00000000-0000-4000-8000-000000000002"
    boot = "00000000-0000-4000-8000-000000000003"
    sample = dict(
        schema_version="maas-go-relay-source-1.0",
        run_id="synthetic-d1",
        request_id=rid,
        instance_id=instance,
        boot_id=boot,
        clock_scope=f"{instance}/{boot}/{rid}",
        source_revision="working-tree-d1",
        publication_id="00000000-0000-4000-8000-000000000004",
        release_revision="a" * 64,
        first_protocol_ms=0,
        first_content_received_ms=4,
        first_content_write_ok_ms=6,
        first_content_flush_attempt_ms=7,
        end_ms=8,
        result="succeeded",
        return_error=False,
    )
    export = dict(
        schema_version="maas-go-relay-export-1.0",
        evidence_kind="controlled_go_http_mysql",
        export_id="00000000-0000-4000-8000-000000000005",
        instance_fixture=False,
        missing_components=[
            "real_higress",
            "worker",
            "gpu",
            "client_receive",
            "cross_clock_calibration",
        ],
        missing_identity=["trace_id", "experiment_ref", "cell_id"],
        run_id="synthetic-d1",
        samples=[sample],
    )
    manifest = dict(
        source_commit_at_manifest=COMMIT,
        source_worktree_dirty=False,
        source_sha256={p: "a" * 64 for p in SOURCE_PATHS},
        raw_file="artifacts/go-relay-d1.json",
        raw_sha256="b" * 64,
        collection_command="bash scripts/collect-relay-d1.sh",
        case_to_request={"content": rid},
        dropped_case="full_sampler (one additional execution, no exported summary)",
        component_scope="Go Relay + temporary MySQL + controlled HTTP upstream; gateway proofs are test adapters",
        unknown=[
            "client receive",
            "real Higress",
            "Worker",
            "GPU",
            "trace_id",
            "experiment_ref",
            "cell_id",
            "cross-clock calibration",
        ],
        consumer_commit="8420aaf956b7d44d52c2bbe52c9d20d15fcdb781",
        direct_diagnostic_sidecar_import_ready=False,
    )
    return export, manifest


class RelayImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.export, self.manifest = fixture()

    def files(self):
        raw = self.root / "raw.json"
        mf = self.root / "manifest.json"
        raw.write_text(json.dumps(self.export, allow_nan=True), encoding="utf-8")
        self.manifest["raw_sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
        mf.write_text(json.dumps(self.manifest), encoding="utf-8")
        return raw, mf, hashlib.sha256(mf.read_bytes()).hexdigest()

    def report(self):
        a, b, h = self.files()
        return build_report(a, b, h, COMMIT)

    def reject(self):
        with self.assertRaises((DiagnosticError, ValueError)):
            self.report()

    def test_four_milestones_and_forward_origin(self):
        r = self.report()
        self.assertEqual(r["source_rows"][0]["content_received_to_write_ok_ms"], 2)
        self.assertIsNone(r["request_diagnostics"][0]["go_server_first_chunk_ms"])
        self.assertEqual(
            r["request_diagnostics"][0]["go_forward_first_content_received_ms"], 4
        )

    def test_empty_and_usage_only_never_become_content(self):
        for case in ("empty", "usage_only"):
            self.manifest["case_to_request"] = {
                case: self.export["samples"][0]["request_id"]
            }
            for field in (
                "first_content_received_ms",
                "first_content_write_ok_ms",
                "first_content_flush_attempt_ms",
            ):
                self.export["samples"][0][field] = None
            r = self.report()
            self.assertEqual(r["source_rows"][0]["first_protocol_ms"], 0)
            self.assertIsNone(r["source_rows"][0]["first_content_received_ms"])

    def test_write_failed_flush_attempt_is_legal(self):
        s = self.export["samples"][0]
        s.update(first_content_write_ok_ms=None, result="cancelled", return_error=True)
        r = self.report()
        self.assertIsNone(r["source_rows"][0]["content_received_to_write_ok_ms"])
        self.assertEqual(r["source_rows"][0]["first_content_flush_attempt_ms"], 7)
        self.assertEqual(len(r["recovery_missing_request_ids"]), 1)

    def test_failure_cancel_eof_timeout_not_dropped_from_population(self):
        for result in ("failed", "cancelled", "interrupted", "timed_out", "unknown"):
            self.export["samples"][0].update(result=result, return_error=True)
            r = self.report()
            self.assertEqual(r["source_counts"]["observed_source_results"], {result: 1})
            self.assertEqual(len(r["recovery_missing_request_ids"]), 1)

    def test_nonfinite_negative_and_boolean_times_rejected(self):
        for value in (float("nan"), float("inf"), -1, True, 1e13):
            self.export["samples"][0]["first_content_received_ms"] = value
            self.reject()

    def test_milestone_ordering_and_parent_presence(self):
        for changes in (
            {"first_content_received_ms": None},
            {"first_protocol_ms": None},
            {"first_content_received_ms": 9},
            {"first_content_write_ok_ms": 3},
            {"first_content_flush_attempt_ms": 5},
            {"end_ms": 6},
        ):
            self.export, self.manifest = fixture()
            self.export["samples"][0].update(changes)
            self.reject()

    def test_request_clock_is_not_a_shared_origin(self):
        self.export["samples"][0]["clock_scope"] = "shared-clock"
        self.reject()

    def test_wrong_boot_identity_is_rejected(self):
        self.export["samples"][0]["boot_id"] = "00000000-0000-4000-8000-000000000099"
        self.reject()

    def test_duplicate_request_or_unmapped_case_rejected(self):
        self.export["samples"].append(copy.deepcopy(self.export["samples"][0]))
        self.reject()
        self.export, self.manifest = fixture()
        self.manifest["case_to_request"][
            "content"
        ] = "00000000-0000-4000-8000-000000000099"
        self.reject()

    def test_run_and_version_must_match(self):
        for field, value in (("run_id", "different"), ("schema_version", "future-2")):
            self.export, self.manifest = fixture()
            self.export["samples"][0][field] = value
            self.reject()

    def test_private_unapproved_fields_rejected_not_echoed(self):
        self.export["samples"][0]["body"] = "SECRET"
        self.reject()

    def test_raw_and_manifest_pins_fail_closed(self):
        a, b, h = self.files()
        with self.assertRaises(DiagnosticError):
            build_report(a, b, "0" * 64, COMMIT)
        a.write_bytes(a.read_bytes() + b" ")
        with self.assertRaises(DiagnosticError):
            build_report(a, b, h, COMMIT)
        with self.assertRaises(DiagnosticError):
            build_report(a, b, h, "0" * 40)

    def test_manifest_cannot_execute_or_expand_source_paths(self):
        self.manifest["source_sha256"]["../../secret"] = "a" * 64
        self.reject()
        self.export, self.manifest = fixture()
        self.manifest["collection_command"] = "malicious"
        self.reject()

    def test_delivery_commit_does_not_overwrite_capture_revision(self):
        r = self.report()
        self.assertEqual(r["source_rows"][0]["source_revision"], "working-tree-d1")
        self.assertFalse(r["source_import"]["capture_commit_attested"])
        self.assertFalse(
            r["source_import"]["source_files_verified_against_delivery_commit"]
        )

    def test_unknown_denominators_usage_and_drop_rate_remain_unknown(self):
        r = self.report()
        for field in ("rates", "goodput", "observation_window", "source_complete_sent"):
            self.assertIsNone(r[field])
        self.assertIsNone(r["source_counts"]["global_sampler_dropped_counter"])
        self.assertEqual(
            r["source_counts"]["source_declared_additional_drop_scenarios"], 1
        )
        self.assertIsNone(r["source_rows"][0]["actual_usage"])
        self.assertIsNone(r["source_rows"][0]["terminal_result"])
        self.assertFalse(r["d1_overall_complete"])
        self.assertFalse(r["e1_executed"])
        self.assertFalse(r["real_execution_enabled"])

    def test_export_coverage_includes_declared_drop_but_not_global_denominator(self):
        r = self.report()
        coverage = r["source_counts"]["source_declared_summary_coverage"]
        self.assertEqual(
            (coverage["known"], coverage["denominator"], coverage["ratio"]), (1, 2, 0.5)
        )
        self.assertIsNone(r["source_counts"]["global_sampler_dropped_counter"])
        self.assertEqual(
            r["source_counts"]["source_milestone_coverage"]["first_protocol_ms"][
                "known"
            ],
            1,
        )

    def test_nonstream_or_no_event_preserves_all_null_milestones(self):
        for field in (
            "first_protocol_ms",
            "first_content_received_ms",
            "first_content_write_ok_ms",
            "first_content_flush_attempt_ms",
        ):
            self.export["samples"][0][field] = None
        r = self.report()
        self.assertEqual(r["source_rows"][0]["end_ms"], 8)
        self.assertIsNone(r["source_rows"][0]["first_protocol_ms"])
        self.assertIsNone(r["source_rows"][0]["client_visible_ttft_ms"])

    def test_omitted_missing_components_cannot_claim_real_path(self):
        self.export["missing_components"].remove("worker")
        self.reject()

    def test_source_file_verification_uses_six_fixed_git_reads(self):
        data = b"source"
        hashes = {p: hashlib.sha256(data).hexdigest() for p in SOURCE_PATHS}
        with patch(verify_source_files.__module__ + ".subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout=data)
            verify_source_files(self.root, COMMIT, hashes)
            self.assertEqual(run.call_count, 6)
            for call in run.call_args_list:
                self.assertEqual(
                    call.args[0][:4], ["git", "-C", str(self.root), "show"]
                )
            run.return_value = subprocess.CompletedProcess([], 0, stdout=b"modified")
            with self.assertRaises(DiagnosticError):
                verify_source_files(self.root, COMMIT, hashes)

    def test_html_distinguishes_go_client_write_and_flush(self):
        html = render(self.report())
        self.assertIn("Go Forward content receive ms", html)
        self.assertIn("flush attempt ms", html)
        self.assertIn("legacy first_chunk使用Received起点", html)
        self.assertNotIn("20条导入终态", html)

    def test_cli_outputs_report_and_cost_but_refuses_overwrite(self):
        a, b, h = self.files()
        out = self.root / "out"
        args = [
            sys.executable,
            str(HERE / "consume_relay.py"),
            "--raw",
            str(a),
            "--manifest",
            str(b),
            "--expected-manifest-sha256",
            h,
            "--expected-source-commit",
            COMMIT,
            "--output-dir",
            str(out),
        ]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        before = {p.name: p.read_bytes() for p in out.iterdir()}
        cost = json.loads(
            (out / "consumer-import-overhead.json").read_text(encoding="utf-8")
        )
        self.assertGreater(cost["consumer_parse_validate_compose_ns"], 0)
        self.assertIsNone(cost["source_sampling_overhead_ns"])
        self.assertEqual(subprocess.run(args, capture_output=True).returncode, 2)
        self.assertEqual(before, {p.name: p.read_bytes() for p in out.iterdir()})

    def test_cli_negative_does_not_publish_success_or_expose_payload(self):
        self.export["samples"][0]["body"] = "SECRET"
        a, b, h = self.files()
        out = self.root / "out"
        r = subprocess.run(
            [
                sys.executable,
                str(HERE / "consume_relay.py"),
                "--raw",
                str(a),
                "--manifest",
                str(b),
                "--expected-manifest-sha256",
                h,
                "--expected-source-commit",
                COMMIT,
                "--output-dir",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 2)
        self.assertFalse(out.exists())
        self.assertNotIn("SECRET", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
