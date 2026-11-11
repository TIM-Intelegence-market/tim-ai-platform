"""Chart-Urteil (src/dashboard/chart_verdict.py): Chart-Lage without look-ahead, frozen rules, paper shadow."""
from __future__ import annotations

import json
from datetime import timedelta

from src.dashboard import chart_verdict as cv
from src.dashboard.plan_journal import SCHEMA
from tests.test_analysis_summary import NOW, _trending_series
from tests.test_orderflow_shadow import lage


def chart(**extra) -> dict:
    """A chart like Uzi's screenshot of 11.11.2026 (BTC 1h)."""
    base = {"price": 73846.0, "day": {"vah": 74400.0, "poc": 73850.0, "val": 72800.0},
            "levels": [{"label": "1D VAH", "price": 74400.0}, {"label": "1D POC", "price": 73850.0}, {"label": "1D VAL", "price": 72800.0},
                       {"label": "1W Low", "price": 73333.0}, {"label": "1D Low (poor)", "price": 72691.0}],
            "structure": {"1h": {"trend": "DOWN", "protected": 74600.0, "target": 72691.0}},
            "trendlines": [{"tf": "1h", "kind": "LOW", "price": 73677.6, "rising": True, "label": "1h Trend Tiefs ↑"}],
            "orderflow": None}
    return {**base, **extra}


def sides(verdict: dict) -> dict:
    return {p["rule"]: p["side"] for p in verdict["points"]}


def test_screenshot_case_long_at_the_poc_is_not_taken():
    v = cv.judge("LONG", 73846.0, chart(), stop=73500.0, target=74600.0)
    rules = sides(v)
    assert rules["R1"] == cv.AGAINST  # at the 1D POC, middle of value
    assert rules["R2"] == cv.AGAINST  # 1h structure down
    assert rules["R4"] == cv.AGAINST and "1D VAH" in cv.text(v)  # VAH before the target
    assert v["decision"] == cv.SKIP and "R6-R8 keine frische Orderflow-Lage" in v["skipped"]


def test_long_at_value_low_on_a_rising_trend_line():
    c = chart(day={"vah": 74400.0, "poc": 73850.0, "val": 73700.0}, structure={"1h": {"trend": "UP", "protected": 73400.0, "target": 74300.0}})
    v = cv.judge("LONG", 73700.0, c, stop=73350.0, target=74250.0)
    rules = sides(v)
    assert rules["R1"] == cv.FOR and rules["R2"] == cv.FOR and rules["R3"] == cv.FOR and rules["R5"] == cv.FOR
    assert rules["R4"] == cv.AGAINST  # the 1D POC 73,850 lies before the target
    assert v["score"] == v["for"] - v["against"] and v["decision"] == cv.TAKE


def test_short_mirrors_and_trend_line_against():
    c = chart(trendlines=[{"tf": "1h", "kind": "LOW", "price": 73800.0, "rising": True, "label": "1h Trend Tiefs ↑"}])
    v = cv.judge("SHORT", 73820.0, c)  # short right onto a rising support line
    assert sides(v)["R5"] == cv.AGAINST and sides(v)["R2"] == cv.FOR
    assert "R4 ohne Stop/Ziel" in v["skipped"]


def test_orderflow_rules_absorption_wave_cvd():
    flow = cv.orderflow_view({**lage("auf", price=73700.0, at=NOW), "day": {"cvd": 120.0},
                              "levels": [{"name": "1D VAL", "price": 73690.0, "absorption": True},
                                         {"name": "1D POC", "price": 73850.0, "absorption": True}]}, NOW)
    v = cv.judge("LONG", 73700.0, chart(orderflow=flow), stop=73400.0, target=74000.0)
    texts = [p["text"] for p in v["points"]]
    assert any("Absorption am 1D VAL" in t for t in texts) and any("Absorption auf dem Weg" in t for t in texts)
    assert sides(v)["R7"] == cv.FOR and sides(v)["R8"] == cv.FOR


