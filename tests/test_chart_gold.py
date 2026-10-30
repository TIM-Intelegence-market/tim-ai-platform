"""Gold (PAXGUSDT) as fourth display market on the TIM chart."""

from __future__ import annotations

from src.dashboard import chart_live
from src.dashboard.chart_live import SYMBOLS, KlineCache, build_live_chart, tab_label
from src.dashboard.public_en import chart_page, english_chart_model, english_note
from tests.test_chart_live import NOW, fake_fetch


def test_gold_is_a_display_symbol_with_its_own_tab() -> None:
    assert SYMBOLS[-1] == "PAXGUSDT" and SYMBOLS[0] == "BTCUSDT"  # BTC stays the default
    assert tab_label("PAXGUSDT") == "GOLD" and tab_label("ETHUSDT") == "ETH"


def test_gold_chart_has_candles_levels_and_the_paxg_note() -> None:
    model = build_live_chart("PAXGUSDT", "1h", cache=KlineCache(fake_fetch()), now=NOW)
    assert model["symbol"] == "PAXGUSDT" and model["name"] == "Gold (PAXG)"
    assert model["candles"] and model["drawings"]
    assert model["level_source"] == "Binance-Klines (nur Anzeige)"  # never the BTC runtime
    assert model["plans"] == []  # plan journals follow BTC only
    assert any(n.startswith("Gold über PAXG") for n in model["notes"])
    english = english_chart_model(model)
    assert english["name"] == "Gold (PAXG)"
    assert any(n.startswith("Gold via PAXG") for n in english["notes"])
    assert english_note(chart_live.GOLD_NOTE).startswith("Gold via PAXG")


def test_public_chart_page_lists_gold_tab() -> None:
    html = chart_page("PAXGUSDT", "4h")
    assert ">GOLD</a>" in html and "symbol=PAXGUSDT" in html
