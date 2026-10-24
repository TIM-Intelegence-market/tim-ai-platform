from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

import pytest

from src.dashboard import session_map
from src.dashboard.analysis_card import (
    REQUIRED,
    economics,
    journal_check,
    reason_text,
    with_journal_check,
)
from src.dashboard.chart_model import build_chart_model
from src.dashboard.pages.chart import _card_section
from src.dashboard.plan_journal import (
    FEE_PER_SIDE,
    RULE_LEVEL,
    SLIPPAGE_PER_SIDE,
    STOP_SLIPPAGE,
    load,
    update,
)
from tests.test_structure_plan import _runtime_series

NOW = datetime(2026, 10, 24, 14, 0, 30, tzinfo=timezone.utc)
REAL_MAP = session_map.build_session_map


def _with_levels(series, now=None):
    """The real preparation map with main levels placed so that a level/1 long exists."""
    prep = REAL_MAP(series, now)
    prep["levels"] = [
        {"label": "PWH · Vorwoche Hoch", "price": 80800.0, "source": "Vorwoche"},
        {"label": "Vortag VAH", "price": 80450.0, "source": "Profil Vortag"},
        {"label": "Vortag VAL", "price": 79800.0, "source": "Profil Vortag"},
        {"label": "PWL · Vorwoche Tief", "price": 79000.0, "source": "Vorwoche"},
    ]
    return prep


def _series() -> dict:
    """_runtime_series plus 4h and 1d candles built from its 1h candles."""
    series = _runtime_series()
    hours = series["1h"]
    for tf, size in (("4h", 4), ("1d", 24)):
        start = next(i for i, c in enumerate(hours) if datetime.fromisoformat(c["open_time"]).timestamp() % (size * 3600) == 0)
        groups = [hours[i:i + size] for i in range(start, len(hours) - size + 1, size)]
        series[tf] = [{**g[0], "timeframe": tf, "close_time": g[-1]["close_time"], "high": max(c["high"] for c in g),
                       "low": min(c["low"] for c in g), "close": g[-1]["close"], "volume": sum(c["volume"] for c in g)} for g in groups]
    return series


def _shifted(end: datetime) -> dict:
    """_runtime_series moved so its last candles close at ``end``."""
    shift = end - datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)
    return {tf: [{**c, "open_time": (datetime.fromisoformat(c["open_time"]) + shift).isoformat(),
                  "close_time": (datetime.fromisoformat(c["close_time"]) + shift).isoformat()} for c in rows]
            for tf, rows in _series().items()}


def test_economics_follow_the_journal_cost_model() -> None:
    eco = economics("LONG", 100.0, 99.0, [102.0, 103.0, 104.0])
    entry_cost = (FEE_PER_SIDE + SLIPPAGE_PER_SIDE) * 100.0
    assert eco["gross_r_tp1"] == 2.0
    assert eco["costs_r_tp1"] == pytest.approx(entry_cost + (FEE_PER_SIDE + SLIPPAGE_PER_SIDE) * 102.0, abs=1e-3)
    assert eco["net_r_tp1"] == pytest.approx(2.0 - eco["costs_r_tp1"], abs=0.01)
    assert eco["gross_r_plan"] == 3.0
    assert eco["net_r_stop"] == pytest.approx(-1.0 - entry_cost - (FEE_PER_SIDE + STOP_SLIPPAGE) * 99.0, abs=0.01)
    assert eco["round_trip_pct"] == pytest.approx(0.1616, abs=1e-3)
    assert 0 < eco["breakeven_hit_rate"] < 0.5
    short = economics("SHORT", 100.0, 101.0, [98.0])
    assert short["gross_r_tp1"] == 2.0 and short["gross_r_plan"] == 2.0
    assert economics("LONG", 100.0, 100.0, [101.0]) is None


def test_reason_codes_are_explained_in_words() -> None:
    assert "Margin" in reason_text("short_not_executable_on_spot")
    assert reason_text("pipeline_no_trade").startswith("Pipeline-Entscheidung NO_TRADE")
    assert reason_text("data_quality_partial") == "Datenqualität PARTIAL, nicht PASS"
    assert reason_text("something_new") == "something_new"


