"""Single-owner CPU runtime integrating conservative scheduling, KV leases and workers.

No model, GPU, gateway, budget ledger or public protocol is implemented here.
"""

from collections import Counter, deque
from dataclasses import dataclass, field
import threading
import uuid

if __package__:
    from .kv_lab import PagePool
    from .scheduler_lab import Scheduler
    from .runtime_worker import (
        Binding,
        BatchPlan,
        WorkItem,
        Receipt,
        Result,
        PreAcceptRejected,
        VOCAB,
    )
else:
    from kv_lab import PagePool
    from scheduler_lab import Scheduler
    from runtime_worker import (
        Binding,
        BatchPlan,
        WorkItem,
        Receipt,
        Result,
        PreAcceptRejected,
        VOCAB,
    )

ACTIVE = frozenset(("submitted", "ack_unknown", "quarantined"))


@dataclass(frozen=True)
class RequestSpec:
    request_id: str
    prompt: tuple
    output_cap: int
    arrival: int = 0
    binding: Binding = Binding()
    trace_id: str = ""

    def __post_init__(self):
        if not isinstance(self.request_id, str) or not 1 <= len(self.request_id) <= 64:
            raise ValueError("request identity")
        if not isinstance(self.prompt, tuple) or not 1 <= len(self.prompt) <= 64:
            raise ValueError("bounded immutable prompt")
        if any(type(t) is not int or not 0 <= t < VOCAB for t in self.prompt):
            raise ValueError("synthetic token IDs")
        if type(self.output_cap) is not int or not 1 <= self.output_cap <= 64:
            raise ValueError("output cap")
        if type(self.arrival) is not int or self.arrival < 0:
            raise ValueError("arrival")
        if not isinstance(self.binding, Binding):
            raise ValueError("binding")
        if not isinstance(self.trace_id, str):
            raise ValueError("trace")
        if self.trace_id == "":
            object.__setattr__(self, "trace_id", "trace:" + self.request_id)


@dataclass
class RequestState:
    spec: RequestSpec
    table: list = field(default_factory=list)
    output: deque = field(default_factory=deque)
    delivered: list = field(default_factory=list)
    busy: object = None
    last_token: object = None
    detached: bool = False
    cancel_requested: bool = False
    reason: object = None


@dataclass
class Record:
    plan: BatchPlan
    state: str
    credit_ids: tuple
    receipt_hash: object = None


