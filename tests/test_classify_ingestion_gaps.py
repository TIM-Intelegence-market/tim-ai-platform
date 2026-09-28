from scripts.classify_ingestion_gaps import digest


def test_empty_gap_classification_has_the_same_completion_shape() -> None:
    payload = {
        "schema_version": "1.0.0",
        "mode": "OBSERVE",
        "read_only_database": True,
        "database_rows_written": 0,
        "symbol": "BTCUSDT",
        "raw_markers": 0,
        "canonical_ranges": 0,
        "classified_gaps": 0,
        "unknown_gaps": 0,
        "missing_records": 0,
        "ranges": [],
    }
    assert len(digest(payload)) == 64
