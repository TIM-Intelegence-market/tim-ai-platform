# TIM Phase 1 — Spot aggTrade Persistence

TIM persists every accepted Binance Spot `BTCUSDT@aggTrade` before it reaches
the candle aggregator. This is an OBSERVE-only infrastructure path.

## Identity and immutability

- Primary key: `(symbol, aggregate_trade_id)`.
- Source is fixed to `BINANCE_SPOT_AGGTRADE`.
- Exact reconnect replays return `False` and do not reach candle aggregation.
- A repeated identity with a different payload is rejected as a governance error.
- Price, quantity, side flag and exchange trade time are stored unchanged.
- `ingest_timestamp` records database arrival time and is not part of the source hash.

## Restart recovery

At startup TIM loads persisted aggTrades from the current UTC one-hour bucket
in exchange-time order. Replaying these records reconstructs all active 1m, 5m,
15m and 1h candle builders. Already persisted IDs remain idempotent when the
WebSocket reconnects.

## Deterministic hash

`agg_trade_hash()` hashes canonical JSON containing the immutable Binance fields
and source. Identical source records produce identical SHA-256 hashes across
restart and replay.

## Migration

Fresh startup applies the table through `src/database/schema.sql`. Existing
installations can apply `src/database/migrations/001_agg_trades.sql`. The normal
TIM launch uses `--init-schema`, so the migration is also applied idempotently on
the next managed restart.

No orderflow rules, predictions, AI calls, orders, or trading controls are part
of this phase.
