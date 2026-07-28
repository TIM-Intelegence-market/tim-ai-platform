# TIM Phase 2 — Deterministic Orderflow Metrics

Phase 2 reads persisted Binance Spot aggTrades and calculates statistics only.
It creates no observations, research cases, confidence values, rankings,
predictions, or trading actions.

## Aggressor convention

Binance `buyer_is_maker=false` means the buyer was the taker and is counted as
aggressive buy activity. `buyer_is_maker=true` means the seller was the taker
and is counted as aggressive sell activity.

## Metrics

- aggressive buy and sell quantity
- net delta (`buy quantity - sell quantity`)
- cumulative delta from an explicit series start
- buy and sell counts
- average and largest trade quantity
- trades and quantity per second
- buy/sell quantity ratio (`null` when sell quantity is zero)

## Determinism

Windows are half-open `[start, end)` and use explicit timezone-aware timestamps.
Trades are ordered by exchange time and aggregate trade ID. Arithmetic uses
`Decimal` created from the persisted numeric representation. Each metric carries
a SHA-256 hash over its exact immutable source records, window and metric
version. Empty windows are retained as zero-valued intervals so replay timelines
remain structurally identical.

`OrderflowMetricsService` obtains records only through the repository's bounded,
ordered `agg_trades_between()` query. No external data or current market state is
consulted during calculation.
