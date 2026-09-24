# Repair record for F12-B

The first F12-B attempt (3473) was not admitted as a valid same-capacity pair:
its query hook added `query_batch_committed` emission and a flush that were not
present in F12-A. It also hit one P/D ready timeout at request
`r00000414-1935038c86d0de74`, followed by one dependency skip. The run and its
failure report remain under `formal-3473/`.

The repair reused the frozen F12-A input and the exact `stage-v5/retry-1`
observation/replay implementation. The historical formal-run ledger was
temporarily isolated during job 3479 and restored after cleanup; it retains
only the original C12/F12/F24 entries. The corrected run passed 425/425 input,
counter, source-identity and cleanup checks.

The corrected pair differs by only 256 adopted local-cache tokens across all
425 requests. This is the result used in `final-analysis/FINAL-REPORT.md`.
