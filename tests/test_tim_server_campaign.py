"""scripts/tim_server_campaign.py: declarations are prospective, coverage is counted per minute."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts import tim_server_campaign as campaign

UTC = timezone.utc
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
START = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)


def declaration(**overrides):
    values = dict(start=START, days=14, target_percent=99.5, host_id="tim-debian-01", symbol="BTCUSDT",
                  commit="a" * 40, now=NOW)
    values.update(overrides)
    return campaign.build_declaration(**values)


def test_declaration_fixes_window_and_target() -> None:
    result = declaration()
    assert result["window_start"] == "2026-10-05T00:00:00Z"
    assert result["window_end"] == "2026-10-19T00:00:00Z"
    assert result["expected_minutes"] == 14 * 1440
    assert result["target_coverage_percent"] == 99.5 and result["trading_actions"] == 0
    assert campaign.declaration_path(result).name == "debian_campaign_20261005T0000Z.json"


@pytest.mark.parametrize(
    "overrides",
    [{"start": NOW + timedelta(minutes=30)}, {"start": NOW - timedelta(days=1)}, {"days": 0}, {"days": 91},
     {"target_percent": 80.0}, {"host_id": "  "}],
)
def test_declaration_rejects_retroactive_or_invalid_windows(overrides) -> None:
    with pytest.raises(campaign.CampaignError):
        declaration(**overrides)


@pytest.mark.parametrize("value", ["2026-10-05T00:00", "2026-10-05T00:00:30Z", "nonsense"])
def test_window_boundaries_are_whole_utc_minutes(value) -> None:
    with pytest.raises(campaign.CampaignError):
        campaign.parse_minute(value)


def test_coverage_counts_minutes_and_groups_gaps() -> None:
    result = declaration(days=1)
    every = {START + timedelta(minutes=offset) for offset in range(1440)}
    gap = {START + timedelta(minutes=offset) for offset in (100, 101, 102, 500)}
    report = campaign.coverage(result, every - gap, START + timedelta(days=2))
    assert report["status"] == "PASS"
    assert report["missing_minutes"] == 4 and report["coverage_percent"] == round(100 * 1436 / 1440, 4)
    assert report["missing_ranges"][0] == {"first": "2026-10-05T01:40:00Z", "last": "2026-10-05T01:42:00Z", "minutes": 3}
    worse = campaign.coverage(result, set(list(sorted(every))[:1400]), START + timedelta(days=2))
    assert worse["status"] == "FAIL"


def test_coverage_before_and_during_window() -> None:
    result = declaration(days=1)
    assert campaign.coverage(result, set(), START - timedelta(hours=1))["status"] == "NOT_STARTED"
    running = campaign.coverage(result, {START}, START + timedelta(minutes=10, seconds=30))
    assert running["status"] == "RUNNING" and running["expected_minutes"] == 10
