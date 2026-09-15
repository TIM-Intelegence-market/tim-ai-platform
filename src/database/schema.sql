DO $tim$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
        EXECUTE 'CREATE EXTENSION IF NOT EXISTS timescaledb';
    END IF;
END
$tim$;

CREATE TABLE IF NOT EXISTS agg_trades (
    symbol TEXT NOT NULL,
    aggregate_trade_id BIGINT NOT NULL CHECK (aggregate_trade_id >= 0),
    trade_time TIMESTAMPTZ NOT NULL,
    price DOUBLE PRECISION NOT NULL CHECK (price > 0),
    quantity DOUBLE PRECISION NOT NULL CHECK (quantity > 0),
    buyer_is_maker BOOLEAN NOT NULL,
    source TEXT NOT NULL CHECK (source = 'BINANCE_SPOT_AGGTRADE'),
    ingest_timestamp TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (symbol, aggregate_trade_id)
);
CREATE INDEX IF NOT EXISTS agg_trades_time_idx ON agg_trades (symbol, trade_time DESC);
CREATE OR REPLACE FUNCTION tim_reject_future_agg_trade_time() RETURNS trigger AS $tim$
BEGIN
    IF NEW.trade_time > clock_timestamp() + interval '5 seconds' THEN
        RAISE EXCEPTION 'future aggTrade timestamps are not allowed';
    END IF;
    RETURN NEW;
END
$tim$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS agg_trades_reject_future_time ON agg_trades;
CREATE TRIGGER agg_trades_reject_future_time BEFORE INSERT OR UPDATE ON agg_trades FOR EACH ROW EXECUTE FUNCTION tim_reject_future_agg_trade_time();

CREATE TABLE IF NOT EXISTS orderflow_observations (
    observation_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    summary TEXT NOT NULL,
    evidence JSONB NOT NULL CHECK (jsonb_array_length(evidence) >= 2),
    rule_version TEXT NOT NULL CHECK (rule_version = '1.0.0'),
    input_hash TEXT NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    provenance TEXT NOT NULL CHECK (provenance = 'BINANCE_SPOT_AGGTRADE_DETERMINISTIC'),
    mode TEXT NOT NULL CHECK (mode = 'OBSERVE')
);
CREATE INDEX IF NOT EXISTS orderflow_observations_time_idx ON orderflow_observations (symbol, observed_at DESC);
CREATE TABLE IF NOT EXISTS orderflow_validations (
    observation_id TEXT PRIMARY KEY REFERENCES orderflow_observations(observation_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL, observed_at TIMESTAMPTZ NOT NULL, baseline_price DOUBLE PRECISION NOT NULL CHECK (baseline_price > 0),
    horizons JSONB NOT NULL, complete BOOLEAN NOT NULL, outcome TEXT CHECK (outcome IN ('PRICE_INCREASED','PRICE_DECREASED','PRICE_SIDEWAYS')),
    validation_hash TEXT NOT NULL CHECK (validation_hash ~ '^[0-9a-f]{64}$'), validated_through TIMESTAMPTZ NOT NULL,
    validation_version TEXT NOT NULL CHECK (validation_version='1.0.0'), mode TEXT NOT NULL CHECK (mode='OBSERVE')
);
CREATE INDEX IF NOT EXISTS orderflow_validations_time_idx ON orderflow_validations(symbol,validated_through DESC);

CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open_time TIMESTAMPTZ NOT NULL,
    close_time TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL CHECK (open > 0),
    high DOUBLE PRECISION NOT NULL CHECK (high > 0),
    low DOUBLE PRECISION NOT NULL CHECK (low > 0),
    close DOUBLE PRECISION NOT NULL CHECK (close > 0),
    volume DOUBLE PRECISION NOT NULL CHECK (volume >= 0),
    trade_count INTEGER NOT NULL CHECK (trade_count >= 0),
    closed BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (symbol, timeframe, open_time)
);
DO $tim$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        EXECUTE 'SELECT create_hypertable(''candles'', ''open_time'', if_not_exists => TRUE, migrate_data => TRUE)';
    END IF;
