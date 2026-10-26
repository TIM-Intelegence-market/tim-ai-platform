BEGIN;
ALTER TABLE candles DROP CONSTRAINT IF EXISTS candles_timeframe_allowed;
ALTER TABLE candles ADD CONSTRAINT candles_timeframe_allowed CHECK (timeframe IN ('1m','5m','15m','1h','4h','1d'));
COMMIT;
