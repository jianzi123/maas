"""Behavioral regressions with independent mathematical/state/fault oracles."""

import itertools
from pathlib import Path
import random
import shutil
import unittest
import uuid
from contextlib import closing
import numpy as np

if __package__:
    from . import (
        attention_lab as a,
        layout_lab as g,
        transforms_lab as t,
        distributed_lab as d,
    )
    from . import (
        kv_lab as k,
        scheduler_lab as s,
        statistics_lab as st,
        durable_lab as db,
    )
else:
    import attention_lab as a, layout_lab as g, transforms_lab as t, distributed_lab as d
    import kv_lab as k, scheduler_lab as s, statistics_lab as st, durable_lab as db


class AttentionTests(unittest.TestCase):
    def test_worked_online_row(self):
        out = a.demo()
        np.testing.assert_allclose(
            out["worked_row"], [2 / 3, 5 / 6], rtol=0, atol=1e-14
        )
        self.assertTrue(out["all_masked_zero"])

    def test_partitions_masks_gqa_and_extreme_scores(self):
        rng = np.random.default_rng(2)
        for scale in [1, 100]:
            q = rng.normal(size=(4, 3, 7)) * scale
            kk = rng.normal(size=(2, 11, 7))
            v = rng.normal(size=kk.shape)
            mask = a.suffix_mask(3, 11)
            mask[0] = False
            for block in [1, 2, 5, 32]:
                np.testing.assert_allclose(
                    a.streaming(q, kk, v, mask, block),
                    a.dense(q, kk, v, mask),
                    rtol=1e-12,
                    atol=1e-12,
                )

    def test_merge_order_and_empty(self):
        scores = np.array([1000.0, 1001.0, 999.0])
        v = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        parts = [
            a.block_state(scores[i : i + 1], v[i : i + 1], [True]) for i in range(3)
        ]
        expected = (
            np.exp(scores - scores.max()) @ v / np.exp(scores - scores.max()).sum()
        )
        for order in itertools.permutations(parts):
            result = a.empty_state(2)
            for part in order:
                result = a.merge(result, part)
            np.testing.assert_allclose(a.finish(result), expected, atol=1e-13)
        np.testing.assert_array_equal(a.finish(a.empty_state(2)), [0, 0])

    def test_paged_gather_noncontiguous_order(self):
        x = np.arange(5 * 2 * 3 * 2).reshape(5, 2, 3, 2)
        expected = np.concatenate((x[4], x[1], x[3]), axis=1)[:, :7]
        np.testing.assert_array_equal(a.gather_pages(x, [4, 1, 3], 7), expected)
        for table, length in [([4], 7), ([5], 1), ([-1], 1)]:
            with self.assertRaises(ValueError):
                a.gather_pages(x, table, length)

    def test_explicit_gqa_head_mapping(self):
        q = np.zeros((4, 1, 1))
        kk = np.zeros((2, 2, 1))
        v = np.array([[[10.0], [10.0]], [[20.0], [20.0]]])
        expected = np.array([[[10.0]], [[10.0]], [[20.0]], [[20.0]]])
        for f in [a.dense, a.streaming]:
            np.testing.assert_array_equal(f(q, kk, v, [[True, True]]), expected)

    def test_suffix_mask(self):
        np.testing.assert_array_equal(
            a.suffix_mask(2, 5), [[1, 1, 1, 1, 0], [1, 1, 1, 1, 1]]
        )
        with self.assertRaises(ValueError):
            a.suffix_mask(6, 5)

    def test_nonfinite_and_overflow_fail(self):
        for bad in [np.nan, np.inf, -np.inf]:
            with self.assertRaises(ValueError):
                a.dense(
                    np.full((1, 1, 2), bad),
                    np.ones((1, 1, 2)),
                    np.ones((1, 1, 2)),
                    [[True]],
                )
        with np.errstate(over="ignore", invalid="ignore"):
            for f in [a.dense, a.streaming]:
                with self.assertRaises(ValueError):
                    f(
                        np.full((1, 1, 2), 1e300),
                        np.full((1, 1, 2), 1e300),
                        np.ones((1, 1, 2)),
                        [[True]],
                    )


