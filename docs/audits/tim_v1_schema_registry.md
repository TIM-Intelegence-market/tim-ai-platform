# TIM v1 Schema Registry

| Entity | Identity | Event time | Numeric storage | Governance |
|---|---|---|---|---|
| agg_trades | `(symbol, aggregate_trade_id)` | `trade_time` UTC | float64 price/qty | source fixed; future >5s rejected |
| candles | `(symbol,timeframe,open_time)` | UTC open/close | float64 OHLCV | allowed TF; future rejected |
| observations | global UUIDv5 | observed/created UTC | float confidence/evidence | provenance, rule/version, SHA-256 |
| research_cases | deterministic text ID | opened/updated UTC | JSON evidence | OPEN/CLOSED |
| orderflow_observations | `ofobs_` + digest | window-end UTC | JSON evidence | ≥2 clauses, v1, OBSERVE |
| orderflow_validations | observation FK | observation/horizon UTC | float baseline + JSON Decimal strings | fixed outcomes, v1, OBSERVE |

## Canonicalization

- Metric inputs are sorted `(event_time, aggregate_trade_id)`.
- Metric arithmetic converts persisted float values through `Decimal(str(value))`.
- Hash JSON uses UTF-8, sorted keys where specified, and compact separators.
- Observation UUIDs and orderflow IDs are content-derived.
- Repository reads that feed science have explicit time/identity ordering.

## Constraints and caveats

- PostgreSQL stores price and quantity as `DOUBLE PRECISION`; exchange decimal text is converted to float during parsing. Decimal arithmetic prevents further binary accumulation drift but cannot restore precision discarded during parsing.
- `Observation.created_at` is wall-clock metadata created by raw rule objects. It is not included in the scientific input hash or stable UUID. Fresh replays can therefore differ in this metadata while their scientific IDs and evidence remain identical.
- Orderflow timeframes such as `60s` are intentionally separate from candle timeframe constraints.
