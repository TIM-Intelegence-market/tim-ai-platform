from scripts.scaled_quarantine_drain import RuntimeGuard, next_batch_size, validate_transition


def state(*, completed=1000, quarantined=100, pending=10, retry=2, processing=0, queue=112, gaps=3):
    return {
        "status_counts": {"COMPLETED": completed, "QUARANTINED": quarantined, "PENDING": pending, "RETRY": retry, "PROCESSING": processing},
        "queue_depth": queue,
        "open_gaps": gaps,
        "cursor": {"cursor_hash": "a" * 64},
        "peak_rss_kib": 100_000,
    }


def test_valid_batch_transition_and_adaptive_step() -> None:
    before = state()
    after = state(completed=1100, quarantined=0, queue=12)
    result = {"status": "COMPLETED", "completed": 100, "selected": 100, "timing": {"recovery_total_seconds": 10}}
    assert validate_transition(before, after, 100) is None
    assert next_batch_size(100, result, before, after) == 250


def test_unexpected_pending_change_stops_and_prevents_scale_up() -> None:
    before = state()
    after = state(completed=1100, quarantined=0, pending=9, queue=12)
    result = {"status": "COMPLETED", "completed": 100, "selected": 100, "timing": {"recovery_total_seconds": 10}}
    assert validate_transition(before, after, 100) == "unexpected PENDING change"
    assert next_batch_size(100, result, before, after) == 100


def test_cursor_or_gap_change_is_a_hard_stop() -> None:
    before = state()
    after = state(completed=1100, quarantined=0, queue=12, gaps=4)
    assert validate_transition(before, after, 100) == "open gap count changed"
    after = state(completed=1100, quarantined=0, queue=12)
    after["cursor"] = {"cursor_hash": "b" * 64}
    assert validate_transition(before, after, 100) == "cursor changed"


def test_runtime_guard_detects_pid_or_restart_change(monkeypatch) -> None:
    identities = iter([(10, 1), (11, 1)])
    monkeypatch.setattr(RuntimeGuard, "_full_check", lambda self: next(identities))
    monkeypatch.setattr("scripts.scaled_quarantine_drain.os.kill", lambda pid, signal: None)
    guard = RuntimeGuard(full_check_every=1)
    try:
        guard()
    except RuntimeError as error:
        assert "PID or restart count changed" in str(error)
    else:
        raise AssertionError("runtime identity change was not rejected")
