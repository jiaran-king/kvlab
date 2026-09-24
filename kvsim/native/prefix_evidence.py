"""Explain first capacity differences using native events and frozen tokens.

Run after compare.py with the final fixed-seed sweep and its original workload.
"""

from __future__ import annotations

import hashlib
import json
import gzip
import pickle
import sys
from collections import Counter
from pathlib import Path

from kvsim.native.capacity import point_directory
from kvsim.native.compare import comparison_pairs
from kvsim.native.result_validation import validate_scan_binding, validate_capacity


def sha256(value) -> bytes:
    return hashlib.sha256(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)).digest()


def prefix_hash_positions(tokens: list[int], limit: int) -> dict[int, int]:
    previous = sha256("0")  # PYTHONHASHSEED=0 in the native run.
    positions = {}
    for start in range(0, limit - limit % 4, 4):
        previous = sha256((previous, tuple(tokens[start:start + 4]), None))
        positions[int.from_bytes(previous, "big") & ((1 << 64) - 1)] = start + 4
    return positions


def collect_side(root: Path, gib: int, admission_step: int,
                 positions: dict[int, int], p_domain: str = "p0") -> dict:
    manifest = json.loads((point_directory(root, gib) / "manifest.json").read_text())
    snapshot = None
    with (point_directory(root, gib) / "steps.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            if row["step"] == admission_step and row.get("p_domain", "p0") == p_domain:
                snapshot = row
                break
    if snapshot is None:
        raise ValueError(f"{gib} GiB has no recorded admission step {admission_step}")
    nearby = Counter()
    matching = []
    with (point_directory(root, gib) / "events.jsonl").open() as stream:
        for line in stream:
            event = json.loads(line)
            if event["kind"] != "native_kv_event":
                continue
            if event.get("p_domain", "p0") != p_domain:
                continue
            if admission_step - 2 <= event["step"] <= admission_step:
                data = event["data"]
                group = data.get("group_idx")
                nearby[f"{event['event']}:group{group}"] += len(data.get("block_hashes", []))
            if event["step"] > admission_step:
                continue
            matches = [positions[int(value)] for value in event["data"].get("block_hashes", [])
                       if int(value) in positions]
            if matches:
                matching.append({
                    "step": event["step"],
                    "event": event["event"],
                    "group": event["data"].get("group_idx"),
                    "prefix_end_positions": matches,
                })
    return {
        "run_id": manifest.get("run_id"),
        "point_id": gib,
        "p_domain": p_domain,
        "admission_step": admission_step,
        "running_before": snapshot["running_before"],
        "waiting_before": snapshot["waiting_before"],
        "free_blocks_before": snapshot["free_blocks_before"],
        "free_blocks_after_schedule": snapshot["free_blocks_after_schedule"],
        "scheduled": snapshot["scheduled"],
        "nearby_event_entries": dict(nearby),
        "matching_prefix_event_count": len(matching),
        "matching_prefix_events": matching[:100],
        "matching_prefix_events_truncated": len(matching) > 100,
    }


def make_evidence(root: Path, workload_path: Path) -> dict:
    comparison = json.loads((root / "comparison.json").read_text())
    point_ids = comparison.get("point_ids", comparison.get("capacities_gib"))
    pair_ids = {f"{a}_vs_{b}": (a, b) for a, b in comparison_pairs(
        tuple(comparison.get("comparable_complete_gib", point_ids)))}
    manifests = [json.loads((point_directory(root, gib) / "manifest.json").read_text())
                 for gib in point_ids]
    validate_scan_binding(comparison, dict(zip(point_ids, manifests)), "comparison")
    for point in point_ids:
        summary, rows = validate_capacity(point_directory(root, point))
        if comparison.get("summaries", {}).get(str(point)) != summary:
            raise ValueError("comparison summary differs from actual run")
        for pair, difference in (comparison.get("first_request_difference") or {}).items():
            if pair not in pair_ids:
                raise ValueError("comparison pair is not a complete-point pair")
            if difference:
                for side, side_point in zip(("left", "right"), pair_ids[pair]):
                    if side_point == point and difference[side] != rows[difference["order"]]:
                        raise ValueError("comparison request differs from actual run")
    recorded = {manifest.get("workload_sha256") for manifest in manifests}
    actual = hashlib.sha256(workload_path.read_bytes()).hexdigest()
    if len(recorded) != 1 or actual not in recorded:
        raise ValueError("evidence workload bytes do not match run manifest SHA256")
    if workload_path.suffix == ".gz":
        with gzip.open(workload_path, "rt") as stream:
            workload = json.load(stream)
    else:
        workload = json.loads(workload_path.read_text())
    tokens_by_id = {
        row["runtime_request_id"]: row["tokens"] for row in workload["requests"]
    }
    findings = {}
    for pair, difference in (comparison.get("first_request_difference") or {}).items():
        if difference is None:
            findings[pair] = None
            continue
        request_id = difference["request_id"]
        limit = max(difference["left"]["initial_adopted_tokens"],
                    difference["right"]["initial_adopted_tokens"])
        positions = prefix_hash_positions(tokens_by_id[request_id], limit)
        left_gib, right_gib = pair_ids[pair]
        findings[pair] = {
            "request_order": difference["order"],
            "request_id": request_id,
            "input_sha256": hashlib.sha256(json.dumps(
                tokens_by_id[request_id], separators=(",", ":")
            ).encode()).hexdigest(),
            "left_p_domain": difference["left"].get("p_domain", "p0"),
            "right_p_domain": difference["right"].get("p_domain", "p0"),
            "prefix_hash_limit_tokens": limit,
            "left_point_id": left_gib,
            "right_point_id": right_gib,
            "left": collect_side(root, left_gib,
                                 difference["left"]["first_scheduled_step"], positions,
                                 difference["left"].get("p_domain", "p0")),
            "right": collect_side(root, right_gib,
                                  difference["right"]["first_scheduled_step"], positions,
                                  difference["right"].get("p_domain", "p0")),
        }
    result = {
        "workload_sha256": actual,
        "runs": {str(point): manifest.get("run_id")
                 for point, manifest in zip(point_ids, manifests)},
        "method": "SHA256/pickle native 4-token hash chain with frozen PYTHONHASHSEED=0; match to recorded native events",
        "scope": "events.jsonl contains only configured step windows; absence of an event outside those windows is unknown",
        "findings": findings,
    }
    (root / "first-difference-evidence.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False)
    )
    report_path = root / "REPORT.md"
    report = report_path.read_text()
    section = ["", "## Evidence at the first differences", ""]
    for pair in findings:
        finding = findings.get(pair)
        if finding is None:
            continue
        left, right = finding["left"], finding["right"]
        before = [
            event for event in left["matching_prefix_events"]
            if event["event"] == "BlockRemoved"
            and left["admission_step"] - 2 <= event["step"] < left["admission_step"]
        ]
        section.append(
            f"- {pair}, request {finding['request_order']}: admitted at separate logical steps "
            f"{left['admission_step']} and {right['admission_step']}; "
            f"running P requests just before admission: {len(left['running_before'])} and "
            f"{len(right['running_before'])}. The baseline window contains "
            f"{len(before)} recorded removals of hashes in this request's candidate prefix "
            f"during the two steps before its admission."
        )
    section.extend([
        "", "`first-difference-evidence.json` records the matching hash positions, group events, and read-only block snapshots. Free blocks include idle cached blocks eligible for replacement, so a high free count does not imply absence of cache pressure. Event files cover selected step windows only; a missing event outside those windows is unknown. These observations show relevant state changes but do not establish a unique cause for every miss.",
        "", "Recreate this section: `python -m kvsim.native.compare <sweep-dir>` followed by `python -m kvsim.native.prefix_evidence <sweep-dir> <frozen-workload.json>`.",
    ])
    if findings and not any(findings.values()):
        section = ["", "## Evidence at the first differences", "",
                   "No request differs in initial cache adoption or cumulative input processing "
                   "between the completed capacity points. There is no first-difference "
                   "request to explain in this sweep.", ""]
    elif not findings:
        section = ["", "## Evidence at the first differences", "",
                   "No comparable complete-point pair is available for request evidence.", ""]
    if "## Evidence at the first differences" not in report:
        report_path.write_text(report + "\n".join(section) + "\n")
    return result


if __name__ == "__main__":
    root = Path(sys.argv[1])
    result = make_evidence(root, Path(sys.argv[2]))
    print(json.dumps({"status": "evidence_generated", "result_path": str((root / "first-difference-evidence.json").resolve())}))
