from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.collection_reporting import CollectionReportBuilder, CollectionReportError


def facts() -> dict:
    return {
        "collection_id": "btc-first-20260904",
        "started_at": "2026-09-04T10:00:00+00:00",
        "ended_at": "2026-09-04T11:00:00+00:00",
        "mode": "OBSERVE",
        "live_trading": False,
        "trading_actions": 0,
        "data_source": "BINANCE_PUBLIC",
        "symbol": "BTCUSDT",
        "expected_period": {"start": "2026-09-04T10:00:00Z", "end": "2026-09-04T11:00:00Z"},
        "actual_period": {"start": "2026-09-04T10:00:00Z", "end": "2026-09-04T11:00:00Z"},
        "code_version": "abc123",
        "config_version": "1",
        "counts": {"events_received": 102, "events_unique": 100, "events_processed": 100, "duplicates": 2, "invalid_events": 0},
        "status_counts": {"COMPLETED": 100, "PENDING": 0, "RETRY": 0, "PROCESSING": 0, "QUARANTINED": 0},
        "gaps": [],
        "preflight": {"database": "PASS", "main_processes": 1, "parallel_jobs": 0, "logs": "PASS", "storage": "PASS"},
        "determinism": {"status": "PASS", "first_hash": "a" * 64, "second_hash": "a" * 64},
        "metrics_scoped": True,
        "findings": ["Der Markt wurde ausschließlich beobachtet."],
        "limitations": ["Kleine Stichprobe."],
    }


def test_complete_collection_is_deterministic_and_ready() -> None:
    builder = CollectionReportBuilder()
    first = builder.build(facts())
    second = builder.build(facts())
    assert first == second
    assert first["quality_status"] == "PASS"
    assert first["decision_status"] == "DECISION_READY"
    assert first["management_traffic_light"] == "GREEN"
    assert first["tim_autonomous_collection_ready"] is True
    assert first["trading_actions"] == 0


def test_classified_open_gap_is_visible_and_limited_not_failed() -> None:
    value = facts()
    value["gaps"] = [{
        "gap_id": "canonical-1",
        "status": "CLASSIFIED",
        "reason": "RECOVERABLE_BACKFILL",
        "category": "RECOVERABLE_BACKFILL",
    }]
    result = CollectionReportBuilder().build(value)
    assert result["checks"]["gaps_classified"] == "PASS"
    assert result["checks"]["known_open_gaps"] == "WARN"
    assert result["quality_status"] == "WARN"
    assert result["decision_status"] == "LIMITED"
    assert result["tim_autonomous_collection_ready"] is False


def test_incomplete_collection_fails_closed_with_no_decision() -> None:
    value = facts()
    value["counts"]["events_processed"] = 99
    value["status_counts"]["PENDING"] = 1
    value["gaps"] = [{"status": "OPEN", "reason": "missing interval"}]
    result = CollectionReportBuilder().build(value)
    assert result["quality_status"] == "FAIL"
    assert result["management_traffic_light"] == "RED"
    assert result["decision_status"] == "NO_DECISION"
    assert result["tim_autonomous_collection_ready"] is False


@pytest.mark.parametrize("key,value", [("live_trading", True), ("trading_actions", 1), ("mode", "LIVE")])
def test_non_observe_or_trading_facts_are_rejected(key: str, value: object) -> None:
    payload = facts(); payload[key] = value
    with pytest.raises(CollectionReportError, match="observe-only"):
        CollectionReportBuilder().build(payload)


def test_writer_is_atomic_idempotent_and_refuses_tamper(tmp_path: Path) -> None:
    builder = CollectionReportBuilder()
    first = builder.write(tmp_path, facts())
    expected = {"management_summary.md", "technical_report.md", "collection_result.json", "data_quality.json", "gaps.json", "manifest.json"}
    report_dir = Path(first["report_dir"])
    assert {path.name for path in report_dir.iterdir()} == expected
    assert builder.write(tmp_path, facts())["resumed"] is True
    (report_dir / "management_summary.md").write_text("tampered")
    with pytest.raises(CollectionReportError, match="refusing overwrite"):
        builder.write(tmp_path, facts())


def test_manifest_hashes_every_payload(tmp_path: Path) -> None:
    result = CollectionReportBuilder().write(tmp_path, facts())
    report_dir = Path(result["report_dir"])
    manifest = json.loads((report_dir / "manifest.json").read_text())
    assert len(manifest["files"]) == 5
    for item in manifest["files"]:
        assert len(item["sha256"]) == 64
        assert (report_dir / item["path"]).stat().st_size == item["size"]