def test_orderflow_counts_only_when_fresh_and_near_the_moment():
    assert cv.orderflow_view(lage("auf", at=NOW), NOW + timedelta(minutes=5)) is not None
    assert cv.orderflow_view(lage("auf", at=NOW), NOW + timedelta(minutes=30)) is None  # too old for that moment
    assert cv.orderflow_view(lage("auf", at=NOW + timedelta(minutes=30)), NOW) is None  # taken later: no look-ahead
    assert cv.orderflow_view({**lage("auf"), "stale": True}, NOW) is None


def test_chart_lage_uses_only_candles_closed_by_then():
    series = _trending_series()
    early = NOW - timedelta(days=2)
    c = cv.chart_lage(series, early)
    assert cv._time(c["candle_close"]) <= early
    cut = {tf: [x for x in rows if cv._time(x["close_time"]) <= early] for tf, rows in series.items()}
    assert cv.chart_lage(cut, early) == c  # later candles change nothing
    full = cv.chart_lage(series, NOW)
    assert full["day"] and full["structure"]["1h"]["trend"] == "UP" and full["levels_source"] == "Kerzen-Näherung"


def _journal(path, *entries) -> None:
    path.write_text(json.dumps({"schema": SCHEMA, "entries": [{**e, "symbol": "BTCUSDT"} for e in entries]}))


def _plan(pid: str, created, status: str = "OPEN", **extra) -> dict:
    return {"id": pid, "direction": "LONG", "timeframe": "1h", "created_at": created.isoformat(), "entry": 90000.0, "stop": 89600.0,
            "targets": [90800.0], "status": status, **extra}


def test_shadow_records_new_plans_and_compares_after_close(tmp_path):
    series = _trending_series()
    journal, path = tmp_path / "tim_plan_journal_mid.json", tmp_path / "verdict.json"
    _journal(journal, _plan("old", NOW - timedelta(hours=3)))
    state = cv.update(path, [journal], series, lage("auf", at=NOW), now=NOW)
    assert state["plans"] == {} and state["ruleset"] == cv.RULESET  # plans before the start are not counted
    t1 = NOW + timedelta(minutes=1)
    _journal(journal, _plan("p1", NOW))
    state = cv.update(path, [journal], series, lage("auf", at=t1), now=t1)
    record = state["plans"]["tim_plan_journal_mid.json:p1"]
    assert record["chart_at_plan"]["as_of"] == NOW.isoformat() and record["urteil"]["ruleset"] == cv.RULESET
    first = record["urteil"]
    # later Lage and candles never change the recorded Urteil
    t2 = NOW + timedelta(hours=2)
    _journal(journal, _plan("p1", NOW, "CLOSED", net_r=1.2))
    state = cv.update(path, [journal], series, lage("ab", at=t2), now=t2)
    record = state["plans"]["tim_plan_journal_mid.json:p1"]
    assert record["urteil"] == first and record["journal"]["net_r"] == 1.2
    s = state["summary"]
    assert s["closed"] == 1 and s["by_decision"]["alle"]["n"] == 1 and not s["judgeable"]


def test_render_escapes_and_names_the_rules():
    view = {"chart": chart(), "LONG": cv.judge("LONG", 73846.0, chart()), "SHORT": cv.judge("SHORT", 73846.0, chart())}
    view["LONG"]["points"].append({"rule": "X", "side": cv.FOR, "text": "<script>"})
    html = cv.render_de(view, None)
    assert "TIM liest den Chart" in html and "<script>" not in html and cv.RULESET in html
    assert "Orderflow-Lage nicht frisch" in html
    assert "kein Chart-Urteil" in cv.render_de(None, None)


def test_chart_page_shows_the_verdict(tmp_path, monkeypatch):
    from src.dashboard.pages.chart import render_chart_page
    from src.dashboard.state import DashboardState

    monkeypatch.setattr(cv, "DEFAULT_PATH", tmp_path / "verdict.json")
    state = DashboardState()
    state.plan_journal_path = tmp_path / "tim.json"
    page = render_chart_page(state, symbol="BTCUSDT")
    assert "tc-verdict" in page
