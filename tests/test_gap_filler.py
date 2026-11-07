"""Issue #82: large gaps no longer block live data; the background filler closes them.

Unit tests use fakes. The PostgreSQL tests (TIM_DURABLE_TEST_DATABASE_URL) replay the
02.11.2026 situation at small scale: a gap too large for the inline budget, live trades
accepted at once, then the filler closes the gap behind the cursor and rebuilds the candles.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio

from src.data_ingestion.catchup import CatchUpCoordinator, CatchUpResult, HttpResponse, PublicBinanceAggTradeClient
from src.data_ingestion.durable import DurableIngestionError
from src.data_ingestion.gap_filler import GapFiller
from src.data_ingestion.ingress import DurableIngress
from src.models.market_data import Trade

NOW = datetime.now(timezone.utc)


def live(trade_id: int, symbol: str = "BTCUSDT") -> Trade:
    return Trade(symbol, 100.0, 0.5, NOW, trade_id, False)


# --- ingress: defer instead of blocking ---------------------------------------------------------------


class IngressStore:
    def __init__(self, cursor_id: int) -> None:
        self.cursor = SimpleNamespace(last_aggregate_trade_id=cursor_id)
        self.ingested: list[int] = []
        self.metrics: list[str] = []

    async def get_cursor(self, _symbol):
        return self.cursor

    async def approved_live_cutover(self, *_args):
        return False

    async def ingest_trade(self, trade):
        self.ingested.append(trade.trade_id)
        self.cursor.last_aggregate_trade_id = max(self.cursor.last_aggregate_trade_id, trade.trade_id)
        return SimpleNamespace(raw_inserted=True, duplicate=False)

    async def record_metric(self, name, *_args, **_kwargs):
        self.metrics.append(name)


class SlowCatchUp:
    """Never finishes: like the 02.11. catch-up at 25 trades/s against a growing gap."""

    def __init__(self) -> None:
        self.calls = 0
        self.cancelled = 0

    async def recover_before(self, *_args, **_kwargs):
        self.calls += 1
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


class IncompleteCatchUp:
    async def recover_before(self, symbol, next_id, **_kwargs):
        return CatchUpResult("OPEN", symbol, 1, next_id - 1, 0, 0, 100, "bounded catch-up page limit 100 reached")


@pytest.mark.asyncio
async def test_resume_hands_a_slow_gap_to_the_background_within_the_budget() -> None:
    store, catchup = IngressStore(100), SlowCatchUp()
    ingress = DurableIngress(store, catchup=catchup, defer_incomplete_gaps=True, inline_budget_seconds=0.05)
    started = time.monotonic()
    await ingress.recover_before_resume(live(5_000_000))
    assert time.monotonic() - started < 2
    assert catchup.cancelled == 1
    assert "gap_deferred_to_background_total" in store.metrics
    # The first live trade goes straight in (ingest_trade records the OPEN gap); no second catch-up.
    await ingress(live(5_000_000))
    await ingress(live(5_000_001))
    assert store.ingested == [5_000_000, 5_000_001]
    assert catchup.calls == 1


@pytest.mark.asyncio
async def test_same_connection_gap_is_deferred_after_an_incomplete_catch_up() -> None:
    store = IngressStore(100)
    ingress = DurableIngress(store, catchup=IncompleteCatchUp(), defer_incomplete_gaps=True)
    await ingress(live(900_000))
    assert store.ingested == [900_000]
    assert store.metrics.count("gap_deferred_to_background_total") == 1


@pytest.mark.asyncio
async def test_without_deferral_live_stays_blocked_as_before() -> None:
    store = IngressStore(100)
    ingress = DurableIngress(store, catchup=IncompleteCatchUp())
    with pytest.raises(DurableIngestionError, match="live resume blocked"):
        await ingress.recover_before_resume(live(900_000))
    with pytest.raises(DurableIngestionError, match="live trade blocked"):
        await ingress(live(900_000))
    assert store.ingested == []


@pytest.mark.asyncio
async def test_a_new_resume_forgets_an_old_deferral() -> None:
    store, catchup = IngressStore(100), SlowCatchUp()
    ingress = DurableIngress(store, catchup=catchup, defer_incomplete_gaps=True, inline_budget_seconds=0.02)
    await ingress.recover_before_resume(live(1_000))
    ingress.catchup = IncompleteCatchUp()

    class Complete:
        async def recover_before(self, symbol, next_id, **_kwargs):
            store.cursor.last_aggregate_trade_id = next_id - 1
            return CatchUpResult("COMPLETE", symbol, 101, next_id - 1, 1, 0, 1)

    ingress.catchup = Complete()
    await ingress.recover_before_resume(live(2_000))  # closes inline: no deferral pending any more
    assert ingress._deferred_from_live_id is None


def test_budget_must_be_positive() -> None:
    with pytest.raises(ValueError):
        DurableIngress(IngressStore(1), inline_budget_seconds=0)


# --- filler: which gaps, backoff, status ----------------------------------------------------------------


class FillerStore:
    def __init__(self, gaps):
        self.gaps = gaps

    async def open_gaps(self, _symbol, *, limit=100, newest_first=False, **_kwargs):
        rows = [g for g in self.gaps if g["status"] in {"OPEN", "CATCHING_UP"}]
        return rows[:limit]


class ScriptedCoordinator:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls: list[str] = []

    async def recover_open_gap(self, gap):
        self.calls.append(gap["gap_id"])
        status, persisted = self.outcomes[gap["gap_id"]]
        if status == "COMPLETE":
            gap["status"] = "RESOLVED"
        return CatchUpResult(status, "BTCUSDT", gap["missing_from_id"], gap["missing_to_id"], persisted, 0, 1,
                             None if status == "COMPLETE" else "public REST source returned no data for requested range")


def gap(gap_id: str, start=1, end=10, status="OPEN", updated=None) -> dict:
    return {"gap_id": gap_id, "missing_from_id": start, "missing_to_id": end, "status": status,
            "updated_at": updated or NOW - timedelta(hours=1)}


@pytest.mark.asyncio
async def test_filler_skips_unusable_and_busy_gaps(tmp_path) -> None:
    gaps = [gap("ok"), gap("noids", None, None), gap("huge", 1, 500_000_000), gap("busy", status="CATCHING_UP", updated=datetime.now(timezone.utc)),
            gap("stale", status="CATCHING_UP", updated=NOW - timedelta(hours=2))]
    coordinator = ScriptedCoordinator({"ok": ("COMPLETE", 10), "stale": ("COMPLETE", 10)})
    filler = GapFiller(FillerStore(gaps), coordinator, "BTCUSDT", status_path=tmp_path / "gap_filler.json")
    report = await filler.run_once()
    assert coordinator.calls == ["ok", "stale"]
    assert filler.status.too_large_gaps == 1
    assert report.resolved == 2 and report.persisted == 20
    status = json.loads((tmp_path / "gap_filler.json").read_text())
    assert status["resolved_total"] == 2 and status["trading_actions"] == 0 and status["mode"] == "OBSERVE"
    assert status["last_progress_at_utc"]


@pytest.mark.asyncio
async def test_filler_backs_off_a_gap_without_progress_and_continues_partial_ones(tmp_path) -> None:
    clock = [0.0]
    gaps = [gap("dead"), gap("long", 1, 10_000_000)]
    coordinator = ScriptedCoordinator({"dead": ("OPEN", 0), "long": ("OPEN", 200_000)})
    filler = GapFiller(FillerStore(gaps), coordinator, "BTCUSDT", status_path=None, clock=lambda: clock[0])
    first = await filler.run_once()
    assert first.work_left and filler.status.state == "FILLING"
    await filler.run_once()
    assert coordinator.calls == ["dead", "long", "long"]  # dead waits, long continues at once
    clock[0] += 10_000
    await filler.run_once()
    assert coordinator.calls[-2:] == ["dead", "long"]
    assert filler.status.missing_trades == 10 + 10_000_000


@pytest.mark.asyncio
async def test_filler_rebuilds_candles_and_survives_errors(tmp_path) -> None:
    rebuilt = []

    async def rebuilder():
        rebuilt.append(1)
        return 3 if len(rebuilt) == 1 else 0

    filler = GapFiller(FillerStore([]), ScriptedCoordinator({}), "BTCUSDT", candle_rebuilder=rebuilder, status_path=None)
    assert (await filler.run_once()).work_left  # three minutes rebuilt: look again soon
    assert not (await filler.run_once()).work_left
    assert filler.status.candles_rebuilt_total == 3 and filler.status.state == "IDLE"

    class Broken(FillerStore):
        async def open_gaps(self, *_args, **_kwargs):
            raise OSError("database restarting")

    stop = asyncio.Event()
    broken = GapFiller(Broken([]), ScriptedCoordinator({}), "BTCUSDT", status_path=None, idle_seconds=0.01)
    task = asyncio.create_task(broken.run(stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, 2)
    assert broken.status.state == "ERROR" and "database restarting" in broken.status.last_error


# --- PostgreSQL: the 02.11. outage in small -------------------------------------------------------------

DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
BASE = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(hours=3)
SYMBOL = "GAPFILL"


@pytest_asyncio.fixture
async def database():
    if not DATABASE_URL:
        pytest.skip("isolated durable-ingestion PostgreSQL URL not provided")
    from src.database.connection import Database

    value = Database(DATABASE_URL, min_size=1, max_size=4)
    await value.connect()
    await value.initialize_schema()
    from pathlib import Path

    async with value.acquire() as connection:  # live_cutover_receipts (approved_live_cutover reads it)
        await connection.execute((Path(__file__).resolve().parents[1] / "src/database/migrations/006_live_cutover_deferred.sql").read_text())

    async def wipe():
        async with value.acquire() as connection:
            # Outbox rows go first; skipping the per-row FK re-check keeps a 100k-row cleanup fast.
            await connection.execute("SET session_replication_role = replica")
            for table in ("ingestion_outbox", "ingestion_gap_incidents", "ingestion_cursors", "agg_trades", "candles"):
                await connection.execute(f"DELETE FROM {table} WHERE symbol LIKE 'GAPFILL%'", timeout=600)
            await connection.execute("SET session_replication_role = origin")

    await wipe()
    yield value
    await wipe()
    await value.close()


def item(trade_id: int) -> dict:
    # 20 trades per second: 40,000 trades cover about 33 minutes, 100,000 about 83
    return {"a": trade_id, "p": str(100 + trade_id % 7), "q": "0.25",
            "T": int((BASE + timedelta(milliseconds=50 * (trade_id - 1_000))).timestamp() * 1000), "m": trade_id % 2 == 0}


def as_trade(trade_id: int, symbol: str = SYMBOL) -> Trade:
    raw = item(trade_id)
    return Trade(symbol, float(raw["p"]), 0.25, datetime.fromtimestamp(raw["T"] / 1000, timezone.utc), trade_id, raw["m"])


def binance(calls: list[int], delay: float = 0.0):
    async def transport(url, _headers, _timeout):
        query = parse_qs(urlsplit(url).query)
        start, limit = int(query["fromId"][0]), int(query["limit"][0])
        calls.append(start)
        if delay:
            await asyncio.sleep(delay)
        return HttpResponse(200, {}, json.dumps([item(i) for i in range(start, start + limit)]).encode())

    return transport


@pytest.mark.asyncio
async def test_large_gap_live_first_then_filled_in_background(database, tmp_path) -> None:
    from src.data_ingestion.durable import DurableIngestionStore
    from src.data_ingestion.gap_filler import deferred_candle_rebuilder

    store = DurableIngestionStore(database, queue_capacity=1_000_000)
    for trade_id in range(1_000, 1_010):
        await store.ingest_trade(as_trade(trade_id))
    first_live = 41_010  # 40,000 trades missing after the "outage"

    # Inline catch-up as in the runtime, but slowed down: it cannot finish within its budget.
    inline_calls: list[int] = []
    inline = CatchUpCoordinator(store, PublicBinanceAggTradeClient(transport=binance(inline_calls, 0.05), minimum_interval=0),
                                max_pages=100, page_limit=1_000)
    ingress = DurableIngress(store, catchup=inline, defer_incomplete_gaps=True, inline_budget_seconds=0.5)
    started = time.monotonic()
    await ingress.recover_before_resume(as_trade(first_live))
    inline_progress = (await store.get_cursor(SYMBOL)).last_aggregate_trade_id - 1_009
    for trade_id in range(first_live, first_live + 5):
        await ingress(as_trade(trade_id))
    assert time.monotonic() - started < 10
    cursor = await store.get_cursor(SYMBOL)
    assert cursor.last_aggregate_trade_id == first_live + 4  # live data flows again
    async with database.acquire() as connection:
        open_rows = await connection.fetch(
            "SELECT missing_from_id,missing_to_id,status FROM ingestion_gap_incidents WHERE symbol=$1 ORDER BY missing_from_id",
            SYMBOL)
    assert open_rows and all(row["status"] == "OPEN" for row in open_rows)
    assert max(row["missing_to_id"] for row in open_rows) == first_live - 1  # exact IDs on record

    filler_calls: list[int] = []
    filler = GapFiller(
        store,
        CatchUpCoordinator(store, PublicBinanceAggTradeClient(transport=binance(filler_calls), minimum_interval=0),
                           max_pages=200, batch_below_cursor=True),
        SYMBOL,
        candle_rebuilder=deferred_candle_rebuilder(database, SYMBOL),
        status_path=tmp_path / "gap_filler.json",
    )
    for _ in range(20):
        report = await filler.run_once()
        if not report.work_left and filler.status.open_gaps == 0:
            break
    async with database.acquire() as connection:
        still_open = await connection.fetchval(
            "SELECT count(*) FROM ingestion_gap_incidents WHERE symbol=$1 AND status IN ('OPEN','CATCHING_UP')", SYMBOL)
        stored = await connection.fetchval(
            "SELECT count(*) FROM agg_trades WHERE symbol=$1 AND aggregate_trade_id BETWEEN 1000 AND $2", SYMBOL, first_live + 4)
        pending_history = await connection.fetchval(
            "SELECT count(*) FROM ingestion_outbox WHERE symbol=$1 AND aggregate_trade_id<$2 AND status IN ('PENDING','RETRY')",
            SYMBOL, first_live)
        # A minute that still holds live work (here: what the inline catch-up wrote, no candle worker runs in
        # this test) is left to that worker by design; every other filled minute must have been rebuilt.
        deferred_left = await connection.fetchval(
            """SELECT count(*) FROM ingestion_outbox d JOIN agg_trades t USING (symbol,aggregate_trade_id)
               WHERE d.symbol=$1 AND d.status='DEFERRED' AND NOT EXISTS (
                   SELECT 1 FROM ingestion_outbox a JOIN agg_trades at USING (symbol,aggregate_trade_id)
                   WHERE a.symbol=$1 AND a.status IN ('PENDING','RETRY','PROCESSING','QUARANTINED')
                     AND date_trunc('minute', at.trade_time)=date_trunc('minute', t.trade_time))""", SYMBOL)
        candles = await connection.fetch(
            """SELECT open_time,volume,trade_count FROM candles WHERE symbol=$1 AND timeframe='1m'
               AND open_time < $2 ORDER BY open_time""", SYMBOL, BASE + timedelta(milliseconds=50 * (first_live - 1_000)))
        cursor_after = await store.get_cursor(SYMBOL)
    assert still_open == 0
    assert stored == first_live + 5 - 1_000  # every ID, nothing twice
    # Only what the inline catch-up wrote contiguously above the old cursor is live work; nothing the filler wrote.
    assert pending_history <= inline_progress + 10 < 40_000
    assert deferred_left == 0  # all filled minutes got their candle
    assert candles, "rebuilt 1m candles for the filled range"
    rebuilt_trades = sum(row["trade_count"] for row in candles)
    assert rebuilt_trades >= 37_000  # all but the minutes left to the live worker (see deferred_left)
    assert cursor_after.last_aggregate_trade_id == first_live + 4  # the filler never moved the cursor
    assert cursor_after.recovery_state == "NORMAL"
    assert filler.status.open_gaps == 0 and filler.status.state in {"IDLE", "FILLING"}


@pytest.mark.asyncio
async def test_historical_batch_rules(database) -> None:
    from src.data_ingestion.durable import CursorConflictError, DurableIngestionStore, HistoricalBatchError

    store = DurableIngestionStore(database)
    symbol = "GAPFILLB"
    await store.ingest_trade(as_trade(1_000, symbol))
    await store.ingest_trade(as_trade(1_100, symbol))
    with pytest.raises(HistoricalBatchError):
        await store.ingest_historical_batch([as_trade(i, symbol) for i in range(1_090, 1_101)])
    first = await store.ingest_historical_batch([as_trade(i, symbol) for i in range(1_001, 1_051)])
    again = await store.ingest_historical_batch([as_trade(i, symbol) for i in range(1_040, 1_060)])
    assert (first.raw_inserted, first.duplicates) == (50, 0)
    assert (again.raw_inserted, again.duplicates) == (9, 11)
    changed = as_trade(1_045, symbol)
    changed = Trade(symbol, changed.price + 1, changed.quantity, changed.event_time, changed.trade_id, changed.buyer_is_maker)
    with pytest.raises(CursorConflictError):
        await store.ingest_historical_batch([changed])
    async with database.acquire() as connection:
        statuses = await connection.fetch(
            "SELECT status,count(*) FROM ingestion_outbox WHERE symbol=$1 AND aggregate_trade_id BETWEEN 1001 AND 1099 GROUP BY 1",
            symbol)
    assert dict((row["status"], row["count"]) for row in statuses) == {"DEFERRED": 59}
    assert (await store.get_cursor(symbol)).last_aggregate_trade_id == 1_100


@pytest.mark.asyncio
async def test_batch_backfill_is_fast_enough(database) -> None:
    """Measured, not assumed: 100,000 trades behind the cursor, pages of 1,000."""
    from src.data_ingestion.durable import DurableIngestionStore

    store = DurableIngestionStore(database)
    symbol = "GAPFILLC"
    await store.ingest_trade(as_trade(1_000, symbol))
    await store.ingest_trade(as_trade(101_001, symbol))
    gap_id = await store.record_gap(symbol=symbol, missing_from_id=1_001, missing_to_id=101_000, reason="TEST_SPEED")
    coordinator = CatchUpCoordinator(store, PublicBinanceAggTradeClient(transport=binance([]), minimum_interval=0),
                                     max_pages=200, page_limit=1_000, batch_below_cursor=True)
    started = time.monotonic()
    result = await coordinator.recover_open_gap({"gap_id": gap_id, "symbol": symbol, "missing_from_id": 1_001,
                                                 "missing_to_id": 101_000})
    seconds = time.monotonic() - started
    assert result.status == "COMPLETE" and result.persisted == 100_000
    rate = 100_000 / seconds
    print(f"batch backfill: {rate:,.0f} trades/s")
    assert rate > 2_000


@pytest.mark.asyncio
async def test_slow_candle_rebuild_does_not_stop_gap_filling() -> None:
    """Live 07.11.: the DEFERRED inventory ran into the 30 s pool timeout and failed every round."""
    now = [1000.0]
    calls = []

    async def rebuilder():
        calls.append(now[0])
        if len(calls) == 1:
            raise TimeoutError()
        return 0

    filler = GapFiller(FillerStore([]), ScriptedCoordinator({}), "BTCUSDT", candle_rebuilder=rebuilder,
                       status_path=None, clock=lambda: now[0], rebuild_idle_seconds=1800.0)
    report = await filler.run_once()
    assert filler.status.state == "IDLE" and filler.status.last_error is None
    assert filler.status.candle_error.startswith("TimeoutError")
    assert report.candles_rebuilt == 0
    await filler.run_once()
    assert len(calls) == 1  # backing off after the failure
    now[0] += 700.0
    await filler.run_once()
    assert len(calls) == 2 and filler.status.candle_error is None
    now[0] += 60.0
    await filler.run_once()
    assert len(calls) == 2  # nothing rebuilt last time: wait for the idle interval
    now[0] += 1800.0
    await filler.run_once()
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_rebuilder_queries_get_long_timeout() -> None:
    from src.data_ingestion.gap_filler import _LongQueries

    seen = []

    class Connection:
        async def fetch(self, query, *args, timeout=None):
            seen.append(("fetch", timeout))
            return []

        async def fetchrow(self, query, *args, timeout=None):
            seen.append(("fetchrow", timeout))

        async def fetchval(self, query, *args, timeout=None):
            seen.append(("fetchval", timeout))

        async def execute(self, query, *args, timeout=None):
            seen.append(("execute", timeout))

        def transaction(self):
            return "tx"

    view = _LongQueries(Connection(), 600.0)
    await view.fetch("q", 1)
    await view.fetchrow("q")
    await view.fetchval("q")
    await view.execute("q")
    assert view.transaction() == "tx"
    assert seen == [("fetch", 600.0), ("fetchrow", 600.0), ("fetchval", 600.0), ("execute", 600.0)]
