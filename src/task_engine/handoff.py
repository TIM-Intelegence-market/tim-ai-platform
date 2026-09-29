"""Session / usage-limit resume contract (Issue #12, P1.6).

The handoff snapshot is derived from the repository alone, so a new session
or process resumes from durable state and never from chat memory. It is not
stored separately, so it cannot drift from the tasks it describes.
"""
import json

from src.task_engine.gating import transition_blockers
from src.task_engine.model import TaskState

S = TaskState
SNAPSHOT_VERSION = 1

# Order in which live work is resumed; BLOCKED, SAFE_STOP and FAILED need an
# explicit decision and are never picked automatically.
RESUME_ORDER = (S.IN_PROGRESS, S.VERIFYING, S.READY, S.PLANNED, S.NEW)
ACTIVE_STATES = frozenset({S.IN_PROGRESS, S.VERIFYING})
FORWARD = {S.NEW: S.PLANNED, S.PLANNED: S.READY, S.READY: S.IN_PROGRESS,
           S.IN_PROGRESS: S.VERIFYING, S.VERIFYING: S.FIXED, S.BLOCKED: S.READY, S.FAILED: S.PLANNED}


def resumable_tasks(repo):
    tasks = []
    for state in RESUME_ORDER:
        tasks += repo.list(state=state)
    return tasks


def _verification(checkpoints):
    for item in reversed(checkpoints):
        if 'verification' in item['metadata']:
            return {'status': item['metadata']['verification'], 'step_id': item['step_id'], 'at': item['at']}
    return {'status': 'NOT_RECORDED', 'step_id': None, 'at': None}


def snapshot(repo, task_id):
    task = repo.get(task_id)
    checkpoints = repo.checkpoints(task_id)
    last = checkpoints[-1] if checkpoints else None
    blockers = []
    if task.state in {S.BLOCKED, S.SAFE_STOP}:
        blockers.append({'code': f'TASK_{task.state.value}', 'task_id': task.task_id,
                         'state': task.state.value, 'reason': task.blocker_reason})
    forward = FORWARD.get(task.state)
    if forward is not None:
        blockers += [b.to_dict() for b in transition_blockers(repo, task, forward)]
    return {
        'snapshot_version': SNAPSHOT_VERSION,
        'task_id': task.task_id,
        'parent_task_id': task.parent_task_id,
        'type': task.type,
        'state': task.state.value,
        'attempt_count': task.attempt_count,
        'last_completed_step': None if last is None else {
            'step_id': last['step_id'], 'at': last['at'], 'metadata': last['metadata']},
        'completed_steps': [item['step_id'] for item in checkpoints],
        'next_action': task.next_action,
        'blockers': blockers,
        'code_version': task.code_version,
        'git_sha': task.git_sha,
        'config_hash': task.config_hash,
        'verification': _verification(checkpoints),
    }


def session_handoff(repo):
    """Snapshot of the task a new session must resume, plus machine-readable status."""
    candidates = resumable_tasks(repo)
    active = [task.task_id for task in candidates if task.state in ACTIVE_STATES]
    handoff = {'snapshot_version': SNAPSHOT_VERSION, 'current': None, 'wip_violation': len(active) > 1,
               'active_task_ids': active,
               'held_task_ids': [t.task_id for state in (S.BLOCKED, S.SAFE_STOP, S.FAILED)
                                 for t in repo.list(state=state)]}
    if candidates:
        handoff['current'] = snapshot(repo, candidates[0].task_id)
    return handoff


def dumps(handoff):
    return json.dumps(handoff, sort_keys=True, separators=(',', ':'))
