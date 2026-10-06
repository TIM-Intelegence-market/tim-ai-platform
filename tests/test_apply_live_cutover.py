import asyncio
import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("apply_live_cutover", ROOT / "scripts/apply_live_cutover.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Stop(Exception):
    pass


@pytest.mark.parametrize("timeout", [None, 42.0])
def test_cutover_connection_uses_a_long_statement_timeout(monkeypatch, tmp_path, timeout):
    # tim-core-01: deferring 50k pending rows in a 15M-row outbox took longer than 60 s.
    module = load()
    seen = {}

    async def fake_connect(*args, **kwargs):
        seen.update(kwargs)
        raise Stop

    monkeypatch.setattr(module.asyncpg, "connect", fake_connect)
    monkeypatch.setattr(module, "settings", SimpleNamespace(database_url="postgresql://tim@127.0.0.1/tim", symbol="BTCUSDT"))
    call = module.run(True, tmp_path / "out.json") if timeout is None else module.run(True, tmp_path / "out.json", timeout)
    with pytest.raises(Stop):
        asyncio.run(call)
    assert seen["command_timeout"] == (module.DEFAULT_COMMAND_TIMEOUT if timeout is None else timeout)
    assert module.DEFAULT_COMMAND_TIMEOUT >= 900


def test_cutover_still_refuses_without_apply(tmp_path):
    result = asyncio.run(load().run(False, tmp_path / "out.json"))
    assert result["status"] == "REFUSED" and result["trading_actions"] == 0


DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
SYMBOL = "CUTOVERQ"


@pytest.mark.asyncio
async def test_cutover_defers_a_quarantined_historical_head(monkeypatch, tmp_path):
    # tim-core-01, 2026-10-06: a QUARANTINED row below the baseline survived the
    # cutover and kept the strict-order CANDLE_V1 worker TERMINAL_BLOCKED.
    if not DATABASE_URL:
        pytest.skip("isolated durable-ingestion PostgreSQL URL not provided")
    from src.data_ingestion.durable import DurableIngestionStore
    from src.database.connection import Database
    from src.models.market_data import Trade

    database = Database(DATABASE_URL, min_size=1, max_size=3)
    await database.connect()
    await database.initialize_schema()

    async def wipe():
        async with database.acquire() as connection:
            for table in ("ingestion_outbox", "ingestion_gap_incidents", "ingestion_cursors", "agg_trades"):
                await connection.execute(f"DELETE FROM {table} WHERE symbol=$1", SYMBOL)
            if await connection.fetchval("SELECT to_regclass('live_cutover_receipts')"):
                await connection.execute("DELETE FROM live_cutover_receipts WHERE symbol=$1", SYMBOL)

    module = load()
    try:
        await wipe()
        store = DurableIngestionStore(database, queue_capacity=10_000)
        base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
        for trade_id in range(10, 15):
            await store.ingest_trade(Trade(SYMBOL, 100.0, 0.25, base + timedelta(milliseconds=trade_id), trade_id, False))
        async with database.acquire() as connection:
            await connection.execute(
                """UPDATE ingestion_outbox SET status='QUARANTINED',attempts=5,last_error='TimeoutError'
                   WHERE symbol=$1 AND worker_name='CANDLE_V1' AND aggregate_trade_id=10""", SYMBOL)
        blocked = await store.claim_detailed("CANDLE_V1", limit=10, strict_order=True)
        assert blocked.status == "TERMINAL_BLOCKED"

        async def first_live():
            return 20

        monkeypatch.setattr(module, "first_live_trade_id", first_live)
        monkeypatch.setattr(module, "settings", SimpleNamespace(database_url=DATABASE_URL, symbol=SYMBOL))
        result = await module.run(True, tmp_path / "out.json")
        assert result["status"] == "APPLIED" and result["baseline_cursor_id"] == 14

        async with database.acquire() as connection:
            row = await connection.fetchrow(
                """SELECT status,last_error FROM ingestion_outbox
                   WHERE symbol=$1 AND worker_name='CANDLE_V1' AND aggregate_trade_id=10""", SYMBOL)
        assert row["status"] == "DEFERRED"
        assert "was QUARANTINED: TimeoutError" in row["last_error"]

        await store.ingest_trade(Trade(SYMBOL, 100.0, 0.25, base + timedelta(milliseconds=20), 20, False))
        claim = await store.claim_detailed("CANDLE_V1", limit=10, strict_order=True)
        assert claim.status == "CLAIMED"
        assert [item.aggregate_trade_id for item in claim.items if item.symbol == SYMBOL] == [20]
    finally:
        await wipe()
        await database.close()
