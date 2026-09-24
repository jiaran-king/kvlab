"""Bounded two-request native preemption/recovery sweep with shorter prefills.

The main 425-request scan is unchanged. These artificial pool sizes test
whether two individually feasible 10k-token requests can overlap, preempt,
and subsequently both release their references.
"""

from __future__ import annotations

import json

from kvsim.native.mechanism_cases import trial


def main() -> None:
    results = []
    for blocks, tokens in ((3500, 12000), (3500, 16000),
                           (3550, 16000), (3600, 20000),
                           (3650, 20000)):
        item = trial(blocks, {"A": [11] * tokens,
                              "B": [12] * tokens}, False)
        result = {key: item[key] for key in (
            "physical_blocks", "released", "waiting_steps", "peak_running",
            "preemptions", "min_free_blocks", "event_types",
            "all_references_released",
        )}
        result["tokens_per_request"] = tokens
        results.append(result)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
