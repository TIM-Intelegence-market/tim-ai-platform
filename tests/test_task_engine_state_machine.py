"""Issue #12 P1.2 contract: complete positive/negative transition matrix and effects."""
from itertools import product

import pytest

from src.task_engine import Task, TaskState
from src.task_engine.state_machine import (
    NON_TERMINAL_STATES, TERMINAL_STATES, TRANSITIONS, InvalidTransition,
    allowed_targets, is_terminal, transition, validate_transition)

S = TaskState
T0 = '2026-09-29T10:00:00+00:00'
T1 = '2026-09-29T10:05:00+00:00'

# Written out independently of the implementation on purpose.
ALLOWED = {
    (S.NEW, S.PLANNED), (S.NEW, S.BLOCKED), (S.NEW, S.SAFE_STOP), (S.NEW, S.FAILED),
    (S.PLANNED, S.READY), (S.PLANNED, S.BLOCKED), (S.PLANNED, S.SAFE_STOP), (S.PLANNED, S.FAILED),
    (S.READY, S.IN_PROGRESS), (S.READY, S.BLOCKED), (S.READY, S.SAFE_STOP), (S.READY, S.FAILED),
    (S.IN_PROGRESS, S.VERIFYING), (S.IN_PROGRESS, S.BLOCKED), (S.IN_PROGRESS, S.SAFE_STOP),
    (S.IN_PROGRESS, S.FAILED),
    (S.VERIFYING, S.FIXED), (S.VERIFYING, S.IN_PROGRESS), (S.VERIFYING, S.BLOCKED),
    (S.VERIFYING, S.SAFE_STOP), (S.VERIFYING, S.FAILED),
    (S.BLOCKED, S.PLANNED), (S.BLOCKED, S.READY), (S.BLOCKED, S.SAFE_STOP), (S.BLOCKED, S.FAILED),
    (S.SAFE_STOP, S.BLOCKED),
    (S.FAILED, S.PLANNED), (S.FAILED, S.BLOCKED), (S.FAILED, S.SAFE_STOP),
}
ALL_PAIRS = list(product(S, S))
REASON = {S.BLOCKED: 'dependency missing', S.SAFE_STOP: 'invariant', S.FAILED: 'gave up'}


def task_in(state, **changes):
    return Task(task_id='t', state=state, **changes)


def test_matrix_covers_all_81_pairs_and_matches_expected():
    actual = {(a, b) for a, b in ALL_PAIRS if b in TRANSITIONS[a]}
    assert set(TRANSITIONS) == set(S)
    assert actual == ALLOWED


@pytest.mark.parametrize('current,target', sorted(ALLOWED))
def test_every_allowed_transition_passes(current, target):
    result = transition(task_in(current), target, at=T1, reason=REASON.get(target))
    assert result.state is target
    assert validate_transition(current, target) is target


@pytest.mark.parametrize('current,target', [p for p in ALL_PAIRS if p not in ALLOWED])
def test_every_illegal_transition_is_rejected_without_change(current, target):
    task = task_in(current, timestamps={'updated_at': T0}, attempt_count=3,
                   blocker_reason='kept', dependencies=['d'])
    before = task.to_dict()
    with pytest.raises(InvalidTransition):
        transition(task, target, at=T1, reason='any')
    with pytest.raises(InvalidTransition):
        validate_transition(current, target)
    assert task.to_dict() == before


@pytest.mark.parametrize('state', list(S))
def test_self_transition_is_always_illegal(state):
    assert state not in allowed_targets(state)
    with pytest.raises(InvalidTransition):
        transition(task_in(state), state, at=T1, reason='x')


def test_terminal_and_non_terminal_partition():
    assert TERMINAL_STATES == {S.FIXED}
    assert NON_TERMINAL_STATES == set(S) - {S.FIXED}
    assert is_terminal(S.FIXED) and not any(is_terminal(s) for s in NON_TERMINAL_STATES)
    assert allowed_targets(S.FIXED) == frozenset()
    for state in NON_TERMINAL_STATES:
        assert allowed_targets(state), state


