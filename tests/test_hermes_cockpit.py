"""Hermes-Agent im Control Center: Bridge (src/dashboard/hermes_bridge.py), Bereich /neu/hermes, Kachel in der Lage."""
from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from src.dashboard import hermes_bridge as hb
from src.dashboard.cockpit.hermes import HERMES_CSP, build_hermes, render_hermes, tile
from src.dashboard.server import DashboardServer
from tests.test_dashboard_cockpit import _live_state

NOW = datetime(2026, 11, 8, 15, 0, tzinfo=timezone.utc)
CONFIG = 'model:\n  provider: "deepseek"\n  model: "deepseek-flash"\nstt:\n  model: "base"\nmcp_servers:\n  tim-ops:\n    command: x\n  tim-graph:\n    command: y\n'


def fake_hermes(path: Path, script: str) -> str:
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "hermes-home"
    home.mkdir()
    (home / "config.yaml").write_text(CONFIG)
    (home / ".env").write_text("DEEPSEEK_API_KEY=sk-not-a-real-key\nDISCORD_BOT_TOKEN=\n")
    monkeypatch.setenv("TIM_HERMES_HOME", str(home))
    monkeypatch.setenv("TIM_HERMES_BIN", fake_hermes(tmp_path / "hermes", 'q=$(cat); printf "\\033[32mAntwort auf: %s\\033[0m\\n" "$q"'))
    return home


def test_status_reads_config_without_exposing_the_key(home: Path, tmp_path: Path) -> None:
    status = hb.status(tmp_path / "log.json", NOW)
    assert status["installed"] and status["provider"] == "deepseek" and status["model"] == "deepseek-flash"
    assert status["key_present"] is True and status["mcp_servers"] == ["tim-ops", "tim-graph"] and status["last"] is None
    assert "sk-not" not in json.dumps(status)
    (home / ".env").write_text("DEEPSEEK_API_KEY=\n")
    assert hb.status(tmp_path / "log.json", NOW)["key_present"] is False


def test_ask_runs_hermes_over_stdin_and_keeps_a_bounded_log(home: Path, tmp_path: Path) -> None:
    log = tmp_path / "log.json"
    entry = hb.ask("Wie ist die Lage? $(rm -rf /) `x`", log_path=log, now=NOW)
    assert entry["ok"] and entry["answer"] == "Antwort auf: Wie ist die Lage? $(rm -rf /) `x`" and entry["seconds"] is not None
    for i in range(hb.KEEP + 3):
        hb.ask(f"Frage {i}", log_path=log, now=NOW)
    entries = hb.load_log(log)
    assert len(entries) == hb.KEEP and entries[-1]["question"] == f"Frage {hb.KEEP + 2}"
    assert hb.status(log, NOW)["asked_today"] == hb.KEEP


