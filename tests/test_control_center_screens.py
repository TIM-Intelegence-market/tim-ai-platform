"""New Control Center (31.10.2026): the four screens, the header facts and their safety."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

import pytest

from src.dashboard import plan_notes, shell
from src.dashboard.plan_journal import SCHEMA as JOURNAL_SCHEMA
from src.dashboard.screens import CSS, SCREEN_CSP, SCRIPT, forschung_body, journal_body, journals, render, system_body
from src.dashboard.server import DashboardServer
from tests.test_dashboard_cockpit import _live_state

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _no_real_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TIM_WORKER_STATUS_URL", "http://127.0.0.1:9/api/status")
    monkeypatch.setenv("TIM_TRADING_TEAM_STATE", str(tmp_path / "no-trading-team"))


def _entry(n: int, direction: str, status: str, hours: float, price: float, net: float | None = None) -> dict:
    entry = {"id": f"{n:012x}", "timeframe": "30m", "created_at": (NOW - timedelta(hours=hours)).isoformat(), "direction": direction,
             "status": status, "entry": price, "stop": price - 300, "targets": [price + 450, price + 600, price + 900], "tp_hits": [],
             "gross_r": None, "net_r": None, "fee_r": None, "slippage_r": None}
    if status == "CLOSED":
        entry.update(gross_r=net + 0.1, net_r=net, fee_r=0.05, slippage_r=0.05, closed_at=NOW.isoformat(), exit_reason="STOP")
    return entry


@pytest.fixture()
def state(tmp_path: Path):
    state = _live_state(tmp_path, NOW)
    tim = [_entry(1, "LONG", "CLOSED", 40, 66800, 2.0), _entry(2, "SHORT", "CLOSED", 20, 67350, -1.0), _entry(3, "SHORT", "OPEN", 1, 67420)]
    struct = [_entry(11, "LONG", "FILLED", 3, 66950), {**_entry(12, "LONG", "CLOSED", 5, 66000, 5.0), "excluded": True}]
    for path, entries in ((state.plan_journal_path, tim), (state.plan_journal_struct_path, struct)):
        path.write_text(json.dumps({"schema": JOURNAL_SCHEMA, "entries": entries, "last_plan_candle": NOW.isoformat()}))
    state.plan_notes_path = tmp_path / "notes.json"
    state.plan_notes_path.write_text(json.dumps({"schema": plan_notes.SCHEMA, "notes": [
        {"id": "PN-00001", "plan_id": f"{2:012x}", "rule": "tim/1", "decision": "SKIPPED", "reason": "Gegen den Trend <b>", "created_at": NOW.isoformat()}]}))
    return state


def _hash(block: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(block.encode()).digest()).decode() + "'"


def test_csp_allows_exactly_the_screen_style_and_script() -> None:
    assert _hash(CSS) in SCREEN_CSP and _hash(SCRIPT) in SCREEN_CSP
    assert "unsafe-inline" not in SCREEN_CSP and "form-action 'none'" in SCREEN_CSP


def test_journal_counts_closed_trades_after_costs_and_skips_excluded(state) -> None:
    body = journal_body(state)
    assert "+1,00 R" in body  # 2,0 − 1,0; the excluded +5 R does not count
    assert "1 Gewinner · 1 Verlierer" in body and "0,20 R" in body  # costs of the two closed trades
    assert "Gegen den Trend &lt;b&gt;" in body  # the note is shown, escaped
    assert body.count("Notiz fehlt") == 3  # plans 1, 3 and 11 have no note yet


def test_journal_survives_a_broken_file(state) -> None:
    state.plan_journal_path.write_text("{kaputt")
    assert "Letzte Trades" in journal_body(state)
    assert [r["key"] for r in journals(state)["rules"]] == ["tim", "struct"]


def test_cockpit_shows_open_plans_result_and_chart(state) -> None:
    _, page = render("/", state)
    assert "<title>Cockpit · TIM</title>" in page and "<svg" in page
    assert "TIM-Regel 67.420" in page and "Struktur 66.950" in page and "im Trade" in page
    assert "Papier-Ergebnis" in page and "Heute zu tun" in page
    assert " style='" not in page and page.count("<script>") == 1


def test_system_lists_problems_first_and_open(state) -> None:
    body = system_body(state)
    lights = re.findall(r"data-s='(ok|warn|fail|unknown)'></span><span><b>", body)
    order = {"fail": 0, "warn": 1, "unknown": 2, "ok": 3}
    assert lights == sorted(lights, key=order.get) and "von" in body and "grün" in body
    assert "UNAVAILABLE" not in body.split("<h2>Ampel</h2>", 1)[1].split("</ul>", 1)[0].split("class='why'")[0]
    assert "href='/archiv'" in body


def test_forschung_reads_the_logbook(tmp_path: Path, state) -> None:
    book = tmp_path / "LOGBUCH.json"
    book.write_text(json.dumps({"updated": "2026-10-31", "entries": [
        {"id": "S1", "title": "CPI", "started": "2026-10-01", "status": "confirmed", "result": "1,40×", "lesson": ""},
        {"id": "S9", "title": "CHoCH", "started": "2026-10-27", "status": "not_testable", "result": "zu wenige", "lesson": "x"}]}))
    body = forschung_body(state, book)
    assert body.index("S9") < body.index("S1")  # newest first
    assert "nicht testbar" in body and "bestätigt" in body
    assert "Logbuch nicht lesbar" in forschung_body(state, tmp_path / "fehlt.json")


def test_header_facts_price_system_and_block(state) -> None:
    facts = shell.compute_facts(state)
    assert facts["price"] is not None and facts["system"] in {"ok", "warn", "fail", "unknown"}
    assert "Sperrzeit" in facts["block"]["text"] or "keine" in facts["block"]["text"]
    html = shell.header_pills(facts)
    assert "Papier · kein Echtgeld" in html and "BTC " in html
    assert "keine Daten" in shell.header_pills(None)


def test_screens_and_fragments_are_served(state) -> None:
    srv = DashboardServer(state, port=0)
    srv.start()
    port = srv.server.server_address[1]
    try:
        for path in ("/", "/trades", "/forschung", "/system"):
            with urlopen(f"http://127.0.0.1:{port}{path}", timeout=30) as response:
                assert response.status == 200 and response.headers["Content-Security-Policy"] == SCREEN_CSP
            with urlopen(f"http://127.0.0.1:{port}{path}?fragment=1", timeout=30) as response:
                assert "html" in json.loads(response.read())
    finally:
        srv.stop()


def test_forschung_shows_the_workshop(tmp_path: Path, state) -> None:
    from datetime import datetime, timezone

    from src.research_lab.learning.registry import ModelRegister
    from src.research_lab.workshop import shadow
    from src.research_lab.workshop.ideas import IdeaQueue
    from src.research_lab.workshop.trade_reflection import ReflectionLog, reflect_journal

    book = tmp_path / "LOGBUCH.json"
    book.write_text(json.dumps({"entries": []}))
    empty = forschung_body(state, book, tmp_path)
    assert "Forschungswerkstatt" in empty and "Keine offenen Ideen" in empty and "Kein Kandidat" in empty
    research = tmp_path / "data/research"
    queue = IdeaQueue(research / "IDEEN.jsonl")
    queue.add(source="uzi", title="Funding <Extrem>", hypothesis="Nach extremem Funding dreht BTC", data=["archive_usdm_klines"])
    trade = {"id": "p1", "status": "CLOSED", "direction": "LONG", "timeframe": "30m", "market_state": "RANGE", "gross_r": 0.1,
             "fee_r": 0.1, "slippage_r": 0.05, "net_r": -0.05, "max_favorable_r": 0.5, "max_adverse_r": -0.2,
             "exit_reason": "BREAK_EVEN_COSTS", "tp_hits": [], "created_at": "2026-10-30T10:00:00Z", "closed_at": "2026-10-30T14:00:00Z"}
    reflect_journal({"entries": [trade]}, ReflectionLog(research / "trade_reflections.jsonl"), name="tim", at="2026-10-31T14:00:00Z")
    (research / "schedule").mkdir()
    (research / "schedule/state.json").write_text(json.dumps({"trades": {"last_run": "2026-10-31T15:44:23Z", "last_result": {"ok": True}},
                                                             "weekly": {"last_run": "2026-10-31T15:44:29Z", "last_result": {"ok": False}}}))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    shadow.start(ModelRegister(tmp_path / shadow.REGISTER_PATH), "S12", model_id="S12-v1", variant_hash="h", code_commit="c",
                 study_version="v", cost_rule="k", min_trades=30, min_effect=0.05, horizon_minutes=60, at=now)
    body = forschung_body(state, book, tmp_path)
    assert "Funding &lt;Extrem&gt;" in body and "<Extrem>" not in body  # escaped
    assert "Kosten haben den Gewinn aufgefressen" in body and "S12-v1" in body
    assert "31.10. 16:44" in body and "Fehler" in body and "noch nie" in body
    assert "0 / 4" in body
    (research / "IDEEN.jsonl").write_text("kaputt\n")
    assert "Ideen-Liste nicht lesbar" in forschung_body(state, book, tmp_path)
    # nothing in the screen writes: the register still has its 3 entries
    assert len(ModelRegister(tmp_path / shadow.REGISTER_PATH).events()) == 3
