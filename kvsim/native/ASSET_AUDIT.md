# H20 native simulator: stage A asset audit

The executable audit is `python3 -m kvsim.native.audit_assets`. It reads the
local historical artifacts without changing them.

| Historical run | P KV GiB per TP rank | Physical blocks | P query / hit tokens | Historical local compute | KVEvent removed hash entries |
|---|---:|---:|---:|---:|---:|
| L2 / 3430 | 12 | 12,393 | 15,666,148 / 6,605,312 | 7,102,684 | 623,629 |
| M / 3429 | 24 | 24,786 | 13,707,996 / 12,449,536 | 1,258,460 | 86,238 |
| H / 3425 | 48 | 49,572 | 13,707,996 / 12,630,784 | 1,077,212 | 44,984 |

All three P launch commands specify TP2, `max_num_seqs=2`,
`max_num_batched_tokens=8192`, FP8 KV, prefix caching, and their listed
per-rank byte budgets. The replay config specifies client concurrency 3.
Each run has 425 request records. These are three separate historical runs;
the 12 GiB L3 run is a fourth observation and must remain distinct.
The three request files each sum to 13,707,996 actual input tokens. L2's
runtime query-hit rate is 42.16%, while its actual-input cache fraction is
48.19%, because its query denominator is larger than actual input. The
audit computes and names both metrics separately.

The observed cache groups have block sizes 256, 64, 64, 4, and 8. Group 0 is
MLA; groups 1–4 are sliding-window MLA. Their window sizes are 128, 128, 8,
and 128 respectively. The launch argument `--block-size 256` is therefore
not a description of every physical cache group. The event summary counts
removed hash entries, not physical blocks or capacity evictions.

The later C12 `effective_cache_config` diagnostic also preserves all five
group layer-name lists, complete spec fields, and 63 tensor offsets/strides.
That record is extracted to `kvsim/native/h20-layout.json`. The final CPU
driver reconstructs the recorded specs and scales tensor sizes by each
capacity's physical block count. This is a worker-layout description used by
the native Scheduler; the CPU simulator does not allocate the worker tensors.

The installed vLLM 0.26.0 `SchedulerConfig.scheduler_reserve_full_isl`
default is `True`, and the L3 diagnostic recorded effective
`full_sequence_must_fit=true`. The L2 effective value was not retained.
The first native scans mistakenly set this field to `False` in the offline
configuration. The corrected condition now records it explicitly as `true`.
This is an evidence-backed target setting, while exact F12/F24 effective
values remain an inference from the installed default and launch path, not
an independently saved effective scheduler snapshot.

The 425 `replay/requests.jsonl` records contain request IDs, session/actor,
start/end times, lengths, and response measurements, but no complete prompt
token arrays or per-step scheduler batches. Each run contains 12 prompt
samples. Consequently, these files alone cannot prove exact historical
per-request prefix identity or P reference-release order. The existing
`replay425-request-admission-workload.json` is trace-driven reconstructed
content with deterministic output substitutes; it is suitable for a frozen
capacity experiment and must be labeled as such.

The local macOS Python environment has neither vLLM nor PyTorch. The H20
runtime at `/home/david_cwq/zhouziheng/agent-replay-20260917/runtime` reports
vLLM 0.26.0. Current installed Scheduler, coordinator, and manager source
SHA256 values match the local `stage-v4/diagnostic-12g/source` and
`stage-v5/source` snapshots (respectively
`2ed2a550b6558b2495eda845a97ae38bcf0225027b9e25fbf00fc3880c1d3941`,
`4c8fbb341f0bd3714eff54ce633f534c1475220decb17c0caed40cbd02b352a2`,
and `3f4af8d247f3fe9570b0132818b832b66ae6a2ac12942588828f899f6ff77ccf`).
These are **current installed source references**, not proof that each
historical run used byte-identical files. The recorded H-to-M code comparison
reports all listed application files equal. M-to-L2 reports `replay_v4.py`
different while the P launch command differs only in KV budget. Historical
runtime patch identity still needs direct provenance checked.

The CPU-only import probes (jobs 3713/3714) completed. The native five-group
Scheduler probe (job 3722) then showed two requests retaining KV simultaneously
across steps, native block events, transfer completion, and P reference release.
Its result is `output/kvsim/native-stage-a/native-probe-3722.json`.

The controlled 425-request scan completed at all three capacities under the
installed vLLM 0.26.0 CPU runtime (final job 3732, `PYTHONHASHSEED=0`). Its
summary, per-request and per-step results, selected event windows, comparison,
and first-difference evidence are under
`output/kvsim/native-stage-a/replay425-final/`. The aggregate result differs
substantially from historical L2 at 12 GiB; historical exact reproduction is
not established. See that directory's `REPORT.md` for metrics and limits.

A separate CPU-only mechanism job (3734) confirmed content-based reuse and
small-pool pressure behavior with two simultaneously running requests. Its
output is `output/kvsim/native-stage-a/mechanism-3734.log`; the Scheduler had
no preemptions in these cases. The job reached terminal `COMPLETED`, and the
account's SLURM queue was empty afterward.

After this first scan, the later stage-v5 formal capture's 425 P-side token
arrays were recovered from the authorized H20 evidence directory. Their
one-to-one source-key mapping and provenance are recorded in
`output/kvsim/native-stage-a/historical-capture-f12/CAPTURE_AUDIT.md`.
The captured-input three-capacity rerun is under
`output/kvsim/native-stage-a/replay425-delivery/`. Its per-request native
decisions matched the earlier synthetic-input and surrogate-layout scans under
the same logical protocol. The old L2/M/H reference runs still lack verified byte-identical
prompt content and P-side arrival/transfer/release order. Current source hashes
and observed group specs are useful references but do not prove exact
historical patch/layout identity for every run. No model or GPU run was
performed in this simulator work.

The captured-input scan above used `scheduler_reserve_full_isl=False`; it is
now retained as a protocol variant. The corrected target-profile scan with
this setting `True` is under
`output/kvsim/native-stage-a/replay425-full-sequence-true/`. It completed all
three capacity points in job 3772 with exactly the same request, step, and
selected event records as the variant. Its `CONFIG_CORRECTION.md` documents
the source of the correction and its remaining historical limits.
