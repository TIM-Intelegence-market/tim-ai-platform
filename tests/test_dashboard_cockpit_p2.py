"""Cockpit P2: "Markt & Pläne", "Mac jetzt" and the worker tiles on "Lage"."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from src.dashboard.cockpit import mac as mac_module
from src.dashboard.cockpit.lage import build_lage
from src.dashboard.cockpit.mac import build_mac, fetch_worker, service_tiles, worker_tiles
from src.dashboard.cockpit.markt import build_markt, timeframe_of
from src.dashboard.cockpit.page import COCKPIT_CSP, mac_body, markt_body, render_mac, render_markt
from src.dashboard.cockpit.sources import BudgetedSources, SourceResult
from src.dashboard.server import DashboardServer
from tests.test_dashboard_cockpit import _live_state, _state

NOW = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
CLOSED_PORT = "http://127.0.0.1:9/api/status"


@pytest.fixture(autouse=True)
def _no_real_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # The Mac runner has the real worker dashboard on 8767; tests must not read it.
    monkeypatch.setenv("TIM_WORKER_STATUS_URL", CLOSED_PORT)
    monkeypatch.setenv("TIM_TRADING_TEAM_STATE", str(tmp_path / "no-trading-team"))


def _ok(value) -> SourceResult:
    return SourceResult("x", True, value, None, 0.0)


def _worker(now: datetime = NOW, **change) -> dict:
    data = {
        "generated_at": int(now.timestamp()),
        "worker": {"agent": {"running": True, "loaded": True, "pid": 1}, "current_issue": None, "developer": None, "paused_ci": False,
                   "process_observation_ok": True, "run_active": False, "ollama": {"model": "qwen3.5:9b", "model_installed": True, "reachable": True}},
        "current": None, "stalled": [], "github": {"ok": True, "error": None, "loading": None},
        "log": {"intake_interval_secs": 300, "last_intake": {"output": "no issue"}, "last_error": {"age_estimate_secs": 315600, "text": "alter Fehler"}},
        "open": [{"number": 401, "title": "Log-Grenze", "url": "https://github.com/TIM-Intelegence-market/tim-ai-platform/issues/401", "eligible": True},
                 {"number": 376, "title": "Journal", "url": "javascript:alert(1)", "eligible": False, "stage": "skipped", "waiting_reason": "Triage"}],
        "done": [{"issue": 311, "title": "alt", "pr_number": 322, "state": "MERGED", "merged_at": "2026-10-16T16:47:46Z", "pr_url": "https://github.com/x/pull/322"},
                 {"issue": 331, "title": "neu", "pr_number": 338, "state": "MERGED", "merged_at": "2026-10-20T01:24:37Z", "pr_url": "https://github.com/x/pull/338"},
                 {"issue": 350, "title": "offen", "pr_number": 360, "state": "OPEN", "pr_created_at": "2026-10-23T01:00:00Z", "pr_url": "https://github.com/x/pull/360"}],
    }
    for key, value in change.items():
        if key in data["worker"]:
            data["worker"][key] = value
        else:
            data[key] = value
    return data


def _by_id(tiles) -> dict:
    return {t.id: t for t in tiles}


# --- issue worker -------------------------------------------------------------

def test_unreachable_worker_is_grey_with_reason() -> None:
    tiles, details = worker_tiles(SourceResult("worker", False, None, "Quelle nicht lesbar: Connection refused", 0.0), NOW)
    tiles = _by_id(tiles)
    assert tiles["worker"].state == "unknown" and "antwortet nicht" in tiles["worker"].reason
    assert tiles["ci_runner"].state == "unknown" and details["reachable"] is False


def test_idle_worker_waits_and_ci_is_free() -> None:
    tiles, details = worker_tiles(_ok(_worker()), NOW)
    tiles = _by_id(tiles)
    assert tiles["worker"].value == "wartet auf Aufgaben" and tiles["worker"].state == "ok"
    assert "alle 5 min" in tiles["worker"].detail
    assert tiles["ci_runner"].value == "kein Lauf gemeldet", "the worker cannot prove the runner is idle when its CI pause is off"
    assert tiles["queue"].value == "1 bereit · 2 offen"
    assert tiles["last_done"].value == "#331 → PR #338", "newest merge first; an open PR is not done"
    assert details["last_error"]["recent"] is False, "an error from days ago is history"


def test_ci_run_pauses_worker() -> None:
    tiles = _by_id(worker_tiles(_ok(_worker(paused_ci=True)), NOW)[0])
    assert tiles["worker"].value == "pausiert" and tiles["worker"].state == "ok"
    assert tiles["ci_runner"].value == "Testlauf läuft"


def test_busy_worker_names_issue_and_ci_state_is_unknown() -> None:
    current = {"issue": 401, "worktree_created_at": int((NOW - timedelta(minutes=12)).timestamp()),
               "events": [{"at": int(NOW.timestamp()), "phase": "Tests laufen", "place": "Worktree", "detail": None}]}
    data = _worker(current_issue=401, run_active=True, developer={"phase": "Claude-Helfer läuft"}, current=current)
    tiles, details = worker_tiles(_ok(data), NOW)
    tiles = _by_id(tiles)
    assert tiles["worker"].value == "arbeitet an #401"
    assert "Log-Grenze" in tiles["worker"].detail and "Claude-Helfer läuft" in tiles["worker"].detail
    assert "11:48 Uhr" in tiles["worker"].detail, "start time in German local time"
    assert tiles["ci_runner"].state == "unknown", "the worker cannot see CI while it works on an issue"
    assert details["current"]["url"].endswith("/issues/401") and details["current"]["events"][0]["phase"] == "Tests laufen"


def test_worker_not_loaded_is_red_and_recent_error_is_yellow() -> None:
    tiles = _by_id(worker_tiles(_ok(_worker(agent={"running": False, "loaded": False})), NOW)[0])
    assert tiles["worker"].state == "fail" and "nicht geladen" in tiles["worker"].reason
    log = {"intake_interval_secs": 300, "last_error": {"age_estimate_secs": 120, "text": "GitHub timeout"}}
    tiles = _by_id(worker_tiles(_ok(_worker(log=log)), NOW)[0])
    assert tiles["worker"].state == "warn" and "GitHub timeout" in tiles["worker"].reason


def test_github_loading_and_old_runs_are_not_problems() -> None:
    data = _worker(github={"ok": False, "loading": True, "error": None}, stalled=[{"issue": 12}])
    tiles, details = worker_tiles(_ok(data), NOW)
    assert _by_id(tiles)["worker"].state == "ok"
    assert details["stalled"] == [12]


def test_stale_worker_status_turns_yellow() -> None:
    tiles = _by_id(worker_tiles(_ok(_worker(now=NOW - timedelta(minutes=10))), NOW)[0])
    assert tiles["worker"].state == "warn" and "veraltet" in tiles["worker"].reason


def test_unsafe_links_are_dropped_and_text_escaped() -> None:
    data = _worker()
    data["open"][0]["title"] = "<script>alert(1)</script>"
    model = {"worker": [], "services": [], "now": [], "worker_details": worker_tiles(_ok(data), NOW)[1], "generated_at": NOW.isoformat()}
    body = mac_body(model)
    assert "javascript:" not in body and "<script>alert" not in body and "&lt;script&gt;" in body


class _Handler(BaseHTTPRequestHandler):
    payload: bytes = b"{}"

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture()
def fake_worker():
    _Handler.payload = json.dumps(_worker(now=datetime.now(timezone.utc), paused_ci=True)).encode()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/api/status"
    finally:
        server.shutdown()


def test_fetch_worker_reads_loopback_and_ignores_proxy(fake_worker: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:1")
    monkeypatch.setenv("http_proxy", "http://proxy.invalid:1")
    assert fetch_worker(fake_worker)["worker"]["paused_ci"] is True


def test_fetch_worker_refuses_other_hosts() -> None:
    with pytest.raises(ValueError):
        fetch_worker("http://example.com/api/status")


class _Redirect(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self.send_response(302)
        self.send_header("Location", "http://127.0.0.2:9/elsewhere")
        self.end_headers()

    def log_message(self, *args) -> None:
        pass


def test_fetch_worker_does_not_follow_redirects() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Redirect)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(ValueError, match="leitet um"):
            fetch_worker(f"http://127.0.0.1:{server.server_address[1]}/api/status")
    finally:
        server.shutdown()


@pytest.mark.parametrize("change", [
    {"open": 5}, {"done": [{"issue": 1, "state": "MERGED", "helpers": 3}]}, {"open": [{"number": "²", "eligible": True}]},
    {"log": {"last_error": {"age_estimate_secs": float("nan"), "text": "x"}}}, {"log": {"last_error": {"age_estimate_secs": float("inf"), "text": "x"}}},
    {"current": {"issue": 1, "events": 7}}, {"current": {"issue": 1, "worktree_created_at": 253402300799}}, {"generated_at": 253402300799},
    {"done": [{"issue": 1, "state": "MERGED", "merged_at": "9999-12-31T23:59:59+00:00"}]},
])
def test_odd_worker_json_keeps_page_and_ci_tile(change: dict) -> None:
    tiles, details = worker_tiles(_ok(_worker(**change)), NOW)
    ids = [t.id for t in tiles]
    assert "worker" in ids and "ci_runner" in ids
    model = {"worker": [t.to_dict() for t in tiles], "services": [], "now": [], "worker_details": details, "generated_at": NOW.isoformat()}
    assert "<h1>Mac jetzt</h1>" in render_mac(model)


def test_worker_json_without_worker_object_is_grey() -> None:
    tiles = _by_id(worker_tiles(_ok({"generated_at": 1}), NOW)[0])
    assert tiles["worker"].state == "unknown" and "Format" in tiles["worker"].reason and tiles["ci_runner"].state == "unknown"


def test_far_future_time_does_not_break_rendering() -> None:
    from src.dashboard.cockpit.page import local_time

    assert local_time("9999-12-31T23:59:59Z") == "—"


# --- background services --------------------------------------------------------

def _services(now: datetime, **files) -> dict:
    results = {name: SourceResult(name, True, {}, None, 0.0) for name in
               ("backup", "server_health_raw", "svc_validator", "svc_server_health", "svc_history_recovery", "svc_readiness_inputs", "svc_dashboard_refresh")}
    results["snapshot"] = SourceResult("snapshot", False, None, "nicht im Test", 0.0)
    results["trading_team"] = _ok({"exists": False})
    for name, value in files.items():
        results[name] = _ok(value)
    return _by_id(service_tiles(results, now))


def test_service_tiles_follow_their_status_files() -> None:
    tiles = _services(
        NOW,
        svc_validator={"check_timestamp": NOW.isoformat(), "overall_status": "DEGRADED", "checks_pass": 15, "checks_total": 19,
                       "failed_checks": ["deepseek_ready", "llama32_ready"]},
        svc_history_recovery={"checked_at": (NOW - timedelta(minutes=30)).isoformat(), "status": "PASS"},
        svc_dashboard_refresh={"checked_at_utc": NOW.isoformat(), "decision": {"action": "WAIT", "reason": "busy", "text": "Runner arbeitet"},
                               "deployed_commit": "affd9938ffc"},
        svc_server_health={"timestamp": NOW.isoformat(), "status": "AMBER", "checks": {"backup_path": {"status": "AMBER", "reason": "Linux-Pfad"}}},
    )
    assert tiles["validator"].state == "warn" and "deepseek_ready" in tiles["validator"].reason and tiles["validator"].value == "15/19 grün"
    assert tiles["history_recovery"].state == "warn" and "veraltet" in tiles["history_recovery"].reason, "30 min silence on a 30 s service"
    assert tiles["dashboard_refresh"].state == "ok" and tiles["dashboard_refresh"].value == "wartet" and "affd993" in tiles["dashboard_refresh"].detail
    assert tiles["server_health"].state == "warn" and "Linux-Pfad" in tiles["server_health"].reason
    assert tiles["readiness_inputs"].state == "unknown" and tiles["readiness_inputs"].reason
    assert tiles["runtime"].state == "unknown", "snapshot not readable gives grey, not green"


def test_failed_deploy_agent_is_red() -> None:
    tiles = _services(NOW, svc_dashboard_refresh={"checked_at_utc": NOW.isoformat(), "decision": {"action": "HOLD", "reason": "ci_failed", "text": "CI rot"}})
    assert tiles["dashboard_refresh"].state == "fail" and "CI rot" in tiles["dashboard_refresh"].reason


def test_trading_team_from_its_state_and_log(tmp_path: Path) -> None:
    folder = tmp_path / "tt"
    folder.mkdir()
    (folder / "state.json").write_text(json.dumps({"mode": "PAPER_ONLY", "open": [1], "shadow_open": [1, 2]}))
    (folder / "run.log").write_text(f"--- Lauf {(NOW - timedelta(minutes=2)).isoformat()} ---\nPapier-Bot: Guthaben 1000 USD frei\n")
    now = datetime.now(timezone.utc)
    tile = _services(now, trading_team=mac_module._trading_team(folder))["trading_team"]
    assert tile.state == "ok" and tile.value == "1 offen · 2 Schatten" and "Guthaben" in tile.detail
    (folder / "state.json").write_text(json.dumps({"mode": "LIVE", "open": []}))
    tile = _services(now, trading_team=mac_module._trading_team(folder))["trading_team"]
    assert tile.state == "fail" and "PAPER_ONLY" in tile.reason
    (folder / "state.json").write_text("{kaputt")
    tile = _services(now, trading_team=mac_module._trading_team(folder))["trading_team"]
    assert tile.state == "warn" and "nicht lesbar" in tile.reason


def test_healthy_validator_is_green_without_reason() -> None:
    tile = _services(NOW, svc_validator={"check_timestamp": NOW.isoformat(), "overall_status": "HEALTHY", "checks_pass": 19, "checks_total": 19})["validator"]
    assert tile.state == "ok" and tile.reason == ""


def test_mac_model_without_any_source_is_grey_not_green(tmp_path: Path) -> None:
    model = build_mac(_state(tmp_path), now=NOW, sources=BudgetedSources())
    assert model["schema"] == "tim_cockpit_mac/1"
    assert model["headline"] != "Alles läuft"
    assert {t["id"]: t["state"] for t in model["services"]}["validator"] == "unknown"
    assert all(t["reason"] for t in model["worker"] + model["services"] if t["state"] != "ok")
    assert "<h1>Mac jetzt</h1>" in render_mac(model)


def test_mac_model_with_worker(tmp_path: Path, fake_worker: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIM_WORKER_STATUS_URL", fake_worker)
    model = build_mac(_live_state(tmp_path, datetime.now(timezone.utc)), sources=BudgetedSources())
    worker = {t["id"]: t for t in model["worker"]}
    assert worker["worker"]["value"] == "pausiert" and worker["ci_runner"]["value"] == "Testlauf läuft"
    assert [line["label"] for line in model["now"]][:2] == ["CI-Runner", "Issue-Worker"]


# --- Lage ------------------------------------------------------------------------

def test_lage_shows_worker_and_ci_runner(tmp_path: Path, fake_worker: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIM_WORKER_STATUS_URL", fake_worker)
    model = build_lage(_live_state(tmp_path, datetime.now(timezone.utc)), sources=BudgetedSources())
    assert [t["id"] for t in model["mac"]] == ["worker", "ci_runner"]
    assert model["mac"][0]["value"] == "pausiert"


def test_lage_counts_a_broken_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(mac_module, "fetch_worker", lambda *a, **k: _worker(now=now, agent={"running": False, "loaded": False}))
    model = build_lage(_live_state(tmp_path, now), sources=BudgetedSources())
    assert any(t["id"] == "worker" and t["state"] == "fail" for t in model["attention"])


# --- Markt & Pläne ------------------------------------------------------------------

def _journal(tmp_path: Path, now: datetime) -> None:
    entries = [
        {"id": "P-1", "created_at": (now - timedelta(hours=3)).isoformat(), "status": "FILLED", "direction": "SHORT", "scenario_id": "<b>S1</b>",
         "entry": 67100.0, "stop": 67400.0, "targets": [66800.0, 66600.0], "filled_at": (now - timedelta(hours=2)).isoformat()},
        {"id": "P-2", "created_at": (now - timedelta(hours=1)).isoformat(), "status": "OPEN", "direction": "LONG", "scenario_id": "L2",
         "entry": 66900.0, "stop": 66700.0, "targets": [67200.0]},
        {"id": "P-0", "created_at": (now - timedelta(hours=30)).isoformat(), "status": "CLOSED", "direction": "LONG", "scenario_id": "L1",
         "entry": 66000.0, "stop": 65800.0, "targets": [66400.0], "closed_at": (now - timedelta(hours=26)).isoformat(), "exit_reason": "STOP",
         "gross_r": -1.0, "net_r": -1.08},
    ]
    (tmp_path / "plan.json").write_text(json.dumps({"schema": "tim_plan_journal/2", "entries": entries, "last_plan_candle": now.isoformat()}))


def test_markt_model_has_chart_prep_and_journals(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    state = _live_state(tmp_path, now)
    _journal(tmp_path, now)
    model = build_markt(state, sources=BudgetedSources())
    assert model["schema"] == "tim_cockpit_markt/1" and model["timeframe"] == "30m"
    assert model["chart"]["svg"].startswith("<svg") and model["chart"]["decision"]
    assert model["prep"]["ok"] is True and model["prep"]["last"] is not None
    assert [row["id"] for row in model["plan_journal"]["active"]] == ["P-2", "P-1"], "newest plan first"
    assert model["plan_journal"]["closed"][0]["net_r"] == -1.08
    body = markt_body(model)
    assert "<b>S1</b>" not in body and "&lt;b&gt;S1&lt;/b&gt;" in body
    assert "−1,08" in body or "-1,08 R" in body
    assert "Noch kein eigener Papier-Trade" in body


def test_markt_timeframe_switch_and_bad_value(tmp_path: Path) -> None:
    state = _live_state(tmp_path, datetime.now(timezone.utc))
    model = build_markt(state, "1h", sources=BudgetedSources())
    assert model["timeframe"] == "1h" and model["chart"]["timeframe"] == "1h"
    assert timeframe_of("<x>") == "30m" and timeframe_of(None) == "30m"
    assert "aria-current=page>1h<" in markt_body(model)


def test_markt_without_candles_explains_instead_of_crashing(tmp_path: Path) -> None:
    model = build_markt(_state(tmp_path), sources=BudgetedSources())
    assert model["chart"]["svg"] is None and model["chart"]["note"]
    assert model["prep"]["ok"] is False and model["prep"]["note"]
    assert "<h1>Markt &amp; Pläne</h1>" in render_markt(model)


def test_markt_broken_journal_log_shown_as_locked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.dashboard.plan_journal as pj

    monkeypatch.setattr(pj, "load_view", lambda path: {"entries": [], "integrity": "LOG_BROKEN: hash chain"})
    model = build_markt(_live_state(tmp_path, datetime.now(timezone.utc)), sources=BudgetedSources())
    assert "Plan-Journal gesperrt" in markt_body(model)


# --- routes ----------------------------------------------------------------------------

@pytest.fixture()
def server(tmp_path: Path):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _journal(tmp_path, now)
    srv = DashboardServer(_live_state(tmp_path, now), port=0)
    srv.start()
    try:
        yield f"http://127.0.0.1:{srv.server.server_address[1]}"
    finally:
        srv.stop()


@pytest.mark.parametrize("path, title", [("/neu/markt", "Markt &amp; Pläne"), ("/neu/markt?tf=1h", "Markt &amp; Pläne"), ("/neu/mac", "Mac jetzt")])
def test_new_areas_answer_fast_with_csp(server: str, path: str, title: str) -> None:
    began = time.monotonic()
    with urlopen(server + path, timeout=10) as response:
        body = response.read().decode()
        assert response.status == 200 and response.headers["Content-Security-Policy"] == COCKPIT_CSP
    assert time.monotonic() - began < 2.0
    assert f"<h1>{title}</h1>" in body and "Im Aufbau" not in body


def test_fragments_keep_timeframe(server: str) -> None:
    with urlopen(server + "/neu/markt?tf=1h", timeout=10) as response:
        assert "data-fragment='/neu/markt?tf=1h&amp;fragment=1'" in response.read().decode()
    with urlopen(server + "/neu/markt?tf=1h&fragment=1", timeout=10) as response:
        assert "aria-current=page>1h<" in json.loads(response.read())["html"]
    with urlopen(server + "/neu/mac?fragment=1", timeout=10) as response:
        assert "<h1>Mac jetzt</h1>" in json.loads(response.read())["html"]


def test_api_areas(server: str) -> None:
    with urlopen(server + "/api/cockpit?area=markt", timeout=10) as response:
        model = json.loads(response.read())
    assert model["schema"] == "tim_cockpit_markt/1" and "svg" not in model["chart"]
    with urlopen(server + "/api/cockpit?area=mac", timeout=10) as response:
        assert json.loads(response.read())["schema"] == "tim_cockpit_mac/1"
    with pytest.raises(HTTPError) as error:
        urlopen(server + "/api/cockpit?area=gibtsnicht", timeout=10)
    assert error.value.code == 404