class LayoutTests(unittest.TestCase):
    def test_tiled_tails_and_strides(self):
        rng = np.random.default_rng(3)
        for m, n, kk in [(37, 53, 29), (1, 3, 5), (9, 1, 17), (5, 7, 0)]:
            x = rng.normal(size=(m, kk * 2))[:, ::2]
            w = rng.normal(size=(kk * 2, n))[::2]
            np.testing.assert_allclose(
                g.tiled_gemm(x, w, (8, 7, 3)), x @ w, atol=1e-12, rtol=1e-12
            )

    def test_address_models(self):
        self.assertEqual(g.sectors([i * 4 for i in range(32)]), 4)
        self.assertEqual(g.sectors([4 + i * 4 for i in range(32)]), 5)
        self.assertEqual(g.bank_conflict_degree([i * 32 for i in range(32)]), 32)
        self.assertEqual(g.bank_conflict_degree([i * 33 for i in range(32)]), 1)
        self.assertEqual(g.bank_conflict_degree([0] * 32), 1)

    def test_register_bound_and_intensity(self):
        self.assertEqual(g.register_bound(65536, 2048, 256, 64, 32)["blocks"], 4)
        self.assertEqual(
            g.register_bound(65536, 2048, 256, 64, 32)["occupancy_upper_bound"], 0.5
        )
        self.assertAlmostEqual(g.intensity(1, 4096, 4096), 0.4997559785, places=8)

    def test_invalid_gemm(self):
        for x, w in [
            (np.ones((2, 3)), np.ones((4, 2))),
            (np.full((2, 2), np.nan), np.ones((2, 2))),
        ]:
            with self.assertRaises(ValueError):
                g.tiled_gemm(x, w)


class TransformTests(unittest.TestCase):
    def test_rope_roundtrip_norm_and_shared_position(self):
        rng = np.random.default_rng(4)
        x = rng.normal(size=(5, 8))
        y = rng.normal(size=(5, 8))
        pos = np.arange(11, 16)
        rx, ry = t.rope(x, pos), t.rope(y, pos)
        np.testing.assert_allclose(t.rope(rx, pos, inverse=True), x, atol=1e-12)
        np.testing.assert_allclose(
            (rx * ry).sum(axis=1), (x * y).sum(axis=1), atol=1e-12
        )

    def test_residual_norm_two_outputs(self):
        r, y = t.rms_residual([[2.0, 3.0]], [[1.0, 1.0]], [1.0, 1.0], 1e-6)
        np.testing.assert_array_equal(r, [[3, 4]])
        np.testing.assert_allclose(
            y, np.array([[3, 4]]) / np.sqrt(12.5 + 1e-6), atol=1e-14
        )

    def test_quant_zero_tail_and_triangle(self):
        q, sc = t.quantize_w8(np.zeros((8, 5)), 3)
        np.testing.assert_array_equal(q, 0)
        np.testing.assert_array_equal(sc, 1)
        self.assertEqual(sc.shape, (3, 5))
        self.assertTrue(t.demo()["triangle_bound_holds"])

    def test_quant_storage_and_format(self):
        q, sc = t.quantize_w8(np.arange(40).reshape(8, 5), 3)
        self.assertEqual(q.nbytes + sc.nbytes, 100)
        self.assertFalse((q == -128).any())
        with self.assertRaises(ValueError):
            t.dequantize_w8(q, np.zeros_like(sc), 3)

    def test_invalid_transforms(self):
        for base in [1.0, np.inf, np.nan]:
            with self.assertRaises(ValueError):
                t.rope(np.ones((2, 4)), [1, 2], base)
        with self.assertRaises(ValueError):
            t.quantize_w8(np.ones((2, 3)), 0)
        with self.assertRaises(ValueError):
            t.rms_residual([1, 2], [0, 0], [1, 1], 0)


