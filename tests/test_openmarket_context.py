"""OpenMarket context types (OI, funding, liquidations, volume profile) against real response shapes.

Fixtures in tests/fixtures/openmarket_2026_10_21 come from a read-only capture on
the target host (see the README there; the volume profile is partly synthetic).
No real API is contacted.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.market_data.providers.openmarket.client import HttpResult, OpenMarketClient
from src.market_data.providers.openmarket.context_schemas import (
    FUNDING_RATE,
    LIQUIDATION,
    OPEN_INTEREST,
    VOLUME_PROFILE,
    ProfilePoint,
    ProfileRow,
    closed_points,
    parse_context_series,
    summarize_profile,
)
from src.market_data.providers.openmarket.errors import OpenMarketError, OpenMarketErrorKind
from src.market_data.providers.openmarket.schemas import parse_json
from src.orderflow_scenario import cli
from src.orderflow_scenario.adapters.openmarket import DEFAULT_CONTEXT_TYPES, OpenMarketAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "openmarket_2026_10_21"
FROM, PERIOD, HOUR = 1792562400, 21600, 3600
NOW = datetime.fromtimestamp(1792584436, timezone.utc)  # 12:07Z, during the running hour
ENV = {"TIM_OPENMARKET_SECRET_PROVIDER": "env", "TIM_OPENMARKET_API_KEY": "om_test_fixture_value_0123456789",
       "TIM_OPENMARKET_BASE_URL": "https://openmarket.invalid"}
EXPECTED = {"exchange": "BINANCE_FUTURES", "rawSymbol": "BTCUSDT", "interval": "HOUR"}


def raw(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


def payload(name: str):
    return parse_json(raw(name))


def expected(data_type: str) -> dict:
    return {"type": data_type, **EXPECTED}


def test_open_interest_real_shape() -> None:
    parsed = parse_context_series(payload(OPEN_INTEREST), data_type=OPEN_INTEREST, expected=expected(OPEN_INTEREST))
    assert not parsed.rejected and not parsed.unexpected_fields
    assert len(parsed.points) == 7
    assert parsed.points[0].close == Decimal("95133.116")  # exact, no float rounding


def test_funding_real_shape() -> None:
    parsed = parse_context_series(payload(FUNDING_RATE), data_type=FUNDING_RATE, expected=expected(FUNDING_RATE))
    assert not parsed.rejected
    assert parsed.points[0].open == Decimal("0.00006678")
    assert parsed.points[-1].close == Decimal("0.0001")


def test_liquidations_real_shape_with_gaps() -> None:
    parsed = parse_context_series(payload(LIQUIDATION), data_type=LIQUIDATION, expected=expected(LIQUIDATION))
    assert parsed.sides == ["BUY", "SELL"]
    assert len([p for p in parsed.points if p.side == "BUY"]) == 6
    assert len([p for p in parsed.points if p.side == "SELL"]) == 5  # empty interval omitted by the provider


def test_volume_profile_sorted_and_triples() -> None:
    parsed = parse_context_series(payload(VOLUME_PROFILE), data_type=VOLUME_PROFILE, expected=expected(VOLUME_PROFILE))
    assert parsed.reordered  # newest first on the wire
    assert [p.timestamp_ns for p in parsed.points] == sorted(p.timestamp_ns for p in parsed.points)
    assert parsed.points[-1].rows[0] == ProfileRow(Decimal("83430"), Decimal("11.48899999999999"), Decimal("3.8939999999999966"))


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p["series"][0]["id"].update(rawSymbol="ETHUSDT"), "rawSymbol"),
        (lambda p: p["series"].append(p["series"][0]), "more than one series"),
        (lambda p: p["series"][0]["points"].__setitem__(0, {"open": 1}), "Point"),
        (lambda p: p.pop("series"), "envelope"),
    ],
)
def test_structural_deviation_is_schema_mismatch(mutate, message) -> None:
    data = json.loads(raw(OPEN_INTEREST))
    mutate(data)
    with pytest.raises(OpenMarketError) as error:
        parse_context_series(data, data_type=OPEN_INTEREST, expected=expected(OPEN_INTEREST))
    assert error.value.kind is OpenMarketErrorKind.SCHEMA_MISMATCH and message in str(error.value)


def test_invalid_points_are_rejected_not_repaired() -> None:
    data = json.loads(raw(VOLUME_PROFILE))
    data["series"][0]["points"][0]["Point"]["profile"] = [83430, 1.0]  # not a triple
    data["series"][0]["points"][1]["Point"]["timestamp"] = {"seconds": 1792580400}  # WebSocket shape on REST
    parsed = parse_context_series(data, data_type=VOLUME_PROFILE, expected=expected(VOLUME_PROFILE))
    assert len(parsed.points) == 1 and len(parsed.rejected) == 2


@pytest.mark.parametrize("side", [None, ["BUY"], "LONG"])
def test_liquidation_side_required(side) -> None:
    data = json.loads(raw(LIQUIDATION))
    if side is None:
        del data["series"][1]["id"]["side"]
    else:
        data["series"][1]["id"]["side"] = side
    with pytest.raises(OpenMarketError) as error:
        parse_context_series(data, data_type=LIQUIDATION, expected=expected(LIQUIDATION))
    assert error.value.kind is OpenMarketErrorKind.SCHEMA_MISMATCH


def test_closed_points_reject_off_grid_and_outside_window() -> None:
    data = json.loads(raw(OPEN_INTEREST))
    data["series"][0]["points"][1]["Point"]["timestamp"] = {"s": FROM + 1800}
    data["series"][0]["points"].append({"Point": {"open": 1, "high": 1, "low": 1, "close": 1, "timestamp": {"s": FROM + PERIOD + HOUR}}})
    parsed = parse_context_series(data, data_type=OPEN_INTEREST, expected=expected(OPEN_INTEREST))
    kept, rejected, excluded = closed_points(parsed.points, from_seconds=FROM, period_seconds=PERIOD, interval_seconds=HOUR,
                                             now_seconds=int(NOW.timestamp()) + 10 * HOUR)
    assert len(kept) == 5 and excluded == 1
    assert sorted(item.split(": ")[1] for item in rejected) == ["not on the interval grid", "outside requested window"]


def test_closed_points_drop_running_and_boundary_interval() -> None:
    parsed = parse_context_series(payload(OPEN_INTEREST), data_type=OPEN_INTEREST, expected=expected(OPEN_INTEREST))
    kept, rejected, excluded = closed_points(parsed.points, from_seconds=FROM, period_seconds=PERIOD, interval_seconds=HOUR,
                                             now_seconds=int(NOW.timestamp()))
    assert len(kept) == 6 and excluded == 1 and not rejected


def test_value_area_algorithm() -> None:
    rows = tuple(ProfileRow(Decimal(price), Decimal(volume), Decimal(0)) for price, volume in
                 [(100, 1), (105, 2), (110, 10), (115, 6), (120, 1)])
    summary = summarize_profile([ProfilePoint(0, rows)])
    assert summary.point_of_control == Decimal(110)
    # 70 % of 20 = 14: POC 10, then 115 (6) -> 16 covered.
    assert (summary.value_area_low, summary.value_area_high) == (Decimal(110), Decimal(115))
    assert summarize_profile([]) is None


class Transport:
    def __init__(self, responses: dict[str, HttpResult]):
        self.responses = responses
        self.paths: list[str] = []

    def __call__(self, method, path, headers, timeout):
        self.paths.append(path)
        data_type = path.split("type=")[1].split("&")[0]
        return self.responses[data_type]


def _candles(side: str | None = None) -> dict:
    points = []
    for index in range(7):
        start = FROM + index * HOUR
        close = 82700 + index * 120
        points.append({"Point": {"open": close - 60, "high": close + 50, "low": close - 90, "close": close, "volume": 1000.5,
                                 "timestamp": {"s": start}, "firstTimestamp": {"s": start, "ns": 1},
                                 "lastTimestamp": {"s": start + HOUR - 1, "ns": 0}}})
    series_id = {"type": "TRADE_AGG" if side else "TRADE_SIDE_AGNOSTIC_AGG", **EXPECTED}
    if side:
        series_id["side"] = side
    return {"id": series_id, "points": points}


def _adapter(**responses) -> tuple[OpenMarketAdapter, Transport]:
    base = {
        "TRADE_SIDE_AGNOSTIC_AGG": HttpResult(200, {}, json.dumps({"series": [_candles()]}).encode()),
        OPEN_INTEREST: HttpResult(200, {}, raw(OPEN_INTEREST)),
        FUNDING_RATE: HttpResult(200, {}, raw(FUNDING_RATE)),
        LIQUIDATION: HttpResult(200, {}, raw(LIQUIDATION)),
        VOLUME_PROFILE: HttpResult(200, {}, raw(VOLUME_PROFILE)),
    }
    base.update(responses)
    transport = Transport(base)
    client = OpenMarketClient(env=ENV, transport=transport, sleep=lambda _: None, max_retries=0)
    adapter = OpenMarketAdapter(client, include_per_side=False, context_types=DEFAULT_CONTEXT_TYPES, now=lambda: NOW)
    return adapter, transport


REQUEST = {"exchange": "BINANCE_FUTURES", "raw_symbol": "BTCUSDT", "interval": "HOUR", "from": FROM, "period": PERIOD,
           "market_type": "FUTURES"}


def test_adapter_builds_positioning_and_profile_from_real_responses() -> None:
    adapter, transport = _adapter()
    adapted = adapter.adapt(REQUEST)
    p = adapted.positioning
    assert p is not None
    assert p.funding_rate == Decimal("0.0001")  # last closed interval, running one excluded
    assert len(p.open_interest) == 6 and p.open_interest[-1][1] == Decimal("97078.067")
    # BUY liquidation orders close shorts (exchange convention, documented in notes).
    assert p.short_liquidation_volume == Decimal("0.45600000000000007") + Decimal("8.004999999999995") + Decimal("44.672") + Decimal("2.987") + Decimal("1.037") + Decimal("0.753")
    assert p.long_liquidation_volume == Decimal("0.467000000000000004")
    assert any(note.startswith("derived:liquidations=BUY_order_side_is_short_liquidation") for note in adapted.extra_notes)
    assert adapted.profile is not None and adapted.profile.point_of_control == Decimal("83360")
    assert any(item.startswith("tpo:TPO_AGG_not_requested") for item in adapted.missing_fields)
    assert len(transport.paths) == 5


def test_adapter_reports_unavailable_context_and_continues() -> None:
    adapter, _ = _adapter(**{FUNDING_RATE: HttpResult(403, {}, b'{"error":"FORBIDDEN"}')})
    adapted = adapter.adapt(REQUEST)
    assert adapted.positioning.funding_rate is None
    assert any(item.startswith("context:FUNDING_RATE_AGG_unavailable") for item in adapted.missing_fields)


def test_adapter_without_liquidation_convention_keeps_sides_out() -> None:
    adapter, _ = _adapter()
    adapter.liquidation_buy_is_short = False
    adapted = adapter.adapt(REQUEST)
    assert adapted.positioning.long_liquidation_volume is None
    assert "liquidations:side_semantics_unverified" in adapted.missing_fields


def test_spot_skips_derivative_types() -> None:
    adapter, transport = _adapter()
    adapted = adapter.adapt({**REQUEST, "market_type": "SPOT"})
    assert "context:OPEN_INTEREST_AGG_futures_only" in adapted.missing_fields
    assert not any("OPEN_INTEREST" in path for path in transport.paths)


def test_cli_openmarket_with_context_runs_pipeline(monkeypatch, capsys) -> None:
    adapter, _ = _adapter()
    monkeypatch.setattr(cli, "OpenMarketAdapter", lambda include_per_side: adapter)
    code = cli.main(["--provider", "openmarket", "--exchange", "BINANCE_FUTURES", "--raw-symbol", "BTCUSDT", "--interval", "HOUR",
                     "--from", str(FROM), "--period", str(PERIOD), "--market-type", "FUTURES", "--validate"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert "schema_validation=PASS" in captured.err
    output = json.loads(captured.out)
    assert output["orderflow"]["positioning"]["funding"]["state"] == "NEUTRAL"
    assert output["orderflow"]["positioning"]["open_interest"]["trend"] == "RISING"
    assert output["orderflow"]["profile"]["point_of_control"] == "83360"
