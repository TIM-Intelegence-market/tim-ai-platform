"""A confirmed scenario reaches a DRAFT trade plan whose first target is 1.5R (decided 2026-09-30)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.models.market_data import Candle, Trade
from src.orderflow_scenario.domain import ConfirmationState, Direction, MarketContext
from src.orderflow_scenario.engines.confirmation import ConfirmationUpdate
from src.orderflow_scenario.engines.pipeline import Pipeline, PipelineInputs

START = datetime(2026, 9, 28, tzinfo=timezone.utc)
NOW = START + timedelta(days=6)


def inputs(**extra) -> PipelineInputs:
    # A rising 4H zigzag (higher highs and lows) with aggressive buyers: TREND_UP, LONG breakout proposed.
    wave = (0, 2, 4, 3, 1, 2)
    mids = [100 + i * 0.8 + wave[i % 6] for i in range(36)]
    candles = tuple(
        Candle("BTCUSDT", "4H", START + timedelta(hours=4 * i), START + timedelta(hours=4 * i + 4), m - 0.3, m + 1, m - 1, m + 0.3, 10, 5)
        for i, m in enumerate(mids)
    )
    last = candles[-1].close
    trades = tuple(Trade("BTCUSDT", last, 1.0, NOW + timedelta(seconds=i), i, False) for i in range(5))
    return PipelineInputs(
        market_context=MarketContext("BTCUSDT", "BINANCE", "FUTURES", "4H", NOW),
        candles=candles,
        trades=trades,
        price_now=Decimal(str(last)),
        price_timestamp=NOW,
        net_delta=Decimal("50"),
        aggressive_buy_volume=Decimal("60"),
        aggressive_sell_volume=Decimal("10"),
        total_volume=Decimal("70"),
        observed_at=NOW,
        structured=True,
        **extra,
    )


def confirmed_run():
    proposed = Pipeline().run(inputs())
    long = next(s for s in proposed.scenarios if s.direction == Direction.LONG)
    update = ConfirmationUpdate(long.scenario_id, long.mandatory_confirmations, (), ())
    return long, Pipeline().run(inputs(confirmation_updates=(update,)))


def test_confirmed_scenario_builds_a_trade_plan():
    long, analysis = confirmed_run()
    assert next(s for s in analysis.scenarios if s.scenario_id == long.scenario_id).state == ConfirmationState.CONFIRMED
    decision = analysis.to_dict()["decision"]
    assert "TRADE_PLAN_NOT_BUILDABLE" not in decision["reason_codes"]
    plan = decision["trade_plan"]
    assert plan is not None
    assert analysis.market_state.primary.value == "TREND_UP"
    assert decision["status"] == "TRADE_PLAN"
    assert plan["entry_model"] == "LIMIT_RETEST"


def test_first_target_is_one_and_a_half_r():
    _, analysis = confirmed_run()
    plan = analysis.to_dict()["decision"]["trade_plan"]
    entry = Decimal(str(plan["entry_zone_low"]))
    risk = entry - Decimal(str(plan["stop_loss"]))
    assert Decimal(str(plan["target_1"])) == entry + risk * Decimal("1.5")
    assert Decimal(str(plan["target_2"])) == entry + risk * Decimal("2")
    assert Decimal(str(plan["target_3"])) == entry + risk * Decimal("3")
    assert Decimal(str(plan["expected_reward_risk"])) >= Decimal("1.5")
