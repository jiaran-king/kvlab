"""Compare two native points under an explicit, checked interpretation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvsim.native.result_validation import validate_capacity, load_jsonl
from kvsim.native.activity import activity_by_p
from kvsim.native.semantics import execution_conditions, source_identity, route_identity, validate_mechanism_pair


MODES = {"capacity-only", "single-variable", "deployment-conditional"}
VARIABLES = {"client_max_in_flight", "p_max_num_seqs", "p_max_num_batched_tokens", "routing"}


def _read(directory: Path) -> tuple[dict, dict, list[dict]]:
    summary, rows = validate_capacity(directory)
    if summary.get("per_p"):
        activity = activity_by_p(rows, load_jsonl(directory / "steps.jsonl"), list(summary["per_p"]))
        for domain, metrics in activity.items():
            summary["per_p"][domain].update(metrics)
    manifest = json.loads((directory / "manifest.json").read_text())
    if summary["status"] != "complete":
        raise ValueError(f"{directory}: only completed points can form a numerical contrast")
    return summary, manifest, rows


def contrast(baseline: Path, variant: Path, output: Path | None,
             mode: str, variable: str | None = None) -> dict:
    if mode not in MODES:
        raise ValueError("unsupported contrast mode")
    if (mode == "single-variable") != (variable is not None):
        raise ValueError("single-variable contrast requires exactly one declared variable")
    if variable is not None and variable not in VARIABLES:
        raise ValueError("unsupported single-variable contrast field")
    left, left_manifest, left_rows = _read(baseline)
    right, right_manifest, right_rows = _read(variant)
    validate_mechanism_pair(left_manifest, right_manifest)
    left_sha = left_manifest.get("workload_sha256")
    right_sha = right_manifest.get("workload_sha256")
    if not left_sha or left_sha != right_sha:
        raise ValueError("contrast needs identical frozen workload SHA256")
    if left_manifest.get("workload_content_source") != right_manifest.get("workload_content_source"):
        raise ValueError("contrast workload content sources differ")
    if [(r["request_id"], r["input_tokens"]) for r in left_rows] != [
        (r["request_id"], r["input_tokens"]) for r in right_rows
    ]:
        raise ValueError("contrast requests or input lengths differ")
    left_digests = [row.get("input_sha256") for row in left_rows]
    right_digests = [row.get("input_sha256") for row in right_rows]
    if all(left_digests) and all(right_digests) and left_digests != right_digests:
        raise ValueError("contrast request input digests differ")
    left_core = execution_conditions(left_manifest)
    right_core = execution_conditions(right_manifest)
    left_route = left_manifest.get("routing") or {}
    right_route = right_manifest.get("routing") or {}
    same_route = route_identity(left_manifest, left_rows) == route_identity(right_manifest, right_rows)
    same_native = source_identity(left_manifest) == source_identity(right_manifest)
    same_effective = left_manifest.get("effective_native_profile") == right_manifest.get("effective_native_profile")
    if left_manifest.get("input_accounting") != right_manifest.get("input_accounting"):
        raise ValueError("contrast input accounting protocols differ; rerun with the same corrected counter")
    same_capacity = left["physical_blocks"] == right["physical_blocks"]
    if mode == "capacity-only":
        if left_core != right_core or not same_route or not same_native or not same_effective:
            raise ValueError("capacity-only contrast has non-capacity execution differences")
    elif mode == "single-variable":
        if not same_capacity or not same_native:
            raise ValueError("single-variable contrast requires one target and KV budget")
        if variable == "routing":
            if left_core != right_core or same_route or not same_effective:
                raise ValueError("routing contrast requires only frozen placement to change")
        else:
            a, b = dict(left_core), dict(right_core)
            left_value, right_value = a.pop(variable, None), b.pop(variable, None)
            if a != b or not same_route or left_value == right_value:
                raise ValueError(f"{variable} contrast changes another execution condition")
            profile_a = dict(left_manifest.get("effective_native_profile") or {})
            profile_b = dict(right_manifest.get("effective_native_profile") or {})
            native_field = {"p_max_num_seqs": "max_num_seqs",
                            "p_max_num_batched_tokens": "max_num_batched_tokens"}.get(variable)
            if native_field:
                profile_a.pop(native_field, None)
                profile_b.pop(native_field, None)
            if profile_a != profile_b:
                raise ValueError("single-variable contrast changes another effective native rule")
    elif mode == "deployment-conditional":
        supported = {"p_domains", "declared_topology", "client_max_in_flight",
                     "p_max_num_seqs", "p_max_num_batched_tokens"}
        changed = {key for key in set(left_core) | set(right_core)
                   if left_core.get(key) != right_core.get(key)}
        if changed - supported:
            raise ValueError(f"unsupported deployment execution differences: {sorted(changed - supported)}")
    changes = {}
    for key in sorted(set(left_core) | set(right_core)):
        if left_core.get(key) != right_core.get(key):
            changes[key] = [left_core.get(key), right_core.get(key)]
    if not same_route:
        changes["routing"] = [left_route.get("routing_sha256"), right_route.get("routing_sha256")]
    if not same_capacity:
        changes["physical_blocks_per_p"] = [left["physical_blocks"], right["physical_blocks"]]
    left_scenario = left_manifest.get("scenario") or {}
    right_scenario = right_manifest.get("scenario") or {}
    if left_scenario.get("topology") != right_scenario.get("topology"):
        changes["topology"] = [left_scenario.get("topology"), right_scenario.get("topology")]
    baseline_processed = left["cumulative_input_processing_tokens"]
    variant_processed = right["cumulative_input_processing_tokens"]
    delta = baseline_processed - variant_processed
    request_changes = []
    for a, b in zip(left_rows, right_rows):
        if (a["initial_adopted_tokens"] != b["initial_adopted_tokens"]
            or a["cumulative_input_processing_tokens"] != b["cumulative_input_processing_tokens"]
            or a.get("p_domain", "p0") != b.get("p_domain", "p0")):
            request_changes.append({
                "order": a["order"], "request_id": a["request_id"],
                "baseline_p": a.get("p_domain", "p0"), "variant_p": b.get("p_domain", "p0"),
                "baseline_adopted": a["initial_adopted_tokens"],
                "variant_adopted": b["initial_adopted_tokens"],
                "baseline_processed": a["cumulative_input_processing_tokens"],
                "variant_processed": b["cumulative_input_processing_tokens"],
            })
    def evidence(summary, manifest):
        return {
            "scenario_id": manifest.get("scenario_id", "legacy-unspecified"),
            "run_id": manifest.get("run_id", "legacy-unspecified"),
            "budget_source": (summary.get("budget_provenance") or {}).get("source", "unknown"),
            "routing_source": (manifest.get("routing") or {}).get("source", "unknown"),
            "target_profile": manifest["conditions"].get("profile"),
            "target_source_identified": bool(manifest.get("native_source_identity")),
            "topology": (manifest.get("scenario") or {}).get("topology"),
        }
    result = {
        "schema": "kvlab-native-contrast/v1", "mode": mode,
        "variable": variable, "status": "complete", "changed_conditions": changes,
        "effective_capacity_changed": not same_capacity,
        "capacity_interpretation": ("effective capacity unchanged; equivalence comparison"
                                    if same_capacity else "effective capacity differs"),
        "workload_sha256": left_sha,
        "baseline": {"path": str(baseline), "summary": left, "evidence": evidence(left, left_manifest)},
        "variant": {"path": str(variant), "summary": right, "evidence": evidence(right, right_manifest)},
        "delta_processed_tokens": delta,
        "relative_processed_reduction": delta / baseline_processed if baseline_processed else None,
        "request_changes": request_changes,
        "per_p": {"baseline": left.get("per_p"), "variant": right.get("per_p")},
        "real_deployment_conclusion_supported": False,
        "evidence_gaps": [
            "Target AFD and non-AFD effective P KV ledgers have not been verified together",
            "Dynamic routing and wall-clock feedback are not replayed",
            "Comparable target deployment cache baseline is not validated",
        ],
        "interpretation": ("Logical input token processing under each declared scenario; "
                           "a deployment-conditional difference combines capacity, topology, routing and scheduling effects. "
                           "It is not TTFT, throughput, FLOPs or a measured AFD benefit."),
    }
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        (output / "contrast.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("variant", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=sorted(MODES), required=True)
    parser.add_argument("--variable", choices=sorted(VARIABLES))
    args = parser.parse_args()
    result = contrast(args.baseline, args.variant, args.output, args.mode, args.variable)
    print(json.dumps({"status": result["status"], "result_path": str((args.output / "contrast.json").resolve())}))
