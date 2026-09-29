"""OpenMarket v1: secret handling, HTTP taxonomy, parsing, mapping, dedup, CLI.

All HTTP traffic goes to an in-memory transport. The JSON envelopes below are
SYNTHETIC test shapes: only the point fields (open/high/low/close/volume/
timestamp/firstTimestamp/lastTimestamp) and the BUY/SELL series come from the
verified documentation. No real API is contacted and no real key exists here.
"""
from __future__ import annotations

import json
import os
import socket
import ssl
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.market_data.providers.openmarket.auth import OpenMarketSecretResolver, masked
from src.market_data.providers.openmarket.client import AUTH_HEADER, HttpResult, OpenMarketClient
from src.market_data.providers.openmarket.errors import OpenMarketError, OpenMarketErrorKind
from src.market_data.providers.openmarket.mapper import dedupe_candles
from src.market_data.providers.openmarket.schemas import parse_candles, parse_json, to_timestamp_ns
from src.orderflow_scenario.adapters import GenericOrderflowAdapter, MMTScreenshotAdapter, MMTStructuredDataAdapter
from src.orderflow_scenario.adapters.openmarket import OpenMarketAdapter
from src.orderflow_scenario import cli

FAKE_KEY = "om_test_fixture_value_0123456789"  # synthetic, not a real credential
BASE = "https://openmarket.invalid"
T0 = 1_789_999_980  # epoch seconds on the 1-minute grid (2026-09-21T14:13:00Z)
ENV = {"TIM_OPENMARKET_SECRET_PROVIDER": "env", "TIM_OPENMARKET_API_KEY": FAKE_KEY, "TIM_OPENMARKET_BASE_URL": BASE}


def point(offset_minutes: int, close: str = "100.5", volume: str = "2.000000001") -> dict:
    return {
        "timestamp": {"seconds": T0 + 60 * offset_minutes, "nanoseconds": 0},
        "open": "100.1", "high": "101.0", "low": "99.9", "close": close, "volume": volume,
        "firstTimestamp": {"seconds": T0 + 60 * offset_minutes, "nanoseconds": 123456789},
        "lastTimestamp": {"seconds": T0 + 60 * offset_minutes + 59, "nanoseconds": 0},
    }


def body(payload) -> bytes:
    return json.dumps(payload).encode()


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, method, path, headers, timeout):
        self.calls.append((path, dict(headers)))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def client(*responses, env=ENV, **kwargs) -> tuple[OpenMarketClient, Transport, list[float]]:
    transport = Transport(*responses)
    sleeps: list[float] = []
    return (
        OpenMarketClient(env=env, transport=transport, sleep=sleeps.append, backoff_seconds=0.1, **kwargs),
        transport,
        sleeps,
    )


def ok(payload, headers=None) -> HttpResult:
    return HttpResult(200, headers or {}, body(payload))


PARAMS = {"type": "TRADE_SIDE_AGNOSTIC_AGG", "exchange": "BINANCE_FUTURES", "rawSymbol": "BTCUSDT",
          "interval": "MINUTE", "from": T0, "period": 180}


# --- secrets -------------------------------------------------------------------

def test_missing_secret() -> None:
    om, transport, _ = client(env={"TIM_OPENMARKET_BASE_URL": BASE})
    with pytest.raises(OpenMarketError) as caught:
        om.get_points(PARAMS)
    assert caught.value.kind is OpenMarketErrorKind.NO_SECRET
    assert transport.calls == [], "no request without a secret"
    assert om.health()["configured"] is False


def test_secret_file_requires_private_mode(tmp_path) -> None:
    path = tmp_path / "key"
    path.write_text(FAKE_KEY)
    os.chmod(path, 0o644)
    resolver = OpenMarketSecretResolver({"TIM_OPENMARKET_SECRET_PROVIDER": "file", "TIM_OPENMARKET_SECRET_FILE": str(path)})
    with pytest.raises(OpenMarketError) as caught:
        resolver.api_key()
    assert "0600" in str(caught.value) and FAKE_KEY not in str(caught.value)
    os.chmod(path, 0o600)
    assert resolver.api_key().reveal() == FAKE_KEY


