# TIM v1 Lookahead and Leakage Audit

Decision: **PASS with documented metadata and transport caveats**.

## Verified boundaries

- BOS and Broncx rules require a closed last candle.
- Observation hash validation queries only candles with `close_time <= observed_at`.
- Orderflow metrics use half-open windows ending at observation time.
- Outcome validation uses a baseline at/before observation time and evidence strictly after it.
- A horizon is evaluated only when `target_at <= as_of`.
- News/memory logic excludes future records in existing regression tests.
- Dashboard, reports, assistants and Ollama output do not feed back into rules.

## No leakage found

No code path was found where post-observation prices, future candles, later news, LLM output, dashboard state or manual labels enter an observation's input hash or rule evaluation.

## Caveats

1. `created_at` is wall-clock metadata, not event time. It must not be interpreted as a market-evidence timestamp.
2. WebSocket retry jitter is nondeterministic operational timing, but it is outside replay science and does not enter hashes.
3. Missing transport intervals are not reconstructed; analyses spanning such intervals must retain gap qualifications.
4. Float parsing/storage is a precision-contract risk, not lookahead.
