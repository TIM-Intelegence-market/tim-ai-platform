"""Mission-task governance: idempotent, update-first, duplicate-safe task creation (#68)."""
from .identity import TaskRequest, canonical_task_key, fingerprint_marker, task_fingerprint
from .registry import Mapping, MappingState, TaskRegistry
from .sync import CreateNotSent, UnknownIssueKind, EnsureOutcome, EnsureResult, IssueRef, IssueGateway, ReopenPolicy, ensure_task
from .github_gateway import GitHubError, GitHubRestGateway
from .engine_bridge import IdentityDrift, issue_for_engine_task, request_from_engine_task, sync_engine_task_to_issue

__all__ = [
    'TaskRequest', 'canonical_task_key', 'task_fingerprint', 'fingerprint_marker',
    'TaskRegistry', 'Mapping', 'MappingState',
    'GitHubRestGateway', 'GitHubError', 'IdentityDrift', 'issue_for_engine_task', 'request_from_engine_task', 'sync_engine_task_to_issue',
    'ensure_task', 'CreateNotSent', 'EnsureResult', 'EnsureOutcome', 'IssueGateway', 'IssueRef', 'ReopenPolicy',
]
