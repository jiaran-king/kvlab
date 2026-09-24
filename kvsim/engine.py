"""Event-driven physical cache state. Observed metrics never enter this module."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import resource
import sys

from .inputs import length, prefix_key, validate
from .profile import resolve


class Infeasible(Exception):
    pass


@dataclass
class Page:
    id: int
    refs: int = 0
    key: tuple | None = None
    formed: int | None = None
    released: int | None = None


class Pool:
    def __init__(self, total):
        self.total = total
        self.pages = {}
        self.free = OrderedDict()
        self.empty_free = OrderedDict()
        self.empty_reuses = 0
        self.index = {}
        self.removed = {}
        self.replacements = 0
        self.next_id = 1  # zero is the runtime's null block

    def available(self):
        return max(0, self.total - self.next_id) + len(self.free) + len(self.empty_free)

    def lookup(self, key):
        entries = self.index.get(key, {})
        return self.pages[next(iter(entries))] if entries else None

    def touch(self, page):
        if page.refs == 0:
            self.free.pop(page.id, None)
            self.empty_free.pop(page.id, None)
        page.refs += 1

    def allocate(self, seq):
        if self.empty_free:
            pid, _ = self.empty_free.popitem(last=False)
            page = self.pages[pid]
            self.empty_reuses += 1
        elif self.next_id < self.total:
            page = Page(self.next_id)
            self.pages[page.id] = page
            self.next_id += 1
        elif self.free:
            pid, _ = self.free.popitem(last=False)
            page = self.pages[pid]
        else:
            raise Infeasible("active_capacity: no reclaimable physical page")
        if page.key is not None:
            self.index[page.key].pop(page.id)
            if not self.index[page.key]:
                del self.index[page.key]
            self.removed[page.key] = dict(formed=page.formed, released=page.released, replaced=seq)
            self.replacements += 1
        page.key = page.formed = page.released = None
        page.refs = 1
        return page

    def publish(self, page, key, seq):
        if page.key is None:
            page.key = key
            page.formed = seq
            # Duplicate logical keys retain separate physical pages.
            self.index.setdefault(key, {})[page.id] = None

    def release(self, page, seq):
        self.release_many([page], seq)

    def release_many(self, pages, seq):
        empty = OrderedDict()
        for page in pages:
            if page.refs <= 0:
                raise ValueError("Release without an active reference")
            page.refs -= 1
            if page.refs == 0:
                page.released = seq
                if page.key is None:
                    empty[page.id] = None
                else:
                    self.free[page.id] = None
        if empty:
            empty.update(self.empty_free)
            self.empty_free = empty

    def snapshot(self):
        active = sum(p.refs > 0 for p in self.pages.values())
        cached = sum(p.refs == 0 and p.key is not None for p in self.pages.values())
        empty = self.total - 1 - active - cached
        if empty < 0:
            raise AssertionError("Physical capacity accounting failed")
        return dict(active=active, cached=cached, empty=empty, reserved=1, replacements=self.replacements, new_allocations=self.next_id-1,
                    empty_reuses=self.empty_reuses, unused=max(0,self.total-self.next_id), released_empty=len(self.empty_free))


@dataclass
class RequestState:
    row: dict
    phase: str = "waiting"
    position: int = 0
    pages: dict = field(default_factory=dict)
    pending: int | None = None
    scheduled_target: int | None = None
    adopted: int = 0
    compute: int = 0
    candidate: int = 0
    lookup: list = field(default_factory=list)
    steps: list = field(default_factory=list)


def simulate(scenario):
    validate(scenario)
    profile = resolve(scenario["config"])
    groups = profile["groups"]
    alignment = profile["alignment"]
    pools = [Pool(profile["num_blocks"]) for _ in range(scenario["p_domains"])]
    states = {r["id"]: RequestState(r, pages={g["name"]: {} for g in groups}) for r in scenario["requests"]}
    keys = {}
    timeline = []
    status, failure = "complete", None
    last_tick = -1
    per_tick_budget = {}

    def key(state, group, index):
        end = (index + 1) * group["block"]
        slot = (state.row["id"], end)
        if slot not in keys:
            keys[slot] = prefix_key(state.row, end)
        return (group["name"], keys[slot])

    def required_indices(group, target, start):
        b = group["block"]
        if group["kind"] == "dense":
            # Compressed allocation divides raw progress before ceil division.
            ratio = group["ratio"]
            storage_b = b // ratio
            count = (target // ratio + storage_b - 1) // storage_b
            return range(count)
        first = max(0, start - group["window"] + 1) // b
        return range(first, (target + b - 1) // b)

    def lookup(state, pool):
        candidate = (length(state.row["parts"]) - 1) // alignment * alignment
        state.candidate = candidate
        details = []
        while True:
            previous = candidate
            for g in groups:
                before = candidate
                b = g["block"]
                missing_key = None
                if g["kind"] == "dense":
                    found = 0
                    for i in range(candidate // b):
                        k = key(state, g, i)
                        if pool.lookup(k) is None:
                            missing_key = k
                            break
                        found += b
                    candidate = found // alignment * alignment
                else:
                    need = (g["window"] - 1 + b - 1) // b
                    while candidate:
                        end = candidate // b
                        missing = next((key(state, g, i) for i in range(max(0, end - need), end)
                                        if pool.lookup(key(state, g, i)) is None), None)
                        if missing is None:
                            break
                        if missing_key is None:
                            missing_key = missing
                        candidate = max(0, candidate - alignment)
                if candidate != before:
                    record = dict(group=g["name"], before=before, after=candidate,
                                  reason="required_state_unavailable")
                    if missing_key in pool.removed:
                        record["last_physical_replacement"] = pool.removed[missing_key]
                    details.append(record)
            if candidate == previous:
                break
        hits = {}
        for g in groups:
            b = g["block"]
            end = candidate // b
            start = 0 if g["kind"] == "dense" else max(0, end - (g["window"] - 1 + b - 1) // b)
            hits[g["name"]] = {i: pool.lookup(key(state, g, i)) for i in range(start, end)}
            selected = list(hits[g["name"]].values())
            if candidate:
                sample = selected[-1] if selected else None
                details.append(dict(group=g["name"], before=candidate, after=candidate,
                    reason="accepted_at_common_boundary", physical_pages=len(selected),
                    boundary_page=None if sample is None else dict(id=sample.id, formed=sample.formed, released=sample.released, refs=sample.refs)))
        state.lookup = details
        return candidate, hits

    def release_all(state, pool, seq):
        for g in groups:
            pages = state.pages[g["name"]]
            pool.release_many([pages[i] for i in sorted(pages, reverse=True)], seq)
            pages.clear()

    for index, event in enumerate(scenario["events"]):
        if index % 256 == 0:
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            peak_bytes = peak if sys.platform == "darwin" else peak * 1024
            if peak_bytes > 512 * 1024**2:
                raise MemoryError("Simulation exceeded 512 MiB process memory budget")
        try:
            if event["seq"] != index or event["tick"] < last_tick:
                raise ValueError("Events require consecutive seq and nondecreasing tick")
            if event["tick"] != last_tick:
                per_tick_budget = {}
            last_tick = event["tick"]
            rid = event["request_id"]
            state = states[rid]
            domain = state.row["p_domain"]
            pool = pools[domain]
            kind = event["kind"]
            n = length(state.row["parts"])
            if kind == "ARRIVE":
                if state.phase != "waiting":
                    raise ValueError("Duplicate arrival")
                for dep in (state.row.get("send_after"), state.row.get("context_after")):
                    if dep and states[dep].phase != "complete":
                        raise ValueError("Arrival before dependency completed")
                active = sum(s.phase not in ("waiting", "complete", "cancelled") for s in states.values())
                if active >= scenario["execution"]["concurrency"]:
                    raise Infeasible("request_concurrency: fixed arrival exceeds slots")
                state.phase = "arrived"
            elif kind == "SCHEDULE":
                if state.phase not in ("arrived", "running") or state.pending is not None:
                    raise ValueError("SCHEDULE requires an arrived/committed request")
                target = event["target"]
                if type(target) is not int or not 0 < target <= n:
                    raise ValueError("Invalid schedule target")
                if type(event["budget"]) is not int or event["budget"] < 0:
                    raise ValueError("Invalid schedule budget")
                state.scheduled_target = target
                new = state.phase == "arrived"
                if new:
                    active_p = sum(s.phase == "running" and s.row["p_domain"] == domain for s in states.values())
                    if active_p >= scenario["execution"]["p_slots"]:
                        raise Infeasible("p_slots: fixed trace exceeds P sequence slots")
                    hit, hits = lookup(state, pool)
                else:
                    hit, hits = state.position, state.pages
                target = max(target, hit)
                compute = target - hit
                used = per_tick_budget.get(domain, 0)
                if compute > event["budget"] or compute + used > scenario["execution"]["step_budget"]:
                    raise Infeasible("scheduling_budget: new input compute exceeds fixed opportunity")
                # Free stale window references in reverse index order before allocation,
                # using only committed progress (never the target of this step).
                if not new:
                    for g in groups:
                        if g["kind"] == "window":
                            cutoff = max(0, state.position - g["window"] + 1) // g["block"]
                            pages = state.pages[g["name"]]
                            skipped = sorted([i for i in pages if i < cutoff], reverse=True)
                            pool.release_many([pages.pop(i) for i in skipped], index)
                missing = []
                for g in groups:
                    existing = hits[g["name"]]
                    for i in required_indices(g, target, hit):
                        if i not in existing:
                            missing.append((g["name"], i))
                pinned_free = {p.id for pages in hits.values() for p in pages.values() if p is not None and p.refs == 0} if new else set()
                if new:
                    # Frozen allocate_slots full_sequence_must_fit check, with
                    # recycling-aware SWA admission caps. It checks future need;
                    # it does not allocate future blocks or double-charge them.
                    admission = len(pinned_free)
                    for g in groups:
                        b = g["block"]
                        if g["kind"] == "dense":
                            ratio = g["ratio"]
                            storage = b // ratio
                            required = (n // ratio + storage - 1) // storage
                            skipped = 0
                        else:
                            budget_tokens = scenario["execution"]["step_budget"]
                            cap = (min(g["window"] - 1 + budget_tokens, scenario["config"].get("max_input_tokens") or n) + b - 1) // b + 1
                            required = min((n + b - 1) // b, cap)
                            skipped = max(0, hit - g["window"] + 1) // b
                        admission += max(0, required - max(skipped, hit // b))
                    if admission > pool.available():
                        raise Infeasible(f"admission_capacity: full-input gate needs {admission} pages; {pool.available()} free")
                if len(missing) + len(pinned_free) > pool.available():
                    raise Infeasible(f"active_capacity: need {len(missing)} new + {len(pinned_free)} cached pages; {pool.available()} free")
                if new:
                    for pages in hits.values():
                        for p in pages.values():
                            if p is None:
                                raise AssertionError("Selected recovery state disappeared")
                            pool.touch(p)
                    state.pages = hits
                    state.adopted = hit
                    state.position = hit
                    state.phase = "running"
                for name, i in missing:
                    state.pages[name][i] = pool.allocate(index)
                state.pending = target
                state.steps.append(dict(event_seq=index, from_token=state.position, to_token=target, compute_tokens=compute))
                per_tick_budget[domain] = used + compute
            elif kind == "STEP_COMPLETE":
                if state.pending is None or event["target"] != state.scheduled_target:
                    raise ValueError("STEP_COMPLETE has no matching scheduled step")
                target = state.pending
                for g in groups:
                    b = g["block"]
                    need = (g["window"] - 1 + b - 1) // b if g["window"] else 0
                    for i, page in state.pages[g["name"]].items():
                        if (i + 1) * b > target or page.key is not None:
                            continue
                        retain = g["kind"] == "dense" or i % (alignment // b) >= alignment // b - need
                        if retain:
                            pool.publish(page, key(state, g, i), index)
                state.compute += target - state.position
                state.position = target
                state.pending = None
                if target == n:
                    state.phase = "transfer"
            elif kind == "P_RELEASE":
                if state.phase != "transfer" or state.pending is not None:
                    raise ValueError("P_RELEASE before input completion")
                release_all(state, pool, index)
                state.phase = "decode"
            elif kind == "REQUEST_COMPLETE":
                if state.phase != "decode":
                    raise ValueError("REQUEST_COMPLETE before P release")
                state.phase = "complete"
                assert state.compute + state.adopted == n
            elif kind == "CANCEL":
                if state.pending is not None or state.phase == "transfer":
                    raise NotImplementedError("Cancellation with in-flight compute/transfer is not supported")
                release_all(state, pool, index)
                state.phase = "cancelled"
            else:
                raise NotImplementedError(f"Unsupported event: {kind}")
            if kind in ("STEP_COMPLETE", "P_RELEASE"):
                timeline.append(dict(event_seq=index, tick=last_tick, p_domain=domain, **pool.snapshot()))
        except Infeasible as exc:
            status = "infeasible_under_fixed_trace"
            failure = dict(event_seq=index, request_id=event.get("request_id"), reason=str(exc))
            break
    if status == "complete" and any(s.phase != "complete" for s in states.values()):
        raise ValueError("Trace ended without completing every request")
    rows = []
    for rid, s in states.items():
        rows.append(dict(request_id=rid, session=s.row["session"], p_domain=s.row["p_domain"],
                         input_tokens=length(s.row["parts"]), p_input_tokens=length(s.row["parts"]),
                         candidate_tokens=s.candidate, adopted_cached_tokens=s.adopted,
                         input_compute_tokens=s.compute, status=s.phase,
                         limiting_groups=list(dict.fromkeys(x["group"] for x in s.lookup if x["after"] < x["before"])),
                         explanation=s.lookup, steps=s.steps, source_kind=s.row["source_kind"]))
    per_p = []
    for domain, pool in enumerate(pools):
        subset = [r for r in rows if r["p_domain"] == domain]
        per_p.append(dict(p_domain=domain, **summarize(subset), **pool.snapshot(),
                          active_peak=max((x["active"] for x in timeline if x["p_domain"] == domain), default=0)))
    return dict(simulator_version="0.1.0", status=status, failure=failure, scenario=scenario, profile=profile, requests=rows,
                summary=summarize(rows), per_p=per_p, timeline=timeline,
                metric_scope="Completed requests only; partial results are not complete capacity points.")


def summarize(rows):
    done = [r for r in rows if r["status"] == "complete"]
    p = sum(r["p_input_tokens"] for r in done)
    h = sum(r["adopted_cached_tokens"] for r in done)
    c = sum(r["input_compute_tokens"] for r in done)
    return dict(planned=len(rows), completed=len(done), p_input_tokens=p,
                adopted_cached_tokens=h, input_compute_tokens=c,
                input_cache_fraction=h / p if p else None)
