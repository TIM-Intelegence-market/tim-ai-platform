from datetime import datetime, timezone

import pytest

from src.options_gamma import recorder

NOW = datetime(2026, 11, 19, 21, 0, tzinfo=timezone.utc)


def _fetch(method, params):
    if method == "get_book_summary_by_currency":
        return {"result": [{"instrument_name": "BTC-27MAR26-100000-C", "open_interest": 5.0, "mark_iv": 50.0}]}
    return {"result": {"index_price": 95000.0}}


def test_capture_append_read_roundtrip(tmp_path):
    first = recorder.capture("BTC", fetch=_fetch, now=NOW)
    path = recorder.append(first, tmp_path)
    recorder.append(recorder.capture("BTC", fetch=_fetch, now=NOW.replace(hour=22)), tmp_path)
    assert path.name == "btc_options_2026-11-19.jsonl.gz"
    snaps = recorder.read(path)
    assert len(snaps) == 2 and snaps[0]["rows"] == first["rows"] and snaps[0]["index_price"] == 95000.0


def test_capture_rejects_empty_and_missing_price():
    with pytest.raises(ValueError):
        recorder.capture("BTC", fetch=lambda m, p: {"result": []})
    with pytest.raises(ValueError):
        recorder.capture("BTC", fetch=lambda m, p: {"result": [{"x": 1}]} if "book" in m else {"result": {}})


def test_record_once_writes_file(tmp_path):
    assert recorder.record_once(tmp_path, fetch=_fetch, now=NOW)[0].exists()
