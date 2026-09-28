from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.data_ingestion.durable import DurableIngestionStore, QueueCapacityError
from src.models.market_data import Trade


BINANCE_PUBLIC_HOSTS = frozenset({"api.binance.com"})
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{3,20}$")


class PublicDataError(RuntimeError):
    """A bounded public market-data request failed validation."""


class PublicRateLimitError(PublicDataError):
    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__(f"public Binance rate limit; retry after {retry_after_seconds:.1f}s")
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class CatchUpResult:
    status: str
    symbol: str
    requested_from_id: int | None
    requested_to_id: int | None
    persisted: int
    duplicates: int
    pages: int
    reason: str | None = None


Transport = Callable[[str, Mapping[str, str], float], Awaitable[HttpResponse]]


async def _default_transport(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
    def request() -> HttpResponse:
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=dict(headers), method="GET"), timeout=timeout
            ) as response:
                return HttpResponse(
                    int(response.status),
                    {str(key).lower(): str(value) for key, value in response.headers.items()},
                    response.read(2_000_001),
                )
        except urllib.error.HTTPError as error:
            return HttpResponse(
                int(error.code),
                {str(key).lower(): str(value) for key, value in error.headers.items()},
                error.read(2_000_001),
            )

    return await asyncio.to_thread(request)


