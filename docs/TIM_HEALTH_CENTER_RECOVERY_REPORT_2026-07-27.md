# TIM Health Center Recovery & Stabilization Report

Date: 2026-07-27  
Mode: OBSERVE-only  
Scope: Health Center, operational validator health persistence, research health checks, dashboard health API and regression coverage.

## Health Summary

The runtime, PostgreSQL connection, public BTCUSDT stream, dashboard, persisted scientific reports, acceptance state and research-health checks were inspected. The active runtime was confirmed as a single process. The dashboard and `/api/state` were reachable before the repair.

The Health Center now separates:

1. current operational health;
2. the frozen historical scientific baseline;
3. V2 governance and readiness.

Historical FAIL or NO-GO evidence is intentionally preserved. It no longer implies that the current runtime is down.

## Root Causes and Repairs

### False live-green header

Root cause: every successful `/api/state` HTTP response forced the global status to green.

Repair: the header now derives its state from the structured `operational_health` result. HTTP reachability alone cannot produce a green system state.

### Stream and capture false positives

Root cause: the string `system_health.stream == "running"` was treated as sufficient evidence. Snapshot creation time was incorrectly used as data freshness.

Repair: the live stream result now requires a running stream and a real recently closed candle. The last candle timestamp and age are exposed as evidence. Missing, stale or future data cannot be green.

### Historical validator presented as current runtime

Root cause: database, dashboard, persistency and runtime cards reused the completed 72-hour validator state from 2026-07-23.

Repair: live cards use current in-memory runtime state and the current process start time. The completed validator remains visible only in the historical scientific section.

### Missing structured health API

Root cause: the dashboard exposed `/api/state` but no dedicated health contract.

Repair: read-only `/api/health` now exposes current operational health, historical scientific status and governance status without changing persisted evidence.

### Health page refresh

Root cause: the five-second poll updated the header but not server-rendered health cards.

Repair: the health page detects meaningful health-state changes and reloads only when the status signature or last real data point changes.

### Future timestamps reported as fresh

Root cause: negative ages were clamped to zero.

Repair: future timestamps are explicitly reported as `INVALID:FUTURE_TIMESTAMP`.

### Acceptance health matrix erased at completion

Root cause: the final acceptance result omitted `health_matrix`; the runner replaced the persisted matrix with an empty object.

Repair: monitoring and final results both include the matrix. The runner also preserves the last non-empty matrix defensively.

### NO-GO recorded as INFO

Root cause: event severity depended only on the matrix level. An empty matrix made a non-zero process exit and NO-GO look informational.

Repair: non-zero execution, script errors and completed NO-GO results are always logged as errors.

### Completed validator restart storm

Root cause: loading a completed validator changed it back to RUNNING, increased `restart_count` and removed completion state.

Repair: completed state is idempotent. A normal restart does not mutate or rerun a completed acceptance validator.

### Database probe connection leak

Root cause: a failed query could bypass connection closure.

Repair: connection closure is guaranteed in `finally`.

### Empty research reports accepted as healthy

Root cause: equality between zero counters made all report integrity checks true. External search and module state were also hardcoded.

Repair: an empty report set is not valid evidence. Search and module state are read from `ResearchConfig`.

### Snapshot lock contention

Root cause: the ingestion lock was held while reading validator, timeline, readiness, audit, quality and manifest files.

Repair: mutable in-memory collections are copied under the lock; file I/O and derived-state work happen after releasing it.

## Changed Files

- `src/dashboard/app.py`
- `src/acceptance/monitor.py`
- `src/operational/runner.py`
- `src/operational/health.py`
- `src/operational/research_health.py`
- `tests/test_dashboard.py`
- `tests/test_acceptance.py`
- `tests/test_operational_validation.py`

## Added Regression Coverage

- dedicated `/api/health` contract;
- stale market data cannot be live-green;
- future timestamp rejection;
- header health is not inferred from HTTP success;
- final acceptance retains a full health matrix;
- completed validator restart is idempotent;
- empty report sets fail research-integrity evidence.

## Verification

- Focused health, dashboard, acceptance and research tests: 48 passed.
- Complete suite: 172 passed, 0 failed, 0 skipped.
- Python compilation: passed.
- Live deployment: one runtime process.
- `/api/health`: HTTP 200.
- Live operational status after deployment: GREEN.
- Historical scientific status remains FAIL/COMPLETED where persisted.
- Governance remains OBSERVE-only, Core FROZEN, NOT_READY_FOR_V2.

## Remaining Risks and Explicit Limitations

- Queue depth is not persisted and remains UNKNOWN.
- Ollama availability has no live health metric and remains UNKNOWN.
- The database card reflects the current runtime connection state, but there is no separate periodic SQL probe after the completed acceptance validator.
- The 145 test warnings come from Python 3.14 deprecations inside `pytest-asyncio`; they are visible and were not suppressed.
- Historical data gaps, provenance limitations and the scientific NO-GO were not changed or hidden.
- Controlled-failure correlation and strict acceptance-window filtering require a separately scoped scientific-validator change; this recovery did not rewrite historical acceptance evidence.

## Final Assessment

The Health Center is stable for its current read-only purpose and no longer conflates a live runtime with frozen scientific evidence. Current operational green is supported by a responding dashboard, connected database, running public stream and fresh persisted candle. Missing telemetry remains explicitly UNKNOWN rather than fabricated.

The system is operationally healthy. Scientific readiness remains blocked by the preserved historical findings.
