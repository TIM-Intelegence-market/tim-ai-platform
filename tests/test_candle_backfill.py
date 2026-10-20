"""Governed 1m candle backfill: only ID-complete raw minutes, dry run writes nothing."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from scripts.tim_candle_backfill import parse_args
from src.operational.candle_backfill import (
    Governance,
    parse_utc,
    run_backfill,
    validate_window,
)

SYMBOL = "BACKFILLTEST"
START = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
GOV = Governance("Uzi", "decision-card-test", "2026-10-20T11:10:19Z")


def test_window_and_governance_guards() -> None:
    with pytest.raises(ValueError, match="after start"):
        validate_window(START, START, NOW)
    with pytest.raises(ValueError, match="settled"):
        validate_window(START, NOW - timedelta(minutes=1), NOW)
    with pytest.raises(ValueError, match="split"):
        validate_window(START, START + timedelta(days=31), NOW)
    with pytest.raises(ValueError, match="minute-aligned"):
        validate_window(START + timedelta(seconds=5), START + timedelta(minutes=5), NOW)
    with pytest.raises(ValueError, match="trailing Z"):
        parse_utc("2026-10-01T00:00:00")
    with pytest.raises(ValueError, match="approved_by"):
        Governance(" ", "x", "2026-10-20T11:10:19Z").validate()
    with pytest.raises(SystemExit):
        parse_args(["--start", "2026-10-01T00:00:00Z", "--end", "2026-10-02T00:00:00Z", "--apply"])
    assert parse_args(["--start", "2026-10-01T00:00:00Z", "--end", "2026-10-02T00:00:00Z"]).apply is False


async def _seed(connection) -> None:
    # Minute 0: valid candle exists. Minutes 1 and 2: trades only (PARTIAL_WRITE).
    # Minute 3: trade 8 missing, so the raw ID range is incomplete. Minute 4: boundary trade.
    trades = [(1, 0, 100.0), (2, 0, 101.0), (3, 1, 102.0), (4, 1, 99.0), (5, 1, 100.5),
              (6, 2, 103.0), (7, 3, 104.0), (9, 3, 104.5), (10, 4, 105.0)]
    for trade_id, minute, price in trades:
        await connection.execute(
            """INSERT INTO agg_trades(symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker,source)
               VALUES($1,$2,$3,$4,$5,false,'BINANCE_SPOT_AGGTRADE')""",
            SYMBOL, trade_id, START + timedelta(minutes=minute, seconds=trade_id), price, 0.5,
        )
    await connection.execute(
        """INSERT INTO candles(symbol,timeframe,open_time,close_time,open,high,low,close,volume,trade_count,closed)
           VALUES($1,'1m',$2,$3,100,101,100,101,1.0,2,true)""", SYMBOL, START, START + timedelta(minutes=1),
    )


@pytest.mark.asyncio
async def test_backfill_rebuilds_only_complete_minutes() -> None:
    url = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("isolated durable-ingestion PostgreSQL URL not provided")
    from src.database.connection import Database

    database = Database(url, min_size=1, max_size=1)
    await database.connect()
    await database.initialize_schema()
    end = START + timedelta(minutes=4)
    hashes = {"x": "y"}
    try:
        async with database.acquire() as connection:
            await connection.execute("DELETE FROM candles WHERE symbol=$1", SYMBOL)
            await connection.execute("DELETE FROM agg_trades WHERE symbol=$1", SYMBOL)
            await _seed(connection)

        dry = await run_backfill(database, SYMBOL, START, end, now=NOW, apply=False, governance=None, code_hashes=hashes)
        assert dry["mode"] == "DRY_RUN" and dry["trading_actions"] == 0
        assert dry["totals"]["missing_before"] == 3 and dry["totals"]["rebuilt"] == 2
        assert dry["totals"]["missing_after"] == 3
        async with database.acquire() as connection:
            assert await connection.fetchval("SELECT count(*) FROM candles WHERE symbol=$1", SYMBOL) == 1

        with pytest.raises(ValueError, match="governance"):
            await run_backfill(database, SYMBOL, START, end, now=NOW, apply=True, governance=None, code_hashes=hashes)

        done = await run_backfill(database, SYMBOL, START, end, now=NOW, apply=True, governance=GOV, code_hashes=hashes)
        assert done["governance"]["approved_by"] == "Uzi"
        assert done["totals"]["rebuilt"] == 2 and done["totals"]["missing_after"] == 1
        proofs = {proof["minute"]: proof for proof in done["proofs"]}
        first = proofs[(START + timedelta(minutes=1)).isoformat()]
        assert (first["status"], first["first_id"], first["last_id"], first["trade_count"]) == ("REBUILT", 3, 5, 3)
        assert first["prior_row_hash"] is None and len(first["candle_hash"]) == 64
        assert proofs[(START + timedelta(minutes=3)).isoformat()]["status"] == "WAIT_RAW"
        assert len(done["manifest_sha256"]) == 64
        async with database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT open,high,low,close,volume,trade_count FROM candles WHERE symbol=$1 AND open_time=$2",
                SYMBOL, START + timedelta(minutes=1))
            assert tuple(row) == (102.0, 102.0, 99.0, 100.5, 1.5, 3)
            assert await connection.fetchval(
                "SELECT count(*) FROM candles WHERE symbol=$1 AND open_time=$2", SYMBOL, START + timedelta(minutes=3)) == 0

        again = await run_backfill(database, SYMBOL, START, end, now=NOW, apply=True, governance=GOV, code_hashes=hashes)
        assert again["totals"]["missing_before"] == 1 and again["totals"]["rebuilt"] == 0
    finally:
        async with database.acquire() as connection:
            await connection.execute("DELETE FROM candles WHERE symbol=$1", SYMBOL)
            await connection.execute("DELETE FROM agg_trades WHERE symbol=$1", SYMBOL)
        await database.close()


def test_lock_wait_retries_until_the_timer_releases(tmp_path) -> None:
    import fcntl

    from scripts.tim_candle_backfill import acquire_lock

    path = tmp_path / "history_recovery.lock"
    holder = path.open("a")
    fcntl.flock(holder, fcntl.LOCK_EX)
    waiter = path.open("a")
    ticks = iter(range(100))

    def release_on_third_sleep(_: float) -> None:
        if next(ticks) == 2:
            fcntl.flock(holder, fcntl.LOCK_UN)

    assert acquire_lock(waiter, 60, clock=lambda: 0.0, sleep=release_on_third_sleep) is True
    other = path.open("a")
    assert acquire_lock(other, 0, sleep=lambda _: None) is False
    for handle in (holder, waiter, other):
        handle.close()
