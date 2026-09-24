"""Read-only inventory of the H20 425-request comparison assets.

Run from the repository root: python3 -m kvsim.native.audit_assets
"""

from __future__ import annotations

import json
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNS = {12: "formal-3430", 24: "formal-3429", 48: "formal-3425"}


def frozen_pair_reference() -> list[dict]:
    path = ROOT / "stage-v5/final-analysis/cpu-3468/summary.csv"
    with path.open(newline="") as stream:
        rows = {row["label"]: row for row in csv.DictReader(stream)}
    result = []
    for label in ("F12", "F24"):
        row = rows[label]
        if int(row["requests"]) != 425 or int(row["input_tokens"]) != 13707996:
            raise ValueError(f"invalid frozen-pair historical row: {label}")
        result.append({
            "label": label,
            "job": int(row["job"]),
            "capacity_gib_per_rank": int(row["p_kv_gib"]),
            "requests": int(row["requests"]),
            "actual_input_tokens": int(row["input_tokens"]),
            "query_hit_rate": float(row["query_hit_rate"]),
            "actual_input_cache_fraction": float(row["input_cache_fraction"]),
            "adopted_tokens": int(row["local_cache_hit"]),
            "local_compute_tokens": int(float(row["local_compute"])),
            "removed_hash_entries": int(row["removed_entries"]),
        })
    return result


def read_json(path: Path):
    return json.loads(path.read_text())


def audit() -> dict:
    runs = []
    for gib, name in RUNS.items():
        directory = ROOT / "stage-v4" / name
        p_config = read_json(directory / "P-config.json")
        command = p_config["command"]
        summary = read_json(directory / "point-summary.json")
        event_summary = read_json(directory / "event-summary.json")
        requests_path = directory / "replay" / "requests.jsonl"
        requests = [json.loads(line) for line in requests_path.read_text().splitlines()]
        samples_path = directory / "prompt-samples.jsonl"
        samples = samples_path.read_text().splitlines() if samples_path.exists() else []
        assert len(requests) == summary["planned"] == 425, name
        assert command[command.index("--kv-cache-memory-bytes") + 1] == str(gib * 2**30)
        assert summary["p_kv_budget_bytes_per_card"] == gib * 2**30
        assert command[command.index("--max-num-seqs") + 1] == "2"
        assert command[command.index("--max-num-batched-tokens") + 1] == "8192"
        assert command[command.index("--tensor-parallel-size") + 1] == "2"
        assert command[command.index("--kv-cache-dtype") + 1] == "fp8"
        assert "--enable-prefix-caching" in command
        actual_input_tokens = sum(r["input_tokens"] for r in requests)
        assert actual_input_tokens == summary["actual_input_tokens_sum"]
        assert (
            summary["p_local_compute_tokens"] + summary["p_local_cache_hit_tokens"]
            == actual_input_tokens
        )
        runs.append(
            {
                "name": name,
                "capacity_gib_per_rank": gib,
                "num_gpu_blocks": summary["p_num_gpu_blocks"],
                "scheduler_capacity_tokens": summary["p_scheduler_capacity_tokens"],
                "group_specs": event_summary["group_specs"],
                "requests": len(requests),
                "prompt_samples": len(samples),
                "request_fields": sorted(set().union(*(r.keys() for r in requests))),
                "actual_input_tokens": actual_input_tokens,
                "query_hit_rate": summary["p_local_hit_fraction"],
                "actual_input_cache_fraction": (
                    summary["p_local_cache_hit_tokens"] / actual_input_tokens
                ),
                "local_compute_tokens": summary["p_local_compute_tokens"],
                "query_tokens": summary["p_query_tokens"],
                "hit_tokens": summary["p_hit_tokens"],
                "removed_hash_entries": event_summary["total_removed_entries"],
            }
        )
    assert all(r["group_specs"] == runs[0]["group_specs"] for r in runs)
    return {
        "source": "stage-v4 formal run artifacts; read-only audit",
        "client_max_concurrency": read_json(ROOT / "stage-v4/formal-3429/replay-config.json")
        ["experiment"]["max_concurrency"],
        "runs": runs,
        "historical_content_coverage": "12 prompt samples per run; requests.jsonl has lengths and timestamps but no complete token arrays",
        "historical_scheduler_coverage": "No per-step P scheduler decisions or P reference release records identified in these run artifacts",
    }


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
