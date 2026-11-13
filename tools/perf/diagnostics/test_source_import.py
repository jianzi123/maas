"""Synthetic adapter regressions; real QA archive is consumed separately, not checked into fixtures."""

import copy, hashlib, json, subprocess, sys, tempfile, unittest, zipfile
from pathlib import Path

if __package__:
    from .source_import import (
        build_report,
        DiagnosticError,
        PRIMARY,
        RETEST,
        SUMMARY,
        WITNESS,
    )
else:
    from source_import import (
        build_report,
        DiagnosticError,
        PRIMARY,
        RETEST,
        SUMMARY,
        WITNESS,
    )
from analyze import InputError

HERE = Path(__file__).resolve().parent
DATA = json.loads((HERE.parent / "fixtures/synthetic.json").read_text(encoding="utf-8"))
COMMIT = "d2d7869fe16b8968d6ca5b00a63560c322b84dc1"


def row(index=0, passed=True):
    t = copy.deepcopy(DATA["terminals"][index])
    budget = t["budget_accounting"]
    receipt = {
        "schema_version": "0.1-draft.1",
        "record_type": "receipt",
        "diagnostic_id": "00000000-0000-4000-8000-000000000701",
        "request_id": t["request_id"],
        "owner_instance_id": t["owner_instance_id"],
        "owner_fence": t["owner_fence"],
        "sequence": 1,
        "observed_at": t["observed_at"],
        "snapshot_sha256": "a" * 64,
        "invocation_binding": t["invocation_binding"],
        "authority": "diagnostic_only",
        "usage": {
            k: t["usage"][k]
            for k in (
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "input_cached_tokens",
                "reasoning_tokens",
            )
        },
        "cause": None,
    }
    if all(value is None for value in receipt["usage"].values()):
        receipt["usage"] = {
            "input_tokens": 12,
            "output_tokens": 7,
            "total_tokens": 19,
            "input_cached_tokens": 4,
            "reasoning_tokens": 3,
        }
    termination = copy.deepcopy(receipt)
    termination.update(
        record_type="termination",
        sequence=2,
        diagnostic_id="00000000-0000-4000-8000-000000000702",
        usage=None,
        cause="normal_completion" if t["result"] == "succeeded" else "eof",
    )
    return {
        "attempts": 1,
        "case": "sample",
        "diagnostics": [receipt, termination],
        "expected_success": t["result"] == "succeeded",
        "money": {
            "Known": budget["money"]["known_used"],
            "Reserved": "0",
            "Held": budget["money"]["unknown_held"],
        },
        "passed": passed,
        "request_id": t["request_id"],
        "terminal": t,
        "tokens": {
            "Known": budget["token"]["known_used"],
            "Reserved": "0",
            "Held": budget["token"]["unknown_held"],
        },
    }


