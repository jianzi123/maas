"""Deterministic integration/fault tests plus real bounded CPU-thread execution."""

from dataclasses import replace
import threading
import json
import random
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
import unittest

if __package__:
    from .runtime_core import Runtime, RequestSpec
    from .runtime_worker import (
        ManualWorker,
        ThreadWorker,
        Binding,
        Result,
        Receipt,
        compute,
    )
    from .kv_lab import PagePool
    from .scheduler_lab import Scheduler
else:
    from runtime_core import Runtime, RequestSpec
    from runtime_worker import (
        ManualWorker,
        ThreadWorker,
        Binding,
        Result,
        Receipt,
        compute,
    )
    from kv_lab import PagePool
    from scheduler_lab import Scheduler


class FailingPool(PagePool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0
        self.fail_on = None

    def allocate(self, owner):
        self.calls += 1
        if self.calls == self.fail_on:
            raise MemoryError("injected allocator failure")
        return super().allocate(owner)


class RuntimeTests(unittest.TestCase):
    def make(self, specs=None, worker=None, **limits):
        w = worker if worker is not None else ManualWorker("worker-1")
        specs = specs if specs is not None else [RequestSpec("A", (1, 2), 3)]
        r = Runtime(specs, w, **limits)
        self.addCleanup(r.close)
        return r, w

    def finish_manual(self, r, w, max_rounds=80):
        for now in range(max_rounds):
            for _ in range(r.max_inflight):
                r.dispatch(now)
            for batch in list(w.plans):
                if batch not in w.completed:
                    w.complete(batch)
            r.poll()
            for rid in r.requests:
                r.drain(rid)
            if all(
                s.reason is not None and s.busy is None for s in r.requests.values()
            ):
                return
        self.fail("bounded manual runtime did not finish")

    def test_preview_does_not_mutate_policy(self):
        p = Scheduler([("A", 0, 4, 3)], pages=4)
        first = p.preview(0)
        self.assertEqual(first, p.preview(0))
        self.assertEqual(p.requests[0].pref, 0)
        self.assertFalse(p.requests[0].admitted)
        self.assertEqual(p.trace, [])

    def test_known_token_sequence_and_full_recovery(self):
        r, w = self.make(
            pages=2, budget=2, chunk=1, output_per_request=1, output_global=1
        )
        self.finish_manual(r, w)
        self.assertEqual([v for _, v in r.requests["A"].delivered], [29786, 492, 64944])
        self.assertEqual(r.policy["A"].decode_steps, 2)
        self.assertEqual(len(r.pool.free), 2)
        self.assertEqual(r.scheduler.held(), 0)
        self.assertEqual([n for n, _ in r.requests["A"].delivered], [1, 2, 3])

    def test_completion_can_precede_transport_drain(self):
        r, w = self.make(
            [RequestSpec("A", (1,), 1)],
            pages=1,
            budget=2,
            output_per_request=1,
            output_global=1,
        )
        b = r.dispatch(0)
        w.complete(b)
        r.poll()
        snap = r.snapshot()
        self.assertEqual(snap["requests"]["A"]["reason"], "completed")
        self.assertFalse(snap["requests"]["A"]["output_drained"])
        self.assertEqual(snap["allocated_pages"], 0)
        self.assertEqual(snap["output_queued"], 1)
        r.drain("A")
        self.assertTrue(r.snapshot()["requests"]["A"]["output_drained"])

    def test_per_request_backpressure_stops_next_decode(self):
        r, w = self.make(output_per_request=1, output_global=4)
        b = r.dispatch(0)
        w.complete(b)
        r.poll()
        while not r.requests["A"].output:
            b = r.dispatch(0)
            w.complete(b)
            r.poll()
        self.assertIsNone(r.dispatch(0))
        self.assertEqual(len(w.plans), len(r.records))
        r.drain("A")
        self.assertIsNotNone(r.dispatch(0))

    def test_global_output_credit_includes_inflight(self):
        specs = [RequestSpec("A", (1,), 2), RequestSpec("B", (2,), 2)]
        r, w = self.make(
            specs, pages=4, budget=2, max_items=1, output_per_request=2, output_global=1
        )
        first = r.dispatch(0)
        self.assertIsNotNone(first)
        self.assertIsNone(r.dispatch(0))
        self.assertEqual(r.snapshot()["output_reserved"], 1)
        w.complete(first)
        r.poll()
        self.assertIsNone(r.dispatch(0))
        r.drain("A")
        self.assertIsNotNone(r.dispatch(0))

    def test_out_of_order_batches_preserve_per_request_sequence(self):
        r, w = self.make(
            [RequestSpec("A", (1,), 2), RequestSpec("B", (2,), 2)],
            pages=4,
            budget=2,
            max_items=1,
            output_global=4,
        )
        a = r.dispatch(0)
        b = r.dispatch(0)
        self.assertNotEqual(a, b)
        w.complete(b)
        w.complete(a)
        r.poll()
        self.assertEqual(r.requests["A"].output[0][1], 2228)
        self.assertEqual(r.requests["B"].output[0][1], 2229)
        self.finish_manual(r, w)
        self.assertEqual([x[0] for x in r.requests["A"].delivered], [1, 2])

    def test_cancel_inflight_holds_reservation_and_pin(self):
        r, w = self.make(
            [RequestSpec("A", (1, 2), 3), RequestSpec("B", (9,), 1, arrival=1)],
            pages=2,
            budget=2,
            chunk=1,
            max_items=1,
        )
        b = r.dispatch(0)
        r.cancel("A")
        snap = r.snapshot()
        self.assertEqual((snap["reserved_pages"], snap["allocated_pages"]), (2, 1))
        self.assertFalse(r.policy["A"].cancelled)
        self.assertIsNone(r.dispatch(1))
        w.complete(b)
        r.poll()
        self.assertEqual(r.scheduler.held(), 0)
        self.assertEqual(len(r.pool.free), 2)
        self.assertFalse(r.requests["A"].output)
        self.assertEqual(r.requests["A"].reason, "cancelled")

    def test_duplicate_completion_does_not_release_successor_page(self):
        r, w = self.make(
            [RequestSpec("A", (1, 2), 3), RequestSpec("B", (9,), 1, arrival=1)],
            pages=2,
            budget=2,
            chunk=1,
            max_items=1,
        )
        old = r.dispatch(0)
        old_lease = r.records[old].plan.items[0].leases[0]
        r.cancel("A")
        w.complete(old)
        r.poll()
        new = r.dispatch(1)
        lease = r.records[new].plan.items[0].leases[0]
        self.assertEqual(old_lease.page, lease.page)
        self.assertGreater(lease.generation, old_lease.generation)
        before = r.snapshot()
        w.replay(old)
        r.poll()
        after = r.snapshot()
        self.assertEqual(before["allocated_pages"], after["allocated_pages"])
        self.assertEqual(after["diagnostics"]["duplicate_completion"], 1)
        self.assertTrue(r.pool.batches[new]["active"])

    def test_cancel_queued_uses_no_worker_or_pages(self):
        r, w = self.make()
        self.assertTrue(r.cancel("A"))
        self.assertFalse(r.cancel("A"))
        self.assertIsNone(r.dispatch(0))
        self.assertEqual(w.plans, {})
        self.assertEqual(r.scheduler.held(), 0)

    def test_preaccept_rejection_rolls_back_all_staging(self):
        r, w = self.make()
        w.reject_next = True
        self.assertIsNone(r.dispatch(0))
        self.assertEqual(r.policy["A"].pref, 0)
        self.assertFalse(r.policy["A"].admitted)
        self.assertEqual(r.requests["A"].table, [])
        self.assertFalse(w.plans)
        self.assertEqual(len(r.pool.free), len(r.pool.pages))
        self.assertEqual(r.snapshot()["output_reserved"], 0)
        self.finish_manual(r, w)

    def test_acceptance_unknown_does_not_resubmit(self):
        r, w = self.make([RequestSpec("A", (1,), 1)], pages=1)
        w.uncertain_next = True
        b = r.dispatch(0)
        self.assertEqual(r.records[b].state, "ack_unknown")
        self.assertIsNone(r.dispatch(0))
        self.assertEqual(len(w.plans), 1)
        w.complete(b)
        r.poll()
        r.drain("A")
        self.assertEqual(r.policy["A"].generated, 1)
        self.assertEqual(len(w.plans), 1)

    def test_missing_completion_needs_separate_worker_stop(self):
        r, w = self.make(pages=2, chunk=1)
        b = r.dispatch(0)
        r.cancel("A")
        for _ in range(3):
            self.assertIsNone(r.dispatch(0))
        with self.assertRaises(ValueError):
            r.reap_stopped(w.incarnation, object())
        self.assertEqual(r.snapshot()["allocated_pages"], 1)
        token = w.stop()
        self.assertEqual(r.reap_stopped(w.incarnation, token), 1)
        self.assertEqual(r.scheduler.held(), 0)
        self.assertEqual(len(r.pool.free), 2)
        self.assertEqual(r.records[b].state, "stopped")

    def test_old_incarnation_cannot_commit_or_unpin(self):
        r, w = self.make(pages=2, chunk=1)
        b = r.dispatch(0)
        new = ManualWorker("worker-2")
        r.replace_worker(new)
        w.complete(b)
        r.consume(w.completed[b])
        self.assertEqual(r.policy["A"].pref, 0)
        self.assertEqual(r.snapshot()["allocated_pages"], 1)
        self.assertEqual(r.diagnostics["stale_incarnation"], 1)
        token = w.stop()
        r.reap_stopped(w.incarnation, token)
        self.assertEqual(r.scheduler.held(), 0)

    def test_cross_source_replacement_is_atomic_rejection(self):
        r, w = self.make()
        b = r.dispatch(0)
        other = ManualWorker("worker-2", replace(w.binding, source_id="foreign"))
        with self.assertRaises(ValueError):
            r.replace_worker(other)
        self.assertIs(r.worker, w)
        self.assertFalse(r.requests["A"].cancel_requested)
        self.assertTrue(r.pool.batches[b]["active"])

    def test_shared_partial_prefix_cow_keeps_results_isolated(self):
        r, w = self.make(
            [RequestSpec("A", (1, 2, 3), 1), RequestSpec("B", (1, 3, 4), 1)],
            pages=4,
            budget=4,
            chunk=2,
        )
        r.prime_prefix("A", (1,))
        r.share_prefix("A", "B")
        original = r.requests["A"].table[0]
        self.assertEqual(r.pool.pages[original.page].owners, {"A", "B"})
        b = r.dispatch(0)
        self.assertNotEqual(r.requests["A"].table, r.requests["B"].table)
        w.complete(b)
        r.poll()
        self.assertEqual(r.drain("A"), [(1, 36230)])
        self.assertEqual(r.drain("B"), [(1, 36362)])
        self.assertEqual(len(r.pool.free), 4)

    def test_cow_allocation_failure_restores_original_references(self):
        pool = FailingPool(4, 2)
        r, w = self.make(
            [RequestSpec("A", (1, 2, 3), 1), RequestSpec("B", (1, 3, 4), 1)],
            pages=4,
            budget=4,
            chunk=2,
            pool=pool,
        )
        r.prime_prefix("A", (1,))
        r.share_prefix("A", "B")
        lease = r.requests["A"].table[0]
        pool.fail_on = pool.calls + 2
        self.assertIsNone(r.dispatch(0))
        self.assertEqual(pool.data(lease), (1,))
        self.assertEqual(pool.pages[lease.page].owners, {"A", "B"})
        self.assertEqual(r.requests["A"].table, [lease])
        self.assertEqual(r.policy["A"].pref, 1)
        self.assertEqual(w.plans, {})
        self.assertEqual(len(pool.free), 3)
        pool.fail_on = None
        self.finish_manual(r, w)

    def test_wrong_prefix_and_overcapacity_are_rejected(self):
        r, _ = self.make(
            [RequestSpec("A", (1, 2), 3), RequestSpec("B", (3, 4), 3)], pages=2
        )
        r.prime_prefix("A", (1,))
        with self.assertRaises(ValueError):
            r.share_prefix("A", "B")
        with self.assertRaises(MemoryError):
            r.prime_prefix("B", (3,))
        self.assertFalse(r.policy["B"].admitted)

    def test_malformed_verified_completion_is_quarantined(self):
        r, w = self.make([RequestSpec("A", (1,), 1)], pages=1)
        b = r.dispatch(0)
        w.complete(b, results=(Result("wrong", (1,), 5),))
        r.poll()
        self.assertTrue(r.halted)
        self.assertEqual(r.snapshot()["allocated_pages"], 1)
        self.assertEqual(r.policy["A"].generated, 0)
        self.assertFalse(r.requests["A"].output)
        token = w.stop()
        r.reap_stopped(w.incarnation, token)
        self.assertEqual(len(r.pool.free), 1)

    def test_invalid_output_value_is_not_published(self):
        for token in (float("nan"), True, -1, 65521):
            with self.subTest(token=token):
                r, w = self.make([RequestSpec("A", (1,), 1)], pages=1)
                b = r.dispatch(0)
                w.complete(b, results=(Result("A", (1,), token),))
                r.poll()
                self.assertTrue(r.halted)
                self.assertEqual(r.policy["A"].generated, 0)
                r.close()

    def test_unverified_message_cannot_close_or_release_worker(self):
        r, w = self.make()
        b = r.dispatch(0)
        plan = r.records[b].plan
        message = Receipt(
            b, w.incarnation, plan.digest, compute(plan), None, 0, object()
        )
        self.assertFalse(r.consume(message))
        self.assertFalse(r.halted)
        self.assertTrue(r.pool.batches[b]["active"])

    def test_conflicting_duplicate_is_fail_closed_without_second_output(self):
        r, w = self.make([RequestSpec("A", (1,), 1)], pages=1)
        b = r.dispatch(0)
        good = w.complete(b)
        r.poll()
        changed = replace(good, results=(Result("A", (1,), 17),))
        w.completed[b] = changed
        self.assertFalse(r.consume(changed))
        self.assertTrue(r.halted)
        self.assertEqual(r.policy["A"].generated, 1)
        self.assertEqual(r.drain("A"), [(1, 2228)])

    def test_worker_error_has_no_successful_output(self):
        r, w = self.make([RequestSpec("A", (1,), 1)], pages=1)
        b = r.dispatch(0)
        w.complete(b, error="injected_failure")
        r.poll()
        self.assertTrue(r.halted)
        self.assertEqual(r.requests["A"].reason, "worker_error")
        self.assertEqual(r.scheduler.held(), 0)
        self.assertEqual(len(r.pool.free), 1)

    def test_actor_owns_mutation(self):
        r, _ = self.make()
        errors = []
        thread = threading.Thread(target=lambda: self._off_actor_cancel(r, errors))
        thread.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ["RuntimeError"])
        self.assertFalse(r.requests["A"].cancel_requested)

    @staticmethod
    def _off_actor_cancel(runtime, errors):
        try:
            runtime.cancel("A")
        except RuntimeError as exc:
            errors.append(type(exc).__name__)

    def test_close_releases_primed_and_inflight_resources(self):
        r, w = self.make(
            [RequestSpec("A", (1, 2), 3), RequestSpec("B", (1, 3), 2)],
            pages=4,
            max_items=1,
            chunk=1,
        )
        r.prime_prefix("A", (1,))
        r.share_prefix("A", "B")
        r.dispatch(0)
        r.close()
        self.assertEqual(len(r.pool.free), 4)
        self.assertEqual(r.scheduler.held(), 0)
        self.assertTrue(w.closed)
        self.assertEqual(r.snapshot()["pending_batches"], 0)

    def test_untyped_submit_error_preserves_ambiguity(self):
        class UnknownWorker(ManualWorker):
            def submit(self, plan):
                super().submit(plan)
                raise OSError("unknown adapter result")

        w = UnknownWorker("uncertain")
        r, _ = self.make([RequestSpec("A", (1,), 1)], w, pages=1)
        b = r.dispatch(0)
        self.assertEqual(r.records[b].state, "ack_unknown")
        self.assertEqual(r.snapshot()["allocated_pages"], 1)
        self.assertIsNone(r.dispatch(0))
        w.complete(b)
        r.poll()
        self.assertEqual(r.drain("A"), [(1, 2228)])

    def test_plan_digest_mismatch_keeps_lease_quarantined(self):
        r, w = self.make([RequestSpec("A", (1,), 1)], pages=1)
        b = r.dispatch(0)
        good = w.complete(b)
        bad = replace(good, plan_digest="wrong-revision")
        w.completed[b] = bad
        r.consume(bad)
        self.assertTrue(r.halted)
        self.assertEqual(r.policy["A"].generated, 0)
        self.assertEqual(r.snapshot()["allocated_pages"], 1)

    def test_unknown_batch_is_diagnostic_only(self):
        r, w = self.make()
        b = r.dispatch(0)
        good = w.complete(b)
        self.assertFalse(r.consume(replace(good, batch_id="unknown")))
        self.assertFalse(r.halted)
        self.assertTrue(r.pool.batches[b]["active"])
        self.assertEqual(r.diagnostics["unknown_batch"], 1)

    def test_seeded_event_interleavings_against_polynomial_oracle(self):
        for seed in range(24):
            rng = random.Random(seed)
            specs = [
                RequestSpec(
                    str(i),
                    tuple(rng.randrange(1, 10) for _ in range(rng.randrange(1, 5))),
                    rng.randrange(1, 4),
                    arrival=rng.randrange(3),
                )
                for i in range(3)
            ]
            r, w = self.make(
                specs, pages=8, budget=3, chunk=1, output_per_request=2, output_global=3
            )
            try:
                for now in range(160):
                    for _ in range(2):
                        r.dispatch(now)
                    pending = [b for b in w.plans if b not in w.completed]
                    rng.shuffle(pending)
                    for b in pending:
                        if rng.random() < 0.8 or now > 120:
                            w.complete(b)
                    r.poll()
                    if now == 3 and seed % 2 == 0:
                        r.cancel("1")
                    for rid in r.requests:
                        if rng.random() < 0.65 or now > 120:
                            r.drain(rid, limit=1)
                    if w.completed and rng.random() < 0.15:
                        w.replay(rng.choice(list(w.completed)))
                        r.poll()
                    r.assert_invariants()
                    if all(
                        s.reason is not None and not s.busy and not s.output
                        for s in r.requests.values()
                    ):
                        break
                else:
                    self.fail("finite seeded trace failed to finish")
                for spec in specs:
                    context = list(spec.prompt)
                    expected = []
                    for _ in range(spec.output_cap):
                        n = len(context)
                        value = (
                            17 * pow(131, n, 65521)
                            + sum(
                                t * pow(131, n - i - 1, 65521)
                                for i, t in enumerate(context)
                            )
                        ) % 65521
                        expected.append(value)
                        context.append(value)
                    delivered = [v for _, v in r.requests[spec.request_id].delivered]
                    self.assertEqual(delivered, expected[: len(delivered)])
                    if not r.requests[spec.request_id].cancel_requested:
                        self.assertEqual(delivered, expected)
                self.assertEqual(r.scheduler.held(), 0)
            finally:
                r.close()

    def test_message_nested_values_are_immutable_and_bounded(self):
        r, w = self.make()
        b = r.dispatch(0)
        plan = r.records[b].plan
        item = plan.items[0]
        with self.assertRaises(ValueError):
            replace(item, context=list(item.context))
        with self.assertRaises(ValueError):
            replace(item, count=0)
        with self.assertRaises(ValueError):
            replace(plan, items=[item])
        with self.assertRaises(ValueError):
            replace(plan, items=(item, item))
        with self.assertRaises(ValueError):
            RequestSpec("B", (1,), 1, trace_id=0)

    def test_constructor_bounds_and_fixed_binding(self):
        with self.assertRaises(ValueError):
            RequestSpec("A", [1, 2], 1)
        with self.assertRaises(ValueError):
            RequestSpec("A", (True,), 1)
        with self.assertRaises(ValueError):
            Runtime([RequestSpec("A", (1,), 1)], ManualWorker("w"), output_global=0)
        with self.assertRaises(ValueError):
            Runtime(
                [RequestSpec("A", (1,), 1, binding=Binding(source_id="other"))],
                ManualWorker("w"),
            )


