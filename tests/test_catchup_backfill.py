from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from src.data_ingestion.catchup import CatchUpCoordinator, HttpResponse, PublicBinanceAggTradeClient


def item(trade_id: int) -> dict:
    return {"a": trade_id, "p": "100.0", "q": "0.5", "T": 1767225600000 + trade_id, "m": False}


class FakeStore:
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

    async def get_cursor(self, _s): return self.cursor
    async def record_gap(self, **_k): gid="b"*64; self.gaps[gid]="OPEN"; return gid
    async def set_gap_status(self, gid, status, **_k): self.gaps[gid]=status
    async def set_recovery_state(self, _s, st): self.recovery=st
    async def record_metric(self, n, *_a, **_k): self.metrics.append(n)
    async def ingest_trade(self, trade):
        inserted = trade.trade_id not in self.persisted
        self.persisted.add(trade.trade_id)
        self.cursor.last_aggregate_trade_id = max(self.cursor.last_aggregate_trade_id, trade.trade_id)
        from dataclasses import dataclass
        @dataclass
        class R: raw_inserted: bool; duplicate: bool
        return R(inserted, not inserted)
    async def resolve_gaps_through(self, _s, _tid): return 1


@pytest.mark.asyncio
async def test_backfill_idempotent_and_bounded():
    """1.1: Backfill muss idempotent und bounded sein (max_pages)."""
    async def transport(url, _h, _t):
        q = parse_qs(urlsplit(url).query)
        start = int(q["fromId"][0]); limit=int(q["limit"][0])
        # liefere genau limit items ab start
        return HttpResponse(200, {}, json.dumps([item(i) for i in range(start, start+limit)]).encode())

    store = FakeStore(99)
    client = PublicBinanceAggTradeClient(transport=transport, minimum_interval=0)
    coord = CatchUpCoordinator(store, client, max_pages=2, page_limit=5)

    gap = {"gap_id":"c"*64, "symbol":"BTCUSDT", "missing_from_id":100, "missing_to_id":109}
    r1 = await coord.recover_open_gap(gap)
    assert r1.status == "COMPLETE"
    assert r1.persisted == 10
    assert r1.pages == 2  # 2*5=10
    # zweiter Durchlauf: duplicates, keine neuen persists
    r2 = await coord.recover_open_gap(gap)
    assert r2.persisted == 0 and r2.duplicates == 10

@pytest.mark.asyncio
async def test_backfill_small_gap_priority_single_trade():
    """Kleinste Lücke (1 Trade) wird vor 2M-Range priorisiert — 1.1 Sorting."""
    async def transport(url, _h, _t):
        q = parse_qs(urlsplit(url).query)
        start = int(q["fromId"][0])
        return HttpResponse(200, {}, json.dumps([item(start)]).encode())
    store = FakeStore(100)
    client = PublicBinanceAggTradeClient(transport=transport, minimum_interval=0)
    coord = CatchUpCoordinator(store, client, max_pages=1, page_limit=1)
    # single trade gap like OUTBOX_CAPACITY
    gap_single = {"gap_id":"d"*64, "symbol":"BTCUSDT", "missing_from_id":101, "missing_to_id":101}
    r = await coord.recover_open_gap(gap_single)
    assert r.status == "COMPLETE" and r.persisted == 1

@pytest.mark.asyncio
async def test_backfill_respects_queue_capacity_and_leaves_open_on_rate_limit():
    """QueueCapacity / RateLimit lässt Gap OPEN — nie inventiert Daten."""
    async def transport_rate(_u,_h,_t):
        return HttpResponse(429, {"retry-after":"1"}, b"{}")
    store = FakeStore(10)
    client = PublicBinanceAggTradeClient(transport=transport_rate, minimum_interval=0)
    coord = CatchUpCoordinator(store, client, max_pages=1)
    gap = {"gap_id":"e"*64, "symbol":"BTCUSDT", "missing_from_id":11, "missing_to_id":12}
    r = await coord.recover_open_gap(gap)
    assert r.status == "OPEN"
    assert "rate limit" in r.reason.lower()
    assert store.persisted == set()
