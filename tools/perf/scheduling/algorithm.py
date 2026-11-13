"""Complete bounded host scheduling algorithm with exact page IDs and synthetic lengths.

All times named 'round' are logical; CPU planning_ns measures host overhead only.
"""

from dataclasses import dataclass, field, asdict
from collections import Counter
from time import perf_counter_ns

if __package__:
    from .pages import Pages
else:
    from pages import Pages


@dataclass(frozen=True)
class Limits:
    page_tokens: int = 16
    kv_budget_bytes: int = 805306368
    kv_bytes_per_token: int = 24576
    batch_tokens: int = 256
    activation_budget_bytes: int = 16777216
    activation_bytes_per_position: int = 65536
    max_batch_items: int = 32
    max_active: int = 32
    queue_capacity: int = 256
    quantum: int = 64
    prefill_age: int = 8
    admission_age: int = 16
    horizon: int = 20000

    def __post_init__(self):
        for k, v in asdict(self).items():
            if type(v) is not int or v <= 0:
                raise ValueError("positive integer " + k)
        if (
            self.horizon > 50000
            or not 1 <= self.capacity <= 8192
            or self.max_active > 256
        ):
            raise ValueError("bounded lab limits")

    @property
    def capacity(self):
        return self.kv_budget_bytes // (self.kv_bytes_per_token * self.page_tokens)

    @property
    def effective_tokens(self):
        return min(
            self.batch_tokens,
            self.activation_budget_bytes // self.activation_bytes_per_position,
        )


@dataclass(frozen=True)
class Entry:
    id: str
    shape: str
    input_tokens: int
    output_cap: int
    arrival_round: int
    prefix_key: object = None
    cancel_round: object = None
    fail_after: object = None
    lose_release: bool = False

    def __post_init__(self):
        if (
            not isinstance(self.id, str)
            or not self.id
            or self.shape not in ("S", "M", "L", "X")
        ):
            raise ValueError("identity/shape")
        for name in ("input_tokens", "output_cap"):
            if (
                type(getattr(self, name)) is not int
                or not 1 <= getattr(self, name) <= 16384
            ):
                raise ValueError(name)
        if type(self.arrival_round) is not int or self.arrival_round < 0:
            raise ValueError("arrival")
        for v in (self.cancel_round, self.fail_after):
            if v is not None and (type(v) is not int or v < 0):
                raise ValueError("fault round/count")
        if self.prefix_key is not None and (
            not isinstance(self.prefix_key, str) or not self.prefix_key
        ):
            raise ValueError("prefix key")
        if type(self.lose_release) is not bool:
            raise ValueError("lose_release")


@dataclass
class Request:
    entry: Entry
    status: str = "queued"
    pref: int = 0
    generated: int = 0
    decode: int = 0
    reserved: int = 0
    table: list = field(default_factory=list)
    admitted_round: object = None
    first_round: object = None
    last_round: object = None
    end_round: object = None
    steps: int = 0
    last_service: object = None
    reason: object = None
    max_wait: int = 0
    decode_gap_max: int = 0

    @property
    def id(self):
        return self.entry.id

    @property
    def position(self):
        return self.pref + self.decode


def quantile(values, q):
    if not values:
        return None
    v = sorted(values)
    x = (len(v) - 1) * q
    i = int(x)
    j = min(i + 1, len(v) - 1)
    return v[i] + (v[j] - v[i]) * (x - i)