def make_archive(path, primary=None, retest=None, summary=None, mutate=None):
    primary = [row(0, False)] if primary is None else primary
    retest = [row(1)] if retest is None else retest
    summary = (
        {"product_sha": COMMIT, "observed_utc": "2026-11-13T00:00:00Z"}
        if summary is None
        else summary
    )
    blobs = {
        PRIMARY: json.dumps(primary).encode(),
        RETEST: json.dumps(retest).encode(),
        SUMMARY: json.dumps(summary).encode(),
        WITNESS: b"synthetic fixture only: relay.Forward( ReadDiagnostics( event_json FROM usage_events",
    }
    manifest = {k: hashlib.sha256(v).hexdigest() for k, v in blobs.items()}
    if mutate:
        mutate(blobs, manifest)
    with zipfile.ZipFile(path, "w") as z:
        for k, v in blobs.items():
            z.writestr(k, v)
        z.writestr("manifest-sha256.json", json.dumps(manifest))
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SourceImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / "source.zip"

    def report(self, **kwargs):
        h = make_archive(self.archive, **kwargs)
        return build_report(self.archive, h, COMMIT)

    def test_partial_report_preserves_unknown_roster_and_identity(self):
        r = self.report()
        self.assertEqual(r["source_counts"]["observed_terminal_records"], 2)
        self.assertIsNone(r["source_counts"]["complete_client_sent"])
        self.assertIsNone(r["metric_report"])
        self.assertFalse(r["d1_overall_complete"])
        self.assertFalse(r["e1_executed"])
        self.assertTrue(
            all(
                row["trace_id"] is None and row["instance_boot_id"] is None
                for row in r["source_rows"]
            )
        )

    def test_oracle_failure_not_rewritten_as_terminal_failure(self):
        r = self.report()
        self.assertEqual(r["source_counts"]["source_test_oracle_failed"], 1)
        self.assertEqual(r["source_rows"][0]["terminal_result"], "succeeded")
        self.assertEqual(r["source_counts"]["source_case_labels"], 1)

    def test_old_first_chunk_is_not_promoted_to_first_content(self):
        r = self.report()
        first = r["source_rows"][0]
        self.assertEqual(first["go_legacy_first_chunk_ms"], 60)
        self.assertIsNone(first["go_first_content_write_ms"])
        self.assertIsNone(first["client_visible_ttft_ms"])
        self.assertEqual(r["timeline"]["intervals"], [])

    def test_usage_only_zero_and_unknown_are_distinct(self):
        r = self.report(primary=[row(1), row(3)], retest=[])
        self.assertEqual(r["source_rows"][0]["actual_usage"]["total_tokens"], 0)
        self.assertIsNone(r["source_rows"][1]["actual_usage"]["total_tokens"])
        self.assertEqual(r["source_rows"][1]["current_token_ledger"]["Held"], "140")

    def test_current_reserved_is_not_original_reservation(self):
        r = self.report()
        self.assertEqual(r["source_rows"][0]["current_token_ledger"]["Reserved"], "0")
        self.assertEqual(r["source_rows"][0]["terminal_original_token_reserved"], "140")

    def test_diagnostic_progress_not_summed_into_actual(self):
        primary = row()
        d = copy.deepcopy(primary["diagnostics"][0])
        d["diagnostic_id"] = "00000000-0000-4000-8000-000000000703"
        d["sequence"] = 2
        d["usage"].update(
            input_tokens=20,
            output_tokens=10,
            total_tokens=30,
            input_cached_tokens=0,
            reasoning_tokens=0,
        )
        primary["diagnostics"][-1]["sequence"] = 3
        primary["diagnostics"].insert(1, d)
        r = self.report(primary=[primary], retest=[])
        self.assertEqual(len(r["source_rows"][0]["receipt_snapshots"]), 2)
        self.assertEqual(
            r["source_rows"][0]["actual_usage"], primary["terminal"]["usage"]
        )

    def test_wrong_archive_hash_rejected(self):
        make_archive(self.archive)
        with self.assertRaises(DiagnosticError):
            build_report(self.archive, "0" * 64, COMMIT)

    def test_wrong_product_commit_rejected(self):
        h = make_archive(self.archive)
        with self.assertRaises(DiagnosticError):
            build_report(self.archive, h, "1" * 40)

    def test_member_hash_mismatch_rejected(self):
        def mutate(blobs, manifest):
            blobs[PRIMARY] += b" "

        h = make_archive(self.archive, mutate=mutate)
        with self.assertRaises(DiagnosticError):
            build_report(self.archive, h, COMMIT)

    def test_request_mismatch_rejected(self):
        p = row()
        p["request_id"] = "00000000-0000-4000-8000-000000000999"
        with self.assertRaises(DiagnosticError):
            self.report(primary=[p], retest=[])

    def test_diagnostic_identity_binding_version_and_authority(self):
        for field, value in [
            ("request_id", "other"),
            ("schema_version", "1.0"),
            ("authority", "final"),
            ("owner_fence", True),
            ("invocation_binding", None),
        ]:
            p = row()
            p["diagnostics"][0][field] = value
            with self.subTest(field=field):
                with self.assertRaises((DiagnosticError, InputError)):
                    self.report(primary=[p], retest=[])

    def test_ledger_mismatch_rejected(self):
        p = row()
        p["tokens"]["Known"] = "999"
        with self.assertRaises(DiagnosticError):
            self.report(primary=[p], retest=[])

    def test_duplicate_identical_dedup_and_conflict_rejected(self):
        p = row()
        r = self.report(primary=[p, p], retest=[])
        self.assertEqual(r["source_counts"]["observed_terminal_records"], 1)
        self.assertEqual(r["source_counts"]["duplicates_ignored"], 1)
        q = copy.deepcopy(p)
        q["passed"] = False
        with self.assertRaises(DiagnosticError):
            self.report(primary=[p, q], retest=[])

    def test_timeout_cancel_without_recovery_proof_stays_unknown(self):
        p = row(3)
        p["terminal"]["result"] = "timed_out"
        p["terminal"]["error_code"] = "upstream_timeout"
        p["diagnostics"][-1]["cause"] = "deadline_exceeded"
        r = self.report(primary=[p], retest=[])
        self.assertEqual(r["source_rows"][0]["terminal_result"], "timed_out")
        self.assertEqual(
            r["source_rows"][0]["slot_recovery_state"],
            "unknown_without_independent_observation",
        )
        self.assertEqual(r["recovery_groups"], [])

    def test_no_private_key_or_body_fields_pass_through(self):
        r = self.report()
        encoded = json.dumps(r)
        for field in ('"key_id"', '"reservation_plan"', '"Body"', '"wire"', '"prompt"'):
            self.assertNotIn(field, encoded)

    def test_unknown_source_fields_are_rejected(self):
        p = row()
        p["secret"] = "SYNTHETIC_SECRET"
        with self.assertRaises(DiagnosticError):
            self.report(primary=[p], retest=[])

    def test_multiple_upstream_attempts_rejected(self):
        p = row()
        p["attempts"] = 2
        with self.assertRaises(DiagnosticError):
            self.report(primary=[p], retest=[])

    def test_source_sampling_overhead_never_inferred_from_test_duration(self):
        r = self.report()
        self.assertIsNone(r["source_import"]["source_sampling_overhead_ns"])
        self.assertIsNone(r["observation_window"])
        self.assertIsNone(r["rates"])


