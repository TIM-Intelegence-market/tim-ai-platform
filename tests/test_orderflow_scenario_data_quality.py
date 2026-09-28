from datetime import datetime, timedelta, timezone

import pytest

from src.models.market_data import Candle, Trade
from src.orderflow_scenario.engines.data_quality import DataQualityGate, DataQualityInputs

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def candle(index: int, price: float = 100.0, closed: bool = True) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe="4H",
        open_time=NOW - timedelta(minutes=240 * (60 - index)),
        close_time=NOW - timedelta(minutes=240 * (59 - index)),
        open=price,
        high=price + 0.5,
        low=price - 0.5,
        close=price,
        volume=100.0,
        trade_count=1000,
        closed=closed,
    )


def trades(count: int) -> tuple[Trade, ...]:
    return tuple(
        Trade("BTCUSDT", 100.0, 0.01, NOW, trade_id=index, buyer_is_maker=index % 2 == 0)
        for index in range(count)
    )


def good_inputs() -> DataQualityInputs:
    return DataQualityInputs(
        candles=tuple(candle(i) for i in range(60)),
        trades=trades(50),
        price_now=100.0,
        price_timestamp=NOW,
        structured=True,
    )


def test_gate_passes_on_complete_structured_input():
    report = DataQualityGate().evaluate(good_inputs(), observed_at=NOW)
    assert report.status == "PASS"
    assert report.confidence >= 0.5
    assert report.missing_fields == ()
    assert report.passed()


def test_gate_rejects_missing_price_as_insufficient():
    inputs = good_inputs()
    inputs = DataQualityInputs(
        candles=inputs.candles,
        trades=inputs.trades,
        price_now=None,
        price_timestamp=None,
    )
    report = DataQualityGate().evaluate(inputs, observed_at=NOW)
    assert report.status == "INSUFFICIENT_DATA"
    assert not report.passed()
    assert "price_now" in report.missing_fields


def test_gate_marks_missing_trades_and_short_history():
    inputs = DataQualityInputs(candles=tuple(candle(i) for i in range(5)), trades=(), price_now=100.0, price_timestamp=NOW)
    report = DataQualityGate().evaluate(inputs, observed_at=NOW)
    assert report.status == "PARTIAL"
    assert "trades" in report.missing_fields


def test_stale_price_is_a_problem():
    inputs = good_inputs()
    inputs = DataQualityInputs(
        candles=inputs.candles,
        trades=inputs.trades,
        price_now=100.0,
        price_timestamp=NOW - timedelta(minutes=180),
    )
    report = DataQualityGate().evaluate(inputs, observed_at=NOW)
    assert any("stale_price" in item for item in report.problems)
    assert report.status != "PASS"



def test_screenshot_input_is_never_fully_trusted():
    inputs = DataQualityInputs(
        candles=tuple(candle(i) for i in range(60)),
        trades=trades(50),
        price_now=100.0,
        price_timestamp=NOW,
        structured=False,
        screenshot_confidence=0.5,
    )
    report = DataQualityGate().evaluate(inputs, observed_at=NOW)
    assert report.status == "PARTIAL"
    assert any("screenshot" in item for item in report.problems)
    assert "prices_from_screenshot" in report.estimated_fields
    assert report.confidence < 0.7


def test_mixed_venues_and_unverified_delta_are_problems():
    inputs = DataQualityInputs(
        candles=tuple(candle(i) for i in range(60)),
        trades=trades(50),
        price_now=100.0,
        price_timestamp=NOW,
        venue_mixed=True,
        delta_definition_verified=False,
    )
    report = DataQualityGate().evaluate(inputs, observed_at=NOW)
    assert any("mixed_venues" in item for item in report.problems)
    assert any("delta_definition_unverified" in item for item in report.problems)


def test_confidence_stays_within_unit_bounds():
    gate = DataQualityGate()
    for index in range(100):
        inputs = good_inputs()
        inputs = DataQualityInputs(
            candles=inputs.candles,
            trades=inputs.trades,
            price_now=100.0,
            price_timestamp=NOW,
            structured=index % 2 == 0,
            venue_mixed=index % 3 == 0,
        )
        report = gate.evaluate(inputs, observed_at=NOW)
        assert 0 <= report.confidence <= 1


@pytest.mark.parametrize("minutes", [0, 1, 1.5, 2])
def test_price_age_within_limit_passes(minutes):
    inputs = good_inputs()
    inputs = DataQualityInputs(
        candles=inputs.candles,
        trades=inputs.trades,
        price_now=100.0,
        price_timestamp=NOW - timedelta(minutes=minutes),
    )
    report = DataQualityGate().evaluate(inputs, observed_at=NOW)
    if minutes <= 1.5:
        assert report.status == "PASS"
    else:
        assert report.status == "PARTIAL"
        assert any("stale_price" in item for item in report.problems)
