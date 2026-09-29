"""Edge cases in the orderflow scenario engines.

1. net_delta == 0 has no aggressive side, so it must not be read as sellers
   (it used to yield aggressive_sellers_* and a PASSIVE_BUYERS hypothesis).
2. Scenario A referenced EntryModel.RETEST, which does not exist, so every
   breakout setup crashed with AttributeError.
3. AuctionStateEngine divided by the mean body of the first three of the last
   six candles and crashed with ZeroDivisionError when those were bodyless.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.models.market_data import Candle, Trade
from src.orderflow_scenario.domain import AuctionStateKind, EntryModel, MarketContext, OrderflowStatementKind
from src.orderflow_scenario.engines.market_state import AuctionStateEngine
from src.orderflow_scenario.engines.orderflow_interpretation import OrderflowInputs, OrderflowInterpretationEngine
from src.orderflow_scenario.engines.pipeline import Pipeline, PipelineInputs
from src.orderflow_scenario.engines.scenario_generator import ScenarioGenerator

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def candle(index: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe="4H",
        open_time=NOW - timedelta(minutes=240 * (60 - index)),
        close_time=NOW - timedelta(minutes=240 * (59 - index)),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100.0,
        trade_count=1000,
        closed=True,
    )


def texts(result, kind: OrderflowStatementKind) -> list[str]:
    return [s.text for s in result.statements if s.kind == kind]


# --- 1. Zero delta -----------------------------------------------------------------

def test_zero_delta_with_price_move_is_neutral_without_interpretation():
    engine = OrderflowInterpretationEngine()
    for last_close, response in ((101.0, "UP"), (99.0, "DOWN")):
        result = engine.evaluate(
            OrderflowInputs(
                candles=(candle(58, 100.0, 100.5, 99.9, 100.0), candle(59, 100.0, 101.1, 98.9, last_close)),
                net_delta=Decimal("0"),
                delta_divergence=True,
            )
        )
        assert result.aggressive_side == "NEUTRAL"
        assert result.price_response == response
        assert texts(result, OrderflowStatementKind.INTERPRETATION) == []
        assert texts(result, OrderflowStatementKind.HYPOTHESIS) == []
        assert texts(result, OrderflowStatementKind.CONFIRMATION) == []
        assert result.absorption_hypothesis is None
        assert result.absorption_confirmed is False


def test_positive_delta_still_interpreted():
    result = OrderflowInterpretationEngine().evaluate(
        OrderflowInputs(
            candles=(candle(58, 100.0, 100.5, 99.9, 100.0), candle(59, 100.0, 101.1, 99.9, 101.0)),
            net_delta=Decimal("120"),
        )
    )
    assert texts(result, OrderflowStatementKind.INTERPRETATION) == ["aggressive_buyers_drive_price_up"]


# --- 2. Scenario A (breakout) --------------------------------------------------------

def test_breakout_scenario_is_built_with_limit_retest_entry():
    # Small alternating bodies, then a close at the top of the range.
    candles = tuple(candle(i, 100.0 - 0.1 * (i % 2), 100.5, 99.5, 100.0 - 0.1 * ((i + 1) % 2)) for i in range(59))
    candles += (candle(59, 100.0, 100.6, 99.9, 100.5),)
    trades = tuple(Trade("BTCUSDT", 100.5, 0.01, NOW, trade_id=i, buyer_is_maker=i % 2 == 0) for i in range(50))
    analysis = Pipeline().run(
        PipelineInputs(
            market_context=MarketContext("BTCUSDT", "BINANCE", "FUTURES", "4H", NOW),
            candles=candles,
            trades=trades,
            price_now=Decimal("100.5"),
            price_timestamp=NOW,
            net_delta=Decimal("120"),
            observed_at=NOW,
        )
    )
    [breakout] = [s for s in analysis.scenarios if s.scenario_id == "A"]
    assert breakout.trade_template["entry_model"] == EntryModel.LIMIT_RETEST.value


def test_scenario_generator_has_no_unknown_entry_models():
    """Every EntryModel.<NAME> in the generator exists in the enum."""
    import inspect
    import re

    source = inspect.getsource(ScenarioGenerator)
    used = set(re.findall(r"EntryModel\.([A-Z_]+)", source))
    assert used and used <= set(EntryModel.__members__)


# --- 3. Bodyless candles in the auction state ---------------------------------------

def test_bodyless_candles_before_expansion_do_not_divide_by_zero():
    dojis = [candle(i, 100.0, 100.5, 99.5, 100.0) for i in range(3)]
    bodies = [candle(3 + i, 100.0, 101.5, 99.5, 101.0) for i in range(3)]
    state = AuctionStateEngine().evaluate(dojis + bodies)
    assert AuctionStateKind.RANGE_EXTENSION in state.secondary
    assert "range_extension" in state.evidence


def test_range_extension_threshold_unchanged_for_real_bodies():
    small = [candle(i, 100.0, 100.5, 99.5, 100.2) for i in range(3)]
    # 0.3 / 0.2 = 1.5 is not > 1.5; 0.4 / 0.2 = 2 is.
    at_threshold = [candle(3 + i, 100.0, 100.5, 99.5, 100.3) for i in range(3)]
    above = [candle(3 + i, 100.0, 100.5, 99.5, 100.4) for i in range(3)]
    engine = AuctionStateEngine()
    assert AuctionStateKind.RANGE_EXTENSION not in engine.evaluate(small + at_threshold).secondary
    assert AuctionStateKind.RANGE_EXTENSION in engine.evaluate(small + above).secondary
