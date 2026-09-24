#!/usr/bin/env python3
"""Record the failed 3473 run without treating its partial counters as a pair."""
import csv, json
from pathlib import Path

root = Path(__file__).resolve().parent
run = root / "formal-3473"
execution = json.loads((run / "replay" / "replay-execution.json").read_text())
nodes = [n for task in execution["tasks"] for n in task["nodes"]]
from collections import Counter
counts = Counter(n.get("status") for n in nodes)
failed = [n for n in nodes if n.get("status") != "success"]
event = json.loads((root / "F12B-event-summary.json").read_text())
cleanup = json.loads((run / "cleanup-audit.json").read_text())
rows = []
with (root / "failed-requests.csv").open("w", newline="") as f:
    fields = ["source_key", "runtime_request_id", "status", "error", "planned_input_tokens", "context_mode"]
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
    for n in failed:
        p = n.get("prompt_calibration") or {}
        w.writerow({"source_key": n.get("source_key"), "runtime_request_id": n.get("runtime_request_id"),
                    "status": n.get("status"), "error": n.get("error"),
                    "planned_input_tokens": p.get("target_tokens", "NA"), "context_mode": n.get("context_mode")})

with (root / "failure-summary.csv").open("w", newline="") as f:
    fields = ["run", "job", "planned_requests", "success", "failed", "skipped_dependency",
              "formal_event_stream_complete", "formal_removed_entries", "cleanup_passed",
              "source_identity_matches_F12A", "primary_failure", "coverage_note"]
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
    w.writerow({"run": "F12B-observer-3473", "job": 3473, "planned_requests": len(nodes),
                "success": counts.get("success", 0), "failed": counts.get("failed", 0),
                "skipped_dependency": counts.get("skipped_dependency_failed", 0),
                "formal_event_stream_complete": event["stream_complete"],
                "formal_removed_entries": event["total_removed_entries"],
                "cleanup_passed": cleanup["resource_cleanup_passed"],
                "source_identity_matches_F12A": False,
                "primary_failure": "r00000414: P HTTP ReadError; D Timeout waiting for P side ready; client ReadTimeout 900.079 s",
                "coverage_note": "423 successes + 1 failed + 1 dependency-skipped; no full paired performance point"})

report = root / "FAILURE-3473-REPORT.md"
report.write_text(f"""# F12B observer run 3473: failure record

This run is retained as diagnostic evidence. It is not a valid full F12-A/F12-B performance pair.

## Coverage

- Planned nodes: **{len(nodes)}**
- Successful: **{counts.get('success', 0)}**
- Failed: **{counts.get('failed', 0)}**
- Dependency-skipped: **{counts.get('skipped_dependency_failed', 0)}**
- Formal KVEvent stream: **complete**, with no gaps or errors.
- Formal `BlockRemoved` entries: **{event['total_removed_entries']}**; these are removal hash entries, not confirmed capacity evictions.
- Cleanup: **passed**.

The failed request is listed in `failed-requests.csv`. It is `r00000414-1935038c86d0de74`, with a 35,165-token planned input. The next dependent request `r00000415-f0883211322d2577` was skipped.

## Failure chain

The proxy recorded a P-side `ReadError` immediately after the request was sent. D received response headers, then both P and D logged `Timeout waiting for P side ready`. The replay client recorded a 900.079-second `ReadTimeout`.

The same source request succeeded in F12-A with 34,560 adopted local-cache tokens and 0.514 s send-to-first-token time. That makes this a useful protocol-failure sample, but the 3473 run used an extra query-batch flush in its diagnostic hook; its source identity therefore differs from F12-A. It cannot isolate server nondeterminism from observer-induced timing.

The corrected run uses the byte-identical F12-A observation and replay implementation. Its result will determine whether the failure recurs under a valid same-capacity protocol.
""")
print(json.dumps({"nodes": len(nodes), "counts": counts, "report": str(report)}))
