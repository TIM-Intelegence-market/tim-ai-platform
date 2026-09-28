from __future__ import annotations

import hashlib
import gzip
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.insights.engine import (
    ResearchInsightsEngine,
    _decimal,
    _evidence_signature,
    _percentile,
    _utc,
)
from src.operational.logging import LogRotator, RotationPolicy, StructuredLog
from src.research_ops.audit import ResearchAuditEngine, parse_time
from src.tim_v2.dataset.models import (
    QualityMetrics,
    TimeRange,
    dataset_from_manifest_json,
)


NOW = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# src/tim_v2/dataset/models.py
# ---------------------------------------------------------------------------

def _base_dataset(**overrides) -> dict:
    base = {
        "dataset_id": "btc_spot_ticks",
        "version": "1.0.0",
        "schema_version": "1.0.0",
        "content_sha256": "a" * 64,
        "source_uri": "s3://authoritative/ticks/manifest.json",
        "source_authorized": True,
        "license_name": "internal-research",
        "sensitivity": "restricted",
        "event_time": TimeRange(NOW, NOW),
        "observation_time": TimeRange(NOW, NOW),
        "publication_time": TimeRange(NOW, NOW),
        "quality": QualityMetrics(record_count=10, coverage_percent=100.0),
        "retention_policy": "retain-7y",
        "lineage": (),
        "supersedes": None,
        "metadata": {},
    }
    base.update(overrides)
    return base


def test_time_range_requires_timezone() -> None:
    tr = TimeRange(datetime(2026, 1, 1), datetime(2026, 1, 2))
    assert tr.issue("EVENT") == "EVENT_TIMEZONE_REQUIRED"


def test_time_range_reports_order_invalid() -> None:
    tr = TimeRange(NOW, NOW.replace(year=2025))
    assert tr.issue("EVENT") == "EVENT_ORDER_INVALID"


def test_quality_metrics_reports_invalid_counts_and_coverage() -> None:
    issues = QualityMetrics(
        record_count=-1,
        missing_record_count=-1,
        duplicate_record_count=-1,
        coverage_percent=101,
    ).issues()
    assert issues == ("RECORD_COUNT_INVALID", "QUALITY_COUNT_INVALID", "COVERAGE_INVALID")


def test_dataset_issues_reports_many_invalid_fields() -> None:
    from src.tim_v2.dataset.models import DatasetVersion

    dataset = DatasetVersion(
        **_base_dataset(
            dataset_id="Bad ID",
            version="1.0",
            schema_version="9",
            content_sha256="not-a-hash",
            source_uri="   ",
            source_authorized=False,
            license_name="   ",
            sensitivity="   ",
            retention_policy="   ",
            lineage=("up@1.0.0", "up@1.0.0"),
        )
    )
    issues = dataset.issues()
    expected = {
        "DATASET_ID_INVALID",
        "VERSION_INVALID",
        "SCHEMA_VERSION_INVALID",
        "CONTENT_HASH_INVALID",
        "SOURCE_URI_REQUIRED",
        "SOURCE_UNAUTHORIZED",
        "LICENSE_REQUIRED",
        "SENSITIVITY_REQUIRED",
        "RETENTION_POLICY_REQUIRED",
        "LINEAGE_DUPLICATE_REFERENCE",
    }
    assert expected <= set(issues)


def _manifest_payload() -> dict:
    iso = {"start": "2026-07-01T00:00:00+00:00", "end": "2026-07-02T00:00:00+00:00"}
    return {
        "dataset_id": "btc_spot_ticks",
        "version": "1.0.0",
        "schema_version": "1.0.0",
        "content_sha256": "b" * 64,
        "source_uri": "s3://authoritative/ticks/manifest.json",
        "source_authorized": True,
        "license_name": "internal-research",
        "sensitivity": "restricted",
        "event_time": iso,
        "observation_time": iso,
        "publication_time": iso,
        "quality": {
            "record_count": 1000,
            "missing_record_count": 0,
            "duplicate_record_count": 0,
            "coverage_percent": 100.0,
        },
        "retention_policy": "retain-7y",
    }


def test_manifest_decoder_round_trips_and_supports_optional_fields() -> None:
    payload = dict(_manifest_payload())
    payload["lineage"] = []
    payload["supersedes"] = None
    payload["metadata"] = {"owner": "research"}
    decoded = dataset_from_manifest_json(json.dumps(payload))
    assert decoded.dataset_id == "btc_spot_ticks"
    assert decoded.lineage == ()
    assert decoded.metadata == {"owner": "research"}


def test_manifest_non_object_rejected() -> None:
    with pytest.raises(ValueError, match="MANIFEST_OBJECT_REQUIRED"):
        dataset_from_manifest_json("[1, 2, 3]")


