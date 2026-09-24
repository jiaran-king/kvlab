# F12B observer run 3473: failure record

This run is retained as diagnostic evidence. It is not a valid full F12-A/F12-B performance pair.

## Coverage

- Planned nodes: **425**
- Successful: **423**
- Failed: **1**
- Dependency-skipped: **1**
- Formal KVEvent stream: **complete**, with no gaps or errors.
- Formal `BlockRemoved` entries: **288314**; these are removal hash entries, not confirmed capacity evictions.
- Cleanup: **passed**.

The failed request is listed in `failed-requests.csv`. It is `r00000414-1935038c86d0de74`, with a 35,165-token planned input. The next dependent request `r00000415-f0883211322d2577` was skipped.

## Failure chain

The proxy recorded a P-side `ReadError` immediately after the request was sent. D received response headers, then both P and D logged `Timeout waiting for P side ready`. The replay client recorded a 900.079-second `ReadTimeout`.

The same source request succeeded in F12-A with 34,560 adopted local-cache tokens and 0.514 s send-to-first-token time. That makes this a useful protocol-failure sample, but the 3473 run used an extra query-batch flush in its diagnostic hook; its source identity therefore differs from F12-A. It cannot isolate server nondeterminism from observer-induced timing.

The corrected run uses the byte-identical F12-A observation and replay implementation. Its result will determine whether the failure recurs under a valid same-capacity protocol.

## Partial performance metrics

The formal-window counters for the 423 successful requests were: 13,637,190 input tokens, 10,289,152 adopted local-cache tokens (75.45% of the successful-subset input), 14,504,083 queried tokens and 10,289,408 hit tokens (70.94% query hit rate), and 3,348,038 local-compute tokens. The recorded P prefill mean was 1.617 s; continuation TTFT P50/P95 were approximately 0.733/10.885 s; request E2E P50/P95 were approximately 11.741/65.738 s.

These figures describe the successful subset and the formal counter window only. They are not a complete 425-request performance point and must not be compared as if the failed request had a normal latency or cache value.
