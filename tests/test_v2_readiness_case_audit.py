from datetime import datetime, timedelta, timezone

from src.v2_readiness.case_audit import ValidatedCaseRecord, audit_validated_cases


UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def record(
    index: int,
    *,
    minute: int | None = None,
    horizons: tuple[int, ...] = (5, 15, 30),
    source_gap: bool = False,
) -> ValidatedCaseRecord:
    observed = BASE + timedelta(minutes=index if minute is None else minute)
    return ValidatedCaseRecord(
        observation_id=f"obs-{index}",
        observed_at=observed,
        validated_through=observed + timedelta(minutes=30),
        kind="RISING_CVD_ACTIVITY",
        outcome="PRICE_INCREASED",
        input_hash=f"{index:064x}",
        horizon_minutes=horizons,
        source_gap_overlap=source_gap,
        case_present=True,
        case_closed=True,
        case_outcome_matches=True,
        provenance_complete=True,
    )


def test_case_gate_counts_strict_non_overlapping_quality_windows() -> None:
    result = audit_validated_cases(
        [record(0), record(1), record(2), record(30), record(60)],
        required_independent_cases=3,
    )
    assert result["raw_complete_validation_rows"] == 5
    assert result["strict_independent_30m_windows"] == 3
    assert result["gate_status"] == "PASS"


def test_same_timestamp_labels_are_not_independent_cases() -> None:
    result = audit_validated_cases(
        [record(1, minute=0), record(2, minute=0), record(3, minute=30)],
        required_independent_cases=3,
    )
    assert result["unique_observation_ids"] == 3
    assert result["unique_underlying_observation_times"] == 2
    assert result["strict_independent_30m_windows"] == 2
    assert result["gate_status"] == "FAIL"


def test_missing_horizon_or_source_gap_fails_quality_screen() -> None:
    result = audit_validated_cases(
        [record(1, horizons=(5, 30)), record(2, minute=30, source_gap=True)],
        required_independent_cases=1,
    )
    assert result["horizon_incomplete"] == 1
    assert result["source_gap_overlap"] == 1
    assert result["quality_eligible_labels"] == 0
    assert result["gate_status"] == "FAIL"


def test_duplicate_observation_id_is_detected() -> None:
    item = record(1)
    result = audit_validated_cases([item, item], required_independent_cases=1)
    assert result["duplicate_observation_id_count"] == 1
    assert result["gate_status"] == "FAIL"


def test_readiness_report_keeps_count_pass_separate_from_scientific_fail() -> None:
    from scripts.v2_readiness_audit import build_case_payload

    records = [record(index, minute=index * 30) for index in range(1917)]
    result = build_case_payload(records, cutoff=BASE + timedelta(days=40), generated_at="2026-10-20T00:00:00Z")
    assert result["case_count_gate_status"] == "PASS"
    assert "current evidence: 1917/1000" in result["gate_reason"]
    assert "current_independent_windows_below_target" not in result["gate_reasons"]
    assert result["gate_status"] == "FAIL"
    assert "negative_and_neutral_controls_absent" in result["gate_reasons"]
    assert "reviewer_evidence_absent" in result["gate_reasons"]
    assert "inter_rater_evidence_absent" in result["gate_reasons"]
    assert result["qualification_counted"] is False
    assert result["v2_approved"] is False


def test_readiness_report_explains_low_counts_and_duplicate_ids_separately() -> None:
    from scripts.v2_readiness_audit import build_case_payload

    item = record(1)
    result = build_case_payload([item, item], cutoff=BASE + timedelta(days=1), generated_at="2026-10-20T00:00:00Z")
    assert "current evidence: 1/1000" in result["gate_reason"]
    assert result["gate_reasons"][:2] == [
        "current_independent_windows_below_target", "current_duplicate_observation_ids"
    ]
    assert result["case_count_gate_status"] == "FAIL"


def test_duplicate_ids_still_block_when_count_target_is_reached() -> None:
    from scripts.v2_readiness_audit import build_case_payload

    records = [record(index, minute=index * 30) for index in range(1000)]
    result = build_case_payload(records + [records[0]], cutoff=BASE + timedelta(days=40),
                                generated_at="2026-10-20T00:00:00Z")
    assert result["current_cutoff_audit"]["statistical_independence_status"] == "PASS"
    assert "current_independent_windows_below_target" not in result["gate_reasons"]
    assert "current_duplicate_observation_ids" in result["gate_reasons"]
    assert result["case_count_gate_status"] == "FAIL"


def test_frozen_and_current_counts_are_reported_independently() -> None:
    from dataclasses import replace
    from scripts.v2_readiness_audit import FROZEN_CASE_CUTOFF, build_case_payload

    frozen = replace(record(0), observed_at=FROZEN_CASE_CUTOFF - timedelta(minutes=30),
                     validated_through=FROZEN_CASE_CUTOFF)
    current = replace(record(1), observed_at=FROZEN_CASE_CUTOFF + timedelta(minutes=30),
                      validated_through=FROZEN_CASE_CUTOFF + timedelta(minutes=60))
    result = build_case_payload([frozen, current], cutoff=FROZEN_CASE_CUTOFF + timedelta(days=1),
                                generated_at="2026-10-20T00:00:00Z")
    assert "Frozen evidence: 1/1000" in result["gate_reason"]
    assert "current evidence: 2/1000" in result["gate_reason"]
    assert result["case_window_start_utc"] is None


def test_empty_explicit_case_window_is_not_qualified_and_hash_is_valid() -> None:
    import hashlib
    from scripts.v2_readiness_audit import build_case_payload, compact_json

    result = build_case_payload([], cutoff=BASE + timedelta(days=1), generated_at="2026-10-20T00:00:00Z",
                                case_from=BASE)
    assert result["case_window_start_utc"] == "2026-01-01T00:00:00Z"
    assert "current evidence: 0/1000" in result["gate_reason"]
    assert result["gate_status"] == "FAIL"
    assert result["qualification_counted"] is False
    artifact_hash = result.pop("artifact_hash")
    assert artifact_hash == hashlib.sha256(compact_json(result)).hexdigest()


def test_readiness_cli_exposes_scientific_fail_alongside_count_pass(monkeypatch, capsys) -> None:
    import asyncio
    import json
    import sys
    from scripts import v2_readiness_audit as script

    from types import SimpleNamespace

    monkeypatch.setattr(script, "settings", SimpleNamespace(database_url="postgresql://unused/test"))
    cases = script.build_case_payload(
        [record(index, minute=index * 30) for index in range(1000)],
        cutoff=BASE + timedelta(days=40), generated_at="2026-10-20T00:00:00Z",
    )

    async def fake_collect(args):
        assert args.no_write is True
        return {"cases": cases, "gaps": [],
                "coverage": {"product_calculation": {"coverage": 1.0}, "audit_agreement": True}}

    monkeypatch.setattr(script, "collect", fake_collect)
    monkeypatch.setattr(sys, "argv", ["v2_readiness_audit.py", "--start", "2026-01-01T00:00:00Z",
                                      "--end", "2026-01-02T00:00:00Z", "--no-write"])
    assert asyncio.run(script.main()) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["current_case_gate"] == "PASS"
    assert summary["scientific_case_gate"] == "FAIL"
    assert summary["scientific_case_gate_reasons"]
    assert summary["qualification_counted"] is False
    assert summary["v2_approved"] is False
