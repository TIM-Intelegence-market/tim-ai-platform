# TIM Data Quality Framework

`DataQualityFramework` validates batches without modifying or inferring records.
It detects deterministic record identities, future, stale, or timezone-invalid
timestamps, missing provenance and required fields, unfinished candles, candle
gaps, unsupported timeframes, and incomplete observation reproducibility
metadata. Reports contain an input SHA-256, provenance counts, issues,
valid/duplicate counts, and a bounded rule-based quality score.

Duplicate identities are based on source keys: trade ID (or an explicit fallback
tuple), candle symbol/timeframe/open time, and observation UUID. The framework
does not promote fixtures or synthetic values to market evidence.

Reproducibility requires an explicit timezone-aware report time. The CLI enforces
this rather than silently using the wall clock:

```bash
.venv/bin/python scripts/data_quality_report.py \
  benchmarks/data_quality_fixture_v1.json \
  --as-of 2026-01-01T12:00:00+00:00
```

The default report is written to `data/quality/latest.json`. Repeating the
command with identical input, policy, and `--as-of` produces identical bytes.
Freshness defaults to 3,600 seconds and can be changed explicitly with
`--freshness-seconds`. Errors return exit status 1; warnings stay visible but do
not cause silent rejection. The report schema is
`schemas/data_quality_report_v1.json`.
