from datetime import datetime, timedelta, timezone

from src.analysis.bos_detector import BOSDetector
from src.models.market_data import Candle, ObservationKind


def candle(index: int, high: float, low: float, close: float, open_: float | None = None) -> Candle:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
    open_price = close if open_ is None else open_
    return Candle("BTCUSDT", "1m", start, start + timedelta(minutes=1), open_price, high, low, close, 1, 10)


def test_bullish_break_of_structure_requires_closed_cross() -> None:
    candles = [candle(0, 100, 95, 98), candle(1, 105, 97, 102), candle(2, 110, 98, 104), candle(3, 106, 99, 103), candle(4, 104, 98, 102), candle(5, 109, 101, 109), candle(6, 113, 108, 112)]
    observation = BOSDetector(pivot_width=2).detect(candles)
    assert observation is not None
    assert observation.kind is ObservationKind.BOS_BULLISH
    assert observation.evidence["swing_price"] == 110


def test_bearish_break_of_structure() -> None:
    candles = [candle(0, 110, 105, 108), candle(1, 109, 101, 104), candle(2, 108, 95, 99), candle(3, 107, 99, 102), candle(4, 108, 100, 103), candle(5, 102, 96, 96), candle(6, 95, 90, 92)]
    observation = BOSDetector(pivot_width=2).detect(candles)
    assert observation is not None
    assert observation.kind is ObservationKind.BOS_BEARISH


def test_no_bos_with_insufficient_or_open_candle() -> None:
    detector = BOSDetector()
    assert detector.detect([candle(0, 100, 90, 95)]) is None
    items = [candle(i, 100 + i, 90 + i, 95 + i) for i in range(7)]
    last = items[-1]
    items[-1] = Candle(last.symbol, last.timeframe, last.open_time, last.close_time, last.open, last.high, last.low, last.close, last.volume, last.trade_count, closed=False)
    assert detector.detect(items) is None
