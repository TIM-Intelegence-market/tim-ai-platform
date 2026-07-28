# TIM Phase 3 — Orderflow Research

Phase 3 converts adjacent deterministic metric windows into descriptive,
read-only research observations. It never predicts price, scores a market,
calculates confidence, or creates trading instructions.

## Two-evidence invariant

Every rule contains at least two explicit boolean evidence clauses. The engine
emits an observation only when every clause is true. PostgreSQL independently
enforces `jsonb_array_length(evidence) >= 2`.

Implemented combinations (rule version `1.0.0`):

- strong buyer activity: buy quantity >= 2x and buy count >= 1.5x prior window
- strong seller activity: sell quantity >= 2x and sell count >= 1.5x prior window
- rising/falling CVD activity plus an increase in the corresponding aggressor count
- high trade frequency: trades/sec >= 2x and quantity/sec >= 1.5x prior window
- large individual trade activity: largest trade >= 3x prior average and >= 2x current average
- extreme buy/sell activity: fixed volume and count ratios are both satisfied

## Reproducibility and persistence

Observation identity and input hash are derived from rule ID/version, both
metric source hashes, and exact evidence. Observation and research case persist
inside one database transaction. Replays are idempotent. New cases begin OPEN,
have no outcome, and list `subsequent_orderflow_context` as missing evidence.

## Deliberately unavailable

Delta divergence, passive resistance, and passive absorption are not implemented
because Phase 2 does not yet provide a deterministic price-response metric.
TIM does not infer these concepts from orderflow alone.

Dashboard: `/orderflow` (read-only timeline, filters and evidence detail).
