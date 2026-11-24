"""E2 (#372): persistent receipt/revision ledger, synthetic fixtures only, no recorder."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.orderflow import pit_ledger as ledger

NOON = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
T = int(NOON.timestamp())
DAY = "2026-11-24"


def _log(path):
    return ledger.PersistentRevisionLog(path, "binance-perp", "BTCUSDT")


def test_restart_keeps_the_knowledge_with_real_receipt_times(tmp_path):
    path = tmp_path / "ledger.jsonl"
    first = _log(path)
    assert first.observe({DAY: [[T - 600, 75000.0, 1.0, 2.0]]}, NOON) == 1
    assert first.observe({DAY: [[T - 600, 75000.0, 1.0, 2.0]]}, NOON + timedelta(minutes=1)) == 0   # unchanged
    first.observe({DAY: [[T - 600, 75000.0, 1.0, 9.0], [T - 900, 75000.0, 5.0, 0.0]]}, NOON + timedelta(hours=1))
    again = _log(path)                                               # restart
    days, counts = again.rows_at(NOON, 300)
    assert days == {DAY: [[T - 600, 75000.0, 1.0, 2.0]]}             # backfill and revision after noon stay out
    assert counts["unknown"] == 1 and counts["revised_later"] == 1
    assert ledger.verify(path) == {"ok": True, "records": 3, "skipped_partial": 0, "break": None}


def test_crash_tail_is_skipped_and_the_chain_goes_on(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _log(path).observe({DAY: [[T - 600, 1.0, 1.0, 2.0]]}, NOON)
    with path.open("ab") as fh:
        fh.write(b'{"schema": "pit-ledger/1", "half')                # crash mid-write
    log = _log(path)
    assert log.check["skipped_partial"] == 1 and log.check["ok"]
    log.observe({DAY: [[T - 300, 1.0, 3.0, 4.0]]}, NOON + timedelta(minutes=5))
    check = ledger.verify(path)
    assert check["ok"] and check["records"] == 2 and check["skipped_partial"] == 1


def test_edit_or_deletion_breaks_the_chain(tmp_path):
    path = tmp_path / "ledger.jsonl"
    log = _log(path)
    for i in range(3):
        log.observe({DAY: [[T - 900 + 300 * i, 1.0, float(i), 1.0]]}, NOON + timedelta(minutes=i))
    lines = path.read_bytes().splitlines()
    edited = json.loads(lines[1])
    edited["values"] = [99.0, 1.0]
    path.write_bytes(b"\n".join([lines[0], json.dumps(edited, sort_keys=True, separators=(",", ":")).encode(), lines[2]]) + b"\n")
    assert ledger.verify(path)["break"] == {"line": 3, "why": "chain"}
    path.write_bytes(b"\n".join([lines[0], lines[2]]) + b"\n")
    assert ledger.verify(path)["ok"] is False


def test_never_back_in_time_other_symbols_and_bad_rows(tmp_path):
    path = tmp_path / "ledger.jsonl"
    log = _log(path)
    log.observe({DAY: [[T - 600, 1.0, 1.0, 2.0]]}, NOON)
    assert log.observe({DAY: [[T - 600, 1.0, 7.0, 2.0]]}, NOON - timedelta(minutes=5)) == 0
    assert log.observe({DAY: [["x", 1.0, 1.0], [T, float("nan"), 1.0, 1.0], [T]]}, NOON) == 0
    assert log.observe(None, NOON) == 0 and log.observe({DAY: [[T, 1.0, 1.0, 1.0]]}, NOON.replace(tzinfo=None)) == 0
    other = ledger.PersistentRevisionLog(path, "binance-perp", "XMRUSDT")
    assert other.rows_at(NOON + timedelta(hours=1), 300)[0] == {}
