# TIM V2 — Future Transport Reliability Requirements

## Scope

These are requirements only. They implement nothing and do not alter TIM Core
1.0. They apply to any future V2 planning after governance approval.

## Deployment-host requirements

### TR-HOST-001 — Continuous-execution profile

The approved live-data host must prevent idle system sleep for the complete
declared observation interval. Display sleep may be independent.

Verification:

- prospective `pmset`/platform power log;
- zero system-sleep overlap with the collection interval;
- independent reviewer confirmation.

### TR-HOST-002 — Power-state telemetry

Sleep, wake, DarkWake, clock change, reboot, and shutdown events must be
timestamped in UTC and correlated with input continuity.

### TR-HOST-003 — Single runtime identity

Exactly one reader instance must own a stream. PID, start time, binary/version,
and configuration hash must be recorded.

## Connection requirements

### TR-CONN-001 — Explicit connection state

Record DNS start/result, TCP/TLS connect, WebSocket open, last frame, ping,
pong, close code, exception class, reconnect start, and reconnect success.

### TR-CONN-002 — Last-message watchdog

Independently track the age of the last valid exchange message. A socket
reported as open must not be considered healthy solely because the process is
alive.

### TR-CONN-003 — Deterministic reconnect policy

Reconnect state and delay must be observable. For scientific replay of
operations, random jitter values must be logged. Reconnect must not silently
assert continuity.

### TR-CONN-004 — Planned connection rotation

Rotate before documented remote connection lifetime and record overlap or
handoff evidence. No two readers may persist duplicates.

## Continuity requirements

### TR-GAP-001 — Exchange-ID continuity

Persist and compare the last accepted aggregate trade ID with the first ID
after reconnect. A discontinuity must create a gap incident immediately.

### TR-GAP-002 — Minute completeness

For every declared 1m interval, report whether raw source continuity and
candle persistence are complete. “Stream running” is insufficient.

### TR-GAP-003 — No silent recovery

Reconnect restores live reception only. Missing history remains a declared
gap unless a separately governed recovery process is explicitly authorized.

### TR-GAP-004 — Recovery provenance

If future governance permits recovery, live and recovered records must carry
distinct provenance, source endpoint, retrieval time, dataset hash, and
validation status. Core 1.0 history must remain unchanged.

## Monitoring and alerting requirements

### TR-MON-001 — Multi-layer health

Monitor separately:

- host awake state;
- process liveness;
- event-loop progress;
- WebSocket state;
- last valid frame age;
- last persisted trade age;
- trade-ID continuity;
- candle completeness.

### TR-MON-002 — Timely alert

An alert must fire before a missing interval can mature silently. Thresholds
must be prospectively defined and versioned; this document defines no numeric
production threshold.

### TR-MON-003 — Independent observer

At least one health signal must originate outside the reader process so an
event-loop stall cannot report itself healthy.

## Network telemetry requirements

### TR-NET-001 — Path evidence

Retain timestamped DNS resolution, interface state, default-route changes,
reachability, TLS failures, and socket-close metadata.

### TR-NET-002 — Environment disclosure

Record active interface, proxy/VPN state, firewall profile, and network change
events for each observation interval.

### TR-NET-003 — No unsupported blame assignment

Do not classify router, ISP, Internet path, or remote endpoint without
timestamped evidence.

## Buffer and processing requirements

### TR-PROC-001 — Backpressure telemetry

Expose queue depth, maximum depth, handler latency, database latency, dropped
frames, and event-loop lag.

### TR-PROC-002 — Resource telemetry

Record CPU, memory, file descriptors, thread/task count, and resource-limit
events at a fixed cadence.

### TR-PROC-003 — Failure isolation

Parsing, validation, persistence, and connection failures must use distinct
error classes and metrics.

## Scientific-governance requirements

### TR-GOV-001 — Prospective interval

Coverage interval, expected cadence, formula, exclusions, and reviewer must be
sealed before collection.

### TR-GOV-002 — Immutable incident record

Every gap incident must include start, detection, recovery, affected IDs,
affected minutes, cause confidence, evidence references, and whether any
reconstruction occurred.

### TR-GOV-003 — Verification gate

Transport readiness requires a prospective run showing:

- zero host sleep during collection;
- deterministic continuity calculation;
- complete incident traceability;
- no silent missing exchange IDs;
- independently verified coverage at the approved threshold.

## Failover requirements

### TR-FAIL-001 — Failover is not duplication

Any future secondary reader must have deterministic ownership and
deduplication. Concurrent uncoordinated readers are prohibited.

### TR-FAIL-002 — Source diversity disclosure

A secondary endpoint or historical source must be explicitly identified in
provenance and may not be silently mixed with the primary live stream.

## Non-requirements

This document does not authorize:

- implementation;
- Core modification;
- historical backfill;
- a new database schema;
- external-source import;
- automatic incident closure;
- any trading capability.

## Acceptance evidence for future V2 planning

Each requirement must map to:

1. an owner;
2. a versioned specification;
3. a deterministic test;
4. an operational evidence artifact;
5. an independent reviewer;
6. an explicit PASS/FAIL decision.

## Status

**READY_FOR_VERIFICATION**