def test_manifest_missing_required_fields_rejected() -> None:
    payload = dict(_manifest_payload())
    del payload["dataset_id"]
    with pytest.raises(ValueError, match="MANIFEST_REQUIRED_FIELDS_MISSING"):
        dataset_from_manifest_json(json.dumps(payload))


def test_manifest_invalid_time_range_rejected() -> None:
    payload = dict(_manifest_payload())
    payload["event_time"] = {"start": "2026-07-01T00:00:00+00:00"}
    with pytest.raises(ValueError, match="MANIFEST_TIME_RANGE_INVALID"):
        dataset_from_manifest_json(json.dumps(payload))


def test_manifest_invalid_quality_rejected() -> None:
    payload = dict(_manifest_payload())
    payload["quality"] = {"record_count": 1}
    with pytest.raises(ValueError, match="MANIFEST_QUALITY_INVALID"):
        dataset_from_manifest_json(json.dumps(payload))


def test_manifest_field_type_errors_rejected() -> None:
    payload = dict(_manifest_payload())
    payload["event_time"]["start"] = "not-a-timestamp"
    with pytest.raises(ValueError, match="MANIFEST_FIELDS_INVALID"):
        dataset_from_manifest_json(json.dumps(payload))


# ---------------------------------------------------------------------------
# src/insights/engine.py
# ---------------------------------------------------------------------------

def _manifest() -> dict:
    return {
        "core_version": "1.0.0",
        "status": "FROZEN",
        "operating_mode": "OBSERVE",
        "components": {
            "orderflow_metrics": "1.0.0",
            "orderflow_observations": "1.0.0",
            "orderflow_validation": "1.0.0",
        },
    }


def test_utc_normalizes_aware_timestamps() -> None:
    assert _utc("2026-07-01T01:00:00+01:00") == datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)


def test_utc_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _utc("2026-07-01T00:00:00")


def test_utc_rejects_invalid_timestamps() -> None:
    with pytest.raises(ValueError, match="invalid timestamp"):
        _utc("not-a-time")


def test_decimal_rejects_invalid_and_non_finite() -> None:
    with pytest.raises(ValueError, match="invalid decimal"):
        _decimal("not-a-number")
    with pytest.raises(ValueError, match="non-finite"):
        _decimal("Infinity")


def test_percentile_requires_values() -> None:
    with pytest.raises(ValueError, match="requires values"):
        _percentile([], __import__("decimal").Decimal("0.5"))


def test_evidence_signature_rejects_non_object_clause() -> None:
    with pytest.raises(ValueError, match="evidence clauses must be objects"):
        _evidence_signature([1, 2])


def test_evidence_signature_rejects_clause_without_stable_descriptor() -> None:
    with pytest.raises(ValueError, match="no stable descriptor"):
        _evidence_signature([{"value": "1", "source_hash": "x"}])


def test_evidence_signature_uses_canonical_stable_descriptor() -> None:
    signature = _evidence_signature([{"stable_key": "first", "value": "2", "source_hash": "x"}])
    assert signature == (json.dumps({"stable_key": "first"}, sort_keys=True, separators=(",", ":")),)


def test_analyze_rejects_non_frozen_manifest() -> None:
    manifest = _manifest()
    manifest["status"] = "DRAFT"
    with pytest.raises(ValueError, match="frozen OBSERVE"):
        ResearchInsightsEngine().analyze([], [], [], manifest)


def test_analyze_rejects_missing_components() -> None:
    manifest = _manifest()
    manifest["components"] = None
    with pytest.raises(ValueError, match="components missing"):
        ResearchInsightsEngine().analyze([], [], [], manifest)


def test_analyze_rejects_incomplete_component_versions() -> None:
    manifest = _manifest()
    del manifest["components"]["orderflow_validation"]
    with pytest.raises(ValueError, match="version metadata incomplete"):
        ResearchInsightsEngine().analyze([], [], [], manifest)


def _obs(oid: str) -> dict:
    return {
        "observation_id": oid,
        "observed_at": "2026-07-01T00:00:00+00:00",
        "input_hash": "a" * 64,
        "kind": "RISING_CVD_ACTIVITY",
        "rule_version": "1.0.0",
        "evidence": [{"metric": "net_delta", "value": "2"}],
    }


def test_analyze_rejects_duplicate_observation_id() -> None:
    obs = _obs("dup")
    with pytest.raises(ValueError, match="duplicate observation_id"):
        ResearchInsightsEngine().analyze([obs, dict(obs)], [], [], _manifest())


def _validation(oid: str, *, outcome: str = "PRICE_INCREASED") -> dict:
    return {
        "observation_id": oid,
        "observed_at": "2026-07-01T00:00:00+00:00",
        "validation_hash": "b" * 64,
        "outcome": outcome,
        "complete": True,
        "horizons": [],
    }


