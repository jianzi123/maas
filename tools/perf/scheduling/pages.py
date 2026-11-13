"""Exact host page allocation for a synchronous synthetic scheduler, not GPU KV tensors."""

from dataclasses import dataclass, field
from collections import deque


def ceildiv(n, d):
    return (n + d - 1) // d


@dataclass
class Page:
    valid: int = 0
    owners: set = field(default_factory=set)
    generation: int = 0
    cached: bool = False


class Pages:
    def __init__(self, capacity, page_tokens, prefixes):
        if (
            type(capacity) is not int
            or type(page_tokens) is not int
            or min(capacity, page_tokens) <= 0
        ):
            raise ValueError("positive page limits")
        self.capacity = capacity
        self.size = page_tokens
        self.pages = [Page() for _ in range(capacity)]
        self.free = deque(range(capacity))
        self.prefixes = {}
        self.allocations = 0
        self.cow = 0
        self.peak = 0
        for key, length in sorted(prefixes.items()):
            if not isinstance(key, str) or type(length) is not int or length < 0:
                raise ValueError("prefix")
            table = []
            for start in range(0, length, page_tokens):
                p = self.allocate("cache:" + key, cached=True)
                self.pages[p].valid = min(page_tokens, length - start)
                table.append(p)
            self.prefixes[key] = (length, tuple(table))
        self.cache_pages = self.used

    @property
    def used(self):
        return self.capacity - len(self.free)

    def allocate(self, owner, cached=False):
        if not self.free:
            raise MemoryError("physical page budget exceeded")
        p = self.free.popleft()
        page = self.pages[p]
        if page.owners or page.valid:
            raise RuntimeError("allocator free invariant")
        page.generation += 1
        page.owners = {owner}
        page.cached = cached
        self.allocations += 1
        self.peak = max(self.peak, self.used)
        return p

    def attach(self, key, owner):
        if key is None:
            return [], 0
        length, table = self.prefixes[key]
        for p in table:
            self.pages[p].owners.add(owner)
        return list(table), length

    def reserve_private(self, input_tokens, output_cap, key):
        length = 0 if key is None else self.prefixes[key][0]
        # Full prefix pages remain read-only; a partial prefix tail needs a private COW page.
        return ceildiv(input_tokens + output_cap - 1, self.size) - length // self.size

    def extra_pages(self, table, position, count):
        if count < 0:
            raise ValueError("count")
        added = max(0, ceildiv(position + count, self.size) - len(table))
        if (
            count
            and position % self.size
            and table
            and len(self.pages[table[-1]].owners) > 1
        ):
            added += 1
        return added

    def append(self, table, position, count, owner):
        if self.extra_pages(table, position, count) > len(self.free):
            raise MemoryError("no atomic page room")
        left = count
        while left:
            if position % self.size == 0:
                table.append(self.allocate(owner))
            index = position // self.size
            p = table[index]
            page = self.pages[p]
            if owner not in page.owners:
                raise RuntimeError("page ownership mismatch")
            if len(page.owners) > 1:
                new = self.allocate(owner)
                self.pages[new].valid = page.valid
                page.owners.remove(owner)
                table[index] = new
                p = new
                page = self.pages[p]
                self.cow += 1
            n = min(left, self.size - position % self.size)
            if page.valid != position % self.size:
                raise RuntimeError("append position mismatch")
            page.valid += n
            position += n
            left -= n
        return count

    def release(self, table, owner):
        for p in table:
            page = self.pages[p]
            if owner not in page.owners:
                raise RuntimeError("double/foreign release")
            page.owners.remove(owner)
            if not page.owners:
                page.valid = 0
                page.cached = False
                self.free.append(p)

    def verify(self, requests, reserved):
        live = {p: set() for p, page in enumerate(self.pages) if page.cached}
        for key, (_, table) in self.prefixes.items():
            for p in table:
                live[p].add("cache:" + key)
        for r in requests:
            for p in r.table:
                live.setdefault(p, set()).add(r.id)
        free = set(self.free)
        if len(free) != len(self.free):
            raise RuntimeError("duplicate free")
        for p, page in enumerate(self.pages):
            if p in free:
                if page.owners or page.valid:
                    raise RuntimeError("free payload")
            elif not page.owners or page.owners != live.get(p):
                raise RuntimeError("reference invariant")
        if not self.used <= self.cache_pages + reserved <= self.capacity:
            raise RuntimeError("reservation invariant")
        return True
