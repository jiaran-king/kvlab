"""One hypothesis-driven preemption case; artificial chunk cap, target H20 groups.

Two long P prefills share a 4,000-block pool. A 2,048-token per-request
chunk cap allows both to keep growing across steps; full-sequence admission
checks each request but does not reserve future slots. The combined future
demand exceeds the pool. This is a mechanism variant, not the H20 main scan.
"""

from __future__ import annotations

import json

from kvsim.native.mechanism_cases import trial


def main() -> None:
    result = trial(
        4000, {"A": [11] * 30000, "B": [12] * 30000}, False,
        observe=False, chunk_limit=2048, max_steps=80,
    )
    preempted = {request_id for step in result["timeline"]
                 for request_id in step["preempted_req_ids"]}
    resumed = {request_id for step in result["timeline"]
               for request_id in step["resumed_req_ids"]}
    report = {key: result[key] for key in (
        "physical_blocks", "chunk_limit", "released", "peak_running",
        "preemptions", "processing_tokens", "all_references_released",
        "min_free_blocks", "waiting_steps",
    )}
    report["preempted_req_ids"] = sorted(preempted)
    report["resumed_req_ids"] = sorted(resumed)
    report["timeline"] = result["timeline"]
    report["success"] = (
        bool(preempted & resumed)
        and set(result["released"]) == {"A", "B"}
        and result["all_references_released"]
    )
    print(json.dumps(report, ensure_ascii=False))
    if not report["success"]:
        raise SystemExit("directed case did not demonstrate completed preemption/recovery")


if __name__ == "__main__":
    main()
