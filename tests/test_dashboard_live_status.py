"""The dashboard status must follow the live process, not frozen page or file snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.dashboard.layout import AUTO_REFRESH_SCRIPT
from src.dashboard.operations import _evidence_age, build_operations_snapshot


def _snapshot(tmp_path: Path, system_health: dict) -> dict:
    completion = tmp_path / "completion"
    completion.mkdir()
    (completion / "queue_metrics.json").write_text(json.dumps({"queue_depth": 99, "status": "PASS"}))
    base = {"operational_health": {"status": "GREEN"}, "system_health": system_health}
    return build_operations_snapshot(
        base,
        completion_root=completion,
        legacy_root=tmp_path / "legacy",
        live_watchdog_path=tmp_path / "watchdog.json",
        rolling_liveness_path=tmp_path / "rolling.json",
    )


def test_fresh_live_queue_depth_wins_over_persisted_file(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    queue = _snapshot(tmp_path, {"queue_depth": 4, "queue_depth_measured_at": now})["runtime"]["queue_depth"]
    assert queue["value"] == 4
    assert queue["source"] == "/api/state system_health.queue_depth"
    assert queue["status"] == "MEASURED"


def test_stale_live_queue_depth_is_not_shown_as_live(tmp_path: Path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    queue = _snapshot(tmp_path, {"queue_depth": 4, "queue_depth_measured_at": old})["runtime"]["queue_depth"]
    assert queue["value"] == 99
    assert queue["source"].endswith("queue_metrics.json")


def test_unmeasured_live_queue_depth_falls_back_to_file(tmp_path: Path) -> None:
    queue = _snapshot(tmp_path, {"queue_depth": 0})["runtime"]["queue_depth"]
    assert queue["value"] == 99


def test_evidence_age_marks_old_evidence() -> None:
    now = datetime.now(timezone.utc)
    assert _evidence_age((now - timedelta(hours=2)).isoformat()) == "heute"
    assert _evidence_age((now - timedelta(days=3)).isoformat()) == "vor 3 Tagen"
    assert _evidence_age((now - timedelta(days=75)).isoformat()) == "vor 75 Tagen · veraltet"
    assert _evidence_age("UNAVAILABLE") == ""
    assert _evidence_age(None) == ""


def test_page_body_is_refreshed_not_only_header() -> None:
    script = AUTO_REFRESH_SCRIPT
    assert "getElementById('main-content')" in script
    assert "DOMParser" in script
    # The view refresh must work on every page, not only /health and /setup-path.
    assert "location.pathname==='/health'" not in script
    assert "location.reload()" not in script


def test_listener_record_passes_only_for_loopback() -> None:
    from src.operational.live_evidence import listener_record

    now = datetime.now(timezone.utc)
    assert listener_record("localhost", 5433, now)["status"] == "PASS"
    assert listener_record("127.0.0.1, ::1", 5433, now)["status"] == "PASS"
    exposed = listener_record("*", 5432, now)
    assert exposed["status"] == "FAIL" and exposed["exposed_addresses"] == ["*"]


def test_rolling_liveness_record_counts_distinct_minutes_in_window() -> None:
    from src.operational.live_evidence import WINDOW_MINUTES, rolling_liveness_record

    end = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    start = end - timedelta(minutes=WINDOW_MINUTES)
    minutes = [start + timedelta(minutes=i) for i in range(WINDOW_MINUTES)]
    full = rolling_liveness_record(minutes + minutes[:5] + [end], start, end, end)
    assert full["valid_observations"] == WINDOW_MINUTES and full["status"] == "PASS"
    partial = rolling_liveness_record(minutes[:-3], start, end, end)
    assert partial["status"] == "FAIL" and partial["coverage_percent"] == "99.792"


def _rolling_file(tmp_path: Path, computed_at: datetime) -> Path:
    path = tmp_path / "rolling.json"
    path.write_text(json.dumps({"valid_observations": 1397, "expected_observations": 1440, "coverage": 0.97014,
                                "status": "FAIL", "computed_at_utc": computed_at.isoformat()}))
    return path


def _ops(tmp_path: Path, system_health: dict, rolling_path: Path) -> dict:
    completion = tmp_path / "completion"
    completion.mkdir(exist_ok=True)
    return build_operations_snapshot(
        {"operational_health": {"status": "GREEN"}, "system_health": system_health},
        completion_root=completion,
        legacy_root=tmp_path / "legacy",
        live_watchdog_path=tmp_path / "watchdog.json",
        rolling_liveness_path=rolling_path,
    )


def test_old_rolling_liveness_file_is_stale_not_current_fail(tmp_path: Path) -> None:
    from src.dashboard.design_system import severity

    old = _ops(tmp_path, {}, _rolling_file(tmp_path, datetime.now(timezone.utc) - timedelta(days=21)))["datasets"][-1]
    assert old["status"].startswith("STALE — FAIL")
    assert severity(old["status"]) == "warn"
    fresh = _ops(tmp_path, {}, _rolling_file(tmp_path, datetime.now(timezone.utc)))["datasets"][-1]
    assert fresh["status"] == "FAIL"


def test_live_postgres_listener_overrides_old_audit(tmp_path: Path) -> None:
    from src.operational.live_evidence import listener_record

    listener = listener_record("localhost", 5433, datetime.now(timezone.utc))
    security = _ops(tmp_path, {"postgres_listener": listener}, tmp_path / "none.json")["security"]
    assert security["status"] == "PASS"
    assert security["status_source"] == "runtime: SHOW listen_addresses"
    stale = dict(listener, checked_at_utc=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    assert _ops(tmp_path, {"postgres_listener": stale}, tmp_path / "none.json")["security"]["status_source"] != "runtime: SHOW listen_addresses"


def test_attention_rows_show_when_file_evidence_was_measured(tmp_path: Path) -> None:
    from src.dashboard.operations import _attention_rows

    completion = tmp_path / "completion"
    completion.mkdir()
    (completion / "independent_case_audit.json").write_text(json.dumps({
        "captured_at_utc": "2026-08-01T15:59:25Z", "status": "FAIL",
        "qualification": {"strict_independent_cases": 0}, "required_independent_cases": 1000,
    }))
    ops = build_operations_snapshot({"operational_health": {"status": "GREEN"}, "system_health": {}},
                                    completion_root=completion, legacy_root=tmp_path / "legacy",
                                    live_watchdog_path=tmp_path / "w.json", rolling_liveness_path=tmp_path / "r.json")
    rows = "".join(_attention_rows({**ops, "live": {"stream": "GREEN"}}))
    assert "Stand 2026-08-01" in rows


class _FakeConnection:
    def __init__(self, listen_error: bool = False) -> None:
        self.listen_error = listen_error

    async def fetch(self, query, symbol, start, end):
        return [{"open_time": start + timedelta(minutes=i)} for i in range(1440)]

    async def fetchval(self, query):
        if self.listen_error:
            raise PermissionError("not allowed")
        return "localhost" if "listen" in query else 5433


class _FakeDatabase:
    def __init__(self, connection) -> None:
        self.connection = connection

    def acquire(self):
        import contextlib

        @contextlib.asynccontextmanager
        async def cm():
            yield self.connection
        return cm()


def _app(tmp_path: Path, connection):
    import threading
    from types import SimpleNamespace

    from main import TIMApplication

    state = SimpleNamespace(rolling_liveness_path=tmp_path / "rolling.json", lock=threading.Lock(), system_health={})
    return TIMApplication, SimpleNamespace(database=_FakeDatabase(connection), dashboard_state=state)


def test_runtime_writes_rolling_room_and_listener(tmp_path: Path) -> None:
    import asyncio

    cls, app = _app(tmp_path, _FakeConnection())
    asyncio.run(cls._refresh_live_evidence(app))
    written = json.loads((tmp_path / "rolling.json").read_text())
    assert written["status"] == "PASS" and written["valid_observations"] == 1440
    assert app.dashboard_state.system_health["postgres_listener"]["status"] == "PASS"


def test_listener_failure_does_not_block_rolling_room(tmp_path: Path) -> None:
    import asyncio

    cls, app = _app(tmp_path, _FakeConnection(listen_error=True))
    asyncio.run(cls._refresh_live_evidence(app))
    assert (tmp_path / "rolling.json").exists()
    assert "postgres_listener" not in app.dashboard_state.system_health
