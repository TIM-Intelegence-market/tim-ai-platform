"""Public read-only English view: allowlist, no writes, rate limit, English text, disclaimer."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from src.dashboard import chart_live
from src.dashboard.public_en import DISCLAIMER, english_chart_model, english_note, journal_page
from src.dashboard.public_server import PublicDashboardServer, RateLimiter, clean_query
from src.dashboard.state import DashboardState
from tests.test_chart_live import NOW, fake_fetch


@pytest.fixture
def server(tmp_path, monkeypatch):
    # A fresh cache: another test may have left the shared one in its pause after an exchange error.
    monkeypatch.setattr(chart_live, "CACHE", chart_live.KlineCache(fake_fetch()))
    state = DashboardState()
    state.plan_journal_path = tmp_path / "tim.json"
    state.plan_journal_struct_path = tmp_path / "struct.json"
    state.plan_journal_level_path = tmp_path / "level.json"
    public = PublicDashboardServer(state, "127.0.0.1", 0)
    public.start()
    yield public, f"http://127.0.0.1:{public.httpd.server_address[1]}"
    public.stop()


def _get(url: str, method: str = "GET", headers: dict | None = None):
    try:
        with urlopen(Request(url, method=method, headers=headers or {}), timeout=10) as response:
            return response.status, dict(response.headers), response.read().decode()
    except HTTPError as error:
        return error.code, dict(error.headers), error.read().decode()


def test_binds_loopback_only():
    with pytest.raises(ValueError):
        PublicDashboardServer(DashboardState(), "0.0.0.0", 0)


def test_chart_page_is_english_with_disclaimer(server):
    _, base = server
    status, headers, body = _get(base + "/chart?symbol=ETHUSDT&tf=4h")
    assert status == 200
    assert "<html lang='en'>" in body and "Research, not financial advice. Observation and paper tracking only" in body and "research, not financial advice" in body
    assert "data-lang='en'" in body and "data-tf='4h'" in body and "data-symbol='ETHUSDT'" in body
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Robots-Tag"] == "noindex, nofollow"
    # No German UI words and no link into the internal Control Center.
    visible = re.sub(r"<style>.*?</style>", "", body, flags=re.S)
    for word in ("Zeitrahmen", "Kerzen", "Linien", "Freigabe", "/neu", "/api/state", "Mac", "Worker"):
        assert word not in visible


def test_internal_routes_are_not_served(server):
    _, base = server
    for path in ("/api/state", "/api/health", "/neu", "/neu/mac", "/neu/system", "/trader-journal", "/api/llm/explain",
                 "/api/rag", "/reports/x", "/setup-path", "/graphify", "/api/cockpit?area=mac", "/exports/analytics.json"):
        assert _get(base + path)[0] == 404, path


def test_writes_are_refused(server):
    _, base = server
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        assert _get(base + "/chart", method)[0] == 405


def test_root_redirects_to_chart_and_robots_disallow(server):
    _, base = server
    with urlopen(base + "/", timeout=10) as response:
        assert response.url.endswith("/chart")
    assert "Disallow: /" in _get(base + "/robots.txt")[2]


def test_chart_api_is_english(server):
    _, base = server
    status, _, body = _get(base + "/api/chart/live?symbol=BTCUSDT&tf=1h&evil=1")
    model = json.loads(body)
    assert status == 200 and model["symbol"] == "BTCUSDT" and model["candles"]
    assert model["groups"]["day"] == "Day (1D)" and model["groups"]["trend"] == "Trend lines"
    text = json.dumps([model["groups"], model["notes"], model.get("level_source"),
                       [(d["label"], d.get("note")) for d in model["drawings"]]], ensure_ascii=False)
    for word in ("lfd.", "Vortag", "Vorwoche", "Kerzen", "Tiefs", "Hochs", "läuft", "nicht", "gebrochen"):
        assert word not in text, word


def test_journal_page_english_and_empty_journals(server):
    _, base = server
    status, _, body = _get(base + "/journal?rule=level")
    assert status == 200 and "Paper journal" in body and "Level rule" in body and "Research, not financial advice. Observation and paper tracking only" in body
    assert "No plans yet." in body
    status, _, body = _get(base + "/api/plan-journal?rule=struct")
    assert status == 200 and "entries" in json.loads(body)


def test_rate_limit_per_client(server):
    public, base = server
    public.limiter = RateLimiter(per_minute=3)
    codes = [_get(base + "/robots.txt", headers={"CF-Connecting-IP": "203.0.113.9"})[0] for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert _get(base + "/robots.txt", headers={"CF-Connecting-IP": "203.0.113.10"})[0] == 200


def test_rate_limiter_window_resets():
    clock = [0.0]
    limiter = RateLimiter(per_minute=1, clock=lambda: clock[0])
    assert limiter.allow("a") and not limiter.allow("a")
    clock[0] = 61
    assert limiter.allow("a")


def test_clean_query_keeps_only_allowed_keys():
    assert clean_query("/chart", {"symbol": ["SOLUSDT"], "tf": ["1d"], "x": ["1"]}) == {"symbol": "SOLUSDT", "tf": "1d"}
    assert clean_query("/journal", {"rule": ["a" * 100]}) == {"rule": "a" * 16}


def test_english_model_translations():
    model = {"groups": {"running": "laufende POCs"}, "notes": ["Keine Kerzen für diese Auswahl.", "Irgendwas Neues und Unbekanntes"],
             "drawings": [{"name": "POC lfd.", "label": "1D POC lfd.", "note": "laufendes Tagesprofil"},
                          {"name": "Trend Tiefs ↗ gebrochen", "label": "4h Trend Tiefs ↗ gebrochen", "note": "durch die letzten zwei Swing-Tiefs (3 Kerzen je Seite)"}],
             "footprint": {"note": "Volume Profile und Footprint aus echten Trades gibt es nur für BTCUSDT: TIM sammelt nur dort Trades."},
             "level_source": "Binance-Klines (nur Anzeige)", "symbol": "SOLUSDT"}
    out = english_chart_model(model)
    assert out["groups"]["running"] == "running POCs"
    assert out["notes"] == ["No candles for this selection.", "Data note available in TIM's German view."]
    assert out["drawings"][0]["label"] == "1D POC (running)" and out["drawings"][0]["note"] == "running day profile"
    assert out["drawings"][1]["label"] == "4h Trend lows ↗ broken"
    assert out["drawings"][1]["note"] == "through the last two swing lows (3 candles per side)"
    assert out["footprint"]["note"].startswith("Volume profile and footprint from real trades exist only for BTCUSDT")
    assert out["level_source"] == "Binance klines (display only)" and out["name"] == "Solana"
    assert english_note("Level 1h: Börse nicht erreichbar (URLError).") == "Level 1h: Exchange not reachable, retrying shortly."


def test_journal_page_rows():
    entry = {"created_at": NOW.isoformat(), "direction": "LONG", "entry": 100000.0, "stop": 99000.0, "targets": [101500.0, None],
             "status": "CLOSED", "exit_reason": "STOP", "gross_r": -1.0, "net_r": -1.12, "excluded": {"reason": "Phantom"}}
    page = journal_page({"tim/1": {"entries": [entry]}}, "tim/1")
    assert "not counted (corrected) · closed (stop)" in page and "-1.12 R" in page and "TP1 101,500.00" in page
