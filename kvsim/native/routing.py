"""Freeze and validate request placement across independent P cache domains."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


SCHEMA = "kvlab-native-routing/v1"
SOURCES = {"actual_capture", "reconstructed", "policy_generated"}


@dataclass(frozen=True)
class FrozenRouting:
    assignments: dict[str, str]
    provenance: dict


def workload_digest(workload) -> str:
    return hashlib.sha256(workload.source.read_bytes()).hexdigest()


def _domains(count: int) -> list[str]:
    if type(count) is not int or count < 1:
        raise ValueError("p_domains must be a positive integer")
    return [f"p{index}" for index in range(count)]


def load_routing(path: Path | None, workload, p_domains: int) -> FrozenRouting:
    domains = _domains(p_domains)
    if path is None:
        if p_domains != 1:
            raise ValueError("multiple P domains require an explicit frozen routing trace")
        return FrozenRouting(
            {request.request_id: "p0" for request in workload.requests},
            {"source": "policy_generated", "method": "all-p0", "domains": domains,
             "workload_sha256": workload_digest(workload), "routing_sha256": None},
        )
    data = json.loads(path.read_text())
    if data.get("schema") != SCHEMA:
        raise ValueError("unsupported routing trace schema")
    if data.get("workload_sha256") != workload_digest(workload):
        raise ValueError("routing trace workload SHA256 does not match input")
    if data.get("domains") != domains:
        raise ValueError("routing trace domain map does not match p_domains")
    if data.get("source") not in SOURCES:
        raise ValueError("routing trace requires a recognized source")
    if not isinstance(data.get("method"), str) or not data["method"]:
        raise ValueError("routing trace requires a generation or capture method")
    rows = data.get("assignments")
    if not isinstance(rows, list) or len(rows) != len(workload.requests):
        raise ValueError("routing trace must cover every request exactly once")
    assignments = {}
    for request, row in zip(workload.requests, rows):
        if not isinstance(row, dict) or set(row) != {"order", "request_id", "assigned_p"}:
            raise ValueError("routing trace has unsupported attempt or placement fields")
        if row["order"] != request.order or row["request_id"] != request.request_id:
            raise ValueError("routing trace order or request coverage differs from workload")
        if row["assigned_p"] not in domains:
            raise ValueError(f"unknown P domain for {request.request_id}")
        assignments[request.request_id] = row["assigned_p"]
    provenance = {key: data.get(key) for key in
                  ("source", "method", "reference_config", "timestamp_semantics", "workload_sha256", "domains")}
    provenance["path"] = str(path.resolve())
    provenance["routing_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return FrozenRouting(assignments, provenance)


def generate_actor_affinity(workload, p_domains: int) -> dict:
    domains = _domains(p_domains)
    return {
        "schema": SCHEMA,
        "workload_sha256": workload_digest(workload),
        "domains": domains,
        "source": "policy_generated",
        "method": "sha256(actor_id) modulo p_domains",
        "reference_config": {"p_domains": p_domains},
        "assignments": [
            {"order": request.order, "request_id": request.request_id,
             "assigned_p": domains[int.from_bytes(
                 hashlib.sha256(request.actor_id.encode()).digest(), "big") % p_domains]}
            for request in workload.requests
        ],
    }


if __name__ == "__main__":
    from kvsim.native.inputs import load_replay_workload

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workload", type=Path)
    parser.add_argument("p_domains", type=int)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    frozen = load_replay_workload(args.workload)
    trace = generate_actor_affinity(frozen, args.p_domains)
    args.output.write_text(json.dumps(trace, indent=2, ensure_ascii=False))
    load_routing(args.output, frozen, args.p_domains)
