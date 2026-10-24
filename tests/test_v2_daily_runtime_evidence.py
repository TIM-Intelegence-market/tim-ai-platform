from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from src.v2_completion.qualification import build_daily_manifest, stable_hash

UTC = timezone.utc
NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)
SCOPE = "SUPPLIED_SNAPSHOT_NOT_FULL_DAY_PROOF"


def campaign():
    # The hash is computed from the content, so the fixture stays valid once
    # build_daily_manifest checks the campaign hash against its content.
    value = {"campaign_status": "ACTIVE", "start_utc": "2026-10-19T00:00:00Z",
             "software_commit": "b" * 40, "configuration_hash": "c" * 64}
    value["preregistration_hash"] = stable_hash(value)
    return value


def metrics(runtime):
    return {"coverage": 1.0, "gap_count": 0, "case_count": 20, "independent_case_count": 10,
            "runtime_status": runtime, "security_status": {"status": "PASS"}, "incident_ids": []}


@pytest.mark.parametrize("actions", [0, 2, 99])
def test_reported_runtime_count_is_preserved_including_nonzero_actions(actions):
    value = build_daily_manifest(campaign(), day=NOW, metrics=metrics({"mode": "OBSERVE", "trading_actions": actions}))
    assert value["trading_actions"] == actions
    assert value["trading_actions_source"] == "metrics.runtime_status.trading_actions"
    assert value["runtime_evidence_scope"] == SCOPE
    assert value["human_approval"] is False


@pytest.mark.parametrize("runtime", [None, {}, "OK", {"trading_actions": None}, {"trading_actions": -1},
                                     {"trading_actions": False}, {"trading_actions": True},
                                     {"trading_actions": "0"}, {"trading_actions": 0.0}])
def test_absent_or_invalid_counts_remain_unknown_instead_of_zero(runtime):
    data = metrics(runtime)
    before = deepcopy(data)
    value = build_daily_manifest(campaign(), day=NOW, metrics=data)
    assert value["trading_actions"] is None
    assert value["trading_actions_source"] is None
    assert value["runtime_evidence_scope"] == SCOPE
    assert data == before and value["metrics"] == before


def test_snapshot_time_and_mode_are_preserved_without_claiming_daywide_observe_proof():
    runtime = {"mode": "EXECUTE", "trading_actions": 5, "generated_at_utc": "2026-10-20T12:00:00Z"}
    value = build_daily_manifest(campaign(), day=datetime(2026, 10, 19, tzinfo=UTC), metrics=metrics(runtime))
    assert value["utc_date"] == "2026-10-19"
    assert value["metrics"]["runtime_status"] == runtime
    assert value["runtime_evidence_scope"] == SCOPE and value["trading_actions"] == 5
    declared = value.pop("manifest_hash")
    assert stable_hash(value) == declared
    value["trading_actions"] = 0
    assert stable_hash(value) != declared


def test_daily_cli_retains_nonzero_health_evidence_when_writing_a_historical_day(tmp_path, monkeypatch):
    from scripts import v2_qualification_daily as script

    directory = tmp_path / "qualification"
    directory.mkdir()
    (directory / "qualification_campaign.json").write_text(json.dumps(campaign()))
    operational = tmp_path / "data/operational"
    operational.mkdir(parents=True)
    health = {"mode": "OBSERVE", "trading_actions": 7, "generated_at_utc": "2026-10-20T12:00:00Z"}
    (operational / "server_health.json").write_text(json.dumps(health))
    audit = {"coverage": {"dimensions": {"date_partitions": [
        {"utc_date": "2026-10-19", "expected": 1440, "observed": 1440, "missing": 0, "coverage": 1.0}]},
        "product_calculation": {"coverage": 1.0, "missing_observations": 0},
        "audit_agreement": True, "data_manifest_hash": "d" * 64, "database_snapshot": "1:2:"},
        "gaps": [], "cases": {"current_cutoff_audit": {
            "raw_complete_validation_rows": 20, "quality_eligible_labels": 20,
            "strict_independent_30m_windows": 10, "required_independent_cases": 1000}}}

    async def collect_day(*args):
        return audit, {"security": {"status": "PASS"}, "open_gaps": 0}

    monkeypatch.setattr(script, "ROOT", tmp_path)
    monkeypatch.setattr(script, "datetime", SimpleNamespace(now=lambda _: NOW))
    monkeypatch.setattr(script, "collect_day", collect_day)
    assert script.main(["--dir", str(directory)]) == 0
    value = json.loads((directory / "daily/2026-10-19.json").read_text())
    assert value["trading_actions"] == value["metrics"]["runtime_status"]["trading_actions"] == 7
    assert value["runtime_evidence_scope"] == SCOPE
    assert value["metrics"]["runtime_status"]["generated_at_utc"] == "2026-10-20T12:00:00Z"
    assert json.loads((operational / "server_health.json").read_text()) == health
