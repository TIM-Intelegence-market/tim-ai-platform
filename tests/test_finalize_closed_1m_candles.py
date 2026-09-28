from datetime import datetime, timezone

from scripts.finalize_closed_1m_candles import candle_from_row, closed_bounds


def test_closed_bounds_excludes_the_current_open_minute():
    start, end = closed_bounds(datetime(2026, 9, 23, 11, 35, 42, tzinfo=timezone.utc), 3)
    assert start == datetime(2026, 9, 23, 11, 32, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 23, 11, 35, tzinfo=timezone.utc)


def test_candle_from_raw_aggregate_is_closed_and_raw_backed():
    candle = candle_from_row({
        "symbol": "BTCUSDT", "open_time": datetime(2026, 9, 23, 11, 34, tzinfo=timezone.utc),
        "open": 100.0, "high": 104.0, "low": 99.0, "close": 103.0, "volume": 7.5, "trade_count": 4,
    })
    assert candle.closed is True
    assert candle.open_time == datetime(2026, 9, 23, 11, 34, tzinfo=timezone.utc)
    assert candle.close_time == datetime(2026, 9, 23, 11, 35, tzinfo=timezone.utc)
    assert (candle.open, candle.high, candle.low, candle.close, candle.volume, candle.trade_count) == (100.0, 104.0, 99.0, 103.0, 7.5, 4)
