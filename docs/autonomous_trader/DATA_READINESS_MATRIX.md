# TIM Data Readiness Matrix

## Legend

- **AVAILABLE:** reachable ingestion, schema, persistence and inspected tests.
- **PARTIAL:** some representation exists, but the requested lifecycle or
  quality evidence is incomplete.
- **MISSING:** no implementation found.
- **UNVERIFIED:** an implementation may exist, but evidence is insufficient.

Target for a future trading research gate: coverage ≥99.5%, no unknown gaps,
no replay mismatches and provenance on every row. TIM does not currently meet
that complete target.

## Matrix

| Data type | Status | Source/market | Ingestion and storage | Quality/replay evidence | Principal limitation | Confidence |
|---|---|---|---|---|---|---|
| Spot AggTrades | AVAILABLE | Binance Spot BTCUSDT public `@aggTrade` | `BinanceTradeStream` → `agg_trades`; primary key `(symbol, aggregate_trade_id)` | duplicate/collision/restart/hash tests in `test_agg_trade_persistence.py`; deterministic ordering | historical missing input; no catch-up after reconnect | HIGH |
| Futures AggTrades | MISSING | — | no endpoint, schema or adapter found | none | no futures raw-data basis | HIGH |
| 1m candles | AVAILABLE | derived from Spot AggTrades | `CandleAggregator` → `candles` | aggregation, ordering, gap, governance and replay tests | frozen continuous window only 60.659% | HIGH |
| 5m/15m/1h candles | AVAILABLE | derived from Spot AggTrades | same table; allowed schema timeframes | aggregation and all-timeframe gap detection | inherit raw-input gaps | HIGH |
| Funding rate | MISSING | — | none | none | required for futures cost modelling | HIGH |
| Open interest | MISSING | — | none | none | no derivatives positioning context | HIGH |
| Liquidations | MISSING | — | none | none | no liquidation context | HIGH |
| Order-book snapshots | MISSING | — | none | none | no book-state replay | HIGH |
| Depth updates | MISSING | — | none | none | no sequencing/snapshot synchronization | HIGH |
| Mark price | MISSING | — | none | none | no futures valuation source | HIGH |
| Index price | MISSING | — | none | none | no index basis | HIGH |
| Fees | PARTIAL | fixed TEST_ONLY paper parameter | in-memory `PaperPolicy.fee_bps` | `test_paper_automation.py` | not market/account/tier-specific; no broker integration | HIGH |
| Slippage | PARTIAL | fixed TEST_ONLY paper parameter | in-memory `PaperPolicy.slippage_bps` | `test_paper_automation.py` | not size-, spread-, latency- or book-sensitive | HIGH |
| Latency | PARTIAL | dashboard/database health only | operational health reports | API <500ms acceptance check | no event-to-persist, signal-to-order or exchange latency model | HIGH |

## Spot AggTrade contract

- Timestamps are timezone-aware UTC (`Trade.event_time`).
- `source` is constrained to `BINANCE_SPOT_AGGTRADE`.
- Future timestamps beyond five seconds are rejected.
- Exact duplicate IDs are idempotent; conflicting payloads for the same ID
  raise an error.
- Queries order by `(trade_time, aggregate_trade_id)`.
- Metric inputs are canonicalized and SHA-256 hashed.
- Restart recovery reloads the current hour from persisted AggTrades.

Evidence: `src/models/market_data.py`, `src/database/schema.sql`,
`src/database/repository.py`, `src/orderflow/metrics.py`.

## Coverage and gap evidence

Frozen interval:

- start `2026-07-22T20:14:00Z`;
- end exclusive `2026-07-23T14:27:00Z`;
- expected 1m intervals: 1,093;
- persisted: 663;
- missing: 430;
- coverage: 60.659%;
- canonical gap groups: 33.

`TIM_TRANSPORT_RELIABILITY_REPORT.md` correlates the 33 groups with macOS host
sleep (99.508% aggregate overlap). Historical data was not reconstructed.

## Quality gates

Implemented:

- schema checks and future-time rejection;
- duplicate and conflicting identity rejection;
- deterministic ordering and hashes;
- persisted gap detection across timeframes;
- provenance restrictions for implemented observations;
- forward-only validation horizons;
- deterministic benchmark and replay tests.

Incomplete:

- no universal pre-observation gate that proves raw-window completeness for
  every path;
- no prospectively approved ≥99.5% qualifying window;
- no automatic historical catch-up;
- row-level provenance is incomplete in historical research artifacts;
- no data contracts for missing futures/book sources.

## Largest gaps

1. continuous capture reliability;
2. futures context data;
3. order-book data;
4. realistic fees/slippage/latency;
5. a universal fail-closed data-quality gate before any future strategy.

