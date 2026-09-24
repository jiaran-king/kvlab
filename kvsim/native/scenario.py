"""Describe budget and deployment provenance without changing the cache backend."""

from __future__ import annotations


SCHEMA = "kvlab-native-scenario/v1"
SOURCES = {"measured", "derived", "assumed"}
AUTHORITIES = {"bytes_per_rank", "physical_blocks"}


def validate_scenario(conditions: dict, resolved_budgets: dict[int, dict]) -> dict:
    source = conditions.get("scenario")
    if source is None:
        return {
            "schema": SCHEMA,
            "scenario_id": conditions.get("scenario_id", "h20-controlled"),
            "target_profile": conditions["profile"],
            "p_domains": conditions["p_domains"],
            "topology": None,
            "budgets": {str(gib): {
                "source": "assumed", "authority": resolved_budgets[gib]["authority"],
                "value": resolved_budgets[gib]["authoritative_value"],
                "evidence": None, "assumptions": "User-selected KV budget; no AFD memory ledger supplied",
            } for gib in resolved_budgets},
        }
    if not isinstance(source, dict) or set(source) != {
        "schema", "scenario_id", "target_profile", "p_domains", "topology", "budgets"
    }:
        raise ValueError("scenario must declare schema, identity, target, topology and budgets")
    if source["schema"] != SCHEMA or source["scenario_id"] != conditions.get("scenario_id"):
        raise ValueError("scenario schema or scenario_id disagrees with conditions")
    if source["target_profile"] != conditions["profile"] or source["p_domains"] != conditions["p_domains"]:
        raise ValueError("scenario target profile or P count disagrees with conditions")
    topology = source["topology"]
    if not isinstance(topology, dict) or set(topology) != {
        "p", "attention", "ffn", "d", "tp", "dp", "ep"
    }:
        raise ValueError("scenario topology must describe P, Attention, FFN, D, TP, DP and EP")
    if type(topology["tp"]) is not int or topology["tp"] != 2:
        raise ValueError("current H20 target requires TP2")
    for name in ("p", "attention", "ffn", "d", "dp", "ep"):
        value = topology[name]
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"scenario topology {name} must be nonnegative or unknown")
    if topology["p"] != conditions["p_domains"]:
        raise ValueError("scenario P allocation disagrees with p_domains")
    budgets = source["budgets"]
    if not isinstance(budgets, dict) or set(budgets) != {str(gib) for gib in resolved_budgets}:
        raise ValueError("scenario must describe each selected capacity exactly once")
    for gib, resolved in resolved_budgets.items():
        entry = budgets[str(gib)]
        if not isinstance(entry, dict) or set(entry) != {
            "source", "authority", "value", "evidence", "assumptions"
        }:
            raise ValueError(f"scenario budget {gib} has unsupported or missing fields")
        if entry["source"] not in SOURCES or entry["authority"] not in AUTHORITIES:
            raise ValueError(f"scenario budget {gib} has unsupported source or authority")
        expected = {
            "bytes_per_rank": resolved["budget_bytes_per_rank"],
            "physical_blocks": resolved["physical_blocks"],
        }[entry["authority"]]
        if type(entry["value"]) is not int or entry["value"] != expected:
            raise ValueError(f"scenario budget {gib} disagrees with actual resolved capacity")
        if entry["source"] in {"measured", "derived"} and not entry["evidence"]:
            raise ValueError(f"scenario budget {gib} needs traceable evidence")
        if entry["source"] == "derived" and not entry["assumptions"]:
            raise ValueError(f"derived budget {gib} needs assumptions")
    return source
