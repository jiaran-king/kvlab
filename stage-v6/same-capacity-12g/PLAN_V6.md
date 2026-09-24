# Same-capacity 12 GiB repeat

## Purpose

Compare the accepted frozen-input F12 run (SLURM 3462, run A) with one new
frozen-input 12 GiB run (run B). The input, P/D topology, runtime, connector,
cache settings, client protocol, and diagnostic hook remain fixed. The new
run is for run-to-run behavior at 12 GiB and is separate from the F12/F24
capacity comparison.

## Reuse decision

Use F12/3462 as run A. The H20 server retains its complete request inputs,
input index, request bodies, query diagnostics, KVEvent stream, proxy log,
admission log, acceptance evidence, and cleanup audit. Its source identity and
diagnostic implementation match the accepted C12 capture. One new run is
therefore sufficient for a same-observation paired comparison.

The event schema has `BlockStored`/`BlockRemoved` hashes and group metadata but
no direct request or lookup-key field. The event stream is retained for paired
analysis, but a hash cannot be assigned to a target lookup without additional
evidence. No new hook is added in this repeat.

## Fixed conditions

- 425 captured request bodies and P-side token IDs from F12/3462.
- Four H20 GPUs, P TP2 + D TP2; P 12 GiB per GPU and D 48 GiB per GPU.
- Same model, runtime, connector, cache and scheduler settings, and existing
  query/input/event observers as F12/3462.
- Same client concurrency 3, dependency rules, wait scale, generation
  parameters, and output plan.
- Uniform warmup, drain, P prefix reset, formal metrics, and cleanup gates.
- Frozen requests do not use newly generated output to build later inputs.

Fresh runtime request IDs and internal hashes are expected; cross-run hash
equality is not an acceptance condition.

## Acceptance and analysis

The new run must complete 425/425, pass frozen-input token and semantic
identity checks against F12/3462, reconcile query/group/final-adoption
counters, have a complete formal event stream, and pass resource cleanup.
Failures are preserved and are not silently retried.

Pair all 425 requests by stable source key. Report positive, negative, zero,
and absolute adoption differences; lookup boundaries; local input compute;
TTFT, slot wait, enqueue-to-first-token, E2E, task window, preemption, and
event counts. Fix the first-difference rule before inspecting target events.
For a small target window, compare input LCP, lookup boundaries, adoption,
actual request timing, and event sequence. Timing overlap alone is not a root
cause, and a BlockRemoved count alone is not a capacity-eviction proof.

## Deliverables

`summary.csv`, `paired-requests.csv`, target timeline/state summary,
`REPORT.md`, frozen configuration and cleanup evidence, and a minimal
reproducible analysis script. No third GPU run is scheduled automatically.