class Runtime:
    def __init__(
        self,
        specs,
        worker,
        *,
        pages=16,
        page_tokens=2,
        budget=4,
        chunk=2,
        max_items=2,
        max_inflight=2,
        output_per_request=2,
        output_global=4,
        pool=None,
    ):
        if not __debug__:
            raise ValueError("invariant checks require normal Python mode")
        if not 1 <= len(specs) <= 32 or any(
            not isinstance(s, RequestSpec) for s in specs
        ):
            raise ValueError("bounded request set")
        if len({s.request_id for s in specs}) != len(specs):
            raise ValueError("duplicate identity")
        limits = (max_items, max_inflight, output_per_request, output_global)
        if any(type(x) is not int or not 1 <= x <= 64 for x in limits):
            raise ValueError("bounded runtime limits")
        if worker.plans or worker.closed:
            raise ValueError("fresh worker required")
        if any(s.binding != worker.binding for s in specs):
            raise ValueError("fixed source/revision binding")
        self.actor = threading.get_ident()
        self.binding = worker.binding
        self.pool = pool if pool is not None else PagePool(pages, page_tokens)
        if (
            len(self.pool.pages) != pages
            or self.pool.page_tokens != page_tokens
            or len(self.pool.free) != pages
            or self.pool.batches
        ):
            raise ValueError("fresh matching page pool")
        self.scheduler = Scheduler(
            [(s.request_id, s.arrival, len(s.prompt), s.output_cap) for s in specs],
            pages=pages,
            page_tokens=page_tokens,
            budget=budget,
            chunk=chunk,
        )
        self.policy = {r.id: r for r in self.scheduler.requests}
        self.requests = {s.request_id: RequestState(s) for s in specs}
        self.worker = worker
        self.workers = {worker.incarnation: worker}
        self.records = {}
        self.max_items = max_items
        self.max_inflight = max_inflight
        self.output_per_request = output_per_request
        self.output_global = output_global
        self.halted = False
        self.serial = 0
        self.session = uuid.uuid4().hex[:12]
        self.events = deque(maxlen=512)
        self.diagnostics = Counter()
        self.worker_threads = set()
        self.max_allocated = 0
        self.max_queued = 0
        self.max_credits = 0
        self.assert_invariants()

    def _actor(self):
        if threading.get_ident() != self.actor:
            raise RuntimeError("runtime mutations belong to its actor")

    def _note(self, event, **fields):
        self.events.append({"event": event, **fields})

    def _pending(self):
        return [r for r in self.records.values() if r.state in ACTIVE]

    def _credits(self, request_id=None):
        return sum(
            sum(1 for x in b.credit_ids if request_id is None or x == request_id)
            for b in self._pending()
        )

    def _queued(self):
        return sum(len(r.output) for r in self.requests.values())

    def _observe_pages(self):
        self.max_allocated = max(
            self.max_allocated, len(self.pool.pages) - len(self.pool.free)
        )

    def _context(self, state):
        return tuple(t for lease in state.table for t in self.pool.data(lease))

    def _detach(self, state):
        if not state.detached:
            for lease in state.table:
                self.pool.release(state.spec.request_id, lease)
            state.detached = True

    def _cancel_quiet(self, state, reason):
        self._detach(state)
        self.scheduler.cancel(state.spec.request_id)
        state.reason = reason
        state.table.clear()

    def prime_prefix(self, request_id, tokens):
        self._actor()
        state = self.requests[request_id]
        r = self.policy[request_id]
        if (
            r.admitted
            or state.busy
            or not isinstance(tokens, tuple)
            or not 0 < len(tokens) < len(state.spec.prompt)
        ):
            raise ValueError("prefix state")
        if tokens != state.spec.prompt[: len(tokens)]:
            raise ValueError("prefix token mismatch")
        if self.scheduler.held() + self.scheduler.reserve(r) > self.scheduler.pages:
            raise MemoryError("capacity envelope")
        r.admitted = True
        try:
            for pos, token in enumerate(tokens):
                if pos % self.pool.page_tokens == 0:
                    state.table.append(self.pool.allocate(request_id))
                    self._observe_pages()
                self.pool.append(request_id, state.table[-1], token)
        except Exception:
            self._detach(state)
            state.table.clear()
            state.detached = False
            r.admitted = False
            raise
        r.pref = len(tokens)
        self.assert_invariants()

    def share_prefix(self, source, target):
        self._actor()
        a = self.requests[source]
        b = self.requests[target]
        ra, rb = self.policy[source], self.policy[target]
        if (
            a.busy
            or a.reason
            or not ra.admitted
            or ra.generated
            or not ra.pref
            or rb.admitted
            or b.table
        ):
            raise ValueError("prefix state")
        if (
            not ra.pref < len(b.spec.prompt)
            or b.spec.prompt[: ra.pref] != a.spec.prompt[: ra.pref]
        ):
            raise ValueError("prefix mismatch")
        if self.scheduler.held() + self.scheduler.reserve(rb) > self.scheduler.pages:
            raise MemoryError("capacity envelope")
        rb.admitted = True
        shared = []
        try:
            for lease in a.table:
                self.pool.share(source, lease, target)
                shared.append(lease)
        except Exception:
            for lease in shared:
                self.pool.release(target, lease)
            rb.admitted = False
            raise
        b.table = shared
        rb.pref = ra.pref
        self.assert_invariants()

    def _rollback(self, snapshots):
        for rid, (old_table, old_admitted, old_detached) in snapshots.items():
            state = self.requests[rid]
            for lease in old_table:
                page = self.pool._page(lease)
                if rid not in page.owners:
                    self.pool.share(next(iter(page.owners)), lease, rid)
            for lease in set(state.table) - set(old_table):
                self.pool.release(rid, lease)
            state.table = list(old_table)
            state.detached = old_detached
            self.policy[rid].admitted = old_admitted

    def dispatch(self, now):
        self._actor()
        if self.halted or len(self._pending()) >= self.max_inflight:
            return None
        excluded = {
            rid
            for rid, s in self.requests.items()
            if s.busy
            or s.cancel_requested
            or s.reason
            or len(s.output) + self._credits(rid) >= self.output_per_request
        }
        work, next_cursor = self.scheduler.preview(now, excluded)
        selected = []
        credits = []
        free_output = self.output_global - self._queued() - self._credits()
        for rid, phase, count in work:
            state = self.requests[rid]
            r = self.policy[rid]
            emit = phase == "decode" or r.pref + count == r.input_tokens
            if emit and free_output <= 0:
                continue
            selected.append((rid, phase, count, emit))
            if emit:
                credits.append(rid)
                free_output -= 1
            if len(selected) == self.max_items:
                break
        if not selected:
            return None
        self.serial += 1
        batch = f"{self.session}:{self.serial}"
        snapshots = {
            rid: (
                tuple(self.requests[rid].table),
                self.policy[rid].admitted,
                self.requests[rid].detached,
            )
            for rid, _, _, _ in selected
        }
        items = []
        try:
            for rid, phase, count, emit in selected:
                state = self.requests[rid]
                r = self.policy[rid]
                context = self._context(state)
                if len(context) != r.pref + r.decode_steps:
                    raise RuntimeError("KV/progress mismatch")
                r.admitted = True
                if state.table and len(context) % self.pool.page_tokens:
                    tail = state.table[-1]
                    if self.pool._page(tail).owners != {rid}:
                        state.table[-1] = self.pool.clone_for_write(rid, tail)
                        self._observe_pages()
                needed = (
                    len(context) + count + self.pool.page_tokens - 1
                ) // self.pool.page_tokens
                while len(state.table) < needed:
                    state.table.append(self.pool.allocate(rid))
                    self._observe_pages()
                tokens = (
                    state.spec.prompt[r.pref : r.pref + count]
                    if phase == "prefill"
                    else (state.last_token,)
                )
                if any(type(t) is not int for t in tokens):
                    raise RuntimeError("missing decode token")
                items.append(
                    WorkItem(
                        rid,
                        state.spec.trace_id,
                        phase,
                        count,
                        r.pref,
                        r.generated,
                        r.decode_steps,
                        context,
                        tokens,
                        emit,
                        tuple(state.table),
                    )
                )
            plan = BatchPlan(batch, self.worker.incarnation, self.binding, tuple(items))
            self.pool.submit(
                batch,
                tuple(
                    (item.request_id, lease) for item in items for lease in item.leases
                ),
            )
        except Exception as exc:
            if self.pool.batches.get(batch, {}).get("active"):
                self.pool.complete(batch)
            self._rollback(snapshots)
            self.diagnostics[type(exc).__name__] += 1
            self._note("staging_rejected", reason=type(exc).__name__)
            self.assert_invariants()
            if not isinstance(exc, (MemoryError, ValueError)):
                raise
            return None
        record = Record(plan, "submitted", tuple(credits))
        self.records[batch] = record
        for item in items:
            self.requests[item.request_id].busy = batch
        self._note(
            "submit",
            batch=batch,
            requests=[i.request_id for i in items],
            plan=plan.digest,
        )
        self.assert_invariants()
        try:
            self.worker.submit(plan)
        except PreAcceptRejected:
            record.state = "rejected"
            self.pool.complete(batch)
            for item in items:
                self.requests[item.request_id].busy = None
            self._rollback(snapshots)
            self.diagnostics["pre_accept_rejected"] += 1
            self._note("pre_accept_rejected", batch=batch)
            self.assert_invariants()
            return None
        except Exception:
            # Only the typed pre-accept guarantee permits rollback.
            record.state = "ack_unknown"
            self.diagnostics["acceptance_unknown"] += 1
            self._note("acceptance_unknown", batch=batch)
        self.scheduler.cursor = next_cursor
        self.assert_invariants()
        return batch

    def cancel(self, request_id):
        self._actor()
        s = self.requests[request_id]
        if s.cancel_requested:
            return False
        s.cancel_requested = True
        s.output.clear()
        if s.busy:
            self._detach(s)
            self._note("cancel_inflight", request=request_id, batch=s.busy)
        else:
            self._cancel_quiet(s, "cancelled")
            self._note("cancel_quiet", request=request_id)
        self.assert_invariants()
        return True

    def _fault(self, reason):
        self.halted = True
        self.diagnostics[reason] += 1
        for rec in self._pending():
            if rec.plan.incarnation == self.worker.incarnation:
                rec.state = "quarantined"
        for s in self.requests.values():
            if s.busy:
                s.cancel_requested = True
                s.output.clear()
                self._detach(s)
            elif self.policy[s.spec.request_id].admitted and not s.reason:
                s.cancel_requested = True
                s.output.clear()
                self._cancel_quiet(s, "worker_error")
        self._note("worker_fault", reason=reason)

    def _valid_result(self, record, event):
        if event.plan_digest != record.plan.digest or not isinstance(
            event.results, tuple
        ):
            return False
        if event.error is not None:
            return (
                isinstance(event.error, str) and bool(event.error) and not event.results
            )
        if len(event.results) != len(record.plan.items):
            return False
        for item, result in zip(record.plan.items, event.results):
            if not isinstance(result, Result):
                return False
            if (
                result.request_id != item.request_id
                or result.kv_tokens != item.append_tokens
            ):
                return False
            if item.emit:
                if (
                    type(result.output_token) is not int
                    or not 0 <= result.output_token < VOCAB
                ):
                    return False
            elif result.output_token is not None:
                return False
            r = self.policy[item.request_id]
            if (r.pref, r.generated, r.decode_steps) != (
                item.pref_before,
                item.generated_before,
                item.decode_before,
            ):
                return False
        return True

    def consume(self, event):
        self._actor()
        if not isinstance(event, Receipt):
            self.diagnostics["invalid_message"] += 1
            return False
        record = self.records.get(event.batch_id)
        if record is None:
            self.diagnostics["unknown_batch"] += 1
            return False
        if (
            event.incarnation != self.worker.incarnation
            or event.incarnation != record.plan.incarnation
        ):
            self.diagnostics["stale_incarnation"] += 1
            return False
        if not self.worker.verify(event):
            self.diagnostics["unverified_receipt"] += 1
            return False
        try:
            fingerprint = event.fingerprint
        except (TypeError, ValueError, AttributeError):
            self._fault("invalid_completion_payload")
            self.assert_invariants()
            return False
        if record.state == "completed":
            if record.receipt_hash == fingerprint:
                self.diagnostics["duplicate_completion"] += 1
                return False
            self._fault("conflicting_completion")
            self.assert_invariants()
            return False
        if record.state not in ACTIVE:
            self._fault("completion_after_rejection")
            self.assert_invariants()
            return False
        if record.state == "quarantined":
            self.diagnostics["quarantined_receipt"] += 1
            return False
        if not self._valid_result(record, event):
            self._fault("invalid_completion_payload")
            self.assert_invariants()
            return False
        # Adapter completion is observed before releasing its modeled pins.
        self.pool.complete(event.batch_id)
        record.state = "completed"
        record.receipt_hash = fingerprint
        if type(event.thread_id) is int:
            self.worker_threads.add(event.thread_id)
        for index, item in enumerate(record.plan.items):
            s = self.requests[item.request_id]
            r = self.policy[item.request_id]
            s.busy = None
            if s.cancel_requested or event.error is not None:
                s.output.clear()
                self._cancel_quiet(
                    s, "cancelled" if s.cancel_requested else "worker_error"
                )
                continue
            result = event.results[index]
            position = r.pref + r.decode_steps
            for token in result.kv_tokens:
                self.pool.append(
                    item.request_id, s.table[position // self.pool.page_tokens], token
                )
                position += 1
            if item.phase == "prefill":
                r.pref += item.count
            else:
                r.decode_steps += 1
            if item.emit:
                r.generated += 1
                s.last_token = result.output_token
                s.output.append((r.generated, result.output_token))
            if r.generated == r.output_cap:
                r.finished = True
                s.reason = "completed"
                self._detach(s)
                s.table.clear()
        self._note("complete", batch=event.batch_id, reason=event.error or "ok")
        if event.error is not None:
            self._fault("worker_compute_error")
        self.assert_invariants()
        return True

    def poll(self):
        self._actor()
        return sum(self.consume(event) for event in self.worker.poll())

    def drain(self, request_id, limit=None):
        self._actor()
        s = self.requests[request_id]
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError("drain limit")
        result = []
        while s.output and (limit is None or len(result) < limit):
            value = s.output.popleft()
            s.delivered.append(value)
            result.append(value)
        self.assert_invariants()
        return result

    def replace_worker(self, new_worker):
        self._actor()
        if new_worker.binding != self.binding:
            raise ValueError("cross-source/revision replacement")
        if (
            new_worker.incarnation in self.workers
            or new_worker.plans
            or new_worker.closed
        ):
            raise ValueError("fresh unique worker incarnation")
        old = self.worker
        self._fault("worker_replaced")
        self.workers[new_worker.incarnation] = new_worker
        self.worker = new_worker
        self.halted = False
        self._note("replace_worker", old=old.incarnation, new=new_worker.incarnation)
        self.assert_invariants()

    def reap_stopped(self, incarnation, token):
        self._actor()
        worker = self.workers[incarnation]
        if not worker.stopped(token):
            raise ValueError("worker not independently quiescent")
        if worker is self.worker:
            self.halted = True
        count = 0
        for record in self._pending():
            if record.plan.incarnation != incarnation:
                continue
            self.pool.complete(record.plan.batch_id)
            record.state = "stopped"
            count += 1
            for item in record.plan.items:
                s = self.requests[item.request_id]
                s.busy = None
                s.cancel_requested = True
                s.output.clear()
                self._cancel_quiet(s, "worker_stopped")
            self._note(
                "reap_stopped", batch=record.plan.batch_id, incarnation=incarnation
            )
        self.assert_invariants()
        return count

    def assert_invariants(self):
        self.pool.assert_invariants()
        allocated = len(self.pool.pages) - len(self.pool.free)
        if not allocated <= self.scheduler.held() <= self.scheduler.pages:
            raise RuntimeError("capacity invariant")
        if self._queued() + self._credits() > self.output_global:
            raise RuntimeError("global output invariant")
        for rid, s in self.requests.items():
            if len(s.output) + self._credits(rid) > self.output_per_request:
                raise RuntimeError("request output invariant")
            if s.busy:
                rec = self.records[s.busy]
                if rec.state not in ACTIVE or rid not in [
                    i.request_id for i in rec.plan.items
                ]:
                    raise RuntimeError("busy ownership")
        for rec in self._pending():
            if not self.pool.batches[rec.plan.batch_id]["active"]:
                raise RuntimeError("lost batch pin")
            for item in rec.plan.items:
                if self.requests[item.request_id].busy != rec.plan.batch_id:
                    raise RuntimeError("request in two batches")
        self.max_allocated = max(self.max_allocated, allocated)
        self.max_queued = max(self.max_queued, self._queued())
        self.max_credits = max(self.max_credits, self._credits())
        return True

    def snapshot(self):
        self._actor()
        self.assert_invariants()
        return {
            "binding": self.binding.__dict__.copy(),
            "current_worker": self.worker.incarnation,
            "halted": self.halted,
            "reserved_pages": self.scheduler.held(),
            "allocated_pages": len(self.pool.pages) - len(self.pool.free),
            "output_queued": self._queued(),
            "output_reserved": self._credits(),
            "pending_batches": len(self._pending()),
            "peak_allocated_pages": self.max_allocated,
            "peak_output_queued": self.max_queued,
            "peak_output_reserved": self.max_credits,
            "diagnostics": dict(self.diagnostics),
            "requests": {
                rid: {
                    "trace_id": s.spec.trace_id,
                    "prefilled": self.policy[rid].pref,
                    "generated": self.policy[rid].generated,
                    "decode_steps": self.policy[rid].decode_steps,
                    "busy": s.busy,
                    "reason": s.reason,
                    "cancel_requested": s.cancel_requested,
                    "queued": list(s.output),
                    "delivered": list(s.delivered),
                    "output_drained": s.reason is not None
                    and not s.output
                    and s.busy is None,
                    "leases": [[l.page, l.generation] for l in s.table],
                }
                for rid, s in self.requests.items()
            },
            "events": list(self.events),
        }

    def close(self):
        self._actor()
        for rid, state in self.requests.items():
            if state.reason is None:
                self.cancel(rid)
        for incarnation, worker in self.workers.items():
            token = worker.close()
            self.reap_stopped(incarnation, token)
