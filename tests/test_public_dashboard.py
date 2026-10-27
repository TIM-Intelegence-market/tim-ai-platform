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
    assert "data-action='none'>Untick all</button>" in body
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


def _entry(minutes: int, status: str, net: float | None = None, excluded: bool = False, direction: str = "LONG") -> dict:
    from datetime import timedelta

    created = NOW + timedelta(minutes=minutes)
    entry = {"created_at": created.isoformat(), "direction": direction, "entry": 100000.0, "stop": 99000.0,
             "targets": [101500.0, 102000.0, 103000.0], "status": status}
    if status in ("FILLED", "CLOSED"):
        entry["filled_at"] = (created + timedelta(minutes=5)).isoformat()
    if status == "CLOSED":
        entry.update(closed_at=(created + timedelta(hours=1)).isoformat(), exit_reason="STOP" if net < 0 else "TP3",
                     gross_r=net + 0.2, net_r=net)
    if excluded:
        entry["excluded"] = {"reason": "Phantom"}
    return entry


def test_journal_page_puts_counted_trades_first_and_folds_the_rest():
    entries = ([_entry(i, "CLOSED", -1.36, excluded=True) for i in range(21)]
               + [_entry(100, "CLOSED", 1.21), _entry(200, "CLOSED", -2.06, direction="SHORT"),
                  _entry(300, "REPLACED"), _entry(400, "OPEN"), _entry(500, "FILLED", direction="SHORT")])
    page = journal_page({"tim/1": {"entries": entries}, "struct/1": {"entries": []}, "level/1": {"entries": []}}, "tim/1")
    main, corrected = page.split("Corrected entries, not counted", 1)
    # Headline: only the two counted trades, net −0.85 R, one win.
    assert "-0.85 R" in main and "-0.42 R" in main and "50 %" in main and "1 in trade · 1 waiting for entry" in main
    assert "not counted (corrected)" not in main  # corrected rows live only in the folded section
    assert corrected.count("not counted (corrected)") == 21 and "<small>(21)</small>" in page.split("Corrected entries")[1][:40]
    assert "Plans that never triggered" in main and "replaced" in main
    assert "<details class='pj-more'>" in page and "<polyline" in page  # folded sections and the result curve
    assert "class='pj-res pj-res--win'>Win<" in main and "class='pj-res pj-res--loss'>Loss<" in main
    assert "pj-tab pj-tab--active' href='/journal?rule=tim' aria-current='page'" in page and "/journal?rule=struct" in page
    assert " style=" not in page  # the CSP allows no inline style attributes


