BEGIN;

CREATE TABLE IF NOT EXISTS ingestion_cursors (
    source TEXT NOT NULL CHECK (source = 'BINANCE'),
    market TEXT NOT NULL CHECK (market = 'SPOT'),
    symbol TEXT NOT NULL CHECK (symbol ~ '^[A-Z0-9]{3,20}$'),
    data_type TEXT NOT NULL CHECK (data_type = 'AGG_TRADE'),
    last_aggregate_trade_id BIGINT CHECK (last_aggregate_trade_id >= 0),
    last_event_time TIMESTAMPTZ,
    last_trade_time TIMESTAMPTZ,
    last_persisted_at TIMESTAMPTZ,
    cursor_version INTEGER NOT NULL CHECK (cursor_version > 0),
    cursor_hash TEXT NOT NULL CHECK (cursor_hash ~ '^[0-9a-f]{64}$'),
    recovery_state TEXT NOT NULL DEFAULT 'NORMAL'
        CHECK (recovery_state IN ('NORMAL','GAP_DETECTED','CATCHING_UP','DEGRADED')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (source, market, symbol, data_type),
    CHECK (
        (last_aggregate_trade_id IS NULL AND last_event_time IS NULL AND last_trade_time IS NULL AND last_persisted_at IS NULL)
        OR
        (last_aggregate_trade_id IS NOT NULL AND last_event_time IS NOT NULL AND last_trade_time IS NOT NULL AND last_persisted_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS ingestion_outbox (
    outbox_id TEXT PRIMARY KEY CHECK (outbox_id ~ '^[0-9a-f]{64}$'),
    worker_name TEXT NOT NULL CHECK (worker_name IN ('CANDLE_V1','FEATURE_V1','OBSERVATION_V1','RESEARCH_TRIGGER_V1')),
    idempotency_key TEXT NOT NULL CHECK (idempotency_key ~ '^[0-9a-f]{64}$'),
    source TEXT NOT NULL CHECK (source = 'BINANCE'),
    market TEXT NOT NULL CHECK (market = 'SPOT'),
    symbol TEXT NOT NULL,
    data_type TEXT NOT NULL CHECK (data_type = 'AGG_TRADE'),
    aggregate_trade_id BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','PROCESSING','RETRY','COMPLETED','QUARANTINED')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    last_error TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    lease_expires_at TIMESTAMPTZ,
    input_hash TEXT NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    output_hash TEXT CHECK (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'),
    worker_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (worker_name, idempotency_key),
    CHECK (status <> 'COMPLETED' OR (completed_at IS NOT NULL AND output_hash IS NOT NULL)),
    FOREIGN KEY (symbol, aggregate_trade_id)
        REFERENCES agg_trades(symbol, aggregate_trade_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ingestion_outbox_claim_idx
    ON ingestion_outbox (worker_name, status, available_at, created_at)
    WHERE status IN ('PENDING','RETRY','PROCESSING');

CREATE TABLE IF NOT EXISTS ingestion_gap_incidents (
    gap_id TEXT PRIMARY KEY CHECK (gap_id ~ '^[0-9a-f]{64}$'),
    source TEXT NOT NULL CHECK (source = 'BINANCE'),
    market TEXT NOT NULL CHECK (market = 'SPOT'),
    symbol TEXT NOT NULL,
    data_type TEXT NOT NULL CHECK (data_type = 'AGG_TRADE'),
    missing_from_id BIGINT CHECK (missing_from_id IS NULL OR missing_from_id >= 0),
    missing_to_id BIGINT CHECK (missing_to_id IS NULL OR missing_to_id >= missing_from_id),
    gap_started_at TIMESTAMPTZ,
    gap_ended_at TIMESTAMPTZ,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN','CATCHING_UP','RESOLVED','IRREPARABLE')),
    detected_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    resolved_at TIMESTAMPTZ,
    last_error TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK ((missing_from_id IS NULL AND missing_to_id IS NULL) OR (missing_from_id IS NOT NULL AND missing_to_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ingestion_gap_open_idx
    ON ingestion_gap_incidents (symbol, status, detected_at)
    WHERE status IN ('OPEN','CATCHING_UP');

CREATE TABLE IF NOT EXISTS ingestion_metrics (
    metric_name TEXT PRIMARY KEY,
    metric_kind TEXT NOT NULL CHECK (metric_kind IN ('COUNTER','GAUGE','MAX')),
    numeric_value DOUBLE PRECISION NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

COMMIT;
