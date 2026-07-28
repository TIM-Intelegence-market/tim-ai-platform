# TIM P0-001 — Coverage Validation

## Frozen validation input

```text
symbol: BTCUSDT
timeframe: 1m
start inclusive: 2026-07-22T20:14:00Z
end exclusive: 2026-07-23T14:27:00Z
closed candles only: true
```

All database checks used read-only, repeatable-read transactions.

## Independent SQL method

The expected denominator was generated independently with a one-minute
PostgreSQL `generate_series`. Distinct persisted closed-candle timestamps were
left-joined to that grid.

```sql
WITH expected AS (
  SELECT generate_series(
    :start::timestamptz,
    :end_exclusive::timestamptz - interval '1 minute',
    interval '1 minute'
  ) AS m
),
actual AS (
  SELECT DISTINCT open_time AS m
  FROM candles
  WHERE symbol = 'BTCUSDT'
    AND timeframe = '1m'
    AND open_time >= :start
    AND open_time < :end_exclusive
    AND closed = TRUE
)
SELECT
  count(*) AS expected,
  count(actual.m) AS observed,
  count(*) - count(actual.m) AS missing
FROM expected
LEFT JOIN actual USING (m);
```

Result:

```text
expected: 1093
observed: 663
missing: 430
coverage: 60.659 %
```

## Determinism test

The same fixed-input query was executed ten times. Each normalized result used
sorted compact JSON and SHA-256.

| Run | Result hash | Coverage |
|---:|---|---:|
| 1 | `fd0b5e6e55851bfb82e4ffbf679260ea339a04b95bdd4bab0837cb38b0bcf08f` | 60.659 % |
| 2 | same | 60.659 % |
| 3 | same | 60.659 % |
| 4 | same | 60.659 % |
| 5 | same | 60.659 % |
| 6 | same | 60.659 % |
| 7 | same | 60.659 % |
| 8 | same | 60.659 % |
| 9 | same | 60.659 % |
| 10 | same | 60.659 % |

Unique result hashes: `1`.

## Test matrix

| Test | Result | Evidence |
|---|---|---|
| Formula inspection | PASS | Implementation counts distinct closed BTCUSDT 1m candle minutes |
| Fixed cut-off | PASS | End exclusive fixed at `2026-07-23T14:27:00Z` |
| Identical input → identical coverage | PASS | 10/10 result hashes identical |
| Independent minute-grid calculation | PASS | SQL result equals readiness result |
| Daily aggregation | PASS | Daily rows sum to 1,093 expected, 663 observed |
| Weekly aggregation | PASS | Week result equals overall fixed interval |
| Monthly aggregation | PASS | Month result equals overall fixed interval |
| Gap ranges sum | PASS | 33 ranges sum to 430 minutes |
| Raw-input boundary check | PASS | All 430 missing minutes contain zero persisted AggTrades |
| No artificial closure | PASS | Missing count remains 430 |
| No historical reconstruction | PASS | Investigation performed no market-data writes |
| Deterministic calculation | PASS | One unique hash across ten runs |

## Protected artifact hashes

The investigation did not modify the following protected evidence:

| Artifact | SHA-256 |
|---|---|
| `config/core_manifest.json` | `82bfe439178299adc5bca0ac1de17614a3fd5fe6ed72a110861f88af9d014ca6` |
| `TIM_V2_SCIENTIFIC_READINESS_ASSESSMENT.md` | `64803129d1f16a7659c49b845f3f19b40659a4dab4dc248fec380cd4940d3bc8` |
| `docs/TIM_FINAL_SCIENTIFIC_RECONCILIATION_REPORT.md` | `99e74eeb64ced4d32832e72c43f4c0a84d0851df8e06a68887304162a54187bc` |
| `scripts/research_infrastructure_review.py` | `9fb5232a99c57a8cc0c285ed943aebe32857648e5c7ef157f5db4e682c51ff75` |

Only the four authorized P0-001 Markdown deliverables were created in the
project.

## 95% validation boundary

The current frozen interval fails:

```text
663 / 1,093 = 60.659 %
```

Without deleting or reconstructing history, a cumulative interval beginning at
the same start requires exactly 7,507 additional observed minutes with zero
additional missing minutes:

```text
(663 + 7,507) / (1,093 + 7,507)
= 8,170 / 8,600
= 95.000 %
```

This is a necessary and sufficient arithmetic condition under the explicitly
stated zero-new-gap condition. It is not operational evidence and is not
treated as achieved.

Real persisted evidence also contains a 506-minute subwindow at 95.059%, but
the absence of a prospectively approved minimum qualifying duration prevents
its use as readiness evidence.

## Current coverage

**60.659 %**

## Maximum reachable without Core change

- Mathematical and empirically observed maximum: **100.000 %** over the
  226-minute partial UTC day on 2026-07-22.
- Longest observed interval at or above 95%: **506 minutes at 95.059 %**.
- Scientifically acceptable maximum for the readiness gate: **not yet
  determinable**, because the required prospective interval duration has not
  been approved.

## Necessary measures

1. Pre-register a qualifying interval and duration.
2. Maintain one continuous existing input runtime.
3. Act on existing stream-inactive and stale-write health states.
4. Preserve timestamped source/persistence evidence.
5. Repeat the fixed read-only validation at interval end.
6. Require independent scientific review.

## Remaining risks and open points

- `CG-023` remains causally unknown.
- Future input interruptions are irreversible without prohibited
  reconstruction.
- A high percentage over an insufficiently short window may not establish
  scientific maturity.
- No prospective qualifying interval has completed.

## Blocker status

**OPEN**

The investigation is reproducible and complete, but the 95% operational
criterion has not been verified.

## Status

**P0-001 COVERAGE INVESTIGATION COMPLETE**
