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
