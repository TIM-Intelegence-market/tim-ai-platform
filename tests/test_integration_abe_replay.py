"""End-to-end replay over A + B + E (Mission 07-FINAL, #372; test bench #384 only).

Real path, no hand-made Lage: trades -> LiveOrderflowTracker (A) -> snapshot -> orderflow shadow update (E, point in
time) -> gate (B, known side). Checked: the same input twice gives byte-identical files; information that arrives after
a plan never changes the plan's record; a restart loses evidence instead of inventing it; a Lage without the side
fields or a perp store without a bucket width is unknown; the earlier version's file is never touched (rollback).
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from src.dashboard import orderflow_shadow as shadow
from src.dashboard import pit_lage as pit
from src.orderflow import live_state as ls
from tests.test_orderflow_live_state import SYMBOL, T0, _feed, quiet_baseline, trade
from tests.test_orderflow_shadow import plan, write_journal

BASE = 20 * 60
NOW1 = T0 + timedelta(seconds=BASE + 180)
CREATED = NOW1 + timedelta(seconds=10)
OLD_BYTES = b'{"schema": "old-version", "plans": {"x": 1}}'


@pytest.fixture(autouse=True)
def _fresh_history():
    pit.reset()
    yield
    pit.reset()


def _tracker_with_buyer_wave() -> ls.LiveOrderflowTracker:
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tid = quiet_baseline(tracker)
    trades = []
    for minute, (qty, step) in enumerate(((2.0, 5), (4.0, 10), (8.0, 20))):
        for k in range(4):
            trades.append(trade(BASE + minute * 60 + k * 10, 75000 + step * (minute + 1) + k, qty / 4, True, tid := tid + 1))
        trades.append(trade(BASE + minute * 60 + 50, 75000 + step * (minute + 1), 0.2, False, tid := tid + 1))
    _feed(tracker, trades)
    return tracker


def _perp(now, **bucket):
    return {"symbol": SYMBOL, "updated_at": now.isoformat(), **bucket,
            "days": {"2026-11-08": [[now.timestamp() - 600, 75000.0, 1.0, 3.0]]}}


def _replay(tmp_path, *, late_news=False, restart=False, strip_side=False, bucket=None):
    """One run. Returns (plan record, bytes of the shadow file, bytes of the old-version file)."""
    pit.reset()
    tmp_path.mkdir(parents=True, exist_ok=True)
    journal, path = tmp_path / "tim_plan_journal_short.json", tmp_path / "shadow.json"
    path.write_bytes(OLD_BYTES)                                  # what the version before pit/1 left behind
    write_journal(journal)
    tracker = _tracker_with_buyer_wave()
    bucket = {"bucket_seconds": 300} if bucket is None else bucket
    lage1 = tracker.snapshot(NOW1, perp_store=_perp(NOW1, **bucket))
    if strip_side:                                               # the same Lage as an orderflow-lage/1 runtime wrote it
        lage1 = {**lage1, "windows": {n: {k: v for k, v in w.items() if k != "unknown_volume"} for n, w in lage1["windows"].items()}}
    shadow.update(path, [journal], lage1, now=NOW1)
    if restart:                                                  # process restart: history and tracker are gone
        pit.reset()
        tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    write_journal(journal, plan("OPEN", created_at=CREATED.isoformat()))
    now2 = CREATED + timedelta(seconds=20)
    shadow.update(path, [journal], tracker.snapshot(now2), now=now2)
    if late_news:                                                # heavy selling and a late-availability batch after the plan
        tid = 10_000
        sells = [trade(BASE + 240 + k, 74800.0 - k, 5.0, False, tid := tid + 1) for k in range(30)]
        _feed(tracker, sells)
        tracker.ingest([trade(BASE + 100, 76000.0, 50.0, True, 99_999)], available_at=now2 + timedelta(minutes=5))
        for minutes in (1, 3, 10):
            later = now2 + timedelta(minutes=minutes)
            shadow.update(path, [journal], tracker.snapshot(later, perp_store=_perp(later, bucket_seconds=300)), now=later)
    target = shadow.current_path(path, SYMBOL)
    return shadow.load(target)["plans"]["p1"], target.read_bytes(), path.read_bytes()


def test_the_real_path_confirms_a_long_plan_inside_a_buyer_wave(tmp_path):
    record, _, old = _replay(tmp_path)
    assert record["lage_at_plan_status"] == pit.OK and record["gate_at_plan"] == shadow.BESTAETIGT
    assert record["lage_at_plan"]["side_status"] == "OK" and record["lage_at_plan"]["known_share"] == 1.0
    assert old == OLD_BYTES


def test_the_same_inputs_give_byte_identical_files(tmp_path):
    first, second = _replay(tmp_path / "a"), _replay(tmp_path / "b")
    assert first[1] == second[1] and first[0] == second[0]
    again = _replay(tmp_path / "c", late_news=True), _replay(tmp_path / "d", late_news=True)
    assert again[0][1] == again[1][1]


def test_nothing_that_arrives_after_the_plan_changes_what_was_noted_at_the_plan(tmp_path):
    plain, late = _replay(tmp_path / "a")[0], _replay(tmp_path / "b", late_news=True)[0]
    for field in ("lage_at_plan", "lage_at_plan_status", "gate_at_plan", "timing_at_plan", "created_at"):
        assert json.dumps(plain[field], sort_keys=True) == json.dumps(late[field], sort_keys=True), field


def test_a_restart_before_the_plan_loses_the_evidence_and_never_confirms(tmp_path):
    record, _, old = _replay(tmp_path, restart=True)
    assert record["lage_at_plan"] is None and str(record["lage_at_plan_status"]).startswith("UNKNOWN")
    assert record["gate_at_plan"] != shadow.BESTAETIGT and old == OLD_BYTES


def test_a_lage_without_the_side_fields_is_unknown_end_to_end(tmp_path):
    record, _, _ = _replay(tmp_path, strip_side=True)
    assert record["lage_at_plan_status"] == pit.OK                      # the Lage was known in time ...
    assert record["lage_at_plan"]["side_status"] == "MISSING"           # ... but says nothing about the side
    assert record["gate_at_plan"] == shadow.UNBEKANNT


@pytest.mark.parametrize("bucket", [{}, {"bucket_seconds": None}, {"bucket_seconds": 0}, {"bucket_seconds": "300"}])
def test_a_perp_store_without_a_bucket_width_adds_no_perp_evidence(tmp_path, bucket):
    record, _, _ = _replay(tmp_path / "x", bucket=bucket)
    good = _replay(tmp_path / "y")[0]
    assert record["lage_at_plan"]["perp_delta_5m"] is None and good["lage_at_plan"]["perp_delta_5m"] is not None
    assert record["gate_at_plan"] == good["gate_at_plan"] == shadow.BESTAETIGT   # the spot wave is still proven


def test_rollback_reads_only_its_own_file_and_the_return_continues(tmp_path):
    record, new_bytes, old = _replay(tmp_path)
    path = tmp_path / "shadow.json"
    assert old == OLD_BYTES and shadow.current_path(path, SYMBOL) != path
    assert json.loads(path.read_bytes())["plans"] == {"x": 1}            # what the earlier version reads after a rollback
    journal = tmp_path / "tim_plan_journal_short.json"
    later = CREATED + timedelta(minutes=30)
    shadow.update(path, [journal], None, now=later)                      # upgrade again: continues, mixes nothing
    state = shadow.load(shadow.current_path(path, SYMBOL))
    assert state["plans"]["p1"]["gate_at_plan"] == record["gate_at_plan"] and path.read_bytes() == OLD_BYTES
