# TIM V2 Operational Readiness Review

Program ID: `TIM-V2-FINAL-READINESS-20260801`

Review: Phase 18C — independent automated operational review

Report evidence cut-off: `2026-08-01T16:18:45Z`

Operational point sample: `2026-08-01T15:47:20Z`  
Structured telemetry snapshot: `2026-08-01T15:48:40.303692Z`  
Final runtime recheck: `2026-08-01T15:59:25.361892Z`

Decision: **FAIL — TIM V2 IS NOT OPERATIONALLY READY**

Trading approval: **NOT GRANTED**

Scientific approval: **NOT GRANTED**

## Review question

> Can V2 be operated safely and reliably in OBSERVE-only mode?

**No, not yet.** The currently running process is OBSERVE-only and its
dashboard is loopback-bound, but the complete operational system does not yet
meet the required security, continuity, observability, recovery, and test
gates.

This review separates current liveness from readiness. A green point-in-time
health response is not evidence of continuous collection or lossless
recovery.

## Independent findings

| Gate | Decision | Basis |
|---|---|---|
| OBSERVE-only enforcement | PASS | API, active runtime composition, database mode constraints, and focused tests show no active trading path |
| Current dashboard boundary | PASS | listener only on `127.0.0.1:8765` |
| Fail-closed dashboard configuration | PASS | non-loopback IPs/hostnames rejected in code and focused negative tests; deployed listener remains loopback |
| PostgreSQL security boundary | **FAIL — P1** | wildcard IPv4/IPv6 port 5432, SSL off, LAN TCP connection succeeds, tracked default credential |
| Current process health | PASS — current sample | runtime, stream, and application DB probes green; fresh public market data |
| Continuous data coverage | FAIL | same-start extended coverage 67.346%, below 95%; 4,600 missing minutes |
| Host continuity | FAIL | 685-minute gap caused by confirmed host shutdown; additional sleep-correlated gaps |
| Durable resume and recovery | FAIL | no durable cursor or governed automatic gap repair |
| Backpressure safety | FAIL | direct serial await; no real queue, overflow, or drop telemetry |
| Independent observability | FAIL | completed validator is stale and is not a continuous external watchdog |
| Restart without loss/duplicates/rewind | PARTIAL PASS | isolated active-bucket recovery plus one controlled launchd restart passed; full crash-boundary/source-cursor proof remains open |
| Graceful safe deactivation | FAIL | signal handler exists; launchd KeepAlive and no tested supervisor runbook |
| Logs and retention | FAIL | no rotation; operational logs grow without a defined bound |
| Runtime test isolation | PASS | complete suite passed in a disposable isolated schema; production schema was not used and test schema was removed |
| Secure MCP local boundary | PASS — disabled | read-only/fail-closed configs and 55 focused tests pass |
| Secure MCP external association | BLOCKED — EXTERNAL | OpenAI organization/workspace mapping remains unresolved; no case ID |

## Evidence that currently passes

- TIM PID 19210 is supervised by launchd and was live after the controlled
  restart.
- `/api/health` reported `OBSERVE`, `observe_only=true`, current runtime,
  database, and stream `GREEN`, and governance `NOT_READY_FOR_V2`.
- The dashboard listener was exclusively `127.0.0.1:8765`.
- The active runtime contains no authenticated exchange, broker, wallet,
  order, position, or capital-allocation path.
- Ollama is disabled for TIM by policy.
- Database identity and integrity checks found no invalid indexes,
  unvalidated constraints, or invalid current market/observation rows.
- Raw trade writes are idempotent at their identity boundary.
- Common high-risk secret-pattern scans found no matches in the scoped MCP
  reports or operational logs.
- 55 Graphify/Gateway security tests and 19 selected runtime/safe-state tests
  passed.

These passes are retained and must not be downgraded merely because other
gates fail. They also must not be combined into a false overall PASS.

## Blocking operational evidence

### Security

The application connects to PostgreSQL through loopback, but PostgreSQL itself
listens on all IPv4 and IPv6 interfaces with SSL off. A LAN connection to port
5432 succeeds, and a default database credential is tracked in source. This is
a P1 network-boundary failure and independently blocks operational approval.