class ThreadRuntimeTests(unittest.TestCase):
    def test_real_cpu_threads_and_callback_publication(self):
        barrier = threading.Barrier(2)
        w = ThreadWorker("cpu-thread", before_compute=lambda p: barrier.wait(timeout=2))
        r = Runtime(
            [RequestSpec("A", (1,), 1), RequestSpec("B", (2,), 1)],
            w,
            pages=2,
            budget=2,
            max_items=1,
            output_global=2,
        )
        try:
            r.dispatch(0)
            r.dispatch(0)
            w.wait_all(timeout=3)
            self.assertEqual(r.poll(), 2)
            self.assertEqual(r.drain("A"), [(1, 2228)])
            self.assertEqual(r.drain("B"), [(1, 2229)])
            self.assertEqual(len(r.worker_threads), 2)
            self.assertNotIn(threading.get_ident(), r.worker_threads)
        finally:
            barrier.abort()
            r.close()
        self.assertTrue(w.stopped(w._stop_token))
        self.assertEqual(r.scheduler.held(), 0)

    def test_cancel_does_not_treat_running_future_as_stopped(self):
        entered = threading.Event()
        release = threading.Event()

        def held_compute(plan):
            entered.set()
            if not release.wait(timeout=3):
                raise TimeoutError("test release missing")

        w = ThreadWorker("held-cpu", before_compute=held_compute)
        r = Runtime([RequestSpec("A", (1,), 1)], w, pages=1, output_global=1)
        try:
            r.dispatch(0)
            self.assertTrue(entered.wait(timeout=2))
            r.cancel("A")
            self.assertEqual(r.snapshot()["allocated_pages"], 1)
            self.assertEqual(r.scheduler.held(), 1)
            self.assertFalse(w.futures[next(iter(w.futures))].cancel())
            release.set()
            w.wait_all()
            r.poll()
            self.assertEqual(r.scheduler.held(), 0)
            self.assertFalse(r.requests["A"].output)
        finally:
            release.set()
            r.close()
        self.assertTrue(w._joined)

    def test_thread_acceptance_ack_unknown_is_not_replayed(self):
        w = ThreadWorker("cpu-unknown")
        w.uncertain_next = True
        r = Runtime([RequestSpec("A", (1,), 1)], w, pages=1)
        try:
            b = r.dispatch(0)
            self.assertEqual(r.records[b].state, "ack_unknown")
            self.assertIsNone(r.dispatch(0))
            w.wait_all()
            r.poll()
            self.assertEqual(r.drain("A"), [(1, 2228)])
            self.assertEqual(len(w.futures), 1)
        finally:
            r.close()

    def test_future_wait_timeout_is_not_stop(self):
        entered = threading.Event()
        release = threading.Event()

        def held(plan):
            entered.set()
            if not release.wait(timeout=3):
                raise TimeoutError("bounded gate")

        w = ThreadWorker("cpu-timeout", before_compute=held)
        r = Runtime([RequestSpec("A", (1,), 1)], w, pages=1)
        try:
            r.dispatch(0)
            self.assertTrue(entered.wait(timeout=2))
            with self.assertRaises(TimeoutError):
                w.wait_all(timeout=0.001)
            self.assertEqual(r.snapshot()["allocated_pages"], 1)
            self.assertEqual(r.snapshot()["reserved_pages"], 1)
        finally:
            release.set()
            r.close()

    def test_cpu_exception_closes_without_success_or_error_body_leak(self):
        def fail(plan):
            raise RuntimeError("private diagnostic text")

        w = ThreadWorker("cpu-error", before_compute=fail)
        r = Runtime([RequestSpec("A", (1,), 1)], w, pages=1)
        try:
            r.dispatch(0)
            w.wait_all()
            r.poll()
            self.assertTrue(r.halted)
            self.assertEqual(r.requests["A"].reason, "worker_error")
            self.assertFalse(r.requests["A"].output)
            self.assertNotIn("private diagnostic", json.dumps(r.snapshot()))
        finally:
            r.close()

    def test_threaded_complete_flow_matches_known_recurrence(self):
        w = ThreadWorker("cpu-flow")
        r = Runtime(
            [RequestSpec("A", (1, 2), 3)],
            w,
            pages=2,
            budget=2,
            chunk=1,
            output_per_request=1,
            output_global=1,
        )
        try:
            for now in range(20):
                r.dispatch(now)
                w.wait_all()
                r.poll()
                r.drain("A")
                if r.requests["A"].reason:
                    break
            self.assertEqual(
                [x[1] for x in r.requests["A"].delivered], [29786, 492, 64944]
            )
            self.assertTrue(r.worker_threads)
            self.assertNotIn(threading.get_ident(), r.worker_threads)
        finally:
            r.close()
        self.assertTrue(all(f.done() for f in w.futures.values()))


class RuntimeCliTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(__file__).resolve().parents[1] / "reports" / "runtime-tests"
        self.root = self.base / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.script = Path(__file__).with_name("runtime_lab.py")

    def tearDown(self):
        resolved = self.root.resolve()
        if resolved.parent != self.base.resolve() or self.root.is_symlink():
            raise RuntimeError("cleanup boundary")
        shutil.rmtree(resolved)

    def test_fresh_report_and_existing_file_is_not_overwritten(self):
        path = self.root / "report.json"
        args = [
            sys.executable,
            str(self.script),
            "--scenario",
            "unknown_ack",
            "--output",
            str(path),
        ]
        first = subprocess.run(args, capture_output=True, text=True, timeout=10)
        self.assertEqual(first.returncode, 0, first.stderr)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(data["model_executed"])
        self.assertTrue(data["all_run_owned_threads_joined"])
        original = path.read_bytes()
        repeat = subprocess.run(args, capture_output=True, text=True, timeout=10)
        self.assertEqual(repeat.returncode, 2)
        self.assertEqual(path.read_bytes(), original)

    def test_optimized_mode_and_unknown_scenario_are_rejected(self):
        for extra in [
            ["-O", str(self.script)],
            [str(self.script), "--scenario", "gpu"],
        ]:
            path = self.root / (uuid.uuid4().hex + ".json")
            result = subprocess.run(
                [sys.executable, *extra, "--output", str(path)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
