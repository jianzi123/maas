"""Immutable CPU-worker messages and controlled manual/threaded adapters.

Token recurrence is synthetic integer arithmetic, not an LLM or device kernel.
The origin object is a local test capability, never a production signature.
"""

from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
import hashlib
import json
import threading
import time

if __package__:
    from .kv_lab import Lease
else:
    from kv_lab import Lease

VOCAB = 65521


class PreAcceptRejected(RuntimeError):
    """Adapter guarantees that this submission did not start."""


class SubmitUncertain(RuntimeError):
    """Acceptance may have happened; do not issue another attempt."""


@dataclass(frozen=True)
class Binding:
    source_id: str = "synthetic-source"
    model_release_uid: str = "synthetic-cr"
    release_revision: str = "synthetic-r1"
    publication_id: str = "synthetic-p1"
    activation_epoch: int = 1
    weights_revision: str = "synthetic-w1"
    engine_revision: str = "synthetic-e1"
    config_revision: str = "synthetic-c1"

    def __post_init__(self):
        if type(self.activation_epoch) is not int or self.activation_epoch < 1:
            raise ValueError("activation epoch")
        for name, value in asdict(self).items():
            if name != "activation_epoch" and (not isinstance(value, str) or not value):
                raise ValueError("empty binding")


@dataclass(frozen=True)
class WorkItem:
    request_id: str
    trace_id: str
    phase: str
    count: int
    pref_before: int
    generated_before: int
    decode_before: int
    context: tuple[int, ...]
    append_tokens: tuple[int, ...]
    emit: bool
    leases: tuple[Lease, ...]

    def __post_init__(self):
        if (
            not isinstance(self.request_id, str)
            or not self.request_id
            or not isinstance(self.trace_id, str)
            or not self.trace_id
        ):
            raise ValueError("work identity")
        if (
            self.phase not in ("prefill", "decode")
            or type(self.count) is not int
            or not 1 <= self.count <= 64
        ):
            raise ValueError("work phase/count")
        if any(
            type(x) is not int or x < 0
            for x in (self.pref_before, self.generated_before, self.decode_before)
        ):
            raise ValueError("work progress")
        if (
            not isinstance(self.context, tuple)
            or not isinstance(self.append_tokens, tuple)
            or len(self.append_tokens) != self.count
        ):
            raise ValueError("immutable work tokens")
        if any(
            type(t) is not int or not 0 <= t < VOCAB
            for t in self.context + self.append_tokens
        ):
            raise ValueError("synthetic work tokens")
        if (
            len(self.context) != self.pref_before + self.decode_before
            or type(self.emit) is not bool
        ):
            raise ValueError("work snapshot")
        if self.phase == "decode" and (self.count != 1 or not self.emit):
            raise ValueError("decode")
        if (
            not isinstance(self.leases, tuple)
            or not self.leases
            or any(not isinstance(l, Lease) for l in self.leases)
        ):
            raise ValueError("immutable leases")