def test_secret_redaction(capsys) -> None:
    secret = OpenMarketSecretResolver(ENV).api_key()
    assert FAKE_KEY not in repr(secret) and FAKE_KEY not in str(secret) and FAKE_KEY not in f"{secret}"
    assert masked(secret) == "****" + FAKE_KEY[-4:]
    om, transport, _ = client(HttpResult(401, {}, body({"error": "INVALID_API_KEY", "echo": FAKE_KEY})))
    with pytest.raises(OpenMarketError) as caught:
        om.get_points(PARAMS)
    rendered = " ".join([str(caught.value), repr(caught.value), json.dumps(om.health())])
    assert FAKE_KEY not in rendered, "a provider body echoing the key must never surface"
    assert caught.value.provider_code == "INVALID_API_KEY"
    sent = transport.calls[0][1][AUTH_HEADER]
    assert FAKE_KEY not in repr(sent) and sent.reveal() == FAKE_KEY, "wrapped until the transport reveals it"
    assert FAKE_KEY not in transport.calls[0][0], "never in the URL"
    assert FAKE_KEY not in capsys.readouterr().out


def test_base_url_must_be_https() -> None:
    om, transport, _ = client(env={**ENV, "TIM_OPENMARKET_BASE_URL": "http://openmarket.invalid"})
    with pytest.raises(OpenMarketError) as caught:
        om.get_points(PARAMS)
    assert caught.value.kind is OpenMarketErrorKind.NOT_CONFIGURED and transport.calls == []


# --- HTTP ------------------------------------------------------------------------

def test_200() -> None:
    headers = {"X-RateLimit-Limit": "1200", "X-RateLimit-Remaining": "1190", "X-RateLimit-Used": "10", "X-RateLimit-Reset": "30"}
    om, transport, _ = client(ok({"data": [point(0)]}, headers))
    response = om.get_points(PARAMS)
    assert response.status == 200 and response.request_path == "/v1/points"
    path = transport.calls[0][0]
    assert path.startswith("/v1/points?") and "type=TRADE_SIDE_AGNOSTIC_AGG" in path and "rawSymbol=BTCUSDT" in path
    assert om.health()["healthy"] is True and om.health()["authenticated"] is True


@pytest.mark.parametrize(
    ("status", "payload", "kind", "code"),
    [
        (400, {"error": "INVALID_SYMBOL"}, OpenMarketErrorKind.INVALID_REQUEST, "INVALID_SYMBOL"),
        (400, {"error": "INVALID_TIMEFRAME"}, OpenMarketErrorKind.INVALID_REQUEST, "INVALID_TIMEFRAME"),
        (401, {"error": "INVALID_API_KEY"}, OpenMarketErrorKind.INVALID_SECRET, "INVALID_API_KEY"),
        (403, {"message": "history depth exceeded"}, OpenMarketErrorKind.FORBIDDEN, None),
        (404, {}, OpenMarketErrorKind.NOT_FOUND, None),
    ],
    ids=["400-symbol", "400-timeframe", "401", "403", "404"],
)
def test_4xx_is_classified_and_not_retried(status, payload, kind, code) -> None:
    om, transport, sleeps = client(HttpResult(status, {}, body(payload)))
    with pytest.raises(OpenMarketError) as caught:
        om.get_points(PARAMS)
    assert caught.value.kind is kind and caught.value.http_status == status and caught.value.provider_code == code
    assert len(transport.calls) == 1 and sleeps == []
    assert om.health()["last_error"] == kind.value


def test_400() -> None:
    test_4xx_is_classified_and_not_retried(400, {"error": "INVALID_PARAMS"}, OpenMarketErrorKind.INVALID_REQUEST, "INVALID_PARAMS")


def test_401() -> None:
    om, _, _ = client(HttpResult(401, {}, body({"error": "INVALID_API_KEY"})))
    with pytest.raises(OpenMarketError):
        om.get_points(PARAMS)
    assert om.health()["authenticated"] is False


def test_403() -> None:
    om, _, _ = client(HttpResult(403, {}, b"max point count exceeded"))
    with pytest.raises(OpenMarketError) as caught:
        om.get_points(PARAMS)
    assert caught.value.kind is OpenMarketErrorKind.FORBIDDEN
    assert om.health()["authenticated"] is None, "a 403 proves nothing about the key (a proxy can send it)"


def test_429() -> None:
    om, transport, sleeps = client(
        HttpResult(429, {"Retry-After": "2", "X-RateLimit-Remaining": "0"}, b"{}"), ok({"data": [point(0)]})
    )
    om.get_points(PARAMS)
    assert sleeps == [2.0] and len(transport.calls) == 2


