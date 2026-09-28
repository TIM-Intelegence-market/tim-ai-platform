-- A documented live cutover never deletes historical work.  It only removes
-- explicitly deferred records from the live capacity calculation.
BEGIN;
ALTER TABLE ingestion_outbox DROP CONSTRAINT IF EXISTS ingestion_outbox_status_check;
ALTER TABLE ingestion_outbox ADD CONSTRAINT ingestion_outbox_status_check
    CHECK (status IN ('PENDING','PROCESSING','RETRY','COMPLETED','QUARANTINED','DEFERRED'));
CREATE TABLE IF NOT EXISTS live_cutover_receipts (
    cutover_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    symbol TEXT NOT NULL,
    baseline_cursor_id BIGINT NOT NULL,
    first_live_trade_id BIGINT NOT NULL,
    deferred_outbox_count BIGINT NOT NULL CHECK (deferred_outbox_count >= 0),
    manifest_json JSONB NOT NULL,
    manifest_hash TEXT NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    mode TEXT NOT NULL CHECK (mode = 'OBSERVE_ONLY'),
    trading_actions INTEGER NOT NULL DEFAULT 0 CHECK (trading_actions = 0)
);
COMMIT;
