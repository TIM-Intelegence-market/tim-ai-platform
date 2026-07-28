# TIM P0-003 — Transport Reliability Report

## Executive finding

The most probable cause is no longer unknown. Persisted macOS power-management
evidence identifies the cause of all 33 live-input gaps as **LOCAL_HOST**:
the Mac entered deep idle sleep repeatedly while the TIM WebSocket reader was
expected to run.

Quantified correlation:

```text
gap groups:                  33
macOS sleep intervals:       33
gap duration:                25,800 seconds
sleep overlap:               25,673 seconds
aggregate overlap:           99.508 %
minimum per-gap overlap:     96.548 %
maximum per-gap overlap:     100.000 %
```

All 33 gaps also terminate within 53 seconds of a logged WebSocket
disconnection. Binance public evidence confirms market activity in all 430
missing minutes. The causal chain is therefore:

```text
macOS idle/maintenance sleep
→ Python event loop and WebSocket reader suspended
→ live frames not received/persisted
→ socket detected stale during DarkWake
→ reconnect without historical catch-up
→ permanent local gap
```

## Scope

This is a read-only investigation of the P0-001/P0-002 frozen interval. It
changes no Core, persistence, database, replay, validator, snapshot, report,
or historical artifact. It implements no transport fix.

Evidence:

- `pmset -g log`
- `pmset -g custom`
- `data/operational/runtime_launchd.err.log`
- `data/operational/events.jsonl`
- `src/data_ingestion/binance_ws.py`
- `main.py`
- P0-001 and P0-002 registers
- official Binance Spot WebSocket documentation

## Local environment

Documented host:

```text
macOS 26.5.1 (Build 25F80)
Darwin 25.5.0
Apple arm64
AC power
```

Current AC power configuration reports:

```text
sleep = 1
powernap = 1
tcpkeepalive = 1
networkoversleep = 0
```

Current settings alone do not prove historical behavior. The historical
`pmset` log does:

- initial `Idle Sleep` at `2026-07-23T04:08:45Z`;
- repeated `Maintenance Sleep` and `Sleep Service Back to Sleep`;
- short `DarkWake` periods between sleep intervals;
- full wake at `2026-07-23T11:56:17Z`;
- another `Idle Sleep` at `2026-07-23T12:03:14Z`;
- full wake at `2026-07-23T12:26:10Z`.

These periods align with the entire sequence from CG-001 through CG-033.

## Classification

Each gap receives exactly one cause category:

| Category | Gaps | Minutes | Evidence status |
|---|---:|---:|---|
| LOCAL_HOST | 33 | 430 | Proven by macOS sleep overlap and disconnect correlation |
| LOCAL_NETWORK | 0 | 0 | Not needed to explain gaps; no separate historical proof |
| INTERNET_PATH | 0 | 0 | Not needed to explain gaps; no path telemetry |
| REMOTE_ENDPOINT | 0 | 0 | Contradicted as primary cause by source availability and host sleep |
| SOFTWARE_FAILURE | 0 | 0 | Reader behaved consistently with event-loop suspension |
| RESOURCE_EXHAUSTION | 0 | 0 | No memory/fatal evidence in interval |
| CONFIGURATION | 0 | 0 | Sleep configuration contributed, but the observed event is classified LOCAL_HOST |
| UNKNOWN | 0 | 0 | Stage and physical host cause are established |

This does not mean that network conditions were perfect. It means no additional
category is required or sufficiently evidenced for these 33 gaps.

## Evidence by investigation area

### Energy and sleep

All 33 gaps overlap a documented host sleep interval. Twenty-two are covered
100%; all others exceed 96.5%. The 127 seconds not marked asleep occur at
second-level sleep/wake boundaries inside minute-bucketed gaps and do not
produce a complete persisted minute.

### Process

The runtime log continues across DarkWake cycles. No fatal traceback,
`MemoryError`, or error-level process record appears in the local
06:00–14:27 interval. This is consistent with suspension rather than process
termination.

### Resources

The historical unified-log query returned no memory-pressure, jetsam, or
out-of-memory record for the interval. No queue-overflow record exists.
Resource exhaustion is not evidenced.

### Network

The WebSocket log contains 28 `no close frame` and 5 keepalive `ping timeout`
terminal events. No historical packet-loss, DNS, router, ISP, VPN, proxy, or
firewall telemetry was retained. Those subcauses cannot be evaluated and are
not asserted.

### Binance

The documented Binance rules describe server pings, pong deadlines, and a
24-hour connection lifetime. TIM's failures occurred on repeated short
connections aligned to host sleep, not at the 24-hour boundary. Public market
records existed for every missing minute. No Binance status evidence was found
that explains the exact local sleep cadence.

## Risk assessment

| Cause | Likelihood | Scientific impact | Coverage impact | Future-live impact |
|---|---|---|---|---|
| LOCAL_HOST sleep | Confirmed | Critical | Direct cause of 430 missing minutes | Critical unless continuous execution is guaranteed |
| LOCAL_NETWORK | Unassessed | Potentially high | Unknown | Requires telemetry |
| INTERNET_PATH | Unassessed | Potentially high | Unknown | Requires telemetry |
| REMOTE_ENDPOINT | Low for these gaps | High if present | Not shown here | Must still be monitored |
| SOFTWARE_FAILURE | Low for these gaps | High if present | Not shown here | Watchdog and sequence evidence required |
| RESOURCE_EXHAUSTION | No evidence | High if present | Not shown here | Resource telemetry required |
| CONFIGURATION | Contributing condition | Critical | Allowed idle sleep | Must be governed in deployment profile |

## Remaining uncertainty

The investigation proves host sleep as the physical trigger for the 33 gaps.
It does not determine whether any additional packet loss occurred during wake
periods, because no packet-level or DNS/route telemetry was retained.

## Readiness impact

Coverage remains 60.659%. The finding does not reconstruct data and does not
close P0-001 or P0-002. It makes P0-003 suitable for independent verification,
but a future operational run must prove that the host remains continuously
awake.

## Status

**READY_FOR_VERIFICATION**

**P0-003 TRANSPORT RELIABILITY INVESTIGATION COMPLETE**
