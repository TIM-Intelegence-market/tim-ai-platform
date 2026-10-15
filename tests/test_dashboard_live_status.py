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