class ConsumeCliTests(unittest.TestCase):
    def test_report_and_consumer_overhead_are_distinct_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.zip"
            h = make_archive(archive)
            out = Path(directory) / "out"
            args = [
                sys.executable,
                str(HERE / "consume.py"),
                "--archive",
                str(archive),
                "--expected-archive-sha256",
                h,
                "--expected-source-commit",
                COMMIT,
                "--output-dir",
                str(out),
            ]
            run = subprocess.run(args, capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            overhead = json.loads(
                (out / "consumer-import-overhead.json").read_text(encoding="utf-8")
            )
            self.assertIsNone(report["source_import"]["source_sampling_overhead_ns"])
            self.assertGreater(overhead["consumer_parse_validate_compose_ns"], 0)
            before = (out / "report.json").read_bytes()
            again = subprocess.run(args, capture_output=True, text=True, timeout=15)
            self.assertEqual(again.returncode, 2)
            self.assertEqual((out / "report.json").read_bytes(), before)

    def test_integrity_failure_has_no_report_or_sensitive_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.zip"
            make_archive(archive)
            out = Path(directory) / "out"
            args = [
                sys.executable,
                str(HERE / "consume.py"),
                "--archive",
                str(archive),
                "--expected-archive-sha256",
                "bad-SYNTHETIC_SECRET",
                "--expected-source-commit",
                COMMIT,
                "--output-dir",
                str(out),
            ]
            run = subprocess.run(args, capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 2)
            self.assertFalse(out.exists())
            self.assertNotIn("SYNTHETIC_SECRET", run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