@dataclass(frozen=True)
class BatchPlan:
    batch_id: str
    incarnation: str
    binding: Binding
    items: tuple[WorkItem, ...]

    def __post_init__(self):
        if (
            not isinstance(self.batch_id, str)
            or not self.batch_id
            or not isinstance(self.incarnation, str)
            or not self.incarnation
        ):
            raise ValueError("batch identity")
        if (
            not isinstance(self.binding, Binding)
            or not isinstance(self.items, tuple)
            or not 1 <= len(self.items) <= 64
        ):
            raise ValueError("immutable batch")
        if any(not isinstance(item, WorkItem) for item in self.items):
            raise ValueError("batch items")
        if len({item.request_id for item in self.items}) != len(self.items):
            raise ValueError("duplicate request in batch")

    @property
    def digest(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class Result:
    request_id: str
    kv_tokens: tuple
    output_token: object


@dataclass(frozen=True)
class Receipt:
    batch_id: str
    incarnation: str
    plan_digest: str
    results: tuple
    error: object
    thread_id: object
    origin: object

    @property
    def fingerprint(self):
        return digest(
            {
                "batch": self.batch_id,
                "incarnation": self.incarnation,
                "plan": self.plan_digest,
                "results": [asdict(r) for r in self.results],
                "error": self.error,
            }
        )


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def compute(plan):
    results = []
    for item in plan.items:
        state = 17
        for token in item.context + item.append_tokens:
            state = (state * 131 + token) % VOCAB
        results.append(
            Result(item.request_id, item.append_tokens, state if item.emit else None)
        )
    return tuple(results)


class ManualWorker:
    """Deterministic event fixture; no background task exists."""

    def __init__(self, incarnation, binding=Binding()):
        if not isinstance(incarnation, str) or not incarnation:
            raise ValueError("incarnation")
        self.incarnation = incarnation
        self.binding = binding
        self.origin = object()
        self._stop_token = None
        self.plans = {}
        self.completed = {}
        self.events = deque()
        self._lock = threading.RLock()
        self._published = threading.Condition(self._lock)
        self.closed = False
        self.reject_next = False
        self.uncertain_next = False

    def _accept(self, plan):
        if self.closed or self.reject_next:
            self.reject_next = False
            raise PreAcceptRejected("controlled pre-accept rejection")
        if plan.incarnation != self.incarnation or plan.binding != self.binding:
            raise PreAcceptRejected("worker binding mismatch")
        if plan.batch_id in self.plans:
            if self.plans[plan.batch_id].digest != plan.digest:
                raise ValueError("submission identity conflict")
            return False
        self.plans[plan.batch_id] = plan
        return True

    def submit(self, plan):
        with self._lock:
            fresh = self._accept(plan)
            if self.uncertain_next and fresh:
                self.uncertain_next = False
                raise SubmitUncertain("controlled lost acceptance ACK")
            return fresh

    def _record(self, plan, results, error=None, thread_id=None):
        with self._lock:
            if plan.batch_id in self.completed:
                return self.completed[plan.batch_id]
            r = Receipt(
                plan.batch_id,
                self.incarnation,
                plan.digest,
                tuple(results),
                error,
                thread_id,
                self.origin,
            )
            self.completed[plan.batch_id] = r
            self.events.append(r)
            self._published.notify_all()
            return r

    def complete(self, batch_id, *, error=None, results=None):
        with self._lock:
            if self.closed:
                raise ValueError("manual worker stopped")
            plan = self.plans[batch_id]
        return self._record(
            plan,
            compute(plan) if results is None and error is None else (results or ()),
            error,
            threading.get_ident(),
        )

    def replay(self, batch_id):
        with self._lock:
            self.events.append(self.completed[batch_id])

    def poll(self):
        with self._lock:
            result = list(self.events)
            self.events.clear()
            return result

    def verify(self, receipt):
        with self._lock:
            original = self.completed.get(receipt.batch_id)
            if receipt.origin is not self.origin or original is None:
                return False
            if original is receipt:
                return True
            try:
                return original.fingerprint == receipt.fingerprint
            except (TypeError, ValueError, AttributeError):
                return False

    def stop(self):
        with self._lock:
            self.closed = True
            if self._stop_token is None:
                self._stop_token = object()
            return self._stop_token

    def stopped(self, token):
        with self._lock:
            return (
                self.closed
                and self._stop_token is not None
                and token is self._stop_token
            )

    def close(self):
        return self.stop()


class ThreadWorker(ManualWorker):
    """Bounded real CPU executor; it only reads immutable copied token context."""

    def __init__(
        self, incarnation, binding=Binding(), max_workers=2, before_compute=None
    ):
        super().__init__(incarnation, binding)
        if type(max_workers) is not int or not 1 <= max_workers <= 4:
            raise ValueError("workers")
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="maas-cpu-lab"
        )
        self.futures = {}
        self.before_compute = before_compute
        self._joined = False

    def _execute(self, plan):
        thread_id = threading.get_ident()
        try:
            if self.before_compute is not None:
                self.before_compute(plan)
            return compute(plan), None, thread_id
        except Exception:
            return (), "synthetic_worker_error", thread_id

    def _done(self, plan, future):
        try:
            results, error, thread_id = future.result()
        except Exception:
            results = ()
            error = "synthetic_worker_cancelled"
            thread_id = None
        self._record(plan, results, error, thread_id)

    def submit(self, plan):
        with self._lock:
            fresh = self._accept(plan)
            if not fresh:
                return False
            try:
                future = self.executor.submit(self._execute, plan)
            except Exception:
                # Executor rejected before any Future/task was created.
                del self.plans[plan.batch_id]
                raise PreAcceptRejected("executor unavailable")
            self.futures[plan.batch_id] = future
            future.add_done_callback(lambda f: self._done(plan, f))
            if self.uncertain_next:
                self.uncertain_next = False
                raise SubmitUncertain("controlled lost acceptance ACK")
            return True

    def complete(self, *args, **kwargs):
        raise ValueError("thread completion must come from its Future")

    def wait_all(self, timeout=3):
        deadline = time.monotonic() + timeout
        with self._lock:
            futures = list(self.futures.values())
            batches = tuple(self.futures)
        _, pending = wait(futures, timeout=timeout)
        if pending:
            raise TimeoutError("bounded CPU tasks have not completed")
        with self._published:
            published = self._published.wait_for(
                lambda: all(batch in self.completed for batch in batches),
                timeout=max(0, deadline - time.monotonic()),
            )
            if not published:
                raise TimeoutError("completion publication not observed")
        return len(futures)

    def stop(self):
        with self._lock:
            self.closed = True
        self.executor.shutdown(wait=True, cancel_futures=True)
        with self._lock:
            self._joined = True
            if self._stop_token is None:
                self._stop_token = object()
            return self._stop_token

    def stopped(self, token):
        with self._lock:
            return (
                self.closed
                and self._joined
                and self._stop_token is token
                and all(f.done() for f in self.futures.values())
            )
