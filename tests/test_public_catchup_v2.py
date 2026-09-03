from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from src.data_ingestion.catchup import (
    CatchUpCoordinator,
    HttpResponse,
    PublicBinanceAggTradeClient,
    PublicRateLimitError,
)


@dataclass
class FakeCursor:
    last_aggregate_trade_id: int


@dataclass
class FakeIngestResult:
    raw_inserted: bool
    duplicate: bool


class FakeStore:
    def __init__(self, cursor_id: int = 99) -> None:
        self.cursor = FakeCursor(cursor_id)
        self.persisted: set[int] = set()
        self.gaps: dict[str, str] = {}
        self.metrics: list[str] = []
        self.recovery = "NORMAL"

    async def get_cursor(self, _symbol):
        return self.cursor

    async def record_gap(self, **_kwargs):
        gap_id = "d" * 64
        self.gaps[gap_id] = "OPEN"
        return gap_id

    async def set_gap_status(self, gap_id, status, **_kwargs):
        self.gaps[gap_id] = status

    async def set_recovery_state(self, _symbol, state):
        self.recovery = state

    async def record_metric(self, name, *_args, **_kwargs):
        self.metrics.append(name)

    async def ingest_trade(self, trade):
        inserted = trade.trade_id not in self.persisted
        self.persisted.add(trade.trade_id)
        self.cursor.last_aggregate_trade_id = max(self.cursor.last_aggregate_trade_id, trade.trade_id)
        return FakeIngestResult(inserted, not inserted)

    async def resolve_gaps_through(self, _symbol, _trade_id):
        return 1


def response_item(trade_id: int) -> dict:
    return {"a": trade_id, "p": "100.0", "q": "0.5", "T": 1767225600000 + trade_id, "m": False}


@pytest.mark.asyncio
async def test_bounded_public_catchup_recovers_long_disconnect_without_auth_headers() -> None:
    calls = []

    async def transport(url, headers, _timeout):
        calls.append((url, dict(headers)))
        query = parse_qs(urlsplit(url).query)
        start, limit = int(query["fromId"][0]), int(query["limit"][0])
        return HttpResponse(200, {}, json.dumps([response_item(item) for item in range(start, start + limit)]).encode())

    store = FakeStore(99)
    client = PublicBinanceAggTradeClient(transport=transport, minimum_interval=0)
    result = await CatchUpCoordinator(store, client, max_pages=3, page_limit=1_000).recover_before("BTCUSDT", 2_101)
    assert result.status == "COMPLETE"
    assert result.persisted == 2_001 and result.pages == 3
    assert min(store.persisted) == 100 and max(store.persisted) == 2_100
    assert all("Authorization" not in headers and "X-MBX-APIKEY" not in headers for _, headers in calls)
    assert all(url.startswith("https://api.binance.com/api/v3/aggTrades?") for url, _ in calls)


@pytest.mark.asyncio
async def test_duplicate_catchup_response_is_idempotent() -> None:
    async def transport(url, _headers, _timeout):
        start = int(parse_qs(urlsplit(url).query)["fromId"][0])
        return HttpResponse(200, {}, json.dumps([response_item(item) for item in range(start, start + 3)]).encode())

    store = FakeStore(9)
    client = PublicBinanceAggTradeClient(transport=transport, minimum_interval=0)
    coordinator = CatchUpCoordinator(store, client, max_pages=1, page_limit=3)
    gap = {"gap_id": "e" * 64, "symbol": "BTCUSDT", "missing_from_id": 10, "missing_to_id": 12}
    first = await coordinator.recover_open_gap(gap)
    second = await coordinator.recover_open_gap(gap)
    assert first.persisted == 3 and first.duplicates == 0
    assert second.persisted == 0 and second.duplicates == 3
    assert store.persisted == {10, 11, 12}


@pytest.mark.asyncio
async def test_rate_limit_leaves_gap_open_and_never_invents_data() -> None:
    async def transport(_url, _headers, _timeout):
        return HttpResponse(429, {"retry-after": "7"}, b"{}")

    store = FakeStore(19)
    result = await CatchUpCoordinator(
        store, PublicBinanceAggTradeClient(transport=transport, minimum_interval=0), max_pages=1
    ).recover_before("BTCUSDT", 22)
    assert result.status == "OPEN" and result.persisted == 0
    assert "rate limit" in result.reason
    assert store.persisted == set()
    assert "catchup_failure_total" in store.metrics


@pytest.mark.asyncio
async def test_client_rejects_unapproved_host_and_surfaces_retry_after() -> None:
    with pytest.raises(ValueError, match="approved HTTPS"):
        PublicBinanceAggTradeClient(base_url="https://example.com")

    async def transport(_url, _headers, _timeout):
        return HttpResponse(429, {"retry-after": "12"}, b"{}")

    client = PublicBinanceAggTradeClient(transport=transport, minimum_interval=0)
    with pytest.raises(PublicRateLimitError) as error:
        await client.fetch("BTCUSDT", 1)
    assert error.value.retry_after_seconds == 12