END
$tim$;
CREATE INDEX IF NOT EXISTS candles_lookup_idx ON candles (symbol, timeframe, open_time DESC);
DO $tim$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='candles_timeframe_allowed') THEN
        ALTER TABLE candles ADD CONSTRAINT candles_timeframe_allowed CHECK (timeframe IN ('1m','5m','15m','1h'));
    END IF;
END
$tim$;

CREATE TABLE IF NOT EXISTS observations (
    observation_id UUID NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    kind TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    summary TEXT NOT NULL,
    confidence SMALLINT NOT NULL CHECK (confidence BETWEEN 0 AND 100),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL,
    provenance TEXT NOT NULL,
    observation_version INTEGER NOT NULL DEFAULT 1,
    rule_id TEXT NOT NULL DEFAULT 'unassigned',
    rule_version TEXT NOT NULL DEFAULT '1.0.0',
    input_hash TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (observation_id)
);
CREATE INDEX IF NOT EXISTS observations_lookup_idx ON observations (symbol, timeframe, observed_at DESC);
ALTER TABLE observations ADD COLUMN IF NOT EXISTS observation_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE observations ADD COLUMN IF NOT EXISTS rule_id TEXT NOT NULL DEFAULT 'unassigned';
ALTER TABLE observations ADD COLUMN IF NOT EXISTS rule_version TEXT NOT NULL DEFAULT '1.0.0';
ALTER TABLE observations ADD COLUMN IF NOT EXISTS input_hash TEXT NOT NULL DEFAULT '';
DO $tim$
DECLARE current_primary_key TEXT;
BEGIN
    SELECT pg_get_constraintdef(oid) INTO current_primary_key FROM pg_constraint WHERE conrelid='observations'::regclass AND contype='p';
    IF current_primary_key IS DISTINCT FROM 'PRIMARY KEY (observation_id)' THEN
        IF current_primary_key IS NOT NULL THEN ALTER TABLE observations DROP CONSTRAINT observations_pkey; END IF;
        ALTER TABLE observations ADD CONSTRAINT observations_pkey PRIMARY KEY (observation_id);
    END IF;
