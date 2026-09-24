"""Small native prefill overlap cases near the recoverable pool boundary."""

from __future__ import annotations

import json

from kvsim.native.mechanism_cases import trial


def main():
    results = []
    for blocks in (3460, 3470, 3480, 3490):
        item = trial(blocks, {"A": [11] * 30000,
                              "B": [12] * 30000}, False)
        results.append({key: item[key] for key in (
            "physical_blocks", "released", "waiting_steps", "peak_running",
            "preemptions", "min_free_blocks", "event_types",
            "all_references_released", "timeline",
        )})
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
