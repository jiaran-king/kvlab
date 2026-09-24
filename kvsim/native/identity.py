"""Stable identities for one frozen native experiment point."""

from __future__ import annotations

import hashlib
import json

from kvsim.native.capacity import budgets_from_conditions


def run_id(workload_sha256: str, routing: dict, conditions: dict, capacity_gib: int) -> str:
    experiment = dict(conditions)
    experiment.pop("capacities_gib", None)
    experiment.pop("routing_trace", None)
    experiment.pop("capacity_points", None)
    material = {
        "workload_sha256": workload_sha256,
        "routing_sha256": routing.get("routing_sha256"),
        "routing_method": routing.get("method"),
        "conditions": experiment,
        "capacity_gib": capacity_gib,
        **({"capacity_budget": budgets_from_conditions(conditions)[capacity_gib]}
           if "capacity_points" in conditions else {}),
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"native-{digest[:20]}"
