# TIM V2 Runtime Reliability Report

Program ID: `TIM-V2-FINAL-READINESS-20260801`

Report evidence cut-off: `2026-08-01T16:18:45Z`

Operational point sample: `2026-08-01T15:47:20Z`  
Structured telemetry snapshot: `2026-08-01T15:48:40.303692Z`  
Final runtime recheck: `2026-08-01T15:59:25.361892Z`

Review type: automated, read-only operational review

Decision: **FAIL — RUNTIME RELIABILITY NOT DEMONSTRATED**

This report does not alter historical market data, coverage, or scientific
evidence. After isolated tests passed, one controlled launchd restart loaded
the bounded recovery and safe-boundary corrections. No trading capability was
enabled.

## Decision basis

TIM is currently alive and receiving public market data in `OBSERVE` mode.
That current liveness does not satisfy the V2 reliability gate. Continuous
collection, restart without loss, durable resume, real backpressure
measurement, independent live monitoring, and log retention are not yet
demonstrated.

The current API health response is therefore interpreted narrowly:

- `operational=GREEN` proves a fresh point-in-time application health sample;
- it does not prove continuous coverage, lossless restart, or source
  continuity;
- `queue_depth=0` is not a measured queue condition because the reported
  model is `DIRECT_AWAIT_NO_APPLICATION_QUEUE`;
- database connectivity through `127.0.0.1` does not prove that the PostgreSQL
  server itself is loopback-only.

## Current runtime snapshot

| Check | Evidence at cut-off | Result |
|---|---|---|
| Runtime | launchd `com.tim.runtime`, PID 19210, run 2 after controlled restart at 15:46:41Z | PASS — live now |
| Mode | `/api/health`: `OBSERVE`, `observe_only=true` | PASS |
| Dashboard | HTTP 200; listener only on `127.0.0.1:8765` | PASS — current binding |
| Collector | stream `GREEN`; data age 52 seconds | PASS — point-in-time only |
| Database application probe | `GREEN`; application connects through loopback | PASS — connectivity only |
| PostgreSQL listener boundary | IPv4 and IPv6 `*.5432`; LAN TCP connection succeeds | FAIL — P1 security dependency |
| Ollama | local service present but `DISABLED_BY_POLICY` for TIM | PASS |
| CPU | approximately 0.0% at the final sample | PASS — no current saturation |
| Resident memory | approximately 74 MiB | PASS — no current pressure observed |
| Open file rows | 55; launchd soft file limit 256 | PASS — current headroom only |
| Disk | 478 GiB free; volume 48% used | PASS — current headroom |
| Supervisor | launchd `RunAtLoad` and `KeepAlive` | PARTIAL — process relaunch only |
| Independent live observer | completed validator is not running continuously | FAIL |
| Durable resume/backfill cursor | none identified | FAIL |
| Real queue/backpressure metric | none | FAIL |
| Log rotation/retention | no policy or rotation mechanism identified | FAIL |
| Clock-offset telemetry | application and database UTC aligned; no independent offset metric | NOT DEMONSTRATED |
| Bounded restart acceptance | controlled restart preserved unique raw rows, advanced ID 4027561835→4027561929, persisted the 15:46 candle and returned health green | PARTIAL PASS — source catch-up still absent |

## Current sleep mitigation

The main agent activated a reversible host-awake guard after the baseline:

```text
/usr/bin/caffeinate -dimsu -w 19210
```

It was active as PID 19228 at the evidence cut-off and is tied to TIM PID
19210. `pmset` confirmed both system- and idle-sleep assertions.
This is a current mitigation only. It is not a permanent repair because it:

- ends when the referenced runtime exits;
- is not demonstrated as boot-persistent;
- cannot repair an existing gap;
- cannot prevent power loss, manual shutdown, or every host failure;
- provides no resume cursor, authoritative backfill, or continuity proof.

A prospective V2 observation interval still requires an approved always-on
host policy plus timestamped power-state evidence.

## Continuity and gap evidence

The fixed historical readiness baseline remains
`663 / 1,093 = 60.659%`. Extending the same start through the Phase 0 cut-off
produced:

- 14,087 expected one-minute intervals;
- 9,487 observed distinct closed one-minute intervals;
- 4,600 missing intervals;
- 67.346% coverage;
- 283 canonical missing ranges;
- a largest range of 685 minutes.

The largest current gap is `2026-08-01T03:18:00Z` through approximately
`2026-08-01T14:43:00Z`. macOS power evidence records shutdown at 03:18 UTC,
boot at 14:42 UTC, and runtime start at 14:43 UTC. Host unavailability is the
confirmed physical cause of this interval. Repeated shorter gaps correlate
with host sleep/DarkWake evidence and WebSocket disconnect warnings; each
interval still requires its own immutable incident classification.

