# Historical backfill candidate report

Status: **FIXED AND VERIFIED — CANDIDATE COMPLETE, NOT PROMOTED**

Dataset: `V2_BACKFILL_CANDIDATE_V1`

## Outcome

The immutable candidate covers all 4,600 missing one-minute intervals in the
fixed completion baseline. It contains 2,736,515 relevant public BTCUSDT Spot
aggregate trades. It changed zero Frozen rows and wrote zero rows to the TIM
production database.

| Metric | Result |
|---|---:|
| Frozen live capture at the fixed cut | 9,847 / 14,447 = 68.160% |
| Gap minutes represented in candidate | 4,600 / 4,600 = 100.000% |
| Fixed-cut live plus candidate, if promoted | 14,447 / 14,447 = 100.000% |
| Frozen rows modified | 0 |
| Production database rows written | 0 |
| Readiness counted | no |

The combined value is an eligibility calculation, not a readiness result.
The authoritative readiness definition currently excludes backfill from its
reported coverage and requires a prospective window. Promotion therefore
requires a real Dataset Governance decision; this program did not manufacture
that decision.

## Sources and validation

Six completed UTC days were sourced from official Binance Vision Spot daily
aggTrades archives. For every archive, the official filename-bound checksum
sidecar was parsed, the downloaded SHA-256 matched, ZIP CRC and member name
passed, every row had the exact eight-field schema, values were positive, UTC
timestamps stayed in the archive day, and aggregate IDs were strictly ordered.

The still unpublished `2026-08-01` archive returned HTTP 404. The authorized
official public Market Data API was used for that day's gaps instead. It
returned 131,721 ID-contiguous rows in 132 bounded pages; 124,943 rows covered
the 843 missing minutes. Every response contributes to the persisted SHA-256
response chain. No API key or trading credential was used.

The full URLs/source IDs, periods, sizes, archive hashes, official checksums,
candidate payload hashes, parser/import versions and all 283 gap mappings are
in `artifacts/v2_completion/backfill_candidate_manifest.json`.

## Immutability and recovery

Downloaded archives remain in the ignored quarantine directory
`data/v2_completion/backfill_quarantine`. Gap-only candidate payloads remain in
the ignored dataset directory
`data/v2_completion/backfill_candidate/V2_BACKFILL_CANDIDATE_V1` and are bound
by the committed manifest. Re-running the builder accepts an existing payload
only when its content hash is identical; a differing payload fails closed.

The executable reconstruction is:

```text
.venv/bin/python scripts/v2_backfill_candidate.py
```

It never imports into Frozen V1 and never promotes itself.
