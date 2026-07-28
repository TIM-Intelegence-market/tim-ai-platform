from datetime import datetime, timezone

import pytest

from src.tim_v2.dataset import DatasetRegistry, DatasetVersion, QualityMetrics, TimeRange, ValidationState


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


def test_duplicate_version_is_rejected_without_overwrite() -> None:
    registry = DatasetRegistry()
    registry.register(dataset())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(dataset())
