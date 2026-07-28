from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Protocol

from src.models.market_data import Trade


SOURCE = "BINANCE_SPOT_AGGTRADE"
METRIC_VERSION = "1.0.0"
ZERO = Decimal("0")


def _decimal(value: float | int | str | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    return format(normalized, "f") if normalized != ZERO else "0"


def _validate_window(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Orderflow window timestamps must be timezone-aware")
    if end <= start:
        raise ValueError("Orderflow window end must be after start")


def _canonical_trade(trade: Trade) -> dict[str, Any]:
    if trade.trade_id is None or trade.buyer_is_maker is None:
        raise ValueError("Persisted aggTrade identity and aggressor flag are required")
    return {"symbol": trade.symbol, "aggregate_trade_id": trade.trade_id, "trade_time": trade.event_time.isoformat(), "price": _text(_decimal(trade.price)), "quantity": _text(_decimal(trade.quantity)), "buyer_is_maker": trade.buyer_is_maker, "source": SOURCE}


@dataclass(frozen=True, slots=True)
class OrderflowMetric:
    symbol: str
    window_start: datetime
    window_end: datetime
    trade_count: int
    buy_count: int
    sell_count: int
    aggressive_buy_volume: Decimal
    aggressive_sell_volume: Decimal
    total_volume: Decimal
    net_delta: Decimal
    cumulative_delta: Decimal
    average_trade_size: Decimal
    largest_trade: Decimal
    trades_per_second: Decimal
    volume_per_second: Decimal
    buy_sell_ratio: Decimal | None
    source_hash: str
    source: str = SOURCE
    metric_version: str = METRIC_VERSION
    mode: str = "OBSERVE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "window_start": self.window_start.isoformat(), "window_end": self.window_end.isoformat(),
            "trade_count": self.trade_count, "buy_count": self.buy_count, "sell_count": self.sell_count,
            "aggressive_buy_volume": _text(self.aggressive_buy_volume), "aggressive_sell_volume": _text(self.aggressive_sell_volume),
            "total_volume": _text(self.total_volume), "net_delta": _text(self.net_delta), "cumulative_delta": _text(self.cumulative_delta),
            "average_trade_size": _text(self.average_trade_size), "largest_trade": _text(self.largest_trade),
            "trades_per_second": _text(self.trades_per_second), "volume_per_second": _text(self.volume_per_second),
            "buy_sell_ratio": _text(self.buy_sell_ratio), "source_hash": self.source_hash, "source": self.source,
            "metric_version": self.metric_version, "mode": self.mode,
        }


class OrderflowMetricsEngine:
    """Pure fixed-window arithmetic; it creates no observations or interpretations."""

    @staticmethod
    def calculate(trades: Iterable[Trade], start: datetime, end: datetime, *, opening_cvd: Decimal = ZERO, symbol: str | None = None) -> OrderflowMetric:
        _validate_window(start, end)
        ordered = sorted((trade for trade in trades if start <= trade.event_time < end), key=lambda item: (item.event_time, item.trade_id if item.trade_id is not None else -1))
        identities = [(trade.symbol, trade.trade_id) for trade in ordered]
        if len(identities) != len(set(identities)): raise ValueError("Duplicate persisted aggTrade identity in metric input")
        symbols = {trade.symbol for trade in ordered}
        if symbol is None:
            if len(symbols) > 1: raise ValueError("A metric window cannot mix symbols")
            symbol = next(iter(symbols), "UNKNOWN")
        if any(trade.symbol != symbol for trade in ordered): raise ValueError("A metric window cannot mix symbols")
        canonical = [_canonical_trade(trade) for trade in ordered]
        digest_payload = {"metric_version": METRIC_VERSION, "symbol": symbol, "window_start": start.isoformat(), "window_end": end.isoformat(), "trades": canonical}
        source_hash = hashlib.sha256(json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        buys = [trade for trade in ordered if trade.buyer_is_maker is False]
        sells = [trade for trade in ordered if trade.buyer_is_maker is True]
        buy_volume = sum((_decimal(trade.quantity) for trade in buys), ZERO)
        sell_volume = sum((_decimal(trade.quantity) for trade in sells), ZERO)
        total = buy_volume + sell_volume; count = len(ordered); duration = _decimal((end - start).total_seconds())
        delta = buy_volume - sell_volume
        return OrderflowMetric(symbol, start, end, count, len(buys), len(sells), buy_volume, sell_volume, total, delta, opening_cvd + delta, total / count if count else ZERO, max((_decimal(trade.quantity) for trade in ordered), default=ZERO), _decimal(count) / duration, total / duration, buy_volume / sell_volume if sell_volume else None, source_hash)

    def series(self, trades: Iterable[Trade], start: datetime, end: datetime, bucket_seconds: int, *, symbol: str) -> list[OrderflowMetric]:
        _validate_window(start, end)
        if bucket_seconds <= 0: raise ValueError("bucket_seconds must be positive")
        items = sorted((item for item in trades if start <= item.event_time < end),key=lambda item:(item.event_time,item.trade_id if item.trade_id is not None else -1))
        identities=[(item.symbol,item.trade_id) for item in items]
        if len(identities)!=len(set(identities)):raise ValueError("Duplicate persisted aggTrade identity in metric input")
        if any(item.symbol!=symbol for item in items):raise ValueError("A metric series cannot mix symbols")
        cursor = start; cvd = ZERO; output = []; index=0
        while cursor < end:
            boundary = min(cursor + timedelta(seconds=bucket_seconds), end)
            next_index=index
            while next_index<len(items) and items[next_index].event_time<boundary:next_index+=1
            metric = self.calculate(items[index:next_index], cursor, boundary, opening_cvd=cvd, symbol=symbol)
            output.append(metric); cvd = metric.cumulative_delta; cursor = boundary
            index=next_index
        return output


class AggTradeReader(Protocol):
    async def agg_trades_between(self, symbol: str, start: datetime, end: datetime) -> list[Trade]: ...


class OrderflowMetricsService:
    def __init__(self, repository: AggTradeReader) -> None: self.repository = repository; self.engine = OrderflowMetricsEngine()

    async def calculate_series(self, symbol: str, start: datetime, end: datetime, bucket_seconds: int) -> list[OrderflowMetric]:
        trades = await self.repository.agg_trades_between(symbol, start, end)
        return self.engine.series(trades, start, end, bucket_seconds, symbol=symbol)
