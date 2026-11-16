"""Nasdaq-100 (NDX) as display market on the TIM chart, candles from the public Yahoo chart endpoint."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.dashboard import chart_live
from src.dashboard.chart_live import SYMBOLS, KlineCache, build_live_chart, parse_yahoo_klines, tab_label
from src.dashboard.public_en import chart_page, english_chart_model

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
START = int(datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc).timestamp())


def payload(n: int = 40, step: int = 3600) -> dict:
    ts = [START + i * step for i in range(n)]
    base = [25_000.0 + i for i in range(n)]
    return {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [{
        "open": base, "high": [b + 5 for b in base], "low": [b - 5 for b in base], "close": [b + 1 for b in base], "volume": [0] * n}]}}]}}


def test_index_tab_and_symbol() -> None:
    assert "NDX" in SYMBOLS and SYMBOLS[0] == "BTCUSDT"
    assert tab_label("NDX") == "NASDAQ"


def test_parse_hourly_bars_marks_the_open_bar() -> None:
    rows = parse_yahoo_klines(payload(), "NDX", "1h", 1000, now=datetime.fromtimestamp(START + 5.5 * 3600, timezone.utc))
    assert len(rows) == 40 and rows[0]["open"] == 25_000.0 and rows[0]["symbol"] == "NDX"
    assert rows[4]["closed"] is True and rows[5]["closed"] is False


def test_parse_aggregates_four_hours_and_drops_bad_bars() -> None:
    data = payload(8)
    data["chart"]["result"][0]["indicators"]["quote"][0]["close"][2] = None
    rows = parse_yahoo_klines(data, "NDX", "4h", 1000, now=NOW)
    assert rows and all(r["high"] >= r["low"] for r in rows)
    assert len(rows) <= 3


def test_parse_rejects_empty_answer() -> None:
    with pytest.raises(ValueError):
        parse_yahoo_klines({"chart": {"result": None}}, "NDX", "1h", 10)


def test_ndx_chart_has_candles_note_and_no_trades() -> None:
    cache = KlineCache(lambda symbol, interval, limit: parse_yahoo_klines(payload(300, 1800), symbol, interval, limit, now=NOW))
    model = build_live_chart("NDX", "30m", cache=cache, now=NOW)
    assert model["symbol"] == "NDX" and model["name"] == "Nasdaq-100"
    assert model["candles"] and model["plans"] == [] and model["funding"] is None
    assert model["level_source"] == "Yahoo-Finance-Kerzen (nur Anzeige)" and model["index_source"] == "yahoo"
    assert any(n.startswith("Nasdaq-100 (^NDX)") for n in model["notes"])
    english = english_chart_model(model)
    assert english["name"] == "Nasdaq-100"
    assert any(n.startswith("Nasdaq-100 (^NDX) from Yahoo") for n in english["notes"])


def test_ndx_unsupported_timeframe_is_a_note_not_a_crash() -> None:
    model = build_live_chart("NDX", "3m", cache=KlineCache(lambda *a: []), now=NOW)
    assert model["candles"] == [] and any("3m gibt es nicht" in n for n in model["notes"])


def test_index_has_its_own_failure_pause() -> None:
    assert chart_live.INDEX_CACHE is not chart_live.CACHE


def test_public_chart_page_lists_nasdaq_tab() -> None:
    html = chart_page("NDX", "1h")
    assert ">NASDAQ</a>" in html and "symbol=NDX" in html
