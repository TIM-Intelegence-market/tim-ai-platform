"""New Control Center (Cockpit) under /neu: tile rule, time budget, page and routes."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from src.dashboard.cockpit import lage as lage_module
from src.dashboard.cockpit.lage import build_lage
from src.dashboard.cockpit.page import AREAS, COCKPIT_CSP, SCRIPT, STYLE, lage_body, local_time, render_area, render_lage
from src.dashboard.cockpit.sources import BudgetedSources
from src.dashboard.cockpit.tiles import NO_REASON, attention, make_tile, state_of
from src.dashboard.server import DashboardServer
from src.dashboard.state import DashboardState

NOW = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_real_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # The Mac runner has the real worker dashboard on 8767; tests must not read it.
    monkeypatch.setenv("TIM_WORKER_STATUS_URL", "http://127.0.0.1:9/api/status")
    monkeypatch.setenv("TIM_TRADING_TEAM_STATE", str(tmp_path / "no-trading-team"))


def _state(tmp_path: Path) -> DashboardState:
    op = tmp_path / "operational"
    op.mkdir(exist_ok=True)
    return DashboardState(
        operational_watchdog_path=op / "watchdog_status.json", rolling_liveness_path=op / "rolling_liveness.json",
        plan_journal_path=tmp_path / "plan.json", plan_journal_struct_path=tmp_path / "plan_struct.json",
        trader_journal_path=tmp_path / "trader.json", qualification_root_path=tmp_path / "qualification",
        validator_path=tmp_path / "validator.json", events_path=tmp_path / "events.jsonl",
        completion_artifacts_path=tmp_path / "completion", legacy_readiness_artifacts_path=tmp_path / "legacy",
        readiness_path=tmp_path / "readiness.json", audit_path=tmp_path / "audit.json", quality_path=tmp_path / "quality.json",
        live_cutover_path=tmp_path / "cutover.json", gate_model_path=tmp_path / "gates.json",
        phase_c_checkpoint_path=tmp_path / "phase_c.json",
    )


def _live_state(tmp_path: Path, now: datetime) -> DashboardState:
    state = _state(tmp_path)
    op = tmp_path / "operational"
    (op / "backup_last_run.json").write_text(json.dumps({"completed_at": (now - timedelta(hours=7)).isoformat(), "status": "PASS", "bytes": 3.2e9}))
    (op / "deployment.json").write_text(json.dumps({"commit": "ddb8b90abcdef", "deployed_at_utc": (now - timedelta(hours=1)).isoformat(),
                                                     "ci_test": {"completed_at_utc": (now - timedelta(hours=2)).isoformat(), "conclusion": "success", "passed": 4100, "failed": 0}}))
    state.system_health.update({"database": "connected", "stream": "running", "last_raw_persisted_at": (now - timedelta(seconds=5)).isoformat()})
    price, start = 67000.0, now.replace(second=0) - timedelta(minutes=1500)
    minutes = []
    for i in range(1500):
        close = price + 40 * math.sin(i / 23)
        opened = start + timedelta(minutes=i)
        minutes.append({"symbol": "BTCUSDT", "timeframe": "1m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(minutes=1)).isoformat(),
                        "open": price, "high": max(price, close) + 5, "low": min(price, close) - 5, "close": close, "volume": 5.0})
        price = close
    with state.lock:
        for timeframe, size in (("1m", 1), ("15m", 15), ("1h", 60)):
            for k in range(0, len(minutes) - size + 1, size):
                group = minutes[k:k + size]
                state.record_chart_candle({**group[0], "timeframe": timeframe, "close_time": group[-1]["close_time"], "high": max(g["high"] for g in group),
                                           "low": min(g["low"] for g in group), "close": group[-1]["close"], "volume": sum(g["volume"] for g in group)}, limit=2000)
    return state


def _all_tiles(model: dict) -> list[dict]:
    return model["system"] + model["market"] + model["journals"]


# --- tile rule --------------------------------------------------------------

def test_status_words_map_to_four_states() -> None:
    assert state_of("PASS") == state_of("GREEN") == "ok"
    assert state_of("RED") == state_of("FAIL") == "fail"
    assert state_of("YELLOW") == state_of("BLOCKED") == state_of("DEGRADED") == "warn"
    assert state_of("UNAVAILABLE") == state_of(None) == state_of("DISABLED") == "unknown"


def test_tile_that_is_not_green_always_has_a_reason() -> None:
    tile = make_tile("x", "X", 1, "FAIL", source="data/x.json")
    assert tile.state == "fail" and tile.reason.startswith(NO_REASON) and "data/x.json" in tile.reason
    assert make_tile("y", "Y", 1, "PASS").reason == ""


def test_stale_data_turns_green_tile_yellow_with_its_age() -> None:
    tile = make_tile("x", "X", 1, "PASS", as_of=(NOW - timedelta(minutes=10)).isoformat(), max_age_seconds=120, now=NOW)
    assert tile.state == "warn" and "veraltet" in tile.reason and "10 min" in tile.reason
    fresh = make_tile("x", "X", 1, "PASS", as_of=(NOW - timedelta(seconds=30)).isoformat(), max_age_seconds=120, now=NOW)
    assert fresh.state == "ok" and fresh.age_seconds == 30


def test_stale_data_keeps_a_red_tile_red() -> None:
    tile = make_tile("x", "X", 1, "FAIL", reason="kaputt", as_of=(NOW - timedelta(hours=2)).isoformat(), max_age_seconds=60, now=NOW)
    assert tile.state == "fail" and tile.reason.startswith("kaputt") and "veraltet" in tile.reason


def test_freshness_without_timestamp_is_grey_not_green() -> None:
    tile = make_tile("x", "X", 1, "PASS", max_age_seconds=60, now=NOW)
    assert tile.state == "unknown" and "Zeitstempel" in tile.reason


def test_attention_lists_red_before_yellow_and_skips_grey() -> None:
    tiles = [make_tile("a", "A", 1, "WARN", reason="w"), make_tile("b", "B", 1, "FAIL", reason="f"), make_tile("c", "C", 1, "UNAVAILABLE", reason="g")]
    assert [t.id for t in attention(tiles)] == ["b", "a"]


# --- time budget ------------------------------------------------------------

def test_slow_source_is_cut_off_and_not_started_twice() -> None:
    sources = BudgetedSources(cache_seconds=0)
    calls = []

    def slow() -> int:
        calls.append(1)
        time.sleep(1.5)
        return 1

    began = time.monotonic()
    first = sources.run({"slow": slow, "fast": lambda: 2}, budget=0.2)
    assert time.monotonic() - began < 1.0
    assert not first["slow"].ok and "antwortet nicht" in first["slow"].error
    assert first["fast"].ok and first["fast"].value == 2
    second = sources.run({"slow": slow}, budget=0.2)
    assert not second["slow"].ok and "antwortet nicht" in second["slow"].error
    assert len(calls) == 1


def test_broken_source_becomes_reason() -> None:
    def broken() -> None:
        raise ValueError("kaputt")

    result = BudgetedSources().run({"x": broken}, budget=1)["x"]
    assert not result.ok and "ValueError" in result.error and "kaputt" in result.error


# --- model ------------------------------------------------------------------

def test_empty_runtime_shows_reasons_not_blank_or_red(tmp_path: Path) -> None:
    model = build_lage(_state(tmp_path), sources=BudgetedSources(cache_seconds=0))
    tiles = _all_tiles(model)
    assert {t["id"] for t in tiles} >= {"runtime", "market_data", "database", "watchdog", "backup", "deploy", "ci", "price", "plan_journal", "trader_journal"}
    for tile in tiles:
        assert tile["state"] in {"ok", "warn", "fail", "unknown"}
        if tile["state"] != "ok":
            assert tile["reason"], tile
    by_id = {t["id"]: t for t in tiles}
    assert by_id["price"]["state"] == "unknown" and "Kerzen" in by_id["price"]["reason"]
    assert by_id["backup"]["state"] == "unknown" and "Backup" in by_id["backup"]["reason"]
    assert by_id["plan_journal"]["state"] == "unknown"


def test_live_runtime_is_green_with_price_and_deploy(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    model = build_lage(_live_state(tmp_path, now), now=now, sources=BudgetedSources(cache_seconds=0))
    by_id = {t["id"]: t for t in _all_tiles(model)}
    assert by_id["runtime"]["state"] == "ok"
    assert by_id["market_data"]["state"] == "ok"
    assert by_id["database"]["state"] == "ok"
    assert by_id["backup"]["state"] == "ok" and by_id["backup"]["value"] == "3,2 GB"
    assert by_id["deploy"]["value"] == "ddb8b90"
    assert by_id["ci"]["state"] == "ok" and "4100" in by_id["ci"]["value"]
    assert by_id["price"]["state"] == "ok" and by_id["price"]["value"].endswith(" $")
    assert by_id["market_state"]["state"] == "ok"
    assert all(info["ok"] for name, info in model["sources"].items() if name != "worker"), "worker dashboard is not running in tests"


def test_stale_market_data_is_yellow_not_green(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    state = _live_state(tmp_path, now)
    state.system_health["last_raw_persisted_at"] = (now - timedelta(minutes=20)).isoformat()
    model = build_lage(state, now=now, sources=BudgetedSources(cache_seconds=0))
    market = next(t for t in model["system"] if t["id"] == "market_data")
    assert market["state"] in {"warn", "fail"} and market["reason"]
    assert any(t["id"] == "market_data" for t in model["attention"])


def test_slow_snapshot_turns_system_grey_instead_of_blocking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(tmp_path)
    original = lage_module._jobs

    def jobs(s):
        out = original(s)
        out["snapshot"] = lambda: time.sleep(3)
        return out

    monkeypatch.setattr(lage_module, "_jobs", jobs)
    began = time.monotonic()
    model = build_lage(state, budget=0.3, sources=BudgetedSources(cache_seconds=0))
    assert time.monotonic() - began < 1.5
    runtime = next(t for t in model["system"] if t["id"] == "runtime")
    assert runtime["state"] == "unknown" and "antwortet nicht" in runtime["reason"]
    assert not model["sources"]["snapshot"]["ok"]


def test_broken_plan_journal_log_is_red(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.dashboard import plan_journal

    monkeypatch.setattr(plan_journal, "load_view", lambda path: {**plan_journal.empty_journal(), "integrity": "LOG_BROKEN: hash", "blocked": True})
    model = build_lage(_state(tmp_path), sources=BudgetedSources(cache_seconds=0))
    tile = next(t for t in model["journals"] if t["id"] == "plan_journal")
    assert tile["state"] == "fail" and "beschädigt" in tile["reason"]


# --- page -------------------------------------------------------------------

def _hash(block: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(block.encode()).digest()).decode() + "'"


def test_csp_pins_the_one_style_and_script() -> None:
    assert _hash(STYLE) in COCKPIT_CSP and _hash(SCRIPT) in COCKPIT_CSP
    page = render_lage({"system": [], "market": [], "journals": [], "attention": [], "plans": []})
    assert page.count("<style>") == 1 and page.count("<script>") == 1
    assert re.search(r"<style>(.*?)</style>", page, re.S).group(1) == STYLE
    assert re.search(r"<script>(.*?)</script>", page, re.S).group(1) == SCRIPT


def test_stored_text_is_escaped() -> None:
    tile = make_tile("x", "<b>X</b>", "<script>alert(1)</script>", "FAIL", reason="<img src=x onerror=alert(1)>").to_dict()
    body = lage_body({"system": [tile], "market": [], "journals": [], "attention": [tile], "plans": [{"direction": "LONG", "title": "<i>t</i>", "lines": ["<u>l</u>"]}]})
    assert "<script>alert" not in body and "<img" not in body and "<i>t</i>" not in body
    assert "&lt;script&gt;" in body


def test_times_are_german_local_time() -> None:
    assert local_time("2026-10-24T09:35:00Z") == "11:35"
    assert local_time("2026-12-24T09:35:00Z", with_date=True) == "24.12. 10:35"


def test_areas_not_built_yet_link_old_pages() -> None:
    for area in AREAS:
        if area["built"]:
            continue
        page = render_area(area["key"])
        assert "Im Aufbau" in page
        for _, href, _ in area["pages"]:
            assert f"href='{href}'" in page


# --- server -----------------------------------------------------------------

@pytest.fixture()
def server(tmp_path: Path):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    srv = DashboardServer(_live_state(tmp_path, now), port=0)
    srv.start()
    try:
        yield f"http://127.0.0.1:{srv.server.server_address[1]}"
    finally:
        srv.stop()


def test_neu_serves_start_page_fast_with_csp(server: str) -> None:
    began = time.monotonic()
    with urlopen(server + "/neu", timeout=10) as response:
        body = response.read().decode()
        assert response.status == 200
        assert response.headers["Content-Security-Policy"] == COCKPIT_CSP
    assert time.monotonic() - began < 2.0
    assert "<h1>Lage</h1>" in body and "BTC-Preis" in body and "Braucht dich" in body


def test_fragment_and_api(server: str) -> None:
    with urlopen(server + "/neu?fragment=1", timeout=10) as response:
        assert "<h1>Lage</h1>" in json.loads(response.read())["html"]
    with urlopen(server + "/api/cockpit", timeout=10) as response:
        model = json.loads(response.read())
    assert model["schema"] == "tim_cockpit_lage/1" and model["mode"] == "OBSERVE"


def test_area_pages_and_unknown_area(server: str) -> None:
    for area in AREAS:
        with urlopen(server + area["href"], timeout=10) as response:
            assert response.status == 200
    with pytest.raises(HTTPError) as error:
        urlopen(server + "/neu/gibtsnicht", timeout=10)
    assert error.value.code == 404


def test_old_start_page_still_served(server: str) -> None:
    with urlopen(server + "/", timeout=20) as response:
        assert response.status == 200


# --- findings of the adversarial review -------------------------------------

def test_red_tile_without_timestamp_stays_red() -> None:
    tile = make_tile("x", "X", 1, "FAIL", reason="kaputt", as_of="bad", max_age_seconds=60, now=NOW)
    assert tile.state == "fail" and "Zeitstempel" in tile.reason


def test_concurrent_request_joins_running_call() -> None:
    sources = BudgetedSources(cache_seconds=0)
    calls = []

    def job() -> int:
        calls.append(1)
        time.sleep(0.3)
        return 7

    import threading

    out = {}
    first = threading.Thread(target=lambda: out.setdefault("a", sources.run({"j": job}, budget=2)))
    first.start()
    time.sleep(0.05)
    second = sources.run({"j": job}, budget=2)
    first.join()
    assert second["j"].ok and second["j"].value == 7 and out["a"]["j"].ok
    assert len(calls) == 1


def test_over_budget_shows_last_good_answer_as_stale() -> None:
    sources = BudgetedSources(cache_seconds=0, stale_seconds=60)
    assert sources.run({"j": lambda: 5}, budget=1)["j"].value == 5
    result = sources.run({"j": lambda: time.sleep(1) or 6}, budget=0.1)["j"]
    assert result.ok and result.value == 5 and result.stale_seconds is not None and "langsam" in result.error


def test_base_exception_in_source_does_not_break_run() -> None:
    def stop() -> None:
        raise SystemExit(1)

    result = BudgetedSources().run({"x": stop}, budget=1)["x"]
    assert not result.ok and "SystemExit" in result.error


def _snapshot_with(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    state = _live_state(tmp_path, now)
    original = state.snapshot

    def patched():
        data = original()
        change(data, now)
        return data

    original_jobs = lage_module._jobs

    def jobs(s):
        out = original_jobs(s)
        out["snapshot"] = patched
        return out

    monkeypatch.setattr(lage_module, "_jobs", jobs)
    return build_lage(state, now=now, sources=BudgetedSources(cache_seconds=0))


def test_red_server_check_turns_runtime_red(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    state = _live_state(tmp_path, now)
    (tmp_path / "operational" / "server_health.json").write_text(json.dumps({"checked_at": now.isoformat(), "checks": {"disk": {"status": "RED", "reason": "Platte voll"}}}))
    runtime = next(t for t in build_lage(state, now=now, sources=BudgetedSources(cache_seconds=0))["system"] if t["id"] == "runtime")
    assert runtime["state"] == "fail" and "Platte voll" in runtime["reason"]


def test_stale_server_check_is_not_counted(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    state = _live_state(tmp_path, now)
    (tmp_path / "operational" / "server_health.json").write_text(json.dumps({"checked_at": (now - timedelta(days=2)).isoformat(), "checks": {"disk": {"status": "RED"}}}))
    runtime = next(t for t in build_lage(state, now=now, sources=BudgetedSources(cache_seconds=0))["system"] if t["id"] == "runtime")
    assert runtime["state"] == "ok" and "veraltet" in runtime["detail"]


def test_unknown_agent_state_does_not_make_deploy_green(tmp_path: Path) -> None:
    model = build_lage(_live_state(tmp_path, datetime.now(timezone.utc)), sources=BudgetedSources(cache_seconds=0))
    deploy = next(t for t in model["system"] if t["id"] == "deploy")
    assert deploy["state"] == "warn" and "Dashboard-Agent" in deploy["reason"]


def test_ci_without_numbers_shows_dash_not_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def change(data, now):
        data["operations"]["audit"].update({"test_status": "PASS", "passed": None, "failed": "UNAVAILABLE"})

    ci = next(t for t in _snapshot_with(tmp_path, monkeypatch, change)["system"] if t["id"] == "ci")
    assert ci["value"] == "— grün · — rot"
    def change_none(data, now):
        data["operations"]["audit"]["test_status"] = None

    ci = next(t for t in _snapshot_with(tmp_path, monkeypatch, change_none)["system"] if t["id"] == "ci")
    assert ci["state"] == "unknown" and "None" not in ci["value"]


def test_unexpected_data_shape_gives_grey_tiles_not_500(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def change(data, now):
        data["operational_health"]["data_age_seconds"] = float("nan")
        data["operations"] = "kaputt"

    model = _snapshot_with(tmp_path, monkeypatch, change)
    assert {t["id"] for t in model["system"]} >= {"runtime", "ci"}
    for tile in model["system"]:
        if tile["state"] != "ok":
            assert tile["reason"]
