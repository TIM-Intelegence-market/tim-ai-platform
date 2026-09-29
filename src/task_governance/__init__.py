"""Mission-task governance: idempotent, update-first, duplicate-safe task creation (#68)."""
from .identity import TaskRequest, canonical_task_key, fingerprint_marker, task_fingerprint
from .registry import Mapping, MappingState, TaskRegistry
from .sync import EnsureOutcome, EnsureResult, IssueRef, IssueGateway, ReopenPolicy, ensure_task

__all__ = [
    'TaskRequest', 'canonical_task_key', 'task_fingerprint', 'fingerprint_marker',
    'TaskRegistry', 'Mapping', 'MappingState',
    'ensure_task', 'EnsureResult', 'EnsureOutcome', 'IssueGateway', 'IssueRef', 'ReopenPolicy',
]
