# TIM Strategy Readiness Matrix

## Legend

- **COMPLETE:** deterministic, versioned, reachable and sufficiently tested.
- **PARTIAL:** useful implementation exists but requested contract is incomplete.
- **MISSING:** no implementation found.
- **NON_DETERMINISTIC:** implementation exists but reproducibility fails.

## Deterministic feature readiness

| Feature | Status | Evidence | Notes |
|---|---|---|---|
| Aggressive buy/sell volume | COMPLETE | `src/orderflow/metrics.py` | Decimal arithmetic; aggressor derived from buyer-is-maker |
| Net delta | COMPLETE | same | buy volume minus sell volume |
| Cumulative delta | COMPLETE | `series` | deterministic fixed-window carry |
| Buy/sell ratio | COMPLETE | same | explicit `None` for zero sell side |
| Buy/sell count | COMPLETE | same | fixed-window count |
| Trade frequency / trades per second | COMPLETE | same | fixed duration |
| Volume per second | COMPLETE | same | Decimal division |
| Average/max trade size | COMPLETE | same | canonical ordered input |
| p90/p95/p99 trade size | MISSING | no implementation found | percentile statistics exist only in research insights, not raw feature engine |
| Price change/range | PARTIAL | candles and validation horizons | not part of the orderflow metric contract |
| Volatility | MISSING | no deterministic feature found | — |
| Activity without price continuation | PARTIAL | Broncx candle rules and descriptive UI concepts | not a canonical orderflow feature contract |
| Delta-price divergence | MISSING | no rule/feature implementation found | UI labels do not prove runtime computation |
| CVD-price divergence | MISSING | no rule/feature implementation found | — |

Metric version is `1.0.0`. Trades are sorted by exchange time and aggregate ID;
Decimal values are canonically serialized; SHA-256 covers version, symbol,
window and canonical trades. Tests: `tests/test_orderflow_metrics.py`.

## Observation readiness

Implemented orderflow observations:

- `STRONG_BUYER_ACTIVITY`
- `STRONG_SELLER_ACTIVITY`
- `RISING_CVD_ACTIVITY`
- `FALLING_CVD_ACTIVITY`
- `HIGH_TRADE_FREQUENCY`
- `LARGE_INDIVIDUAL_TRADE_ACTIVITY`
- `EXTREME_BUY_RATIO_ACTIVITY`
- `EXTREME_SELL_RATIO_ACTIVITY`

Each requires two satisfied evidence clauses and adjacent windows. IDs and
input hashes are deterministic. Fields include ID, UTC time, symbol,
timeframe, version, evidence, hash, provenance and mode. Research cases add
`missing_evidence`.

Requested conceptual coverage:

| Requested concept | Status | Reason |
|---|---|---|
| POSITIVE_DELTA / NEGATIVE_DELTA | PARTIAL | delta measured, but no single-delta observation by design |
| LARGE_TRADE_BY_PERCENTILE | MISSING | fixed relative-average threshold, not percentile |
| ACTIVITY_WITHOUT_PRICE_CONTINUATION | MISSING in orderflow engine | no price feature in metric pair |
| PRICE_NON_CONTINUATION_AFTER_ACTIVITY | MISSING | retrospective outcomes do not implement this rule |
| DELTA_PRICE_DIVERGENCE | MISSING | no deterministic rule found |
| CVD_PRICE_DIVERGENCE | MISSING | no deterministic rule found |
| POSSIBLE_PASSIVE_ABSORPTION_CANDIDATE | MISSING in orderflow engine | candle `ABSORPTION_CONTEXT` is not equivalent |

Important gap: implemented observation creation checks adjacency and evidence,
but does not consume a universal coverage/freshness quality verdict. Therefore
the future criterion “no observation with insufficient data quality” is not
fully proven.

## Machine-readable strategy contract

| Required field | Status |
|---|---|
| strategy_id/version | MISSING |
| market/session/timeframes | MISSING |
| required_data | MISSING |
| context/entry/exclusion conditions | MISSING |
| invalidation/stop/target | MISSING |
| max_holding_time | MISSING |
| risk_rule | MISSING |
| data_quality_requirements | MISSING |

`src/models/market_data.py:Setup` is not a strategy contract and is disabled by
default. No runtime code produces a trade decision.

## Overall strategy status

**MISSING.**

The feature layer is **PARTIAL**, the implemented observation layer is
**COMPLETE for its declared V1 rules**, and a strategy is **MISSING**. A trade
cannot be reconstructed from versioned rules because no trade decision exists.
No strategy is invented or proposed by this assessment.

