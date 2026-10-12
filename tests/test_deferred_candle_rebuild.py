"""Offline rebuild of 1m candles for DEFERRED CANDLE_V1 outbox work.

Pure tests cover the verdict and hash rules. The database tests seed raw trades
through the real store, defer rows the way the live cutover does, and check
that only the planned minutes change: candles appear, DEFERRED rows complete,
active rows, cursor, gap ledger and queue_depth stay as they were.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from src.data_ingestion import deferred_candles as module
from src.data_ingestion.deferred_candles import (
    BLOCKER_DEFERRED_WORK,
    BLOCKER_LIVE_WORK,
    BLOCKER_NOT_CLOSED,
    BLOCKER_OPEN_GAP,
    METRIC_REBUILT_CANDLES,
    METRIC_REBUILT_ITEMS,
    METRIC_UNCANDLED_CANDLES,
    SCOPE_UNCANDLED,
    candle_output_hash,
    classify_minute,
    closed_before,
    rebuild_deferred_candles,
    rebuild_uncandled_candles,
)
from src.data_ingestion.durable import DurableIngestionStore
from src.database.connection import Database
from src.models.market_data import Candle, Trade


UTC = timezone.utc
NOW = datetime(2026, 10, 12, 12, 0, 30, tzinfo=UTC)


def test_closed_before_keeps_the_safety_margin_away_from_the_live_minute() -> None:
    # 12:00:30 minus 120 s is 11:58:30, whose minute is 11:58; the last closed minute is 11:57.
    assert closed_before(NOW, 120) == datetime(2026, 10, 12, 11, 57, tzinfo=UTC)
    assert closed_before(NOW, 0) == datetime(2026, 10, 12, 11, 59, tzinfo=UTC)
    with pytest.raises(ValueError):
        closed_before(NOW, -1)


def _plan(**overrides):
    values = dict(
        symbol="BTCUSDT", open_time=datetime(2026, 10, 12, 11, 0, tzinfo=UTC), deferred_items=3,
        active_items=0, completed_items=0, raw_trades=3, min_trade_id=10, max_trade_id=12,
        open_gaps=0, closed_through=datetime(2026, 10, 12, 11, 57, tzinfo=UTC),
    )
    values.update(overrides)
    return classify_minute(**values)


def test_classify_minute_orders_blockers_and_accepts_a_clean_closed_minute() -> None:
    assert _plan().blocker is None and _plan().rebuildable
    assert _plan(open_time=datetime(2026, 10, 12, 11, 58, tzinfo=UTC)).blocker == BLOCKER_NOT_CLOSED
    assert _plan(active_items=1).blocker == BLOCKER_LIVE_WORK
    assert _plan(open_gaps=1).blocker == BLOCKER_OPEN_GAP
    # Not closed wins over everything else: the live minute is never touched.
    assert _plan(open_time=datetime(2026, 10, 12, 11, 58, tzinfo=UTC), active_items=1, open_gaps=1).blocker == BLOCKER_NOT_CLOSED
    with pytest.raises(ValueError):
        _plan(deferred_items=0)


def test_classify_uncandled_minute_sends_deferred_work_to_the_other_scope() -> None:
    clean = _plan(deferred_items=0, scope=SCOPE_UNCANDLED)
    assert clean.blocker is None
    assert _plan(deferred_items=1, scope=SCOPE_UNCANDLED).blocker == BLOCKER_DEFERRED_WORK
    assert _plan(deferred_items=1, active_items=1, scope=SCOPE_UNCANDLED).blocker == BLOCKER_LIVE_WORK
    assert _plan(deferred_items=0, open_gaps=1, scope=SCOPE_UNCANDLED).blocker == BLOCKER_OPEN_GAP
    with pytest.raises(ValueError):
        _plan(scope="SOMETHING_ELSE")
    with pytest.raises(ValueError):
        _plan(deferred_items=0, raw_trades=0, scope=SCOPE_UNCANDLED)


def test_output_hash_is_deterministic_and_bound_to_the_candle_and_rebuild_version() -> None:
    open_time = datetime(2026, 10, 12, 11, 0, tzinfo=UTC)
    first = Candle("BTCUSDT", "1m", open_time, open_time + timedelta(minutes=1), 100.0, 101.0, 99.0, 100.5, 3.0, 4)
    same = Candle("BTCUSDT", "1m", open_time, open_time + timedelta(minutes=1), 100.0, 101.0, 99.0, 100.5, 3.0, 4)
    other = Candle("BTCUSDT", "1m", open_time, open_time + timedelta(minutes=1), 100.0, 101.0, 99.0, 100.5, 3.0, 5)
    assert candle_output_hash(first) == candle_output_hash(same)
    assert candle_output_hash(first) != candle_output_hash(other)
    assert len(candle_output_hash(first)) == 64 and candle_output_hash(first).islower()
    assert module.REBUILD_VERSION == "DEFERRED_CANDLE_REBUILD_V1"


# --- database-backed tests -------------------------------------------------

DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
database_only = pytest.mark.skipif(not DATABASE_URL, reason="isolated durable-ingestion PostgreSQL URL not provided")
SYMBOL = "DEFERREDC"
BASE = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(hours=3)
TABLES = ("candles", "ingestion_outbox", "ingestion_gap_incidents", "ingestion_cursors", "ingestion_metrics", "agg_trades")


def trade(trade_id: int, minute: int, second: int, price: float, quantity: float = 0.5) -> Trade:
    return Trade(SYMBOL, price, quantity, BASE + timedelta(minutes=minute, seconds=second), trade_id, False)


@pytest_asyncio.fixture
async def database():
    assert DATABASE_URL is not None
    value = Database(DATABASE_URL, min_size=1, max_size=3)
    await value.connect()
    await value.initialize_schema()
    await _clean(value)
    yield value
    await _clean(value)
    await value.close()


async def _clean(value: Database) -> None:
    async with value.acquire() as connection:
        for table in TABLES:
            if table == "ingestion_metrics":
                await connection.execute("DELETE FROM ingestion_metrics")
            else:
                await connection.execute(f"DELETE FROM {table} WHERE symbol=$1", SYMBOL)


async def seed(database: Database) -> DurableIngestionStore:
    """Three minutes of raw trades; minutes 0 and 1 are deferred like a cutover does it, minute 2 stays live."""
    store = DurableIngestionStore(database, queue_capacity=1_000)
    trades = [
        trade(100, 0, 5, 100.0), trade(101, 0, 20, 102.0, 1.0), trade(102, 0, 50, 99.0),
        trade(103, 1, 10, 99.5), trade(104, 1, 40, 101.5),
        trade(105, 2, 0, 101.0), trade(106, 2, 30, 100.0),
    ]
    for item in trades:
        result = await store.ingest_trade(item)
        assert result.raw_inserted and result.outbox_inserted
    async with database.acquire() as connection:
        deferred = await connection.execute(
            """UPDATE ingestion_outbox SET status='DEFERRED',last_error='deferred by live cutover TEST',updated_at=clock_timestamp()
               WHERE symbol=$1 AND worker_name='CANDLE_V1' AND aggregate_trade_id<=104""",
            SYMBOL,
        )
        assert deferred == "UPDATE 5"
        await connection.execute(
            "INSERT INTO ingestion_metrics(metric_name,metric_kind,numeric_value) VALUES('queue_depth','GAUGE',2) ON CONFLICT(metric_name) DO UPDATE SET numeric_value=2"
        )
    return store


async def outbox_rows(database: Database) -> dict[int, dict]:
    async with database.acquire() as connection:
        rows = await connection.fetch(
            "SELECT aggregate_trade_id,status,output_hash,completed_at,last_error FROM ingestion_outbox WHERE symbol=$1 AND worker_name='CANDLE_V1' ORDER BY aggregate_trade_id",
            SYMBOL,
        )
    return {int(row["aggregate_trade_id"]): dict(row) for row in rows}


async def candles(database: Database) -> list[dict]:
    async with database.acquire() as connection:
        rows = await connection.fetch(
            "SELECT open_time,close_time,open,high,low,close,volume,trade_count,closed FROM candles WHERE symbol=$1 AND timeframe='1m' ORDER BY open_time",
            SYMBOL,
        )
    return [dict(row) for row in rows]


async def metric(database: Database, name: str) -> float | None:
    async with database.acquire() as connection:
        return await connection.fetchval("SELECT numeric_value FROM ingestion_metrics WHERE metric_name=$1", name)


@database_only
@pytest.mark.asyncio
async def test_dry_run_plans_deferred_minutes_and_writes_nothing(database) -> None:
    await seed(database)
    before = await outbox_rows(database)
    async with database.acquire() as connection:
        report = await rebuild_deferred_candles(connection, SYMBOL, apply=False)
    assert report.applied is False and report.planned_minutes == 2 and report.blocked_minutes == 0
    assert [(m.status, m.deferred_items, m.raw_trades) for m in report.minutes] == [("PLANNED", 3, 3), ("PLANNED", 2, 2)]
    assert report.deferred_by_worker == {"CANDLE_V1": 5}
    assert await candles(database) == []
    assert await outbox_rows(database) == before
    assert await metric(database, METRIC_REBUILT_ITEMS) is None


@database_only
@pytest.mark.asyncio
async def test_apply_rebuilds_raw_backed_candles_and_completes_only_deferred_rows(database) -> None:
    await seed(database)
    async with database.acquire() as connection:
        cursor_before = await connection.fetchrow("SELECT * FROM ingestion_cursors WHERE symbol=$1", SYMBOL)
        report = await rebuild_deferred_candles(connection, SYMBOL, apply=True)
        cursor_after = await connection.fetchrow("SELECT * FROM ingestion_cursors WHERE symbol=$1", SYMBOL)
    assert (report.rebuilt_minutes, report.rebuilt_items, report.blocked_minutes, report.conflict_minutes) == (2, 5, 0, 0)
    assert (report.candles_inserted, report.candles_updated, report.candles_unchanged) == (2, 0, 0)
    assert report.live_queue_mutations == 0 and report.gap_ledger_mutations == 0 and report.trading_actions == 0

    built = await candles(database)
    assert [c["open_time"] for c in built] == [BASE, BASE + timedelta(minutes=1)]
    first = built[0]
    assert (first["open"], first["high"], first["low"], first["close"]) == (100.0, 102.0, 99.0, 99.0)
    assert (first["volume"], first["trade_count"], first["closed"]) == (2.0, 3, True)
    assert first["close_time"] == BASE + timedelta(minutes=1)
    second = built[1]
    assert (second["open"], second["high"], second["low"], second["close"], second["trade_count"]) == (99.5, 101.5, 99.5, 101.5, 2)

    rows = await outbox_rows(database)
    for trade_id in (100, 101, 102, 103, 104):
        assert rows[trade_id]["status"] == "COMPLETED"
        assert rows[trade_id]["completed_at"] is not None and rows[trade_id]["last_error"] is None
    assert len({rows[i]["output_hash"] for i in (100, 101, 102)}) == 1
    assert rows[100]["output_hash"] != rows[103]["output_hash"]
    assert rows[100]["output_hash"] == report.minutes[0].output_hash
    # Live rows of minute 2 and the cursor are untouched; queue_depth only counts active rows.
    assert rows[105]["status"] == "PENDING" and rows[106]["status"] == "PENDING"
    assert dict(cursor_after) == dict(cursor_before)
    assert await metric(database, "queue_depth") == 2
    assert await metric(database, METRIC_REBUILT_ITEMS) == 5
    assert await metric(database, METRIC_REBUILT_CANDLES) == 2


@database_only
@pytest.mark.asyncio
async def test_rerun_after_apply_has_nothing_left_and_stays_idempotent(database) -> None:
    await seed(database)
    async with database.acquire() as connection:
        first = await rebuild_deferred_candles(connection, SYMBOL, apply=True)
        candles_after_first = await candles(database)
        second = await rebuild_deferred_candles(connection, SYMBOL, apply=True)
    assert first.rebuilt_minutes == 2
    assert second.planned_minutes == 0 and second.rebuilt_minutes == 0 and second.deferred_by_worker == {}
    assert await candles(database) == candles_after_first
    assert await metric(database, METRIC_REBUILT_ITEMS) == 5


@database_only
@pytest.mark.asyncio
async def test_minute_with_live_work_is_blocked_and_untouched(database) -> None:
    await seed(database)
    async with database.acquire() as connection:
        # One row of minute 0 is still live (RETRY): the whole minute belongs to the worker.
        await connection.execute(
            "UPDATE ingestion_outbox SET status='RETRY' WHERE symbol=$1 AND worker_name='CANDLE_V1' AND aggregate_trade_id=101", SYMBOL
        )
        report = await rebuild_deferred_candles(connection, SYMBOL, apply=True)
    assert report.planned_minutes == 2 and report.rebuilt_minutes == 1 and report.blocked_minutes == 1
    assert report.minutes[0].status == "BLOCKED" and report.minutes[0].blocker == BLOCKER_LIVE_WORK
    rows = await outbox_rows(database)
    assert rows[100]["status"] == "DEFERRED" and rows[101]["status"] == "RETRY" and rows[102]["status"] == "DEFERRED"
    assert rows[103]["status"] == "COMPLETED" and rows[104]["status"] == "COMPLETED"
    assert [c["open_time"] for c in await candles(database)] == [BASE + timedelta(minutes=1)]


@database_only
@pytest.mark.asyncio
async def test_open_gap_next_to_the_minute_blocks_it_until_the_gap_is_resolved(database) -> None:
    store = await seed(database)
    # IDs 103..104 exist; a missing trade right before 103 could still belong to minute 1.
    gap_id = await store.record_gap(symbol=SYMBOL, missing_from_id=102, missing_to_id=102, reason="TEST_GAP")
    async with database.acquire() as connection:
        # record_gap lands on an already persisted id here; the ledger, not the raw table, is what blocks.
        blocked = await rebuild_deferred_candles(connection, SYMBOL, apply=True)
        assert blocked.planned_minutes == 2 and blocked.blocked_minutes == 2 and blocked.rebuilt_minutes == 0
        assert {m.blocker for m in blocked.minutes} == {BLOCKER_OPEN_GAP}
        assert await candles(database) == []
        await connection.execute("UPDATE ingestion_gap_incidents SET status='RESOLVED',resolved_at=clock_timestamp() WHERE gap_id=$1", gap_id)
        resolved = await rebuild_deferred_candles(connection, SYMBOL, apply=True)
    assert resolved.rebuilt_minutes == 2 and resolved.blocked_minutes == 0


@database_only
@pytest.mark.asyncio
async def test_time_spanning_gap_blocks_only_the_minutes_it_overlaps(database) -> None:
    store = await seed(database)
    # A gap recorded far away in trade ids but whose time span covers minute 1 only.
    await store.record_gap(symbol=SYMBOL, missing_from_id=900, missing_to_id=950, reason="TRADE_ID_GAP")
    async with database.acquire() as connection:
        await connection.execute(
            "UPDATE ingestion_gap_incidents SET gap_started_at=$2,gap_ended_at=$3 WHERE symbol=$1 AND missing_from_id=900",
            SYMBOL, BASE + timedelta(minutes=1, seconds=20), BASE + timedelta(minutes=1, seconds=45),
        )
        report = await rebuild_deferred_candles(connection, SYMBOL, apply=True)
    assert [(m.status, m.blocker) for m in report.minutes] == [("REBUILT", None), ("BLOCKED", BLOCKER_OPEN_GAP)]


@database_only
@pytest.mark.asyncio
async def test_recent_minute_inside_the_safety_margin_is_not_closed_yet(database) -> None:
    await seed(database)
    async with database.acquire() as connection:
        # Pretend "now" is 30 s after minute 1 opened: minute 0 is closed, minute 1 is not.
        report = await rebuild_deferred_candles(connection, SYMBOL, apply=True, now=BASE + timedelta(minutes=1, seconds=30), safety_seconds=0)
    assert [(m.status, m.blocker) for m in report.minutes] == [("REBUILT", None), ("BLOCKED", BLOCKER_NOT_CLOSED)]


@database_only
@pytest.mark.asyncio
async def test_existing_partial_candle_is_replaced_by_the_raw_backed_one(database) -> None:
    await seed(database)
    async with database.acquire() as connection:
        await connection.execute(
            """INSERT INTO candles(symbol,timeframe,open_time,close_time,open,high,low,close,volume,trade_count,closed)
               VALUES($1,'1m',$2,$3,100.0,100.0,100.0,100.0,0.5,1,false)""",
            SYMBOL, BASE, BASE + timedelta(minutes=1),
        )
        report = await rebuild_deferred_candles(connection, SYMBOL, apply=True)
    assert (report.candles_inserted, report.candles_updated, report.candles_unchanged) == (1, 1, 0)
    assert report.minutes[0].candle_action == "UPDATED"
    first = (await candles(database))[0]
    assert (first["high"], first["low"], first["trade_count"], first["closed"]) == (102.0, 99.0, 3, True)


@database_only
@pytest.mark.asyncio
async def test_deferred_rows_of_other_workers_are_reported_but_never_touched(database) -> None:
    await seed(database)
    async with database.acquire() as connection:
        await connection.execute(
            """INSERT INTO ingestion_outbox(outbox_id,worker_name,idempotency_key,source,market,symbol,data_type,aggregate_trade_id,input_hash,worker_version,status)
               VALUES(repeat('b',64),'FEATURE_V1',repeat('c',64),'BINANCE','SPOT',$1,'AGG_TRADE',100,repeat('d',64),'1.0.0','DEFERRED')""",
            SYMBOL,
        )
        report = await rebuild_deferred_candles(connection, SYMBOL, apply=True)
        feature_status = await connection.fetchval("SELECT status FROM ingestion_outbox WHERE worker_name='FEATURE_V1' AND symbol=$1", SYMBOL)
    assert report.deferred_by_worker == {"CANDLE_V1": 5, "FEATURE_V1": 1}
    assert report.rebuilt_minutes == 2 and feature_status == "DEFERRED"


@database_only
@pytest.mark.asyncio
async def test_max_minutes_bounds_one_run_oldest_first(database) -> None:
    await seed(database)
    async with database.acquire() as connection:
        report = await rebuild_deferred_candles(connection, SYMBOL, apply=True, max_minutes=1)
    assert report.planned_minutes == 1 and report.rebuilt_minutes == 1
    assert [c["open_time"] for c in await candles(database)] == [BASE]
    rows = await outbox_rows(database)
    assert rows[103]["status"] == "DEFERRED" and rows[104]["status"] == "DEFERRED"


# --- second scope: raw trades without any outbox work ----------------------

async def seed_uncandled(database: Database) -> None:
    """Minutes 10 and 11 reach agg_trades directly (like a promoted offline candidate): no outbox rows."""
    async with database.acquire() as connection:
        rows = [
            (SYMBOL, 700, BASE + timedelta(minutes=10, seconds=5), 90.0, 0.5, False, "BINANCE_SPOT_AGGTRADE"),
            (SYMBOL, 701, BASE + timedelta(minutes=10, seconds=40), 91.0, 1.5, True, "BINANCE_SPOT_AGGTRADE"),
            (SYMBOL, 702, BASE + timedelta(minutes=11, seconds=1), 89.0, 0.5, False, "BINANCE_SPOT_AGGTRADE"),
        ]
        await connection.executemany(
            "INSERT INTO agg_trades(symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker,source) VALUES($1,$2,$3,$4,$5,$6,$7)",
            rows,
        )


@database_only
@pytest.mark.asyncio
async def test_uncandled_scope_builds_candles_for_minutes_without_outbox_rows_only(database) -> None:
    await seed(database)             # minutes 0,1 deferred; minute 2 live
    await seed_uncandled(database)   # minutes 10,11 without outbox rows
    async with database.acquire() as connection:
        report = await rebuild_uncandled_candles(connection, SYMBOL, apply=True, window_start=BASE - timedelta(hours=1))
        outbox_statuses = await connection.fetch(
            "SELECT status, count(*) AS n FROM ingestion_outbox WHERE symbol=$1 GROUP BY status ORDER BY status", SYMBOL
        )
    # Minutes 0 and 1 are blocked (deferred work belongs to the other scope), minute 2 is blocked by live work,
    # minutes 10 and 11 are rebuilt.
    assert report.scope == SCOPE_UNCANDLED and report.planned_minutes == 5
    assert [(m.status, m.blocker) for m in report.minutes] == [
        ("BLOCKED", BLOCKER_DEFERRED_WORK), ("BLOCKED", BLOCKER_DEFERRED_WORK), ("BLOCKED", BLOCKER_LIVE_WORK),
        ("REBUILT", None), ("REBUILT", None),
    ]
    assert report.rebuilt_minutes == 2 and report.rebuilt_items == 0 and report.candles_inserted == 2
    built = await candles(database)
    assert [c["open_time"] for c in built] == [BASE + timedelta(minutes=10), BASE + timedelta(minutes=11)]
    assert (built[0]["open"], built[0]["high"], built[0]["low"], built[0]["close"], built[0]["volume"], built[0]["trade_count"]) == (90.0, 91.0, 90.0, 91.0, 2.0, 2)
    # No outbox row was created or changed.
    assert [(r["status"], int(r["n"])) for r in outbox_statuses] == [("DEFERRED", 5), ("PENDING", 2)]
    assert await metric(database, METRIC_UNCANDLED_CANDLES) == 2
    assert await metric(database, METRIC_REBUILT_ITEMS) is None


@database_only
@pytest.mark.asyncio
async def test_uncandled_scope_dry_run_and_window_bounds(database) -> None:
    await seed_uncandled(database)
    async with database.acquire() as connection:
        dry = await rebuild_uncandled_candles(connection, SYMBOL, apply=False, window_start=BASE)
        assert dry.planned_minutes == 2 and dry.rebuilt_minutes == 0 and await candles(database) == []
        # Window ends before minute 11: only minute 10 is in scope.
        narrow = await rebuild_uncandled_candles(
            connection, SYMBOL, apply=True, window_start=BASE, window_end=BASE + timedelta(minutes=11)
        )
        assert [m.open_time for m in narrow.minutes] == [(BASE + timedelta(minutes=10)).isoformat()]
        # A window entirely in the future (after the last closed minute) is empty.
        empty = await rebuild_uncandled_candles(connection, SYMBOL, apply=True, window_start=datetime.now(UTC) + timedelta(hours=1))
        assert empty.planned_minutes == 0
        # Second pass finds only minute 11 and is then idempotent.
        rest = await rebuild_uncandled_candles(connection, SYMBOL, apply=True, window_start=BASE)
        again = await rebuild_uncandled_candles(connection, SYMBOL, apply=True, window_start=BASE)
    assert rest.rebuilt_minutes == 1 and again.planned_minutes == 0
    assert len(await candles(database)) == 2


@database_only
@pytest.mark.asyncio
async def test_uncandled_scope_replaces_an_unclosed_candle_and_respects_open_gaps(database) -> None:
    await seed_uncandled(database)
    store = DurableIngestionStore(database)
    async with database.acquire() as connection:
        await connection.execute(
            """INSERT INTO candles(symbol,timeframe,open_time,close_time,open,high,low,close,volume,trade_count,closed)
               VALUES($1,'1m',$2,$3,90.0,90.0,90.0,90.0,0.5,1,false)""",
            SYMBOL, BASE + timedelta(minutes=10), BASE + timedelta(minutes=11),
        )
        # Missing ids right after 702 could belong to minute 11.
        gap_id = await store.record_gap(symbol=SYMBOL, missing_from_id=703, missing_to_id=710, reason="TRADE_ID_GAP")
        report = await rebuild_uncandled_candles(connection, SYMBOL, apply=True, window_start=BASE)
        assert [(m.status, m.blocker, m.candle_action) for m in report.minutes] == [
            ("REBUILT", None, "UPDATED"), ("BLOCKED", BLOCKER_OPEN_GAP, None),
        ]
        await connection.execute("UPDATE ingestion_gap_incidents SET status='RESOLVED' WHERE gap_id=$1", gap_id)
        resolved = await rebuild_uncandled_candles(connection, SYMBOL, apply=True, window_start=BASE)
    assert resolved.rebuilt_minutes == 1
    first = (await candles(database))[0]
    assert (first["closed"], first["trade_count"], first["high"]) == (True, 2, 91.0)
