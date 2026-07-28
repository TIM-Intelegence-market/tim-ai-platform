BEGIN;
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
COMMIT;
