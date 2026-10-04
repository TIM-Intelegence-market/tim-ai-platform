"""Catch-up resumes after an interrupted run instead of refetching filled IDs.

A long outage is caught up in several bounded runs.  Each interrupted run leaves
an OPEN gap whose range is already partly persisted.  Re-running catch-up on
such a gap must fetch only the missing IDs, and never jump over the durable
cursor (that would record a spurious TRADE_ID_GAP).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio

from src.data_ingestion.catchup import CatchUpCoordinator, HttpResponse, PublicBinanceAggTradeClient
from src.models.market_data import Trade
from tests.test_public_catchup_v2 import FakeStore, response_item


class ResumableStore(FakeStore):
    """FakeStore plus the read-only range probe of DurableIngestionStore."""

    def __init__(self, cursor_id: int, persisted: set[int]) -> None:
        super().__init__(cursor_id)
        self.persisted = set(persisted)
        self.probe_calls = 0

    async def first_missing_trade_id(self, _symbol, from_id, to_id):
        self.probe_calls += 1
        for trade_id in range(from_id, to_id + 1):
            if trade_id not in self.persisted:
                return trade_id
        return to_id + 1


def recording_transport(calls: list[tuple[int, int]]):
    async def transport(url, _headers, _timeout):
        query = parse_qs(urlsplit(url).query)
        start, limit = int(query["fromId"][0]), int(query["limit"][0])
        calls.append((start, limit))
        return HttpResponse(200, {}, json.dumps([response_item(i) for i in range(start, start + limit)]).encode())

    return transport


def coordinator(store, calls, *, max_pages=100, page_limit=10) -> CatchUpCoordinator:
    client = PublicBinanceAggTradeClient(transport=recording_transport(calls), minimum_interval=0)
    return CatchUpCoordinator(store, client, max_pages=max_pages, page_limit=page_limit)


@pytest.mark.asyncio
async def test_fully_persisted_stale_gap_resolves_without_any_request() -> None:
    store = ResumableStore(500, set(range(100, 501)))
    calls: list[tuple[int, int]] = []
    gap = {"gap_id": "a" * 64, "symbol": "BTCUSDT", "missing_from_id": 100, "missing_to_id": 400}
    result = await coordinator(store, calls).recover_open_gap(gap)
    assert result.status == "COMPLETE"
    assert calls == []
    assert result.pages == 0 and result.persisted == 0 and result.already_present == 301
    assert store.gaps[gap["gap_id"]] == "RESOLVED"


@pytest.mark.asyncio
async def test_partly_filled_gap_fetches_only_the_holes() -> None:
    # 100..149 and 160..199 filled by an earlier run; holes 150..159 and 200..209.
    filled = set(range(100, 150)) | set(range(160, 200))
    store = ResumableStore(1_000, filled | set(range(210, 1_001)))
    calls: list[tuple[int, int]] = []
    gap = {"gap_id": "b" * 64, "symbol": "BTCUSDT", "missing_from_id": 100, "missing_to_id": 209}
    result = await coordinator(store, calls, page_limit=10).recover_open_gap(gap)
    assert result.status == "COMPLETE"
    assert calls == [(150, 10), (160, 10), (200, 10)]
    assert result.persisted == 20 and result.duplicates == 10
    assert result.already_present == 80
    assert set(range(100, 210)) <= store.persisted


@pytest.mark.asyncio
async def test_skip_never_crosses_the_durable_cursor() -> None:
    # Cursor at 120, but raw rows above it exist (121..130): they must be
    # fetched again so the cursor advances contiguously.
    store = ResumableStore(120, set(range(100, 131)))
    calls: list[tuple[int, int]] = []
    result = await coordinator(store, calls, page_limit=10).recover_before("BTCUSDT", 141)
    assert result.status == "COMPLETE"
    assert calls[0][0] == 121
    assert store.cursor.last_aggregate_trade_id == 140


@pytest.mark.asyncio
async def test_probe_failure_falls_back_to_plain_fetch() -> None:
    class BrokenProbe(ResumableStore):
        async def first_missing_trade_id(self, *_args):
            raise TimeoutError("slow agg_trades scan")

    store = BrokenProbe(500, set(range(100, 501)))
    calls: list[tuple[int, int]] = []
    gap = {"gap_id": "c" * 64, "symbol": "BTCUSDT", "missing_from_id": 100, "missing_to_id": 119}
    result = await coordinator(store, calls, page_limit=10).recover_open_gap(gap)
    assert result.status == "COMPLETE"
    assert [start for start, _ in calls] == [100, 110]
    assert result.duplicates == 20 and result.already_present == 0


@pytest.mark.asyncio
async def test_interrupted_runs_add_up_to_one_complete_catch_up() -> None:
    """Three budget-limited runs on the same gap finish it without refetching."""
    store = ResumableStore(99, set())
    calls: list[tuple[int, int]] = []
    gap = {"gap_id": "d" * 64, "symbol": "BTCUSDT", "missing_from_id": 100, "missing_to_id": 159}
    worker = coordinator(store, calls, max_pages=2, page_limit=10)
    statuses = [(await worker.recover_open_gap(gap)).status for _ in range(3)]
    assert statuses == ["OPEN", "OPEN", "COMPLETE"]
    assert [start for start, _ in calls] == [100, 110, 120, 130, 140, 150]


DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
BASE = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(hours=2)


@pytest_asyncio.fixture
async def database():
    if not DATABASE_URL:
        pytest.skip("isolated durable-ingestion PostgreSQL URL not provided")
    from src.database.connection import Database

    value = Database(DATABASE_URL, min_size=1, max_size=3)
    await value.connect()
    await value.initialize_schema()

    async def wipe():
        async with value.acquire() as connection:
            for table in ("ingestion_outbox", "ingestion_gap_incidents", "ingestion_cursors",
                          "ingestion_metrics", "agg_trades"):
                await connection.execute(f"DELETE FROM {table} WHERE symbol LIKE 'RESUME%'"
                                         if table != "ingestion_metrics" else f"DELETE FROM {table}")

    await wipe()
    yield value
    await wipe()
    await value.close()


def trade(symbol: str, trade_id: int) -> Trade:
    return Trade(symbol, 100.0, 0.25, BASE + timedelta(milliseconds=trade_id), trade_id, False)


@pytest.mark.asyncio
async def test_first_missing_trade_id_on_postgres(database) -> None:
    from src.data_ingestion.durable import DurableIngestionStore

    store = DurableIngestionStore(database, queue_capacity=10_000)
    for trade_id in [*range(10, 20), *range(25, 31)]:
        await store.ingest_trade(trade("RESUMEA", trade_id))
    assert await store.first_missing_trade_id("RESUMEA", 5, 40) == 5
    assert await store.first_missing_trade_id("RESUMEA", 10, 40) == 20
    assert await store.first_missing_trade_id("RESUMEA", 25, 30) == 31
    assert await store.first_missing_trade_id("RESUMEA", 25, 40) == 31
    assert await store.first_missing_trade_id("RESUMEA", 12, 19) == 20
    assert await store.first_missing_trade_id("RESUMEA", 19, 19) == 20
    assert await store.first_missing_trade_id("RESUMEA", 20, 20) == 20
    with pytest.raises(ValueError):
        await store.first_missing_trade_id("RESUMEA", 10, 9)


@pytest.mark.asyncio
async def test_stale_gap_on_postgres_resolves_with_only_missing_requests(database) -> None:
    from src.data_ingestion.durable import DurableIngestionStore

    store = DurableIngestionStore(database, queue_capacity=10_000)
    symbol = "RESUMEB"
    await store.ingest_trade(trade(symbol, 99))
    # Earlier interrupted run: gap 100..159 recorded, 100..139 already filled.
    gap_id = await store.record_gap(symbol=symbol, missing_from_id=100, missing_to_id=159, reason="TEST_STALE")
    for trade_id in range(100, 140):
        await store.ingest_trade(trade(symbol, trade_id))

    calls: list[tuple[int, int]] = []

    async def transport(url, _headers, _timeout):
        query = parse_qs(urlsplit(url).query)
        start, limit = int(query["fromId"][0]), int(query["limit"][0])
        calls.append((start, limit))
        items = [{"a": i, "p": "100.0", "q": "0.25", "T": int((BASE + timedelta(milliseconds=i)).timestamp() * 1000),
                  "m": False} for i in range(start, start + limit)]
        return HttpResponse(200, {}, json.dumps(items).encode())

    client = PublicBinanceAggTradeClient(transport=transport, minimum_interval=0)
    worker = CatchUpCoordinator(store, client, max_pages=10, page_limit=10)
    result = await worker.recover_open_gap(
        {"gap_id": gap_id, "symbol": symbol, "missing_from_id": 100, "missing_to_id": 159}
    )
    assert result.status == "COMPLETE", result.reason
    assert calls == [(140, 10), (150, 10)]
    assert result.already_present == 40 and result.persisted == 20
    async with database.acquire() as connection:
        status = await connection.fetchval("SELECT status FROM ingestion_gap_incidents WHERE gap_id=$1", gap_id)
        extra_gaps = await connection.fetchval(
            "SELECT count(*) FROM ingestion_gap_incidents WHERE symbol=$1 AND gap_id<>$2", symbol, gap_id)
    assert status == "RESOLVED"
    assert extra_gaps == 0


@pytest.mark.asyncio
async def test_range_above_cursor_is_not_skipped_into() -> None:
    # Cursor 50, gap 100..129 with 100..119 stored: skipping would widen the
    # TRADE_ID_GAP ingest records from the cursor, so fetch from 100.
    store = ResumableStore(50, set(range(100, 120)))
    calls: list[tuple[int, int]] = []
    gap = {"gap_id": "f" * 64, "symbol": "BTCUSDT", "missing_from_id": 100, "missing_to_id": 129}
    result = await coordinator(store, calls, page_limit=10).recover_open_gap(gap)
    assert calls[0][0] == 100 and result.already_present == 0


@pytest.mark.asyncio
async def test_unhelpful_probe_is_not_repeated_on_every_duplicate_page() -> None:
    store = ResumableStore(120, set(range(100, 221)))
    calls: list[tuple[int, int]] = []
    result = await coordinator(store, calls, page_limit=10).recover_before("BTCUSDT", 231)
    assert result.status == "COMPLETE"
    assert calls[0][0] == 121
    assert store.probe_calls <= 2
