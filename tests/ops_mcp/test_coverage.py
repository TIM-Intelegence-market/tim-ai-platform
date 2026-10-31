"""#152 M3b: data coverage in tim-ops. The Postgres connection is faked except
in the last test, which needs the isolated CI database. The read-only DB role
itself is a server step (docs/ops_mcp/README.md) and is not proven here."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.ops_mcp.coverage import (NOW, READ_ONLY_CHECK, READ_ONLY_SETTINGS, SELECT_CANDLE_TIMES,
                                  SELECT_OPEN_GAPS, CoverageReader)
from src.ops_mcp.mcp_server import OpsMcpServer
from src.ops_mcp.readers import ResearchReader, TaskReader

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
NOW_AT = datetime(2026, 10, 24, 12, 0, 30, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
DSN = "postgresql://tim_ops_ro@127.0.0.1:5433/tim_test"


class FakeConnection:
    def __init__(self, times, gaps=(), read_only="on"):
        self.times, self.gaps, self.read_only = list(times), list(gaps), read_only
        self.statements: list[tuple[str, tuple]] = []
        self.transaction_kwargs: dict = {}
        self.closed = False

    def transaction(self, **kwargs):
        self.transaction_kwargs = kwargs
        connection = self

        class Transaction:
            async def __aenter__(self):
                return connection

            async def __aexit__(self, *exc):
                return False
        return Transaction()

    async def fetchval(self, statement, *args):
        self.statements.append((statement, args))
        return {READ_ONLY_CHECK: self.read_only, NOW: NOW_AT}[statement]

    async def fetch(self, statement, *args):
        self.statements.append((statement, args))
        if statement == SELECT_CANDLE_TIMES:
            return [{"open_time": t} for t in self.times if args[2] <= t < args[3]]
        assert statement == SELECT_OPEN_GAPS
        return self.gaps[:args[1]]

    async def close(self):
        self.closed = True


def fake(connection: FakeConnection, calls: dict | None = None):
    async def connect(dsn, **kwargs):
        if calls is not None:
            calls.update(dsn=dsn, kwargs=kwargs)
        return connection
    return connect


def minutes(start: datetime, count: int, step: int = 1, skip=()):
    return [start + timedelta(minutes=i * step) for i in range(count) if i not in skip]


def server(reader: CoverageReader) -> OpsMcpServer:
    instance = OpsMcpServer(TaskReader(None), ResearchReader(ROOT), coverage=reader,
                            health=lambda: {})
    instance.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize"})
    return instance


def call(instance, arguments: dict) -> dict:
    response = instance.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": "data_coverage", "arguments": arguments}})
    assert "result" in response, response
    return json.loads(response["result"]["content"][0]["text"])


def test_not_configured_without_dsn():
    instance = server(CoverageReader(None))
    assert call(instance, {}) == {"status": "not_configured", "hint": "set TIM_OPS_COVERAGE_DSN"}
    health = instance.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": {"name": "ops_health", "arguments": {}}})
    assert json.loads(health["result"]["content"][0]["text"])["coverage_db"] == "not_configured"


def test_one_minute_coverage_with_missing_ranges(monkeypatch):
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", DSN)
    start = WINDOW_END - timedelta(hours=1)
    connection = FakeConnection(minutes(start, 60, skip={10, 11, 59}))
    calls: dict = {}
    result = call(server(CoverageReader(DSN, connect=fake(connection, calls))), {"hours": 1})
    assert result["status"] == "ok" and result["read_only_session"] is True
    assert (result["symbol"], result["timeframe"]) == ("BTCUSDT", "1m")
    assert result["window_start"] == "2026-10-24T11:00:00Z"
    assert result["window_end"] == "2026-10-24T12:00:00Z"
    assert (result["expected"], result["observed"]) == (60, 57)
    assert result["coverage"] == "0.9500" and result["target"] == "0.95"
    assert result["meets_target"] is True
    assert result["missing_ranges"] == [
        {"from": "2026-10-24T11:10:00Z", "to": "2026-10-24T11:11:00Z", "candles": 2},
        {"from": "2026-10-24T11:59:00Z", "to": "2026-10-24T11:59:00Z", "candles": 1}]
    assert result["missing_truncated"] is False
    assert calls["kwargs"]["server_settings"] == READ_ONLY_SETTINGS
    assert connection.transaction_kwargs == {"isolation": "repeatable_read", "readonly": True}
    assert connection.statements[0][0] == READ_ONLY_CHECK
    candle_args = next(a for s, a in connection.statements if s == SELECT_CANDLE_TIMES)
    assert candle_args == ("BTCUSDT", "1m", start, WINDOW_END)
    assert connection.closed is True


def test_coarser_timeframe_and_target_miss(monkeypatch):
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", DSN)
    start = WINDOW_END - timedelta(hours=2)
    connection = FakeConnection(minutes(start, 24, step=5, skip={0, 1, 2}))
    result = call(server(CoverageReader(DSN, connect=fake(connection))),
                  {"timeframe": "5m", "hours": 2})
    assert (result["expected"], result["observed"]) == (24, 21)
    assert result["coverage"] == "0.8750" and result["meets_target"] is False
    assert result["missing_ranges"] == [
        {"from": "2026-10-24T10:00:00Z", "to": "2026-10-24T10:10:00Z", "candles": 3}]


def test_missing_ranges_are_bounded(monkeypatch):
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", DSN)
    start = WINDOW_END - timedelta(hours=1)
    connection = FakeConnection(minutes(start, 60, skip=set(range(0, 60, 2))))
    result = call(server(CoverageReader(DSN, connect=fake(connection))),
                  {"hours": 1, "limit": 5})
    assert len(result["missing_ranges"]) == 5 and result["missing_truncated"] is True
    assert result["observed"] == 30


def test_open_incidents_are_listed_and_redacted(monkeypatch):
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", DSN)
    gap = {"gap_id": "a" * 64, "status": "OPEN", "reason": "reconnect token=supersecretvalue123",
           "gap_started_at": NOW_AT - timedelta(minutes=5), "gap_ended_at": None,
           "detected_at": NOW_AT}
    connection = FakeConnection(minutes(WINDOW_END - timedelta(hours=1), 60), gaps=[gap])
    result = call(server(CoverageReader(DSN, connect=fake(connection))), {"hours": 1})
    [incident] = result["open_incidents"]
    assert incident["gap_id"] == "a" * 64 and incident["status"] == "OPEN"
    assert "supersecretvalue123" not in json.dumps(result)
    assert result["missing_ranges"] == [] and result["coverage"] == "1.0000"


def test_session_that_is_not_read_only_is_refused(monkeypatch):
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", DSN)
    connection = FakeConnection([], read_only="off")
    response = server(CoverageReader(DSN, connect=fake(connection))).handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "data_coverage", "arguments": {}}})
    assert response["error"]["code"] == -32001
    assert "read-only" in response["error"]["message"]
    assert [s for s, _ in connection.statements] == [READ_ONLY_CHECK]
    assert connection.closed is True


def test_connection_errors_do_not_leak_the_dsn(monkeypatch):
    secret_dsn = "postgresql://tim_ops_ro:hunter2pass@127.0.0.1:5433/tim_test"
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", secret_dsn)

    async def connect(dsn, **kwargs):
        raise OSError(f"could not connect to {dsn}")
    response = server(CoverageReader(secret_dsn, connect=connect)).handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "data_coverage", "arguments": {}}})
    assert response["error"]["code"] == -32001
    assert "hunter2pass" not in json.dumps(response) and "tim_ops_ro" not in json.dumps(response)


def test_runtime_database_is_refused_in_test_context(monkeypatch):
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", DSN)
    called = []

    async def connect(dsn, **kwargs):
        called.append(dsn)
    response = server(CoverageReader("postgresql://tim@db.example:5432/tim",
                                     connect=connect)).handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "data_coverage", "arguments": {}}})
    assert response["error"]["code"] == -32001 and called == []


@pytest.mark.parametrize("arguments", [{"timeframe": "2m"}, {"hours": 0}, {"hours": 169},
                                       {"symbol": "btc; drop"}, {"limit": 0}, {"extra": 1}])
def test_invalid_arguments_are_structured(arguments):
    response = server(CoverageReader(None)).handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "data_coverage", "arguments": arguments}})
    assert response["error"]["code"] == -32000


def test_statements_only_read():
    for statement in (SELECT_CANDLE_TIMES, SELECT_OPEN_GAPS, NOW):
        upper = statement.upper()
        assert upper.startswith("SELECT ") and ";" not in upper
        for word in ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "TRUNCATE",
                     "GRANT"):
            assert word not in upper
    # Prices and volumes stay out: only open times are read.
    assert "close" not in SELECT_CANDLE_TIMES.replace("closed", "")
    assert READ_ONLY_CHECK == "SHOW default_transaction_read_only"


DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="isolated PostgreSQL URL not provided")
def test_real_database_coverage_and_read_only_session():
    import asyncpg

    from src.database.connection import Database

    symbol = "COVTESTUSDT"
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    times = [now - timedelta(minutes=m) for m in range(1, 61) if m not in (5, 6)]

    async def scenario():
        database = Database(DATABASE_URL, min_size=1, max_size=1)
        await database.connect()
        await database.initialize_schema()
        try:
            async with database.acquire() as connection:
                await connection.execute("DELETE FROM candles WHERE symbol=$1", symbol)
                await connection.executemany(
                    "INSERT INTO candles VALUES ($1,'1m',$2,$3,1,1,1,1,0,0,true)",
                    [(symbol, t, t + timedelta(seconds=59)) for t in times])
            result = await asyncio.to_thread(
                CoverageReader(DATABASE_URL).coverage, symbol=symbol, hours=1)
            assert result["status"] == "ok" and result["read_only_session"] is True
            assert result["expected"] == 60 and result["observed"] in (57, 58)
            reader = await asyncpg.connect(DATABASE_URL,
                                           server_settings=dict(READ_ONLY_SETTINGS))
            try:
                with pytest.raises(asyncpg.exceptions.ReadOnlySQLTransactionError):
                    await reader.execute("DELETE FROM candles WHERE symbol=$1", symbol)
            finally:
                await reader.close()
            async with database.acquire() as connection:
                await connection.execute("DELETE FROM candles WHERE symbol=$1", symbol)
        finally:
            await database.close()

    asyncio.run(scenario())
