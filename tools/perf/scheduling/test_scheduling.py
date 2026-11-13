"""Page-budget scheduler correctness, overload/fairness and measurement regressions."""

from dataclasses import replace
import copy, random, unittest
import tempfile, subprocess, sys
from pathlib import Path

if __package__:
    from .algorithm import Engine, Entry, Limits, finite_chunks
    from .pages import Pages
    from .sampling_probe import cases
else:
    from algorithm import Engine, Entry, Limits, finite_chunks
    from pages import Pages
    from sampling_probe import cases


def small(**kw):
    base = Limits(
        page_tokens=4,
        kv_bytes_per_token=2,
        kv_budget_bytes=128,
        batch_tokens=8,
        activation_budget_bytes=64,
        activation_bytes_per_position=8,
        max_active=8,
        max_batch_items=8,
        quantum=4,
        prefill_age=3,
        admission_age=4,
        horizon=200,
    )
    return replace(base, **kw)


class PageTests(unittest.TestCase):
    def test_private_tail_increment(self):
        p = Pages(6, 4, {})
        table = []
        p.append(table, 0, 3, "A")
        self.assertEqual(p.extra_pages(table, 3, 1), 0)
        p.append(table, 3, 1, "A")
        self.assertEqual(p.extra_pages(table, 4, 1), 1)
        p.append(table, 4, 1, "A")
        self.assertEqual(p.used, 2)
        self.assertEqual([p.pages[x].valid for x in table], [4, 1])

    def test_shared_full_pages_count_once_and_partial_tail_cow(self):
        p = Pages(8, 4, {"P": 5})
        a, pos = p.attach("P", "A")
        b, _ = p.attach("P", "B")
        self.assertEqual(p.used, 2)
        self.assertEqual(p.reserve_private(8, 3, "P"), 2)
        self.assertEqual(p.extra_pages(a, pos, 2), 1)
        old = b[-1]
        p.append(a, pos, 2, "A")
        self.assertNotEqual(a[-1], b[-1])
        self.assertEqual(p.pages[old].valid, 1)
        p.release(a, "A")
        p.release(b, "B")
        self.assertEqual(p.used, 2)

    def test_atomic_oom(self):
        p = Pages(1, 4, {})
        table = []
        p.append(table, 0, 3, "A")
        before = copy.deepcopy((p.pages, table))
        with self.assertRaises(MemoryError):
            p.append(table, 3, 3, "A")
        self.assertEqual((p.pages, table), before)

    def test_generation_and_double_release(self):
        p = Pages(1, 4, {})
        a = []
        p.append(a, 0, 1, "A")
        old = p.pages[0].generation
        p.release(a, "A")
        b = []
        p.append(b, 0, 1, "B")
        self.assertGreater(p.pages[0].generation, old)
        with self.assertRaises(RuntimeError):
            p.release(a, "A")

    def test_exact_rounding_unshared_formula_exhaustive(self):
        for prefix in range(1, 12):
            for append in range(1, 12):
                p = Pages(20, 4, {})
                table = []
                p.append(table, 0, prefix, "A")
                expected = (prefix + append + 3) // 4 - (prefix + 3) // 4
                self.assertEqual(p.extra_pages(table, prefix, append), expected)
                p.append(table, prefix, append, "A")
                self.assertEqual(p.used, (prefix + append + 3) // 4)


class AlgorithmTests(unittest.TestCase):
    def test_all_outputs_and_conservation_all_policies(self):
        entries = [
            Entry("A", "L", 17, 5, 0),
            Entry("B", "S", 5, 1, 1),
            Entry("C", "M", 9, 3, 2),
        ]
        for policy in Engine.POLICIES:
            result = Engine(entries, small(), policy=policy, chunk=8).run(audit=True)
            self.assertEqual(result["counts"], {"completed": 3})
            self.assertEqual(result["pages_remaining"], 0)
            self.assertEqual([r["generated"] for r in result["rows"]], [5, 1, 3])

    def test_final_prefill_produces_first_output(self):
        result = Engine([Entry("A", "S", 3, 1, 0)], small()).run(audit=True)
        self.assertEqual(result["rows"][0]["generated"], 1)
        self.assertEqual(result["rows"][0]["first_output_round"], 0)
        self.assertEqual(result["logical_rounds"], 1)

    def test_activation_bounds_and_page_aligned_middle(self):
        result = Engine(
            [Entry("A", "L", 17, 3, 0)], small(activation_budget_bytes=32), chunk=128
        ).run(audit=True)
        for row in result["trace_sample"]:
            self.assertLessEqual(row["activation_proxy_bytes"], 32)
            for _, phase, n in row["work"]:
                if phase == "prefill":
                    self.assertIn(n, (4, 1))

    def test_no_feasible_chunk_is_rejected_not_spun(self):
        r = Engine(
            [Entry("A", "L", 10, 2, 0)], small(batch_tokens=3), policy="age_fair"
        ).run(audit=True)
        self.assertEqual(r["rows"][0]["reason"], "no_feasible_aligned_chunk")
        self.assertEqual(r["counts"], {"rejected": 1})

    def test_prefix_partial_tail_alignment(self):
        r = Engine(
            [
                Entry("A", "S", 9, 2, 0, prefix_key="P"),
                Entry("B", "S", 9, 2, 0, prefix_key="P"),
            ],
            small(),
            prefixes={"P": 3},
        ).run(audit=True)
        self.assertEqual(r["counts"], {"completed": 2})
        self.assertEqual(r["cow_pages"], 2)
        self.assertEqual(r["pages_remaining"], 1)

    def test_output_envelope_avoids_partial_deadlock(self):
        r = Engine(
            [Entry("A", "S", 4, 2, 0), Entry("B", "S", 4, 2, 0)],
            small(kv_budget_bytes=16),
            chunk=4,
        ).run(audit=True)
        self.assertEqual(r["counts"], {"completed": 2})
        self.assertLessEqual(r["peak_reserved_including_cache"], 2)

    def test_impossible_individual_envelope_rejected(self):
        r = Engine([Entry("A", "L", 100, 9, 0)], small()).run()
        self.assertEqual(r["rows"][0]["reason"], "individual_kv_envelope")

    def test_admission_age_barrier_eventually_admits_large_request(self):
        entries = [Entry("A", "S", 4, 10, 0), Entry("L", "L", 32, 1, 1)] + [
            Entry("s" + str(i), "S", 4, 2, i) for i in range(2, 70)
        ]
        r = Engine(
            entries,
            small(kv_budget_bytes=64, max_active=16, admission_age=2, horizon=500),
            policy="age_fair",
        ).run(audit=True)
        self.assertIsNotNone(r["rows"][1]["admitted_round"])
        self.assertEqual(r["counts"], {"completed": len(entries)})
        self.assertGreater(r["diagnostics"].get("aged_admission_barrier", 0), 0)

    def test_prefill_not_starved_by_decode_and_batch_item_limit(self):
        entries = [Entry("d" + str(i), "S", 1, 15, 0) for i in range(4)] + [
            Entry("L", "L", 16, 1, 1)
        ]
        r = Engine(
            entries,
            small(kv_budget_bytes=256, max_batch_items=2, max_active=8, batch_tokens=5),
            policy="age_fair",
        ).run(audit=True)
        self.assertEqual(r["counts"], {"completed": 5})
        self.assertLess(r["rows"][-1]["first_output_round"], 20)

    def test_age_reduces_prefill_service_gap_under_short_arrivals(self):
        entries = [Entry("long", "L", 96, 1, 0)] + [
            Entry("s" + str(i), "S", 4, 1, i // 2) for i in range(60)
        ]
        limits = small(
            kv_budget_bytes=1024,
            max_active=64,
            max_batch_items=1,
            batch_tokens=4,
            prefill_age=3,
            horizon=300,
        )
        fair = Engine(entries, limits, policy="age_fair").run(audit=True)
        no = Engine(entries, limits, policy="no_age").run(audit=True)
        self.assertLess(
            fair["rows"][0]["max_service_gap_rounds"],
            no["rows"][0]["max_service_gap_rounds"],
        )

    def test_cancel_fail_unrecovered_remain_in_sent_denominator(self):
        e = [
            Entry("A", "S", 8, 4, 0, cancel_round=1),
            Entry("B", "M", 8, 3, 0, fail_after=1),
            Entry("C", "M", 8, 3, 0, fail_after=1, lose_release=True),
        ]
        r = Engine(e, small()).run(audit=True)
        self.assertEqual(r["sent"], 3)
        self.assertEqual(sum(r["counts"].values()), 3)
        self.assertEqual(r["remaining_unrecovered"], 1)
        self.assertGreater(r["private_pages_reserved"], 0)
        self.assertEqual(r["rows"][2]["end_round"], None)

    def test_queue_bound_rejects_overload_and_horizon_retains_pending(self):
        e = [Entry(str(i), "L", 32, 20, 0) for i in range(12)]
        r = Engine(e, small(queue_capacity=3, horizon=2)).run(audit=True)
        self.assertEqual(r["counts"]["rejected"], 9)
        self.assertGreater(r["remaining_pending"], 0)
        self.assertEqual(sum(r["counts"].values()), 12)

    def test_fixed_seed_small_exhaustive_loads(self):
        rng = random.Random(99)
        for _ in range(30):
            e = [
                Entry(
                    str(i),
                    "X",
                    rng.randrange(1, 20),
                    rng.randrange(1, 8),
                    rng.randrange(4),
                )
                for i in range(6)
            ]
            for policy in ("static", "adaptive", "age_fair"):
                r = Engine(e, small(horizon=400), policy=policy, chunk=8).run(
                    audit=True
                )
                self.assertEqual(r["counts"], {"completed": 6})

    def test_single_item_mixed_phase_alternates_without_decode_starvation(self):
        e = [Entry("decode", "S", 1, 12, 0)] + [
            Entry("p" + str(i), "S", 4, 1, i) for i in range(1, 60)
        ]
        r = Engine(
            e,
            small(
                kv_budget_bytes=1024,
                max_active=64,
                max_batch_items=1,
                batch_tokens=4,
                horizon=200,
            ),
            policy="age_fair",
        ).run(audit=True)
        self.assertEqual(r["counts"], {"completed": 60})
        self.assertLess(r["rows"][0]["end_round"], 40)

    def test_unsent_future_arrivals_are_not_in_sent_denominator(self):
        r = Engine(
            [Entry("now", "S", 1, 1, 0), Entry("future", "S", 1, 1, 99)],
            small(horizon=2),
        ).run(audit=True)
        self.assertEqual(r["sent"], 1)
        self.assertEqual(r["input_entries"], 2)
        self.assertEqual(r["not_offered"], 1)
        self.assertEqual(r["rows"][1]["status"], "not_offered")
        self.assertEqual(r["counts"], {"completed": 1})

    def test_configuration_and_fragmentation_boundary(self):
        with self.assertRaises(ValueError):
            small(batch_tokens=0)
        with self.assertRaises(ValueError):
            small(kv_budget_bytes=1)
        self.assertEqual(finite_chunks(3, 10, 4, 4), 1)
        self.assertEqual(finite_chunks(0, 10, 3, 4), 0)

    def test_calibration_score_penalizes_dropped_requests(self):
        if __package__:
            from .compare import score
        else:
            from compare import score
        self.assertLess(
            score({"counts": {"completed": 3}, "sent": 3, "logical_rounds": 100}),
            score({"counts": {"completed": 2}, "sent": 3, "logical_rounds": 1}),
        )


class ReportTests(unittest.TestCase):
    def test_j02_hash_distribution_and_same_work_for_all_policies(self):
        if __package__:
            from .compare import workload
        else:
            from compare import workload
        e, p, m = workload()
        self.assertEqual(len(e), 200)
        self.assertEqual(
            {s: sum(r.shape == s for r in e) for s in ("S", "M", "L")},
            {"S": 120, "M": 60, "L": 20},
        )
        other, _, m2 = workload()
        self.assertEqual(e, other)
        self.assertEqual(m["entry_sha256"], m2["entry_sha256"])

    def test_report_publication_refuses_overwrite(self):
        if __package__:
            from .compare import write_report
        else:
            from compare import write_report
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            write_report(path, {"synthetic": True})
            old = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_report(path, {"synthetic": False})
            self.assertEqual(old, path.read_bytes())

    def test_cli_optimized_mode_rejected_without_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-O",
                    str(Path(__file__).with_name("compare.py")),
                    "--output",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse(path.exists())

    def test_fair_quantum_too_small_is_explicitly_rejected(self):
        r = Engine(
            [Entry("A", "M", 10, 2, 0)], small(quantum=3), policy="age_fair"
        ).run()
        self.assertEqual(r["rows"][0]["reason"], "no_feasible_aligned_chunk")


class SamplingTests(unittest.TestCase):
    def test_client_parser_ignores_no_content_events(self):
        r = cases()
        self.assertEqual(r["with_content"]["legacy_first_normalized_event_ms"], 5)
        self.assertEqual(r["with_content"]["client_content_times_ms"], [30])
        self.assertIsNone(r["without_content"]["go_content_write_boundary_ms_proposed"])

    def test_worker_clock_not_subtracted(self):
        self.assertTrue(cases()["worker_native_ttft"]["cannot_subtract_from_client"])


if __name__ == "__main__":
    unittest.main()
