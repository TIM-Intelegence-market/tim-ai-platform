# TIM V2 Independent Data-Quality Review

Review type: automated independent forensic review

Human reviewer status: **NOT PERFORMED**

Overall quality disposition: **FAIL / OPEN**

This review independently reconciles frozen artifacts, current read-only
database facts, coverage semantics, and the 1,339-case claim. It is not a human
Scientific Review and cannot close V2-B03, V2-B04, V2-B05, or V2-B06.

## Evidence cut-offs

- Frozen scientific artifacts: `2026-07-23T14:27:42.127641Z`.
- Program baseline: `2026-08-01T15:00:43.767881Z`.
- Coverage forensic transaction: `2026-08-01T15:15:03.034086Z`.
- Gap-range forensic transaction: `2026-08-01T15:15:27.258264Z`.
- Case forensic transaction: `2026-08-01T15:15:54.067395Z`.

Current transactions were PostgreSQL `REPEATABLE READ`, `READ ONLY`. They did
not alter data or runtime state.

## Frozen quality artifacts

| Artifact | Frozen result | SHA-256 | Review disposition |
|---|---|---|---|
| [Artifact audit](../../data/research/audit/latest.json) | `FAIL`, 13 of 15 passed | `6620681264615c88d58702cf773a0a938fc0ea227d394f162d3dbfa7613391fb` | **FAIL remains binding** |
| [Research quality](../../data/research/quality/latest.json) | `FAIL`, 7,479 records checked, 367 raw gap records | `eff0ce873d63d9398cf8b51f646c62ad7681bdd93ae7938fd6ed99ac1c6701d4` | **FAIL remains binding** |
| [Readiness](../../data/research/status/tim_v1_readiness.json) | `NOT_READY_FOR_V2` | `7b682c57521f766c90e18900e490892d0faec2def4e3dbd65343e8380ab2ef6a` | **NOT READY** |

The artifacts have not been regenerated since July 23. Current runtime data
therefore cannot be inferred from them, and current DB counts cannot silently
replace their frozen evidence domain.

## Coverage and source-data quality

The independent current extension contains 9,501 observed of 14,101 expected
closed minutes, 4,600 missing minutes in 283 ranges, and 67.378200% coverage.
Of the missing minutes, 4,597 contain no persisted aggTrades and three contain
raw trades but no closed candle.

At `2026-08-01T15:15:03Z`, the persisted BTCUSDT aggregate-trade set contained:

- 4,009,771 rows and 4,009,771 distinct aggregate-trade IDs;
- ID range `4020624599` through `4027557716`;
- 2,923,347 absent IDs inside that inclusive span;
- event-sequence coverage of **57.835032%**.

Uniqueness of persisted IDs is positive evidence, but the large uncollected ID
span, missing minutes, stale artifacts, and incomplete candle lineage prevent a
quality PASS.

## Audit of the 1,339 validated cases

The published count originates from complete rows in `orderflow_validations`
whose `observed_at` falls before the frozen cut-off. Reconstructing the actual
frozen system-time boundary with
`validated_through <= 2026-07-23T14:27:42.127641Z` yields exactly 1,339 rows.

| Test | Result |
|---|---:|
| Rows | 1,339 |
| Unique observation IDs | 1,339 |
| Unique validation hashes | 1,339 |
| Unique input hashes | 1,339 |
| Distinct observed timestamps | 554 |
| Adjacent case pairs | 1,338 |
| Adjacent pairs with overlapping 30-minute horizon | 1,338 |
| Greedy non-overlapping 30-minute-window sensitivity | 30 |

Timestamp multiplicity is material: 171 timestamps produced one case, 150
produced two, 115 produced three, 71 produced four, 43 produced five, and four
produced six.

Exact ID/hash deduplication succeeds, but scientific independence is not
demonstrated. The observation engine may fire multiple deterministic patterns
at the same minute, and each pattern becomes a case. The validation engine then
uses the same 5-, 15-, and 30-minute future market path and classifies the
30-minute move using a fixed `+/-0.10%` threshold. Consequently, 1,339 unique
database rows are not evidence of 1,339 independent market experiments.

The 30-window result is a sensitivity check, not a newly imposed acceptance
rule. It demonstrates why an independence and near-duplicate rule must be
pre-registered before the qualifying count is calculated.

## Late-completion reproducibility

The current database contains 1,398 complete validations whose `observed_at`
falls in the original frozen observation window. Fifty-nine completed after the
frozen system-time cut-off. Filtering only on `observed_at`, as the producer
does, therefore changes the historical count; filtering `validated_through` at
the frozen cut-off restores 1,339. A final manifest must bind both event time
and system/validation time.

## Missing scientific-review fields

The current observation and validation schema has no durable fields for:

- named reviewer and review status;
- blind label, reviewer disagreement, and adjudication;
- volatility and liquidity regime;
- selection or confirmation-bias disposition;
- near-duplicate or overlapping-horizon cluster;
- per-case coverage/gap exposure;
- approved case-definition and independence-rule version.

Without these fields and a signed review protocol, the required “at least 1,000
cases after deduplication and quality review” is **not demonstrated**.

## Provenance and backfill

The live `agg_trades` table records a generic source and ingest timestamp, but
the candle table lacks source URI, source checksum, dataset/import version, and
ingest/system timestamp. Candle upsert can overwrite the same key. This is
insufficient for a versioned historical import or immutable acceptance pack.

If separately acquired and checksum-verified, official Binance Spot aggTrades
archives could be technically suitable for an isolated V2 dataset. This run
proved only filename-bound checksum-sidecar availability, not raw archive
payload availability or integrity. Backfill remains governance-conflicted and
is excluded from every result in this review. No OHLCV substitute or synthetic
interval is acceptable.

## Quality-gate matrix

| Area | Finding | Status |
|---|---|---|
| Frozen artifact audit | 13/15, artifact says FAIL | **FAIL** |
| Frozen research quality | Artifact says FAIL | **FAIL** |
| Primary coverage | 60.659% frozen; 67.378200% current diagnostic | **FAIL** |
| Gap completeness | 283 ranges classified forensically; signed ledger absent | **OPEN** |
| Persisted aggTrade uniqueness | Exact IDs unique | Evidence present, not an overall PASS |
| Event-sequence continuity | 57.835032% | **FAIL** |
| Exact case duplicates | None across IDs/hashes | Evidence present |
| Case independence | Severe timestamp/horizon reuse | **FAIL / UNKNOWN until rule approval** |
| Human review | Not performed | **WAITING / OPEN** |
| Historical backfill | Feasible but policy-conflicted; not performed | **CONFLICT / SEPARATE** |

Secure MCP is not a scientific Core gate and was not used in this quality
decision.

## Required actions

1. Seal one prospective evidence scope and immutable system-time cut-off.
2. Add versioned source and derivation lineage before any V2 import.
3. Implement and independently reconcile the canonical gap ledger.
4. Pre-register exact, near-duplicate, horizon-overlap, regime, and case-quality
   rules before recounting cases.
5. Produce a frozen case manifest with reviewer identities, blind labels,
   disagreements, adjudication, regimes, gap exposure, and all source hashes.
6. Require at least 1,000 qualifying cases after those rules, followed by named
   independent manual review.

## Conclusion

The data and case evidence are useful exploratory material, but they do not
satisfy the V2 scientific-quality or independent-review gates. Overall status
remains **FAIL / OPEN**, with no V2 or trading approval.
