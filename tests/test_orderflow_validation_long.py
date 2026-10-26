from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.models.market_data import Candle
from src.orderflow.validation_long import LONG_HORIZONS, LONG_VALIDATION_VERSION, OrderflowLongValidationEngine

AT = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
OBS = {"observation_id": "ofobs_long", "symbol": "BTCUSDT", "observed_at": AT.isoformat(), "input_hash": "b" * 64}
ROOT = Path(__file__).resolve().parents[1]


def candle(open_minute: int, close: float, high: float | None = None, low: float | None = None, symbol: str = "BTCUSDT", timeframe: str = "1m") -> Candle:
    open_time = AT + timedelta(minutes=open_minute)
    high = close if high is None else high
    low = close if low is None else low
    return Candle(symbol, timeframe, open_time, open_time + timedelta(minutes=1), close, max(high, close), min(low, close), close, 1.0, 1)


def series(first_minute: int, last_minute: int, price: float = 100.0) -> list[Candle]:
    return [candle(m, price) for m in range(first_minute, last_minute + 1)]


def test_horizons_are_one_four_and_twentyfour_hours():
    assert LONG_HORIZONS == (60, 240, 1440)
    assert LONG_VALIDATION_VERSION == "long-1.0.0"


def test_baseline_is_last_candle_closed_at_or_before_observation():
    # candle -1 closes exactly at AT (allowed), candle 0 closes after AT (not allowed as baseline)
    candles = [candle(-2, 90), candle(-1, 100), candle(0, 150)] + series(1, 60, 110)
    result = OrderflowLongValidationEngine().validate(OBS, candles, AT + timedelta(minutes=60))
    assert result is not None
    assert result.baseline_price == Decimal("100") and result.baseline_close_time == AT


def test_full_hour_is_complete_and_measures_close_and_excursions():
    candles = [candle(-1, 100)] + series(0, 59, 102)
    candles[10] = candle(9, 102, high=105, low=98)
    result = OrderflowLongValidationEngine().validate(OBS, candles, AT + timedelta(minutes=60))
    assert result is not None and [h.minutes for h in result.horizons] == [60]
    hour = result.horizons[0]
    assert hour.complete and hour.candle_count == 60 and hour.expected_candles == 60
    assert hour.price_change_percent == Decimal("2") and hour.max_high_percent == Decimal("5") and hour.min_low_percent == Decimal("-2")
    assert not result.complete  # 4h and 24h not reachable yet
    assert result.validated_through == AT + timedelta(minutes=60)


def test_gap_in_candles_marks_horizon_incomplete_but_keeps_measurement():
    candles = [candle(-1, 100)] + series(0, 59, 101)
    del candles[20:25]  # five missing minutes
    result = OrderflowLongValidationEngine().validate(OBS, candles, AT + timedelta(minutes=60))
    hour = result.horizons[0]
    assert not hour.complete and hour.candle_count == 55 and hour.expected_candles == 60
    assert hour.to_dict()["coverage_percent"].startswith("91.66")
    assert hour.price_change_percent == Decimal("1")


def test_unreached_horizons_are_skipped_and_future_candles_ignored():
    candles = [candle(-1, 100)] + series(0, 300, 100)
    result = OrderflowLongValidationEngine().validate(OBS, candles, AT + timedelta(minutes=240))
    assert [h.minutes for h in result.horizons] == [60, 240]
    assert all(h.complete for h in result.horizons) and not result.complete


def test_all_three_horizons_complete_and_hash_is_order_independent():
    candles = [candle(-1, 100)] + series(0, 1439, 100)
    engine = OrderflowLongValidationEngine()
    first = engine.validate(OBS, candles, AT + timedelta(minutes=1440))
    second = engine.validate(OBS, list(reversed(candles)), AT + timedelta(minutes=1440))
    assert first == second and first.complete and [h.minutes for h in first.horizons] == [60, 240, 1440]
    assert first.validation_hash == second.validation_hash and len(first.validation_hash) == 64


def test_no_classification_is_stored():
    candles = [candle(-1, 100)] + series(0, 59, 130)
    result = OrderflowLongValidationEngine().validate(OBS, candles, AT + timedelta(minutes=60)).to_dict()
    assert "outcome" not in result and all("outcome" not in h for h in result["horizons"])
    assert result["mode"] == "OBSERVE" and result["validation_version"] == "long-1.0.0"


def test_returns_none_without_baseline_or_before_first_horizon():
    engine = OrderflowLongValidationEngine()
    assert engine.validate(OBS, series(0, 59), AT + timedelta(minutes=60)) is None  # no candle closed before AT
    assert engine.validate(OBS, [candle(-1, 100)] + series(0, 30), AT + timedelta(minutes=30)) is None


@pytest.mark.parametrize("bad", [[candle(0, 100, symbol="ETHUSDT")], [candle(0, 100, timeframe="5m")], [candle(0, 100), candle(0, 100)]])
def test_rejects_mixed_symbols_wrong_timeframe_and_duplicates(bad):
    with pytest.raises(ValueError):
        OrderflowLongValidationEngine().validate(OBS, [candle(-1, 100)] + bad, AT + timedelta(minutes=60))


def test_schema_and_migration_define_the_same_long_table():
    schema = (ROOT / "src/database/schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "src/database/migrations/008_orderflow_validations_long.sql").read_text(encoding="utf-8")
    start = migration.index("CREATE TABLE IF NOT EXISTS orderflow_validations_long")
    end = migration.index("COMMIT;")
    assert migration[start:end].strip() in schema
    assert "validation_version='long-1.0.0'" in schema
