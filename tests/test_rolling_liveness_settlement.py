"""Rolling liveness uses a fixed settlement delay and strict expected-slot counting."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from src.operational.live_evidence import compute_rolling_liveness

NOW = datetime(2026, 10, 15, 12, 0, 30, tzinfo=timezone.utc)
EXPECTED_END = datetime(2026, 10, 15, 11, 58, tzinfo=timezone.utc)
EXPECTED_START = EXPECTED_END - timedelta(minutes=1440)


class _Connection:
    def __init__(self, times) -> None:
        self.times = list(times)
        self.calls: list[tuple] = []

    async def fetch(self, query, symbol, start, end):
        self.calls.append((symbol, start, end))
        return [{"open_time": value} for value in self.times]


def _slots() -> list[datetime]:
    return [EXPECTED_START + timedelta(minutes=i) for i in range(1440)]


def _run(times) -> tuple[dict, _Connection]:
    connection = _Connection(times)
    return asyncio.run(compute_rolling_liveness(connection, now=NOW)), connection


def test_sql_receives_fixed_delayed_window() -> None:
    record, connection = _run(_slots())
    assert connection.calls == [("BTCUSDT", EXPECTED_START, EXPECTED_END)]
    assert record["settlement_lag_minutes"] == 2
    assert record["window_end_utc"] == "2026-10-15T11:58:00Z"
    assert record["expected_observations"] == 1440


def test_complete_mature_window_passes_with_unsettled_newest_minutes() -> None:
    record, _ = _run(_slots())
    assert record["status"] == "PASS"
    assert record["valid_observations"] == 1440
    assert record["missing_observations"] == 0
    assert record["missing_examples_utc"] == []


def test_inner_missing_mature_minute_fails() -> None:
    slots = _slots()
    missing = slots.pop(700)
    record, _ = _run(slots)
    assert record["status"] == "FAIL"
    assert record["valid_observations"] == 1439
    assert record["missing_observations"] == 1
    assert record["missing_examples_utc"] == [missing.strftime("%Y-%m-%dT%H:%M:%SZ")]


def test_stopped_feed_fails() -> None:
    record, _ = _run(_slots()[:1260])
    assert record["status"] == "FAIL"
    assert record["missing_observations"] == 180
    assert len(record["missing_examples_utc"]) == 5


def test_duplicates_and_off_grid_timestamps_do_not_replace_missing_slots() -> None:
    slots = _slots()
    missing = slots.pop(10)
    times = slots + slots[:20] + [missing + timedelta(seconds=30), missing + timedelta(microseconds=1)]
    record, _ = _run(times)
    assert record["status"] == "FAIL"
    assert record["valid_observations"] == 1439
    assert record["missing_observations"] == 1


def test_missing_examples_are_bounded() -> None:
    record, _ = _run(_slots()[:10])
    assert record["missing_observations"] == 1430
    assert len(record["missing_examples_utc"]) == 5
    assert record["missing_examples_utc"][0] == "2026-10-14T11:58:00Z".replace("11:58", "12:08")
