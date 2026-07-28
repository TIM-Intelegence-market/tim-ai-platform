# TIM Core 1.0 — Monthly Research Snapshot Protocol

Monthly snapshots provide an immutable research chronology without changing
the frozen Core. They are descriptive records only and never activate rules,
data sources, or runtime behaviour.

## Naming

`TIM Core 1.0 — Research Snapshot YYYY-MM`

The canonical JSON filename is `YYYY-MM.json` under
`data/research/snapshots/`.

## Required fields

- snapshot month and generation timestamp;
- Core and component versions copied from `config/core_manifest.json`;
- persisted AggTrade, candle, observation, and validated-case counts;
- real data-coverage percentage and its measured interval;
- replay hash and replay status;
- data-quality metrics and integrity status;
- explicit provenance summary;
- unresolved integrity issues, if any.

Counts must come from persisted state. Fixture, simulated, or TEST_ONLY data
must be excluded and may not be presented as research evidence.

## Determinism and version isolation

The snapshot payload is serialized with sorted keys before its SHA-256 digest
is calculated. Analyses must be partitioned whenever Core, metric, rule, or
validation versions differ. A mixed-version aggregate may only be shown as
separate labelled partitions.

## Coverage

Coverage is reported as measured observed duration divided by planned duration
for the stated interval. The snapshot must retain the raw expected and observed
interval counts so the percentage can be reproduced. Missing intervals remain
visible and are never silently interpolated.

## Snapshot template

```json
{
  "snapshot_name": "TIM Core 1.0 — Research Snapshot YYYY-MM",
  "snapshot_month": "YYYY-MM",
  "generated_at": "",
  "core_manifest_hash": "",
  "versions": {},
  "counts": {
    "agg_trades": 0,
    "candles": 0,
    "observations": 0,
    "validated_cases": 0
  },
  "coverage": {
    "interval_start": "",
    "interval_end": "",
    "expected_intervals": 0,
    "observed_intervals": 0,
    "coverage_percent": 0
  },
  "replay": {"status": "NOT_RUN", "hash": ""},
  "data_quality": {},
  "provenance": {},
  "integrity_status": "UNKNOWN",
  "open_integrity_issues": [],
  "snapshot_hash": ""
}
```
