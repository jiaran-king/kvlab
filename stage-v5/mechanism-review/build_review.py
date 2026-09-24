#!/usr/bin/env python3
"""Build the bounded v5 mechanism-review artifacts from CPU summaries.

This script intentionally uses the persisted request summaries only.  It does
not infer block lifetimes and does not make another lookup call.
"""

import csv
import json
from pathlib import Path


STAGE = Path(__file__).resolve().parents[1]
DATA = STAGE / "final-analysis" / "cpu-3468"
OUT = Path(__file__).resolve().parent


def read_csv(path: Path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def calls(row):
    return json.loads(row["lookup_call_sequence"])


def is_group0_only(a, z, delta):
    ga, gz = calls(a), calls(z)
    if not ga or not gz or ga[0]["groups"] != [0] or gz[0]["groups"] != [0]:
        return False
    if gz[0]["returned"] - ga[0]["returned"] != delta:
        return False
    return all(x["candidate"] == x["returned"] for x in ga[1:] + gz[1:])


def has_joint_contraction(row):
    for x in calls(row):
        if x["groups"] == [1, 2] and x["candidate"] > 0 and x["returned"] < x["candidate"]:
            return True
    return False


def by_key(path):
    return {r["source_key"]: r for r in read_csv(path)}


def target_row(run, role, category, row, delta=""):
    keep = [
        "source_key", "client_request_id", "server_request_id", "context_after",
        "input_tokens", "output_tokens", "adopted_local_cache_tokens", "query_calls",
        "query_tokens", "query_hit_tokens", "external_tokens", "first_query_time",
        "first_schedule_decision", "ttft_seconds", "slot_wait_seconds",
        "enqueue_to_first_token_seconds", "actor_id", "session_id", "context_mode",
        "predecessor_input_tokens", "lcp_tokens", "admission_lookup_hit",
        "lcp_minus_adopted", "first_reducing_groups", "first_candidate",
        "first_returned", "lookup_call_sequence",
    ]
    out = {"run": run, "role": role, "category": category, "delta_F24_minus_F12": delta}
    out.update({k: row.get(k, "") for k in keep})
    return out


def main():
    f12 = by_key(DATA / "F12-requests.csv")
    f24 = by_key(DATA / "F24-requests.csv")
    paired = read_csv(DATA / "paired-requests.csv")
    deltas = {r["source_key"]: int(r["delta_A"]) for r in paired}

    positive = [k for k, d in deltas.items() if d > 0]
    group0 = [k for k in positive if is_group0_only(f12[k], f24[k], deltas[k])]
    joint = [k for k in positive if has_joint_contraction(f12[k])]
    # Keep the documented clean joint-group example as the representative.
    target_group0 = max(group0, key=lambda k: deltas[k])
    target_joint = "r00000183-d01c855532666b44"
    if target_joint not in joint:
        raise RuntimeError("the documented joint-group target is not present")

    targets = [target_group0, target_joint]
    rows = []
    for key in targets:
        category = "group0_return_boundary" if key == target_group0 else "joint_group_1_2_contraction"
        pred = f12[key]["context_after"]
        for run, data in (("F12", f12), ("F24", f24)):
            rows.append(target_row(run, "target", category, data[key], deltas[key]))
            if pred and pred in data:
                rows.append(target_row(run, "predecessor", category, data[pred], ""))

    fields = list(rows[0])
    with (OUT / "target-requests.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    net = sum(deltas.values())
    positive_gain = sum(d for d in deltas.values() if d > 0)
    summary = {
        "source": {
            "F12_requests": len(f12),
            "F24_requests": len(f24),
            "paired_requests": len(paired),
            "paired_net_adopted_gain": net,
            "positive_requests": sum(d > 0 for d in deltas.values()),
            "zero_requests": sum(d == 0 for d in deltas.values()),
            "negative_requests": sum(d < 0 for d in deltas.values()),
            "positive_gain": positive_gain,
        },
        "classification": {
            "group0_only_requests": len(group0),
            "group0_only_gain": sum(deltas[k] for k in group0),
            "joint_contraction_requests": len(joint),
            "joint_contraction_gain": sum(deltas[k] for k in joint),
            "group0_only_fraction_of_net": sum(deltas[k] for k in group0) / net,
            "joint_fraction_of_net": sum(deltas[k] for k in joint) / net,
        },
        "targets": {
            "group0_return_boundary": {
                "source_key": target_group0,
                "delta": deltas[target_group0],
                "selection": "largest positive delta among requests whose later group calls do not shrink the candidate",
            },
            "joint_group_1_2_contraction": {
                "source_key": target_joint,
                "delta": deltas[target_joint],
                "selection": "documented clean example: nonzero group-0 candidate is reduced to zero by joint [1,2] in F12",
            },
        },
        "effective_cache_config": {
            "num_blocks": 12393,
            "scheduler_block_size": 256,
            "hash_block_size": 4,
            "retention_interval": None,
            "groups": [
                {"group": 0, "manager": "FullAttentionManager", "block_size": 256, "sliding_window": None},
                {"group": 1, "manager": "SlidingWindowManager", "block_size": 64, "sliding_window": 128},
                {"group": 2, "manager": "SlidingWindowManager", "block_size": 64, "sliding_window": 128},
                {"group": 3, "manager": "SlidingWindowManager", "block_size": 4, "sliding_window": 8},
                {"group": 4, "manager": "SlidingWindowManager", "block_size": 8, "sliding_window": 128},
            ],
            "evidence": "stage-v5/formal-3454/query-diagnostic-1271803.jsonl effective_cache_config; the same source identity/configuration was accepted for C12/F12/F24",
        },
        "event_window": {
            "C12": {"formal_start_last_sequence": 0, "clear_sequence": 1, "formal_end_last_sequence": 591},
            "F12": {"formal_start_last_sequence": 1, "clear_sequence": 3, "formal_end_last_sequence": 537},
            "F24": {"formal_start_last_sequence": 2, "clear_sequence": 3, "formal_end_last_sequence": 418},
            "counting_rule": "count only BlockStored/BlockRemoved after the single AllBlocksCleared event and through the formal end sequence; explicitly require formal_start_last_sequence < sequence <= formal_end_last_sequence",
            "raw_event_limitation": "stage-v5 retains boundary summaries, not the full C12/F12/F24 kv-events.jsonl; the existing CPU run performed the full stream analysis",
        },
    }
    (OUT / "mechanism-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary["classification"], indent=2))


if __name__ == "__main__":
    main()