def test_500() -> None:
    om, transport, sleeps = client(HttpResult(500, {}, body({"error": "INTERNAL_ERROR"})), ok({"data": [point(0)]}))
    om.get_points(PARAMS)
    assert sleeps == [0.1] and len(transport.calls) == 2


def test_504() -> None:
    om, _, _ = client(*[HttpResult(504, {}, body({"error": "TIMEOUT"}))] * 3)
    with pytest.raises(OpenMarketError) as caught:
        om.get_points(PARAMS)
    assert caught.value.kind is OpenMarketErrorKind.TIMEOUT and caught.value.http_status == 504


def test_timeout() -> None:
    om, transport, sleeps = client(TimeoutError(), TimeoutError(), TimeoutError())
    with pytest.raises(OpenMarketError) as caught:
        om.get_points(PARAMS)
    assert caught.value.kind is OpenMarketErrorKind.TIMEOUT
    assert len(transport.calls) == 3 and sleeps == [0.1, 0.2]


@pytest.mark.parametrize(
    ("exception", "kind"),
    [(socket.gaierror(), OpenMarketErrorKind.DNS_FAILURE), (ssl.SSLError(), OpenMarketErrorKind.TLS_FAILURE),
     (ConnectionResetError(), OpenMarketErrorKind.NETWORK_FAILURE)],
    ids=["dns", "tls", "network"],
)
def test_network_failures_are_classified(exception, kind) -> None:
    om, _, _ = client(exception, exception, exception, max_retries=0)
    with pytest.raises(OpenMarketError) as caught:
        om.get_points(PARAMS)
    assert caught.value.kind is kind


def test_invalid_json() -> None:
    om, transport, _ = client(HttpResult(200, {}, b"{not json"))
    with pytest.raises(OpenMarketError) as caught:
        om.get_points(PARAMS)
    assert caught.value.kind is OpenMarketErrorKind.SCHEMA_MISMATCH and len(transport.calls) == 1


# --- rate limits -------------------------------------------------------------------

def test_rate_limit_headers() -> None:
    headers = {"x-ratelimit-limit": "1200", "X-RateLimit-Remaining": "5", "X-RateLimit-Used": "1195", "X-RateLimit-Reset": "17"}
    om, _, _ = client(ok({"data": [point(0)]}, headers))
    om.get_points(PARAMS)
    state = om.health()["rate_limit_state"]
    assert state == {"limit": "1200", "remaining": "5", "used": "1195", "reset": "17", "retry_after": None, "limited": False}


def test_retry_after() -> None:
    om, transport, sleeps = client(HttpResult(429, {"Retry-After": "3600"}, b"{}"), max_retry_after_seconds=30)
    with pytest.raises(OpenMarketError) as caught:
        om.get_points(PARAMS)
    assert caught.value.kind is OpenMarketErrorKind.RATE_LIMITED and caught.value.retry_after_seconds == 3600
    assert sleeps == [] and len(transport.calls) == 1, "a wait beyond the cap fails fast instead of sleeping"
    assert om.health()["rate_limit_state"]["limited"] is True


def test_bounded_retry() -> None:
    om, transport, sleeps = client(*[HttpResult(503, {}, b"")] * 10, max_retries=2)
    with pytest.raises(OpenMarketError):
        om.get_points(PARAMS)
    assert len(transport.calls) == 3 and sleeps == [0.1, 0.2]
    capped = OpenMarketClient(env=ENV, transport=Transport(), max_retries=99)
    assert capped.max_retries == 5


# --- parsing and mapping -----------------------------------------------------------------

