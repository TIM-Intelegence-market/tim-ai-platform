"""Signed net_delta: sellers as aggressors reach the Orderflow Interpretation Engine.

net_delta = aggressive buy volume - aggressive sell volume, so a negative value
is valid input. Before this fix OrderflowInputs rejected it, which made the
seller branch (SELLERS, aggressive_sellers_*, PASSIVE_BUYERS) unreachable and
crashed Pipeline.run for every seller-dominated input.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.models.market_data import Candle, Trade
from src.orderflow_scenario.adapters import GenericOrderflowAdapter, MMTScreenshotAdapter, MMTStructuredDataAdapter
from src.orderflow_scenario.domain import DecisionStatus, MarketContext, OrderflowStatementKind
from src.orderflow_scenario.engines.orderflow_interpretation import OrderflowInputs, OrderflowInterpretationEngine
from src.orderflow_scenario.engines.pipeline import Pipeline, PipelineInputs

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


def two_candles(previous_close: float, last_close: float) -> tuple[Candle, Candle]:
    return (
        candle(58, 100.0, 100.5, min(previous_close, 100.0) - 0.1, previous_close),
        candle(59, previous_close, max(previous_close, last_close) + 0.1, min(previous_close, last_close) - 0.1, last_close),
    )


def statement_texts(result, kind: OrderflowStatementKind) -> list[str]:
    return [s.text for s in result.statements if s.kind == kind]


# --- 1. Input validation -------------------------------------------------------

def test_negative_net_delta_is_accepted():
    inputs = OrderflowInputs(net_delta=Decimal("-120"))
    assert inputs.net_delta == Decimal("-120")


@pytest.mark.parametrize("field", ["aggressive_buy_volume", "aggressive_sell_volume", "total_volume"])
def test_volumes_stay_non_negative(field: str):
    with pytest.raises(ValueError, match=f"{field} cannot be negative"):
        OrderflowInputs(**{field: Decimal("-1")})


# --- 2. Engine: seller branch ----------------------------------------------------

def test_negative_delta_with_falling_price_means_sellers_drive_price_down():
    result = OrderflowInterpretationEngine().evaluate(
        OrderflowInputs(candles=two_candles(100.0, 99.0), net_delta=Decimal("-120"))
    )
    assert result.aggressive_side == "SELLERS"
    assert result.price_response == "DOWN"
    assert "net_delta=-120 aggressive_side=SELLERS" in statement_texts(result, OrderflowStatementKind.OBSERVATION)
    assert statement_texts(result, OrderflowStatementKind.INTERPRETATION) == ["aggressive_sellers_drive_price_down"]
    assert statement_texts(result, OrderflowStatementKind.HYPOTHESIS) == []
    assert result.absorption_hypothesis is None
    assert result.absorption_confirmed is False


def test_negative_delta_with_rising_price_hypothesises_passive_buyers():
    result = OrderflowInterpretationEngine().evaluate(
        OrderflowInputs(candles=two_candles(100.0, 101.0), net_delta=Decimal("-120"))
    )
    assert result.aggressive_side == "SELLERS"
    assert result.price_response == "UP"
    assert statement_texts(result, OrderflowStatementKind.INTERPRETATION) == ["aggressive_sellers_limited_price_progress"]
    assert statement_texts(result, OrderflowStatementKind.HYPOTHESIS) == ["passive_buyers_absorb_market_sells"]
    assert result.absorption_hypothesis == "PASSIVE_BUYERS"
    assert result.absorption_confirmed is False
    assert statement_texts(result, OrderflowStatementKind.REFUTATION) == []


def test_passive_buyer_absorption_is_confirmed_by_delta_divergence():
    result = OrderflowInterpretationEngine().evaluate(
        OrderflowInputs(candles=two_candles(100.0, 101.0), net_delta=Decimal("-120"), delta_divergence=True)
    )
    assert result.absorption_hypothesis == "PASSIVE_BUYERS"
    assert result.absorption_confirmed is True
    assert "absorption_supported_by_delta_divergence" in statement_texts(result, OrderflowStatementKind.CONFIRMATION)


def test_seller_branch_mirrors_buyer_branch():
    """Same magnitude, opposite sign: the buyer and seller readings are symmetric."""
    engine = OrderflowInterpretationEngine()
    for previous, last, buyer_text, seller_text in (
        (100.0, 101.0, "aggressive_buyers_drive_price_up", "aggressive_sellers_limited_price_progress"),
        (100.0, 99.0, "aggressive_buyers_limited_price_progress", "aggressive_sellers_drive_price_down"),
    ):
        buyers = engine.evaluate(OrderflowInputs(candles=two_candles(previous, last), net_delta=Decimal("120")))
        sellers = engine.evaluate(OrderflowInputs(candles=two_candles(previous, last), net_delta=Decimal("-120")))
        assert statement_texts(buyers, OrderflowStatementKind.INTERPRETATION) == [buyer_text]
        assert statement_texts(sellers, OrderflowStatementKind.INTERPRETATION) == [seller_text]
    assert engine.evaluate(OrderflowInputs(candles=two_candles(100.0, 99.0), net_delta=Decimal("120"))).absorption_hypothesis == "PASSIVE_SELLERS"


# --- 3. Pipeline: scenario, probability, decision -------------------------------

def _pipeline_candles(previous_close: float, last_close: float) -> tuple[Candle, ...]:
    # Alternating small bodies: flat zero-body candles are not realistic input.
    base = tuple(candle(i, 100.0 - 0.1 * (i % 2), 100.5, 99.5, 100.0 - 0.1 * ((i + 1) % 2)) for i in range(58))
    return base + (
        candle(58, 100.0, 100.0, min(previous_close, 100.0) - 0.1, previous_close),
        candle(59, previous_close, max(previous_close, last_close) + 0.1, min(previous_close, last_close) - 0.05, last_close),
    )


def _run(net_delta: str, previous_close: float, last_close: float, delta_divergence: bool | None = None):
    trades = tuple(Trade("BTCUSDT", last_close, 0.01, NOW, trade_id=i, buyer_is_maker=i % 2 == 0) for i in range(50))
    return Pipeline().run(
        PipelineInputs(
            market_context=MarketContext("BTCUSDT", "BINANCE", "FUTURES", "4H", NOW),
            candles=_pipeline_candles(previous_close, last_close),
            trades=trades,
            price_now=Decimal(str(last_close)),
            price_timestamp=NOW,
            net_delta=Decimal(net_delta),
            delta_divergence=delta_divergence,
            observed_at=NOW,
        )
    )


def test_pipeline_runs_with_negative_delta_and_falling_price():
    analysis = _run("-120", 100.0, 99.0)
    assert analysis.data_quality.status == "PASS"
    assert analysis.orderflow.aggressive_side == "SELLERS"
    assert analysis.orderflow.price_response == "DOWN"
    assert "aggressive_sellers_drive_price_down" in [s.text for s in analysis.orderflow.statements]
    assert analysis.decision.status == DecisionStatus.NO_TRADE


def test_pipeline_seller_absorption_reaches_scenarios_and_probability():
    """Near the range low with rising price: sellers absorbed by passive buyers.

    Intended change: the LONG sweep/reversal scenario (B) now receives the
    seller evidence and the SELLERS penalty in the heuristic probability.
    Without confirmations the decision stays NO_TRADE.
    """
    sellers = _run("-120", 99.0, 99.2)
    buyers = _run("120", 99.0, 99.2)
    assert sellers.orderflow.aggressive_side == "SELLERS"
    assert sellers.orderflow.absorption_hypothesis == "PASSIVE_BUYERS"

    [sweep] = [s for s in sellers.scenarios if s.scenario_id == "B"]
    assert "delta_strongly_negative_without_follow_through" in sweep.evidence_for
    assert "absorption_hypothesis_passive_buyers" in sweep.evidence_for
    [sweep_buyers] = [s for s in buyers.scenarios if s.scenario_id == "B"]
    assert "absorption_hypothesis_passive_buyers" not in sweep_buyers.evidence_for
    # LONG with aggressive sellers: -0.06 instead of +0.08, partly offset by the extra evidence.
    assert sweep.score < sweep_buyers.score

    assert sellers.decision.status == DecisionStatus.NO_TRADE
    assert "NO_SCENARIO_CONFIRMED" in sellers.decision.reason_codes

    confirmed = _run("-120", 99.0, 99.2, delta_divergence=True)
    assert confirmed.orderflow.absorption_confirmed is True
    [sweep_confirmed] = [s for s in confirmed.scenarios if s.scenario_id == "B"]
    assert sweep_confirmed.score > sweep.score


# --- 4. Adapters pass the sign through unchanged ---------------------------------

@pytest.mark.parametrize(
    "adapter",
    [GenericOrderflowAdapter(), MMTStructuredDataAdapter(), MMTScreenshotAdapter()],
    ids=lambda adapter: adapter.adapter_kind,
)
def test_adapters_keep_negative_net_delta(adapter):
    adapted = adapter.adapt({"symbol": "BTCUSDT", "candles": [], "net_delta": "-12.5"}, observed_at=NOW)
    assert adapted.net_delta == Decimal("-12.5")
