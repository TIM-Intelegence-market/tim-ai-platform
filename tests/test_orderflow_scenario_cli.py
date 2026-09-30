"""End-to-end CLI runs with JSON files read from disk (ISO-8601 timestamps as strings)."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.orderflow_scenario import cli
from src.orderflow_scenario.adapters.generic import GenericOrderflowAdapter, _dt
from src.orderflow_scenario.adapters.mmt_screenshot import MMTScreenshotAdapter
from src.orderflow_scenario.domain import MarketContext
from src.orderflow_scenario.engines.pipeline import Pipeline, PipelineInputs

START = datetime(2026, 9, 28, 21, 0, tzinfo=timezone.utc)


def raw_candles(count: int = 24, fmt=lambda t: t.isoformat()) -> list[dict]:
    return [
        {
            "open_time": fmt(START + timedelta(minutes=15 * index)),
            "period_seconds": 900,
            "open": 1,
            "high": 2,
            "low": 0.5,
            "close": 1.5,
            "volume": 1,
            "trade_count": 1,
        }
        for index in range(count)
    ]


def run_cli(tmp_path, payload: dict, *extra: str) -> int:
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return cli.main(["--input", str(path), *extra])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-09-28T21:00:00+00:00", START),
        ("2026-09-28T21:00:00Z", START),
        ("2026-09-28T21:00:00.000z", START),
        ("2026-09-28T21:00:00", START),
        ("2026-09-28T23:00:00+02:00", START),
        (datetime(2026, 9, 28, 21, 0), START),
        (START, START),
        (None, None),
    ],
)
def test_dt_accepts_iso_strings_and_datetimes(value, expected):
    result = _dt(value)
    assert result == expected
    if result is not None:
        assert result.tzinfo is not None


@pytest.mark.parametrize("value", ["", "yesterday", "2026-13-01T00:00:00Z", 1790000000, 1.5])
def test_dt_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="invalid datetime value"):
        _dt(value)


def test_generic_adapter_parses_json_timestamps():
    adapted = GenericOrderflowAdapter().adapt({"symbol": "BTCUSDT", "candles": raw_candles(3, lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ"))})
    assert len(adapted.candles) == 3
    assert not [item for item in adapted.missing_fields if item.startswith("candles")]
    first = adapted.candles[0]
    assert datetime.fromisoformat(first["open_time"]) == START
    assert datetime.fromisoformat(first["close_time"]) == START + timedelta(seconds=900)


@pytest.mark.parametrize(
    ("provider", "payload"),
    [
        ("generic", {"symbol": "BTCUSDT", "candles": raw_candles()}),
        ("generic", {"symbol": "BTCUSDT", "candles": raw_candles(fmt=lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ"))}),
        ("mmt-structured", {"symbol": "BTCUSDT", "candles": raw_candles()}),
        ("mmt-screenshot", {"symbol": "BTCUSDT", "price_now": 1.5, "candles": raw_candles()}),
        ("mmt-screenshot", {"symbol": "BTCUSDT", "price_now": 1.5, "candles": raw_candles(fmt=lambda t: t.replace(tzinfo=None).isoformat())}),
    ],
)
def test_cli_end_to_end_from_json_file(tmp_path, capsys, provider, payload):
    assert run_cli(tmp_path, payload, "--provider", provider, "--validate") == 0
    captured = capsys.readouterr()
    assert "schema_validation=PASS" in captured.err
    output = json.loads(captured.out)
    assert output["symbol"] == "BTCUSDT"
    assert output["data_quality"]["status"] != "INSUFFICIENT_DATA"
    assert not [item for item in output["data_quality"]["missing_fields"] if item.startswith("candles(")]


def test_cli_fails_clearly_when_every_candle_is_rejected(tmp_path, capsys):
    payload = {"symbol": "BTCUSDT", "candles": raw_candles(3, lambda t: "not-a-time")}
    assert run_cli(tmp_path, payload) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no usable candles in input (3 rejected" in captured.err
    assert "max()" not in captured.err


def test_cli_without_candles_ends_in_no_trade(tmp_path, capsys):
    assert run_cli(tmp_path, {"symbol": "BTCUSDT", "candles": []}, "--validate") == 0
    output = json.loads(capsys.readouterr().out)
    assert output["data_quality"]["status"] == "INSUFFICIENT_DATA"
    assert output["decision"]["status"] == "NO_TRADE"


def test_pipeline_levels_from_empty_candles():
    context = MarketContext(symbol="BTCUSDT", venue="UNKNOWN", market_type="FUTURES", timeframe="4H", timestamp=START)
    analysis = Pipeline().run(PipelineInputs(market_context=context, candles=()))
    assert analysis.decision.status.value == "NO_TRADE"


@pytest.mark.parametrize(
    "bad",
    [{"period_seconds": 0}, {"period_seconds": -60}, {"high": 0.1}, {"open_time": "not-a-time"}, {"open": "x"}],
)
def test_screenshot_rejects_single_bad_candle_without_failing_the_run(tmp_path, capsys, bad):
    candles = raw_candles()
    candles[5] = {**candles[5], **bad}
    payload = {"symbol": "BTCUSDT", "price_now": 1.5, "candles": candles}
    assert run_cli(tmp_path, payload, "--provider", "mmt-screenshot", "--validate") == 0
    output = json.loads(capsys.readouterr().out)
    assert output["symbol"] == "BTCUSDT"


@pytest.mark.parametrize(
    ("provider", "payload"),
    [
        ("generic", [1, 2, 3]),
        ("generic", {"symbol": "BTCUSDT", "candles": [1, "x"]}),
        ("mmt-screenshot", [1, 2, 3]),
        ("mmt-screenshot", {"symbol": "BTCUSDT", "candles": "abc"}),
    ],
)
def test_cli_malformed_input_exits_cleanly(tmp_path, capsys, provider, payload):
    assert run_cli(tmp_path, payload, "--provider", provider) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("ERROR:")
    assert "Traceback" not in captured.err


def raw_trades(count: int = 3) -> list[dict]:
    return [
        {
            "event_time": (START + timedelta(seconds=index)).isoformat(),
            "price": 1.5,
            "quantity": 0.1,
            "trade_id": index,
            "buyer_is_maker": index % 2 == 0,
        }
        for index in range(count)
    ]


@pytest.mark.parametrize("provider", ["generic", "mmt-structured"])
def test_cli_passes_adapter_trades_to_the_pipeline(tmp_path, capsys, provider):
    payload = {"symbol": "BTCUSDT", "candles": raw_candles(), "trades": raw_trades()}
    assert run_cli(tmp_path, payload, "--provider", provider, "--validate") == 0
    output = json.loads(capsys.readouterr().out)
    assert "trades" not in output["data_quality"]["missing_fields"]


def test_pipeline_inputs_rebuild_trade_models():
    inputs = cli._pipeline_inputs(GenericOrderflowAdapter(), {"symbol": "BTCUSDT", "candles": raw_candles(), "trades": raw_trades(2)})
    assert [trade.trade_id for trade in inputs.trades] == [0, 1]
    assert inputs.trades[0].event_time == START
    assert inputs.trades[0].buyer_is_maker is True


def test_cli_without_trades_still_reports_them_missing(tmp_path, capsys):
    assert run_cli(tmp_path, {"symbol": "BTCUSDT", "candles": raw_candles()}, "--validate") == 0
    output = json.loads(capsys.readouterr().out)
    assert "trades" in output["data_quality"]["missing_fields"]


def test_cli_with_price_but_no_candles_ends_in_no_trade(tmp_path, capsys):
    assert run_cli(tmp_path, {"symbol": "BTCUSDT", "price_now": 1.5, "candles": []}, "--validate") == 0
    output = json.loads(capsys.readouterr().out)
    assert output["data_quality"]["status"] == "INSUFFICIENT_DATA"
    assert output["decision"]["status"] == "NO_TRADE"
    assert output["scenarios"] == []


def _without_period(candles: list[dict]) -> list[dict]:
    return [{key: value for key, value in candle.items() if key != "period_seconds"} for candle in candles]


@pytest.mark.parametrize(
    ("timeframe", "seconds"),
    [(None, 14400), ("4H", 14400), ("15m", 900), ("1h", 3600), ("1D", 86400), ("30s", 30)],
)
@pytest.mark.parametrize("adapter", [GenericOrderflowAdapter(), MMTScreenshotAdapter()])
def test_candle_period_defaults_to_timeframe(adapter, timeframe, seconds):
    candles = _without_period(raw_candles(2))
    if timeframe is not None:
        for candle in candles:
            candle["timeframe"] = timeframe
    adapted = adapter.adapt({"symbol": "BTCUSDT", "price_now": 1.5, "candles": candles})
    first = adapted.candles[0]
    assert datetime.fromisoformat(first["close_time"]) - datetime.fromisoformat(first["open_time"]) == timedelta(seconds=seconds)


@pytest.mark.parametrize("adapter", [GenericOrderflowAdapter(), MMTScreenshotAdapter()])
def test_candle_period_follows_payload_timeframe(adapter):
    adapted = adapter.adapt({"symbol": "BTCUSDT", "price_now": 1.5, "timeframe": "15m", "candles": _without_period(raw_candles(2))})
    first = adapted.candles[0]
    assert first["timeframe"] == "15m"
    assert datetime.fromisoformat(first["close_time"]) - datetime.fromisoformat(first["open_time"]) == timedelta(minutes=15)


@pytest.mark.parametrize("adapter", [GenericOrderflowAdapter(), MMTScreenshotAdapter()])
def test_explicit_period_wins_over_timeframe(adapter):
    adapted = adapter.adapt({"symbol": "BTCUSDT", "price_now": 1.5, "timeframe": "4H", "candles": raw_candles(2)})
    first = adapted.candles[0]
    assert datetime.fromisoformat(first["close_time"]) - datetime.fromisoformat(first["open_time"]) == timedelta(seconds=900)


@pytest.mark.parametrize("adapter", [GenericOrderflowAdapter(), MMTScreenshotAdapter()])
def test_unknown_timeframe_without_period_rejects_the_candle(adapter):
    candles = _without_period(raw_candles(1))
    candles[0]["timeframe"] = "weekly"
    adapted = adapter.adapt({"symbol": "BTCUSDT", "price_now": 1.5, "candles": candles})
    assert adapted.candles == ()
    assert any("weekly" in item for item in adapted.missing_fields)
