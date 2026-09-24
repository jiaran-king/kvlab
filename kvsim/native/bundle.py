"""Pack native scan results, including incomplete points, for KVLab."""

from __future__ import annotations

import json
import argparse
from pathlib import Path

from kvsim.native.compare import scan_capacities, read_reference, comparison_pairs
from kvsim.native.result_validation import load_jsonl, validate_capacity, validate_scan_binding
from kvsim.native.activity import activity_by_p
from kvsim.native.capacity import point_directory
from kvsim.native.contrast import contrast as checked_contrast


def build_bundle(root: Path, output: Path,
                 title: str = "Native vLLM controlled capacity scan",
                 reference_path: Path | None = None,
                 contrast_path: Path | None = None,
                 contrast_variant_run: Path | None = None) -> dict:
    comparison = json.loads((root / "comparison.json").read_text())
    selected_contrast = contrast_path or root / "contrast.json"
    if contrast_path is not None and not selected_contrast.exists():
        raise ValueError(f"requested contrast does not exist: {selected_contrast}")
    contrast = json.loads(selected_contrast.read_text()) if selected_contrast.exists() else None
    if contrast is not None and contrast.get("schema") != "kvlab-native-contrast/v1":
        raise ValueError("unsupported native contrast schema")
    evidence_path = root / "first-difference-evidence.json"
    evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else {"findings": {}}
    capacities = scan_capacities(root)
    runs = {}
    for gib in capacities:
        directory = point_directory(root, gib)
        summary, requests = validate_capacity(directory)
        if comparison.get("summaries", {}).get(str(gib)) != summary:
            raise ValueError("comparison summary differs from bundled run; regenerate comparison")
        steps = load_jsonl(directory / "steps.jsonl")
        if summary.get("per_p"):
            activity = activity_by_p(requests, steps, list(summary["per_p"]))
            for domain, metrics in activity.items():
                summary["per_p"][domain].update(metrics)
            summary["waiting_request_steps"] = sum(x["waiting_request_steps"] for x in activity.values())
            summary["preemptions"] = sum(x["preemptions"] for x in activity.values())
            summary["resumes"] = sum(x["resumes"] for x in activity.values())
        runs[str(gib)] = {
            "summary": summary,
            "manifest": json.loads((directory / "manifest.json").read_text()),
            "requests": requests,
            "steps": steps,
            "events": load_jsonl(directory / "events.jsonl"),
        }
    first_manifest = runs[str(capacities[0])]["manifest"]
    manifests = {point: run["manifest"] for point, run in runs.items()}
    validate_scan_binding(comparison, manifests, "comparison")
    complete = tuple(point for point in capacities if runs[str(point)]["summary"]["status"] == "complete")
    if comparison.get("status") != ("complete" if len(complete) == len(capacities) else "incomplete"):
        raise ValueError("comparison status differs from bundled runs")
    pairs = {f"{a}_vs_{b}": (str(a), str(b)) for a, b in comparison_pairs(complete)}
    differences = comparison.get("first_request_difference") or {}
    if set(differences) != set(pairs):
        raise ValueError("comparison pairs differ from bundled complete runs")
    for pair, (left, right) in pairs.items():
        actual = next(((a, b) for a, b in zip(runs[left]["requests"], runs[right]["requests"])
                       if a["initial_adopted_tokens"] != b["initial_adopted_tokens"]
                       or a["cumulative_input_processing_tokens"] != b["cumulative_input_processing_tokens"]), None)
        expected = ({"order": actual[0]["order"], "request_id": actual[0]["request_id"],
                     "left": actual[0], "right": actual[1]} if actual else None)
        if differences[pair] != expected:
            raise ValueError("comparison first difference does not belong to bundled runs")
    if evidence_path.exists():
        validate_scan_binding(evidence, manifests, "evidence")
        if set(evidence.get("findings", {})) != set(pairs):
            raise ValueError("evidence comparison pairs differ")
        for pair, finding in evidence["findings"].items():
            difference = differences[pair]
            if finding is None:
                if difference is not None:
                    raise ValueError("evidence omits the selected request difference")
                continue
            if difference is None or finding.get("request_id") != difference["request_id"]:
                raise ValueError("evidence request differs from comparison")
            for side, point in zip(("left", "right"), pairs[pair]):
                row = difference[side]
                if (finding.get("input_sha256") != row.get("input_sha256")
                    or not row.get("input_sha256")
                    or finding[side].get("run_id") != manifests[point]["run_id"]
                    or str(finding.get(f"{side}_point_id")) != point
                    or str(finding[side].get("point_id")) != point
                    or finding[side].get("p_domain") != row.get("p_domain", "p0")
                    or finding[side].get("admission_step") != row["first_scheduled_step"]):
                    raise ValueError("evidence run/P/request input binding differs")
    if contrast is not None and contrast.get("workload_sha256") != first_manifest.get("workload_sha256"):
        raise ValueError("contrast workload SHA256 differs from bundled scan")
    variant_run = None
    if contrast_variant_run is not None:
        if contrast is None:
            raise ValueError("variant run requires a contrast")
        variant_summary, variant_requests = validate_capacity(contrast_variant_run)
        variant_manifest = json.loads((contrast_variant_run / "manifest.json").read_text())
        if variant_summary["status"] != "complete" or variant_manifest.get("workload_sha256") != first_manifest.get("workload_sha256"):
            raise ValueError("contrast variant must be complete and use the bundled workload")
        if variant_manifest.get("run_id") != contrast["variant"]["evidence"]["run_id"]:
            raise ValueError("contrast variant run ID differs from comparison")
        variant_run = {
            "summary": variant_summary, "manifest": variant_manifest,
            "requests": variant_requests,
            "steps": load_jsonl(contrast_variant_run / "steps.jsonl"),
            "events": load_jsonl(contrast_variant_run / "events.jsonl"),
        }
    if contrast is not None:
        available = list(runs.values()) + ([variant_run] if variant_run else [])
        directories = {run["manifest"].get("run_id"): point_directory(root, point)
                       for point, run in ((point, runs[str(point)]) for point in capacities)}
        if variant_run:
            directories[variant_run["manifest"].get("run_id")] = contrast_variant_run
        for side in ("baseline", "variant"):
            identity = contrast[side]["evidence"].get("run_id")
            if not identity or identity == "legacy-unspecified":
                raise ValueError(f"contrast {side} lacks sufficient run identity")
            matching = [run for run in available if run["manifest"].get("run_id") == identity]
            if not matching or (side == "baseline" and not any(
                run["manifest"].get("run_id") == identity for run in runs.values()
            )):
                raise ValueError(f"contrast {side} run is not present in the bundle")
            actual = matching[0]
            if actual["summary"]["status"] != "complete":
                raise ValueError(f"contrast {side} is not complete")
            # Derived activity fields can be added to old summaries; core counts
            # and run identity must still be those of the actual attached run.
            for field in ("run_id", "physical_blocks", "requests_planned", "requests_completed",
                          "actual_input_tokens", "initial_adopted_cache_tokens",
                          "cumulative_input_processing_tokens", "prefix_hits", "prefix_queries"):
                if contrast[side]["summary"].get(field) != actual["summary"].get(field):
                    raise ValueError(f"contrast {side} summary differs from attached run: {field}")
        recalculated = checked_contrast(
            directories[contrast["baseline"]["evidence"]["run_id"]],
            directories[contrast["variant"]["evidence"]["run_id"]],
            None, contrast["mode"], contrast.get("variable"),
        )
        for field in ("changed_conditions", "delta_processed_tokens", "relative_processed_reduction",
                      "request_changes", "per_p"):
            if contrast.get(field) != recalculated[field]:
                raise ValueError(f"contrast {field} differs from attached runs; regenerate contrast")
    provenance = first_manifest.get("workload_capture_provenance") or {}
    c12_capture = (first_manifest.get("workload_content_source") == "historical_capture"
                   and len(runs[str(capacities[0])]["requests"]) == 425
                   and "formal-3458" in provenance.get("historical_run", ""))
    reference = read_reference(reference_path) if c12_capture else None
    bundle = {
        "schema": "kvlab-native-results/v1",
        "title": title,
        "point_ids": list(capacities),
        **({"capacities_gib": list(capacities)} if all(type(x) is int for x in capacities) else {}),
        "status": comparison.get("status", "complete"),
        "comparison": comparison.get("first_request_difference") or {},
        "contrast": contrast,
        "contrast_variant": variant_run,
        "evidence": evidence,
        "historical_reference": reference["runs"] if reference else [],
        "historical_frozen_pair": reference["frozen_pair"] if reference else [],
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")))
    return bundle


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan_dir", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--title", default="Native vLLM controlled capacity scan")
    parser.add_argument("--historical-reference", type=Path)
    parser.add_argument("--contrast", type=Path)
    parser.add_argument("--contrast-variant-run", type=Path)
    args = parser.parse_args()
    result = build_bundle(args.scan_dir, args.output_json, title=args.title,
                 reference_path=args.historical_reference,
                 contrast_path=args.contrast,
                 contrast_variant_run=args.contrast_variant_run)

    print(json.dumps({"status": result["status"], "result_path": str(args.output_json.resolve())}))
