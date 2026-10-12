-- DEFERRED outbox rows are outside the live claim index (which covers only
-- PENDING/RETRY/PROCESSING). The offline candle rebuild and the dashboard count
-- them per symbol; without this partial index that is a sequential scan over
-- the whole outbox on every run.
BEGIN;
CREATE INDEX IF NOT EXISTS ingestion_outbox_deferred_idx
    ON ingestion_outbox (worker_name, symbol, aggregate_trade_id)
    WHERE status = 'DEFERRED';
COMMIT;
