"""Connect a local Task Engine task (#12) to exactly one GitHub issue (#68).

The Task Engine only stores tasks; it never talks to GitHub. `sync_engine_task_to_issue` derives the
task identity from the engine task, runs `ensure_task`, and records the resulting issue number as an
idempotent checkpoint. It never changes the task state, so a BLOCKED sync leaves the engine untouched.
"""
import hashlib
import re

from .identity import TaskRequest
from .sync import EnsureOutcome, ReopenPolicy, ensure_task

_PLAIN_TARGET = re.compile(r'^[A-Z0-9][A-Z0-9_.\-]*$')
_RESERVED_TARGET = re.compile(r'^H-[0-9A-F]{16}$')
STEP_PREFIX = 'github_issue:'


class IdentityDrift(ValueError):
    """The engine task already has an issue checkpoint under another identity (phase, type, target, schema)."""


def _target_for(task_id) -> str:
    """The canonical key upper-cases the target, so ids that differ only in case would share one issue.
    Only ids that are already upper case (and cannot look like a hash target) are used as they are."""
    if _PLAIN_TARGET.match(task_id) and not _RESERVED_TARGET.match(task_id):
        return task_id
    return 'H-' + hashlib.sha256(task_id.encode('utf-8')).hexdigest()[:16].upper()


_WITH_ISSUE = (EnsureOutcome.CREATED, EnsureOutcome.RECOVERED, EnsureOutcome.UPDATED, EnsureOutcome.REOPENED)


def _section(heading, lines):
    return f'**{heading}**\n' + '\n'.join(f'- {line}' for line in lines) if lines else ''


def request_from_engine_task(task, *, mission_id, phase_id, target=None, schema_version='v1', task_type=None) -> TaskRequest:
    """Identity comes from the caller's mission/phase plus the task: the same task id always yields the same key."""
    parts = [task.objective.strip(),
             _section('Acceptance criteria', task.acceptance_criteria),
             _section('Required evidence', task.required_evidence),
             f'Engine task: `{task.task_id}`' + (f' (source: {task.source})' if task.source else '')]
    return TaskRequest(mission_id=mission_id, phase_id=phase_id, task_type=task_type or task.type,
                       target=target or _target_for(task.task_id), schema_version=schema_version,
                       title=task.title or task.task_id, body='\n\n'.join(part for part in parts if part))


def sync_engine_task_to_issue(engine, task_id, registry, gateway, *, mission_id, phase_id, claimant, trusted_authors,
                              target=None, schema_version='v1', task_type=None, policy=ReopenPolicy.NEVER, retry=False,
                              authoritative_hint=None, legacy_issues=(), lease_seconds=300.0):
    """Ensure the task's issue and checkpoint `github_issue:<fingerprint[:16]>`; returns the `EnsureResult`."""
    task = engine.get_task(task_id)
    request = request_from_engine_task(task, mission_id=mission_id, phase_id=phase_id, target=target,
                                       schema_version=schema_version, task_type=task_type)
    step = f'{STEP_PREFIX}{request.fingerprint[:16]}'
    drifted = [c['step_id'] for c in engine.checkpoints(task_id)
               if c['step_id'].startswith(STEP_PREFIX) and c['step_id'] != step]
    if drifted:
        raise IdentityDrift(f'task {task_id} already has {drifted[0]}; this call would create a second issue')
    result = ensure_task(request, registry, gateway, claimant=claimant, policy=policy, retry=retry,
                         trusted_authors=trusted_authors, authoritative_hint=authoritative_hint,
                         legacy_issues=legacy_issues, lease_seconds=lease_seconds)
    if result.outcome in _WITH_ISSUE and result.issue_number is not None and task.state.value != 'FIXED':
        engine.checkpoint(task_id, step,
                          next_action=task.next_action or 'continue task', metadata={'issue': result.issue_number,
                                                                                    'outcome': result.outcome.value})
    return result
