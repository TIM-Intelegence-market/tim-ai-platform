"""Persistent repair task contracts and content-bound, fail-closed completion.

Evidence is inspected, never executed. Reports are local verification evidence,
not independent attestation of a production repair or authority to deploy it.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import difflib
import hashlib
import json
from pathlib import Path
import re
import stat
import uuid
import xml.etree.ElementTree as ET

from .processing import redact


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


REQUIRED_EVIDENCE = ('root_cause', 'reproduction', 'repair', 'targeted_tests',
                     'regression_tests', 'safety', 'runtime', 'integrity', 'recurrence')
_SHA = re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?')
_NEXT = {
    TaskState.NEW: {TaskState.PLANNED},
    TaskState.PLANNED: {TaskState.READY},
    TaskState.READY: {TaskState.IN_PROGRESS},
    TaskState.IN_PROGRESS: {TaskState.VERIFYING},
    TaskState.VERIFYING: {TaskState.FIXED, TaskState.IN_PROGRESS},
    TaskState.BLOCKED: {TaskState.PLANNED, TaskState.READY},
    TaskState.SAFE_STOP: {TaskState.BLOCKED},
    TaskState.FAILED: {TaskState.PLANNED},
    TaskState.FIXED: set(),
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 8192


@dataclass(frozen=True)
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_task: str | None = None
    incident_id: str | None = None
    type: str = 'BUGFIX'
    priority: str = 'P2'
    risk: str = 'MEDIUM'
    state: TaskState = TaskState.NEW
    dependencies: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ('Verified repair or explicit safe escalation',)
    required_evidence: tuple[str, ...] = REQUIRED_EVIDENCE
    attempt_count: int = 0
    failure_reason: str = ''
    blocker_reason: str = ''
    next_action: str = 'Investigate sanitized incident evidence; do not execute remediation'
    git_sha: str = 'UNKNOWN'
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    completed_at: str | None = None
    completion_evidence: dict = field(default_factory=dict)

    def __post_init__(self):
        if not _text(self.id) or len(self.id) > 128 or self.type not in {'BUGFIX', 'INVESTIGATION', 'MAINTENANCE'}:
            raise ValueError('invalid task identity or type')
        TaskState(self.state)
        if self.priority not in {'P0', 'P1', 'P2', 'P3'} or self.risk not in {'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'}:
            raise ValueError('invalid priority or risk')
        if type(self.attempt_count) is not int or self.attempt_count < 0:
            raise ValueError('invalid attempt count')
        for items in (self.dependencies, self.acceptance_criteria, self.required_evidence):
            if not isinstance(items, (tuple, list)) or len(items) > 100 or any(not _text(x) for x in items):
                raise ValueError('invalid task requirements')
        if not self.acceptance_criteria or len(set(self.dependencies)) != len(self.dependencies) or self.id in self.dependencies:
            raise ValueError('invalid task dependencies or acceptance')
        if self.type == 'BUGFIX' and not set(REQUIRED_EVIDENCE) <= set(self.required_evidence):
            raise ValueError('BUGFIX evidence requirements cannot be weakened')
        if self.git_sha != 'UNKNOWN' and (not isinstance(self.git_sha, str) or not _SHA.fullmatch(self.git_sha)):
            raise ValueError('invalid Git SHA')
        if not _text(self.next_action):
            raise ValueError('next action required')
        for value in (self.created_at, self.updated_at, self.started_at, self.completed_at):
            if value is not None and datetime.fromisoformat(value).tzinfo is None:
                raise ValueError('task timestamps must include timezone')

    def safe_dict(self):
        return redact(asdict(self))

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        value['state'] = TaskState(value['state'])
        for name in ('dependencies', 'acceptance_criteria', 'required_evidence'):
            value[name] = tuple(value[name])
        return cls(**value)


def validate_task_transition(current, target):
    current, target = TaskState(current), TaskState(target)
    allowed = set(_NEXT[current])
    if current not in {TaskState.FIXED, TaskState.SAFE_STOP}:
        allowed |= {TaskState.BLOCKED, TaskState.SAFE_STOP, TaskState.FAILED}
    allowed.discard(current)
    if target not in allowed:
        raise ValueError('invalid task state transition')
    return target


def _artifact(reference):
    """Bounded regular-file evidence with no symlink traversal or evaluation."""
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}:
        raise ValueError('content-addressed evidence reference required')
    path = Path(reference['path'])
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('unsafe evidence path')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 2 * 1024 * 1024:
        raise ValueError('invalid evidence file size/type')
    with path.open('rb') as handle:
        data = handle.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != reference['sha256']:
        raise ValueError('evidence integrity mismatch')
    return data


def _report(reference, task):
    report = json.loads(_artifact(reference))
    if (report.get('task_id') != task.id or report.get('attempt_count') != task.attempt_count
            or report.get('git_sha') != task.git_sha):
        raise ValueError('stale or unrelated task evidence')
    return report


def validate_fix_evidence(task: Task, evidence: dict):
    """Analysis, booleans and unbound reports cannot stand in for a repair."""
    if task.git_sha == 'UNKNOWN' or not isinstance(evidence, dict):
        raise ValueError('verified code version and completion evidence required')
    if not set(task.required_evidence) <= set(evidence):
        raise ValueError('required completion evidence missing')
    if not _text(evidence.get('root_cause')):
        raise ValueError('root cause required')
    reproduction = _report(evidence['reproduction'], task)
    if reproduction.get('outcome') not in {'REPRODUCED', 'TECHNICALLY_NOT_REPRODUCIBLE'}:
        raise ValueError('reproduction outcome required')
    if not _text(reproduction.get('details')):
        raise ValueError('reproduction evidence or technical justification required')
    repair = evidence['repair']
    # An operational recovery needs its own verifier before it can satisfy FIXED.
    if not isinstance(repair, dict) or repair.get('kind') != 'CODE_PATCH':
        raise ValueError('proven code repair required; operational verifier unavailable')
    before, after = _artifact(repair['before']), _artifact(repair['after'])
    patch = _artifact(repair['patch'])
    expected = ''.join(difflib.unified_diff(before.decode().splitlines(True),
                         after.decode().splitlines(True), fromfile='before', tofile='after')).encode()
    if before == after or not expected or patch != expected:
        raise ValueError('actual before/after code change and matching patch required')
    for gate in ('targeted_tests', 'regression_tests'):
        report = _report(evidence[gate], task)
        if report.get('status') != 'PASS' or report.get('code_sha256') != repair['after']['sha256']:
            raise ValueError('test report must pass for repaired code')
        tree = ET.fromstring(_artifact(report['junit']))
        cases = list(tree.iter('testcase'))
        if not cases or any(list(tree.iter(tag)) for tag in ('failure', 'error', 'skipped')):
            raise ValueError('targeted and regression tests must pass without skips')
    for gate in ('safety', 'runtime', 'integrity', 'recurrence'):
        report = _report(evidence[gate], task)
        checks = report.get('checks')
        if (report.get('status') != 'PASS' or not isinstance(checks, dict) or not checks
                or any(not _text(k) or v is not True for k, v in checks.items())):
            raise ValueError('verification gate did not pass')
        if gate == 'recurrence':
            _artifact(report['protection'])
    return evidence
