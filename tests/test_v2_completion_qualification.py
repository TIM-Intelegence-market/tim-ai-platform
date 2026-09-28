from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.v2_completion.qualification import (
    REQUIRED_START_GATES,
    StartGate,
    activate_campaign,
    build_daily_manifest,
    build_preregistration,
    campaign_duration,
)


UTC = timezone.utc


def gates(status: str = "PASS") -> list[StartGate]:
    return [StartGate(name, status, f"evidence/{name}.json") for name in REQUIRED_START_GATES]


def prereg(status: str = "PASS") -> dict:
    return build_preregistration(
        gates=gates(status),
        software_commit="a" * 40,
        configuration_hash="b" * 64,
        current_independent_cases=300,
        observed_minutes=14400,
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_duration_never_undercuts_1000_non_overlapping_windows() -> None:
    value = campaign_duration(current_independent_cases=1000, observed_minutes=1000)
    assert value["pre_registered_minimum_minutes"] >= 1000 * 30


def test_campaign_is_locked_when_any_gate_fails() -> None:
    values = gates()
    values[0] = StartGate(values[0].name, "FAIL", "listener wildcard")
    value = build_preregistration(
        gates=values,
        software_commit="a" * 40,
        configuration_hash="b" * 64,
        current_independent_cases=300,
        observed_minutes=14400,
    )
    assert value["campaign_status"] == "NOT_STARTED_START_GATE_BLOCKED"
    assert value["start_utc"] is None
    with pytest.raises(RuntimeError, match="cannot start"):
        activate_campaign(value, start=datetime.now(UTC), actual_commit="a" * 40)


def test_activation_is_explicit_and_commit_bound() -> None:
    value = prereg()
    with pytest.raises(RuntimeError, match="differs"):
        activate_campaign(value, start=datetime.now(UTC), actual_commit="c" * 40)
    active = activate_campaign(
        value,
        start=datetime(2026, 8, 2, tzinfo=UTC),
        actual_commit="a" * 40,
    )
    assert active["campaign_status"] == "ACTIVE"
    assert active["expected_end_utc"] > active["start_utc"]


def test_daily_manifest_rejects_inactive_or_incomplete_metrics() -> None:
    value = prereg()
    with pytest.raises(RuntimeError, match="active campaign"):
        build_daily_manifest(value, day=datetime.now(UTC), metrics={})
    active = activate_campaign(
        value, start=datetime.now(UTC), actual_commit="a" * 40
    )
    with pytest.raises(ValueError, match="daily metrics missing"):
        build_daily_manifest(active, day=datetime.now(UTC), metrics={})
