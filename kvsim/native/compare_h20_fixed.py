"""Align the captured-input native scan with the historical F12/F24 pair.

This compares final adopted input-cache tokens by stable source key. It does
not equate historical local_compute with cumulative native input processing.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    with path.open() as stream:
        return [json.loads(line) for line in stream]


def compare(reference_dir: Path, execution_path: Path, scan_dir: Path,
            output_dir: Path) -> dict:
    execution = json.loads(execution_path.read_text())
    source_by_request = {
        node["runtime_request_id"]: node["source_key"]
        for task in execution["tasks"] for node in task["nodes"]
        if node.get("node_type") == "request"
    }
    if len(source_by_request) != 425:
        raise ValueError("expected 425 mapped captured requests")

    aligned = {}
    summary = {}
    for gib in (12, 24):
        with (reference_dir / f"F{gib}-requests.csv").open(newline="") as stream:
            historical_rows = list(csv.DictReader(stream))
        historical = {row["source_key"]: row for row in historical_rows}
        simulated = load_jsonl(scan_dir / f"{gib}gib/requests.jsonl")
        if len(historical) != 425 or len(simulated) != 425:
            raise ValueError(f"{gib} GiB does not contain 425 requests")
        if len(historical) != len(historical_rows):
            raise ValueError(f"duplicate historical source keys at {gib} GiB")
        rows = {}
        for native in simulated:
            source_key = source_by_request[native["request_id"]]
            reference = historical[source_key]
            if native["input_tokens"] != int(reference["input_tokens"]):
                raise ValueError(f"input length mismatch for {source_key}")
            real = int(reference["adopted_local_cache_tokens"])
            offline = native["initial_adopted_tokens"]
            rows[source_key] = {
                "order": native["order"], "source_key": source_key,
                "input_tokens": native["input_tokens"],
                "lcp_with_predecessor": int(reference["lcp_tokens"]),
                "context_after": reference["context_after"],
                "historical_adopted": real,
                "native_adopted": offline,
                "native_minus_historical": offline - real,
                "native_submitted_step": native["submitted_step"],
                "native_first_scheduled_step": native["first_scheduled_step"],
            }
        if len(rows) != 425 or set(rows) != set(historical):
            raise ValueError(f"source key mismatch at {gib} GiB")
        aligned[gib] = rows
        different = [row for row in rows.values()
                     if row["native_minus_historical"]]
        summary[gib] = {
            "different_requests": len(different),
            "native_more_requests": sum(row["native_minus_historical"] > 0
                                        for row in different),
            "native_less_requests": sum(row["native_minus_historical"] < 0
                                        for row in different),
            "net_native_minus_historical": sum(
                row["native_minus_historical"] for row in different),
            "absolute_difference": sum(abs(row["native_minus_historical"])
                                       for row in different),
            "first_difference": min(different, key=lambda row: row["order"]),
            "first_difference_at_least_1024": min(
                (row for row in different
                 if abs(row["native_minus_historical"]) >= 1024),
                key=lambda row: row["order"], default=None),
            "largest_differences": sorted(
                different, key=lambda row: abs(row["native_minus_historical"]),
                reverse=True)[:10],
        }

    real_gain = {
        key for key in aligned[12]
        if aligned[24][key]["historical_adopted"]
        > aligned[12][key]["historical_adopted"]
    }
    native_gain = {
        key for key in aligned[12]
        if aligned[24][key]["native_adopted"]
        > aligned[12][key]["native_adopted"]
    }
    gain_overlap = {
        "historical_positive_requests": len(real_gain),
        "native_positive_requests": len(native_gain),
        "shared_positive_requests": len(real_gain & native_gain),
        "historical_only": len(real_gain - native_gain),
        "native_only": len(native_gain - real_gain),
    }
    result = {
        "basis": "C12-captured P inputs, F12/F24 historical adoption, "
                 "native scan aligned by source_key and input length",
        "capacity_summary": summary,
        "capacity_gain_request_overlap": gain_overlap,
        "limits": [
            "Historical scheduling, P arrivals, transfer and reference-release "
            "times were not replayed.",
            "Adoption differences alone do not identify the cause of a cache miss.",
            "Historical local_compute and native cumulative processing are "
            "different counters.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    with (output_dir / "requests.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["order", "source_key", "input_tokens", "context_after",
                         "lcp_with_predecessor", "F12_adopted", "native12_adopted",
                         "native12_minus_F12", "F24_adopted", "native24_adopted",
                         "native24_minus_F24", "native12_submitted_step",
                         "native24_submitted_step"])
        for key in sorted(aligned[12], key=lambda k: aligned[12][k]["order"]):
            a, b = aligned[12][key], aligned[24][key]
            writer.writerow([
                a["order"], key, a["input_tokens"], a["context_after"],
                a["lcp_with_predecessor"], a["historical_adopted"],
                a["native_adopted"], a["native_minus_historical"],
                b["historical_adopted"], b["native_adopted"],
                b["native_minus_historical"], a["native_submitted_step"],
                b["native_submitted_step"],
            ])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference_dir", type=Path)
    parser.add_argument("execution_json", type=Path)
    parser.add_argument("native_scan_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    result = compare(args.reference_dir, args.execution_json,
                     args.native_scan_dir, args.output_dir)
    print(json.dumps({"capacity_summary": {
        gib: {k: v for k, v in row.items()
              if k not in {"first_difference", "first_difference_at_least_1024",
                           "largest_differences"}}
        for gib, row in result["capacity_summary"].items()},
        "capacity_gain_request_overlap": result["capacity_gain_request_overlap"]},
        indent=2))


if __name__ == "__main__":
    main()
