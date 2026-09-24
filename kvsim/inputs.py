"""Scenario compilation: one canonical content representation, no model calls."""

import copy
import hashlib
import json
from pathlib import Path

from .profile import resolve

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "output/ascend-handoff/Ascend910C_KV_Replay_425/workload/reference-plan.json"


def canonical(parts):
    """Merge contiguous slices; fragment boundaries never define cache identity."""
    out = []
    for part in parts:
        p = dict(part)
        if set(p) != {"id", "start", "length"} or not isinstance(p["id"], str):
            raise ValueError("Each segment needs id, start, length")
        if any(isinstance(p[k], bool) or not isinstance(p[k], int) or p[k] < 0 for k in ("start", "length")):
            raise ValueError("Segment offsets and lengths must be nonnegative integers")
        if not p["length"]:
            continue
        if out and out[-1]["id"] == p["id"] and out[-1]["start"] + out[-1]["length"] == p["start"]:
            out[-1]["length"] += p["length"]
        else:
            out.append(p)
    return out


def length(parts):
    return sum(p["length"] for p in parts)


def prefix(parts, count):
    out = []
    for p in parts:
        n = min(count, p["length"])
        if n:
            out.append({**p, "length": n})
        count -= n
        if not count:
            break
    return canonical(out)


def segment(name, n):
    return {"id": name, "start": 0, "length": n}


def token_parts(tokens):
    # Stable token IDs give actual-token mode the same ordered-content contract.
    if not isinstance(tokens, list) or any(type(x) is not int or x < 0 for x in tokens):
        raise ValueError("tokens must be a list of nonnegative integers")
    return [segment("token:" + str(x), 1) for x in tokens]


