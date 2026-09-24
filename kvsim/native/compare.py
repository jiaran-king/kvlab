"""Compare native capacity results by frozen workload order.

Usage: python3 -m kvsim.native.compare <sweep-output-directory>
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from kvsim.native.result_validation import load_jsonl, validate_capacity, scan_binding
from kvsim.native.capacity import point_directory
from kvsim.native.semantics import execution_conditions, source_identity, route_identity, validate_mechanism_pair


def scan_capacities(root: Path) -> tuple[int, ...]:
    plan = root / "scan.json"
    if plan.exists():
        data = json.loads(plan.read_text())
        values = data.get("point_ids", data.get("capacities_gib"))
        if not isinstance(values, list) or not values or any(type(x) is not int and (not isinstance(x, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", x)) for x in values):
            raise ValueError("invalid scan capacity list")
        capacities = tuple(values)
    else:
        capacities = tuple(sorted(int(match.group(1)) for path in root.iterdir()
                                  if path.is_dir() and (match := re.fullmatch(r"(\d+)gib", path.name))))
    if not capacities or len(capacities) != len(set(capacities)) or (all(type(x) is int for x in capacities) and capacities != tuple(sorted(capacities))):
        raise ValueError("scan needs unique ascending capacity points")
    return capacities


def comparison_pairs(capacities: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    pairs = list(zip(capacities, capacities[1:]))
    if len(capacities) > 2:
        pairs.append((capacities[0], capacities[-1]))
    return tuple(pairs)


def read_reference(path: Path | None = None) -> dict:
    path = path or Path(__file__).with_name("h20-reference.json")
    reference = json.loads(path.read_text())
    if reference.get("schema") != "kvlab-h20-historical-reference/v1":
        raise ValueError("unsupported H20 historical reference")
    return reference


def compare(root: Path, reference_path: Path | None = None) -> dict:
    capacities = scan_capacities(root)
    validated = {gib: validate_capacity(point_directory(root, gib)) for gib in capacities}
    summaries = {gib: item[0] for gib, item in validated.items()}
    if any(summaries[gib].get("point_id", summaries[gib]["capacity_gib_per_rank"]) != gib for gib in capacities):
        raise ValueError("capacity summary disagrees with its directory")
    manifests = {gib: json.loads((point_directory(root, gib) / "manifest.json").read_text())
                 for gib in capacities}
    sources = {summary["content_source"] for summary in summaries.values()}
    if len(sources) != 1:
        raise ValueError("capacity runs use different content sources")
    source = sources.pop()
    workload_hashes = {manifest.get("workload_sha256") for manifest in manifests.values()}
    if len(workload_hashes) != 1:
        raise ValueError("capacity runs use different frozen workload contents")
    workload_identity = next(iter(workload_hashes))
    if workload_identity is None and len({manifest.get("workload_path") for manifest in manifests.values()}) != 1:
        raise ValueError("legacy runs without workload SHA256 require one recorded workload path")
    conditions = [manifests[gib]["conditions"] for gib in capacities]
    semantics = [execution_conditions(manifests[gib]) for gib in capacities]
    if any(condition != semantics[0] for condition in semantics):
        raise ValueError("capacity runs use different execution conditions")
    if "capacities_gib" in conditions[0] and tuple(conditions[0]["capacities_gib"]) != capacities:
        raise ValueError("scan capacities disagree with conditions")
    routes = [route_identity(manifests[gib], validated[gib][1]) for gib in capacities]
    if any(route != routes[0] for route in routes):
        raise ValueError("capacity runs use different frozen routing traces")
    rows = {gib: item[1] for gib, item in validated.items()}
    base_ids = [row["request_id"] for row in rows[capacities[0]]]
    if any([row["request_id"] for row in rows[gib]] != base_ids for gib in capacities):
        raise ValueError("capacity runs do not contain the same ordered requests")
    if any([row["input_tokens"] for row in rows[gib]] !=
           [row["input_tokens"] for row in rows[capacities[0]]] for gib in capacities):
        raise ValueError("capacity runs do not have the same input lengths")
    baseline_digests = [row.get("input_sha256") for row in rows[capacities[0]]]
    if all(baseline_digests) and any(
        all(row.get("input_sha256") for row in rows[gib]) and
        [row["input_sha256"] for row in rows[gib]] != baseline_digests
        for gib in capacities
    ):
        raise ValueError("capacity runs do not have the same request input digests")
    completed = tuple(gib for gib in capacities if summaries[gib].get("status") == "complete"
                      and summaries[gib]["requests_completed"] == summaries[gib]["requests_planned"])
    for point in completed[1:]:
        validate_mechanism_pair(manifests[completed[0]], manifests[point])
    identities = [source_identity(manifests[gib]) for gib in completed]
    if any(identity != identities[0] for identity in identities):
        raise ValueError("capacity runs use different native source identities")
    effective_profiles = [manifests[gib].get("effective_native_profile") for gib in completed]
    if any(profile != effective_profiles[0] for profile in effective_profiles):
        raise ValueError("capacity runs use different effective native profiles")
    accounting = [manifests[gib].get("input_accounting") for gib in completed]
    if any(item != accounting[0] for item in accounting):
        raise ValueError("capacity runs use different input accounting protocols")
    incomplete = [gib for gib, summary in summaries.items()
                  if summary.get("status", "complete") != "complete"
                  or summary["requests_completed"] != summary["requests_planned"]]
    if incomplete:
        first = {}
        for left, right in comparison_pairs(completed):
            difference = next(((a, b) for a, b in zip(rows[left], rows[right])
                               if a["initial_adopted_tokens"] != b["initial_adopted_tokens"]
                               or a["cumulative_input_processing_tokens"] != b["cumulative_input_processing_tokens"]), None)
            first[f"{left}_vs_{right}"] = ({
                "order": difference[0]["order"], "request_id": difference[0]["request_id"],
                "left": difference[0], "right": difference[1],
            } if difference else None)
        with (root / "comparison.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["capacity_gib_per_rank", "status", "completed",
                             "planned", "failure_reason"])
            for gib, summary in summaries.items():
                writer.writerow([gib, summary.get("status", "incomplete"),
                                 summary["requests_completed"],
                                 summary["requests_planned"],
                                 summary.get("failure_reason") or ""])
        result = {**scan_binding(manifests), "status": "incomplete", "point_ids": capacities,
                  **({"capacities_gib": capacities} if all(type(x) is int for x in capacities) else {}),
                  "comparable_complete_gib": completed, "summaries": summaries,
                  "workload_identity_verified": workload_identity is not None,
                  "first_request_difference": first}
        (root / "comparison.json").write_text(json.dumps(result, indent=2))
        lines = ["# Native capacity scan — incomplete", "",
                 "At least one capacity point did not complete; its partial requests, steps and events remain in its output directory.",
                 "", "| Point | Completed | Status | Reason |",
                 "|---:|---:|---|---|"]
        for gib, summary in summaries.items():
            lines.append(f"| {gib} | {summary['requests_completed']}/{summary['requests_planned']} | "
                         f"{summary.get('status', 'incomplete')} | "
                         f"{summary.get('failure_reason') or '—'} |")
        lines.extend(["", "Complete-point pairs remain comparable under the recorded workload and conditions:"])
        if workload_identity is None:
            lines.append("Legacy manifests have no workload SHA256; content equality is unverified.")
        for pair, difference in first.items():
            lines.append(f"- {pair}: " + (f"first difference at request {difference['order']}"
                                            if difference else "no per-request adopted/processed difference"))
        (root / "REPORT.md").write_text("\n".join(lines) + "\n")
        return result
    first = {}
    for left, right in comparison_pairs(capacities):
        difference = next((
            (a, b) for a, b in zip(rows[left], rows[right])
            if a["initial_adopted_tokens"] != b["initial_adopted_tokens"]
            or a["cumulative_input_processing_tokens"] != b["cumulative_input_processing_tokens"]
        ), None)
        first[f"{left}_vs_{right}"] = (
            {
                "order": difference[0]["order"],
                "request_id": difference[0]["request_id"],
                "left": difference[0],
                "right": difference[1],
            } if difference else None
        )

    with (root / "comparison.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "order", "request_id", "session_id", "input_tokens",
            *[f"adopted_{gib}" for gib in capacities],
            *[f"processed_{gib}" for gib in capacities],
        ])
        for items in zip(*(rows[gib] for gib in capacities)):
            writer.writerow([
                items[0]["order"], items[0]["request_id"],
                items[0]["session_id"], items[0]["input_tokens"],
                *[item["initial_adopted_tokens"] for item in items],
                *[item["cumulative_input_processing_tokens"] for item in items],
            ])

    result = {
        **scan_binding(manifests),
        "status": "complete",
        "comparison_basis": ("same frozen workload SHA256, request order and input lengths"
                             if workload_identity is not None else
                             "legacy shared workload path and aligned requests; content SHA256 unavailable"),
        "content_source": source,
        "point_ids": capacities,
                  **({"capacities_gib": capacities} if all(type(x) is int for x in capacities) else {}), "summaries": summaries,
        "first_request_difference": first,
    }
    (root / "comparison.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    lines = [
        "# Native H20-profile controlled capacity scan",
        "",
        (f"All {len(capacities)} points use the same " + {
            "historical_capture": "captured historical P-side token workload",
            "captured_tokens": "captured token workload (provenance recorded in manifests)",
            "trace_driven_synthetic": "trace-driven synthetic token workload",
            "synthetic": "explicitly synthetic mechanism workload",
        }[source] +
         " and deterministic logical release protocol. Results are a new controlled experiment, not a reproduction of the historical runs."),
        "",
        "| Point | Complete | Native query hit | Adopted input cache | Cumulative input processing | Removed hash entries | Steps |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for gib in capacities:
        summary = summaries[gib]
        query_rate = summary["prefix_query_hit_rate"]
        query_display = f"{query_rate:.2%}" if query_rate is not None else "—"
        lines.append(
            f"| {gib} | {summary['requests_completed']}/{summary['requests_planned']} | "
            f"{query_display} | "
            f"{summary['actual_input_cache_fraction']:.2%} | "
            f"{summary['cumulative_input_processing_tokens']:,} | "
            f"{sum(summary['removed_hash_entries_by_group'].values()):,} | "
            f"{summary['logical_steps']:,} |"
        )
    provenance = manifests[capacities[0]].get("workload_capture_provenance") or {}
    c12_capture = (source == "historical_capture" and len(rows[capacities[0]]) == 425
                   and "formal-3458" in provenance.get("historical_run", ""))
    reference = read_reference(reference_path) if c12_capture else None
    if reference:
        lines.extend([
            "", "## Historical H20 reference (separate runs)", "",
            "| P KV GiB/rank | Historical query hit | Historical local compute source count | Historical removed hash entries |",
            "|---:|---:|---:|---:|",
        ])
        for item in reference["runs"]:
            lines.append(f"| {item['capacity_gib_per_rank']} | {item['query_hit_rate']:.2%} | "
                         f"{item['local_compute_tokens']:,.0f} | {item['removed_hash_entries']:,} |")
        lines.extend(["", "The historical local_compute is an input-source count; simulated cumulative "
                      "processing includes rescheduling. These runs had different external event histories."])
    else:
        lines.extend(["", "Historical H20 request-level comparison is unavailable for this workload. "
                      "No measured result is inferred for a new capacity."])
    if conditions[0].get("full_sequence_must_fit") is True:
        lines.extend([
            "", "Full-sequence admission is enabled in this scan. The installed target vLLM 0.26.0 SchedulerConfig defaults it to true, and the L3 historical diagnostic recorded it as true; L2's effective value was not retained. Earlier native scans with this setting false are separate controlled runs, not the target-profile result.",
        ])
    elif conditions[0].get("full_sequence_must_fit") is False:
        lines.extend([
            "", "Full-sequence admission is disabled in this scan. This differs from the installed target vLLM 0.26.0 default and the recorded L3 diagnostic; interpret it as a protocol variant, not the target-profile result.",
        ])
    else:
        lines.extend([
            "", "Full-sequence admission was not recorded in these conditions. Do not treat this scan as a verified target-profile run; use the corrected scan with an explicit setting for that comparison.",
        ])
    if c12_capture:
        lines.extend([
            "", "## Fixed-input H20 pair using the same C12 capture", "",
            "| Run | P KV GiB/rank | Query hit | Input cache fraction | Local compute | Removed hash entries |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        frozen_pair = reference["frozen_pair"]
        for item in frozen_pair:
            lines.append(
                f"| {item['label']} / {item['job']} | "
                f"{item['capacity_gib_per_rank']} | "
                f"{item['query_hit_rate']:.2%} | "
                f"{item['actual_input_cache_fraction']:.2%} | "
                f"{item['local_compute_tokens']:,} | "
                f"{item['removed_hash_entries']:,} |"
            )
        lines.extend([
            "", "F12/F24 reused the C12 captured P input, so content identity is comparable to this scan. Historical request interleaving, model processing and P reference-release timing were not replayed; aggregate differences remain evidence of those unmodeled execution conditions, not proof of a single cause.",
            "",
            "Simulation and historical local_compute use different definitions and execution histories; matched input content alone does not establish a matched cache result.",
        ])
    lines.extend(["", "## First request differences", ""])
    for pair, item in first.items():
        if item is None:
            lines.append(f"- {pair}: no adopted/processed difference in the aligned requests.")
        else:
            left = item["left"]
            right = item["right"]
            lines.append(
                f"- {pair}: request order {item['order']} ({item['request_id']}); "
                f"adopted {left['initial_adopted_tokens']:,} vs {right['initial_adopted_tokens']:,}; "
                f"processed {left['cumulative_input_processing_tokens']:,} vs "
                f"{right['cumulative_input_processing_tokens']:,}."
            )
    lines.extend([
        "", "## Interpretation limits", "",
        "The native Scheduler and cache manager made admission, prefix and reclaim decisions. The offline connector supplies transfer-complete notifications; no model, D-side compute or wall-clock timing was simulated. The five group specs, layer names and tensor strides come from the recorded H20 effective config; tensor sizes scale with physical block count. CPU-only execution does not allocate worker KV tensors, so scaled worker layouts are not independently verified.",
        "",
        "Historical L2/M/H query hits, local-compute counts and KVEvent removals are reference values only; they were not inputs to these runs. The historical request and P release event stream is incomplete, so differences from those values cannot be assigned one cause without further evidence.",
        "",
        "Run inside the pinned vLLM CPU runtime under the configured scheduler: `PYTHONHASHSEED=0 python -m kvsim.native.run <frozen-workload.json> <conditions.json> <new-output-dir>`. Use the conditions for the selected experiment, not a historical default; effective conditions and budgets are recorded in each manifest. See START_HERE for the packaged example and environment setup.",
    ])
    if c12_capture:
        lines.extend([
            "", "The P-side input arrays were captured during C12 run 3458 and mapped to all 425 requests by source key. Later F12/F24 runs 3462/3463 mark this input frozen and verified. The mapping and its limits are documented in `output/kvsim/native-stage-a/historical-capture-f12/CAPTURE_AUDIT.md`. This does not supply historical P scheduler batches or release times.",
        ])
    if identities[0]:
        lines.extend([
            "", "The manifests record vLLM " + identities[0]["vllm_version"] +
            " and the loaded native Scheduler/cache source file identities. "
            "The Scheduler, manager, coordinator and single-type manager match "
            "saved stage-v5/retry-1 source snapshots; BlockPool matches the "
            "stage-v4 source snapshot. This does not establish every historical "
            "worker patch or the actual 24/48 GiB tensor allocation.",
        ])
    if effective_profiles[0] is None:
        lines.extend([
            "", "These saved runs predate the effective-native-profile check. Their manifests preserve intended conditions and source identity, but do not prove the environment-derived retention rule actually in force. New runs reject a mismatch before request submission and record the effective profile.",
        ])
    running_peaks = {}
    running_before_peaks = {}
    overlap_steps = {}
    for gib in capacities:
        steps = load_jsonl(point_directory(root, gib) / "steps.jsonl")
        running_before_peaks[gib] = max((len(item["running_before"]) for item in steps), default=0)
        running_peaks[gib] = max((len(item["running_after_schedule"]) for item in steps), default=0)
        overlap_steps[gib] = sum(len(item["running_after_schedule"]) > 1 for item in steps)
    lines.extend([
        "", "Native running-set peaks after scheduling were " + ", ".join(
            f"{gib}: {running_peaks[gib]}" for gib in capacities
        ) + "; before scheduling, " + ", ".join(
            f"{gib}: {running_before_peaks[gib]}" for gib in capacities
        ) + ". Steps with two active P requests after scheduling: " + ", ".join(
            f"{gib}: {overlap_steps[gib]}" for gib in capacities
        ) + ". The per-request preemption count was " + str(sum(
            item["preemptions"] for gib in capacities for item in rows[gib]
        )) + f" across all {len(capacities)} runs. Same-batch overlap can be checked here; sustained overlap and successful preemption recovery are covered by separate directed mechanism evidence.",
    ])
    (root / "REPORT.md").write_text("\n".join(lines) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan_dir", type=Path)
    parser.add_argument("--historical-reference", type=Path)
    args = parser.parse_args()
    result = compare(args.scan_dir, args.historical_reference)
    print(json.dumps({"status": result["status"], "result_path": str((args.scan_dir / "comparison.json").resolve())}))
