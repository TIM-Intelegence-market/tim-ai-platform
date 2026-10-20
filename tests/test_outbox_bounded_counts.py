"""Status and watchdog queries must not scan the COMPLETED outbox rows.

The outbox keeps one COMPLETED row per trade. Counting them made `tim_ingestion_control.py`
take 13-28 s on the Mac mini, so `timctl start` hit its bootstrap timeout and the watchdog
reported a false database TimeoutError.
"""
from __future__ import annotations

import asyncio
import inspect
from contextlib import asynccontextmanager

from src.data_ingestion.control import COUNTED_OUTBOX_STATUSES, IngestionControl
from src.operational import watchdog


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, query: str, *args):
        self.calls.append((query, args))
        return [{"status": "PENDING", "count": 2}]

    async def fetchrow(self, query: str, *args):
        self.calls.append((query, args))
        return {"count": 0, "first_lease_expiry": None}


class FakeDatabase:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


class FakeStore:
    def __init__(self, connection: FakeConnection) -> None:
        self.database = FakeDatabase(connection)

    async def get_cursor(self, symbol: str):
        return None

    async def metrics_snapshot(self, symbol: str):
        return {}


def test_control_status_counts_only_indexed_non_completed_statuses() -> None:
    connection = FakeConnection()
    report = asyncio.run(IngestionControl(FakeStore(connection), "BTCUSDT").status())
    grouped = [(query, args) for query, args in connection.calls if "GROUP BY status" in query]
    assert len(grouped) == 1
    query, args = grouped[0]
    assert "WHERE status=ANY($1::text[])" in query
    assert args == (list(COUNTED_OUTBOX_STATUSES),)
    assert "COMPLETED" not in COUNTED_OUTBOX_STATUSES
    assert report["outbox_by_status"] == {"PENDING": 2}


def test_watchdog_queue_query_filters_in_where_clause() -> None:
    source = inspect.getsource(watchdog.IndependentWatchdog._database)
    assert "FILTER (WHERE status" not in source
    assert "FROM ingestion_outbox WHERE status IN ('PENDING','PROCESSING','RETRY','QUARANTINED')" in source
