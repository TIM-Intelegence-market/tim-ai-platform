"""Deterministic TaskState machine (Issue #12, P1.2).

The only place that decides whether a state change is legal. Semantics match
src/bugfixer/tasks.py: a linear main path, escape states reachable from every
live state, SAFE_STOP released only through BLOCKED, FIXED terminal.

Time is supplied by the caller (``at``); nothing here reads the wall clock.
Evidence gating for FIXED is not decided here.
"""
from dataclasses import replace
from datetime import datetime
from types import MappingProxyType

from src.task_engine.model import Task, TaskState

S = TaskState

TERMINAL_STATES = frozenset({S.FIXED})
NON_TERMINAL_STATES = frozenset(set(S) - TERMINAL_STATES)
ESCAPE_STATES = frozenset({S.BLOCKED, S.SAFE_STOP, S.FAILED})
REASON_REQUIRED = ESCAPE_STATES

_FORWARD = {
    S.NEW: {S.PLANNED},
    S.PLANNED: {S.READY},
    S.READY: {S.IN_PROGRESS},
    S.IN_PROGRESS: {S.VERIFYING},
    S.VERIFYING: {S.FIXED, S.IN_PROGRESS},
    S.BLOCKED: {S.PLANNED, S.READY},
    S.SAFE_STOP: {S.BLOCKED},
    S.FAILED: {S.PLANNED},
    S.FIXED: set(),
}


def _build():
    table = {}
    for state, targets in _FORWARD.items():
        allowed = set(targets)
        if state not in TERMINAL_STATES and state is not S.SAFE_STOP:
            allowed |= ESCAPE_STATES
        allowed.discard(state)  # self-transitions are never legal
        table[state] = frozenset(allowed)
    return MappingProxyType(table)


TRANSITIONS = _build()


class InvalidTransition(ValueError):
    """Raised for any rejected transition; the task is left unchanged."""


def is_terminal(state):
    return TaskState(state) in TERMINAL_STATES


def allowed_targets(state):
    return TRANSITIONS[TaskState(state)]


def validate_transition(current, target):
    if not isinstance(current, TaskState) or not isinstance(target, TaskState):
        raise InvalidTransition('states must be TaskState members')
    if target not in TRANSITIONS[current]:
        raise InvalidTransition(f'illegal transition {current} -> {target}')
    return target


def _instant(value):
    if not isinstance(value, str):
        raise InvalidTransition('transition time must be an ISO-8601 string')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise InvalidTransition('transition time must be an ISO-8601 string') from error
    if parsed.tzinfo is None:
        raise InvalidTransition('transition time must include a timezone')
    return parsed


def transition(task, target, *, at, reason=None):
    """Return a new Task in ``target``; raise InvalidTransition and change nothing otherwise.

    Timestamps: ``updated_at`` and ``<state>_at`` are set to ``at``; ``created_at``
    is recorded on the first transition if absent. Time may not move backwards.
    Entering IN_PROGRESS counts an attempt; attempts are never reduced.
    Entering BLOCKED/SAFE_STOP/FAILED requires a reason; leaving BLOCKED or
    SAFE_STOP clears the blocker reason.
    """
    if not isinstance(task, Task):
        raise InvalidTransition('task must be a Task')
    validate_transition(task.state, target)
    moment = _instant(at)
    previous = task.timestamps.get('updated_at')
    if previous is not None and moment < _instant(previous):
        raise InvalidTransition('transition time precedes the last update')
    if target in REASON_REQUIRED and (not isinstance(reason, str) or not reason.strip()):
        raise InvalidTransition(f'transition to {target} requires a reason')
    if reason is not None and not isinstance(reason, str):
        raise InvalidTransition('reason must be a string')

    timestamps = dict(task.timestamps)
    timestamps.setdefault('created_at', at)
    timestamps['updated_at'] = at
    timestamps[f'{target.value.lower()}_at'] = at

    changes = {'state': target, 'timestamps': timestamps,
               'acceptance_criteria': list(task.acceptance_criteria),
               'required_evidence': list(task.required_evidence),
               'dependencies': list(task.dependencies)}
    if target is S.IN_PROGRESS:
        changes['attempt_count'] = task.attempt_count + 1
    if target in {S.BLOCKED, S.SAFE_STOP}:
        changes['blocker_reason'] = reason
    elif task.state in {S.BLOCKED, S.SAFE_STOP}:
        changes['blocker_reason'] = None
    if target is S.FAILED:
        changes['failure_reason'] = reason
    return replace(task, **changes)
