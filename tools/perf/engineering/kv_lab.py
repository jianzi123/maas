"""Host state model with real ownership/COW invariants; completions are simulated."""

from dataclasses import dataclass, field


class StaleLease(ValueError):
    pass


class BusyPage(ValueError):
    pass


@dataclass(frozen=True, order=True)
class Lease:
    page: int
    generation: int


@dataclass
class Page:
    generation: int = 0
    owners: set = field(default_factory=set)
    inflight: set = field(default_factory=set)
    tokens: list = field(default_factory=list)


class PagePool:
    def __init__(self, capacity, page_tokens=4):
        if (
            type(capacity) is not int
            or type(page_tokens) is not int
            or min(capacity, page_tokens) <= 0
        ):
            raise ValueError("positive capacity/page")
        self.pages = [Page() for _ in range(capacity)]
        self.free = set(range(capacity))
        self.page_tokens = page_tokens
        self.batches = {}

    def _page(self, lease):
        if (
            not isinstance(lease, Lease)
            or type(lease.page) is not int
            or type(lease.generation) is not int
            or not 0 <= lease.page < len(self.pages)
        ):
            raise StaleLease("page")
        p = self.pages[lease.page]
        if p.generation != lease.generation or lease.page in self.free:
            raise StaleLease("allocation generation")
        return p

    def allocate(self, owner):
        if not isinstance(owner, str) or not owner:
            raise ValueError("owner")
        if not self.free:
            raise MemoryError("page pool exhausted")
        index = min(self.free)
        self.free.remove(index)
        p = self.pages[index]
        p.generation += 1
        p.owners = {owner}
        p.inflight = set()
        p.tokens = []
        self.assert_invariants()
        return Lease(index, p.generation)

    def data(self, lease):
        return tuple(self._page(lease).tokens)

    def append(self, owner, lease, token):
        p = self._page(lease)
        if p.owners != {owner}:
            raise ValueError("shared/unowned write requires COW")
        if p.inflight:
            raise BusyPage("device access outstanding")
        if len(p.tokens) >= self.page_tokens:
            raise ValueError("page full; append a new logical page")
        if type(token) is not int:
            raise ValueError("integer token")
        p.tokens.append(token)
        self.assert_invariants()

    def share(self, source, lease, target):
        p = self._page(lease)
        if source not in p.owners or not isinstance(target, str) or not target:
            raise ValueError("owner")
        if p.inflight and len(p.tokens) < self.page_tokens:
            raise BusyPage("partial page outstanding")
        p.owners.add(target)
        self.assert_invariants()

    def _recycle(self, index):
        p = self.pages[index]
        if not p.owners and not p.inflight:
            p.tokens = []
            self.free.add(index)

    def release(self, owner, lease):
        p = self._page(lease)
        if owner not in p.owners:
            raise ValueError("detach event must be deduplicated by caller")
        p.owners.remove(owner)
        self._recycle(lease.page)
        self.assert_invariants()

    def clone_for_write(self, owner, lease):
        p = self._page(lease)
        if owner not in p.owners:
            raise ValueError("owner")
        if p.inflight:
            raise BusyPage("cannot copy data with outstanding device access")
        if len(p.tokens) >= self.page_tokens:
            raise ValueError("full page")
        if p.owners == {owner}:
            return lease
        # Allocate BEFORE removing old reference. OOM leaves original page untouched.
        new = self.allocate(owner)
        self._page(new).tokens = p.tokens.copy()
        self.release(owner, lease)
        self.assert_invariants()
        return new

    def submit(self, batch, bindings):
        payload = tuple(bindings)
        if not isinstance(batch, str) or not batch or not payload:
            raise ValueError("batch")
        if batch in self.batches:
            if self.batches[batch]["payload"] != payload:
                raise ValueError("batch identity conflict")
            return False
        for owner, lease in payload:
            if owner not in self._page(lease).owners:
                raise ValueError("unowned submit")
        # Validation finishes before pinning any page.
        self.batches[batch] = {"payload": payload, "active": True}
        for _, lease in payload:
            self._page(lease).inflight.add(batch)
        self.assert_invariants()
        return True

    def complete(self, batch):
        b = self.batches[batch]
        if not b["active"]:
            return False
        b["active"] = False
        for lease in {lease for _, lease in b["payload"]}:
            p = self._page(lease)
            p.inflight.remove(batch)
            self._recycle(lease.page)
        self.assert_invariants()
        return True

    def assert_invariants(self):
        for i, p in enumerate(self.pages):
            if i in self.free:
                assert not p.owners and not p.inflight and not p.tokens
            else:
                assert p.owners or p.inflight
                assert len(p.tokens) <= self.page_tokens
            for batch in p.inflight:
                b = self.batches[batch]
                assert b["active"]
                assert any(l == Lease(i, p.generation) for _, l in b["payload"])
        for batch, b in self.batches.items():
            if b["active"]:
                for _, l in b["payload"]:
                    assert l.page not in self.free
                    assert self.pages[l.page].generation == l.generation
                    assert batch in self.pages[l.page].inflight
        return True


def demo():
    p = PagePool(2, 4)
    a = p.allocate("A")
    p.append("A", a, 11)
    p.share("A", a, "B")
    b = p.clone_for_write("B", a)
    p.append("B", b, 22)
    isolated = [list(p.data(a)), list(p.data(b))]
    p.submit("worker1:batch7", (("A", a),))
    p.release("A", a)
    free_before = len(p.free)
    p.complete("worker1:batch7")
    new = p.allocate("C")
    try:
        p.data(a)
        stale = False
    except StaleLease:
        stale = True
    return {
        "cow_isolated_tokens": isolated,
        "free_while_inflight": free_before,
        "same_physical_page": new.page == a.page,
        "new_generation": new.generation,
        "stale_handle_rejected": stale,
        "duplicate_completion_is_noop": p.complete("worker1:batch7") is False,
        "actual_device_completion_verified": False,
    }
