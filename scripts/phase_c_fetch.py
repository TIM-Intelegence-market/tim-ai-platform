"""Phase C — Full 33-day isolated fetch (Jun19-Jul22) with checkpoint, no production writes."""
import asyncio, hashlib, json, sys, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.data_ingestion.catchup import PublicBinanceAggTradeClient

TARGET_FROM = datetime(2026, 6, 19, tzinfo=timezone.utc)
TARGET_TO = datetime(2026, 7, 22, 20, 13, 21, 782000, tzinfo=timezone.utc)
CHECKPOINT = Path("/tmp/phase_c_checkpoint.json")
LOG = Path("/tmp/phase_c_fetch.log")

def checkpoint_state():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"last_id": 3992578124, "pages": 0, "trades": 0, "hash": hashlib.sha256(b"").hexdigest()}

async def main():
    import asyncpg
    pw = (Path.home() / "Library/Application Support/TIM/test-database-password").read_text().strip()
    # verify isolation
    conn = await asyncpg.connect(host="127.0.0.1", port=5433, database="tim_test", user="tim_test", password=pw)
    try:
        db = await conn.fetchval("SELECT current_database()")
        port = await conn.fetchval("SELECT inet_server_port()")
        assert db == "tim_test" and port == 5433, "not isolated"
    finally:
        await conn.close()
    state = checkpoint_state()
    next_id = state["last_id"] + 1
    client = PublicBinanceAggTradeClient()
    total_pages = 0
    total_trades = state["trades"]
    hasher = hashlib.sha256()
    # we don't have previous hash state, use simple count for now
    start = time.time()
    # we will fetch until we reach TARGET_TO timestamp
    while True:
        try:
            trades = await client.fetch("BTCUSDT", next_id, limit=1000)
        except Exception as e:
            print("FETCH_ERROR %s at %d" % (type(e).__name__, next_id), flush=True)
            await asyncio.sleep(5)
            continue
        if not trades:
            break
        # check if first trade beyond TARGET_TO
        if trades[0].event_time >= TARGET_TO:
            break
        # filter to target window
        in_window = [t for t in trades if t.event_time < TARGET_TO]
        if not in_window:
            # beyond window
            break
        # insert into isolated DB
        conn = await asyncpg.connect(host="127.0.0.1", port=5433, database="tim_test", user="tim_test", password=pw)
        try:
            # batch insert
            await conn.executemany(
                "INSERT INTO agg_trades(symbol,price,quantity,trade_time,aggregate_trade_id,buyer_is_maker,source) VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT DO NOTHING",
                [(t.symbol, t.price, t.quantity, t.event_time, t.trade_id, t.buyer_is_maker, "BINANCE_SPOT_AGGTRADE") for t in in_window],
            )
        finally:
            await conn.close()
        total_pages += 1
        total_trades += len(in_window)
        next_id = trades[-1].trade_id + 1
        state.update({"last_id": trades[-1].trade_id, "pages": state["pages"] + 1, "trades": total_trades})
        CHECKPOINT.write_text(json.dumps(state))
        if total_pages % 100 == 0:
            print("PROGRESS pages=%d trades=%d last_id=%d" % (total_pages, total_trades, trades[-1].trade_id), flush=True)
        # check if last trade's time beyond target
        if trades[-1].event_time >= TARGET_TO:
            break
        # stop if we have fetched enough to cover 33 days (approx 48M, but we will stop at TARGET_TO)
        if total_trades > 50000000:
            break
    print("DONE pages=%d trades=%d duration=%.0fs" % (total_pages, total_trades, time.time() - start), flush=True)

if __name__ == "__main__":
    asyncio.run(main())
