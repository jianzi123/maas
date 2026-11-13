"""Bounded CPU runtime integration scenarios; no GPU/model/API/cluster path."""

import argparse
import json
import os
from pathlib import Path
import threading
import uuid

if __package__:
    from .runtime_core import Runtime, RequestSpec
    from .runtime_worker import ManualWorker, ThreadWorker, Result
    from .kv_lab import PagePool
else:
    from runtime_core import Runtime, RequestSpec
    from runtime_worker import ManualWorker, ThreadWorker, Result
    from kv_lab import PagePool


class FaultPool(PagePool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0
        self.fail_on = None

    def allocate(self, owner):
        self.calls += 1
        if self.calls == self.fail_on:
            raise MemoryError("injected allocation failure")
        return super().allocate(owner)


def drive_manual(runtime, worker, max_rounds=64):
    for now in range(max_rounds):
        for _ in range(runtime.max_inflight):
            runtime.dispatch(now)
        for batch in reversed(list(worker.plans)):
            if batch not in worker.completed:
                worker.complete(batch)
        runtime.poll()
        for rid in runtime.requests:
            runtime.drain(rid)
        if all(
            s.reason is not None and s.busy is None for s in runtime.requests.values()
        ):
            return
    raise RuntimeError("bounded logical run did not finish")


def backpressure():
    w = ManualWorker("manual-backpressure")
    r = Runtime(
        [RequestSpec("A", (1,), 2), RequestSpec("B", (2,), 2)],
        w,
        pages=4,
        budget=2,
        max_items=1,
        output_per_request=1,
        output_global=2,
    )
    try:
        a, b = r.dispatch(0), r.dispatch(0)
        w.complete(b)
        w.complete(a)
        r.poll()
        assert r.dispatch(0) is None
        full = r.snapshot()
        assert full["output_queued"] == 2 and full["output_reserved"] == 0
        r.drain("A")
        r.drain("B")
        drive_manual(r, w)
        final = r.snapshot()
        assert [t for _, t in r.requests["A"].delivered] == [2228, 32012]
        assert [t for _, t in r.requests["B"].delivered] == [2229, 32144]
        return {"queue_full": full, "final": final, "out_of_order_completions": True}
    finally:
        r.close()


def cancel_and_reuse():
    w = ManualWorker("manual-cancel")
    r = Runtime(
        [RequestSpec("A", (1, 2), 3), RequestSpec("B", (9,), 1, arrival=1)],
        w,
        pages=2,
        budget=2,
        chunk=1,
        max_items=1,
    )
    try:
        old = r.dispatch(0)
        old_lease = r.records[old].plan.items[0].leases[0]
        r.cancel("A")
        held = r.snapshot()
        assert r.dispatch(1) is None
        assert held["reserved_pages"] == 2 and held["allocated_pages"] == 1
        w.complete(old)
        r.poll()
        released = r.snapshot()
        assert released["allocated_pages"] == released["reserved_pages"] == 0
        new = r.dispatch(1)
        lease = r.records[new].plan.items[0].leases[0]
        w.replay(old)
        r.poll()
        assert lease.page == old_lease.page and lease.generation > old_lease.generation
        assert r.pool.batches[new]["active"]
        w.complete(new)
        r.poll()
        r.drain("B")
        return {
            "cancelled_inflight": held,
            "after_completion": released,
            "successor_lease": [lease.page, lease.generation],
            "old_lease": [old_lease.page, old_lease.generation],
            "final": r.snapshot(),
        }
    finally:
        r.close()


def unknown_ack():
    w = ManualWorker("manual-unknown")
    w.uncertain_next = True
    r = Runtime([RequestSpec("A", (1,), 1)], w, pages=1)
    try:
        b = r.dispatch(0)
        unknown = r.snapshot()
        assert (
            r.records[b].state == "ack_unknown"
            and r.dispatch(0) is None
            and len(w.plans) == 1
        )
        w.complete(b)
        r.poll()
        r.drain("A")
        w.replay(b)
        r.poll()
        assert len(w.plans) == 1 and r.policy["A"].generated == 1
        return {
            "ack_unknown": unknown,
            "accepted_plan_count": len(w.plans),
            "final": r.snapshot(),
        }
    finally:
        r.close()


def stale_worker():
    old = ManualWorker("old-instance")
    r = Runtime(
        [RequestSpec("A", (1,), 1), RequestSpec("B", (2,), 1, arrival=1)],
        old,
        pages=1,
        max_items=1,
    )
    new = ManualWorker("new-instance")
    try:
        b = r.dispatch(0)
        r.replace_worker(new)
        old.complete(b)
        r.consume(old.completed[b])
        held = r.snapshot()
        assert (
            held["reserved_pages"] == held["allocated_pages"] == 1
            and r.dispatch(1) is None
        )
        token = old.stop()
        r.reap_stopped(old.incarnation, token)
        successor = r.dispatch(1)
        r.consume(old.completed[b])
        assert r.pool.batches[successor]["active"]
        new.complete(successor)
        r.poll()
        r.drain("B")
        return {
            "quarantined": held,
            "new_incarnation": new.incarnation,
            "final": r.snapshot(),
            "old_receipt_is_not_stop_proof": True,
        }
    finally:
        r.close()


def cow_rollback():
    pool = FaultPool(4, 2)
    w = ManualWorker("manual-cow")
    r = Runtime(
        [RequestSpec("A", (1, 2, 3), 1), RequestSpec("B", (1, 3, 4), 1)],
        w,
        pages=4,
        budget=4,
        chunk=2,
        pool=pool,
    )
    try:
        r.prime_prefix("A", (1,))
        r.share_prefix("A", "B")
        original = r.requests["A"].table[0]
        pool.fail_on = pool.calls + 2
        assert r.dispatch(0) is None
        rolled = r.snapshot()
        assert pool.data(original) == (1,) and pool.pages[original.page].owners == {
            "A",
            "B",
        }
        assert not w.plans
        pool.fail_on = None
        drive_manual(r, w)
        assert r.requests["A"].delivered == [(1, 36230)] and r.requests[
            "B"
        ].delivered == [(1, 36362)]
        return {
            "after_injected_oom": rolled,
            "original_shared_data": [1],
            "final": r.snapshot(),
        }
    finally:
        r.close()


def invalid_result():
    w = ManualWorker("manual-invalid")
    r = Runtime([RequestSpec("A", (1,), 1)], w, pages=1)
    try:
        b = r.dispatch(0)
        w.complete(b, results=(Result("wrong-request", (1,), 17),))
        r.poll()
        blocked = r.snapshot()
        assert blocked["halted"] and blocked["allocated_pages"] == 1
        token = w.stop()
        r.reap_stopped(w.incarnation, token)
        final = r.snapshot()
        assert final["allocated_pages"] == final["reserved_pages"] == 0
        return {
            "invalid_completion_quarantined": blocked,
            "after_independent_fixture_stop": final,
        }
    finally:
        r.close()


def threaded_flow():
    w = ThreadWorker("real-cpu-thread")
    r = Runtime(
        [RequestSpec("A", (1, 2), 3), RequestSpec("B", (9,), 2)],
        w,
        pages=4,
        budget=2,
        chunk=1,
        max_items=1,
        output_per_request=1,
        output_global=2,
    )
    try:
        for now in range(64):
            for _ in range(r.max_inflight):
                r.dispatch(now)
            w.wait_all(timeout=3)
            r.poll()
            for rid in r.requests:
                r.drain(rid)
            if all(s.reason is not None for s in r.requests.values()):
                break
        else:
            raise RuntimeError("bounded threaded flow did not finish")
        snapshot = r.snapshot()
        assert [v for _, v in r.requests["A"].delivered] == [29786, 492, 64944]
        assert r.worker_threads and threading.get_ident() not in r.worker_threads
        result = {
            "actual_cpu_executor": True,
            "compute_thread_count": len(r.worker_threads),
            "compute_is_synthetic_token_recurrence": True,
            "final": snapshot,
        }
    finally:
        r.close()
    assert w._joined and all(f.done() for f in w.futures.values())
    result["threads_joined_before_return"] = True
    return result


SCENARIOS = {
    "backpressure": backpressure,
    "cancel_reuse": cancel_and_reuse,
    "unknown_ack": unknown_ack,
    "stale_worker": stale_worker,
    "cow_rollback": cow_rollback,
    "invalid_result": invalid_result,
    "threaded": threaded_flow,
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--scenario", choices=["all", *SCENARIOS], default="all")
    args = p.parse_args()
    if not __debug__:
        p.error("normal Python invariant checks required")
    if args.output.exists():
        p.error("choose a fresh output filename")
    results = {
        name: fn() for name, fn in SCENARIOS.items() if args.scenario in ("all", name)
    }
    report = {
        "schema_version": "cpu-runtime-integration-1.0",
        "synthetic_inputs": True,
        "evidence_kind": "controlled_cpu_runtime_and_manual_fault_fixtures",
        "gpu_executed": False,
        "model_executed": False,
        "platform_api_executed": False,
        "authority": "teaching_only_no_admission_settlement_refund_or_device_close_proof",
        "manual_completion_and_stop_are_fixtures": True,
        "no_latency_or_throughput_claim": True,
        "all_run_owned_threads_joined": True,
        "results": results,
    }
    encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(
        args.output.name + "." + uuid.uuid4().hex + ".tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as f:
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        os.link(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "scenarios": list(results),
                "gpu_executed": False,
                "threads_joined": True,
                "output": args.output.name,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