class DistributedTests(unittest.TestCase):
    def test_tp_row_and_column(self):
        rng = np.random.default_rng(5)
        x = rng.normal(size=(3, 8))
        w = rng.normal(size=(8, 8))
        for n in [1, 2, 4, 8]:
            np.testing.assert_allclose(d.column_parallel(x, w, n), x @ w, atol=1e-12)
            np.testing.assert_allclose(d.row_parallel(x, w, n), x @ w, atol=1e-12)

    def test_moe_inverse_routing(self):
        result = d.demo()
        self.assertLess(result["moe_combine_error"], 1e-12)
        self.assertEqual(result["expert_assignments"], [4, 4, 3, 3])

    def test_moe_overflow_and_duplicate_do_not_drop(self):
        x = np.ones((2, 3))
        w = np.ones((2, 3, 4))
        e = np.array([[0, 1], [0, 1]])
        p = np.full((2, 2), 0.5)
        with self.assertRaises(ValueError):
            d.moe_dispatch(x, w, e, p, capacity=1)
        with self.assertRaises(ValueError):
            d.moe_dispatch(x, w, np.zeros((2, 2), dtype=int), p)
        with self.assertRaises(ValueError):
            d.moe_dispatch(x, w, e, p * 1.00001)

    def test_speculative_probability_exact(self):
        for p, q in [
            ([0.1, 0.7, 0.2], [0.4, 0.4, 0.2]),
            ([0, 1], [1, 0]),
            ([0.2, 0.8], [0.2, 0.8]),
        ]:
            np.testing.assert_allclose(
                d.speculative_mass(p, q)["result_mass"], p, atol=1e-14
            )

    def test_collective_bytes_and_invalid_partition(self):
        self.assertEqual(d.ring_bytes_per_rank(8 * 1024**2, 4), 12 * 1024**2)
        self.assertEqual(d.ring_bytes_per_rank(100, 1), 0)
        with self.assertRaises(ValueError):
            d.row_parallel(np.ones((2, 7)), np.ones((7, 4)), 2)


class PagePoolTests(unittest.TestCase):
    def test_cow_isolates_partial_tail(self):
        out = k.demo()
        self.assertEqual(out["cow_isolated_tokens"], [[11], [11, 22]])

    def test_detached_page_stays_pinned(self):
        p = k.PagePool(1)
        h = p.allocate("A")
        p.submit("b", (("A", h),))
        p.release("A", h)
        self.assertEqual(p.free, set())
        with self.assertRaises(MemoryError):
            p.allocate("B")
        p.complete("b")
        self.assertEqual(p.free, {0})

    def test_stale_generation_and_duplicate_completion(self):
        p = k.PagePool(1)
        a1 = p.allocate("A")
        p.submit("b", (("A", a1),))
        p.release("A", a1)
        p.complete("b")
        b = p.allocate("B")
        self.assertNotEqual(a1.generation, b.generation)
        with self.assertRaises(k.StaleLease):
            p.data(a1)
        self.assertFalse(p.complete("b"))
        self.assertNotIn(0, p.free)

    def test_submission_atomicity_and_identity(self):
        p = k.PagePool(2)
        h = p.allocate("A")
        with self.assertRaises(ValueError):
            p.submit("bad", (("A", h), ("B", h)))
        self.assertFalse(p.pages[h.page].inflight)
        self.assertNotIn("bad", p.batches)
        self.assertTrue(p.submit("b", (("A", h),)))
        self.assertFalse(p.submit("b", (("A", h),)))
        with self.assertRaises(ValueError):
            p.submit("b", (("B", h),))

    def test_oom_cow_preserves_old_owners(self):
        p = k.PagePool(1)
        h = p.allocate("A")
        p.append("A", h, 3)
        p.share("A", h, "B")
        with self.assertRaises(MemoryError):
            p.clone_for_write("B", h)
        self.assertEqual(p.pages[h.page].owners, {"A", "B"})
        self.assertEqual(p.data(h), (3,))

    def test_shared_or_inflight_write_blocked(self):
        p = k.PagePool(2)
        h = p.allocate("A")
        p.share("A", h, "B")
        with self.assertRaises(ValueError):
            p.append("A", h, 1)
        p.release("B", h)
        p.submit("b", (("A", h),))
        with self.assertRaises(k.BusyPage):
            p.append("A", h, 1)
        with self.assertRaises(k.BusyPage):
            p.share("A", h, "B")

    def test_full_page_requires_new_logical_page(self):
        p = k.PagePool(2, 1)
        h = p.allocate("A")
        p.append("A", h, 7)
        p.share("A", h, "B")
        with self.assertRaises(ValueError):
            p.clone_for_write("B", h)

    def test_all_release_completion_interleavings(self):
        for order in itertools.permutations(["A", "B", "done"]):
            p = k.PagePool(1)
            h = p.allocate("A")
            p.share("A", h, "B")
            p.submit("b", (("A", h), ("B", h)))
            for i, event in enumerate(order):
                if event == "done":
                    p.complete("b")
                else:
                    p.release(event, h)
                self.assertTrue(p.assert_invariants())
                self.assertEqual(0 in p.free, i == 2)


