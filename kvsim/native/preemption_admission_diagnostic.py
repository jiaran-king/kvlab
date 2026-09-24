"""Measure the native full-sequence admission requirement in the 3805 case.

One read-only wrapper records the coordinator's existing estimate. The same
case is run unobserved to check that collecting it changed no decisions.
"""

from __future__ import annotations

import json

from kvsim.native.mechanism_cases import trial


def main() -> None:
    inputs = {"A": [11] * 30000, "B": [12] * 30000}
    args = (4000, inputs, False)
    plain = trial(*args, observe=False, chunk_limit=2048, max_steps=80)
    measured = trial(
        *args, observe=False, chunk_limit=2048, max_steps=80,
        capture_admission=True,
    )
    keys = (
        "released", "adopted_tokens", "waiting_steps", "peak_running",
        "preemptions", "processing_tokens", "min_free_blocks",
        "all_references_released", "timeline",
    )
    unchanged = all(plain[key] == measured[key] for key in keys)
    first_b = next(
        (item for item in measured["admission_checks"]
         if item["request_id"] == "B"), None
    )
    output = {
        "observer_decisions_unchanged": unchanged,
        "admission_checks": measured["admission_checks"],
        "first_b_check": first_b,
        "first_b_pool_lower_bound_at_same_step": (
            4000 - first_b["free_blocks_before"] + first_b["required_blocks"]
            if first_b else None
        ),
        "peak_nonfree_blocks_in_4000_case": 4000 - measured["min_free_blocks"],
        "released": measured["released"],
        "preemptions": measured["preemptions"],
    }
    print(json.dumps(output, ensure_ascii=False))
    if not unchanged or first_b is None:
        raise SystemExit("admission observation failed its validity check")


if __name__ == "__main__":
    main()
