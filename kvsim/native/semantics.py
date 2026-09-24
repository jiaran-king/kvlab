"""Execution semantics used by both scan and cross-scenario comparisons."""


def execution_conditions(manifest: dict) -> dict:
    result = {key: value for key, value in manifest["conditions"].items()
            if key not in {"capacities_gib", "capacity_points", "routing_trace",
                           "scenario_id", "scenario", "event_limit", "event_windows",
                           "max_steps", "routing"}}
    topology = (manifest.get("scenario") or {}).get("topology")
    if topology is not None:
        result["declared_topology"] = topology
    return result


def source_identity(manifest: dict):
    identity = manifest.get("native_source_identity")
    if not identity:
        return identity
    return {**identity, "classes": {
        name: {key: value for key, value in entry.items()
               if key != "path" or not entry.get("sha256")}
        for name, entry in identity.get("classes", {}).items()
    }}


def route_identity(manifest: dict, rows: list[dict]):
    if rows and all(row.get("p_domain") is not None for row in rows):
        return [(row["request_id"], row["p_domain"]) for row in rows]
    route = manifest.get("routing") or {}
    return {key: route.get(key) for key in ("routing_sha256", "method", "domains")}


def validate_mechanism_pair(left: dict, right: dict) -> None:
    """Scheduling knobs may change; the native cache mechanism may not."""
    if not source_identity(left) or source_identity(left) != source_identity(right):
        raise ValueError("non-capacity execution differences: native source identity")
    fixed = []
    knobs = {"max_num_seqs": "p_max_num_seqs",
             "max_num_batched_tokens": "p_max_num_batched_tokens"}
    for manifest in (left, right):
        profile = manifest.get("effective_native_profile")
        if not profile:
            raise ValueError("effective native profile is required for a checked comparison")
        for native, declared in knobs.items():
            if profile.get(native) != manifest["conditions"].get(declared):
                raise ValueError(f"effective {native} differs from declared {declared}")
        for domain_profile in (manifest.get("effective_native_profile_by_p") or {}).values():
            if domain_profile != profile:
                raise ValueError("effective native profiles differ across P domains")
        fixed.append({k: v for k, v in profile.items() if k not in knobs})
    if fixed[0] != fixed[1]:
        raise ValueError("non-capacity execution differences: fixed native cache rules")
    if left.get("input_accounting") != right.get("input_accounting"):
        raise ValueError("input accounting protocols differ; rerun with the same counter")
