from datetime import datetime

import pytest

from src.bugfixer import safety
from src.repair_repro.guards import cutoff_filter, database_guard


def test_same_database_is_rejected(monkeypatch):
    def reject_same(test_url, runtime_url):
        raise safety.SafetyViolation("same database")

    monkeypatch.setattr(safety, "require_isolated_database", reject_same)

    assert database_guard("postgres://db/test", "postgres://db/test") == (
        False,
        "database not isolated",
    )


def test_different_databases_are_accepted(monkeypatch):
    monkeypatch.setattr(safety, "require_isolated_database", lambda *_: None)

    assert database_guard("postgres://db/test", "postgres://db/runtime") == (
        True,
        "isolated",
    )


def test_database_reason_does_not_contain_url_secret(monkeypatch):
    def reject_same(test_url, runtime_url):
        raise safety.SafetyViolation("same database")

    monkeypatch.setattr(safety, "require_isolated_database", reject_same)
    secret_url = "postgres://user:super-secret@example.test/db"

    assert "super-secret" not in database_guard(secret_url, secret_url)[1]


def test_cutoff_filter_drops_events_after_cutoff():
    events = [
        {"id": "before", "timestamp": "2026-01-01T11:59:59+00:00"},
        {"id": "after", "timestamp": "2026-01-01T12:00:01+00:00"},
    ]

    assert cutoff_filter(events, "2026-01-01T12:00:00+00:00") == [events[0]]


def test_cutoff_filter_keeps_event_at_cutoff():
    event = {"id": "exact", "timestamp": "2026-01-01T12:00:00+00:00"}

    assert cutoff_filter([event], "2026-01-01T12:00:00+00:00") == [event]


@pytest.mark.parametrize(
    "events, cutoff",
    [
        ([{"timestamp": "2026-01-01T12:00:00"}], "2026-01-01T12:00:00+00:00"),
        ([{"timestamp": "not-a-timestamp"}], "2026-01-01T12:00:00+00:00"),
        ([{}], "2026-01-01T12:00:00+00:00"),
        (["not an event"], "2026-01-01T12:00:00+00:00"),
        ([{"timestamp": "2026-01-01T12:00:00+00:00"}], "2026-01-01T12:00:00"),
    ],
)
def test_cutoff_filter_rejects_invalid_timestamps_or_events(events, cutoff):
    with pytest.raises(ValueError):
        cutoff_filter(events, cutoff)


def test_cutoff_filter_does_not_mutate_input():
    events = [{"timestamp": "2026-01-01T12:00:00+00:00"}]
    original = [event.copy() for event in events]

    result = cutoff_filter(events, "2026-01-01T12:00:00+00:00")

    assert events == original
    assert result is not events
    assert result == events
