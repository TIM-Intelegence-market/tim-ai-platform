"""Absorption vs. exhaustion: the Orderflow Interpretation Engine keeps them apart.

Rules (docs/knowledge/ORDERFLOW_REGELN.md, R1-R4):
R1 delta against price on normal/heavy volume   -> ABSORPTION (passive side takes the other side)
R2 directional delta, flat price, heavy volume  -> ABSORPTION
R3 delta against price on thin volume           -> EXHAUSTION (no absorber needed, aggressor ran out)
R4 delta with price, thin volume, shrinking range -> EXHAUSTION (fading into the extreme)
Exhaustion is confirmed by a fading delta series or a delta flip, refuted by an
expanding delta. Absorption keeps its confirmation via delta_divergence.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.models.market_data import Candle, Trade
from src.orderflow_scenario.adapters import GenericOrderflowAdapter
from src.orderflow_scenario.domain import MarketContext, OrderflowInterpretation, OrderflowStatementKind
from src.orderflow_scenario.engines.orderflow_interpretation import (
    OrderflowInputs,
    OrderflowInterpretationEngine,
    effort_context,
)
from src.orderflow_scenario.engines.pipeline import Pipeline, PipelineInputs
from src.orderflow_scenario.report import build_report

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
ENGINE = OrderflowInterpretationEngine()


def candle(index: int, open_: float, high: float, low: float, close: float, volume: float = 100.0) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe="4H",
        open_time=NOW - timedelta(minutes=240 * (60 - index)),
        close_time=NOW - timedelta(minutes=240 * (59 - index)),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        trade_count=1000,
        closed=True,
    )


# Close of the last baseline candle (five alternating candles end at 99.9).
FLAT_CLOSE = 99.9


def series(last_close: float, last_volume: float, last_range: float = 1.0, baseline: int = 5) -> tuple[Candle, ...]:
    """Baseline candles (volume 100, range 1.0, closes 100.0/99.9) plus a last candle."""
    base = tuple(candle(50 + i, 100.0 - 0.1 * (i % 2), 100.5, 99.5, 100.0 - 0.1 * ((i + 1) % 2)) for i in range(baseline))
    previous_close = base[-1].close
    half = last_range / 2
    mid = (previous_close + last_close) / 2
    high = max(mid + half, previous_close, last_close)
    low = min(mid - half, previous_close, last_close)
    return base + (candle(59, previous_close, high, low, last_close, volume=last_volume),)


def texts(result, kind: OrderflowStatementKind) -> list[str]:
    return [s.text for s in result.statements if s.kind == kind]


# --- effort context --------------------------------------------------------------

def test_effort_context_needs_a_baseline():
    assert effort_context(series(99.0, 150.0)[-2:]) == (None, None)
    volume_ratio, range_ratio = effort_context(series(99.0, 150.0, last_range=0.5))
    assert volume_ratio == Decimal("1.5")
    assert range_ratio is not None and range_ratio < Decimal("1.2")


def test_two_candles_keep_the_classic_absorption_read():
    result = ENGINE.evaluate(OrderflowInputs(candles=series(99.0, 100.0)[-2:], net_delta=Decimal("120")))
    assert result.reaction == "ABSORPTION"
    assert result.absorption_hypothesis == "PASSIVE_SELLERS"
    assert result.exhaustion_hypothesis is None
    assert "absorption_effort_high_volume" not in texts(result, OrderflowStatementKind.INTERPRETATION)


# --- R1 / R3: delta against price ----------------------------------------------------

def test_r1_heavy_volume_without_progress_is_absorption():
    result = ENGINE.evaluate(OrderflowInputs(candles=series(99.0, 150.0), net_delta=Decimal("120")))
    assert result.reaction == "ABSORPTION"
    assert result.absorption_hypothesis == "PASSIVE_SELLERS"
    assert result.exhaustion_hypothesis is None
    assert "passive_sellers_absorb_market_buys" in texts(result, OrderflowStatementKind.HYPOTHESIS)
    assert "absorption_effort_high_volume" in texts(result, OrderflowStatementKind.INTERPRETATION)
    assert texts(result, OrderflowStatementKind.REFUTATION) == []


def test_r3_thin_volume_without_progress_is_exhaustion_not_absorption():
    result = ENGINE.evaluate(OrderflowInputs(candles=series(99.0, 40.0), net_delta=Decimal("120")))
    assert result.reaction == "EXHAUSTION"
    assert result.absorption_hypothesis is None
    assert result.exhaustion_hypothesis == "BUYERS_EXHAUSTED"
    assert result.exhaustion_confirmed is False
    assert "absorption_refuted_thin_volume" in texts(result, OrderflowStatementKind.REFUTATION)
    assert "aggressive_buyers_exhausted_thin_volume" in texts(result, OrderflowStatementKind.HYPOTHESIS)
    assert "passive_sellers_absorb_market_buys" not in texts(result, OrderflowStatementKind.HYPOTHESIS)
    assert "delta_series" in result.missing_data


def test_same_delta_and_price_differ_only_by_effort():
    """The old code called both of these absorption; only volume separates them."""
    absorbed = ENGINE.evaluate(OrderflowInputs(candles=series(101.0, 160.0), net_delta=Decimal("-120")))
    exhausted = ENGINE.evaluate(OrderflowInputs(candles=series(101.0, 50.0), net_delta=Decimal("-120")))
    assert (absorbed.reaction, absorbed.absorption_hypothesis) == ("ABSORPTION", "PASSIVE_BUYERS")
    assert (exhausted.reaction, exhausted.exhaustion_hypothesis) == ("EXHAUSTION", "SELLERS_EXHAUSTED")


def test_delta_divergence_still_confirms_absorption_only():
    absorbed = ENGINE.evaluate(OrderflowInputs(candles=series(99.0, 150.0), net_delta=Decimal("120"), delta_divergence=True))
    exhausted = ENGINE.evaluate(OrderflowInputs(candles=series(99.0, 40.0), net_delta=Decimal("120"), delta_divergence=True))
    assert absorbed.absorption_confirmed is True
    assert exhausted.absorption_confirmed is False and exhausted.exhaustion_confirmed is False


# --- R4: delta with price, fading -----------------------------------------------------

def test_r4_continuation_on_normal_volume():
    result = ENGINE.evaluate(OrderflowInputs(candles=series(101.0, 100.0), net_delta=Decimal("120")))
    assert result.reaction == "CONTINUATION"
    assert result.absorption_hypothesis is None and result.exhaustion_hypothesis is None


def test_r4_thin_volume_and_shrinking_range_is_exhaustion():
    result = ENGINE.evaluate(OrderflowInputs(candles=series(100.4, 40.0, last_range=0.5), net_delta=Decimal("120")))
    assert result.reaction == "EXHAUSTION"
    assert result.exhaustion_hypothesis == "BUYERS_EXHAUSTED"
    assert "aggressive_buyers_fading_into_extreme" in texts(result, OrderflowStatementKind.HYPOTHESIS)


def test_r4_thin_volume_with_wide_range_stays_continuation():
    result = ENGINE.evaluate(OrderflowInputs(candles=series(101.0, 40.0, last_range=1.5), net_delta=Decimal("120")))
    assert result.reaction == "CONTINUATION"


@pytest.mark.parametrize(
    "delta_series, confirmation",
    [
        ((Decimal("90"), Decimal("60"), Decimal("20")), "exhaustion_supported_by_fading_delta"),
        ((Decimal("60"), Decimal("-15")), "exhaustion_supported_by_delta_flip"),
    ],
)
def test_exhaustion_is_confirmed_by_delta_series(delta_series, confirmation):
    plain = ENGINE.evaluate(OrderflowInputs(candles=series(100.4, 40.0, last_range=0.5), net_delta=Decimal("120")))
    confirmed = ENGINE.evaluate(
        OrderflowInputs(candles=series(100.4, 40.0, last_range=0.5), net_delta=Decimal("120"), delta_series=delta_series)
    )
    assert confirmed.exhaustion_confirmed is True
    assert confirmation in texts(confirmed, OrderflowStatementKind.CONFIRMATION)
    assert confirmed.confidence > plain.confidence
    assert "delta_series" not in confirmed.missing_data


def test_expanding_delta_refutes_exhaustion():
    result = ENGINE.evaluate(
        OrderflowInputs(
            candles=series(100.4, 40.0, last_range=0.5),
            net_delta=Decimal("120"),
            delta_series=(Decimal("20"), Decimal("40"), Decimal("80")),
        )
    )
    assert result.exhaustion_hypothesis is None
    assert result.exhaustion_confirmed is False
    assert result.reaction == "CONTINUATION"
    assert "exhaustion_refuted_delta_expanding" in texts(result, OrderflowStatementKind.REFUTATION)


def test_seller_exhaustion_uses_the_seller_sign():
    result = ENGINE.evaluate(
        OrderflowInputs(
            candles=series(99.6, 40.0, last_range=0.5),
            net_delta=Decimal("-120"),
            delta_series=(Decimal("-90"), Decimal("-60"), Decimal("-20")),
        )
    )
    assert result.exhaustion_hypothesis == "SELLERS_EXHAUSTED"
    assert result.exhaustion_confirmed is True


# --- R2: flat price ------------------------------------------------------------------

def test_r2_flat_price_on_heavy_volume_is_absorption():
    result = ENGINE.evaluate(OrderflowInputs(candles=series(FLAT_CLOSE, 180.0), net_delta=Decimal("-120")))
    assert result.price_response == "FLAT"
    assert result.reaction == "ABSORPTION"
    assert result.absorption_hypothesis == "PASSIVE_BUYERS"
    assert "passive_buyers_absorb_market_sells_flat_price" in texts(result, OrderflowStatementKind.HYPOTHESIS)


def test_flat_price_on_normal_volume_stays_unresolved():
    result = ENGINE.evaluate(OrderflowInputs(candles=series(FLAT_CLOSE, 100.0), net_delta=Decimal("-120")))
    assert result.reaction == "UNRESOLVED"
    assert result.absorption_hypothesis is None and result.exhaustion_hypothesis is None


def test_zero_delta_has_no_reaction():
    result = ENGINE.evaluate(OrderflowInputs(candles=series(99.0, 40.0), net_delta=Decimal("0")))
    assert result.reaction == "UNRESOLVED"
    assert result.exhaustion_hypothesis is None


# --- domain contract -----------------------------------------------------------------

def test_domain_rejects_both_reads_at_once():
    with pytest.raises(ValueError, match="mutually exclusive"):
        OrderflowInterpretation(
            aggressive_side="BUYERS",
            price_response="DOWN",
            absorption_hypothesis="PASSIVE_SELLERS",
            absorption_confirmed=False,
            open_interest_interpretation=None,
            statements=(),
            confidence=Decimal("0.5"),
            missing_data=(),
            exhaustion_hypothesis="BUYERS_EXHAUSTED",
        )


def test_to_dict_carries_the_reaction():
    result = ENGINE.evaluate(OrderflowInputs(candles=series(99.0, 40.0), net_delta=Decimal("120")))
    payload = result.to_dict()
    assert payload["reaction"] == "EXHAUSTION"
    assert payload["exhaustion_hypothesis"] == "BUYERS_EXHAUSTED"
    assert payload["exhaustion_confirmed"] is False
    assert payload["absorption_hypothesis"] is None


# --- adapter, pipeline, report --------------------------------------------------------

def test_generic_adapter_reads_delta_series():
    adapted = GenericOrderflowAdapter().adapt(
        {
            "symbol": "BTCUSDT",
            "venue": "BINANCE",
            "timeframe": "4H",
            "observed_at": NOW.isoformat(),
            "candles": [],
            "net_delta": "120",
            "delta_series": ["90", "60", 20],
        }
    )
    assert adapted.delta_series == (Decimal("90"), Decimal("60"), Decimal("20"))
    assert GenericOrderflowAdapter().adapt({"symbol": "BTCUSDT", "observed_at": NOW.isoformat(), "candles": []}).delta_series is None


def _pipeline_candles(last_close: float, last_high: float, last_low: float, last_volume: float) -> tuple[Candle, ...]:
    """58 baseline candles, a push to 99.0 (low 98.9), then the candle under test at the range low."""
    base = tuple(candle(i, 100.0 - 0.1 * (i % 2), 100.5, 99.5, 100.0 - 0.1 * ((i + 1) % 2)) for i in range(58))
    return base + (
        candle(58, 100.0, 100.0, 98.9, 99.0),
        candle(59, 99.0, last_high, last_low, last_close, volume=last_volume),
    )


def _run(net_delta: str, last_close: float, last_high: float, last_low: float, last_volume: float, delta_series=None):
    trades = tuple(Trade("BTCUSDT", last_close, 0.01, NOW, trade_id=i, buyer_is_maker=i % 2 == 0) for i in range(50))
    return Pipeline().run(
        PipelineInputs(
            market_context=MarketContext("BTCUSDT", "BINANCE", "FUTURES", "4H", NOW),
            candles=_pipeline_candles(last_close, last_high, last_low, last_volume),
            trades=trades,
            price_now=Decimal(str(last_close)),
            price_timestamp=NOW,
            net_delta=Decimal(net_delta),
            delta_series=delta_series,
            observed_at=NOW,
        )
    )


def test_pipeline_seller_exhaustion_reaches_the_sweep_scenario_and_report():
    """Thin selling at the range low: sellers exhausted, LONG sweep scenario gets the evidence."""
    # Sellers keep pushing (delta with price) but on 40 % volume and a 0.3 range: fading into the low.
    analysis = _run("-120", 98.8, 99.05, 98.75, 40.0, delta_series=(Decimal("-90"), Decimal("-60"), Decimal("-20")))
    assert analysis.data_quality.status == "PASS"
    assert analysis.orderflow.reaction == "EXHAUSTION"
    assert analysis.orderflow.exhaustion_hypothesis == "SELLERS_EXHAUSTED"
    assert analysis.orderflow.absorption_hypothesis is None
    [sweep] = [s for s in analysis.scenarios if s.scenario_id == "B"]
    assert "exhaustion_hypothesis_sellers_exhausted" in sweep.evidence_for
    assert "absorption_hypothesis_passive_buyers" not in sweep.evidence_for

    unconfirmed = _run("-120", 98.8, 99.05, 98.75, 40.0)
    [sweep_unconfirmed] = [s for s in unconfirmed.scenarios if s.scenario_id == "B"]
    assert analysis.orderflow.exhaustion_confirmed is True
    assert sweep.score > sweep_unconfirmed.score

    report = build_report(analysis)
    assert "Reaktion: EXHAUSTION." in report
    assert "Exhaustion-Hypothese: SELLERS_EXHAUSTED." in report
    assert "Exhaustion: CONFIRMED_SELLERS_EXHAUSTED." in report


def test_pipeline_absorption_is_unchanged_on_heavy_volume():
    # Sellers aggressive, price rises off the low on 160 % volume: passive buyers absorb.
    analysis = _run("-120", 99.2, 99.3, 98.9, 160.0)
    assert analysis.orderflow.reaction == "ABSORPTION"
    assert analysis.orderflow.absorption_hypothesis == "PASSIVE_BUYERS"
    [sweep] = [s for s in analysis.scenarios if s.scenario_id == "B"]
    assert "absorption_hypothesis_passive_buyers" in sweep.evidence_for
    explanation = next(item["result"] for item in analysis.audit["engines"] if item["engine"] == "setup_explanation")
    facts = explanation["facts"]
    assert facts["orderflow_reaction"] == "ABSORPTION"
    assert facts["exhaustion_status"] == "UNAVAILABLE"
