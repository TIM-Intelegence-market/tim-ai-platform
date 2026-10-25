from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.data_ingestion.derived_candles import DERIVED_TIMEFRAMES, derive_candles, derive_from, source_timeframe
from src.database.repository import ALLOWED_TIMEFRAMES, _validate_candle_for_persistence
from src.models.market_data import Candle

ROOT = Path(__file__).resolve().parents[1]
DAY = datetime(2026, 10, 24, tzinfo=timezone.utc)


def hour(offset: int, *, price: float = 100.0, high: float | None = None, low: float | None = None, symbol: str = "BTCUSDT", closed: bool = True) -> Candle:
    open_time = DAY + timedelta(hours=offset)
    high = price if high is None else high
    low = price if low is None else low
    return Candle(symbol, "1h", open_time, open_time + timedelta(hours=1), price, max(high, price), min(low, price), price, 2.0, 10, closed)


def test_only_4h_and_1d_are_derived_and_both_come_from_1h():
    assert DERIVED_TIMEFRAMES == {"4h": "1h", "1d": "1h"}
    assert source_timeframe("4h") == "1h" and source_timeframe("1d") == "1h"
    with pytest.raises(ValueError):
        source_timeframe("1h")


def test_four_hour_candle_from_four_contiguous_hours():
    source = [hour(0, price=100), hour(1, price=104, high=110), hour(2, price=98, low=95), hour(3, price=101)]
    [candle] = derive_candles(source, "4h", DAY + timedelta(hours=4))
    assert candle.timeframe == "4h" and candle.open_time == DAY and candle.close_time == DAY + timedelta(hours=4)
    assert (candle.open, candle.high, candle.low, candle.close) == (100, 110, 95, 101)
    assert candle.volume == 8.0 and candle.trade_count == 40 and candle.closed is True


def test_bucket_with_gap_or_open_source_candle_is_skipped():
    gap = [hour(0), hour(1), hour(3)]  # hour 2 missing
    assert derive_candles(gap, "4h", DAY + timedelta(hours=4)) == []
    not_closed = [hour(0), hour(1), hour(2), hour(3, closed=False)]
    assert derive_candles(not_closed, "4h", DAY + timedelta(hours=4)) == []


def test_bucket_whose_close_is_in_the_future_is_not_written():
    source = [hour(i) for i in range(4)]
    assert derive_candles(source, "4h", DAY + timedelta(hours=3, minutes=59)) == []
    assert len(derive_candles(source, "4h", DAY + timedelta(hours=4))) == 1


def test_daily_candle_needs_all_24_hours_and_aligns_to_utc_midnight():
    source = [hour(i, price=100 + i) for i in range(-3, 27)]  # spills into the previous and next day
    result = derive_candles(source, "1d", DAY + timedelta(days=1, hours=3))
    assert [c.open_time for c in result] == [DAY]
    day = result[0]
    assert day.open == 100 and day.close == 123 and day.high == 123 and day.low == 100
    assert day.trade_count == 240


def test_derivation_is_order_independent_and_per_symbol():
    source = [hour(i) for i in range(4)] + [hour(i, symbol="ETHUSDT", price=50) for i in range(4)]
    forward = derive_candles(source, "4h", DAY + timedelta(hours=4))
    backward = derive_candles(list(reversed(source)), "4h", DAY + timedelta(hours=4))
    assert forward == backward and sorted(c.symbol for c in forward) == ["BTCUSDT", "ETHUSDT"]


def test_wrong_source_timeframe_and_conflicting_duplicates_raise():
    with pytest.raises(ValueError):
        derive_candles([Candle("BTCUSDT", "15m", DAY, DAY + timedelta(minutes=15), 1, 1, 1, 1, 1, 1)], "4h", DAY + timedelta(hours=4))
    with pytest.raises(ValueError):
        derive_candles([hour(0, price=100), hour(0, price=101)], "4h", DAY + timedelta(hours=4))
    # an identical duplicate is harmless
    assert len(derive_candles([hour(i) for i in range(4)] + [hour(0)], "4h", DAY + timedelta(hours=4))) == 1


def test_next_pass_starts_at_the_bucket_after_the_latest_derived_one():
    assert derive_from(None, "4h") is None
    assert derive_from(DAY, "4h") == DAY + timedelta(hours=4)
    assert derive_from(DAY, "1d") == DAY + timedelta(days=1)


def test_persistence_accepts_derived_timeframes_and_schema_matches_migration():
    assert {"4h", "1d"} <= ALLOWED_TIMEFRAMES
    [candle] = derive_candles([hour(i) for i in range(4)], "4h", DAY + timedelta(hours=4))
    _validate_candle_for_persistence(candle, now=DAY + timedelta(hours=4))
    schema = (ROOT / "src/database/schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "src/database/migrations/009_candles_4h_1d.sql").read_text(encoding="utf-8")
    check = "CHECK (timeframe IN ('1m','5m','15m','1h','4h','1d'))"
    assert check in schema and check in migration
    assert "DROP CONSTRAINT IF EXISTS candles_timeframe_allowed" in schema
