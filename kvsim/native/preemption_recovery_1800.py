"""One source-backed two-prefill recovery attempt at an 1,800-block pool.

Job 3817 measured 1,681 blocks held immediately after both 2,048-token
chunks and a later 1,933-block peak in the 4,000-block case. The 1,800-block
pool lies between those values, so both should admit before native pressure.
This is an artificial chunk-limit variant, never the historical main scan.
"""

from __future__ import annotations

import json

from kvsim.native.mechanism_cases import trial


def main() -> None:
    result = trial(
        1800, {"A": [11] * 30000, "B": [12] * 30000}, False,
        observe=False, chunk_limit=2048, max_steps=80,
        capture_admission=True,
    )
    preempted = {request_id for step in result["timeline"]
                 for request_id in step["preempted_req_ids"]}
    resumed = {request_id for step in result["timeline"]
               for request_id in step["resumed_req_ids"]}
    output = {key: result[key] for key in (
        "physical_blocks", "chunk_limit", "released", "peak_running",
        "preemptions", "processing_tokens", "all_references_released",
        "min_free_blocks", "waiting_steps", "admission_checks", "timeline",
    )}
    output["preempted_req_ids"] = sorted(preempted)
    output["resumed_req_ids"] = sorted(resumed)
    output["success"] = (
        bool(preempted & resumed)
        and set(result["released"]) == {"A", "B"}
        and result["all_references_released"]
    )
    print(json.dumps(output, ensure_ascii=False))
    if not output["success"]:
        raise SystemExit("1,800-block case did not complete preempt-then-recover")


if __name__ == "__main__":
    main()
