"""Shared point-in-time contract (Mission 07, #372): property tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.orderflow import pit_contract as pc

T = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def obs(event=T, available=T, source="binance", symbol="BTCUSDT"):
    return pc.Observation(source, symbol, event, available)


def test_check_needs_event_and_known_availability_before_t():
    assert pc.check(obs(), T) == pc.OK
    assert pc.check(obs(event=T + timedelta(seconds=1)), T) == pc.FUTURE_EVENT
    assert pc.check(obs(available=T + timedelta(seconds=1)), T) == pc.NOT_YET_AVAILABLE
    assert pc.check(obs(available=None), T) == pc.UNKNOWN_AVAILABILITY        # never inferred from the event time
    assert pc.check(obs(), T.replace(tzinfo=None)) == pc.UNKNOWN_NO_TIME
    assert pc.check(obs(event=None), T) == pc.UNKNOWN_NO_TIME
    assert pc.check(obs(), T, symbol="XMRUSDT") == pc.WRONG_SOURCE and pc.check(obs(), T, source="bybit") == pc.WRONG_SOURCE


def test_as_time_never_guesses():
    assert pc.as_time("2026-11-24T12:00:00") is None and pc.as_time(float("nan")) is None and pc.as_time(True) is None
    assert pc.as_time("2026-11-24T12:00:00Z") == T and pc.as_time(T.timestamp()) == T


def _store(*rows):
    return {"2026-11-24": [list(r) for r in rows]}


def test_backfill_after_t_is_left_out_and_revision_after_t_keeps_the_old_value():
    t = T.timestamp()
    log = pc.RevisionLog()
    log.observe(_store([t - 600, 1.0, 1.0, 2.0]), T - timedelta(seconds=290))       # bucket 11:50 seen 11:55:10
    log.observe(_store([t - 600, 1.0, 1.0, 5.0], [t - 900, 1.0, 9.0, 0.0]), T + timedelta(hours=1))  # revised + backfill
    days, counts = log.rows_at(T, 300)
    assert days == {"2026-11-24": [[t - 600, 1.0, 1.0, 2.0]]}
    assert counts == {"kept": 1, "open": 0, "unknown": 1, "revised_later": 1}
    later, _ = log.rows_at(T + timedelta(hours=1), 300)
    assert sorted(later["2026-11-24"]) == [[t - 900, 1.0, 9.0, 0.0], [t - 600, 1.0, 1.0, 5.0]]


def test_metamorphic_information_after_t_never_changes_rows_at_t():
    t = T.timestamp()
    a, b = pc.RevisionLog(), pc.RevisionLog()
    first = _store([t - 600, 1.0, 1.0, 2.0], [t - 300, 2.0, 0.5, 0.5])
    for log in (a, b):
        log.observe(first, T - timedelta(seconds=10))
    b.observe(_store([t - 600, 1.0, 7.0, 7.0], [t - 1200, 3.0, 1.0, 1.0], [t, 1.0, 4.0, 4.0]), T + timedelta(seconds=1))
    assert a.rows_at(T, 300)[0] == b.rows_at(T, 300)[0]


def test_open_bucket_restart_and_bad_rows():
    t = T.timestamp()
    log = pc.RevisionLog()
    log.observe(_store([t - 120, 1.0, 1.0, 1.0], ["x", 1.0, 1.0], [t - 900, 1.0, "y", 1.0]), T)
    days, counts = log.rows_at(T, 300)
    assert days == {} and counts["open"] == 1                                         # running bucket never counts
    log.reset()                                                                         # restart: nothing known
    assert log.rows_at(T, 300)[0] == {}
    log.observe(_store([t - 900, 1.0, 1.0, 1.0]), T + timedelta(minutes=5))
    assert log.rows_at(T, 300)[1]["unknown"] == 1                                       # seen after t: not evidence at t
