import hashlib
import json

from src.collection_reporting import load_gap_classification, missing_ranges


def test_gap_markers_are_consolidated_to_disjoint_actual_holes() -> None:
    result = missing_ranges([10, 11, 15, 16, 20], marker_from_id=10, marker_to_id=22)
    assert [(item.missing_from_id, item.missing_to_id) for item in result] == [(12, 14), (17, 19), (21, 22)]
    assert all(item.category == "RECOVERABLE_BACKFILL" for item in result)


def test_empty_range_is_one_bounded_gap() -> None:
    result = missing_ranges([], marker_from_id=5, marker_to_id=7)
    assert result[0].missing_records == 3


def test_classification_artifact_is_hash_and_marker_bound(tmp_path) -> None:
    payload = {
        "mode": "OBSERVE",
        "read_only_database": True,
        "database_rows_written": 0,
        "symbol": "BTCUSDT",
        "raw_markers": 2,
        "canonical_ranges": 1,
        "classified_gaps": 1,
        "unknown_gaps": 0,
        "ranges": [{"range_id": 1, "category": "RECOVERABLE_BACKFILL"}],
    }
    payload["classification_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path = tmp_path / "gaps.json"
    path.write_text(json.dumps(payload))
    assert load_gap_classification(path, symbol="BTCUSDT", raw_marker_count=2)
    assert load_gap_classification(path, symbol="BTCUSDT", raw_marker_count=3) is None
    payload["ranges"][0]["category"] = "UNKNOWN"
    path.write_text(json.dumps(payload))
    assert load_gap_classification(path, symbol="BTCUSDT", raw_marker_count=2) is None