def test_analyze_rejects_invalid_validation_hash() -> None:
    validation = _validation("obs1")
    validation["validation_hash"] = "not-a-hash"
    with pytest.raises(ValueError, match="invalid validation hash"):
        ResearchInsightsEngine().analyze([], [validation], [], _manifest())


def test_analyze_rejects_duplicate_validation_observation_id() -> None:
    validation = _validation("")
    with pytest.raises(ValueError, match="duplicate validation observation_id"):
        ResearchInsightsEngine().analyze([], [validation], [], _manifest())


def test_analyze_rejects_unsupported_outcome() -> None:
    validation = _validation("obs1", outcome="PREDICTION")
    with pytest.raises(ValueError, match="unsupported persisted outcome"):
        ResearchInsightsEngine().analyze([], [validation], [], _manifest())


def test_analyze_excludes_test_only_validation() -> None:
    validation = _validation("obs-unknown")
    validation["mode"] = "TEST_ONLY"
    validation["validation_hash"] = hashlib.sha256(b"x").hexdigest()
    result = ResearchInsightsEngine().analyze(
        [dict(_obs("obs1"), evidence=[{"metric": "net_delta", "value": "2"}, {"metric": "trades_per_second", "value": "4"}])],
        [validation],
        [],
        _manifest(),
        {},
    )
    assert result["sample_size"] == 1
    assert any(item["reason"] == "TEST_ONLY" for item in result["exclusions"])


# ---------------------------------------------------------------------------
# src/operational/logging.py
# ---------------------------------------------------------------------------

def test_rotation_policy_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        RotationPolicy(max_bytes=0)
    with pytest.raises(ValueError, match="backup_count"):
        RotationPolicy(backup_count=0)
    with pytest.raises(ValueError, match="retention_days"):
        RotationPolicy(retention_days=0)


