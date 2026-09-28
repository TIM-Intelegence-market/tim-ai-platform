# Canonical independent-case methodology

Status: **FIXED AND VERIFIED — METHOD IMPLEMENTED; QUALIFICATION EVIDENCE PENDING**

## Canonical unit

A qualification unit is exactly one UTC-aware, 30-minute, non-overlapping
source window. The next unit may begin only at or after the prior unit ends.
Every unit records:

- UTC start and end;
- Binance Spot BTCUSDT source-window identity;
- minute completeness and gap exposure;
- observation ID when the unit is a detected positive;
- pre-registered label and positive/negative/neutral-control class;
- volatility, liquidity, session, weekday and optional trend/range regime;
- reviewer identity only after a real review;
- public-source provenance and SHA-256 input identity.

Duplicate unit IDs, duplicate input hashes, overlapping windows, incomplete
data, any source-gap exposure or missing provenance fail validation.

## Sampling

Sampling is time-blocked and hash-bound. Positive detector cases are not
treated as the entire scientific population. The prospective dataset must also
sample negative and neutral control windows and cover the pre-registered
volatility, liquidity, UTC-session and weekday strata. Near-duplicate source
windows and cherry-picked replacements are prohibited. Exclusions must use a
pre-registered reason and remain visible.

## Reproduced audits

| Cut | Complete labels | Quality eligible | Unique source windows | Strict 30m units | Required | Gate |
|---|---:|---:|---:|---:|---:|---|
| Frozen V1 | 1,339 | 910 | 378 | 14 | 1,000 | FAIL |
| Completion baseline current cut | 22,225 | 19,998 | 8,620 | 298 | 1,000 | FAIL |
| Prospective qualification | 0 | 0 | 0 | 0 | 1,000 | TIME GATE NOT STARTED |

The Frozen 1,339 are labels, never independent cases. The existing automated
audit evaluated all 1,339 rows against complete horizons, source-gap exposure,
case linkage/outcome and provenance, then deduplicated underlying source
windows and applied the strict 30-minute separation. Its frozen audit hash is
preserved in `artifacts/v2_completion/independent_case_audit.json`.

Current and Frozen evidence contains detector-fired cases only and lacks
negative/control sampling. It cannot pass the prospective scientific gate.
