# Mission 07 — deterministic offline research baseline

Implementation: `src/research_intelligence/engine.py` and `runner.py`.
Run: `.venv/bin/python -m src.research_intelligence.runner --collection verified-btcusdt-20260906T115023Z`.

The module is deliberately not wired into TIMApplication or any execution path.
The three horizons use independently configured durations and coverage gates.
SHORT requires 60 closed, contiguous one-minute bars; MID 168 hourly bars;
LONG 90 daily bars. At least 80% verified evidence is required for READY.
These are conservative research policy thresholds, not empirically calibrated
strategy parameters. READY describes data sufficiency only. Every thesis also
requires coherent evidence, quote quality, structural invalidation and R/R >= 2.

Input candles carry start/end/availability timestamps, complete-window status,
seconds, OHLCV and explicit VERIFIED/LEGACY provenance. Optional signed volume
supports aggressor imbalance and a labeled absorption proxy. Optional quotes
require publication/event timestamps, spread_bps, slippage_bps and depth_quote;
5 bps spread, 10 bps slippage and 100,000 quote units are conservative BTCUSDT
research thresholds. They are not a position-size-based execution simulation.
Callers of the pure engine must establish provenance; the collection runner
independently verifies the complete original receipt journal before assigning
VERIFIED. There is no production legacy-data adapter in this version.

The journal opens SQLite mode=ro, never the collector's mutable constructor.
An independent replay validates chain, accounting and native candle output.
Only trades both observed and timestamped at/before T enter aggregation. Partial
first/last windows are excluded. Candles must close and become available at/before
T. Future quote fields are discarded before hashing. Unsupported sources cannot
leak future data into the engine because they are never read.

Implemented features include local extrema and structure, close-confirmed BOS,
sweep/reclaim and conflicting sweeps, signed volume, absorption proxy, relative
volume, volatility regime, four-bar higher-timeframe comparison, candidate order
blocks and three-bar imbalances. Confidence is an explanatory weighted score,
with coverage and legacy penalties; it is not a probability. The resolver preserves
all input analyses and records alignment/conflict and the dominant READY horizon.

## Remaining Mission 07 scope — no full acceptance claimed

The following need validated adapters/calculations and their own tests before
full feature-scope acceptance: actual orderbook/passive absorption; price-binned
volume profile; derivative OI, funding, liquidation-event evidence; spot-vs-perp;
calendar-aligned Daily/Weekly/Monthly multi-timeframe context; accumulation /
distribution and long-term spot-demand evidence. Four-bar aggregation is a local
cross-timeframe proxy, not a replacement for those calendar contexts. Missing
inputs are explicit unavailable values. This implementation cannot classify
LIQUIDATION_EVENT, and does not fake that class from price volatility.

The fixed collection contains only four complete minute bars; its result is
SHORT LIMITED and MID/LONG NOT_READY, all NO_TRADE. No legacy dataset is loaded.
The historical legacy evidence warning remains in the reports. Research baseline
is runnable and deterministic; full TIM_TRADING_INTELLIGENCE_READY remains NO
until the outstanding feature scope is implemented and validated.

Graphify: the existing `graphify-out/.graphify_analysis.json` community 0 was
used to identify the native aggregator/model/orderflow architecture boundary.
This was not a fresh graph build. No model-generated market decisions are used;
Ollama and Omniroute were not needed for this implementation.
