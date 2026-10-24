"""Campaign start refuses anything but fresh, all-PASS evidence for HEAD; daily days are complete and new."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import hashlib
import json

import pytest

from src.v2_completion import campaign
from src.v2_completion.qualification import (
    REQUIRED_START_GATES,
    activate_campaign,
    build_daily_manifest,
    build_preregistration,
)

HEAD = "a" * 40
NOW = datetime(2026, 10, 20, 13, 30, 20, tzinfo=UTC)


def seal_report(value):
    payload = {key: item for key, item in value.items() if key != "report_sha256"}
    value["report_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return value


def report(**overrides):
    gates = [{"name": name, "status": "PASS", "evidence": {}, "reasons": []} for name in REQUIRED_START_GATES]
    gates[-1]["evidence"] = {"frozen_commit": HEAD}
    value = {"kind": campaign.START_GATE_KIND, "evaluated_at_utc": "2026-10-20T13:25:00+00:00",
             "context": {"head": HEAD}, "all_start_gates_pass": True, "blocking_start_gates": [],
             "gates": gates, "report_sha256": "f" * 64}
    value.update(overrides)
    return seal_report(value)


def test_gates_from_report_accepts_only_fresh_all_pass_for_head() -> None:
    gates = campaign.gates_from_report(report(), report_ref="r.json", head=HEAD, now=NOW)
    assert [gate.name for gate in gates] == list(REQUIRED_START_GATES)
    assert all(gate.status == "PASS" and "sha256=" in gate.evidence for gate in gates)
    with pytest.raises(ValueError, match="fresh"):
        campaign.gates_from_report(report(), report_ref="r", head=HEAD, now=NOW + timedelta(hours=1))
    with pytest.raises(ValueError, match="different commit"):
        campaign.gates_from_report(report(), report_ref="r", head="b" * 40, now=NOW)
    with pytest.raises(ValueError, match="do not all pass"):
        campaign.gates_from_report(report(all_start_gates_pass=False, blocking_start_gates=["watchdog"]),
                                   report_ref="r", head=HEAD, now=NOW)
    with pytest.raises(ValueError, match="kind|start-gate evaluation"):
        campaign.gates_from_report(report(kind="OTHER"), report_ref="r", head=HEAD, now=NOW)
    broken = report()
    broken["gates"][-1]["evidence"] = {"frozen_commit": "c" * 40}
    with pytest.raises(ValueError, match="frozen commit"):
        campaign.gates_from_report(seal_report(broken), report_ref="r", head=HEAD, now=NOW)


def test_activation_is_prospective_and_34_days() -> None:
    gates = campaign.gates_from_report(report(), report_ref="r", head=HEAD, now=NOW)
    prereg = build_preregistration(gates=gates, software_commit=HEAD, configuration_hash="c",
                                   current_independent_cases=298, observed_minutes=14447, generated_at=NOW)
    start = campaign.campaign_start_minute(NOW)
    assert start == datetime(2026, 10, 20, 13, 31, tzinfo=UTC) and start > NOW
    active = activate_campaign(prereg, start=start, actual_commit=HEAD)
    assert active["campaign_status"] == "ACTIVE" and active["duration"]["pre_registered_minimum_days"] == 34
    assert active["expected_end_utc"] == "2026-11-23T13:31:00Z"
    assert active["trading_approved"] is False and active["readiness_counted"] is False


def test_pending_days_only_complete_unwritten_days() -> None:
    start = datetime(2026, 10, 20, 13, 31, tzinfo=UTC)
    assert campaign.pending_days(start, datetime(2026, 10, 21, 0, 3, tzinfo=UTC), set()) == []
    later = datetime(2026, 10, 23, 0, 30, tzinfo=UTC)
    assert campaign.pending_days(start, later, set()) == [date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)]
    assert campaign.pending_days(start, later, {"2026-10-20"}) == [date(2026, 10, 21), date(2026, 10, 22)]
    assert campaign.day_window(start, date(2026, 10, 20)) == (start, datetime(2026, 10, 21, tzinfo=UTC))
    assert campaign.day_window(start, date(2026, 10, 21))[0] == datetime(2026, 10, 21, tzinfo=UTC)


def test_daily_metrics_feed_the_manifest() -> None:
    day = date(2026, 10, 21)
    window = (datetime(2026, 10, 21, tzinfo=UTC), datetime(2026, 10, 22, tzinfo=UTC))
    coverage = {
        "dimensions": {"date_partitions": [
            {"utc_date": "2026-10-20", "expected": 629, "observed": 629, "missing": 0, "coverage": 1.0},
            {"utc_date": "2026-10-21", "expected": 1440, "observed": 1438, "missing": 2, "coverage": 0.998611}]},
        "product_calculation": {"coverage": 0.99903, "missing_observations": 2},
        "audit_agreement": True, "data_manifest_hash": "d" * 64, "database_snapshot": "1:2:",
    }
    gaps = [{"gap_id": "gap_old", "start_utc": "2026-10-20T14:00:00Z", "end_utc": "2026-10-20T14:01:00Z"},
            {"gap_id": "gap_new", "start_utc": "2026-10-21T05:00:00Z", "end_utc": "2026-10-21T05:02:00Z"}]
    cases = {"raw_complete_validation_rows": 40, "quality_eligible_labels": 30,
             "strict_independent_30m_windows": 25, "required_independent_cases": 1000}
    metrics = campaign.daily_metrics(day=day, window=window, coverage=coverage, gaps=gaps, cases=cases,
                                     health={"mode": "OBSERVE", "trading_actions": 0, "status": "PASS"},
                                     security={"status": "PASS"}, open_gap_incidents=0)
    assert metrics["coverage"] == 0.998611 and metrics["gap_count"] == 1 and metrics["incident_ids"] == ["gap_new"]
    assert metrics["independent_case_count"] == 25 and metrics["runtime_status"]["mode"] == "OBSERVE"
    gates = campaign.gates_from_report(report(), report_ref="r", head=HEAD, now=NOW)
    prereg = build_preregistration(gates=gates, software_commit=HEAD, configuration_hash="c",
                                   current_independent_cases=298, observed_minutes=14447, generated_at=NOW)
    active = activate_campaign(prereg, start=campaign.campaign_start_minute(NOW), actual_commit=HEAD)
    manifest = build_daily_manifest(active, day=window[0], metrics=metrics)
    assert manifest["utc_date"] == "2026-10-21" and manifest["trading_actions"] == 0
    with pytest.raises(ValueError, match="no partition"):
        campaign.daily_metrics(day=date(2026, 10, 25), window=window, coverage=coverage, gaps=gaps, cases=cases,
                               health=None, security={}, open_gap_incidents=None)


def test_start_script_requires_named_approval() -> None:
    from scripts.v2_qualification_start import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--start-gates", "x.json", "--approved-by", " ", "--decision-ref", "d", "--approved-at",
                    "2026-10-20T12:59:10Z"])
    with pytest.raises(SystemExit):
        parse_args(["--start-gates", "x.json", "--approved-by", "Uzi", "--decision-ref", "d", "--approved-at",
                    "2026-10-20T12:59:10"])
    assert parse_args(["--start-gates", "x.json", "--approved-by", "Uzi", "--decision-ref", "d",
                       "--approved-at", "2026-10-20T12:59:10Z"]).approved_by == "Uzi"


def test_start_rejects_changed_report_even_when_gate_decisions_still_look_green():
    value = report()
    value["gates"][0]["evidence"] = {"changed_after_evaluation": True}
    with pytest.raises(ValueError, match="hash"):
        campaign.gates_from_report(value, report_ref="r", head=HEAD, now=NOW)


@pytest.mark.parametrize("declared", [None, "", "f" * 64])
def test_start_requires_matching_report_hash(declared):
    value = report()
    value["report_sha256"] = declared
    with pytest.raises(ValueError, match="hash"):
        campaign.gates_from_report(value, report_ref="r", head=HEAD, now=NOW)


def test_duplicate_gate_cannot_replace_an_earlier_failure():
    value = report()
    duplicate = dict(value["gates"][0])
    value["gates"][0]["status"] = "FAIL"
    value["gates"].append(duplicate)
    with pytest.raises(ValueError, match="exactly once"):
        campaign.gates_from_report(seal_report(value), report_ref="r", head=HEAD, now=NOW)


def test_each_gate_must_pass_despite_a_green_summary():
    value = report()
    value["gates"][0]["status"] = "FAIL"
    with pytest.raises(ValueError, match="do not all pass"):
        campaign.gates_from_report(seal_report(value), report_ref="r", head=HEAD, now=NOW)


@pytest.mark.parametrize("overrides", [{"all_start_gates_pass": "true"}, {"blocking_start_gates": None}])
def test_summary_must_be_explicitly_true_with_an_empty_blocker_list(overrides):
    with pytest.raises(ValueError, match="do not all pass"):
        campaign.gates_from_report(report(**overrides), report_ref="r", head=HEAD, now=NOW)


def test_real_collector_report_remains_compatible_and_can_supply_start_gates():
    from src.v2_completion.start_gate_checks import GateResult, summarize

    rows = [GateResult(name, "PASS", {"frozen_commit": HEAD} if name == "configuration_and_commit_frozen" else {})
            for name in REQUIRED_START_GATES]
    value = summarize(rows, now=NOW, context={"head": HEAD})
    # Captured from the producer before the integrity fix: no report format/hash migration.
    assert value["report_sha256"] == "fcf4d528b62f88f1c8c3d6acbf872f5fc33fbfbaed8d51041d3c2d268f97276d"
    gates = campaign.gates_from_report(value, report_ref="r", head=HEAD, now=NOW)
    assert len(gates) == len(REQUIRED_START_GATES) and all(gate.status == "PASS" for gate in gates)


def test_invalid_report_stops_start_script_before_any_campaign_files_are_written(tmp_path, monkeypatch):
    from scripts import v2_qualification_start as script

    value = report(evaluated_at_utc=datetime.now(UTC).isoformat())
    value["gates"][0]["evidence"] = {"changed_after_evaluation": True}
    path = tmp_path / "start-gates.json"
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    output = tmp_path / "qualification"
    monkeypatch.setattr(script, "git", lambda *args: HEAD if args == ("rev-parse", "HEAD") else "")
    with pytest.raises(ValueError, match="hash"):
        script.main(["--start-gates", str(path), "--approved-by", "Test reviewer",
                     "--decision-ref", "TEST_ONLY", "--approved-at", "2026-10-20T13:00:00Z",
                     "--output-dir", str(output), "--baseline", str(tmp_path / "absent-baseline.json")])
    assert not output.exists()
    assert path.read_bytes() == raw


@pytest.mark.parametrize("rows", [None, {}, [None], [{"name": 123}], []])
def test_malformed_gate_collections_are_rejected_as_invalid_reports(rows):
    with pytest.raises(ValueError, match="exactly once"):
        campaign.gates_from_report(report(gates=rows), report_ref="r", head=HEAD, now=NOW)
