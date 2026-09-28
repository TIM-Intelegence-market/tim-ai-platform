from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from src.data_ingestion.catchup import CatchUpCoordinator, HttpResponse, PublicBinanceAggTradeClient
from src.data_ingestion.durable import DurableIngestionStore


def item(trade_id: int) -> dict:
    return {"a": trade_id, "p": "100.0", "q": "0.5", "T": 1767225600000 + trade_id, "m": False}


def make_transport():
    async def transport(url, _h, _t):
        q = parse_qs(urlsplit(url).query)
        start = int(q["fromId"][0])
        limit = int(q["limit"][0])
        return HttpResponse(200, {}, json.dumps([item(i) for i in range(start, start + limit)]).encode())
    return transport


class FakeStore:
    """No-DB fake: backfill succeeds, verification raises like command_timeout."""

    def __init__(self, cursor_id: int = 100) -> None:
        from dataclasses import dataclass

        @dataclass
        class C:
            last_aggregate_trade_id: int

        self.cursor = C(cursor_id)
        self.persisted: set[int] = set()
        self.gaps: dict[str, str] = {}
        self.metrics: list[str] = []
        self.recovery = "NORMAL"

    async def get_cursor(self, _s):
        return self.cursor

    async def record_gap(self, **_k):
        gid = "b" * 64
        self.gaps[gid] = "OPEN"
        return gid

    async def set_gap_status(self, gid, status, **_k):
        self.gaps[gid] = status

    async def set_recovery_state(self, _s, st):
        self.recovery = st

    async def record_metric(self, n, *_a, **_k):
        self.metrics.append(n)

    async def ingest_trade(self, trade):
        inserted = trade.trade_id not in self.persisted
        self.persisted.add(trade.trade_id)
        self.cursor.last_aggregate_trade_id = max(self.cursor.last_aggregate_trade_id, trade.trade_id)
        from dataclasses import dataclass

        @dataclass
        class R:
            raw_inserted: bool
            duplicate: bool

        return R(inserted, not inserted)

    async def resolve_gaps_through(self, _s, _tid):
        # Simulates asyncpg command_timeout=30s on the unbounded verification
        # query: bare TimeoutError with empty message, exactly as observed in
        # production (reconnect_total metadata error_type=TimeoutError).
        raise TimeoutError()


@pytest.mark.asyncio
async def test_resolve_timeout_must_not_escape_recover_range():
    """Fail-closed: slow verification degrades to OPEN, never kills the caller."""
    store = FakeStore(100)
    client = PublicBinanceAggTradeClient(transport=make_transport(), minimum_interval=0)
    coord = CatchUpCoordinator(store, client, max_pages=10, page_limit=10)
    # gap 101..105 fully backfillable in one page
    result = await coord.recover_before("BTCUSDT", 106)
    assert result.status == "OPEN"
    assert result.persisted == 5
    assert "catchup_failure_total" in store.metrics


@pytest.mark.asyncio
async def test_resolve_timeout_reason_names_the_error_type():
    """Empty TimeoutError str must not produce an empty reason (diagnosability)."""
    store = FakeStore(100)
    client = PublicBinanceAggTradeClient(transport=make_transport(), minimum_interval=0)
    coord = CatchUpCoordinator(store, client, max_pages=10, page_limit=10)
    result = await coord.recover_before("BTCUSDT", 106)
    assert result.reason is not None and result.reason != ""
    assert "TimeoutError" in result.reason


class FakeTx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return False


class FakeConn:
    def __init__(self) -> None:
        self.fetch_calls: list[tuple[str, tuple]] = []

    def transaction(self):
        return FakeTx()

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return []

    async def fetchval(self, _sql, *_args):
        return 5  # remaining > 0: skips the cursor write path

    async def fetchrow(self, _sql, *_args):
        return None  # no cursor row: write path skipped via `if cursor and ...`


class FakeAcquire:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        return False


class FakeDB:
    def __init__(self) -> None:
        self.conn = FakeConn()

    def acquire(self):
        return FakeAcquire(self.conn)


@pytest.mark.asyncio
async def test_resolve_verify_is_bounded_oldest_first():
    """Verification must be bounded (LIMIT) and oldest-first, never unbounded."""
    db = FakeDB()
    store = DurableIngestionStore(db, resolve_verify_limit=100)
    assert await store.resolve_gaps_through("BTCUSDT", 4066014861) == 0
    assert len(db.conn.fetch_calls) == 1
    sql, args = db.conn.fetch_calls[0]
    assert "LIMIT $3" in sql
    assert args[2] == 100
    assert "ORDER BY detected_at" in sql


def test_resolve_verify_limit_defaults_and_validates():
    db = FakeDB()
    # Calibrated default: 10 oldest-first verifications fit the 30s timeout
    # (measured ~1.1s per ancient gap on production scale).
    assert DurableIngestionStore(db).resolve_verify_limit == 10
    with pytest.raises(ValueError):
        DurableIngestionStore(db, resolve_verify_limit=0)


class ScaleFakeConn(FakeConn):
    """Emulates the bounded resolve SQL over many historical gaps.

    Mirrors production semantics: oldest-first prefix of size LIMIT is
    selected, only that prefix is verified, verified rows leave candidacy,
    and the next call continues where the previous stopped.
    """

    def __init__(self, total_gaps: int) -> None:
        super().__init__()
        # gap i: detected_at rank i (0 = oldest), all with to_id under cap.
        self.states = ["OPEN"] * total_gaps
        self.verified_order: list[int] = []

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        _symbol, cap, limit = args[0], args[1], args[2]
        assert "LIMIT $3" in sql and "ORDER BY detected_at" in sql
        candidates = [i for i, s in enumerate(self.states) if s in ("OPEN", "CATCHING_UP")][:limit]
        assert candidates == sorted(candidates), "prefix must be oldest-first"
        resolved = []
        for i in candidates:
            # Fake verification: every selected gap is complete (as measured
            # for the production prefix: 100/100 verifiable).
            self.verified_order.append(i)
            self.states[i] = "RESOLVED"
            resolved.append({"gap_id": i})
        return resolved

    async def fetchval(self, _sql, *_args):
        return sum(1 for s in self.states if s in ("OPEN", "CATCHING_UP"))


class ScaleFakeDB(FakeDB):
    def __init__(self, total_gaps: int) -> None:
        self.conn = ScaleFakeConn(total_gaps)


@pytest.mark.asyncio
async def test_bounded_prefix_progresses_without_skips_or_reorder():
    """250 historical gaps, limit 100: call 1 verifies 0..99 in order,
    call 2 continues at 100..199; nothing skipped, nothing reordered."""
    db = ScaleFakeDB(250)
    store = DurableIngestionStore(db, resolve_verify_limit=100)
    assert await store.resolve_gaps_through("BTCUSDT", 9_999_999_999) == 100
    assert db.conn.verified_order == list(range(100))
    assert await store.resolve_gaps_through("BTCUSDT", 9_999_999_999) == 100
    assert db.conn.verified_order == list(range(200))
    # Third call drains the final 50 and reports the remainder honestly.
    assert await store.resolve_gaps_through("BTCUSDT", 9_999_999_999) == 50
    assert db.conn.verified_order == list(range(250))
