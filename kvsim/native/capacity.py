"""H20-profile KV budget conversion and ordered capacity selection."""

from __future__ import annotations

import json
import re
from pathlib import Path


GIB = 1024 ** 3
# The current CPU target is the historical H20 layout, with evidence at
# 12/24/48 GiB. Bound scans to that budget range until another layout is
# checked; points inside it are selected by input, not by a case list.
MAX_POINTS = 8


def target_layout() -> dict:
    layout = json.loads(Path(__file__).with_name("h20-layout.json").read_text())
    if layout.get("schema") != "kvlab-native-h20-layout/v1":
        raise ValueError("unsupported H20 layout")
    return layout


def capacities_from_conditions(conditions: dict) -> tuple[int, ...]:
    values = conditions.get("capacities_gib")
    if not isinstance(values, list) or not values:
        raise ValueError("capacities_gib must be a nonempty list of integer GiB budgets")
    if len(values) > MAX_POINTS:
        raise ValueError(f"scan supports at most {MAX_POINTS} capacity points")
    maximum = target_layout()["max_budget_gib_per_rank"]
    if any(type(value) is not int or not 1 <= value <= maximum for value in values):
        raise ValueError(f"capacity must be an integer from 1 to {maximum} GiB per P rank")
    if len(values) != len(set(values)):
        raise ValueError("duplicate capacity in capacities_gib")
    if values != sorted(values):
        raise ValueError("capacities_gib must be in ascending order")
    return tuple(values)


def capacity_layout(gib: int) -> dict:
    layout = target_layout()
    maximum = layout["max_budget_gib_per_rank"]
    if type(gib) is not int or not 1 <= gib <= maximum:
        raise ValueError(f"capacity must be an integer from 1 to {maximum} GiB per P rank")
    return resolve_budget({"authority": "bytes_per_rank", "bytes_per_rank": gib * GIB})


def resolve_budget(point: dict) -> dict:
    """Resolve a budget against the pinned shared-stride physical pool layout.

    Physical blocks include the null block. Bytes absent from a blocks-authority
    input remain unknown; allocated layout bytes are a separate derived value.
    """
    layout = target_layout()
    authority = point.get("authority")
    if authority not in {"bytes_per_rank", "physical_blocks"}:
        raise ValueError("budget authority must be bytes_per_rank or physical_blocks")
    if authority not in point:
        raise ValueError(f"budget requires authoritative {authority}")
    for field in ("bytes_per_rank", "physical_blocks"):
        if field in point and (type(point[field]) is not int or point[field] <= 0):
            raise ValueError(f"{field} must be a positive integer")
    strides = {item["block_stride"] for item in layout["kv_cache_tensors"]}
    if len(strides) != 1:
        raise ValueError("H20 profile does not have one verified per-rank block stride")
    stride = strides.pop()
    if type(stride) is not int or stride <= 0:
        raise ValueError("invalid H20 block stride")
    if 12 * GIB // stride != layout["reference_num_blocks"]:
        raise ValueError("H20 reference budget disagrees with captured block count")
    budget = point.get("bytes_per_rank")
    blocks = point.get("physical_blocks")
    if budget is not None:
        resolved = budget // stride
        if blocks is not None and blocks != resolved:
            raise ValueError("bytes_per_rank and physical_blocks disagree after native floor conversion")
        blocks = resolved
    maximum = layout["max_budget_gib_per_rank"] * GIB
    if (budget is not None and budget > maximum) or blocks > maximum // stride:
        raise ValueError("budget exceeds the supported per-rank resource limit")
    if blocks < 2:
        raise ValueError("capacity cannot hold the H20 null block and a data block")
    return {
        "authority": authority,
        "authoritative_value": point[authority],
        "budget_gib_per_rank": budget / GIB if budget is not None else None,
        "budget_bytes_per_rank": budget,
        "bytes_per_physical_block_per_rank": stride,
        "physical_blocks": blocks,
        "effective_kv_bytes_per_rank": blocks * stride,
        "unused_budget_bytes_per_rank": budget % stride if budget is not None else None,
        "reserved_null_blocks": 1,
        "rounding": ("floor(budget_bytes_per_rank / bytes_per_physical_block_per_rank)"
                     if budget is not None else "physical pool block count supplied directly"),
        "layout_id": layout["profile"],
        "layout_source": layout["source"],
    }


def budgets_from_conditions(conditions: dict) -> dict:
    """Keep legacy GiB keys; exact points have explicit stable string IDs."""
    if "capacity_points" not in conditions:
        return {gib: capacity_layout(gib) for gib in capacities_from_conditions(conditions)}
    if "capacities_gib" in conditions:
        raise ValueError("choose capacity_points or capacities_gib, not both")
    points = conditions["capacity_points"]
    if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS:
        raise ValueError(f"capacity_points requires 1 to {MAX_POINTS} points")
    resolved = {}
    for point in points:
        if not isinstance(point, dict) or set(point) - {
            "id", "authority", "bytes_per_rank", "physical_blocks"
        }:
            raise ValueError("unsupported capacity point fields")
        key = point.get("id")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", key):
            raise ValueError("capacity point id must start with a letter and use letters, digits, _ or -")
        if key in resolved:
            raise ValueError("duplicate capacity point id")
        resolved[key] = resolve_budget(point)
    return resolved


def point_directory(root: Path, point: int | str) -> Path:
    return root / (f"{point}gib" if type(point) is int else point)
