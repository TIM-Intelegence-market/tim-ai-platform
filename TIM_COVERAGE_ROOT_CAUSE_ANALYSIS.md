# TIM P0-001 — Continuous Coverage Root Cause Analysis

## Scope and evidence freeze

This investigation is read-only and concerns the persisted readiness cut-off
`2026-07-23T14:27:00Z`. No Core, manifest, validator, replay, rule, metric,
snapshot, scientific report, schema, or persisted market record was changed.

Evidence sources:

- `data/research/status/tim_v1_readiness.json`
- PostgreSQL tables `candles` and `agg_trades`, queried in read-only,
  repeatable-read transactions
- `data/operational/events.jsonl`
- `scripts/research_infrastructure_review.py` (formula inspection only)

The normalized investigation evidence has SHA-256
`6b650240babae8ead23110d68f19565d0c8be96d635166fa675f206ebfad1f2b`.

## Coverage definition

The implemented continuous interval begins one minute after the first
persisted AggTrade minute and ends at the last closed BTCUSDT 1m candle:

- start, inclusive: `2026-07-22T20:14:00Z`
- end, inclusive: `2026-07-23T14:26:00Z`
- equivalent end, exclusive: `2026-07-23T14:27:00Z`

Only distinct, closed, persisted `BTCUSDT` / `1m` candle `open_time` values
inside that interval count as observed minutes.

Formula:

```text
expected_minutes = floor((end_inclusive - start_inclusive) / 60 seconds) + 1
coverage_percent = observed_distinct_closed_1m_minutes / expected_minutes * 100
```

The implementation rounds to three decimals with decimal half-even rounding.
For this cut-off:

```text
expected = 1,093
observed = 663
missing  = 430
coverage = 663 / 1,093 × 100 = 60.659 %
```

This is a candle-persistence coverage measure. It is not exchange uptime,
network uptime, event-log availability, or validator uptime.

## Quantification

### Calendar day

The calendar rows are partial UTC days bounded by the frozen interval.

| UTC date | Expected | Observed | Missing | Coverage |
|---|---:|---:|---:|---:|
| 2026-07-22 | 226 | 226 | 0 | 100.000 % |
| 2026-07-23 | 867 | 437 | 430 | 50.404 % |

Daily coverage statistics:

- median: `75.202 %`
- minimum: `50.404 %`
- maximum: `100.000 %`

### Calendar week

| ISO week | Expected | Observed | Missing | Coverage |
|---|---:|---:|---:|---:|
| 2026-W30 | 1,093 | 663 | 430 | 60.659 % |

### Calendar month

| Month | Expected | Observed | Missing | Coverage |
|---|---:|---:|---:|---:|
| 2026-07 | 1,093 | 663 | 430 | 60.659 % |

### Overall

The overall continuous-window value is `60.659 %`. The separate historical
month coverage reported by the snapshot is `44.911 %` (`1,959 / 4,362`) and
must not be substituted for this blocker’s continuous-window metric.

## Root-cause localization

There are 33 distinct missing 1m ranges containing 430 missing minutes.
For every one of those 430 minutes:

- no closed 1m candle exists; and
- no persisted AggTrade exists.

Therefore the measured loss occurs at or before raw AggTrade persistence. It
does not originate in the deterministic AggTrade-to-candle aggregation path
for persisted input. This finding is supported by the exact zero count of
persisted AggTrades across all missing minutes.

### Cause classification

| Cause category | Ranges | Minutes | Evidence |
|---|---:|---:|---|
| DATA_GAP | 33 | 430 | Persisted 1m minutes are absent; matching DATA_GAP events exist |
| MISSING_INPUT | 32 | 415 | Zero AggTrades plus nearby health samples showing stream inactive or stale writes |
| UNKNOWN | 1 | 15 | Zero AggTrades while nearby health samples reported stream active |
| PROCESS_STOP | 0 proven | 0 proven | No interval-specific evidence proves a stopped runtime |
| VALIDATOR_FAILURE | 0 proven | 0 proven | Nearby samples report validator running; validator is not the input source |
| PIPELINE_FAILURE | 0 proven | 0 proven | No missing minute contains persisted raw input that was dropped downstream |
| MANUAL_STOP | 0 proven | 0 proven | No interval-specific manual-stop evidence exists |

`DATA_GAP` is the observed impact, while `MISSING_INPUT` and `UNKNOWN` are the
causal classifications. Event-log cause text
`UNKNOWN_SOURCE_OR_PERSISTENCE_GAP` correctly avoids asserting an unproven
network, exchange, process, or operator cause.

## Exact root cause

The direct, reproducible cause of 60.659% coverage is the absence of 430
distinct closed 1m candle minutes inside the fixed denominator of 1,093
minutes.

The pipeline boundary localization is exact:

1. 430 candle minutes are absent.
2. The same 430 minutes contain zero persisted AggTrades.
3. Consequently, downstream candle aggregation could not generate those
   candle records from persisted input.
4. Health evidence classifies 415 minutes as input-stream/persistence
   unavailability.
5. The remaining 15-minute range (`CG-023`) cannot be assigned beyond
   `UNKNOWN` from the available evidence.

The underlying physical cause of each missing input interval (network,
Binance endpoint, runtime supervision, operating-system sleep, or another
source/persistence fault) is not established by timestamped evidence and is
not asserted.

## Scientific impact

- Historical missing data remains missing and is not reconstructed.
- Any analysis requiring uninterrupted data across these ranges is limited.
- Results based only on persisted, provenance-valid records are not shown to
  be altered.
- The 60.659% readiness criterion fails because the declared continuous
  interval is not at least 95% complete.
- Event counts are not gap counts: the 367 DATA_GAP log records within the
  cut-off contain repeated checks and multiple timeframes. The canonical
  blocker register contains 33 distinct BTCUSDT 1m ranges.

## Maximum demonstrated coverage without Core change

Observed historical evidence demonstrates:

- `100.000 %` for the 226-minute partial UTC day on 2026-07-22;
- longest actual subwindow at or above 95%:
  `2026-07-22T20:14:00Z` through `2026-07-23T04:40:00Z` (end exclusive),
  `481 / 506 = 95.059 %`;
- actual suffix ending at the frozen cut-off:
  `2026-07-23T12:19:00Z` through `2026-07-23T14:27:00Z`,
  `122 / 128 = 95.312 %`.

These values prove that at least 95% was empirically achieved in real
subwindows without changing Core. They do not satisfy the readiness gate:
the qualifying interval duration was not prospectively defined, and selecting
a favorable historical interval after observation would be scientifically
invalid.

## Open points

1. A governance-approved prospective qualifying interval and minimum duration
   are absent.
2. `CG-023` remains causally `UNKNOWN`.
3. The physical causes behind the 32 `MISSING_INPUT` ranges are not
   independently timestamped with sufficient granularity.
4. Historical coverage cannot be increased without prohibited reconstruction
   or denominator manipulation.

## Blocker status

**OPEN**

The arithmetic and failure boundary are verified, but the prospective
operational evidence required for at least 95% does not yet exist.
