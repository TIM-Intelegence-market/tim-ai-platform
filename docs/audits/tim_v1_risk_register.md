# TIM v1 Risk Register

| ID | Severity | Finding | Evidence | Recommendation |
|---|---|---|---|---|
| R-001 | P1 | Live disconnect gaps cannot be backfilled by the current transport | Historical gap/coverage reports; no backfill path | Keep gap qualification; design V2 transport telemetry/failover separately |
| R-002 | P1 | Exchange decimals are parsed/stored as float64 | parser, schema | Future version should define exact decimal/numeric contract; do not rewrite v1 |
| R-003 | P2 | `Observation.created_at` is wall-clock metadata | model/rule construction | Exclude from scientific equality or inject an explicit replay timestamp |
| R-004 | P2 | Same-timestamp live trade ordering relies on source delivery order | aggregator tracks time, not `(time,id)` | Specify ordering contract and test transport ordering in V2 |
| R-005 | P2 | Active sub-hour candle state is memory-resident | aggregator/runtime restore path | Treat restart boundaries as gap-qualified; add future checkpoint contract outside v1 |
| R-006 | P2 | Research artifact audit reports historical documentation/hash-contract issues | existing audit artifacts | Preserve history; apply the versioned hash contract only prospectively |
| R-007 | P3 | Local pytest launcher has a stale absolute shebang | `.venv/bin/pytest` | Use `.venv/bin/python -m pytest` or recreate the environment in maintenance |
| R-008 | P3 | WebSocket retry jitter is nondeterministic | stream retry | Accept as operational behavior; it is excluded from scientific hashes |

No trading/execution risk was found because no authenticated order path exists and persisted scientific modes are constrained to `OBSERVE`.
