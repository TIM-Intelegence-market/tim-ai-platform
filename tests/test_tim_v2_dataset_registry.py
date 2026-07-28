from datetime import datetime, timezone

import pytest

import json

from src.tim_v2.dataset import DatasetRegistry, DatasetVersion, QualityMetrics, TimeRange, ValidationState, dataset_from_manifest_json


NOW = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)


def dataset(*, version: str = "1.0.0", lineage: tuple[str, ...] = (), supersedes: str | None = None, source_authorized: bool = True, event_end: datetime = NOW) -> DatasetVersion:
    return DatasetVersion(
        dataset_id="btc_spot_ticks",
        version=version,
        schema_version="1.0.0",
        content_sha256="a" * 64,
        source_uri="s3://authoritative/btc_spot_ticks/manifest.json",
        source_authorized=source_authorized,
        license_name="internal-research",
        sensitivity="restricted",
        event_time=TimeRange(NOW, event_end),
        observation_time=TimeRange(NOW, NOW),
        publication_time=TimeRange(NOW, NOW),
        quality=QualityMetrics(record_count=10, coverage_percent=100.0),
        retention_policy="retain-7y",
        lineage=lineage,
        supersedes=supersedes,
    )


def test_valid_dataset_is_registered_without_reading_or_copying_data() -> None:
    result = DatasetRegistry().register(dataset())
    assert result.state is ValidationState.VALID
    assert result.issues == ()
    assert len(result.manifest_sha256) == 64


def test_manifest_hash_is_deterministic() -> None:
    assert dataset().manifest_sha256() == dataset().manifest_sha256()


def test_unauthorized_source_is_quarantined() -> None:
    result = DatasetRegistry().register(dataset(source_authorized=False))
    assert result.state is ValidationState.QUARANTINED
    assert "SOURCE_UNAUTHORIZED" in result.issues


def test_invalid_event_order_is_quarantined() -> None:
    result = DatasetRegistry().register(dataset(event_end=NOW.replace(hour=11)))
    assert "EVENT_ORDER_INVALID" in result.issues


def test_unknown_lineage_is_quarantined() -> None:
    result = DatasetRegistry().register(dataset(lineage=("upstream@1.0.0",)))
    assert "LINEAGE_REFERENCE_NOT_FOUND:upstream@1.0.0" in result.issues


def test_registered_lineage_and_supersession_are_valid() -> None:
    registry = DatasetRegistry()
    first = registry.register(dataset())
    second = registry.register(dataset(version="1.0.1", lineage=(first.dataset.key,), supersedes=first.dataset.key))
    assert second.state is ValidationState.VALID


def test_identical_registration_is_idempotent_but_changed_version_is_rejected() -> None:
    registry = DatasetRegistry()
    first = registry.register(dataset())
    assert registry.register(dataset()) is first
    with pytest.raises(ValueError, match="already registered"):
        registry.register(dataset(version="1.0.0", source_authorized=False))


def test_canonical_manifest_ignores_whitespace_and_field_order() -> None:
    payload = dataset().manifest_payload()
    first = dataset_from_manifest_json(json.dumps(payload, separators=(",", ":")))
    second = dataset_from_manifest_json(json.dumps(dict(reversed(list(payload.items()))), indent=2))
    assert first.manifest_sha256() == second.manifest_sha256()


def test_semantic_manifest_change_changes_hash_and_old_version_is_unchanged() -> None:
    original = dataset()
    changed = dataset(version="1.0.1")
    assert original.manifest_sha256() != changed.manifest_sha256()
    assert original.version == "1.0.0"


@pytest.mark.parametrize("raw, code", [
    ("{", "MANIFEST_JSON_INVALID"),
    ('{"unexpected": true}', "MANIFEST_UNKNOWN_FIELDS"),
])
def test_malformed_or_unknown_manifest_is_rejected(raw: str, code: str) -> None:
    with pytest.raises(ValueError, match=code):
        dataset_from_manifest_json(raw)


@pytest.mark.parametrize("source_uri, issue", [
    ("file:///tmp/../secret", "SOURCE_URI_SCHEME_FORBIDDEN"),
    ("s3://authoritative/../../outside", "SOURCE_URI_PATH_TRAVERSAL"),
])
def test_path_and_symlink_style_file_uris_are_not_opened_and_are_quarantined(source_uri: str, issue: str) -> None:
    result = DatasetRegistry().register(DatasetVersion(**{**dataset().__dict__, "source_uri": source_uri}))
    assert result.state is ValidationState.QUARANTINED
    assert issue in result.issues


def test_cyclic_lineage_is_quarantined() -> None:
    registry = DatasetRegistry()
    first = registry.register(dataset(lineage=("btc_spot_ticks@1.0.1",)))
    second = registry.register(dataset(version="1.0.1", lineage=(first.dataset.key,)))
    assert "LINEAGE_CYCLE" in second.issues
