"""OpenMarket REST schema exactly as documented (owner-verified official docs).

The side-agnostic fixture below is the documented example response, verbatim
(``series[].id`` + ``series[].points[].Point``, REST timestamps ``{"s", "ns"}``).
The per-side fixture follows the same documented envelope with ``id.side``.
These tests pin the documented path; the synthetic shapes in
test_openmarket_v1.py only cover the defensive fallback.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.market_data.providers.openmarket import client as client_module
from src.market_data.providers.openmarket.client import HttpResult, OpenMarketClient
from src.market_data.providers.openmarket.errors import OpenMarketError, OpenMarketErrorKind
from src.market_data.providers.openmarket.schemas import parse_candles, parse_json, to_timestamp_ns
from src.orderflow_scenario.adapters.openmarket import OpenMarketAdapter

DOCUMENTED_SIDE_AGNOSTIC = """
{
  "series": [
    {
      "id": {
        "type": "TRADE_SIDE_AGNOSTIC_AGG",
        "exchange": "BINANCE_FUTURES",
        "rawSymbol": "BTCUSDT",
        "normalizedSymbol": "BTC-USDT",
        "category": "PERPETUAL",
        "interval": "HOUR",
        "coin": "BTC"
      },
      "points": [
        {
          "Point": {
            "open": 66499.9,
            "high": 66639.0,
            "low": 66400.0,
            "close": 66467.8,
            "volume": 2852.833,
            "timestamp": {"s": 1774800000},
            "firstTimestamp": {"s": 1774800003, "ns": 234000000},
            "lastTimestamp": {"s": 1774803599, "ns": 649000000}
          }
        }
      ]
    }
  ]
}
"""
HOUR_START = 1774800000
EXPECTED = {"type": "TRADE_SIDE_AGNOSTIC_AGG", "exchange": "BINANCE_FUTURES", "rawSymbol": "BTCUSDT", "interval": "HOUR"}
PER_SIDE_EXPECTED = {**EXPECTED, "type": "TRADE_AGG"}
ENV = {"TIM_OPENMARKET_SECRET_PROVIDER": "env", "TIM_OPENMARKET_API_KEY": "om_test_fixture_value_0123456789"}
REQUEST = {"exchange": "BINANCE_FUTURES", "raw_symbol": "BTCUSDT", "interval": "HOUR", "from": HOUR_START,
           "period": 3600, "market_type": "FUTURES"}


def documented() -> dict:
    return parse_json(DOCUMENTED_SIDE_AGNOSTIC.encode())


def per_side(*sides: str | None, volume: str = "1000.5") -> dict:
    """Documented envelope for TRADE_AGG: one series per side, side in series[].id.side."""
    base = documented()["series"][0]
    series = []
    for side in sides:
        item = copy.deepcopy(base)
        item["id"]["type"] = "TRADE_AGG"
        if side is None:
            item["id"].pop("side", None)
        else:
            item["id"]["side"] = side
        item["points"][0]["Point"]["volume"] = Decimal(volume) if side != "SELL" else Decimal("852.333")
        series.append(item)
    return {"series": series}


class Transport:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, method, path, headers, timeout):
        self.calls.append(path)
        return self.responses.pop(0)


def ok(payload) -> HttpResult:
    return HttpResult(200, {}, json.dumps(payload, default=str).encode())


# --- documented envelope --------------------------------------------------------

def test_documented_side_agnostic_response() -> None:
    parsed = parse_candles(documented(), per_side=False, expected=EXPECTED)
    assert parsed.documented_envelope is True and parsed.rejected == []
    [candle] = parsed.points
    assert (candle.open, candle.high, candle.low, candle.close, candle.volume) == (
        Decimal("66499.9"), Decimal("66639.0"), Decimal("66400.0"), Decimal("66467.8"), Decimal("2852.833")
    )
    assert parsed.envelope_paths == ["$.series[0].points[*].Point"]


def test_documented_point_wrapper() -> None:
    payload = documented()
    unwrapped = payload["series"][0]["points"][0].pop("Point")
    payload["series"][0]["points"][0] = unwrapped  # the Point wrapper is part of the documented schema
    with pytest.raises(OpenMarketError) as caught:
        parse_candles(payload, per_side=False, expected=EXPECTED)
    assert caught.value.kind is OpenMarketErrorKind.SCHEMA_MISMATCH


def test_documented_series_id() -> None:
    parsed = parse_candles(documented(), per_side=False, expected=EXPECTED)
    assert parsed.series_ids == [{
        "type": "TRADE_SIDE_AGNOSTIC_AGG", "exchange": "BINANCE_FUTURES", "rawSymbol": "BTCUSDT",
        "normalizedSymbol": "BTC-USDT", "category": "PERPETUAL", "interval": "HOUR", "coin": "BTC",
    }]
    for field, wrong in (("type", "TRADE_AGG"), ("exchange", "BYBIT"), ("rawSymbol", "ETHUSDT"), ("interval", "MINUTE")):
        payload = documented()
        payload["series"][0]["id"][field] = wrong
        with pytest.raises(OpenMarketError) as caught:
            parse_candles(payload, per_side=False, expected=EXPECTED)
        assert caught.value.kind is OpenMarketErrorKind.SCHEMA_MISMATCH and field in str(caught.value)
    missing_id = documented()
    del missing_id["series"][0]["id"]
    with pytest.raises(OpenMarketError):
        parse_candles(missing_id, per_side=False, expected=EXPECTED)


def test_documented_rest_timestamp() -> None:
    parsed = parse_candles(documented(), per_side=False, expected=EXPECTED)
    [candle] = parsed.points
    assert candle.timestamp == datetime.fromtimestamp(HOUR_START, timezone.utc)
    assert candle.first_timestamp_ns == 1774800003_234000000
    assert candle.last_timestamp_ns == 1774803599_649000000
    assert parsed.timestamp_encodings == {"REST"}


def test_documented_per_side_response() -> None:
    parsed = parse_candles(per_side("BUY", "SELL"), per_side=True, expected=PER_SIDE_EXPECTED)
    assert parsed.documented_envelope is True and parsed.side_location == "series[].id.side"
    assert sorted((p.side, p.volume) for p in parsed.points) == [("BUY", Decimal("1000.5")), ("SELL", Decimal("852.333"))]


# --- REST vs WebSocket timestamp schemas ----------------------------------------

def test_rest_timestamp_s() -> None:
    assert to_timestamp_ns({"s": HOUR_START}, label="t") == HOUR_START * 10**9


def test_rest_timestamp_s_ns() -> None:
    assert to_timestamp_ns({"s": HOUR_START, "ns": 234000000}, label="t") == HOUR_START * 10**9 + 234000000


def test_websocket_timestamp_seconds_nanoseconds() -> None:
    assert to_timestamp_ns({"seconds": HOUR_START, "nanoseconds": 5}, label="t") == HOUR_START * 10**9 + 5


@pytest.mark.parametrize(
    "value",
    [{"s": HOUR_START, "nanoseconds": 1}, {"seconds": HOUR_START, "ns": 1}, {"s": HOUR_START, "seconds": HOUR_START},
     {"s": HOUR_START, "ns": 1, "extra": 0}, {"ns": 5}, {"nanoseconds": 5}, {"s": "1774800000"}],
    ids=["s+nanoseconds", "seconds+ns", "s+seconds", "extra-key", "ns-only", "nanoseconds-only", "string-seconds"],
)
def test_invalid_mixed_timestamp(value) -> None:
    with pytest.raises(OpenMarketError) as caught:
        to_timestamp_ns(value, label="t")
    assert caught.value.kind is OpenMarketErrorKind.SCHEMA_MISMATCH


def test_rest_points_reject_websocket_timestamps() -> None:
    payload = documented()
    payload["series"][0]["points"][0]["Point"]["timestamp"] = {"seconds": HOUR_START, "nanoseconds": 0}
    parsed = parse_candles(payload, per_side=False, expected=EXPECTED)
    assert parsed.points == [] and "REST timestamp" in parsed.rejected[0], "REST and WebSocket schemas are not interchangeable"


# --- per-side location series[].id.side ------------------------------------------

def test_per_side_buy_series_only() -> None:
    parsed = parse_candles(per_side("BUY"), per_side=True, expected=PER_SIDE_EXPECTED)
    assert [p.side for p in parsed.points] == ["BUY"]


def test_per_side_sell_series_only() -> None:
    parsed = parse_candles(per_side("SELL"), per_side=True, expected=PER_SIDE_EXPECTED)
    assert [p.side for p in parsed.points] == ["SELL"]


@pytest.mark.parametrize(
    ("sides", "message"),
    [((None,), "side"), (("BOTH",), "side"), (("buy",), "side"), (("BUY", "BUY"), "duplicate"), (("SELL", "SELL"), "duplicate")],
    ids=["missing-side", "invalid-side", "lowercase-side", "duplicate-buy", "duplicate-sell"],
)
def test_per_side_invalid_series(sides, message) -> None:
    with pytest.raises(OpenMarketError) as caught:
        parse_candles(per_side(*sides), per_side=True, expected=PER_SIDE_EXPECTED)
    assert caught.value.kind is OpenMarketErrorKind.SCHEMA_MISMATCH and message in str(caught.value)


def test_side_agnostic_series_must_not_carry_a_side() -> None:
    payload = documented()
    payload["series"][0]["id"]["side"] = "BUY"
    with pytest.raises(OpenMarketError):
        parse_candles(payload, per_side=False, expected=EXPECTED)


# --- wire contract ------------------------------------------------------------------

def test_default_base_url_and_wire_parameter_names() -> None:
    DEFAULT_BASE_URL = getattr(client_module, "DEFAULT_BASE_URL", None)
    assert DEFAULT_BASE_URL == "https://api.openmarket.xyz"
    transport = Transport(ok(json.loads(DOCUMENTED_SIDE_AGNOSTIC)))
    client = OpenMarketClient(env=ENV, transport=transport)
    assert client.base_url == DEFAULT_BASE_URL, "works without TIM_OPENMARKET_BASE_URL"
    adapted = OpenMarketAdapter(client, include_per_side=False, now=lambda: datetime.fromtimestamp(HOUR_START + 7200, timezone.utc)).adapt(REQUEST)
    [path] = transport.calls
    assert path == ("/v1/points?type=TRADE_SIDE_AGNOSTIC_AGG&exchange=BINANCE_FUTURES&rawSymbol=BTCUSDT"
                    f"&interval=HOUR&from={HOUR_START}&period=3600")
    notes = set(adapted.extra_notes)
    for check in ("check:documented_envelope=PASS", "check:rest_timestamp_schema=PASS", "check:series_id=PASS",
                  "check:time_semantics=PASS"):
        assert check in notes
    assert len(adapted.candles) == 1 and adapted.candles[0]["open"] == 66499.9


def test_override_base_url_still_supported() -> None:
    client = OpenMarketClient(env={**ENV, "TIM_OPENMARKET_BASE_URL": "https://staging.openmarket.invalid"}, transport=Transport())
    assert client.base_url == "https://staging.openmarket.invalid"


def test_documented_per_side_through_adapter_keeps_delta_unproven() -> None:
    transport = Transport(ok(json.loads(DOCUMENTED_SIDE_AGNOSTIC)), ok(json.loads(json.dumps(per_side("BUY", "SELL"), default=str))))
    adapted = OpenMarketAdapter(OpenMarketClient(env=ENV, transport=transport),
                                now=lambda: datetime.fromtimestamp(HOUR_START + 7200, timezone.utc)).adapt(REQUEST)
    assert "type=TRADE_AGG" in transport.calls[1]
    assert "check:side_location=PASS" in adapted.extra_notes
    assert adapted.net_delta is None and adapted.aggressive_buy_volume is None and adapted.aggressive_sell_volume is None
    assert "aggressive_volume:TRADE_AGG_side_semantics_unverified" in adapted.missing_fields
    assert any("buy_volume=1000.5 sell_volume=852.333" in note for note in adapted.extra_notes)


# --- proof script gates --------------------------------------------------------------

PROOF_NOW = HOUR_START + 3600  # fixed clock; the proof window is 10..5 minutes before it


def minute_series(data_type: str, side: str | None = None, *, rest: bool = True) -> dict:
    start = (PROOF_NOW // 60) * 60 - 600
    points = []
    for minute in range(5):
        t = start + 60 * minute
        stamp = (lambda s, ns=0: {"s": s, "ns": ns}) if rest else (lambda s, ns=0: {"seconds": s, "nanoseconds": ns})
        points.append({"Point": {"open": "100.0", "high": "101.0", "low": "99.0", "close": "100.5", "volume": "3.25",
                                 "timestamp": stamp(t), "firstTimestamp": stamp(t + 1, 5), "lastTimestamp": stamp(t + 58)}})
    series_id = {"type": data_type, "exchange": "BINANCE_FUTURES", "rawSymbol": "BTCUSDT", "normalizedSymbol": "BTC-USDT",
                 "category": "PERPETUAL", "interval": "MINUTE", "coin": "BTC"}
    if side:
        series_id["side"] = side
    return {"id": series_id, "points": points}


def run_proof(monkeypatch, capsys, *responses, argv=()):
    import importlib.util
    spec = importlib.util.spec_from_file_location("om_proof_doc", "scripts/openmarket_api_proof.py")
    proof = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proof)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("TIM_OPENMARKET_BASE_URL", raising=False)
    monkeypatch.setattr(proof.socket, "getaddrinfo", lambda *a, **k: [])
    monkeypatch.setattr(proof.time, "time", lambda: PROOF_NOW)
    transport = Transport(*[ok(payload) for payload in responses])
    monkeypatch.setattr(proof, "OpenMarketClient", lambda max_retries: OpenMarketClient(env=ENV, transport=transport, max_retries=0))
    monkeypatch.setattr("sys.argv", ["proof", *argv])
    code = proof.main()
    return code, capsys.readouterr().out


def test_proof_passes_only_on_the_documented_contract(monkeypatch, capsys) -> None:
    code, out = run_proof(monkeypatch, capsys, {"series": [minute_series("TRADE_SIDE_AGNOSTIC_AGG")]})
    for line in ("HTTP_STATUS=200", "DOCUMENTED_ENVELOPE=PASS", "REST_TIMESTAMP_SCHEMA=PASS", "SERIES_ID=PASS",
                 "WINDOW_SEMANTICS=PASS", "NORMALIZATION=PASS", "BASE_URL=DOCUMENTED_DEFAULT", "FINAL=PASS"):
        assert line in out, line
    assert code == 0 and "om_test_fixture_value" not in out


def test_proof_per_side_requires_side_location(monkeypatch, capsys) -> None:
    code, out = run_proof(
        monkeypatch, capsys,
        {"series": [minute_series("TRADE_SIDE_AGNOSTIC_AGG")]},
        {"series": [minute_series("TRADE_AGG", "BUY"), minute_series("TRADE_AGG", "SELL")]},
        argv=("--per-side",),
    )
    assert code == 0 and "SIDE_LOCATION=PASS" in out and "REST_SIDE_AGGRESSOR_SEMANTICS=UNPROVEN" in out


def test_proof_fails_on_fallback_or_websocket_timestamps(monkeypatch, capsys) -> None:
    fallback = {"points": [item["Point"] for item in minute_series("TRADE_SIDE_AGNOSTIC_AGG")["points"]]}
    code, out = run_proof(monkeypatch, capsys, fallback)
    assert code == 1 and "DOCUMENTED_ENVELOPE=FAIL" in out and "FINAL=FAIL" in out and "AUTH=UNPROVEN" in out
    code, out = run_proof(monkeypatch, capsys, {"series": [minute_series("TRADE_SIDE_AGNOSTIC_AGG", rest=False)]})
    assert code == 1 and "FINAL=FAIL" in out
    assert "REST_TIMESTAMP_SCHEMA=FAIL" in out and "NORMALIZATION=FAIL" in out