class PublicBinanceAggTradeClient:
    """Strictly unauthenticated, bounded Binance Spot aggTrade REST client."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.binance.com",
        transport: Transport | None = None,
        request_timeout: float = 10.0,
        minimum_interval: float = 0.05,
    ) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != "https" or parsed.hostname not in BINANCE_PUBLIC_HOSTS:
            raise ValueError("catch-up endpoint must be an approved HTTPS Binance public host")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("catch-up endpoint cannot contain credentials, query, or fragment")
        self.base_url = base_url.rstrip("/")
        self.transport = transport or _default_transport
        self.request_timeout = max(1.0, min(request_timeout, 30.0))
        self.minimum_interval = max(0.0, minimum_interval)
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def fetch(self, symbol: str, from_id: int, *, limit: int = 1_000) -> list[Trade]:
        if not SYMBOL_PATTERN.fullmatch(symbol):
            raise ValueError("invalid Binance symbol")
        if from_id < 0:
            raise ValueError("from_id must be non-negative")
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        query = urllib.parse.urlencode({"symbol": symbol, "fromId": from_id, "limit": limit})
        url = f"{self.base_url}/api/v3/aggTrades?{query}"
        headers = {"Accept": "application/json", "User-Agent": "TIM-OBSERVE-CATCHUP/1.0"}
        async with self._lock:
            delay = self.minimum_interval - (time.monotonic() - self._last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            response = await self.transport(url, headers, self.request_timeout)
            self._last_request = time.monotonic()
        if len(response.body) > 2_000_000:
            raise PublicDataError("public Binance response exceeds the 2 MB safety limit")
        if response.status in {418, 429}:
            retry_after = response.headers.get("retry-after", "1")
            try:
                seconds = max(1.0, min(float(retry_after), 300.0))
            except ValueError:
                seconds = 1.0
            raise PublicRateLimitError(seconds)
        if response.status != 200:
            raise PublicDataError(f"public Binance HTTP status {response.status}")
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PublicDataError("public Binance response is not valid JSON") from error
        if not isinstance(payload, list) or len(payload) > limit:
            raise PublicDataError("public Binance response shape or item count is invalid")

        trades: list[Trade] = []
        for item in payload:
            if not isinstance(item, dict):
                raise PublicDataError("public Binance aggTrade item is not an object")
            if not isinstance(item.get("m"), bool) or isinstance(item.get("a"), bool) or isinstance(item.get("T"), bool):
                raise PublicDataError("public Binance aggTrade identity or maker flag has an invalid type")
            try:
                trade = Trade(
                    symbol=symbol,
                    price=float(item["p"]),
                    quantity=float(item["q"]),
                    event_time=datetime.fromtimestamp(int(item["T"]) / 1_000, tz=timezone.utc),
                    trade_id=int(item["a"]),
                    buyer_is_maker=item["m"],
                )
            except (KeyError, TypeError, ValueError, OverflowError) as error:
                raise PublicDataError("public Binance aggTrade item failed validation") from error
            if trade.trade_id is None or trade.trade_id < from_id:
                raise PublicDataError("public Binance returned an aggregate ID below fromId")
            trades.append(trade)
        if any(right.trade_id <= left.trade_id for left, right in zip(trades, trades[1:])):
            raise PublicDataError("public Binance aggregate IDs are not strictly increasing")
        return trades


class CatchUpCoordinator:
    """Bounded, idempotent gap repair before live-stream continuation."""

    def __init__(
        self,
        store: DurableIngestionStore,
        client: PublicBinanceAggTradeClient,
        *,
        max_pages: int = 100,
        page_limit: int = 1_000,
    ) -> None:
        if not 1 <= max_pages <= 10_000:
            raise ValueError("max_pages must be between 1 and 10000")
        if not 1 <= page_limit <= 1_000:
            raise ValueError("page_limit must be between 1 and 1000")
        self.store = store
        self.client = client
        self.max_pages = max_pages
        self.page_limit = page_limit

    async def recover_before(
        self,
        symbol: str,
        next_live_trade_id: int,
        *,
        reason: str = "DISCONNECT_OR_RECONNECT_GAP",
    ) -> CatchUpResult:
        """Recover ``cursor + 1`` through ``next_live_trade_id - 1``.

        Callers must run this before accepting the first post-disconnect live event.
        This preserves an unambiguous low-water boundary even after a long outage.
        """
        cursor = await self.store.get_cursor(symbol)
        if cursor is None or cursor.last_aggregate_trade_id is None:
            return CatchUpResult("NO_CURSOR", symbol, None, None, 0, 0, 0, "no trusted start ID")
        start_id = cursor.last_aggregate_trade_id + 1
        end_id = next_live_trade_id - 1
        if end_id < start_id:
            return CatchUpResult("NO_GAP", symbol, start_id, end_id, 0, 0, 0)
        gap_id = await self.store.record_gap(
            symbol=symbol,
            missing_from_id=start_id,
            missing_to_id=end_id,
            reason=reason,
            details={"next_live_trade_id": next_live_trade_id},
        )
        return await self._recover_range(symbol, start_id, end_id, gap_id)

    async def recover_open_gap(self, gap: Mapping[str, Any]) -> CatchUpResult:
        start_id, end_id = gap.get("missing_from_id"), gap.get("missing_to_id")
        if not isinstance(start_id, int) or not isinstance(end_id, int):
            return CatchUpResult(
                "OPEN", str(gap.get("symbol", "")), start_id, end_id, 0, 0, 0,
                "gap has no authoritative aggregate-ID range",
            )
        return await self._recover_range(str(gap["symbol"]), start_id, end_id, str(gap["gap_id"]))

    async def _recover_range(self, symbol: str, start_id: int, end_id: int, gap_id: str) -> CatchUpResult:
        expected = start_id
        persisted = duplicates = pages = 0
        await self.store.set_gap_status(gap_id, "CATCHING_UP")
        try:
            await self.store.set_recovery_state(symbol, "CATCHING_UP")
        except Exception:
            # A gap imported from an evidence ledger can predate cursor creation.
            pass
        await self.store.record_metric("catchup_total")
        reason: str | None = None
        try:
            while expected <= end_id and pages < self.max_pages:
                requested = min(self.page_limit, end_id - expected + 1)
                batch = await self.client.fetch(symbol, expected, limit=requested)
                pages += 1
                if not batch:
                    reason = "public REST source returned no data for requested range"
                    break
                for trade in batch:
                    assert trade.trade_id is not None
                    if trade.trade_id > end_id:
                        break
                    if trade.trade_id != expected:
                        reason = f"authoritative response starts/continues at {trade.trade_id}, expected {expected}"
                        break
                    result = await self.store.ingest_trade(trade)
                    persisted += int(result.raw_inserted)
                    duplicates += int(result.duplicate)
                    expected += 1
                if reason:
                    break
                if batch[-1].trade_id is not None and batch[-1].trade_id < expected - 1:
                    reason = "catch-up source made no forward progress"
                    break
            if expected <= end_id and reason is None:
                reason = f"bounded catch-up page limit {self.max_pages} reached"
        except (PublicDataError, QueueCapacityError, OSError, TimeoutError) as error:
            reason = str(error) or type(error).__name__
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"

        if expected > end_id:
            try:
                # Verify the exact incident we have just filled.  Older,
                # governance-held evidence gaps must never block the live
                # reconnect path from proving its own complete range.
                resolve_exact = getattr(self.store, "resolve_gap", None)
                resolved = await resolve_exact(gap_id) if resolve_exact is not None else bool(
                    await self.store.resolve_gaps_through(symbol, end_id)
                )
            except (OSError, TimeoutError) as error:
                # Verification only: a slow gap table must degrade to OPEN,
                # never escape as a bare error that kills the stream loop.
                resolved = 0
                reason = str(error) or type(error).__name__
            except Exception as error:
                resolved = 0
                reason = f"{type(error).__name__}: {error}"
            if resolved:
                return CatchUpResult("COMPLETE", symbol, start_id, end_id, persisted, duplicates, pages)
            reason = reason or "persisted range failed independent completeness verification"

        await self.store.set_gap_status(gap_id, "OPEN", error=reason)
        await self.store.record_metric("catchup_failure_total")
        try:
            await self.store.set_recovery_state(symbol, "GAP_DETECTED")
        except Exception:
            pass
        return CatchUpResult("OPEN", symbol, start_id, end_id, persisted, duplicates, pages, reason)
