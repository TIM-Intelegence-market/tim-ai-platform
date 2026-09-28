# TIM Dashboard V2: Data Contracts

**PROGRAM 2 — Professional Dashboard V2 — Contract Specification**

Program: `TIM-V2-COMPLETION-PROGRAM-20260803`
Items: `src/dashboard/app.py`, `src/dashboard/operations.py`

## Purpose

This document is the authoritative, developer-facing data contract for the
dashboard's read-only control surface. It defines every observable field from
the root status (`system_status`) down to the evidence index (`evidence_index`),
the provenance rules, and the invariants that CI enforces. No field is invented;
every status/coverage/metric on screen either comes from a persisted evidence
artifact or is reported as `UNAVAILABLE`.

## 1. Top-level snapshot (`/api/state`)

`DashboardState.snapshot()` returns:

| Field | Type | Source | Notes |
|---|---|---|---|
| `timestamp` | ISO-8601 | generated | UTC, at build time |
| `mode` | `"OBSERVE"` | constant | never changes in V2 |
| `provenance` | `"PUBLIC_MARKET_DATA_DETERMINISTIC"` | constant | no synthetic reinterpretation |
| `dashboard_version` | str | `DASHBOARD_VERSION` | currently `3.0.0` |
| `count_scope` | `"VISIBLE_RECENT_WINDOW"` | constant | honest bounds marker |
| `visible_counts` | dict | computed | candles/observations/research_cases |
| `case_counts` | dict | computed | active/closed/total |
| `candles` | list | `recent_candles[-50:]` | capped |
| `observations` | list | `active_observations[-50:]` | capped + case link |
| `research_cases` | list | `research_cases[-50:]` | capped |
| `validator` | dict | file or computed | see §4 |
| `timeline` | list | file | normalized events |
| `system_health` | dict | state | live broker/system |
| `operational_health` | dict | computed | see §2 |
| `market_status` | dict | state | symbol/timeframe |
| `memory_status` | dict | state | counters |
| `news` | dict | state | news engine |
| `readiness` | dict | `readiness()` | see §3 |
| `research_audit` | dict | file | artifact-driven |
| `research_quality` | dict | file | artifact-driven |
| `core_manifest` | dict | file | `config/core_manifest.json` |
| `governance_roles` | dict | file | roles |
| `safety` | str | constant | "RESEARCH ONLY — NO ORDERS OR EXECUTION" |
| `operations` | dict | `build_operations_snapshot` | see §5 |

## 2. `operational_health` (system status → freshness)

|Field|Type|Truth rule|
|---|---|---|
|`status`|GREEN/YELLOW/RED|`data_fresh` = age in `[0,120]s`. GREEN iff stream running AND db connected AND fresh; YELLOW iff db connected; else RED.|
|`database`, `stream`, `dashboard`, `runtime`|GREEN/RED|per-condition map|
|`last_data_at`|str/None|last candle close/open time|
|`data_age_seconds`|int|gap seconds, or `"MISSING:last_data_at"`|
|`checked_at`|ISO|build time|
|`runtime_started_at`|ISO|process start|
|`queue_depth` / `queue_model`|int/str|from system_health; model `"DIRECT_AWAIT_NO_APPLICATION_QUEUE"` default|
|`ollama_enabled` / `ollama_availability`|bool/str|explicit, never assumed reachable|

## 3. `readiness()` (persisted, non-synthetic)

Reads the readiness artifact and returns only keys present in evidence; does not
compute new scores. Callers must treat absent keys as `UNAVAILABLE`.

## 4. `validator`

`_validator()` builds cycle/health info from the validator artifact path; when
the artifact is absent the view shows an explicit "not available" state rather
than fabricating a PASS.

## 5. `operations` contract (`/api/operations`, `build_operations_snapshot`)

The control-center contract. `read_only`, `execution_disabled`, and
`trading_locked` are all literally `True`.

Sub-sections:

|Key|Meaning|Evidence priority|
|---|---|---|
|`security`|Postgres listener/HBA/credential state|completion evidence wins; legacy labelled baseline|
|`runtime`|processes, uptime, restarts, cursor age, queue|watchdog → tests → live snapshot |
|`datasets`|coverage cards: Frozen Live, Backfill Candidate, Approved Qualification, Prospective Campaign, Rolling Liveness|per-card artifact, `UNAVAILABLE` when missing |
|`gaps`|P0/P1 gap rows, bounded at `MAX_GAP_ROWS=500`|gap inventory jsonl |
|`qualification`|campaign id/status/manifest|preregistration + daily manifest |
|`independent_cases`|frozen/current/qualification/required/negative-controls/regime|case audit artifact |
|`readiness`|overall status + normalized gates|implementation state |
|`mcp`|case id, workspace, tunnel permissions|mcp support status |
|`audit`|test passed/failed/warnings, doctor/validate/protected, last incident|test summaries |
|`sources`|**evidence index** (see §6)|per-item path + availability predicate |

### Status normalization (`_normalized_status`)

`TRUE/GREEN/OK/COMPLETED/HEALTHY → PASS`; `FALSE → FAIL`; `WAITING/PENDING
REAL HUMAN REVIEW → PENDING HUMAN APPROVAL`; `NOT STARTED → TIME GATE`.
Everything else stays verbatim. Unknown status values are never promoted to a
fake PASS; classes are derived green/yellow/red from text markers only.

### Coverage truth model

Coverage is shown per dataset with three distinct guard rails:
- Rolling liveness coverage is a `PASS`-qualified window (`PT1440M`), never an
  overall claim.
- Backfill/qualification coverage is `UNAVAILABLE` unless an approved manifest
  exists; a blocked manifest is `BLOCKED`, not a success.
- The aggregation label is always `UNAVAILABLE` when either the numerator or
  the denominator source is missing.

## 6. `evidence_index` (`operations.sources`)

Every displayed value has a machine-readable trace:

```
sources: {
  "<artifact>.json": {"path", "available": bool, "scope": "V2_COMPLETION"|"LEGACY_BASELINE"},
  ...
}
```

Rules:
- `scope: "LEGACY_BASELINE"` sources are surfaced only as clearly labelled
  baselines; they are never promoted to a current V2 claim.
- `available: false` is shown as `UNAVAILABLE`, never synthesized.
- The rendered Audit & Evidence page enumerates these sources so a human can
  verify each claim directly to its artifact.
- A live watchdog entry (`live/watchdog_status.json`) is added separately with
  its own path/availability; it is a `LIVE_RUNTIME` observation, not a
  completion artifact.

## 7. Security & transport invariants (enforced)

- Loopback-only bind + DNS-rebinding `Host` check (421 for off-loopback).
- Full CSP (`default-src 'none'`), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, COOP/CORP.
- No inline handlers (`on*` attributes) allowed; all client behaviour is via the single auto-refresh script.
- Secrets are never serialized into the snapshot; redaction verified by test.

## 8. Honesty rules (V2 mandatory)

1. No synthetic status/coverage/metric values.
2. Missing evidence → `UNAVAILABLE`, never a default-present footer.
3. No predictions, forecasts, rankings, or recomputed confidence scores.
4. `Trading Action Count = 0` and `trading_enabled = false` at all times.
5. Every value must resolve to an artifact path via the evidence index or be explicitly `UNAVAILABLE`.