def prefix_key(request, end):
    material = [request.get("cache_identity", ""), prefix(request["parts"], end)]
    return hashlib.sha256(json.dumps(material, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def synthetic(settings):
    defaults = dict(chains=4, rounds=4, first_tokens=20000, increment=2048, output_tokens=256, competitors=0)
    s = {**defaults, **settings}
    for k in defaults:
        if type(s[k]) is not int or s[k] < (1 if k in ("chains", "rounds", "first_tokens") else 0):
            raise ValueError(f"Invalid synthetic parameter: {k}")
    count = s["chains"] * (s["rounds"] + (s["rounds"] - 1) * s["competitors"])
    if count > 2000:
        raise ValueError("Synthetic workload exceeds 2000 requests")
    requests = []
    for chain in range(s["chains"]):
        sid = f"chain-{chain}"
        previous = None
        parts = []
        for turn in range(s["rounds"]):
            rid = f"{sid}/r{turn}"
            context = previous
            if previous:
                parts = parts + [segment(previous + "/output", s["output_tokens"]), segment(rid, s["increment"])]
            else:
                parts = [segment(rid, s["first_tokens"])]
            send = previous
            for j in range(s["competitors"] if previous else 0):
                cid = f"{rid}/competition-{j}"
                requests.append(dict(id=cid, session=sid, parts=[segment(cid, s["first_tokens"])],
                                     output_tokens=s["output_tokens"], send_after=send, context_after=None,
                                     context_mode="independent", source_kind="synthetic"))
                send = cid
            requests.append(dict(id=rid, session=sid, parts=canonical(parts), output_tokens=s["output_tokens"],
                                 send_after=send, context_after=context, context_mode="append" if context else "independent",
                                 source_kind="synthetic"))
            previous = rid
    return requests


def agentinfer(plan, captures=None):
    """Adapt structural ReplayPlan; missing tokens use explicitly synthetic content."""
    requests = []
    assumptions = []
    for task in plan["tasks"]:
        known = {}
        for node in task["requests"]:
            if node["node_type"] != "request":
                raise NotImplementedError("Timing-only nodes need explicit event adaptation")
            key = node["source_key"]
            rid = task["runtime_session_id"] + "/" + key
            parent = node.get("context_after")
            n = node["planned_input_tokens"]
            if captures and key in captures:
                parts = token_parts(captures[key])
                source = "captured_tokens"
            else:
                inherited = []
                if parent and parent in known:
                    prev = known[parent]
                    inherited = prev["parts"] + [segment(prev["id"] + "/output", prev["output_tokens"])]
                # This is a declared construction, NOT the historical PromptBuilder trim.
                parts = prefix(inherited, n)
                parts += [segment(rid + "/synthetic", n - length(parts))]
                source = "synthetic_from_plan"
            req = dict(id=rid, session=task["runtime_session_id"], parts=canonical(parts),
                       output_tokens=node["planned_output_tokens"],
                       send_after=(task["runtime_session_id"] + "/" + node["send_after"]) if node.get("send_after") else None,
                       context_after=(task["runtime_session_id"] + "/" + parent) if parent else None,
                       context_mode=node["context_mode"], source_kind=source,
                       wait_ticks=0)
            known[key] = req
            requests.append(req)
    if any(r["source_kind"] == "synthetic_from_plan" for r in requests):
        assumptions.append("Historical plan lengths/dependencies; contents synthesized by prefix slicing, NOT captured inputs or actual trim semantics.")
    assumptions.append("Historical wait seconds are not hardware time: generated virtual ordering uses zero think ticks unless explicit events are imported.")
    return requests, assumptions


def compile_scenario(settings=None):
    settings = copy.deepcopy(settings or {})
    if settings.get("schema_version") == 1:
        validate(settings)
        return settings
    config = settings.get("config", {})
    resolve(config)
    assumptions = ["Virtual ticks specify ordering, not seconds or device speed.",
                   "A scheduling step commits before the next step; pending state is never reused.",
                   "D outputs are content only; no D→P KV return."]
    source = settings.get("workload", "synthetic")
    if source == "replay425":
        reqs, notes = agentinfer(json.loads(PLAN.read_text()))
        assumptions += notes
    elif source == "agentinfer":
        reqs, notes = agentinfer(settings["plan"], settings.get("captures"))
        assumptions += notes
    elif source == "custom":
        reqs = settings["requests"]
    elif source == "synthetic":
        reqs = synthetic(settings.get("synthetic", {}))
    else:
        raise ValueError("Unknown workload")
    domains = settings.get("p_domains", 4)
    if type(domains) is not int or not 1 <= domains <= 16:
        raise ValueError("p_domains must be in 1..16")
    sessions = list(dict.fromkeys(r["session"] for r in reqs))
    mapping = settings.get("routing", {})
    for r in reqs:
        if "tokens" in r:
            r["parts"] = token_parts(r.pop("tokens"))
        r["parts"] = canonical(r["parts"])
        default_domain = 0 if settings.get("routing_mode") == "p0" else sessions.index(r["session"]) % domains
        r.setdefault("p_domain", mapping.get(r["session"], default_domain))
        r.setdefault("send_after", None)
        r.setdefault("context_after", None)
        r.setdefault("source_kind", "explicit_segments")
    execution = {"concurrency": 3, "p_slots": 2, "chunk_tokens": 8192, "step_budget": 8192,
                 "transfer_ticks": 1, "decode_ticks": 2, **settings.get("execution", {})}
    scenario = dict(schema_version=1, config=config, p_domains=domains, requests=reqs,
                    execution=execution, assumptions=assumptions, workload=source)
    validate(scenario, check_events=False)
    scenario["events"] = settings.get("events") or generate_events(reqs, execution)
    validate(scenario)
    return scenario


def validate(s, check_events=True):
    resolve(s["config"])
    if type(s["p_domains"]) is not int or not 1 <= s["p_domains"] <= 16:
        raise ValueError("p_domains must be in 1..16")
    reqs = s["requests"]
    if not 1 <= len(reqs) <= 2000:
        raise ValueError("Use 1..2000 requests in the local first version")
    ids = {r["id"] for r in reqs}
    if len(ids) != len(reqs):
        raise ValueError("Duplicate request id")
    if sum(length(r["parts"]) for r in reqs) > 100_000_000:
        raise ValueError("Scenario exceeds 100 million input tokens")
    for r in reqs:
        r["parts"] = canonical(r["parts"])
        if length(r["parts"]) <= 0:
            raise ValueError("Input length must be positive")
        if s["config"].get("max_input_tokens") is not None and length(r["parts"]) > s["config"]["max_input_tokens"]:
            raise NotImplementedError("Input exceeds configured deployment max_input_tokens")
        if type(r["output_tokens"]) is not int or r["output_tokens"] < 0:
            raise ValueError("output_tokens must be nonnegative")
        if type(r["p_domain"]) is not int or not 0 <= r["p_domain"] < s["p_domains"]:
            raise ValueError("Invalid P domain")
        for k in ("send_after", "context_after"):
            if r.get(k) is not None and r[k] not in ids:
                raise ValueError(f"Unknown {k}: {r[k]}")
    e = s["execution"]
    unknown = set(e) - {"concurrency", "p_slots", "chunk_tokens", "step_budget", "transfer_ticks", "decode_ticks"}
    if unknown:
        raise NotImplementedError("Unsupported execution settings: " + ", ".join(sorted(unknown)))
    for k in ("concurrency", "p_slots", "chunk_tokens", "step_budget", "transfer_ticks", "decode_ticks"):
        if type(e[k]) is not int or e[k] < (1 if k in ("concurrency", "p_slots", "chunk_tokens", "step_budget") else 0):
            raise ValueError(f"Invalid execution setting {k}")
    if check_events and len(s["events"]) > 100000:
        raise ValueError("Too many events")


def generate_events(reqs, execution):
    """Cold-progress round robin; generated once, never depends on cache hits."""
    waiting = list(reqs)
    active, releasing, decoding, done = {}, {}, {}, set()
    events = []
    tick = 0
    def emit(kind, rid, **kw):
        events.append(dict(seq=len(events), tick=tick, kind=kind, request_id=rid, **kw))
    while waiting or active or releasing or decoding:
        if tick > 100000:
            raise ValueError("Event generation did not terminate")
        for rid, at in list(releasing.items()):
            if at <= tick:
                emit("P_RELEASE", rid)
                del releasing[rid]
                decoding[rid] = tick + execution["decode_ticks"]
        for rid, at in list(decoding.items()):
            if at <= tick:
                emit("REQUEST_COMPLETE", rid)
                done.add(rid)
                del decoding[rid]
        for r in list(waiting):
            occupied = len(active) + len(releasing) + len(decoding)
            p_active = sum(x[0]["p_domain"] == r["p_domain"] for x in active.values())
            if occupied >= execution["concurrency"] or p_active >= execution["p_slots"]:
                continue
            if any(r.get(k) and r[k] not in done for k in ("send_after", "context_after")):
                continue
            emit("ARRIVE", r["id"])
            active[r["id"]] = [r, 0]
            waiting.remove(r)
        budgets = {}
        for rid, (r, pos) in list(active.items()):
            p = r["p_domain"]
            budget = budgets.get(p, execution["step_budget"])
            if budget <= 0:
                continue
            delta = min(execution["chunk_tokens"], budget, length(r["parts"]) - pos)
            target = pos + delta
            emit("SCHEDULE", rid, target=target, budget=delta)
            emit("STEP_COMPLETE", rid, target=target)
            budgets[p] = budget - delta
            active[rid][1] = target
            if target == length(r["parts"]):
                del active[rid]
                releasing[rid] = tick + execution["transfer_ticks"]
        if waiting and not active and not releasing and not decoding:
            raise ValueError("Dependency cycle or unsatisfied dependency")
        tick += 1
    return events