There is no evidence that the missing minutes were fabricated or silently
filled. That preserves scientific honesty but leaves the coverage gate open.

## Collector and processing findings

The public WebSocket reader awaits the complete handler for every message in
`src/data_ingestion/binance_ws.py`. The handler in `main.py` serially performs
raw persistence, candle aggregation, orderflow work, validation, research
trigger work, file writes, and logging before the reader advances.

Consequences:

- there is no application-level durable ingress queue;
- queue depth, high-water mark, dropped-frame count, and backpressure are not
  measured;
- enrichment or database latency can delay reception;
- the final active-run snapshot measured source-to-store p95 at 1.757 seconds,
  p99 at 5.292 seconds and a 999.951-second maximum, with 5,100 rows classified
  as more than five minutes late. The maximum and late-row tail remain material
  warnings, although a controlled test has not proven single-cause attribution.

The runtime error log contains 432 historical public-stream disconnect
warnings. The majority are missing-close-frame and keepalive-timeout cases.
The reconnect loop uses exponential backoff with jitter, but it has no durable
source cursor or governed missing-history recovery.

## Restart and recovery findings

Raw trade insertion is idempotent by primary key and `ON CONFLICT DO NOTHING`,
with a conflicting-payload check. This is valuable duplicate protection but
does not prove end-to-end restart safety.

The candidate now starts recovery at the oldest latest persisted candle across
configured timeframes and idempotently persists every completed candle emitted
during raw replay. Isolated restart tests prove recovery of an active raw
bucket, and the controlled live restart preserved the transition minute. This
closes the confirmed current-hour/discard defect prospectively, but does not
provide a durable exchange source cursor or recover trades never collected.

The current evidence does not demonstrate:

- restart across every possible crash boundary;
- absence of duplicate research side effects across every crash boundary;
- exchange catch-up without a durable source cursor;
- replay from a durable high-water mark;
- gap detection and authoritative repair after host suspension;
- queue drain after a stalled downstream component.

Signal handlers request a graceful stream stop for `SIGINT` and `SIGTERM`, but
launchd `KeepAlive` will relaunch a normally killed process. No documented and
tested supervisor-level deactivation procedure was found. A controlled live
shutdown was deliberately not performed during this audit.

## Observability and log retention

The runtime exposes start time, latest-data age, basic component flags, and a
constant queue value. It does not continuously expose the Phase 5 minimum set,
including expected/received/valid/dropped event counters, drop reasons,
duplicate/out-of-order/late counters, parse and write latency, persistence
errors, event-loop lag, gap count, longest open gap, rolling coverage, real
restart count, or recovery state.

The completed operational validator is historical evidence, not an active
independent observer. Its state and generated gap/readiness artifacts are
stale relative to the current runtime.

No log rotation was found. Current sizes include:

| File | Size | Lines |
|---|---:|---:|
| `runtime_launchd.err.log` | 9,348,200 bytes | 18,800 |
| `events.jsonl` | 10,387,077 bytes | 37,154 |
| `validator_launchd.log` | 24,553,635 bytes | 922,824 |

Unbounded growth remains an operational risk even though current disk space
is ample.

## Test evidence and limits

The final isolated verification produced:

- 55 Graphify MCP client and workspace-gateway tests;
- 59 runtime/recovery/safe-state tests;
- 38 data-quality tests and 68 science tests;
- 113 TIM-IM tests;
- 362/362 tests in the complete suite, zero failures/skips/XFAIL, using an
  isolated PostgreSQL schema that was removed afterward.

The restart replay and controlled supervisor restart now have bounded passing
evidence. The tests still do not simulate every crash boundary, host failure,
durable exchange catch-up, authoritative backfill, or full bootout/disable
runbook. Test isolation is no longer an open gate.

## Minimal remediation and re-review gates

1. Move collection to an approved always-on execution profile and retain
   prospective sleep/wake/reboot evidence.
2. Add a durable source/downstream high-water cursor and deterministic gap
   incident ledger.
3. Decouple ingress from enrichment through a bounded durable queue or outbox,
   with explicit overflow behavior.
4. Publish real receive/drop/duplicate/ordering/error/latency/queue/gap and
   restart/recovery metrics.
5. Replay raw records through every incomplete downstream stage after restart;
   persist emitted completed candles.
6. Add isolated crash-boundary, reconnect, cursor, duplicate, queue-drain, and
   graceful supervisor restart tests.
7. Run an independent continuous watchdog outside the collector process.
8. Add bounded log rotation and retention.
9. Document and test a supervisor-aware safe stop and rollback procedure.
10. Close the PostgreSQL network-boundary finding documented in the security
    acceptance report.

Until these gates pass with prospective evidence, runtime reliability remains
**FAIL**.
