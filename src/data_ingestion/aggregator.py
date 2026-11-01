from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from src.models.market_data import Candle, Trade

TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


def timeframe_seconds(timeframe: str) -> int:
    try:
        return TIMEFRAME_SECONDS[timeframe]
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe: {timeframe}") from exc


def bucket_start(timestamp: datetime, timeframe: str) -> datetime:
    if timestamp.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware")
    seconds = timeframe_seconds(timeframe)
    epoch = int(timestamp.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=timezone.utc)


@dataclass(slots=True)
class _BuildingCandle:
    symbol: str
    timeframe: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int

    @classmethod
    def from_trade(cls, trade: Trade, timeframe: str) -> "_BuildingCandle":
        return cls(trade.symbol, timeframe, bucket_start(trade.event_time, timeframe), trade.price, trade.price, trade.price, trade.price, trade.quantity, 1)

    def update(self, trade: Trade) -> None:
        self.high = max(self.high, trade.price)
        self.low = min(self.low, trade.price)
        self.close = trade.price
        self.volume += trade.quantity
        self.trade_count += 1

    def freeze(self, closed: bool) -> Candle:
        return Candle(self.symbol, self.timeframe, self.open_time, self.open_time + timedelta(seconds=timeframe_seconds(self.timeframe)), self.open, self.high, self.low, self.close, self.volume, self.trade_count, closed)


class CandleAggregator:
    def __init__(self, timeframes: Iterable[str]) -> None:
        self.timeframes = tuple(timeframes)
        for timeframe in self.timeframes:
            timeframe_seconds(timeframe)
        self._active: dict[tuple[str, str], _BuildingCandle] = {}
        self._last_trade_time: dict[str, datetime] = {}

    def add_trade(self, trade: Trade) -> list[Candle]:
        previous = self._last_trade_time.get(trade.symbol)
        if previous is not None and trade.event_time < previous:
            raise ValueError("Out-of-order trade rejected")
        self._last_trade_time[trade.symbol] = trade.event_time
        completed: list[Candle] = []
        for timeframe in self.timeframes:
            key = (trade.symbol, timeframe)
            start = bucket_start(trade.event_time, timeframe)
            active = self._active.get(key)
            if active is None:
                self._active[key] = _BuildingCandle.from_trade(trade, timeframe)
            elif start == active.open_time:
                active.update(trade)
            elif start > active.open_time:
                completed.append(active.freeze(closed=True))
                self._active[key] = _BuildingCandle.from_trade(trade, timeframe)
            else:
                raise ValueError("Trade belongs to an already closed candle")
        return completed

    def snapshots(self) -> list[Candle]:
        return [item.freeze(closed=False) for item in self._active.values()]


def startup_replay_start(latest_open_times: Iterable[datetime], timeframes: Iterable[str], now: datetime) -> datetime:
    """Earliest trade time the startup replay has to read.

    The replay only rebuilds the in-memory buckets that are still open. Closed
    candles are already written per trade by the durable outbox worker, so the
    replay never needs to go back further than the start of the current bucket
    of the largest timeframe. Without this bound one stale timeframe (for
    example 1h after a long outage) pulled the replay back days and made every
    start scan tens of millions of trades.
    """
    largest = max(timeframes, key=timeframe_seconds)
    floor = bucket_start(now, largest)
    latest = list(latest_open_times)
    if not latest:
        return floor
    return max(min(latest), floor)