def test_journal_page_csp_matches_its_style(server):
    import base64
    import hashlib

    _, base = server
    status, headers, body = _get(base + "/journal")
    style = re.search(r"<style>(.*?)</style>", body, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()
    assert status == 200 and f"style-src 'sha256-{digest}'" in headers["Content-Security-Policy"]
    assert "script-src 'none'" in headers["Content-Security-Policy"] and "<script" not in body


def test_journal_page_shows_the_three_timeframes_first():
    page = journal_page({"short": {"entries": []}, "mid": {"entries": [_entry(100, "CLOSED", 1.21)]}, "long": {"entries": []},
                         "tim": {"entries": [_entry(100, "CLOSED", -1.0)]}}, "")
    tabs = page.split("aria-label='Timeframe'>", 1)[1].split("</nav>", 1)[0]
    assert [n in tabs for n in ("SHORT · 15m", "MID · 1h", "LONG · 1D")] == [True, True, True]
    assert "pj-tab pj-tab--active' href='/journal' aria-current='page'><b>MID · 1h" in tabs  # MID is the default
    assert "TIM rule 30m" in page.split("Earlier test versions", 1)[1] and "no plan yet" in tabs
    assert "+1.21 R" in page and "/journal/trade?rule=mid&amp;id=" in page and "/chart?tf=1h" in page


@pytest.mark.parametrize("entry,text", [
    (_entry(1, "CLOSED", -1.2), "Price went against the plan and hit the stop."),
    ({**_entry(1, "CLOSED", 0.3), "exit_reason": "BREAK_EVEN_COSTS", "tp_hits": ["x"]}, "A third was taken at TP1 at 101,500.00; the rest closed at break-even + costs."),
    ({**_entry(1, "CLOSED", 2.1), "exit_reason": "TP3", "tp_hits": ["a", "b", "c"]}, "All three targets were reached."),
    (_entry(1, "OPEN"), "Waiting for price to reach the entry."),
    (_entry(1, "REPLACED"), "Never filled: TIM drew new levels in the same direction."),
])
def test_explain_says_what_happened_in_plain_words(entry, text):
    from src.dashboard.public_en import explain

    sentence = explain({**entry, "scenario_type": "LIQUIDITY_SWEEP_REVERSAL", "market_state": "BALANCE"})
    assert sentence.startswith("Long on a reversal after a liquidity sweep in a range: entry 100,000.00, stop 99,000.00 (1.00 % away).")
    assert sentence.endswith(text)


def test_trade_page_has_every_number_and_unknown_ids_are_404(server, tmp_path):
    public, base = server
    entry = {**_entry(100, "CLOSED", -1.18), "id": "abc123def456", "fee_r": 0.1, "slippage_r": 0.08, "exit_price": 99000.0,
             "max_favorable_r": 0.4, "max_adverse_r": -1.0, "timeframe": "1h"}
    public.state.plan_journal_mid_path = tmp_path / "mid.json"
    public.state.plan_journal_mid_path.write_text(json.dumps({"schema": "tim_plan_journal/2", "entries": [entry]}))
    status, headers, body = _get(base + "/journal/trade?rule=mid&id=abc123def456")
    assert status == 200 and "Long · MID · 1h · closed · -1.18 R" in body and "Price went against the plan and hit the stop." in body
    assert "-0.10 R" in body and "-0.08 R" in body and "Worst during trade" in body and "<ol class='pj-steps'>" in body
    assert "script-src 'none'" in headers["Content-Security-Policy"]
    assert _get(base + "/journal/trade?rule=mid&id=ffffffffffff")[0] == 404
    assert _get(base + "/journal/trade?rule=mid&id=<script>")[0] == 404
    status, _, body = _get(base + "/api/plan-journal?rule=mid")
    assert status == 200 and json.loads(body)["entries"][0]["id"] == "abc123def456"


def test_public_chart_carries_tims_plans(server, tmp_path):
    from datetime import timedelta

    public, base = server
    opened = NOW - timedelta(hours=6)
    entry = {**_entry(0, "CLOSED", -1.18), "id": "abc123def456", "created_at": opened.isoformat(), "filled_at": opened.isoformat(),
             "closed_at": (opened + timedelta(hours=2)).isoformat(), "entry": 113000.0, "stop": 112500.0}
    public.state.plan_journal_struct_path = tmp_path / "struct.json"
    public.state.plan_journal_struct_path.write_text(json.dumps({"schema": "tim_plan_journal/2", "entries": [entry, {**entry, "id": "x", "excluded": {"r": 1}}]}))
    model = json.loads(_get(base + "/api/chart/live?symbol=BTCUSDT&tf=30m")[2])
    assert [(p["id"], p["group"], p["label"]) for p in model["plans"]] == [("abc123def456", "plans_old", "Structure 30m")]
    plan = model["plans"][0]
    assert plan["fill_t"] <= plan["close_t"] and plan["net_r"] == -1.18 and plan["entry"] == 113000.0
    assert model["groups"]["plans_mid"] == "TIM plans MID 1h" and "plans_mid" in model["default_groups"]
    assert "plans_old" in model["groups"] and "plans_old" not in model["default_groups"]  # test versions start hidden
    assert json.loads(_get(base + "/api/chart/live?symbol=ETHUSDT&tf=30m")[2])["plans"] == []