def test_candle_mapping() -> None:
    # Structural fallback shape (no documented "series" envelope).
    om, _, _ = client(ok({"meta": {"exchange": "BINANCE_FUTURES"}, "points": [point(0), point(1), point(2)]}))
    adapted = OpenMarketAdapter(om, include_per_side=False, now=lambda: datetime.fromtimestamp(T0 + 150, timezone.utc)).adapt(
        {"exchange": "BINANCE_FUTURES", "raw_symbol": "BTCUSDT", "interval": "MINUTE", "from": T0, "period": 180, "market_type": "FUTURES"}
    )
    assert adapted.venue == "BINANCE_FUTURES" and adapted.symbol == "BTCUSDT" and adapted.timeframe == "1m"
    assert len(adapted.candles) == 2, "the running third interval is excluded"
    first = adapted.candles[0]
    assert first["open_time"] == "2026-09-21T14:13:00+00:00" and first["close_time"] == "2026-09-21T14:14:00+00:00"
    assert all(c["closed"] for c in adapted.candles)
    assert "excluded:open_interval_candles=1" in adapted.extra_notes
    assert "check:time_semantics=PASS" in adapted.extra_notes and "verify:time_unit=true" in adapted.extra_notes
    assert adapted.total_volume == Decimal("4.000000002")
    assert "candles.trade_count" in adapted.missing_fields
    assert any(note.startswith("provenance:provider=openmarket") for note in adapted.extra_notes)
    assert "provenance:envelope_paths=$.points" in adapted.extra_notes
    assert "check:documented_envelope=FAIL" in adapted.extra_notes, "the fallback is never documented evidence"
    assert any(note.startswith("provenance:response_sha256=") for note in adapted.extra_notes)
    assert "derived:total_volume=true derivation=sum_of_closed_TRADE_SIDE_AGNOSTIC_AGG_volume complete=true" in adapted.extra_notes


def rest_point(offset_minutes: int, volume: str) -> dict:
    """point() in the documented REST form: Point wrapper, {s, ns} timestamps."""
    raw = point(offset_minutes, volume=volume)
    for name in ("timestamp", "firstTimestamp", "lastTimestamp"):
        raw[name] = {"s": raw[name]["seconds"], "ns": raw[name]["nanoseconds"]}
    return {"Point": raw}


def _per_side_payload(buy_volume="3.5", sell_volume="1.25"):
    """Documented TRADE_AGG envelope: one series per side, side in series[].id.side."""
    def series_id(side):
        return {"type": "TRADE_AGG", "exchange": "BINANCE_FUTURES", "rawSymbol": "BTCUSDT", "interval": "MINUTE", "side": side}
    return {"series": [
        {"id": series_id("BUY"), "points": [rest_point(0, buy_volume)]},
        {"id": series_id("SELL"), "points": [rest_point(0, sell_volume), rest_point(1, "9")]},
    ]}


def test_per_side_mapping() -> None:
    request = {"exchange": "BINANCE_FUTURES", "raw_symbol": "BTCUSDT", "interval": "MINUTE", "from": T0, "period": 120, "market_type": "FUTURES"}
    om, transport, _ = client(ok({"points": [point(0)]}), ok(_per_side_payload()))
    unverified = OpenMarketAdapter(om).adapt(request)
    assert "type=TRADE_AGG" in transport.calls[1][0]
    assert unverified.net_delta is None and unverified.aggressive_buy_volume is None
    assert "aggressive_volume:TRADE_AGG_side_semantics_unverified" in unverified.missing_fields
    assert any("buy_volume=3.5 sell_volume=1.25 paired_intervals=1 unpaired_intervals=1" in n for n in unverified.extra_notes)

    om, _, _ = client(ok({"points": [point(0)]}), ok(_per_side_payload()))
    derived = OpenMarketAdapter(om, side_is_aggressor=True).adapt(request)
    assert derived.aggressive_buy_volume == Decimal("3.5") and derived.aggressive_sell_volume == Decimal("1.25")
    assert derived.net_delta == Decimal("2.25"), "only paired intervals; the SELL-only minute is not read as zero BUY"
    assert any(n.startswith("derived:net_delta=true derivation=buy_volume_minus_sell_volume") for n in derived.extra_notes)


def test_per_side_unavailable_is_reported_not_fatal() -> None:
    request = {"exchange": "BINANCE_FUTURES", "raw_symbol": "BTCUSDT", "interval": "MINUTE", "from": T0, "period": 60, "market_type": "FUTURES"}
    om, _, _ = client(ok({"points": [point(0)]}), HttpResult(403, {}, b"type not permitted for tier"))
    adapted = OpenMarketAdapter(om).adapt(request)
    assert len(adapted.candles) == 1
    assert "aggressive_volume:TRADE_AGG_unavailable:FORBIDDEN" in adapted.missing_fields