END
$tim$;
DO $tim$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='observations_timeframe_allowed') THEN
        ALTER TABLE observations ADD CONSTRAINT observations_timeframe_allowed CHECK (timeframe IN ('1m','5m','15m','1h'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='observations_provenance_allowed') THEN
        ALTER TABLE observations ADD CONSTRAINT observations_provenance_allowed CHECK (provenance='PUBLIC_MARKET_DATA_DETERMINISTIC');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='observations_rule_version_allowed') THEN
        ALTER TABLE observations ADD CONSTRAINT observations_rule_version_allowed CHECK ((rule_id='bos' AND rule_version='1.0.0') OR (rule_id='bronxc' AND rule_version='1.0.0'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='observations_input_hash_sha256') THEN
        ALTER TABLE observations ADD CONSTRAINT observations_input_hash_sha256 CHECK (input_hash ~ '^[0-9a-f]{64}$');
    END IF;
END
$tim$;

CREATE OR REPLACE FUNCTION tim_reject_future_candle_time() RETURNS trigger AS $tim$
BEGIN
    IF NEW.open_time>clock_timestamp() OR NEW.close_time>clock_timestamp() THEN
        RAISE EXCEPTION 'future candle timestamps are not allowed';
    END IF;
    RETURN NEW;
END
$tim$ LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION tim_reject_future_observation_time() RETURNS trigger AS $tim$
BEGIN
    IF NEW.observed_at>clock_timestamp() OR NEW.created_at>clock_timestamp() THEN
        RAISE EXCEPTION 'future observation timestamps are not allowed';
    END IF;
    RETURN NEW;
END
$tim$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS candles_reject_future_time ON candles;
CREATE TRIGGER candles_reject_future_time BEFORE INSERT OR UPDATE ON candles FOR EACH ROW EXECUTE FUNCTION tim_reject_future_candle_time();
DROP TRIGGER IF EXISTS observations_reject_future_time ON observations;
CREATE TRIGGER observations_reject_future_time BEFORE INSERT OR UPDATE ON observations FOR EACH ROW EXECUTE FUNCTION tim_reject_future_observation_time();

CREATE TABLE IF NOT EXISTS research_cases (
    case_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('OPEN','CLOSED')),
    observation_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    outcome TEXT,
    rule_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    documentation TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_cases_lookup_idx ON research_cases (symbol, status, updated_at DESC);

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
    recovery_state TEXT NOT NULL DEFAULT 'NORMAL' CHECK (recovery_state IN ('NORMAL','GAP_DETECTED','CATCHING_UP','DEGRADED')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (source, market, symbol, data_type),
    CHECK ((last_aggregate_trade_id IS NULL AND last_event_time IS NULL AND last_trade_time IS NULL AND last_persisted_at IS NULL) OR (last_aggregate_trade_id IS NOT NULL AND last_event_time IS NOT NULL AND last_trade_time IS NOT NULL AND last_persisted_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS ingestion_outbox (
    outbox_id TEXT PRIMARY KEY CHECK (outbox_id ~ '^[0-9a-f]{64}$'), worker_name TEXT NOT NULL CHECK (worker_name IN ('CANDLE_V1','FEATURE_V1','OBSERVATION_V1','RESEARCH_TRIGGER_V1')),
    idempotency_key TEXT NOT NULL CHECK (idempotency_key ~ '^[0-9a-f]{64}$'), source TEXT NOT NULL CHECK (source = 'BINANCE'),
    market TEXT NOT NULL CHECK (market = 'SPOT'), symbol TEXT NOT NULL, data_type TEXT NOT NULL CHECK (data_type = 'AGG_TRADE'), aggregate_trade_id BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','PROCESSING','RETRY','COMPLETED','QUARANTINED','DEFERRED')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0), max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    last_error TEXT, started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), lease_expires_at TIMESTAMPTZ,
    input_hash TEXT NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'), output_hash TEXT CHECK (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'),
    worker_version TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (worker_name,idempotency_key), CHECK (status <> 'COMPLETED' OR (completed_at IS NOT NULL AND output_hash IS NOT NULL)),
    FOREIGN KEY (symbol,aggregate_trade_id) REFERENCES agg_trades(symbol,aggregate_trade_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ingestion_outbox_claim_idx ON ingestion_outbox(worker_name,status,available_at,created_at) WHERE status IN ('PENDING','RETRY','PROCESSING');
CREATE INDEX IF NOT EXISTS ingestion_outbox_worker_order_active_idx
    ON ingestion_outbox(worker_name,aggregate_trade_id,created_at,outbox_id)
    INCLUDE(status) WHERE status <> 'COMPLETED';

CREATE TABLE IF NOT EXISTS ingestion_gap_incidents (
    gap_id TEXT PRIMARY KEY CHECK (gap_id ~ '^[0-9a-f]{64}$'), source TEXT NOT NULL CHECK (source = 'BINANCE'), market TEXT NOT NULL CHECK (market = 'SPOT'),
    symbol TEXT NOT NULL, data_type TEXT NOT NULL CHECK (data_type = 'AGG_TRADE'), missing_from_id BIGINT CHECK (missing_from_id IS NULL OR missing_from_id >= 0),
    missing_to_id BIGINT CHECK (missing_to_id IS NULL OR missing_to_id >= missing_from_id), gap_started_at TIMESTAMPTZ,
    gap_ended_at TIMESTAMPTZ, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CATCHING_UP','RESOLVED','IRREPARABLE')),
    detected_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), resolved_at TIMESTAMPTZ, last_error TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb, updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK ((missing_from_id IS NULL AND missing_to_id IS NULL) OR (missing_from_id IS NOT NULL AND missing_to_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ingestion_gap_open_idx ON ingestion_gap_incidents(symbol,status,detected_at) WHERE status IN ('OPEN','CATCHING_UP');

CREATE TABLE IF NOT EXISTS ingestion_metrics (
    metric_name TEXT PRIMARY KEY, metric_kind TEXT NOT NULL CHECK (metric_kind IN ('COUNTER','GAUGE','MAX')),
    numeric_value DOUBLE PRECISION NOT NULL DEFAULT 0, metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
