# TIM V2 Data Coverage Methodology

Status: **Defined for audit; qualifying interval not yet approved**

Coverage gate: **FAIL**

## Primary coverage definition

The binding metric preserves the existing V2 criterion:

- symbol: `BTCUSDT`;
- market source boundary: Binance Spot aggregate trades;
- persisted measurement object: closed `1m` candles derived from those trades;
- time zone: UTC;
- interval: `[start_inclusive, end_exclusive)`;
- expected set: every one-minute open timestamp on the UTC minute grid inside
  the complete predefined interval;
- observed set: distinct persisted closed BTCUSDT `1m` candle `open_time`
  values exactly matching the expected grid;
- duplicates: persisted rows beyond the first row for the same
  `(symbol, timeframe, open_time)`, reported separately;
- missing: expected timestamps not present in the observed set.

For an interval whose boundaries fall on UTC minute boundaries:

```text
expected = floor((end_exclusive - start_inclusive) / 60 seconds)
observed = count(distinct qualifying open_time)
missing = expected - observed
coverage_percent = observed / expected * 100
```

The published artifact rounds with decimal `ROUND_HALF_EVEN` to three decimal
places. Acceptance compares the unrounded ratio to `95.000%`; display rounding
must never turn a lower result into a pass.

No minute may be removed after observing the outcome. Trailing collector
downtime is inside the denominator through the fixed `end_exclusive`.
Maintenance exclusions, if governance ever permits them, must be declared and
hashed before collection and reported both gross and net. No such exclusion is
approved for the evidence assessed here.

## Required secondary dimensions

These dimensions diagnose scientific integrity but do not replace the primary
candle-minute gate:

1. **Raw active-minute coverage:** expected minutes containing one or more
   persisted Binance Spot aggTrades.
2. **AggTrade sequence coverage:** distinct aggregate-trade IDs divided by the
   inclusive ID span, with every missing ID range enumerated.
3. **Duplicate rate:** duplicate candle keys and duplicate aggregate-trade IDs.
4. **Lineage coverage:** percentage of qualifying rows with immutable source
   URI or stream identity, source checksum where applicable, ingest timestamp,
   dataset version, parser version, and derivation hash.
5. **Gap disposition coverage:** percentage of canonical gap ranges with cause,
   evidence, owner, scientific impact, and reviewer disposition.

## Published frozen result

Source:
[tim_v1_readiness.json](../../data/research/status/tim_v1_readiness.json),
SHA-256
`7b682c57521f766c90e18900e490892d0faec2def4e3dbd65343e8380ab2ef6a`.

| Field | Value |
|---|---:|
| Start inclusive | `2026-07-22T20:14:00Z` |
| End exclusive | `2026-07-23T14:27:00Z` |
| Expected minutes | 1,093 |
| Observed distinct closed minutes | 663 |
| Missing minutes | 430 |
| Coverage | 60.658737...% |
| Published rounded coverage | 60.659% |
| Gate | **FAIL** |

The frozen snapshot also reports broader July coverage of
`1,959 / 4,362 = 44.911%` in
[2026-07.in_progress.json](../../data/research/snapshots/2026-07.in_progress.json).

## Current diagnostic results

Current diagnostics extend the frozen start but are not prospectively approved
qualifying intervals.

| Reported boundary | Expected | Observed | Missing | Coverage | Use |
|---|---:|---:|---:|---:|---|
| Baseline source reports `end_inclusive=2026-08-01T15:00:00Z` | 14,087 | 9,487 | 4,600 | 67.346% | Stored program baseline |
| Forensic `end_exclusive=2026-08-01T15:15:00Z` | 14,101 | 9,501 | 4,600 | 67.378200% | Independent read-only transaction |

At the forensic cut-off, the automatically derived August window
`[2026-08-01T00:08:00Z, 2026-08-01T15:15:00Z)` contained only
`71 / 907 = 7.828004%`. This diagnostic demonstrates why a month-derived
denominator cannot serve as a governance-approved qualifying interval.

The baseline boundary above is reproduced exactly as stored in
`baseline_manifest.json`; it must not be silently converted to end-exclusive.
That artifact's relation summary reports the latest candle at `14:59Z`, while
its coverage block reports `end_inclusive=15:00Z`. This internal boundary
discrepancy is another reason the baseline is diagnostic rather than acceptance
evidence.

## Independent query shape

The independent calculation uses a read-only repeatable-read PostgreSQL
transaction and an explicit minute grid:

```sql
WITH expected AS (
  SELECT generate_series(
    :start_inclusive::timestamptz,
    :end_exclusive::timestamptz - interval '1 minute',
    interval '1 minute'
  ) AS open_time
), observed AS (
  SELECT DISTINCT open_time
  FROM candles
  WHERE symbol = 'BTCUSDT'
    AND timeframe = '1m'
    AND closed = true
    AND open_time >= :start_inclusive
    AND open_time < :end_exclusive
)
SELECT count(*) AS expected,
       count(observed.open_time) AS observed,
       count(*) - count(observed.open_time) AS missing
FROM expected
LEFT JOIN observed USING (open_time);
```

Missing ranges are constructed only after generating every expected timestamp,
then grouping adjacent absent minutes. At forensic cut-off this produced 283
ranges and 4,600 minutes; 250 ranges and 4,170 minutes occurred after the
frozen interval.

## Defects in the current producer calculation

The implementation in
[research_infrastructure_review.py](../../scripts/research_infrastructure_review.py)
is useful for monitoring but is not sufficient for final acceptance:

- the month start and last persisted candle determine boundaries after the
  fact;
- the last persisted candle truncates trailing downtime;
- month rollover changes the denominator automatically;
- `open_time < as_of` is used without a candle ingest/system timestamp;
- a candle persisted later can change a historical `as_of` result;
- `DISTINCT` hides duplicates instead of reporting them;
- event-sequence and lineage coverage are absent.

The historical reproducibility defect was observed directly: the same
`as_of` first returned 58 observed of 894 expected August minutes and later 59
of 895 after a candle with an earlier open time was persisted. A final tool
must use an immutable database snapshot or require `close_time` and durable
ingest/system time to be at or before the evidence cut-off.

## Qualifying-run requirements

Before a new measurement can be considered for acceptance, governance must
freeze and hash the full interval and minimum duration. The final artifact must
contain expected, observed, missing, duplicates, all gap ranges, raw-ID
continuity, lineage completeness, query/tool version, immutable data cut-off,
and independent reproduction. Until then, monitoring values remain diagnostic
and the coverage gate remains **FAIL**.