def test_decimal_precision() -> None:
    payload = parse_json(b'{"points":[{"timestamp":1790000000,"open":0.1,"high":0.30000000000000004,"low":0.1,"close":0.2,"volume":12345678901234567890.123456789}]}')
    parsed = parse_candles(payload, per_side=False)
    candle = parsed.points[0]
    assert candle.high == Decimal("0.30000000000000004") and candle.volume == Decimal("12345678901234567890.123456789")
    assert isinstance(candle.open, Decimal)


def test_timestamp_mapping() -> None:
    assert to_timestamp_ns({"seconds": T0, "nanoseconds": 123456789}, label="t") == T0 * 10**9 + 123456789
    assert to_timestamp_ns(T0, label="t") == T0 * 10**9
    assert to_timestamp_ns("2026-09-21T14:13:00.5+02:00", label="t") == (T0 - 7200) * 10**9 + 500_000_000
    for bad in (T0 * 1000, "2026-09-21T14:13:20", {"seconds": T0, "nanoseconds": 10**9}, 1.5, True):
        with pytest.raises(OpenMarketError) as caught:
            to_timestamp_ns(bad, label="t")
        assert caught.value.kind is OpenMarketErrorKind.SCHEMA_MISMATCH
    parsed = parse_candles({"points": [point(0)]}, per_side=False)
    assert parsed.points[0].first_timestamp_ns == T0 * 10**9 + 123456789, "nanoseconds are kept"


def test_symbol_mapping() -> None:
    om, transport, _ = client(ok({"points": [point(0)]}))
    adapted = OpenMarketAdapter(om, include_per_side=False).adapt(
        {"exchange": "BYBIT", "raw_symbol": "BTCUSDT", "interval": "FOUR_HOURS", "from": T0, "period": 14400, "market_type": "FUTURES"}
    )
    assert "exchange=BYBIT" in transport.calls[0][0] and "rawSymbol=BTCUSDT" in transport.calls[0][0]
    assert adapted.venue == "BYBIT" and adapted.timeframe == "4H", "exchange+rawSymbol identify the instrument"
    for bad in ({"exchange": "binance futures"}, {"raw_symbol": "BTC/USDT"}, {"interval": "2H"}, {"market_type": "PERP"}):
        request = {"exchange": "BYBIT", "raw_symbol": "BTCUSDT", "interval": "HOUR", "from": T0, "period": 60, "market_type": "SPOT", **bad}
        with pytest.raises(ValueError):
            OpenMarketAdapter(om, include_per_side=False).adapt(request)


def test_missing_fields() -> None:
    incomplete = dict(point(1))
    del incomplete["volume"]
    broken = dict(point(2), low="200")
    parsed = parse_candles({"points": [point(0), incomplete, broken, dict(point(3), extra="x")]}, per_side=False)
    assert [p.timestamp_ns for p in parsed.points] == [T0 * 10**9, (T0 + 180) * 10**9]
    assert any("missing volume" in item for item in parsed.rejected)
    assert any("invalid OHLC" in item for item in parsed.rejected)
    assert parsed.unexpected_fields == {"extra"}
    assert parse_candles({"points": []}, per_side=False).points == [], "an empty window is empty, not an error"
    with pytest.raises(OpenMarketError):
        parse_candles({"points": "nope"}, per_side=False)
    with pytest.raises(OpenMarketError):
        parse_candles({"a": [point(0)], "b": [point(1)]}, per_side=False)  # ambiguous envelope
    with pytest.raises(OpenMarketError):
        parse_candles({"series": [{"points": [point(0)]}]}, per_side=True)  # side missing


def test_deduplication() -> None:
    parsed = parse_candles({"points": [point(2), point(0), point(0), point(1), point(1, close="100.9")]}, per_side=False)
    unique, report = dedupe_candles(parsed.points, exchange="BINANCE_FUTURES", raw_symbol="BTCUSDT", interval="MINUTE", data_type="TRADE_SIDE_AGNOSTIC_AGG")
    assert [p.timestamp_ns for p in unique] == [T0 * 10**9, (T0 + 120) * 10**9]
    assert report.duplicates == 1 and report.reordered is True
    assert len(report.conflicts) == 1, "conflicting duplicates are dropped and reported, never picked"
    per_side = parse_candles(_per_side_payload(), per_side=True)
    unique, report = dedupe_candles(per_side.points, exchange="X", raw_symbol="Y", interval="MINUTE", data_type="TRADE_AGG")
    assert len(unique) == 3 and report.duplicates == 0, "BUY and SELL at the same timestamp are distinct points"


