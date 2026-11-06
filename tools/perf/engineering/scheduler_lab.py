"""A running CPU length-state scheduler; no model forward or time/throughput model."""

from dataclasses import dataclass
import math


@dataclass
class Request:
    id: str
    arrival: int
    input_tokens: int
    output_cap: int
    pref: int = 0
    generated: int = 0
    decode_steps: int = 0
    admitted: bool = False
    finished: bool = False
    cancelled: bool = False


class Scheduler:
    def __init__(self, requests, pages=16, page_tokens=2, budget=4, chunk=3):
        if (
            any(
                type(x) is not int or x <= 0
                for x in (pages, page_tokens, budget, chunk)
            )
            or budget < 2
        ):
            raise ValueError("limits")
        self.requests = [Request(*r) for r in requests]
        if len({r.id for r in self.requests}) != len(self.requests):
            raise ValueError("duplicate request")
        self.pages = pages
        self.page_tokens = page_tokens
        self.budget = budget
        self.chunk = chunk
        for r in self.requests:
            if (
                r.arrival < 0
                or min(r.input_tokens, r.output_cap) <= 0
                or self.reserve(r) > pages
            ):
                raise ValueError("individual sequence cannot fit conservative envelope")
        self.cursor = 0
        self.trace = []

    def reserve(self, r):
        return math.ceil((r.input_tokens + r.output_cap - 1) / self.page_tokens)

    def active(self, r):
        return r.admitted and not r.finished and not r.cancelled

    def held(self):
        return sum(self.reserve(r) for r in self.requests if self.active(r))

    def used(self):
        return sum(
            math.ceil((r.pref + r.decode_steps) / self.page_tokens)
            for r in self.requests
            if self.active(r)
        )

    def cancel(self, request_id):
        # Called BETWEEN synchronously completed logical rounds only.
        r = next(r for r in self.requests if r.id == request_id)
        if not r.finished:
            r.cancelled = True

    def step(self, now):
        eligible = [
            r
            for r in self.requests
            if r.arrival <= now and not r.finished and not r.cancelled
        ]
        pending = sorted(
            [r for r in eligible if r.pref < r.input_tokens],
            key=lambda r: (r.arrival, r.id),
        )
        decoders = [
            r
            for r in eligible
            if r.pref == r.input_tokens and r.generated < r.output_cap
        ]
        if decoders:
            offset = self.cursor % len(decoders)
            decoders = decoders[offset:] + decoders[:offset]
            self.cursor += 1
        work = []
        remaining = self.budget
        decode_quota = self.budget - 1 if pending else self.budget
        for r in decoders[:decode_quota]:
            r.decode_steps += 1
            r.generated += 1
            remaining -= 1
            work.append([r.id, "decode", 1])
        for r in pending:
            if not remaining:
                break
            if not r.admitted:
                if self.held() + self.reserve(r) > self.pages:
                    continue
                r.admitted = True
            count = min(self.chunk, remaining, r.input_tokens - r.pref)
            r.pref += count
            remaining -= count
            work.append([r.id, "prefill", count])
            if r.pref == r.input_tokens:
                r.generated = 1
        peak = self.used()
        reserved_before_finish = self.held()
        assert peak <= reserved_before_finish <= self.pages
        finished = []
        for r in eligible:
            if r.generated == r.output_cap:
                r.finished = True
                finished.append(r.id)
        self.trace.append(
            {
                "round": now,
                "work": work,
                "peak_pages_before_completion": peak,
                "reserved_pages_before_completion": reserved_before_finish,
                "used_after": self.used(),
                "reserved_after": self.held(),
                "finished": finished,
            }
        )
        return self.trace[-1]

    def run(self, max_rounds=100):
        for t in range(max_rounds):
            self.step(t)
            if all(r.finished or r.cancelled for r in self.requests):
                return self.trace
        raise TimeoutError("logical round limit, not a GPU deadline")


def demo():
    s = Scheduler(
        [("A", 0, 4, 3), ("B", 1, 7, 2), ("C", 2, 2, 1)], pages=8, budget=4, chunk=2
    )
    trace = s.run()
    tight = Scheduler([("A", 0, 4, 2), ("B", 0, 4, 2)], pages=3, budget=3, chunk=2)
    tight.run()
    return {
        "trace": trace,
        "all_completed": all(r.finished for r in s.requests),
        "tight_capacity_rounds": len(tight.trace),
        "reservation_policy": "full per-sequence KV upper bound; conservative",
        "logical_rounds_are_not_latency": True,
        "GPU_or_business_admission_implemented": False,
    }
