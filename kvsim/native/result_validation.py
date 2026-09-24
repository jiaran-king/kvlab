"""Internal consistency checks for one native capacity result."""

from __future__ import annotations

import json
import math
from pathlib import Path

from kvsim.native.accounting import completed_input_totals


def load_jsonl(path: Path) -> list[dict]:
    with path.open() as stream:
        return [json.loads(line) for line in stream]


def scan_binding(manifests: dict) -> dict:
    hashes = {manifest.get("workload_sha256") for manifest in manifests.values()}
    if len(hashes) != 1:
        raise ValueError("scan workload identities differ")
    return {"runs": {str(key): value.get("run_id") for key, value in manifests.items()},
            "workload_sha256": next(iter(hashes))}


def validate_scan_binding(document: dict, manifests: dict, label: str) -> None:
    binding = scan_binding(manifests)
    if not binding["workload_sha256"] or not all(binding["runs"].values()):
        raise ValueError(f"{label}: legacy run identity is insufficient for attachment")
    if any(document.get(key) != value for key, value in binding.items()):
        raise ValueError(f"{label}: run/workload binding differs; regenerate from this scan")


def validate_rates(item: dict, label: str, *, complete: bool) -> None:
    for numerator, denominator, rate in (
        ("prefix_hits", "prefix_queries", "prefix_query_hit_rate"),
        ("initial_adopted_cache_tokens", "actual_input_tokens", "actual_input_cache_fraction"),
    ):
        n, d, value = item[numerator], item[denominator], item.get(rate)
        if type(n) is not int or type(d) is not int or not 0 <= n <= d:
            raise ValueError(f"{label}: invalid {numerator}/{denominator}")
        # Incomplete runs deliberately withhold the full-workload adoption rate.
        if d == 0 or (not complete and rate == "actual_input_cache_fraction" and value is None):
            if value is not None:
                raise ValueError(f"{label}: {rate} must be NA for a zero denominator")
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or not math.isclose(
            value, n / d, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(f"{label}: {rate} disagrees with {numerator}/{denominator}")


def round_observation(steps: list[dict], domains: list[str], complete: bool) -> dict:
    """Only an incomplete terminal round may be a prefix of domain order."""
    by_round = {}
    previous = (0, -1)
    for row in steps:
        domain = row.get("p_domain", "p0")
        if domain not in domains or type(row["step"]) is not int:
            raise ValueError("invalid logical round/P domain")
        position = (row["step"], domains.index(domain))
        if position <= previous:
            raise ValueError("logical round rows are duplicated or out of order")
        previous = position
        by_round.setdefault(row["step"], []).append(row)
    if list(by_round) != list(range(1, len(by_round) + 1)):
        raise ValueError("logical rounds have a missing middle step")
    full = []
    partial = None
    for step, group in by_round.items():
        seen = [row.get("p_domain", "p0") for row in group]
        if seen == domains:
            full.append(group)
        elif complete or step != max(by_round) or seen != domains[:len(seen)]:
            raise ValueError("a logical round lacks one step for each P outside the incomplete tail")
        else:
            partial = {"step": step, "observed_p_domains": seen,
                       "unobserved_p_domains": domains[len(seen):],
                       "active_ref_blocks_observed_sum": sum(row["active_ref_blocks_after_schedule"] for row in group)}
    return {"last_full_round": len(full), "partial_round": partial,
            "full_round_active_peak": max((sum(row["active_ref_blocks_after_schedule"] for row in group)
                                           for group in full), default=None)}


def validate_capacity(directory: Path) -> tuple[dict, list[dict]]:
    summary = json.loads((directory / "summary.json").read_text())
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if (manifest.get("run_id") or summary.get("run_id")) and manifest.get("run_id") != summary.get("run_id"):
            raise ValueError(f"{directory.name}: manifest and summary run IDs differ")
    rows = load_jsonl(directory / "requests.jsonl")
    label = directory.name
    planned = summary["requests_planned"]
    completed = summary["requests_completed"]
    if type(planned) is not int or type(completed) is not int or not 0 <= completed <= planned:
        raise ValueError(f"{label}: invalid planned/completed counts")
    if len(rows) != planned:
        raise ValueError(f"{label}: {len(rows)} request rows, summary plans {planned}")
    ids = [row["request_id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{label}: duplicate request ID")
    if [row["order"] for row in rows] != list(range(planned)):
        raise ValueError(f"{label}: request order is not contiguous")
    actual_completed = sum(row["client_complete_step"] is not None for row in rows)
    if actual_completed != completed:
        raise ValueError(f"{label}: {actual_completed} completed request rows, summary says {completed}")
    if summary.get("requests_unfinished") != planned - completed:
        raise ValueError(f"{label}: unfinished request count disagrees with rows")
    for row in rows:
        if (type(row["input_tokens"]) is not int or row["input_tokens"] <= 0
            or type(row["initial_adopted_tokens"]) is not int
            or not 0 <= row["initial_adopted_tokens"] <= row["input_tokens"]
            or type(row["cumulative_input_processing_tokens"]) is not int
            or row["cumulative_input_processing_tokens"] < 0):
            raise ValueError(f"{label}: invalid token counts for {row['request_id']}")
        if "completed_input_intervals" in row:
            intervals = row["completed_input_intervals"]
            if any(not 0 <= item["start"] < item["end"] <= row["input_tokens"]
                   or not 1 <= item["step"] <= summary["logical_steps"] for item in intervals):
                raise ValueError(f"{label}: invalid completed input interval for {row['request_id']}")
            if any(row.get(key) != value for key, value in completed_input_totals(intervals).items()):
                raise ValueError(f"{label}: input accounting disagrees with completed intervals")
    totals = {
        "actual_input_tokens": sum(row["input_tokens"] for row in rows),
        "initial_adopted_cache_tokens": sum(row["initial_adopted_tokens"] for row in rows),
        "cumulative_input_processing_tokens": sum(row["cumulative_input_processing_tokens"] for row in rows),
    }
    for name, actual in totals.items():
        if summary[name] != actual:
            raise ValueError(f"{label}: {name} summary {summary[name]} disagrees with request rows {actual}")
    validate_rates(summary, label, complete=summary.get("status") == "complete")
    if "per_p" in summary:
        per_p = summary["per_p"]
        if set(per_p) != {f"p{i}" for i in range(summary["p_domains"])}:
            raise ValueError(f"{label}: P domain summary coverage differs from declared domains")
        if any(row.get("p_domain") not in per_p for row in rows):
            raise ValueError(f"{label}: request assigned to unknown P domain")
        for domain, item in per_p.items():
            validate_rates(item, f"{label}/{domain}", complete=summary.get("status") == "complete")
            members = [row for row in rows if row["p_domain"] == domain]
            expected = {
                "requests_planned": len(members),
                "requests_completed": sum(row["client_complete_step"] is not None for row in members),
                "actual_input_tokens": sum(row["input_tokens"] for row in members),
                "initial_adopted_cache_tokens": sum(row["initial_adopted_tokens"] for row in members),
                "cumulative_input_processing_tokens": sum(
                    row["cumulative_input_processing_tokens"] for row in members),
            }
            if any(item.get(key) != value for key, value in expected.items()):
                raise ValueError(f"{label}: {domain} summary disagrees with request rows")
        for key in ("requests_planned", "requests_completed", *totals,
                    "prefix_queries", "prefix_hits", "preempted_queries", "preempted_hits"):
            if sum(item[key] for item in per_p.values()) != summary[key]:
                raise ValueError(f"{label}: global {key} differs from P totals")
        steps = load_jsonl(directory / "steps.jsonl")
        if summary["status"] == "complete" and not steps:
            raise ValueError(f"{label}: complete run lacks logical round records")
        if any("active_ref_blocks_after_schedule" in row for row in steps) and not all(
            "active_ref_blocks_after_schedule" in row for row in steps
        ):
            raise ValueError(f"{label}: logical round records have missing block observations")
        if steps and all("active_ref_blocks_after_schedule" in step for step in steps):
            boundary = round_observation(steps, [f"p{i}" for i in range(summary["p_domains"])], summary["status"] == "complete")
            if summary.get("observation_boundary", boundary) != boundary:
                raise ValueError(f"{label}: recorded observation boundary differs from steps")
            if boundary["partial_round"] is not None or "observation_boundary" in summary:
                summary["observation_boundary"] = boundary
            peak = boundary["full_round_active_peak"]
            if summary.get("peak_active_blocks_global") != peak:
                raise ValueError(f"{label}: global active peak is not from one logical round")
            for domain, item in per_p.items():
                domain_steps = [row for row in steps if row.get("p_domain", "p0") == domain]
                if item.get("peak_active_blocks") != max(
                    (row["active_ref_blocks_after_schedule"] for row in domain_steps), default=0
                ) or item.get("peak_reusable_cached_blocks") != max(
                    (row["reusable_cached_blocks_after_schedule"] for row in domain_steps), default=0
                ):
                    raise ValueError(f"{label}: {domain} block peaks disagree with steps")
    if summary["status"] == "complete":
        if completed != planned or summary.get("failure_reason") is not None:
            raise ValueError(f"{label}: complete status disagrees with request completion")
        expected_fraction = totals["initial_adopted_cache_tokens"] / totals["actual_input_tokens"]
        if abs(summary["actual_input_cache_fraction"] - expected_fraction) > 1e-12:
            raise ValueError(f"{label}: input cache fraction disagrees with request rows")
    elif summary["status"] in {"incomplete", "not_run"}:
        if not summary.get("failure_reason"):
            raise ValueError(f"{label}: incomplete result lacks failure reason")
        if summary["status"] == "not_run" and (completed != 0 or summary.get("logical_steps") != 0):
            raise ValueError(f"{label}: unstarted point has completed work")
    else:
        raise ValueError(f"{label}: unknown result status {summary['status']!r}")
    return summary, rows