class SchedulerTests(unittest.TestCase):
    def test_pressure_reservation_avoids_partial_prefill_deadlock(self):
        x = s.Scheduler([("A", 0, 4, 2), ("B", 0, 4, 2)], pages=3, budget=3, chunk=2)
        x.run()
        self.assertTrue(all(r.finished for r in x.requests))
        for row in x.trace:
            self.assertLessEqual(row["peak_pages_before_completion"], 3)

    def test_first_output_and_cancel_between_rounds(self):
        x = s.Scheduler([("A", 0, 4, 2), ("B", 0, 2, 1)], pages=8, budget=4, chunk=2)
        x.step(0)
        x.cancel("A")
        x.run()
        self.assertTrue(x.requests[0].cancelled)
        self.assertEqual(x.requests[1].decode_steps, 0)
        self.assertEqual(x.held(), 0)

    def test_seeded_finite_workloads(self):
        rng = random.Random(17)
        for seed in range(50):
            req = [
                (str(i), rng.randrange(5), rng.randrange(1, 8), rng.randrange(1, 5))
                for i in range(6)
            ]
            x = s.Scheduler(req, pages=12, budget=4, chunk=2)
            x.run()
            self.assertTrue(all(r.finished for r in x.requests))
            for row in x.trace:
                self.assertLessEqual(sum(w[2] for w in row["work"]), 4)
                self.assertLessEqual(row["reserved_pages_before_completion"], 12)

    def test_infeasible_input_rejected(self):
        with self.assertRaises(ValueError):
            s.Scheduler([("A", 0, 10, 10)], pages=1)
        with self.assertRaises(ValueError):
            s.Scheduler([("A", 0, 1, 1)], budget=1)