def test_prune_expired_removes_stale_backups_ignores_others(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("data")
    stale = tmp_path / "events.jsonl.1.gz"
    stale.write_bytes(b"x")
    unrelated = tmp_path / "events.jsonl.tmp"
    unrelated.write_text("y")
    past = time.time() - 3 * 24 * 3600
    os.utime(stale, (past, past))
    os.utime(unrelated, (past, past))
    rotator = LogRotator(path, RotationPolicy(retention_days=1))
    removed = rotator._prune_expired_locked()
    assert str(stale) in removed
    assert unrelated.exists()
    assert not stale.exists()


def test_rotate_locked_empty_file_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("")
    rotator = LogRotator(path)
    assert rotator._rotate_locked() is None


def test_rotate_locked_uncompressed(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("line\n" * 100)
    rotator = LogRotator(path, RotationPolicy(compress=False, backup_count=1))
    rotated = rotator._rotate_locked()
    assert rotated is not None
    assert rotated.name == "events.jsonl.1"
    assert rotated.read_text() == "line\n" * 100


def test_rotate_locked_preserve_inode_keeps_active_file(tmp_path: Path) -> None:
    path = tmp_path / "runtime_launchd.err.log"
    path.write_text("line\n" * 100)
    inode = path.stat().st_ino
    rotator = LogRotator(
        path,
        RotationPolicy(compress=True, backup_count=1),
        preserve_inode=True,
    )

    rotated = rotator._rotate_locked()

    assert rotated is not None
    assert rotated.name == "runtime_launchd.err.log.1.gz"
    assert path.exists() and path.stat().st_ino == inode
    assert path.read_bytes() == b""
    with gzip.open(rotated, "rt", encoding="utf-8") as handle:
        assert handle.read() == "line\n" * 100


def test_rotate_if_needed_force_rotates(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("data")
    rotator = LogRotator(path, RotationPolicy(max_bytes=50, backup_count=2, retention_days=7))
    result = rotator.rotate_if_needed(force=True)
    assert result["rotated"] is not None
    assert result["size_before"] == 4


def test_rotate_if_needed_respects_threshold(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("small")
    rotator = LogRotator(path, RotationPolicy(max_bytes=100000, retention_days=7))
    result = rotator.rotate_if_needed()
    assert result["rotated"] is None
    assert result["size_before"] == 5


def test_rotate_if_needed_auto_rotates_when_oversize(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("x" * 1000)
    rotator = LogRotator(path, RotationPolicy(max_bytes=100, backup_count=4, retention_days=7))
    result = rotator.rotate_if_needed()
    assert result["rotated"] is not None
    assert not path.exists()


def test_rotate_if_needed_reports_expired_removed(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("data")
    stale = tmp_path / "events.jsonl.1.gz"
    stale.write_bytes(b"x")
    past = time.time() - 3 * 24 * 3600
    os.utime(stale, (past, past))
    rotator = LogRotator(path, RotationPolicy(retention_days=1, backup_count=2, max_bytes=100000))
    result = rotator.rotate_if_needed()
    assert str(stale) in result["expired_removed"]


def test_structured_log_redacts_nested_secrets(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    StructuredLog(path).write(
        "REDACT_TEST",
        credentials={"secret_token": "super-secret", "ok": "fine"},
        api_key="key-123",
        nested=[{"password": "p1", "safe": "v1"}],
    )
    raw = path.read_text()
    assert "super-secret" not in raw and "key-123" not in raw and "p1" not in raw
    assert raw.count("[REDACTED]") >= 2
    assert "v1" in raw and "REDACT_TEST" in raw


# ---------------------------------------------------------------------------
# src/research_ops/audit.py
# ---------------------------------------------------------------------------

def _audit_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "config").mkdir(parents=True)
    (root / "data/research/module_b_reports").mkdir(parents=True)
    (root / "config/core_manifest.json").write_text(
        json.dumps(
            {
                "core_version": "1.0.0",
                "status": "FROZEN",
                "operating_mode": "OBSERVE",
                "components": {
                    "orderflow_metrics": "1.0.0",
                    "orderflow_observations": "1.0.0",
                    "orderflow_validation": "1.0.0",
                },
            }
        )
    )
    return root


def test_parse_time_invalid_returns_none() -> None:
    assert parse_time("not-a-date") is None
    assert parse_time(None) is None


def test_parse_time_naive_returns_none() -> None:
    assert parse_time("2026-07-01T00:00:00") is None


def test_parse_time_aware_converts_to_utc() -> None:
    assert parse_time("2026-07-01T00:00:00Z") == datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_audit_requires_aware_as_of(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ResearchAuditEngine(_audit_root(tmp_path)).audit(as_of=datetime(2026, 7, 1))


def test_audit_rejects_non_frozen_manifest(tmp_path: Path) -> None:
    root = _audit_root(tmp_path)
    (root / "config/core_manifest.json").write_text(json.dumps({"status": "DRAFT", "operating_mode": "OBSERVE"}))
    with pytest.raises(ValueError, match="frozen OBSERVE"):
        ResearchAuditEngine(root).audit(as_of=NOW)


def test_audit_detects_json_hash_issues(tmp_path: Path) -> None:
    root = _audit_root(tmp_path)
    payload = {
        "mode": "OBSERVE",
        "timestamp": "2026-07-01T00:00:00+00:00",
        "provenance": "PUBLIC_MARKET_DATA_DETERMINISTIC",
        "output_hash": "short",
        "snapshot_hash": "short",
        "report_hash": "short",
    }
    (root / "data/research/state.json").write_text(json.dumps(payload))
    result = ResearchAuditEngine(root).audit(as_of=NOW)
    codes = {item["code"] for item in result["issues"]}
    assert {"OUTPUT_HASH_MISMATCH", "SNAPSHOT_HASH_MISMATCH", "REPORT_HASH_MISMATCH"} <= codes


def test_audit_detects_mode_and_provenance_violations(tmp_path: Path) -> None:
    root = _audit_root(tmp_path)
    (root / "data/research/bad.json").write_text(
        json.dumps({"mode": "PREDICT", "provenance": "opaque", "timestamp": "2026-07-01T00:00:00+00:00"})
    )
    result = ResearchAuditEngine(root).audit(as_of=NOW)
    codes = {item["code"] for item in result["issues"]}
    assert {"MODE_VIOLATION", "INVALID_PROVENANCE"} <= codes


def test_audit_detects_missing_metadata_and_invalid_artifact(tmp_path: Path) -> None:
    root = _audit_root(tmp_path)
    (root / "data/research/module_b_reports/note.md").write_text("# heading\ncontent")
    (root / "data/research/broken.json").write_text("{not-json")
    result = ResearchAuditEngine(root).audit(as_of=NOW)
    codes = {item["code"] for item in result["issues"]}
    assert {"MISSING_METADATA", "INVALID_ARTIFACT"} <= codes


def test_audit_detects_missing_report_target(tmp_path: Path) -> None:
    root = _audit_root(tmp_path)
    metadata = {
        "path": "data/research/missing.md",
        "mode": "OBSERVE",
        "timestamp": "2026-07-01T00:00:00+00:00",
        "provenance": "DETERMINISTIC",
        "file": "data/research/missing_target.md",
        "input_hash": "a" * 64,
        "artifact_hash": "a" * 64,
        "schema_version": "1.0.0",
        "generator_version": "1.0.0",
        "word_count": 1,
    }
    (root / "data/research/report.md.json").write_text(json.dumps(metadata))
    result = ResearchAuditEngine(root).audit(as_of=NOW)
    assert any(item["code"] == "MISSING_REPORT" for item in result["issues"])
