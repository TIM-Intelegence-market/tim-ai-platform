"""scripts/tim_server_health.py: thresholds of task package P6, worst check wins."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import tim_server_health as health
from tests.test_tim_db_backup import make_dump

UTC = timezone.utc
NOW = datetime(2026, 10, 5, 12, 30, 20, tzinfo=UTC)


@pytest.mark.parametrize(
    ("output", "status"),
    [
        ("ActiveState=active\nSubState=running\n", "GREEN"),
        ("ActiveState=activating\nSubState=auto-restart\n", "AMBER"),
        ("ActiveState=failed\nSubState=failed\n", "RED"),
        (None, "RED"),
    ],
)
def test_runtime_check(output, status) -> None:
    assert health.runtime_check(output)["status"] == status


def test_candle_freshness_counts_from_candle_close() -> None:
    assert health.candle_freshness_check(NOW - timedelta(seconds=200), NOW)["status"] == "GREEN"
    assert health.candle_freshness_check(NOW - timedelta(seconds=241), NOW)["status"] == "RED"
    assert health.candle_freshness_check(None, NOW)["status"] == "RED"


def test_gap_check_ignores_the_settling_minutes_and_reports_missing_ones() -> None:
    start, end = health.gap_window(NOW)
    assert end == datetime(2026, 10, 5, 12, 28, tzinfo=UTC) and end - start == timedelta(minutes=60)
    every = {start + timedelta(minutes=offset) for offset in range(60)}
    assert health.gap_check(every, start, end)["status"] == "GREEN"
    missing = every - {start + timedelta(minutes=7)}
    result = health.gap_check(missing, start, end)
    assert result["status"] == "RED" and result["missing"] == 1
    assert result["first_missing"] == [(start + timedelta(minutes=7)).isoformat()]


def test_disk_thresholds(monkeypatch) -> None:
    class Usage:
        def __init__(self, used):
            self.total, self.used, self.free = 100, used, 100 - used

    for used, status in ((50, "GREEN"), (85, "AMBER"), (95, "RED")):
        monkeypatch.setattr(health.shutil, "disk_usage", lambda path, used=used: Usage(used))
        assert health.disk_check(Path("/")) ["status"] == status


def test_time_sync_check() -> None:
    assert health.time_sync_check("yes\n")["status"] == "GREEN"
    assert health.time_sync_check("no\n")["status"] == "RED"
    assert health.time_sync_check(None)["status"] == "RED"


def test_backup_check_age(tmp_path: Path) -> None:
    assert health.backup_check(tmp_path, NOW)["status"] == "RED"
    make_dump(tmp_path, NOW - timedelta(hours=30))
    assert health.backup_check(tmp_path, NOW)["status"] == "RED"
    make_dump(tmp_path, NOW - timedelta(hours=2))
    assert health.backup_check(tmp_path, NOW)["status"] == "GREEN"


def test_overall_is_the_worst_check() -> None:
    assert health.overall({"a": {"status": "GREEN"}, "b": {"status": "AMBER"}}) == "AMBER"
    assert health.overall({"a": {"status": "RED"}, "b": {"status": "AMBER"}}) == "RED"
    assert health.overall({}) == "RED"


def test_unreachable_database_is_red_not_a_crash(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TIM_DATABASE_SECRET_PROVIDER", "file")
    monkeypatch.setenv("TIM_DATABASE_SECRET_FILE", str(tmp_path / "missing"))
    monkeypatch.setattr(health, "command_output", lambda command: None)
    report = health.collect(tmp_path, tmp_path)
    assert report["status"] == "RED"
    assert report["checks"]["candle_freshness"]["reason"].startswith("database unavailable")
    assert report["trading_actions"] == 0


def test_backup_check_reports_unreadable_directory(monkeypatch, tmp_path) -> None:
    from scripts import tim_db_backup

    def denied(directory):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(tim_db_backup, "dumps", denied)
    result = health.backup_check(tmp_path, health.datetime.now(health.UTC))
    assert result["status"] == "RED" and "unreadable" in result["reason"]
