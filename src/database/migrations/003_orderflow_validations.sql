BEGIN;
CREATE TABLE IF NOT EXISTS orderflow_validations (
    observation_id TEXT PRIMARY KEY REFERENCES orderflow_observations(observation_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL, observed_at TIMESTAMPTZ NOT NULL, baseline_price DOUBLE PRECISION NOT NULL CHECK (baseline_price > 0),
    horizons JSONB NOT NULL, complete BOOLEAN NOT NULL, outcome TEXT CHECK (outcome IN ('PRICE_INCREASED','PRICE_DECREASED','PRICE_SIDEWAYS')),
    validation_hash TEXT NOT NULL CHECK (validation_hash ~ '^[0-9a-f]{64}$'), validated_through TIMESTAMPTZ NOT NULL,
    validation_version TEXT NOT NULL CHECK (validation_version='1.0.0'), mode TEXT NOT NULL CHECK (mode='OBSERVE')
);
CREATE INDEX IF NOT EXISTS orderflow_validations_time_idx ON orderflow_validations(symbol,validated_through DESC);
COMMIT;
