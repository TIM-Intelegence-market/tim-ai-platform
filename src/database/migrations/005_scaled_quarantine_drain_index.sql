-- Run outside an explicit transaction so PostgreSQL can keep the live outbox writable.
CREATE INDEX CONCURRENTLY IF NOT EXISTS ingestion_outbox_worker_order_active_idx
    ON ingestion_outbox(worker_name,aggregate_trade_id,created_at,outbox_id)
    INCLUDE(status) WHERE status <> 'COMPLETED';