def test_safe_stop_is_released_only_through_blocked():
    assert allowed_targets(S.SAFE_STOP) == {S.BLOCKED}


def test_raw_strings_are_not_accepted_as_states():
    with pytest.raises(InvalidTransition):
        validate_transition('NEW', S.PLANNED)
    with pytest.raises(InvalidTransition):
        transition(task_in(S.NEW), 'PLANNED', at=T1)


def test_timestamps_are_set_deterministically_from_supplied_time():
    first = transition(task_in(S.NEW), S.PLANNED, at=T0)
    assert first.timestamps == {'created_at': T0, 'updated_at': T0, 'planned_at': T0}
    second = transition(first, S.READY, at=T1)
    assert second.timestamps == {'created_at': T0, 'updated_at': T1, 'planned_at': T0, 'ready_at': T1}
    again = transition(transition(task_in(S.NEW), S.PLANNED, at=T0), S.READY, at=T1)
    assert again.to_dict() == second.to_dict()


def test_existing_created_at_is_preserved():
    task = task_in(S.NEW, timestamps={'created_at': '2026-01-01T00:00:00+00:00'})
    assert transition(task, S.PLANNED, at=T1).timestamps['created_at'] == '2026-01-01T00:00:00+00:00'


@pytest.mark.parametrize('at', [None, 5, 'yesterday', '2026-09-29T10:00:00'])
def test_invalid_or_naive_time_is_rejected(at):
    with pytest.raises(InvalidTransition):
        transition(task_in(S.NEW), S.PLANNED, at=at)


def test_time_cannot_move_backwards():
    task = task_in(S.NEW, timestamps={'updated_at': T1})
    with pytest.raises(InvalidTransition):
        transition(task, S.PLANNED, at=T0)
    assert transition(task, S.PLANNED, at=T1).state is S.PLANNED


def test_valid_transition_returns_new_task_and_leaves_original_untouched():
    task = task_in(S.READY, dependencies=['d'], timestamps={'updated_at': T0})
    before = task.to_dict()
    moved = transition(task, S.IN_PROGRESS, at=T1)
    moved.dependencies.append('leak')
    moved.timestamps['leak'] = 'x'
    assert task.to_dict() == before


def test_attempt_count_increments_on_in_progress_and_never_resets():
    task = transition(task_in(S.READY), S.IN_PROGRESS, at=T0)
    assert task.attempt_count == 1
    task = transition(task, S.VERIFYING, at=T0)
    task = transition(task, S.IN_PROGRESS, at=T1)
    assert task.attempt_count == 2
    task = transition(task, S.FAILED, at=T1, reason='broken')
    task = transition(task, S.PLANNED, at=T1)
    assert task.attempt_count == 2


@pytest.mark.parametrize('target', sorted(REASON))
@pytest.mark.parametrize('reason', [None, '', '   '])
def test_escape_states_require_reason(target, reason):
    with pytest.raises(InvalidTransition):
        transition(task_in(S.IN_PROGRESS), target, at=T1, reason=reason)


def test_reasons_are_recorded_and_blocker_cleared_on_release():
    blocked = transition(task_in(S.READY), S.BLOCKED, at=T0, reason='dep open')
    assert blocked.blocker_reason == 'dep open'
    assert transition(blocked, S.READY, at=T1).blocker_reason is None
    stopped = transition(task_in(S.READY), S.SAFE_STOP, at=T0, reason='invariant')
    assert stopped.blocker_reason == 'invariant'
    assert transition(stopped, S.BLOCKED, at=T1, reason='needs review').blocker_reason == 'needs review'
    failed = transition(task_in(S.READY), S.FAILED, at=T0, reason='gave up')
    assert failed.failure_reason == 'gave up'


def test_non_task_is_rejected():
    with pytest.raises(InvalidTransition):
        transition({'state': 'NEW'}, S.PLANNED, at=T0)
