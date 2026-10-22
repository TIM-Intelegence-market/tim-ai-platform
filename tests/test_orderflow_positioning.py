"""Funding, liquidations, OI series, orderbook depth, volume profile and TPO in the orderflow pipeline."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.orderflow_scenario import cli
from src.orderflow_scenario.domain import OrderflowStatementKind
from src.orderflow_scenario.engines.orderflow_interpretation import OrderflowInputs, OrderflowInterpretationEngine
from src.orderflow_scenario.positioning import (
    PositioningInputs,
    ProfileLevels,
    interpret_positioning,
    interpret_profile,
    open_interest_trend,
    parse_context,
)
from src.models.market_data import Candle

T0 = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)


def texts(statements) -> list[str]:
    return [item.text for item in statements]


def test_parse_context_full_payload() -> None:
    parsed = parse_context({
        "funding_rate": "0.0001", "funding_interval_hours": 8,
        "liquidations": {"long_volume": 10, "short_volume": "2.5"},
        "open_interest": [{"time": "2026-10-21T00:00:00Z", "value": 100}, {"time": "2026-10-21T01:00:00Z", "value": 103}],
        "orderbook_depth": [{"depth_pct": 2.5, "imbalance": -0.203}, {"depth_pct": 5, "bid_volume": 900, "ask_volume": 1100}],
        "volume_profile": {"poc": 83200, "vah": 83600, "val": 82900},
        "tpo": {"poc": 1, "ib_high": 83400, "ib_low": 83000, "poor_high": 83600, "naked_pocs": [82500, 84100]},
    })
    assert parsed.rejected == ["tpo:poc_value_area_ignored_volume_profile_used"]  # never a mixed value area
    p = parsed.positioning
    assert p.funding_rate == Decimal("0.0001") and p.long_liquidation_volume == Decimal(10)
    assert [d.imbalance for d in p.orderbook_depth] == [Decimal("-0.203"), Decimal("-0.1")]
    profile = parsed.profile
    assert profile.point_of_control == Decimal(83200)  # volume profile wins over TPO
    assert profile.initial_balance_high == Decimal(83400) and profile.naked_pocs == (Decimal(82500), Decimal(84100))
    assert profile.source == ("volume_profile", "tpo")


@pytest.mark.parametrize(
    "payload, fragment",
    [
        ({"funding_rate": "abc"}, "funding_rate"),
        ({"funding_rate": 0.5}, "implausible"),  # 50 % per interval: a percentage was passed as a fraction
        ({"liquidations": {"long_volume": -1}}, "negative"),
        ({"open_interest": [{"time": "2026-10-21T00:00:00", "value": 1}]}, "timezone"),
        ({"orderbook_depth": [{"depth_pct": 2.5, "imbalance": 1.5}]}, "imbalance"),
        ({"volume_profile": {"poc": 90, "vah": 100, "val": 95}}, "inside the value area"),
        ({"tpo": {"naked_pocs": "82500"}}, "not_a_list"),
    ],
)
def test_parse_context_rejects_without_repair(payload, fragment) -> None:
    parsed = parse_context(payload)
    assert any(fragment in item for item in parsed.rejected), parsed.rejected


def test_conflicting_open_interest_points_are_dropped() -> None:
    parsed = parse_context({"open_interest": [
        {"time": "2026-10-21T00:00:00Z", "value": 1}, {"time": "2026-10-21T00:00:00Z", "value": 2},
        {"time": "2026-10-21T01:00:00Z", "value": 3},
    ]})
    assert len(parsed.positioning.open_interest) == 1
    assert any("conflicting" in item for item in parsed.rejected)


def test_empty_payload_gives_no_context() -> None:
    parsed = parse_context({})
    assert parsed.positioning is None and parsed.profile is None and not parsed.rejected


def test_open_interest_trend_thresholds() -> None:
    series = lambda *values: tuple((T0 + timedelta(hours=i), Decimal(v)) for i, v in enumerate(values))
    assert open_interest_trend(series(100, 100.4))[0] == "FLAT"
    assert open_interest_trend(series(100, 101))[0] == "RISING"
    assert open_interest_trend(series(100, 98))[0] == "FALLING"
    assert open_interest_trend(series(100)) == (None, None)


def test_funding_states() -> None:
    neutral = interpret_positioning(PositioningInputs(funding_rate=Decimal("0.0001")), "UP")
    assert neutral.summary["funding"]["state"] == "NEUTRAL" and not neutral.summary["bias_hints"]
    extreme = interpret_positioning(PositioningInputs(funding_rate=Decimal("0.0006")), "UP")
    assert extreme.summary["funding"]["state"] == "EXTREME_POSITIVE"
    assert "longs_crowded_squeeze_risk_down" in texts(extreme.statements)
    assert extreme.summary["bias_hints"] == ["against_long:crowded_funding"]
    # 1 h funding of 0.0001 is 0.0008 per 8 h: extreme.
    hourly = interpret_positioning(PositioningInputs(funding_rate=Decimal("0.0001"), funding_interval_hours=1), "UP")
    assert hourly.summary["funding"]["state"] == "EXTREME_POSITIVE"


def test_liquidations_and_open_interest_combination() -> None:
    falling = tuple((T0 + timedelta(hours=i), Decimal(v)) for i, v in enumerate((100, 97)))
    result = interpret_positioning(
        PositioningInputs(long_liquidation_volume=Decimal(80), short_liquidation_volume=Decimal(10), open_interest=falling), "DOWN"
    )
    assert result.summary["liquidations"]["state"] == "LONGS_DOMINANT"
    assert "long_liquidations_drive_price_down" in texts(result.statements)
    assert "open_interest_drop_matches_long_liquidations" in texts(result.statements)
    assert result.open_interest_with_price == "FALLING_WITH_PRICE_DOWN"
    assert result.summary["bias_hints"] == []  # a flush can continue or exhaust: no score hint


def test_crowded_longs_hypothesis() -> None:
    rising = tuple((T0 + timedelta(hours=i), Decimal(v)) for i, v in enumerate((100, 103)))
    result = interpret_positioning(PositioningInputs(funding_rate=Decimal("0.0003"), open_interest=rising), "UP")
    assert "crowded_longs_add_downside_liquidity" in texts(result.statements)


def test_orderbook_depth_is_observation_only() -> None:
    parsed = parse_context({"orderbook_depth": [{"depth_pct": 2.5, "imbalance": -0.203}, {"depth_pct": 5, "imbalance": -0.066}]})
    result = interpret_positioning(parsed.positioning, "UP")
    depth_statements = [item for item in result.statements if "orderbook" in item.text]
    assert {item.kind for item in depth_statements} == {OrderflowStatementKind.OBSERVATION}
    assert [item["state"] for item in result.summary["orderbook_depth"]] == ["ASK_HEAVY", "BALANCED"]
    assert not result.summary["bias_hints"]


def test_missing_context_is_listed() -> None:
    result = interpret_positioning(None, "UNKNOWN")
    assert set(result.missing) == {"funding_rate", "liquidations", "open_interest_series", "orderbook_depth"}


def test_profile_location() -> None:
    profile = ProfileLevels(point_of_control=Decimal(100), value_area_high=Decimal(105), value_area_low=Decimal(95),
                            initial_balance_high=Decimal(103), initial_balance_low=Decimal(97), poor_high=Decimal(110),
                            naked_pocs=(Decimal(90), Decimal(120)))
    statements, summary, missing = interpret_profile(profile, Decimal(104))
    assert summary["price_location"] == "INSIDE_VALUE" and summary["ib_location"] == "ABOVE_IB"
    assert summary["nearest_naked_poc"] == "90" and not missing
    assert "initial_balance_extension_up" in texts(statements)
    assert interpret_profile(None, Decimal(1))[2] == ("volume_profile_or_tpo",)


def _candles(closes) -> list[Candle]:
    return [
        Candle(symbol="BTCUSDT", timeframe="1H", open_time=T0 + timedelta(hours=i), close_time=T0 + timedelta(hours=i + 1),
               open=c - 10, high=c + 20, low=c - 20, close=c, volume=100.0, trade_count=0, closed=True)
        for i, c in enumerate(closes)
    ]


def test_engine_derives_open_interest_with_price_from_series() -> None:
    rising = tuple((T0 + timedelta(hours=i + 1), Decimal(v)) for i, v in enumerate((100, 103)))
    result = OrderflowInterpretationEngine().evaluate(
        OrderflowInputs(candles=_candles([83000, 83400]), net_delta=Decimal(5), positioning=PositioningInputs(open_interest=rising))
    )
    assert result.open_interest_interpretation == "long_accumulation"
    assert result.positioning["open_interest"]["with_price"] == "RISING_WITH_PRICE_UP"
    oi = next(item for item in result.statements if item.text == "open_interest_long_accumulation")
    assert oi.evidence_refs == ("open_interest", "candles")


def test_explicit_open_interest_contradicting_series_is_not_interpreted() -> None:
    rising = tuple((T0 + timedelta(hours=i + 1), Decimal(v)) for i, v in enumerate((100, 103)))
    result = OrderflowInterpretationEngine().evaluate(
        OrderflowInputs(candles=_candles([83000, 83400]), open_interest_with_price="FALLING_WITH_PRICE_UP",
                        positioning=PositioningInputs(open_interest=rising))
    )
    assert result.open_interest_interpretation is None
    assert "conflict:open_interest_input_vs_series" in result.missing_data
    agreeing = OrderflowInterpretationEngine().evaluate(
        OrderflowInputs(candles=_candles([83000, 83400]), open_interest_with_price="RISING_WITH_PRICE_UP",
                        positioning=PositioningInputs(open_interest=rising))
    )
    assert agreeing.open_interest_interpretation == "long_accumulation"


def test_window_price_not_last_step_decides_context() -> None:
    # 24 rising candles, the last one closes lower: the window rose, the last step fell.
    closes = [83000 + i * 100 for i in range(23)] + [85100]
    series = tuple((T0 + timedelta(hours=i + 1), Decimal(100 + i)) for i in range(24))
    result = OrderflowInterpretationEngine().evaluate(OrderflowInputs(
        candles=_candles(closes), net_delta=Decimal(-3),
        positioning=PositioningInputs(open_interest=series, long_liquidation_volume=Decimal(9), short_liquidation_volume=Decimal(1)),
    ))
    assert result.price_response == "DOWN"
    assert result.open_interest_interpretation == "long_accumulation"
    assert "long_liquidations_drive_price_down" not in texts(result.statements)


def test_open_interest_outside_candle_window_is_ignored() -> None:
    old = tuple((T0 - timedelta(days=2, hours=-i), Decimal(100 + i)) for i in range(3))
    result = OrderflowInterpretationEngine().evaluate(OrderflowInputs(candles=_candles([83000, 83400]), positioning=PositioningInputs(open_interest=old)))
    assert result.open_interest_interpretation is None
    assert "open_interest_series:outside_candle_window" in result.missing_data


def test_analysis_without_context_keeps_missing_data() -> None:
    result = OrderflowInterpretationEngine().evaluate(OrderflowInputs(candles=_candles([83000, 83400]), net_delta=Decimal(5)))
    assert result.missing_data == ("aggressive_volume",)
    assert result.positioning == {} and result.profile == {}


def test_invalid_funding_interval_drops_funding_only() -> None:
    parsed = parse_context({"funding_rate": 0.0003, "funding_interval_hours": 4.9, "liquidations": {"long_volume": 1, "short_volume": 2}})
    assert parsed.positioning.funding_rate is None and parsed.positioning.long_liquidation_volume == Decimal(1)
    assert any(item.startswith("funding_rate:") for item in parsed.rejected)
    implausible = parse_context({"funding_rate": 0.5, "liquidations": {"long_volume": 1, "short_volume": 2}})
    assert implausible.positioning is not None and implausible.positioning.funding_rate is None


def test_orderbook_imbalance_contradicting_volumes_is_rejected() -> None:
    parsed = parse_context({"orderbook_depth": [{"depth_pct": 1, "imbalance": 0.5, "bid_volume": 1, "ask_volume": 100}]})
    assert parsed.positioning is None and any("contradicts" in item for item in parsed.rejected)


def test_poor_high_direction_is_relative_to_price() -> None:
    statements, _, _ = interpret_profile(ProfileLevels(poor_high=Decimal(100), poor_low=Decimal(90)), Decimal(105))
    assert "poor_high_unfinished_auction_at=100 level_below_price" in texts(statements)
    assert "poor_low_unfinished_auction_at=90 level_below_price" in texts(statements)


def test_context_confidence_bonus_is_capped() -> None:
    engine = OrderflowInterpretationEngine()
    candles = _candles([83000, 83400])
    base = engine.evaluate(OrderflowInputs(candles=candles, net_delta=Decimal(5), open_interest_with_price="RISING_WITH_PRICE_UP"))
    context = parse_context({
        "funding_rate": 0.0001, "liquidations": {"long_volume": 1, "short_volume": 1},
        "open_interest": [{"time": "2026-10-21T00:00:00Z", "value": 100}, {"time": "2026-10-21T01:00:00Z", "value": 103}],
        "orderbook_depth": [{"depth_pct": 1, "imbalance": 0}],
        "volume_profile": {"poc": 83300, "vah": 83500, "val": 83100},
    })
    full = engine.evaluate(OrderflowInputs(candles=candles, net_delta=Decimal(5), open_interest_with_price="RISING_WITH_PRICE_UP",
                                           positioning=context.positioning, profile=context.profile))
    assert full.confidence - base.confidence == Decimal("0.08")  # five categories, capped at +0.08


SCREENSHOT_2026_10_21 = {
    "symbol": "BTCUSDT", "venue": "BINANCE", "market_type": "FUTURES", "timeframe": "30m", "price_now": 83521.34,
    "candles": [{"open_time": "2026-10-21T11:30:00+00:00", "timeframe": "30m", "open": 83491.19, "high": 83594.0,
                 "low": 83412.0, "close": 83521.34, "volume": 0, "closed": False}],
    "net_delta": -9.77, "open_interest_with_price": "RISING_WITH_PRICE_UP", "levels": {"range_high": 83600, "range_low": 83350},
    "orderbook_depth": [{"depth_pct": 2.5, "imbalance": -0.203}, {"depth_pct": 5, "imbalance": -0.066}],
    "read_confidence": 0.55,
}


def test_cli_screenshot_with_orderbook_depth(tmp_path, capsys) -> None:
    path = tmp_path / "input.json"
    path.write_text(json.dumps(SCREENSHOT_2026_10_21), encoding="utf-8")
    code = cli.main(["--input", str(path), "--provider", "mmt-screenshot", "--validate"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert "schema_validation=PASS" in captured.err
    output = json.loads(captured.out)
    assert output["orderflow"]["positioning"]["orderbook_depth"][0]["state"] == "ASK_HEAVY"
    assert "funding_rate" in output["orderflow"]["missing_data"]


def test_cli_generic_with_full_context(tmp_path, capsys) -> None:
    candles = [{"open_time": (T0 + timedelta(hours=i)).isoformat(), "timeframe": "1H", "open": 83000 + i * 10,
                "high": 83050 + i * 10, "low": 82950 + i * 10, "close": 83020 + i * 10, "volume": 50} for i in range(30)]
    payload = {
        "symbol": "BTCUSDT", "venue": "BINANCE", "market_type": "FUTURES", "timeframe": "1H", "candles": candles,
        "net_delta": 12, "funding_rate": 0.0006,
        "open_interest": [{"time": (T0 + timedelta(hours=i)).isoformat(), "value": 100 + i} for i in range(5)],
        "liquidations": {"long_volume": 5, "short_volume": 40},
        "volume_profile": {"poc": 83150, "vah": 83250, "val": 83050},
        "tpo": {"ib_high": 83100, "ib_low": 83000, "poor_high": 83400},
    }
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    code = cli.main(["--input", str(path), "--validate"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    output = json.loads(captured.out)
    positioning = output["orderflow"]["positioning"]
    assert positioning["funding"]["state"] == "EXTREME_POSITIVE"
    assert positioning["liquidations"]["state"] == "SHORTS_DOMINANT"
    assert output["orderflow"]["profile"]["price_location"] == "ABOVE_VALUE"
    assert "Funding (8h)" in output["report_text"] and "Profil" in output["report_text"]