def test_card_has_every_required_field_and_says_why_no_trade(monkeypatch) -> None:
    monkeypatch.setattr(session_map, "build_session_map", _with_levels)
    card = build_chart_model(_runtime_series(), "30m", now=NOW, card=True)["analysis_card"]
    assert card["complete"] and card["missing"] == []
    assert all(card.get(key) not in (None, {}, []) for key in REQUIRED)
    assert card["symbol"] == "BTCUSDT" and card["timeframe"] == "30m"
    assert card["data"]["age_seconds"] == 30 and not card["data"]["stale"]
    assert card["trend"]["location"] and card["structure"]["market_state"]
    assert card["liquidity"]["above"] and card["liquidity"]["below"]
    assert card["orderflow"]["observations"] and "Footprint" in card["orderflow"]["limits"]
    level = next(p for p in card["plans"] if p["source"] == "level/1")
    assert level["id"] == "L1" and level["direction"] == "LONG" and level["economics"]["gross_r_tp1"] >= 1.5
    assert level["economics"]["net_r_tp1"] < level["economics"]["gross_r_tp1"]
    assert level["evidence"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert card["decision"]["status"] == "NO_TRADE" and level["decision"] == "NO_TRADE"
    assert any("Hypothesen-Register" in text for text in card["decision"]["reasons_text"])
    assert card["primary"] == "L1"


def test_card_without_plans_lists_the_dropped_reasons() -> None:
    card = build_chart_model(_runtime_series(), "30m", now=NOW, card=True)["analysis_card"]
    if not [p for p in card["plans"] if p["source"] == "level/1"]:
        assert set(card["dropped"]) <= set(card["decision"]["reasons_text"]) or card["plans"]
    assert card["decision"]["status"] == "NO_TRADE" and card["complete"]


def test_stale_data_is_no_trade() -> None:
    card = build_chart_model(_runtime_series(), "30m", now=NOW + timedelta(hours=3), card=True)["analysis_card"]
    assert card["data"]["stale"] and card["decision"]["status"] == "NO_TRADE"
    assert card["decision"]["reasons_text"] == ["Daten veraltet"]


def test_every_timeframe_gets_a_card() -> None:
    series = _series()
    for tf in ("30m", "1h", "4h", "1d", "1w", "1M"):
        card = build_chart_model(series, tf, now=NOW, card=True).get("analysis_card")
        assert card and card["timeframe"] == tf and card["decision"]["status"] == "NO_TRADE"
        if tf in ("30m", "1h", "4h", "1d"):  # the fixture holds about three weeks: 1w/1M may have too few candles
            assert card["complete"], (tf, card["missing"])


def test_chart_and_level_journal_agree(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(session_map, "build_session_map", _with_levels)
    series = _runtime_series()
    path = tmp_path / "level.json"
    update(path, series, now=NOW, rule=RULE_LEVEL)
    journal = load(path)
    model = with_journal_check(build_chart_model(series, "30m", now=NOW, card=True), series, path, NOW)
    card = model["analysis_card"]
    check = card["journal_check"]
    assert check["state"] == "MATCH" and check["journal_last_close"] == check["chart_last_close"] == "2026-10-24T14:00:00Z"
    for plan in (p for p in card["plans"] if p["source"] == "level/1"):
        entry = next(e for e in journal["entries"] if e["direction"] == plan["direction"] and e["status"] == "OPEN")
        assert (entry["entry"], entry["stop"], entry["targets"]) == (plan["entry"], plan["stop"], plan["targets"])
        assert entry["journal_decision"] == plan["decision"]
        assert set(entry["journal_decision_reasons"]) == set(plan["reasons"])
        assert entry["evidence_status"] == plan["evidence"]["status"]


def test_journal_check_states() -> None:
    plan = {"source": "level/1", "id": "L1", "direction": "LONG", "entry": 100.0, "stop": 99.0, "targets": [102.0, 103.0, 104.0], "decision": "NO_TRADE"}
    card = {"plans": [plan]}
    entry = {"direction": "LONG", "status": "OPEN", "timeframe": "30m", "entry": 100.0, "stop": 99.0, "targets": [102.0, 103.0, 104.0],
             "created_at": "2026-10-24T14:00:00Z", "journal_decision": "NO_TRADE"}
    close = "2026-10-24T14:00:00Z"
    assert journal_check(card, None, close)["state"] == "NO_JOURNAL"
    assert journal_check(card, {"last_plan_candle": close, "entries": [entry]}, close)["state"] == "MATCH"
    assert journal_check(card, {"last_plan_candle": "2026-10-24T13:30:00Z", "entries": []}, close)["state"] == "JOURNAL_BEHIND"
    assert journal_check(card, {"last_plan_candle": close, "entries": []}, close)["state"] == "MISSING"
    older = {**entry, "stop": 98.5, "created_at": "2026-10-24T12:00:00Z"}
    assert journal_check(card, {"last_plan_candle": close, "entries": [older]}, close)["state"] == "RESTING"
    assert journal_check(card, {"last_plan_candle": close, "entries": [{**entry, "stop": 98.5}]}, close)["state"] == "MISMATCH"


def test_card_section_renders_every_field(monkeypatch) -> None:
    monkeypatch.setattr(session_map, "build_session_map", _with_levels)
    card = build_chart_model(_runtime_series(), "30m", now=NOW, card=True)["analysis_card"]
    html = _card_section(card)
    for field in ("symbol", "structure", "trend", "liquidity", "orderflow", "entry", "stop", "targets", "r", "costs", "evidence", "data", "decision"):
        assert f"data-field='{field}'" in html, field
    assert "Warum kein Trade" in html and "data-plan='L1'" in html and "NO_TRADE" in html
    assert _card_section(None) == ""


def _server(tmp_path, series):
    from src.dashboard.app import DashboardServer, DashboardState

    state = DashboardState()
    state.plan_journal_level_path = tmp_path / "level.json"
    with state.lock:
        for rows in series.values():
            for candle in rows:
                state.record_chart_candle(candle, limit=600)
    server = DashboardServer(state, port=0)
    server.start()
    return state, server, server.server.server_address[1]


def _live_series() -> dict:
    now = datetime.now(timezone.utc)
    end = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
    return _shifted(end)


def test_page_api_and_journal_show_the_same_plan(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(session_map, "build_session_map", _with_levels)
    series = _live_series()
    state, server, port = _server(tmp_path, series)
    try:
        update(state.plan_journal_level_path, state.chart_series(), rule=RULE_LEVEL)
        with urlopen(f"http://127.0.0.1:{port}/api/chart?tf=30m", timeout=10) as response:
            card = json.loads(response.read())["analysis_card"]
        with urlopen(f"http://127.0.0.1:{port}/api/plan-journal?rule=level", timeout=10) as response:
            journal = json.loads(response.read())
        with urlopen(f"http://127.0.0.1:{port}/chart?tf=30m", timeout=10) as response:
            page = response.read().decode()
    finally:
        server.stop()
    assert card["journal_check"]["state"] == "MATCH"
    level = next(p for p in card["plans"] if p["source"] == "level/1")
    entry = next(e for e in journal["entries"] if e["direction"] == level["direction"] and e["status"] == "OPEN")
    assert (entry["entry"], entry["stop"], entry["targets"]) == (level["entry"], level["stop"], level["targets"])
    assert "Analyse-Steckbrief" in page and "Chart und Journal stimmen überein" in page and "data-plan='L1'" in page


SCREENSHOT_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "chart_card_screenshots.mjs"


def _node_playwright() -> bool:
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, timeout=30, check=False).returncode == 0


@pytest.mark.skipif(not _node_playwright(), reason="node with playwright not installed (cloud sandbox has it, the Mac runner not)")
def test_browser_renders_the_card_on_every_timeframe(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(session_map, "build_session_map", _with_levels)
    state, server, port = _server(tmp_path, _live_series())
    try:
        update(state.plan_journal_level_path, state.chart_series(), rule=RULE_LEVEL)
        result = subprocess.run(["node", str(SCREENSHOT_SCRIPT), f"http://127.0.0.1:{port}", str(tmp_path)],
                                capture_output=True, text=True, timeout=180, check=False)
    finally:
        server.stop()
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert {row["tf"] for row in report} == {"30m", "1h", "4h", "1d", "1w", "1M"}
    for row in report:
        if row["tf"] in ("1w", "1M") and not row["card"]:  # fixture has too few candles there: the page says so
            assert not row["overflow"], row
            continue
        assert row["card"] and row["decision"] == "NO_TRADE" and row["fields"] >= 8, row
        assert row["svg"] and not row["overflow"], row
    assert report[0]["journal"] == "Chart und Journal stimmen überein"
    assert all((tmp_path / f"chart-{row['tf']}.png").stat().st_size > 10_000 for row in report if row["card"])
    assert (tmp_path / "chart-30m-phone-card.png").stat().st_size > 10_000
