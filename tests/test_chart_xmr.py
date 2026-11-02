"""Monero (XMRUSDT) as display market on the TIM chart, from the Binance USD-M perpetual."""

from __future__ import annotations

import io
import json

from src.dashboard import chart_live
from src.dashboard import market_context as mc
from src.dashboard.chart_live import SYMBOLS, KlineCache, build_live_chart, kline_url, tab_label
from src.dashboard.pages.chart import render_chart_page
from src.dashboard.public_en import chart_page, english_chart_model, english_note
from tests.test_chart_live import NOW, fake_fetch


def test_xmr_is_a_display_symbol_between_sol_and_gold() -> None:
    assert SYMBOLS[0] == "BTCUSDT" and SYMBOLS[-1] == "PAXGUSDT"  # BTC stays the default, gold stays last
    assert SYMBOLS.index("XMRUSDT") == SYMBOLS.index("SOLUSDT") + 1
    assert tab_label("XMRUSDT") == "XMR"


def test_only_xmr_reads_the_perpetual_klines() -> None:
    assert kline_url("XMRUSDT").startswith("https://fapi.binance.com/fapi/v1/klines?")
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "PAXGUSDT"):
        assert kline_url(symbol).startswith("https://api.binance.com/api/v3/klines?")


def test_fetch_klines_calls_the_futures_endpoint_for_xmr(monkeypatch) -> None:
    seen: list[str] = []
    row = [1_700_000_000_000, "340.1", "341.0", "339.5", "340.7", "12.5", 1_700_000_059_999]

    def fake_urlopen(url: str, timeout: float):
        seen.append(url)
        return io.BytesIO(json.dumps([row]).encode())

    monkeypatch.setattr(chart_live, "urlopen", fake_urlopen)
    rows = chart_live.fetch_klines("XMRUSDT", "1m", 5)
    assert seen == ["https://fapi.binance.com/fapi/v1/klines?symbol=XMRUSDT&interval=1m&limit=5"]
    assert rows[0]["close"] == 340.7 and rows[0]["symbol"] == "XMRUSDT"


def test_xmr_chart_has_candles_levels_and_the_perp_note() -> None:
    model = build_live_chart("XMRUSDT", "1h", cache=KlineCache(fake_fetch()), now=NOW)
    assert model["symbol"] == "XMRUSDT" and model["name"] == "Monero (XMR-Perp)"
    assert model["candles"] and model["drawings"]
    assert model["level_source"] == "Binance-Klines (nur Anzeige)"  # never the BTC runtime
    assert model["plans"] == []  # plan journals follow BTC only
    assert any(n.startswith("Monero über den Binance-Perpetual") for n in model["notes"])
    english = english_chart_model(model)
    assert english["name"] == "Monero (XMR perp)"
    assert any(n.startswith("Monero via the Binance perpetual") for n in english["notes"])
    assert english_note(chart_live.XMR_NOTE).startswith("Monero via the Binance perpetual")


def test_chart_pages_list_the_xmr_tab() -> None:
    html = chart_page("XMRUSDT", "4h")
    assert ">XMR</a>" in html and "symbol=XMRUSDT" in html


def test_german_chart_page_marks_xmr_as_perpetual_display() -> None:
    class State:
        def snapshot(self):
            return {}

        def chart_series(self):
            return {}

    html = render_chart_page(State(), "1h", symbol="XMRUSDT")
    assert ">XMR</a>" in html
    assert "Monero (XMR-Perp) ist reine Anzeige aus öffentlichen Binance-Kerzen (Perpetual)" in html


def test_missing_coinbase_product_is_not_retried_as_a_failure() -> None:
    calls: list[str] = []

    def funding(symbol: str):
        calls.append("funding")
        return {"symbol": symbol}

    def premium(symbol: str):
        return mc.coinbase_premium(fetch=lambda url: calls.append(url), symbol=symbol)

    cache = mc.ContextCache({"funding": funding, "premium": premium}, ttl=3600.0, fail_pause=0.0)
    first = cache.snapshot("XMRUSDT", background=False)
    assert first["funding"] == {"symbol": "XMRUSDT"} and first["premium"] is None
    cache.snapshot("XMRUSDT", background=False)
    assert calls == ["funding"]  # no Coinbase request, and no retry before the TTL
