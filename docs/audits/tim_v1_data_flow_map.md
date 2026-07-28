# TIM v1 Data Flow Map

## Primary live path

1. Binance public `aggTrade` JSON is parsed and type-checked.
2. `agg_trades` persistence occurs first. Exact replay duplicates return `False`; conflicting payloads for an existing ID raise.
3. Only a newly persisted trade reaches candle aggregation.
4. Closed UTC buckets are upserted into `candles`.
5. Closed candle history drives deterministic BOS/Broncx observations.
6. Observation input hashes are checked against persisted, closed candles before atomic observation/case persistence.
7. Consecutive 1-minute aggTrade windows produce Decimal-based orderflow metrics.
8. Fixed two-clause rules produce orderflow observations and research cases atomically.
9. Persisted trades at `observed_at < trade_time <= horizon` produce 5/15/30-minute validation records; a 30-minute result closes the case.
10. Dashboard and analytics read persisted state; they do not create market evidence.

## Time semantics

- Exchange trade time: Binance `T`, converted to timezone-aware UTC.
- Candle window: `[open_time, close_time)`.
- Metric window: `[window_start, window_end)`.
- Observation time: closed candle time or orderflow window end.
- Validation baseline: last trade at or before observation time.
- Validation evidence: strictly after observation time and at/before each horizon.
- Ingest time is operational metadata and is not used for market ordering.

## Failure boundaries

- Malformed transport messages are logged and skipped.
- A disconnect retries with bounded exponential backoff and jitter.
- There is no live backfill; disconnect intervals remain scientific gaps.
- Active candles exist only in memory. Restart restores the current 1h aggregate from persisted aggTrades; completed smaller windows are reconstructed naturally from persisted history only where explicitly invoked.
- Database transactions bind observation+case and validation+case mutations.

See `artifacts/audits/tim_v1_data_flow_graph.json` for the machine-readable graph.
