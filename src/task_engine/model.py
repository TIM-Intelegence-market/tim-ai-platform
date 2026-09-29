"""Canonical Task Engine entity and state enum (Issue #12, P1.1).

Schema and serialization only. Transition rules live in the state machine;
nothing here persists, schedules or executes anything.
"""
from dataclasses import dataclass, field, fields
from enum import StrEnum


class TaskState(StrEnum):
    NEW = 'NEW'
    PLANNED = 'PLANNED'
    READY = 'READY'
    IN_PROGRESS = 'IN_PROGRESS'
    VERIFYING = 'VERIFYING'
    BLOCKED = 'BLOCKED'
    SAFE_STOP = 'SAFE_STOP'
    FIXED = 'FIXED'
    FAILED = 'FAILED'


_TEXT_FIELDS = ('source', 'type', 'priority', 'risk', 'title', 'objective')
_OPTIONAL_TEXT_FIELDS = ('failure_reason', 'blocker_reason', 'next_action',
                         'code_version', 'git_sha', 'config_hash')
_LIST_FIELDS = ('acceptance_criteria', 'required_evidence', 'dependencies')


def _identity(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 128


@dataclass(frozen=True)
class Task:
    task_id: str
    parent_task_id: str | None = None
    source: str = ''
    type: str = ''
    priority: str = ''
    risk: str = ''
    state: TaskState = TaskState.NEW
    title: str = ''
    objective: str = ''
    acceptance_criteria: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    timestamps: dict[str, str] = field(default_factory=dict)
    attempt_count: int = 0
    failure_reason: str | None = None
    blocker_reason: str | None = None
    next_action: str | None = None
    code_version: str | None = None
    git_sha: str | None = None
    config_hash: str | None = None

    def __post_init__(self):
        if not _identity(self.task_id):
            raise ValueError('task_id must be a non-empty string of at most 128 characters')
        if self.parent_task_id is not None and (not _identity(self.parent_task_id)
                                                or self.parent_task_id == self.task_id):
            raise ValueError('parent_task_id must be another task identity')
        if not isinstance(self.state, TaskState):
            raise ValueError('state must be a TaskState')
        for name in _TEXT_FIELDS:
            if not isinstance(getattr(self, name), str):
                raise ValueError(f'{name} must be a string')
        for name in _OPTIONAL_TEXT_FIELDS:
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f'{name} must be a string or None')
        for name in _LIST_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValueError(f'{name} must be a list of strings')
        if any(not _identity(item) for item in self.dependencies):
            raise ValueError('dependencies must be task identities')
        if not isinstance(self.timestamps, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) for k, v in self.timestamps.items()):
            raise ValueError('timestamps must map strings to strings')
        if type(self.attempt_count) is not int or self.attempt_count < 0:
            raise ValueError('attempt_count must be a non-negative integer')

    def to_dict(self):
        """Plain JSON-compatible dict; containers are copies, state is its string value."""
        result = {}
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, TaskState):
                value = value.value
            elif isinstance(value, (list, dict)):
                value = value.copy()
            result[item.name] = value
        return result

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError('task data must be a dict')
        known = {item.name for item in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f'unknown task fields: {sorted(unknown)}')
        if 'task_id' not in data:
            raise ValueError('task_id is required')
        values = {}
        for name, value in data.items():
            if isinstance(value, (list, dict)):
                value = value.copy()
            values[name] = value
        if 'state' in values:
            state = values['state']
            if not isinstance(state, str) or state not in TaskState.__members__:
                raise ValueError(f'invalid task state: {state!r}')
            values['state'] = TaskState(state)
        return cls(**values)