def test_ask_reports_failures_instead_of_raising(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIM_HERMES_BIN", fake_hermes(tmp_path / "broken", 'echo "kaputt" >&2; exit 3'))
    entry = hb.ask("Hallo", log_path=tmp_path / "log.json", now=NOW)
    assert entry["ok"] is False and "kaputt" in entry["error"]
    monkeypatch.setenv("TIM_HERMES_BIN", str(tmp_path / "missing"))
    assert "nicht installiert" in hb.ask("Hallo", log_path=tmp_path / "log.json", now=NOW)["error"]
    with pytest.raises(hb.QuestionError):
        hb.ask("   ", log_path=tmp_path / "log.json")
    with pytest.raises(hb.QuestionError):
        hb.ask("x" * (hb.MAX_QUESTION + 1), log_path=tmp_path / "log.json")


def test_tile_states(home: Path, tmp_path: Path) -> None:
    status = hb.status(tmp_path / "log.json", NOW)
    assert tile(status, NOW).state == "ok" and "bereit" in tile(status, NOW).value
    assert tile({**status, "key_present": False}, NOW).state == "warn"
    assert tile({**status, "installed": False}, NOW).state == "unknown"
    assert tile({**status, "last": {"ok": False, "error": "Timeout"}}, NOW).reason == "Timeout"
    assert tile(None, NOW).state == "unknown"


def test_page_shows_form_locally_and_only_the_log_remotely(home: Path, tmp_path: Path) -> None:
    log = tmp_path / "log.json"
    entry = hb.ask("<b>Frage</b>", log_path=log, now=NOW)

    class State:
        hermes_log_path = log

    model = build_hermes(State(), NOW, token="tok-123", asked=entry["id"])
    html = render_hermes(model)
    assert "name='token' value='tok-123'" in html and "action='/neu/hermes/ask'" in html and "<script" not in html
    assert "&lt;b&gt;Frage&lt;/b&gt;" in html and "hermes-new" in html and "deepseek-flash" in html
    remote = render_hermes(build_hermes(State(), NOW, can_ask=False))
    assert "<form" not in remote and "nur lesend" in remote
    assert "form-action 'self'" in HERMES_CSP


@pytest.fixture
def server(tmp_path: Path, home: Path):
    state = _live_state(tmp_path, datetime.now(timezone.utc).replace(microsecond=0))
    state.hermes_log_path = tmp_path / "hermes-log.json"
    srv = DashboardServer(state, port=0)
    srv.start()
    try:
        yield srv, f"http://127.0.0.1:{srv.server.server_address[1]}"
    finally:
        srv.stop()


def test_server_serves_page_and_answers_a_question(server) -> None:
    srv, base = server
    with urlopen(f"{base}/neu/hermes", timeout=10) as response:
        html = response.read().decode()
        assert response.status == 200 and "form-action 'self'" in response.headers["Content-Security-Policy"]
    assert "Hermes fragen" in html and "TIM-KI (Hermes)" in html
    with urlopen(f"{base}/system", timeout=10) as response:  # the System screen lists the Lage's system tiles as lights
        assert "TIM-KI (Hermes)" in response.read().decode()
    body = urlencode({"token": srv.form_token, "question": "Was macht TIM?"}).encode()
    request = Request(f"{base}/neu/hermes/ask", data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urlopen(request, timeout=120) as response:  # urllib follows the 303
        page = response.read().decode()
    assert "Antwort auf: Was macht TIM?" in page
    bad = Request(f"{base}/neu/hermes/ask", data=body, method="POST",
                  headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://evil.example"})
    with pytest.raises(HTTPError) as err:
        urlopen(bad, timeout=10)
    assert err.value.code == 403


# --- Zweitmeinung zu Plänen und Tagesbericht (Uzi 09.11.2026) ---

LAGE = {"as_of": "2026-11-08T15:00:00+00:00", "price": 103000.0, "tempo": "schnell",
        "wave": {"direction": "auf", "strength": 2, "phase": "Impuls", "exhaustion": False},
        "windows": {"5m": {"delta": 12.5}}, "perp": {"delta_5m": 40.0},
        "levels": [{"name": "POC", "distance_pct": 0.12, "absorption": "Käufer", "imbalance": 1.4}]}


def _journal(path: Path, entries: list[dict]) -> Path:
    from src.dashboard import plan_journal

    plan_journal.save({**plan_journal.empty_journal(), "entries": entries}, path)
    return path


def _plan(plan_id: str, created: datetime, **extra) -> dict:
    return {"id": plan_id, "timeframe": "15m", "direction": "LONG", "created_at": created.isoformat(), "entry": 103000.0,
            "stop": 102500.0, "targets": [103750.0, 104000.0, 104500.0], "status": "OPEN", **extra}


def test_plan_opinion_comments_new_plans_once_and_never_changes_the_journal(tmp_path: Path) -> None:
    from datetime import timedelta

    from src.dashboard import plan_opinion

    store, journal = tmp_path / "opinion.json", tmp_path / "short.json"
    _journal(journal, [_plan("old", NOW - timedelta(hours=1))])
    asked: list[str] = []

    def ask(text: str) -> dict:
        asked.append(text)
        return {"ok": True, "seconds": 2.0, "answer": "**DAFÜR:** Welle läuft mit.\nDAGEGEN: Stop liegt eng.\nURTEIL: Dafür."}

    plan_opinion.update(store, [journal], LAGE, now=NOW, ask=ask)  # start: the old plan is before started_at
    assert asked == []
    _journal(journal, [_plan("old", NOW - timedelta(hours=1)), _plan("a", NOW), _plan("b", NOW)])
    before = journal.read_bytes()
    state = plan_opinion.update(store, [journal], LAGE, now=NOW + timedelta(minutes=1), ask=ask)
    assert len(asked) == 1 and "old" not in state["plans"] and journal.read_bytes() == before
    assert "Einstieg 103000.00" in asked[0] and "Welle auf" in asked[0] and "POC" in asked[0] and len(asked[0]) <= plan_opinion.MAX_PROMPT
    assert state["plans"]["a"]["opinion"]["verdict"] == "DAFÜR" and state["plans"]["a"]["opinion"]["contra"] == "Stop liegt eng."
    plan_opinion.update(store, [journal], None, now=NOW + timedelta(minutes=2), ask=ask)
    state = plan_opinion.update(store, [journal], None, now=NOW + timedelta(minutes=3), ask=ask)
    assert len(asked) == 2 and state["plans"]["b"]["lage_at_plan"]["price"] == 103000.0  # the Lage of the plan's moment
    _journal(journal, [_plan("a", NOW, status="CLOSED", net_r=1.2, closed_at=NOW.isoformat()), _plan("b", NOW)])
    summary = plan_opinion.update(store, [journal], None, now=NOW + timedelta(minutes=4), ask=ask)["summary"]
    assert summary["by_verdict"] == {"DAFÜR": {"n": 1, "wins": 1, "sum_net_r": 1.2}} and summary["judgeable"] is False


def test_plan_opinion_gives_up_after_failures_and_on_late_plans(tmp_path: Path) -> None:
    from datetime import timedelta

    from src.dashboard import plan_opinion

    store, journal = tmp_path / "opinion.json", tmp_path / "short.json"
    plan_opinion.update(store, [journal], None, now=NOW, ask=lambda text: {"ok": False})
    _journal(journal, [_plan("a", NOW)])
    calls: list[str] = []

    def broken(text: str) -> dict:
        calls.append(text)
        raise RuntimeError("weg")

    for minute in range(1, 5):
        state = plan_opinion.update(store, [journal], None, now=NOW + timedelta(minutes=minute), ask=broken)
    assert len(calls) == plan_opinion.MAX_ATTEMPTS and state["plans"]["a"]["skipped"] == "RuntimeError" and "opinion" not in state["plans"]["a"]
    _journal(journal, [_plan("a", NOW), _plan("late", NOW + timedelta(minutes=5))])
    state = plan_opinion.update(store, [journal], None, now=NOW + timedelta(hours=2), ask=broken)
    assert len(calls) == plan_opinion.MAX_ATTEMPTS and "zu spät" in state["plans"]["late"]["skipped"]
    assert plan_opinion.parse("irgendwas")["verdict"] == plan_opinion.UNCLEAR
    assert plan_opinion.parse("Urteil: DAGEGEN")["verdict"] == "DAGEGEN"


def test_daily_report_is_written_once_per_slot_with_facts(tmp_path: Path) -> None:
    from datetime import timedelta

    from src.dashboard import daily_report

    store, journal = tmp_path / "reports.json", tmp_path / "short.json"
    evening = datetime(2026, 11, 8, 21, 5, tzinfo=timezone.utc)  # 22:05 in Germany
    _journal(journal, [_plan("a", evening - timedelta(hours=3), status="CLOSED", net_r=1.5, closed_at=(evening - timedelta(hours=1)).isoformat()),
                       _plan("b", evening - timedelta(hours=2), status="FILLED"),
                       _plan("x", evening - timedelta(days=3), status="CLOSED", net_r=-1.0, closed_at=(evening - timedelta(days=2)).isoformat())])
    asked: list[str] = []

    def ask(text: str) -> dict:
        asked.append(text)
        return {"ok": True, "answer": "Ruhiger Tag, ein Plan im Plus."}

    assert daily_report.update(store, {"15m": journal}, LAGE, now=evening - timedelta(hours=1, minutes=10), ask=ask) is None  # 20:55
    report = daily_report.update(store, {"15m": journal}, LAGE, lambda: [{"label": "Backup", "value": "alt", "reason": "3 Tage"}], now=evening, ask=ask)
    assert report["slot"] == "2026-11-08-22" and report["text"] == "Ruhiger Tag, ein Plan im Plus." and "Abendbericht" in asked[0]
    assert any("1 geschlossen (1 im Plus), Summe +1.50 R" in line for line in report["facts"])
    assert any("LONG im Trade" in line for line in report["facts"]) and any("Backup: alt (3 Tage)" in line for line in report["facts"])
    assert daily_report.update(store, {"15m": journal}, LAGE, now=evening + timedelta(minutes=5), ask=ask) is None and len(asked) == 1
    morning = datetime(2026, 11, 9, 7, 1, tzinfo=timezone.utc)

    def down() -> list:
        raise OSError("zu")

    second = daily_report.update(store, {"15m": journal}, None, down, now=morning, ask=lambda text: {"ok": False, "error": "Timeout"})
    assert second["slot"] == "2026-11-09-08" and second["text"] is None and second["error"] == "Timeout"
    assert "Control Center: Zustand nicht lesbar." in second["facts"] and second["since"] == report["until"]
    assert daily_report.update(store, {"15m": journal}, None, now=morning + timedelta(hours=5), ask=ask) is None  # 13:01, 8 Uhr is done
    assert daily_report.due_slot(datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc), []) is None  # 13:00, missed by too long
    assert daily_report.latest(store)["slot"] == "2026-11-09-08"


def test_hermes_page_shows_report_and_opinions(home: Path, tmp_path: Path) -> None:
    from src.dashboard import daily_report, plan_opinion

    journal = _journal(tmp_path / "short.json", [])

    class State:
        hermes_log_path = tmp_path / "log.json"
        daily_report_path = tmp_path / "reports.json"
        plan_opinion_path = tmp_path / "opinion.json"

    empty = render_hermes(build_hermes(State(), NOW))
    assert "Noch kein Bericht" in empty and "Noch keine Zweitmeinung" in empty
    plan_opinion.update(State.plan_opinion_path, [journal], LAGE, now=NOW, ask=None)
    _journal(journal, [_plan("a", NOW)])
    plan_opinion.update(State.plan_opinion_path, [journal], LAGE, now=NOW, symbol="BTCUSDT",
                        ask=lambda text: {"ok": True, "answer": "DAFÜR: <b>Welle</b>\nDAGEGEN: eng\nURTEIL: NEUTRAL"})
    daily_report.update(State.daily_report_path, {"15m": journal}, LAGE, now=datetime(2026, 11, 8, 21, 5, tzinfo=timezone.utc),
                        ask=lambda text: {"ok": True, "answer": "Alles ruhig."})
    html = render_hermes(build_hermes(State(), NOW, can_ask=False))
    assert "Alles ruhig." in html and "Urteil <b>NEUTRAL</b>" in html and "&lt;b&gt;Welle&lt;/b&gt;" in html and "<script" not in html


def test_bridge_own_jobs_stay_out_of_the_chat_log(home: Path, tmp_path: Path) -> None:
    log = tmp_path / "log.json"
    entry = hb.ask("x" * 900, log_path=log, now=NOW, limit=1500, record=False)
    assert entry["ok"] and hb.load_log(log) == []
    with pytest.raises(hb.QuestionError):
        hb.ask("x" * 900, log_path=log, now=NOW)


# --- Täglicher Kritiker (Uzi 11.11.2026) ---

def test_daily_critic_writes_once_a_day_from_facts_and_remembers_yesterday(tmp_path: Path) -> None:
    from datetime import timedelta

    from src.dashboard import daily_critic

    store = tmp_path / "critic.json"
    morning = datetime(2026, 11, 11, 6, 5, tzinfo=timezone.utc)  # 07:05 in Germany
    asked: list[str] = []

    def ask(text: str) -> dict:
        asked.append(text)
        return {"ok": True, "answer": f"PROJEKT: Schwäche {len(asked)}\nCHART AUS NUTZERSICHT: zu langsam"}

    def broken() -> list[str]:
        raise OSError("zu")

    sources = {"Journale": lambda: ["Papier-Journal 15m: 7 Tage: 3 geschlossen."], "Chart": broken}
    assert daily_critic.update(store, sources, now=morning - timedelta(minutes=10), ask=ask) is None  # 06:55
    report = daily_critic.update(store, sources, now=morning, ask=ask)
    assert report["slot"] == "2026-11-11" and "Schwäche 1" in report["text"]
    assert report["facts"] == ["Papier-Journal 15m: 7 Tage: 3 geschlossen.", "Chart: nicht lesbar (OSError)."]
    assert "CHART AUS NUTZERSICHT" in asked[0] and "Kritik von gestern:" not in asked[0] and len(asked[0]) <= daily_critic.MAX_PROMPT
    assert daily_critic.update(store, sources, now=morning + timedelta(hours=1), ask=ask) is None and len(asked) == 1
    daily_critic.update(store, sources, now=morning + timedelta(days=1), ask=ask)
    assert "Kritik von gestern:\nPROJEKT: Schwäche 1" in asked[1]
    silent = daily_critic.update(store, sources, now=morning + timedelta(days=2), ask=lambda text: {"ok": False, "error": "Timeout"})
    assert silent["text"] is None and silent["error"] == "Timeout" and silent["facts"]
    assert daily_critic.due_slot(morning + timedelta(hours=4), []) is None  # 11:05, missed by too long
    assert [r["slot"] for r in daily_critic.latest(store, 14)] == ["2026-11-13", "2026-11-12", "2026-11-11"]


def test_daily_critic_facts_come_from_journals_chart_and_cockpit(tmp_path: Path) -> None:
    from datetime import timedelta

    from src.dashboard import daily_critic

    journal = _journal(tmp_path / "short.json", [
        _plan("a", NOW - timedelta(days=3), status="CLOSED", net_r=1.5, closed_at=(NOW - timedelta(days=2)).isoformat()),
        _plan("b", NOW - timedelta(days=21), status="CLOSED", net_r=-1.0, closed_at=(NOW - timedelta(days=20)).isoformat()),
        _plan("c", NOW, status="OPEN")])
    assert daily_critic.journal_facts({"15m": journal}, NOW) == [
        "Papier-Journal 15m: 7 Tage: 1 geschlossen, 1 im Plus, +1.50 R netto; 30 Tage: 2 geschlossen, 1 im Plus, +0.50 R netto."]
    shadow = tmp_path / "shadow.json"
    shadow.write_text(json.dumps({"summary": {"closed": 4, "target": 30, "by_gate": {"GEGEN": {"n": 4, "sum_net_r": -2.0}}}}))
    assert daily_critic.shadow_facts({"Orderflow-Schatten": shadow, "Zweitmeinung": tmp_path / "none.json"}) == [
        "Orderflow-Schatten: 4 von 30 geschlossenen Plänen (GEGEN 4 Pläne -2.00 R).", "Zweitmeinung: noch keine Auswertung."]
    chart = daily_critic.chart_facts({"symbol": "BTCUSDT", "timeframe": "30m", "candles": [{}] * 300, "last_closed": "2026-11-08T14:30:00+00:00",
                                      "groups": {"day": "Tag", "vwap": "VWAP"}, "default_groups": ["day"],
                                      "drawings": [{"group": "day"}, {"group": "day"}], "plans": [{}], "bubbles": {"items": []},
                                      "footprint": {"bars": []}, "liquidation": None, "notes": ["Footprint: keine Trades"]}, 0.42)
    assert "300 Kerzen" in chart[0] and "gebaut in 0.4 s" in chart[0] and "day 2" in chart[1]
    assert "1 Pläne, 0 Volumen-Blasen" in chart[2] and "Liquidations-Karte fehlt" in chart[2] and chart[3] == "Hinweis im Chart: Footprint: keine Trades"
    cockpit = daily_critic.cockpit_facts({"headline": "1 Fehler", "system": [{"state": "fail"}, {"state": "ok"}], "market": [{"state": "unknown"}],
                                          "attention": [{"label": "Watchdog", "value": "rot", "reason": "runtime"}]})
    assert cockpit == ["Control Center: 1 Fehler; 3 Kacheln, 1 rot, 0 gelb, 1 ohne Daten.", "Braucht einen Blick: Watchdog: rot (runtime)."]
    assert daily_critic.merge_facts(tmp_path) == ["Merges: Git-Verlauf nicht lesbar."]


def test_daily_critic_reads_the_running_state_and_shows_on_the_page(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.dashboard import daily_critic

    monkeypatch.chdir(tmp_path)
    state = _live_state(tmp_path, datetime.now(timezone.utc).replace(microsecond=0))
    state.hermes_log_path, state.daily_critic_path = tmp_path / "log.json", tmp_path / "critic.json"
    state.plan_opinion_path, state.daily_report_path = tmp_path / "opinion.json", tmp_path / "reports.json"
    lines = daily_critic.gather(daily_critic.state_sources(state, root=tmp_path))
    assert any(line.startswith("Chart BTCUSDT 30m:") for line in lines) and any(line.startswith("Control Center:") for line in lines)
    assert any(line.startswith("Papier-Journal 1h:") for line in lines)
    assert "Noch keine Kritik" in render_hermes(build_hermes(state, NOW))
    daily_critic.update(state.daily_critic_path, {"x": lambda: ["Fakt <eins>"]}, now=datetime(2026, 11, 11, 6, 5, tzinfo=timezone.utc),
                        ask=lambda text: {"ok": True, "answer": "PROJEKT: <b>dünn</b>"})
    html = render_hermes(build_hermes(state, NOW, can_ask=False))
    assert "PROJEKT: &lt;b&gt;dünn&lt;/b&gt;" in html and "Fakt &lt;eins&gt;" in html and "id='h-critic'" in html
