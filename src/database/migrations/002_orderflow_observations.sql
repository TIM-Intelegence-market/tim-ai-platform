BEGIN;
CREATE TABLE IF NOT EXISTS orderflow_observations (
    observation_id TEXT PRIMARY KEY, kind TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL, summary TEXT NOT NULL,
    evidence JSONB NOT NULL CHECK (jsonb_array_length(evidence) >= 2),
    rule_version TEXT NOT NULL CHECK (rule_version = '1.0.0'),
    input_hash TEXT NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    provenance TEXT NOT NULL CHECK (provenance = 'BINANCE_SPOT_AGGTRADE_DETERMINISTIC'),
    mode TEXT NOT NULL CHECK (mode = 'OBSERVE')
);
CREATE INDEX IF NOT EXISTS orderflow_observations_time_idx ON orderflow_observations (symbol, observed_at DESC);
COMMIT;
