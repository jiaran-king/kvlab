"""Validate one supported native H20 experiment before CPU execution.

Usage: python3 -m kvsim.native.conditions <conditions.json>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvsim.native.capacity import budgets_from_conditions, target_layout
from kvsim.native.inputs import validate_h20_condition_fields
from kvsim.native.scenario import validate_scenario


def read_conditions(path: Path) -> dict:
    conditions = json.loads(path.read_text())
    layout = target_layout()
    validate_h20_condition_fields(conditions)
    if conditions.get("schema") != "kvlab-native-conditions/v1":
        raise ValueError("unsupported conditions schema")
    if conditions.get("profile") != layout["profile"]:
        raise ValueError("unsupported native cache profile")
    if "scenario_id" in conditions and (not isinstance(conditions["scenario_id"], str)
                                        or not conditions["scenario_id"].strip()):
        raise ValueError("scenario_id must be a nonempty string")
    p_domains = conditions.get("p_domains")
    if type(p_domains) is not int or p_domains < 1:
        raise ValueError("p_domains must be a positive integer")
    if conditions.get("routing") == "all-p0":
        if p_domains != 1 or "routing_trace" in conditions:
            raise ValueError("all-p0 requires one P and no routing trace")
    elif conditions.get("routing") == "trace":
        if not isinstance(conditions.get("routing_trace"), str) or not conditions["routing_trace"]:
            raise ValueError("trace routing requires routing_trace path")
    else:
        raise ValueError("unsupported routing mode")
    for name in ("p_max_num_seqs", "p_max_num_batched_tokens", "client_max_in_flight"):
        value = conditions.get(name)
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if conditions.get("full_sequence_must_fit") is not layout["full_sequence_must_fit"]:
        raise ValueError("H20 profile requires recorded full-sequence admission")
    release_protocol = conditions.get("release_protocol")
    if release_protocol not in {
        "transfer-next-step-client-following-step",
        "transfer-after-specified-steps-client-following-step",
    }:
        raise ValueError("unsupported release protocol")
    transfer_delay = conditions.get("transfer_delay_steps")
    if type(transfer_delay) is not int or transfer_delay < 1:
        raise ValueError("transfer_delay_steps must be a positive integer")
    if release_protocol == "transfer-next-step-client-following-step" and transfer_delay != 1:
        raise ValueError("next-step release protocol requires transfer_delay_steps=1")
    if conditions.get("arrival_protocol") != "stable-ready-order-no-wall-time":
        raise ValueError("unsupported arrival protocol")
    budgets = budgets_from_conditions(conditions)
    validate_scenario(conditions, budgets)
    largest_pool = max(item["physical_blocks"] for item in budgets.values())
    if largest_pool * p_domains > 100_000:
        raise ValueError("scan exceeds 100000 aggregate physical blocks across P domains")
    if type(conditions.get("max_steps")) is not int or conditions["max_steps"] <= 0:
        raise ValueError("max_steps must be a positive integer")
    if type(conditions.get("event_limit")) is not int or conditions["event_limit"] < 0:
        raise ValueError("event_limit must be a nonnegative integer")
    for window in conditions.get("event_windows", []):
        if not (isinstance(window, list) and len(window) == 2
                and all(type(value) is int for value in window)
                and 1 <= window[0] <= window[1]):
            raise ValueError("invalid event window")
    return conditions


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("conditions", type=Path)
    args = parser.parse_args()
    selected = read_conditions(args.conditions)
    print(json.dumps({
        "profile": selected["profile"],
        "p_domains": selected["p_domains"],
        "routing": selected["routing"],
        "routing_trace": selected.get("routing_trace"),
        "capacities": budgets_from_conditions(selected),
        "p_max_num_seqs": selected["p_max_num_seqs"],
        "p_max_num_batched_tokens": selected["p_max_num_batched_tokens"],
        "client_max_in_flight": selected["client_max_in_flight"],
        "release_protocol": selected["release_protocol"],
    }, indent=2, ensure_ascii=False))
