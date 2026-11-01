"""Text summary of TIM's analysis on the chart pages (German Control Center, public English view)."""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

from src.dashboard.analysis_summary import build_summary, level_en, render_de, render_en
from tests.test_structure_plan import _c, _runtime_series

NOW = datetime(2026, 10, 24, 14, 0, 30, tzinfo=timezone.utc)


def _trending_series(step: float = 20.0) -> dict:
    """30m and 1h candles that climb in waves: the structure turns up and breaks higher."""
    end = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)
    series = {}
    for tf, seconds in (("30m", 1800), ("1h", 3600)):
        start = end - timedelta(seconds=seconds * 500)
        rows, price = [], 80000.0
        for i in range(500):
            close = 80000.0 + step * i + 300 * math.sin(i / 6)
            rows.append(_c(tf, start + timedelta(seconds=seconds * i), seconds, price, max(price, close) + 5, min(price, close) - 5, close))
            price = close
        series[tf] = rows
    return series


def _plans() -> dict:
    return {
        "short": [{"status": "FILLED", "direction": "LONG", "entry": 79900.0, "fill_price": 79910.0, "stop": 79500.0},
                  {"status": "OPEN", "direction": "SHORT", "entry": 80500.0, "stop": 80900.0},
                  {"status": "OPEN", "direction": "LONG", "entry": 70000.0, "stop": 69000.0, "excluded": True},
                  {"status": "CLOSED", "direction": "LONG", "entry": 79000.0, "stop": 78500.0}],
        "level": [{"status": "OPEN", "direction": "LONG", "entry": 79000.0, "stop": 78500.0}],  # retired rule: not summarised
    }


def test_no_candles_gives_no_summary_but_a_clear_text():
    summary = build_summary({}, {}, NOW)
    assert summary["available"] is False and summary["paper_only"] is True
    assert "keine Zusammenfassung" in render_de(summary)
    assert "no summary" in render_en(summary)


def test_summary_facts_come_from_the_series_and_journals():
    summary = build_summary(_runtime_series(), _plans(), NOW)
    assert summary["available"] and not summary["stale"]
    assert summary["last_close_time"] == "2026-10-24T14:00:00+00:00"
    assert summary["bias"] in {"LONG", "SHORT", "NEUTRAL", "UNKNOWN"}
    above, below = summary["levels"]["above"], summary["levels"]["below"]
    assert all(item["price"] > summary["last"] for item in above) and all(item["price"] < summary["last"] for item in below)
    assert [i["price"] for i in above] == sorted(i["price"] for i in above)
    assert [i["price"] for i in below] == sorted((i["price"] for i in below), reverse=True)
    assert all(not item["label"].startswith(("Asia", "London", "New York", "IB")) for item in above + below)
    # Only waiting and running plans of the active journals; the fill price wins over the plan's entry.
    assert [(p["status"], p["direction"], p["entry"]) for p in summary["plans"]] == [("FILLED", "LONG", 79910.0), ("OPEN", "SHORT", 80500.0)]


def test_structure_follows_the_chart_bos_mss():
    from src.dashboard.chart_live import market_structure
    from src.dashboard.chart_model import analytical_series, clean_candles

    series = _trending_series()
    summary = build_summary(series, {}, NOW)
    rows = {row["timeframe"]: row for row in summary["structure"]}
    candles = clean_candles(analytical_series(series, NOW)["30m"], "30m")
    expected = market_structure(candles, "30m")
    assert rows["30m"]["trend"] == expected["trend"] == "UP"
    assert rows["30m"]["last_event"]["kind"] == expected["events"][-1]["kind"]
    assert rows["30m"]["protected"] == round(expected["protected"]["price"], 2)
    assert "<b>30m</b> aufwärts" in render_de(summary) and "<b>30m</b> up" in render_en(summary)
    # Price above every main level: said so, not left blank.
    assert summary["levels"]["above"] == []
    assert "keins (Kurs über allen Hauptleveln)" in render_de(summary) and "none (price above all main levels)" in render_en(summary)


def test_stale_data_is_flagged():
    summary = build_summary(_runtime_series(), {}, NOW + timedelta(hours=3))
    assert summary["stale"]
    assert "Daten veraltet" in render_de(summary) and "data is stale" in render_en(summary)


def test_texts_in_both_languages():
    summary = build_summary(_runtime_series(), _plans(), NOW)
    de, en = render_de(summary), render_en(summary)
    assert "Was TIM gerade sagt" in de and "keine Empfehlung" in de and "1 läuft (LONG 15m ab 79.910)" in de
    assert "1 wartet auf den Einstieg (SHORT 15m ab 80.500)" in de
    assert "What TIM's analysis says now" in en and "not advice" in en and "1 running (LONG 15m from 79,910)" in en
    assert "16:00 CEST" in en  # 24.10. is still summer time in Berlin
    visible = re.sub(r"<[^>]+>", " ", en)
    for word in ("Vortag", "Vorwoche", "heute", "Woche ", "Struktur", "läuft", "aufwärts", "abwärts", "Kurs", "über", "unter "):
        assert word not in visible
    assert "No open paper plans" in render_en(build_summary(_runtime_series(), {}, NOW))


def test_level_labels_in_english():
    assert level_en("PDH · Vortag Hoch · Poor High") == "PDH (prior day high) · Poor High"
    assert level_en("Vortag POC · Vorwoche POC") == "Prior day POC · Prior week POC"
    assert level_en("heute POC (laufend)") == "Today POC (running)"
    assert level_en("naked POC 23.10.") == "naked POC 23.10."


def test_chart_pages_show_the_summary(tmp_path, monkeypatch):
    from src.dashboard import chart_live
    from src.dashboard.pages.chart import render_chart_page
    from src.dashboard.public_server import PublicDashboardServer
    from src.dashboard.state import DashboardState
    from tests.test_chart_live import fake_fetch

    monkeypatch.setattr(chart_live, "CACHE", chart_live.KlineCache(fake_fetch()))
    state = DashboardState()
    state.plan_journal_path = tmp_path / "tim.json"
    page = render_chart_page(state, symbol="ETHUSDT")
    assert "data-summary='analysis_summary/1'" in page and "Was TIM gerade sagt" in page
    public = PublicDashboardServer(state, "127.0.0.1", 0)
    html = public.render_page("/chart", {"symbol": "BTCUSDT"})
    assert "What TIM's analysis says now" in html and "Was TIM" not in html
    # A broken summary only hides itself.
    monkeypatch.setattr("src.dashboard.analysis_summary.build_summary", lambda *a, **k: 1 / 0)
    assert "What TIM's analysis says now" not in public.render_page("/chart", {"symbol": "BTCUSDT"})
    assert "Zusammenfassung nicht verfügbar" in render_chart_page(state, symbol="ETHUSDT")