### Coverage and host availability

The authoritative Phase 0 extension records 9,487 observed of 14,087 expected
minutes, or 67.346%, with 4,600 missing minutes in 283 canonical ranges. The
largest 685-minute range aligns exactly with host shutdown, boot, and runtime
restart evidence. Historical data has not been fabricated or denominator-
adjusted; the gate legitimately remains failed.

### Recovery architecture

Launchd relaunches the process but still does not restore exchange history that
was never collected, because no durable exchange catch-up cursor exists.
Startup restoration now begins at the oldest latest persisted candle and
persists completed candles emitted during replay. An isolated recovery test
and one controlled live restart passed without a duplicate or transition-
minute loss. This is meaningful remediation but not full crash-boundary or
source-catch-up proof.

### Observability

The runtime reports a constant queue value for a direct-await design. It lacks
the required event accounting, drop reasons, duplicate/order/late counters,
real queue/backpressure, detailed latencies, rolling coverage, live gaps,
restart count, and recovery state. The historical validator has completed and
does not observe the current collector independently.

### Reliability operations

No bounded log rotation or complete supervisor-aware bootout/disable procedure
was found. Test isolation is now implemented and the complete suite passed in
a disposable schema. One controlled launchd restart and active-bucket recovery
test passed; broader failure injection remains open.

## Current reversible mitigation

After restart, the main agent re-established `caffeinate -dimsu -w 19210`,
observed active as PID 19228. This reduces immediate idle/sleep risk while the current runtime PID
exists. It is a reversible present-tense mitigation, not a permanent repair or
acceptance artifact. It does not survive every process/host transition,
restore missing data, provide a cursor, or prove a prospective continuous
window.

## Secure MCP separation

The Secure MCP workstream remains deliberately separate:

- local Graphify and gateway controls are safely disabled and pass focused
  read-only tests;
- `tunnel-client`, a dedicated runtime key, and a custom app have not been
  started;
- OpenAI workspace/organization association remains externally blocked;
- the support dossier is prepared, but no submission or case ID is recorded.

Resolving MCP would not repair coverage, PostgreSQL exposure, observability,
or restart safety. Conversely, the external MCP blocker must not halt safe
internal remediation of those independent gates.

## Conditions for operational re-review

Operational V2 may be reviewed again only after evidence shows:

1. PostgreSQL is loopback/private-bound by approved policy, LAN access is
   denied, effective HBA/firewall rules are reviewed, and the credential is
   rotated and removed from tracked defaults.
2. Dashboard startup fails closed for every non-loopback bind.
3. A prospectively approved observation interval runs on an always-on host
   with power-state telemetry and no unexplained P0/P1 gaps.
4. Coverage and an independent audit both meet the unmodified 95% gate.
5. A durable cursor/checkpoint and authoritative gap-recovery design pass
   isolated failure tests.
6. Restart tests prove no loss, duplicate downstream effects, or cursor
   rewind across every persistence boundary.
7. Real source/receive/valid/drop/order/latency/queue/gap/restart/recovery
   telemetry and alerts operate continuously.
8. An external watchdog detects collector stalls and stale persistence.
9. Log rotation, retention, disk alerts, and a supervisor-aware stop/rollback
   runbook are tested.
10. The full test suite passes against an isolated test database without
    touching the active dataset.
11. Security/Safe State and Runtime Reliability each receive an independent
    PASS.

The Secure MCP external blocker may remain separately documented, but no MCP
component may be enabled before association resolution and its own read-only
canary acceptance.

## Final determination

TIM is **currently collecting in a technically constrained OBSERVE-only
state**, which is safer than an enabled execution system. It is nevertheless
**NOT OPERATIONALLY READY FOR V2** because material P1 security, continuity,
recovery, observability, and retention gates remain open. Test isolation is
closed and is not part of this remaining blocker set.

This automated review cannot provide human scientific approval and never
authorizes trading or a live execution path.
