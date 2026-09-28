"""Validated, versioned incident lifecycle contracts."""
from enum import StrEnum

from src.collection_reporting.errors import ErrorClass

SCHEMA_VERSION = 2


class State(StrEnum):
    NEW = 'NEW'
    NORMALIZED = 'NORMALIZED'
    CLASSIFIED = 'CLASSIFIED'
    INVESTIGATING = 'INVESTIGATING'
    REPRODUCED = 'REPRODUCED'
    ROOT_CAUSE_FOUND = 'ROOT_CAUSE_FOUND'
    FIX_PROPOSED = 'FIX_PROPOSED'
    FIX_TESTING = 'FIX_TESTING'
    RESOLVED = 'RESOLVED'
    ESCALATED = 'ESCALATED'
    SAFE_STOP = 'SAFE_STOP'


_CHAIN = tuple(State)[:9]
_NEXT = {a: b for a, b in zip(_CHAIN, _CHAIN[1:])}


def validate_transition(current: str, target: str, evidence: str) -> State:
    current, target = State(current), State(target)
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError('transition requires evidence')
    allowed = {_NEXT[current]} if current in _NEXT else set()
    if current not in {State.RESOLVED, State.SAFE_STOP}:
        allowed |= {State.ESCALATED, State.SAFE_STOP}
    if current in {State.ESCALATED, State.RESOLVED}:
        allowed.add(State.INVESTIGATING)
    allowed.discard(current)
    if target not in allowed:
        raise ValueError('invalid incident state transition')
    return target
