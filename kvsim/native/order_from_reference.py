"""Freeze a captured workload in one historical P first-query order.

This is a conditional-order experiment. It uses only request identity and
first-query time from a reference run, never reference hit/adoption outcomes.
It does not independently validate Scheduler ordering or wall-clock timing.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path


def read_json(path: Path) -> dict:
    if path.suffix == ".gz":
        with gzip.open(path, "rt") as stream:
            return json.load(stream)
    return json.loads(path.read_text())


def freeze_order(workload_path: Path, reference_csv: Path,
                 output_path: Path, label: str) -> dict:
    workload = read_json(workload_path)
    if workload.get("schema") != "kvlab-replay-workload/v1":
        raise ValueError("unsupported workload schema")
    requests = workload["requests"]
    by_key = {row["source_key"]: row for row in requests}
    if len(by_key) != len(requests):
        raise ValueError("duplicate captured source keys")
    with reference_csv.open(newline="") as stream:
        reference = list(csv.DictReader(stream))
    times = {}
    for row in reference:
        key = row["source_key"]
        if key in times:
            raise ValueError(f"duplicate reference source key: {key}")
        times[key] = float(row["first_query_time"])
        if len(by_key[key]["tokens"]) != int(row["input_tokens"]):
            raise ValueError(f"captured input length mismatch: {key}")
    if set(times) != set(by_key):
        raise ValueError("reference and captured request keys differ")
    ordered = sorted(requests, key=lambda row: (times[row["source_key"]],
                                                row["source_key"]))
    rank_by_id = {row["runtime_request_id"]: i
                  for i, row in enumerate(ordered)}
    for i, row in enumerate(ordered):
        for field in ("send_after", "context_after"):
            predecessor = row[field]
            if predecessor is not None and rank_by_id[predecessor] >= i:
                raise ValueError(f"reference order violates {field} for {row['source_key']}")
    workload["requests"] = ordered
    metadata = workload["metadata"]
    metadata["execution_profile"] = "historical-first-query-order-conditional"
    metadata["historical_order_source"] = {
        "label": label,
        "reference_csv": str(reference_csv),
        "field": "first_query_time",
        "meaning": "observed P first-lookup order, not arrival or release time",
    }
    metadata.setdefault("assumptions", []).append(
        "Requests are submitted in observed P first-query order when dependencies "
        "and client slots permit; original wall-clock gaps and P releases are not replayed."
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output_path, "wt", compresslevel=6) as stream:
        json.dump(workload, stream, ensure_ascii=False, separators=(",", ":"))
    return {
        "label": label,
        "requests": len(ordered),
        "input_tokens": sum(len(row["tokens"]) for row in ordered),
        "first_keys": [row["source_key"] for row in ordered[:20]],
        "output": str(output_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captured_workload", type=Path)
    parser.add_argument("reference_requests_csv", type=Path)
    parser.add_argument("output_workload_gz", type=Path)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    print(json.dumps(freeze_order(args.captured_workload,
                                  args.reference_requests_csv,
                                  args.output_workload_gz,
                                  args.label), indent=2))


if __name__ == "__main__":
    main()
