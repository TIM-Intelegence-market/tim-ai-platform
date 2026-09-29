"""Fix-First acceptance validator (Issue #12, P1.7).

A BUGFIX task may become FIXED only with content-bound evidence of an actual
repair and its verification. The check reuses the existing, reviewed
validator in src/bugfixer/tasks.py rather than defining a second, weaker one:
every artifact is hash-checked, the patch must equal the diff of the
before/after files, targeted and regression tests must pass as JUnit without
skips, and safety/runtime/integrity/recurrence reports must pass and be bound
to this task's id, attempt and Git SHA.

Analysis, reflection, booleans, prose and external model verdicts cannot
satisfy it; operational remediation is rejected until it has its own
verifier. Any error while checking evidence rejects (fail closed).
"""
from src.bugfixer.tasks import REQUIRED_EVIDENCE as BUGFIX_EVIDENCE
from src.bugfixer.tasks import Task as _EvidenceSubject
from src.bugfixer.tasks import validate_fix_evidence
from src.task_engine.model import TaskState
from src.task_engine.state_machine import InvalidTransition


class FixFirstRejected(InvalidTransition):
    pass


def validate_fixed(task, evidence):
    """Raise FixFirstRejected unless ``evidence`` proves ``task`` may become FIXED."""
    if not isinstance(evidence, dict):
        raise FixFirstRejected('completion evidence must be a dict of evidence references')
    if task.type == 'BUGFIX':
        try:
            subject = _EvidenceSubject(
                id=task.task_id, type='BUGFIX', attempt_count=task.attempt_count,
                git_sha=task.git_sha or 'UNKNOWN',
                required_evidence=tuple(dict.fromkeys((*BUGFIX_EVIDENCE, *task.required_evidence))))
            validate_fix_evidence(subject, evidence)
        except Exception as error:  # fail closed on any malformed or unverifiable evidence
            raise FixFirstRejected(f'BUGFIX {task.task_id} cannot be FIXED: {error}') from error
        return
    missing = [name for name in task.required_evidence if not evidence.get(name)]
    if missing:
        raise FixFirstRejected(f'{task.task_id} missing required evidence: {missing}')


def fix_first_guard(evidence_for):
    """Transition guard: ``evidence_for(task_id)`` supplies the stored evidence references."""
    def guard(task, target):
        if target is TaskState.FIXED:
            validate_fixed(task, evidence_for(task.task_id))
    return guard
