"""Daily evidence must reference the content of the loaded campaign."""
from __future__ import annotations

import copy
import json
from datetime import UTC, datetime

import pytest

from src.v2_completion.qualification import (
    REQUIRED_START_GATES,
    StartGate,
    activate_campaign,
    build_daily_manifest,
    build_preregistration,
)


def active_campaign():
    prereg = build_preregistration(
        gates=[StartGate(name, "PASS", "test-evidence") for name in REQUIRED_START_GATES],
        software_commit="a" * 40, configuration_hash="b" * 64,
        current_independent_cases=300, observed_minutes=14400,
    )
    # The real start command adds these before activation, whose final hash binds them.
    prereg["start_approval"] = {"approved_by": "test-owner", "decision_ref": "test-only"}
    prereg["start_gate_report_sha256"] = "c" * 64
    return activate_campaign(prereg, start=datetime(2026, 10, 1, tzinfo=UTC), actual_commit="a" * 40)


def metrics():
    return {"coverage": 0.95, "gap_count": 0, "case_count": 0,
            "independent_case_count": 0, "runtime_status": {"trading_actions": 0},
            "security_status": "PASS", "incident_ids": []}


def test_valid_activated_campaign_roundtrips_without_mutation():
    campaign = json.loads(json.dumps(active_campaign()))
    original = copy.deepcopy(campaign)
    manifest = build_daily_manifest(campaign, day=datetime(2026, 10, 2, tzinfo=UTC), metrics=metrics())
    assert manifest["preregistration_hash"] == campaign["preregistration_hash"]
    assert campaign == original


@pytest.mark.parametrize("field,value", [
    ("configuration_hash", "d" * 64),
    ("software_commit", "e" * 40),
    ("start_utc", "2026-09-01T00:00:00Z"),
    ("coverage_target", 0.01),
    ("start_approval", {"approved_by": "changed"}),
])
def test_daily_manifest_rejects_changed_campaign(field, value):
    campaign = active_campaign()
    campaign[field] = value
    with pytest.raises(ValueError, match="campaign.*hash"):
        build_daily_manifest(campaign, day=datetime(2026, 10, 2, tzinfo=UTC), metrics=metrics())


@pytest.mark.parametrize("stored", [None, "", "f" * 64, 123, True])
def test_daily_manifest_rejects_missing_or_wrong_campaign_hash(stored):
    campaign = active_campaign()
    if stored is None:
        del campaign["preregistration_hash"]
    else:
        campaign["preregistration_hash"] = stored
    with pytest.raises(ValueError, match="campaign.*hash"):
        build_daily_manifest(campaign, day=datetime(2026, 10, 2, tzinfo=UTC), metrics=metrics())


def test_daily_collector_rejects_changed_campaign_before_collection(tmp_path, monkeypatch):
    from scripts import v2_qualification_daily as daily

    campaign = active_campaign()
    campaign["duration"]["pre_registered_minimum_minutes"] = 1
    source = tmp_path / "qualification_campaign.json"
    source.write_text(json.dumps(campaign))
    before = source.read_bytes()

    async def forbidden(*args, **kwargs):
        pytest.fail("database collection must not run for an inconsistent campaign")

    monkeypatch.setattr(daily, "collect_day", forbidden)
    with pytest.raises(ValueError, match="campaign.*hash"):
        daily.main(["--dir", str(tmp_path)])
    assert source.read_bytes() == before
    assert not (tmp_path / "daily").exists()


def test_daily_collector_no_campaign_still_exits_normally(tmp_path, capsys):
    from scripts import v2_qualification_daily as daily

    assert daily.main(["--dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_ACTIVE"
