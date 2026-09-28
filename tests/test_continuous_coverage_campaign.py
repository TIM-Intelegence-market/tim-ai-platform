from datetime import datetime, timedelta, timezone

import json

from scripts.continuous_coverage_campaign import evaluated_end, missing_minutes, power_telemetry_status


UTC = timezone.utc
START = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)


def test_current_minute_is_not_counted_before_it_can_close() -> None:
    assert evaluated_end(START, START + timedelta(days=30), START + timedelta(minutes=4, seconds=40)) == START + timedelta(minutes=3)


def test_missing_minutes_has_no_exclusions_or_forward_fill() -> None:
    end = START + timedelta(minutes=3)
    assert missing_minutes(START, end, {START, START + timedelta(minutes=2)}) == ["2026-09-23T10:01:00Z"]


def test_power_telemetry_must_be_fresh_and_passing(tmp_path) -> None:
    path = tmp_path / "power.json"
    path.write_text(json.dumps({"status": "PASS", "observed_at_utc": "2026-09-23T10:00:00Z"}))
    assert power_telemetry_status(path, START + timedelta(seconds=179))["status"] == "PASS"
    assert power_telemetry_status(path, START + timedelta(seconds=181)) == {
        "status": "FAIL", "reason": "STALE", "age_seconds": 181.0
    }
