"""Portable metadata regressions; no synthetic values are performance evidence."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cadence_protocol import make_plan, validate_plan, CONFIG, digest, match_error, write_json
from analyze_kv_cadence import validate_block, analyze


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan("unit-metadata", "a" * 40)

    def test_frozen_denominator(self):
        self.assertEqual(len(self.plan["schedule"]), 108)
        blocks = [b for c in self.plan["schedule"] for b in c["blocks"]]
        self.assertEqual(len(blocks), 1080)
        self.assertEqual(len({b["block_id"] for b in blocks}), 1080)
        self.assertEqual(sum(b["variant"] == "native" for b in blocks), 540)
        self.assertEqual(len({b["pair_id"] for b in blocks}), 540)

    def test_config_cannot_raise_resource_cap(self):
        self.plan["config"]["resource_caps"]["max_requests"] = 9
        with self.assertRaises(ValueError):
            validate_plan(self.plan)

    def test_duplicate_schedule_identity_rejected(self):
        c = self.plan["schedule"][0]
        c["blocks"][1]["block_id"] = c["blocks"][0]["block_id"]
        with self.assertRaises(ValueError):
            validate_plan(self.plan)

    def test_boolean_schedule_is_not_integer(self):
        self.plan["schedule"][0]["blocks"][1]["slot"] = True
        with self.assertRaises(ValueError):
            validate_plan(self.plan)

    def test_source_digest_cannot_be_changed(self):
        self.plan["source_sha256"]["cadence_protocol.py"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source digest mismatch"):
            validate_plan(self.plan)

    def test_nonfinite_matching_tolerance_rejected(self):
        self.plan["config"]["match_tolerance_relative"] = float("nan")
        with self.assertRaises(ValueError):
            validate_plan(self.plan)

    def test_invalid_plan_cli_does_not_import_torch_or_make_success_dir(self):
        cache = Path.cwd() / ".cache" / "cadence-tests"
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as td:
            folder = Path(td).resolve()
            self.assertTrue(folder.is_relative_to(cache.resolve()))
            marker = folder / "torch-imported"
            (folder / "torch.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\nraise RuntimeError('unexpected GPU import')\n")
            self.plan["config"]["blocks_per_cluster_total"] = 20
            path = folder / "invalid.json"
            write_json(path, self.plan)
            destination = folder / "must-not-exist"
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("bench_kv_cadence.py")),
                "--plan", str(path), "--run-id", "R01", "--output", str(destination)],
                env=dict(os.environ, PYTHONPATH=str(folder)), capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("frozen config changed", result.stderr)
            self.assertFalse(marker.exists())
            self.assertFalse(destination.exists())

    def test_missing_runs_stay_in_denominator(self):
        result = analyze(self.plan, Path("nonexistent-cadence-evidence"))
        self.assertEqual(result["block_status_counts"], {"missing": 1080})
        self.assertEqual(result["planned_calls"], 10800)
        self.assertFalse(any(r["complete"] for r in result["triplets"]))


class BlockTests(unittest.TestCase):
    def setUp(self):
        plan = make_plan("unit-metadata", "a" * 40)
        self.cluster = plan["schedule"][0]
        self.block = self.cluster["blocks"][0]
        self.runtime = {"clock_scope": "local-test-only",
                        "targets_ns": {"native": 1000, "mature": 1000}}
        self.cell = {"cell_id": "R01/full/B3"}
        self.row = dict(self.block)
        for k in ("cluster_id", "triplet_id", "run_id", "scope", "batch",
                  "policy", "rotation", "strategy_position"):
            self.row[k] = self.cluster[k]
        self.row.update(status="measured", calls_completed=10,
            clock_scope="local-test-only", runtime_manifest_sha256=digest(self.runtime),
            cell_sha256=digest(self.cell), previous_done_ns=1000, ready_ns=1100,
            submit_ns=2000, enqueue_end_ns=3000, done_ns=5000,
            preparation_ns=100, ready_to_submit_ns=900, wall_ns=3000,
            host_enqueue_ns=1000, wait_ns=2000, thread_cpu_ns=900, event_ns=2500,
            gap_match=match_error(1000, 1000), query_id=self.block["block_id"] + "/query",
            query_begin_ns=1200, query_end_ns=1300)

    def check(self):
        validate_block(self.row, self.block, self.cluster, self.runtime, self.cell, CONFIG)

    def test_valid_measured_identity(self):
        self.check()

    def test_foreign_clock_rejected(self):
        self.row["clock_scope"] = "another-process"
        with self.assertRaisesRegex(ValueError, "foreign clock"):
            self.check()

    def test_matching_error_not_trusted(self):
        self.row["gap_match"]["matched"] = False
        with self.assertRaisesRegex(ValueError, "matching error"):
            self.check()

    def test_wall_accounting_not_trusted(self):
        self.row["wall_ns"] += 1
        with self.assertRaisesRegex(ValueError, "wall accounting"):
            self.check()

    def test_nonfinite_timing_rejected(self):
        self.row["event_ns"] = float("nan")
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            self.check()

    def test_foreign_query_rejected(self):
        self.row["query_id"] = "other-source-query"
        with self.assertRaisesRegex(ValueError, "query identity"):
            self.check()

    def test_missing_cannot_carry_timing(self):
        self.row["status"] = "missing"
        self.row["calls_completed"] = 0
        with self.assertRaisesRegex(ValueError, "carries measurements"):
            self.check()

    def test_valid_missing_is_retained(self):
        self.row = {k: v for k, v in self.row.items() if k in
                    ("block_id", "pair_id", "variant", "slot", "pair", "calls_planned",
                     "cluster_id", "triplet_id", "run_id", "scope", "batch", "policy",
                     "rotation", "strategy_position")}
        self.row.update(status="missing", calls_completed=0, missing_reason="timeout")
        self.check()


if __name__ == "__main__":
    unittest.main()
