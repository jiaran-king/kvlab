"""Bounded artificial pool sweep to exercise native preemption if reachable."""

from __future__ import annotations

import json

from kvsim.native.mechanism_cases import trial


def main():
    results = []
    cases = [
        (3420, 30000), (3430, 30000), (3440, 30000),
        (3400, 10000), (3420, 10000), (3440, 10000),
    ]
    for blocks, b_tokens in cases:
        item = trial(blocks, {"A": [11] * 30000,
                              "B": [12] * b_tokens}, False)
        results.append({key: item[key] for key in (
            "physical_blocks", "released", "adopted_tokens", "waiting_steps",
            "peak_running", "preemptions", "min_free_blocks", "event_types",
            "all_references_released",
        )})
        results[-1]["B_input_tokens"] = b_tokens
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