class StatisticsTests(unittest.TestCase):
    def test_risk_sets_ties_and_unreached_tail(self):
        r = st.kaplan_meier(
            [1, 2, 2, 3, 4, 5], np.array([True, True, False, True, False, False])
        )
        self.assertEqual([x["at_risk"] for x in r["rows"]], [6, 5, 3, 2, 1])
        self.assertAlmostEqual(r["rows"][2]["survival"], 4 / 9)
        self.assertEqual(r["median"], 3)
        self.assertIsNone(r["p95"])

    def test_all_censored_is_not_fast_recovery(self):
        r = st.kaplan_meier([1, 2, 3], np.zeros(3, dtype=bool))
        self.assertIsNone(r["median"])
        self.assertIsNone(r["p95"])
        self.assertEqual(r["rows"][-1]["survival"], 1)

    def test_paired_ratio_units_and_fixed_gain(self):
        r = st.paired_gain([10, 20, 30], [11, 22, 33], resamples=200)
        self.assertAlmostEqual(r["gain"], 0.1)
        np.testing.assert_allclose(r["percentile_95"], [0.1, 0.1], atol=1e-14)
        self.assertAlmostEqual(
            r["gain"], st.paired_gain([100, 200, 300], [110, 220, 330], 200)["gain"]
        )

    def test_invalid_statistics(self):
        with self.assertRaises(ValueError):
            st.paired_gain([0, 1], [1, 2])
        with self.assertRaises(ValueError):
            st.kaplan_meier([1, 2], [1, 0])


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.base = (
            Path(__file__).resolve().parents[1] / "reports" / "engineering-tests"
        )
        self.base.mkdir(parents=True, exist_ok=True)
        self.root = self.base / uuid.uuid4().hex
        self.root.mkdir()

    def tearDown(self):
        resolved = self.root.resolve()
        parent = self.base.resolve()
        if resolved.parent != parent or self.root.is_symlink():
            raise RuntimeError("cleanup boundary")
        shutil.rmtree(resolved)

    def test_actual_process_crashes_and_recovery(self):
        result = db.demo(self.root / "cases")
        self.assertEqual(
            [x.get("crash_exit") for x in result["experiments"][:3]], [91, 92, 93]
        )
        self.assertTrue(result["experiments"][-1]["new_owner_recovered"])
        self.assertEqual(
            [
                (
                    x["state_before_recovery"],
                    x["resources_before_recovery"],
                    x["apply_writes_before_recovery"],
                )
                for x in result["experiments"][:3]
            ],
            [("prepared", 0, 0), ("prepared", 1, 0), ("applied", 1, 1)],
        )

    def test_same_command_different_payload_conflicts(self):
        db.initialize(self.root)
        db.recover(self.root, db.COMMAND, db.PAYLOAD)
        with self.assertRaises(ValueError):
            db.recover(self.root, db.COMMAND, dict(db.PAYLOAD, revision="other"))
        self.assertEqual(len(db.inspect(self.root)["resources"]), 1)

    def test_tombstone_before_effect(self):
        db.initialize(self.root)
        with closing(db.connect(self.root / "journal.sqlite")) as c:
            c.execute("UPDATE owner SET deleted=1")
        with self.assertRaises(ValueError):
            db.recover(self.root, db.COMMAND, db.PAYLOAD)
        self.assertEqual(db.inspect(self.root)["resources"], [])

    def test_foreign_resource_not_adopted(self):
        db.initialize(self.root)
        db.prepare(self.root, db.COMMAND, db.PAYLOAD, 1)
        with closing(db.connect(self.root / "remote.sqlite")) as c:
            c.execute(
                "INSERT INTO resources VALUES(?,?,?)", (db.COMMAND, "foreign", "UID-X")
            )
        with self.assertRaises(ValueError):
            db.recover(self.root, db.COMMAND, db.PAYLOAD)
        self.assertEqual(db.inspect(self.root)["commands"][0][1], "prepared")

    def test_report_cli_refuses_existing_output(self):
        import subprocess, sys

        output = self.root / "report.json"
        argv = [
            sys.executable,
            str(Path(__file__).with_name("run.py")),
            "--lab",
            "attention",
            "--output",
            str(output),
        ]
        good = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        self.assertEqual(good.returncode, 0, good.stderr)
        original = output.read_bytes()
        bad = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        self.assertEqual(bad.returncode, 2)
        self.assertFalse(bad.stdout)
        self.assertEqual(output.read_bytes(), original)
        optimized = self.root / "optimized.json"
        blocked = subprocess.run(
            [
                sys.executable,
                "-O",
                str(Path(__file__).with_name("run.py")),
                "--output",
                str(optimized),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertFalse(optimized.exists())

    def test_committed_read_does_not_repeat_effect(self):
        db.initialize(self.root)
        first = db.recover(self.root, db.COMMAND, db.PAYLOAD)
        again = db.recover(self.root, db.COMMAND, db.PAYLOAD)
        self.assertEqual(first["uid"], again["uid"])
        self.assertFalse(again["external_ensure_called"])
        self.assertEqual(db.inspect(self.root)["commands"][0][4], 1)


class ReportGateTests(unittest.TestCase):
    def test_nonfinite_or_failed_numeric_checks_reject_report(self):
        if __package__:
            from .run import validate_numeric_reports
        else:
            from run import validate_numeric_reports
        for v in [float("nan"), float("inf"), 1.0]:
            with self.assertRaises(ValueError):
                validate_numeric_reports(
                    {"attention": {"max_abs_error_by_block": {"1": v}}}
                )
        with self.assertRaises(ValueError):
            validate_numeric_reports(
                {
                    "transforms": {
                        "rope_roundtrip_max_error": 0.0,
                        "triangle_bound_holds": False,
                    }
                }
            )


if __name__ == "__main__":
    unittest.main()
