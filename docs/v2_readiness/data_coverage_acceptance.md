# TIM V2 Data Coverage Acceptance Record

Decision: **FAIL**

Gate: `coverage >= 95.000%`

Automatic or retrospective promotion: **prohibited**

## Acceptance scope

This record evaluates existing evidence against the unchanged coverage section
of the [V2 Readiness Checklist](../../TIM_V2_READINESS_CHECKLIST.md). It does
not create a qualifying interval, import historical data, or approve V2.

## Numeric determinations

| Evidence | Interval | Expected | Observed | Missing | Coverage | Gate |
|---|---|---:|---:|---:|---:|---|
| Published frozen readiness | `[2026-07-22T20:14Z, 2026-07-23T14:27Z)` | 1,093 | 663 | 430 | 60.659% | **FAIL** |
| Program baseline diagnostic | Source reports `end_inclusive=2026-08-01T15:00Z` | 14,087 | 9,487 | 4,600 | 67.346% | **FAIL** |
| Independent forensic diagnostic | `[2026-07-22T20:14Z, 2026-08-01T15:15Z)` | 14,101 | 9,501 | 4,600 | 67.378200% | **FAIL** |

The frozen result is the published readiness evidence. Current diagnostics are
reported to prevent a stale status from being mistaken for current collection
quality, but neither diagnostic is a prospectively approved qualifying run.
The baseline boundary is quoted as stored; its relation summary reports a
latest candle at `14:59Z`, so that diagnostic has an unresolved internal
boundary discrepancy and is not normalized here.

## Checklist evaluation

| Requirement | Evidence result | Acceptance status |
|---|---|---|
| Qualifying duration approved before measurement | No approval record exists | **OPEN** |
| Symbol and timeframe defined | BTCUSDT closed `1m` candle scope is documented | Evidence present; no standalone gate PASS |
| Start inclusive and end exclusive recorded | Frozen and diagnostic boundaries are recorded | Evidence present; prospective boundary still OPEN |
| Expected intervals reproducible | Explicit UTC minute grid and formula documented | Evidence present |
| Persisted intervals independently counted | Read-only `generate_series` recomputation performed | Evidence present, current snapshot not immutable |
| Duplicate intervals checked and reported | Final product and audit artifacts report zero persisted duplicate candle minutes | **PASS as machine evidence** |
| Missing intervals enumerated | Deterministic 283-row machine ledger exists; independent signed disposition is absent | **OPEN** |
| Coverage at least 95.000% | Highest reported value here is 67.378200% | **FAIL** |
| No reconstruction/interpolation/estimation | Values in this record use persisted live evidence only | No waiver for future backfill |
| Evidence hash recorded | Frozen sources, calculation code, data manifests and result payloads are hashed; human evidence-freeze verification is absent | **OPEN** |
| V2-B01 at least VERIFIED | Register remains OPEN | **FAIL / OPEN** |

Because the threshold fails, no combination of the other evidence can produce
acceptance.

## Coverage integrity findings

The legacy live producer methodology cannot be used unchanged for a final gate:

- its end follows the last persisted candle and therefore omits trailing
  downtime;
- month rollover resets its start and denominator;
- late candle persistence can change a historical `as_of` result;
- it did not emit duplicates, raw ID continuity, and lineage; the new audit
  artifacts do, but have no human acceptance;
- it has no pre-approved minimum interval duration.

The required replacement methodology is specified in
[data_coverage_methodology.md](data_coverage_methodology.md).

## Backfill disposition

No backfilled minute is present in these acceptance calculations. Official
Binance Spot aggTrades are technically suitable source records, but existing
governance prohibits historical backfill while the final-completion program
permits it. Until governance explicitly resolves that conflict:

- backfill is not authorized for acceptance;
- it must not alter the published frozen result or V1 rows;
- it must remain in an isolated, append-only, versioned V2 evidence dataset;
- official klines or other OHLCV must never substitute for aggTrades;
- a future acceptance report must show live-only and approved-backfill coverage
  separately.

Backfill cannot retroactively prove operational collector continuity. At most,
an approved separate dataset could support data completeness with explicit
lineage.

## Required re-evaluation package

A future acceptance attempt requires one immutable pack containing:

1. prior human approval of interval, minimum duration, scope, and exclusions;
2. sealed database/source cut-off and query/tool hashes;
3. expected, observed, missing, and duplicate counts;
4. complete canonical gap ledger and raw aggregate-trade-ID continuity report;
5. lineage and checksum report for every qualifying source partition;
6. independent recomputation with identical output hash;
7. zero unresolved new gaps in the qualifying scope;
8. named Integrity, QA, Scientific, and Release Authority decisions.

## Final disposition

**COVERAGE ACCEPTANCE FAIL.** V2-B01 remains OPEN. This record grants no V2,
implementation, release, or trading approval.