# --- TIM integration ------------------------------------------------------------

def falling(index: int, close: float) -> dict:
    return dict(point(index), open=str(close + 0.2), high=str(close + 0.5), low=str(close - 0.5), close=str(close))


def test_cli_openmarket_runs_the_scenario_pipeline(monkeypatch, capsys) -> None:
    # A falling series: a rising breakout series reaches a pre-existing defect in
    # scenario_generator.py (EntryModel.RETEST does not exist), outside this scope.
    om, _, _ = client(ok({"points": [falling(i, 100 - i * 0.3) for i in range(30)]}), ok(_per_side_payload()))
    monkeypatch.setattr(cli, "OpenMarketAdapter", lambda include_per_side: OpenMarketAdapter(om, include_per_side=include_per_side))
    code = cli.main(["--provider", "openmarket", "--exchange", "BINANCE_FUTURES", "--raw-symbol", "BTCUSDT",
                     "--interval", "MINUTE", "--from", str(T0), "--period", "1800", "--market-type", "FUTURES", "--validate"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert "schema_validation=PASS" in captured.err
    assert json.loads(captured.out)
    assert FAKE_KEY not in captured.out + captured.err


def test_cli_openmarket_fails_closed(monkeypatch, capsys) -> None:
    om, _, _ = client(HttpResult(401, {}, body({"error": "INVALID_API_KEY"})))
    monkeypatch.setattr(cli, "OpenMarketAdapter", lambda include_per_side: OpenMarketAdapter(om, include_per_side=include_per_side))
    code = cli.main(["--provider", "openmarket", "--exchange", "BINANCE_FUTURES", "--raw-symbol", "BTCUSDT",
                     "--interval", "MINUTE", "--from", str(T0), "--period", "60", "--market-type", "FUTURES"])
    captured = capsys.readouterr()
    assert code == 3 and captured.out == "" and "INVALID_SECRET" in captured.err


def test_existing_mmt_adapter_unchanged() -> None:
    structured = MMTStructuredDataAdapter().adapt({"symbol": "BTCUSDT", "candles": [], "net_delta": "12.5"})
    assert structured.venue == "MMT_GG" and structured.net_delta == Decimal("12.5")
    assert "mmt_structured_export_limited_to_recognized_fields" in structured.extra_notes
    assert MMTScreenshotAdapter().adapter_kind == "MMT_SCREENSHOT"
    assert cli.main.__code__.co_consts is not None
    parser_choices = ("generic", "mmt-structured", "mmt-screenshot", "openmarket")
    source = open(cli.__file__, encoding="utf-8").read()
    assert all(choice in source for choice in parser_choices)
    assert 'default="generic"' in source, "generic stays the default provider"


def test_existing_generic_adapter_unchanged() -> None:
    adapted = GenericOrderflowAdapter().adapt({"symbol": "ETHUSDT", "venue": "BINANCE", "candles": [], "total_volume": "7"})
    assert adapted.symbol == "ETHUSDT" and adapted.venue == "BINANCE" and adapted.total_volume == Decimal("7")
    assert adapted.missing_fields == ("trades",)


def test_proof_script_never_claims_pass_without_http_200(monkeypatch, capsys) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("om_proof", "scripts/openmarket_api_proof.py")
    proof = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proof)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(proof.socket, "getaddrinfo", lambda *a, **k: [])
    fake = Transport(HttpResult(403, {}, b"blocked by egress proxy"))
    monkeypatch.setattr(proof, "OpenMarketClient", lambda max_retries: OpenMarketClient(env=ENV, transport=fake, max_retries=0))
    monkeypatch.setattr("sys.argv", ["proof"])
    assert proof.main() == 1
    out = capsys.readouterr().out
    assert "AUTH=UNPROVEN" in out and "TLS=UNPROVEN" in out and "FINAL=FAIL" in out
    assert "AUTH=PASS" not in out and FAKE_KEY not in out


def test_traceback_locals_never_contain_the_key() -> None:
    import traceback
    om, _, _ = client(HttpResult(401, {}, body({"error": "INVALID_API_KEY"})))
    try:
        om.get_points(PARAMS)
    except OpenMarketError as error:
        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
    assert "SecretValue('@REDACTED@')" in rendered and FAKE_KEY not in rendered


@pytest.mark.parametrize("value", ["short", "has space inside key", "tab\tkey_12345678", "ümlaut_key_12345678"])
def test_malformed_key_is_rejected_before_any_request(value) -> None:
    om, transport, _ = client(env={**ENV, "TIM_OPENMARKET_API_KEY": value})
    with pytest.raises(OpenMarketError) as caught:
        om.get_points(PARAMS)
    assert caught.value.kind is OpenMarketErrorKind.NO_SECRET and transport.calls == []
    assert value not in str(caught.value)


def test_time_semantics_reject_points_outside_window_or_interval() -> None:
    request = {"exchange": "BINANCE_FUTURES", "raw_symbol": "BTCUSDT", "interval": "MINUTE", "from": T0, "period": 120, "market_type": "FUTURES"}
    outside = point(5)
    wrong_last = dict(point(1), lastTimestamp={"seconds": T0 + 60 + 60, "nanoseconds": 0})
    om, _, _ = client(ok({"points": [point(0), wrong_last, outside]}))
    adapted = OpenMarketAdapter(om, include_per_side=False).adapt(request)
    assert len(adapted.candles) == 1
    assert "check:time_semantics=FAIL" in adapted.extra_notes and "verify:time_unit=false" in adapted.extra_notes
    assert any("outside requested window" in m for m in adapted.missing_fields)
    assert any("first/last trade outside" in m for m in adapted.missing_fields)
    no_bounds = {key: value for key, value in point(0).items() if key not in {"firstTimestamp", "lastTimestamp"}}
    om, _, _ = client(ok({"points": [no_bounds]}))
    unproven = OpenMarketAdapter(om, include_per_side=False).adapt(request)
    assert "check:time_semantics=UNPROVEN" in unproven.extra_notes and "verify:time_unit=false" in unproven.extra_notes


def test_point_side_must_match_series_side() -> None:
    # Fallback path only: the documented path reads the side from series[].id.side.
    payload = {"data": [
        {"series": {"side": "BUY"}, "points": [dict(point(0), side="SELL"), dict(point(1), side="BUY")]},
        {"series": {"side": "SELL"}, "points": [point(0)]},
    ]}
    parsed = parse_candles(payload, per_side=True)
    assert [(p.side, p.timestamp_ns) for p in parsed.points] == [("BUY", (T0 + 60) * 10**9), ("SELL", T0 * 10**9)]
    assert any("contradicts series side" in item for item in parsed.rejected)


@pytest.mark.parametrize(
    "timestamp",
    ["0001-01-01T00:00:00+14:00", {"seconds": 10**15, "nanoseconds": 0}, {"seconds": -5, "nanoseconds": 0},
     "2026-09-21T14:13:00.1234567+00:00", "1969-12-31T23:59:59+00:00"],
)
def test_hostile_timestamps_stay_in_the_taxonomy(timestamp) -> None:
    parsed = parse_candles({"points": [dict(point(0), timestamp=timestamp), point(1)]}, per_side=False)
    assert len(parsed.points) == 1 and len(parsed.rejected) == 1


def test_hostile_json_stays_in_the_taxonomy() -> None:
    for raw in (b"[" * 200_000 + b"]" * 200_000, b'{"v": ' + b"9" * 5000 + b"}", b"\xff\xfe"):
        with pytest.raises(OpenMarketError) as caught:
            parse_json(raw)
        assert caught.value.kind is OpenMarketErrorKind.SCHEMA_MISMATCH
    parsed = parse_candles({"points": [dict(point(0), volume="1e400")]}, per_side=False)
    assert parsed.points == [] and "plausible" in parsed.rejected[0]


def test_cli_existing_providers_run_end_to_end(capsys) -> None:
    import io
    import sys as _sys
    for provider in ("generic", "mmt-structured"):
        _sys.stdin = io.StringIO(json.dumps({"symbol": "BTCUSDT", "candles": []}))
        try:
            code = cli.main(["--provider", provider])
        finally:
            _sys.stdin = _sys.__stdin__
        captured = capsys.readouterr()
        # No candles at all is not an input error: the pipeline fails closed to NO_TRADE.
        assert "not subscriptable" not in captured.err and code == 0
        assert json.loads(captured.out)["decision"]["status"] == "NO_TRADE"
