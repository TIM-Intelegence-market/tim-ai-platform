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


def test_immutable_manifest_preserves_existing_evidence(tmp_path) -> None:
    from src.v2_completion.qualification import write_immutable_json

    path = tmp_path / "daily" / "2026-10-20.json"
    assert write_immutable_json(path, {"coverage": 0.95}) == "CREATED"
    original = path.read_bytes()
    assert write_immutable_json(path, {"coverage": 0.95}) == "UNCHANGED"
    with pytest.raises(FileExistsError, match="different content"):
        write_immutable_json(path, {"coverage": 1.0})
    assert path.read_bytes() == original


@pytest.mark.parametrize("same_payload", [False, True])
def test_parallel_manifest_publication_never_overwrites_the_winner(tmp_path, monkeypatch, same_payload) -> None:
    from concurrent.futures import ThreadPoolExecutor
    import json
    from threading import Barrier
    from src.v2_completion import qualification

    path = tmp_path / "daily" / "2026-10-20.json"
    barrier = Barrier(2)
    original_link = qualification.os.link

    def competing_link(source, target):
        # Both writers have finished their private files before either publishes.
        barrier.wait(timeout=5)
        return original_link(source, target)

    monkeypatch.setattr(qualification.os, "link", competing_link)
    payloads = [{"writer": 1}, {"writer": 1 if same_payload else 2}]

    def publish(payload):
        try:
            return qualification.write_immutable_json(path, payload), payload
        except FileExistsError:
            return "CONFLICT", payload

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish, payload) for payload in payloads]
        results = [future.result(timeout=10) for future in futures]
    assert sorted(status for status, _ in results) == sorted(
        ["CREATED", "UNCHANGED" if same_payload else "CONFLICT"]
    )
    winner = next(payload for status, payload in results if status == "CREATED")
    assert json.loads(path.read_text()) == winner
    assert list(path.parent.iterdir()) == [path]


def test_failed_manifest_publication_leaves_no_partial_evidence(tmp_path, monkeypatch) -> None:
    from src.v2_completion import qualification

    path = tmp_path / "daily" / "2026-10-20.json"

    def unavailable_link(source, target):
        raise OSError("publication unavailable")

    monkeypatch.setattr(qualification.os, "link", unavailable_link)
    with pytest.raises(OSError, match="publication unavailable"):
        qualification.write_immutable_json(path, {"coverage": 0.95})
    assert not path.exists()
    assert list(path.parent.iterdir()) == []


def test_new_manifest_retains_normal_file_creation_permissions(tmp_path) -> None:
    import stat
    from src.v2_completion.qualification import write_immutable_json

    reference = tmp_path / "normal-file.json"
    reference.write_text("{}")
    manifest = tmp_path / "manifest.json"
    assert write_immutable_json(manifest, {"coverage": 0.95}) == "CREATED"
    assert stat.S_IMODE(manifest.stat().st_mode) == stat.S_IMODE(reference.stat().st_mode)
