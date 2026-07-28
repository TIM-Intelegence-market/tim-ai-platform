# TIM Phase 4 — Orderflow Validation Engine

Phase 4 documents what happened after an existing Orderflow Observation. It
creates no observations, rules, confidence values, probabilities, rankings,
predictions, or trading actions.

## Fixed protocol

- Horizons: 5, 15 and 30 minutes after `observed_at`.
- Baseline: last persisted Binance Spot aggTrade at or before `observed_at`.
- Horizon price: last persisted trade at or before the exact horizon.
- Delta: aggressive buy quantity minus aggressive sell quantity strictly after
  the observation and through the horizon.
- Price outcome after 30 minutes: `PRICE_INCREASED` above +0.10%,
  `PRICE_DECREASED` below -0.10%, otherwise `PRICE_SIDEWAYS`.

Partial 5/15-minute records remain OPEN and retain
`subsequent_orderflow_context`. Once the 30-minute horizon is backed by real
persisted trades, validation, case closure, outcome, and missing-evidence removal
are persisted atomically.

Every horizon and complete validation has a SHA-256 source hash. Reversed input
order produces identical output. Future horizons and missing baselines are never
invented.

The read-only `/orderflow` page displays validation progress, outcome, and the
complete 5/15/30-minute evidence timeline.