def finite_chunks(progress, remaining, limit, page):
    if remaining <= limit:
        return remaining
    return max(0, ((progress + limit) // page) * page - progress)


class Engine:
    POLICIES = ("static", "adaptive", "age_fair", "no_age")

    def __init__(
        self, entries, limits=Limits(), *, prefixes=None, policy="age_fair", chunk=128
    ):
        if policy not in self.POLICIES or type(chunk) is not int or chunk <= 0:
            raise ValueError("policy/chunk")
        if not 1 <= len(entries) <= 2000 or len({e.id for e in entries}) != len(
            entries
        ):
            raise ValueError("bounded unique workload")
        self.limits = limits
        self.policy = policy
        self.chunk = chunk
        self.pool = Pages(limits.capacity, limits.page_tokens, prefixes or {})
        if self.pool.cache_pages >= limits.capacity:
            raise ValueError("no private page capacity")
        self.requests = [Request(e) for e in entries]
        self.metrics = Counter()
        for r in self.requests:
            if r.entry.prefix_key is not None:
                if r.entry.prefix_key not in self.pool.prefixes:
                    raise ValueError("unknown prefix")
                if self.pool.prefixes[r.entry.prefix_key][0] >= r.entry.input_tokens:
                    raise ValueError("prefix must leave new input")
        self.trace = []
        self.planning_ns = []
        self.peak_reserved = 0
        self.prefill_remaining = 0

    @property
    def reserved(self):
        return sum(
            r.reserved for r in self.requests if r.status in ("active", "unrecovered")
        )

    def _close(self, r, status, now, reason=None):
        self.pool.release(r.table, r.id)
        r.table = []
        r.reserved = 0
        r.status = status
        r.end_round = now
        r.reason = reason

    def _admit(self, now):
        waiting = sorted(
            [
                r
                for r in self.requests
                if r.status == "queued" and r.entry.arrival_round <= now
            ],
            key=lambda r: (r.entry.arrival_round, r.id),
        )
        for r in waiting:
            if r.entry.cancel_round is not None and now >= r.entry.cancel_round:
                r.status = "cancelled"
                r.end_round = now
                r.reason = "cancel_before_admission"
        waiting = [r for r in waiting if r.status == "queued"]
        for r in waiting[self.limits.queue_capacity :]:
            r.status = "rejected"
            r.end_round = now
            r.reason = "queue_capacity"
        waiting = waiting[: self.limits.queue_capacity]
        active_count = sum(r.status == "active" for r in self.requests)
        held = self.reserved
        for r in waiting:
            e = r.entry
            prefix = 0 if e.prefix_key is None else self.pool.prefixes[e.prefix_key][0]
            n = self.pool.reserve_private(e.input_tokens, e.output_cap, e.prefix_key)
            if self.pool.cache_pages + n > self.limits.capacity:
                r.status = "rejected"
                r.reason = "individual_kv_envelope"
                r.end_round = now
                continue
            maxchunk = (
                self.chunk
                if self.policy == "static"
                else (
                    self.limits.quantum
                    if self.policy in ("age_fair", "no_age")
                    else self.limits.batch_tokens
                )
            )
            if not finite_chunks(
                prefix,
                e.input_tokens - prefix,
                min(self.limits.effective_tokens, maxchunk),
                self.pool.size,
            ):
                r.status = "rejected"
                r.reason = "no_feasible_aligned_chunk"
                r.end_round = now
                continue
            if active_count >= self.limits.max_active:
                break
            if self.pool.cache_pages + held + n > self.limits.capacity:
                self.metrics["admission_capacity_wait"] += 1
                # An old request creates an admission drain barrier, never evicting active KV.
                if (
                    self.policy == "age_fair"
                    and now - e.arrival_round >= self.limits.admission_age
                ):
                    self.metrics["aged_admission_barrier"] += 1
                    break
                continue
            r.table, r.pref = self.pool.attach(e.prefix_key, r.id)
            r.reserved = n
            r.status = "active"
            r.admitted_round = now
            r.last_service = now - 1
            active_count += 1
            held += n

    def _choose(self, now):
        active = [r for r in self.requests if r.status == "active"]
        pref = [r for r in active if r.pref < r.entry.input_tokens]
        decode = [r for r in active if r.pref == r.entry.input_tokens]
        key = lambda r: (r.last_service, r.entry.arrival_round, r.id)
        decode.sort(key=key)
        fair = self.policy in ("age_fair", "no_age")
        if fair:
            pref.sort(
                key=lambda r: (
                    (
                        0
                        if self.policy == "age_fair"
                        and now - r.last_service >= self.limits.prefill_age
                        else 1
                    ),
                    (
                        r.last_service
                        if self.policy == "age_fair"
                        and now - r.last_service >= self.limits.prefill_age
                        else r.entry.input_tokens - r.pref
                    ),
                    r.entry.arrival_round,
                    r.id,
                )
            )
        else:
            pref.sort(key=lambda r: (r.entry.arrival_round, r.id))
        remaining = self.limits.effective_tokens
        actions = []
        # Reserve the minimum page-aligned progress for one feasible prefill when mixing.
        floor = 0
        if fair and pref:
            floor = next(
                (
                    n
                    for r in pref
                    if (
                        n := finite_chunks(
                            r.pref,
                            r.entry.input_tokens - r.pref,
                            min(remaining, self.pool.size),
                            self.pool.size,
                        )
                    )
                ),
                0,
            )
        # If one batch cannot host BOTH phases, alternate phase opportunity.
        # Reserving the entire budget for prefill forever would starve decode.
        if (
            fair
            and pref
            and decode
            and (remaining <= floor or self.limits.max_batch_items == 1)
        ):
            if now % 2 == 0:
                floor = 0
                pref = []
            else:
                decode = []
        for r in decode[
            : max(
                0,
                min(
                    self.limits.max_batch_items - (1 if floor else 0), remaining - floor
                ),
            )
        ]:
            actions.append((r, "decode", 1))
            remaining -= 1
        for r in pref:
            if remaining <= 0 or len(actions) >= self.limits.max_batch_items:
                break
            if self.policy == "static":
                target = self.chunk
            elif self.policy == "adaptive":
                target = max(self.pool.size, remaining // max(1, len(pref)))
            else:
                target = self.limits.quantum
            n = finite_chunks(
                r.pref,
                r.entry.input_tokens - r.pref,
                min(remaining, target),
                self.pool.size,
            )
            if n <= 0:
                self.metrics["no_feasible_chunk_wait"] += 1
                continue
            actions.append((r, "prefill", n))
            remaining -= n
        return actions

    def step(self, now, *, audit=False):
        begin = perf_counter_ns()
        for r in self.requests:
            if (
                r.status == "active"
                and r.entry.cancel_round is not None
                and now >= r.entry.cancel_round
            ):
                self._close(r, "cancelled", now, "cancel_at_synchronous_boundary")
        self._admit(now)
        actions = self._choose(now)
        self.planning_ns.append(perf_counter_ns() - begin)
        active_count = sum(r.status == "active" for r in self.requests)
        used_tokens = sum(n for _, _, n in actions)
        if (
            used_tokens > self.limits.effective_tokens
            or len(actions) > self.limits.max_batch_items
        ):
            raise RuntimeError("batch constraints")
        for r, phase, n in actions:
            wait = now - r.last_service
            r.max_wait = max(r.max_wait, wait)
            if phase == "decode":
                r.decode_gap_max = max(r.decode_gap_max, wait)
            self.pool.append(r.table, r.position, n, r.id)
            if phase == "prefill":
                r.pref += n
            else:
                r.decode += 1
            if phase == "decode" or r.pref == r.entry.input_tokens:
                r.generated += 1
                if r.first_round is None:
                    r.first_round = now
            r.last_round = now
            r.last_service = now
            r.steps += 1
        physical = self.pool.used
        reserved = self.reserved
        self.peak_reserved = max(self.peak_reserved, reserved + self.pool.cache_pages)
        if (
            physical > reserved + self.pool.cache_pages
            or reserved + self.pool.cache_pages > self.limits.capacity
        ):
            raise RuntimeError("KV constraints")
        if audit:
            self.pool.verify(self.requests, reserved)
        for r, _, _ in actions:
            if r.entry.fail_after is not None and r.steps >= r.entry.fail_after:
                if r.entry.lose_release:
                    r.status = "unrecovered"
                    r.reason = "synthetic_missing_release"
                    r.end_round = None
                else:
                    self._close(r, "failed", now, "synthetic_compute_failure")
            elif r.generated == r.entry.output_cap:
                self._close(r, "completed", now)
        if self.limits.horizon <= 2048 or now < 32 or now % 128 == 0:
            self.trace.append(
                {
                    "round": now,
                    "work": [[r.id, p, n] for r, p, n in actions],
                    "batch_positions": used_tokens,
                    "activation_proxy_bytes": used_tokens
                    * self.limits.activation_bytes_per_position,
                    "physical_pages_before_release": physical,
                    "private_reserved_pages": reserved,
                    "active": active_count,
                }
            )
        return bool(actions)

    def run(self, *, audit=False):
        end = 0
        for now in range(self.limits.horizon):
            self.step(now, audit=audit)
            end = now + 1
            if all(r.status not in ("active", "queued") for r in self.requests):
                break
        if audit:
            self.pool.verify(self.requests, self.reserved)
        rows = []
        for r in self.requests:
            rows.append(
                {
                    "id": r.id,
                    "shape": r.entry.shape,
                    "status": (
                        "not_offered" if r.entry.arrival_round >= end else r.status
                    ),
                    "reason": r.reason,
                    "arrival_round": r.entry.arrival_round,
                    "admitted_round": r.admitted_round,
                    "first_output_round": r.first_round,
                    "end_round": r.end_round,
                    "observed_until_round": end,
                    "queue_wait_rounds": (
                        None
                        if r.admitted_round is None
                        else r.admitted_round - r.entry.arrival_round
                    ),
                    "worker_first_output_wait_rounds": (
                        None
                        if r.first_round is None
                        else r.first_round - r.entry.arrival_round
                    ),
                    "generated": r.generated,
                    "output_cap": r.entry.output_cap,
                    "max_service_gap_rounds": r.max_wait,
                    "max_decode_gap_rounds": r.decode_gap_max,
                    "private_pages_still_reserved": (
                        r.reserved if r.status in ("active", "unrecovered") else 0
                    ),
                }
            )
        offered = [r for r in rows if r["status"] != "not_offered"]
        groups = {}
        for shape in sorted({r["shape"] for r in offered}):
            group = [r for r in offered if r["shape"] == shape]
            observed = [
                r["worker_first_output_wait_rounds"]
                for r in group
                if r["worker_first_output_wait_rounds"] is not None
            ]
            groups[shape] = {
                "sent": len(group),
                "first_output_count": len(observed),
                "first_output_coverage": len(observed) / len(group),
                "first_output_wait_rounds_p95": quantile(observed, 0.95),
                "max_service_gap_rounds": max(
                    (r["max_service_gap_rounds"] for r in group), default=0
                ),
            }
        return {
            "policy": self.policy,
            "chunk": self.chunk,
            "logical_rounds": end,
            "input_entries": len(rows),
            "not_offered": len(rows) - len(offered),
            "sent": len(offered),
            "counts": dict(Counter(r["status"] for r in offered)),
            "remaining_unrecovered": sum(r["status"] == "unrecovered" for r in rows),
            "remaining_pending": sum(r["status"] in ("active", "queued") for r in rows),
            "logical_completions_per_round": sum(
                r["status"] == "completed" for r in rows
            )
            / end,
            "peak_physical_pages": self.pool.peak,
            "peak_reserved_including_cache": self.peak_reserved,
            "capacity_pages": self.limits.capacity,
            "cache_pages": self.pool.cache_pages,
            "pages_remaining": self.pool.used,
            "private_pages_reserved": self.reserved,
            "cow_pages": self.pool.cow,
            "allocations": self.pool.allocations,
            "diagnostics": dict(self.metrics),
            "planning_cpu_ns": {
                "count": len(self.planning_ns),
                "p50": quantile(self.planning_ns, 0.5),
                "p95": quantile(self.planning_ns, 0.95),
                "sum": sum(self.planning_ns),
            },
            "by_shape": groups,
            "rows": rows,
            "trace_sample": self.trace,
            "units": "logical rounds, synthetic lengths, host physical page IDs; NOT model latency or GPU throughput",
        }
