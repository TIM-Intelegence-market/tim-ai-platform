from __future__ import annotations

from src.collection_reporting.collector import CollectionPreflightError


def test_preflight_error_preserves_read_only_snapshot() -> None:
    snapshot = {"status_counts": {"PENDING": 2}, "trading_actions": 0}
    error = CollectionPreflightError(["outbox is not drained"], snapshot)
    assert error.reasons == ["outbox is not drained"]
    assert error.snapshot is snapshot
    assert "outbox is not drained" in str(error)
