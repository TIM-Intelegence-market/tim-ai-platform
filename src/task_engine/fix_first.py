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

P1.13: a BUGFIX that declares ``repair_execution`` in required_evidence must
also prove the repair was executed by the engine's repair executor, and its
pre-/post-repair reproduction is re-derived from the JUnit and probe
artifacts themselves, never taken from a report's status field.
"""
import json
import xml.etree.ElementTree as ET

from src.bugfixer.tasks import REQUIRED_EVIDENCE as BUGFIX_EVIDENCE
from src.bugfixer.tasks import Task as _EvidenceSubject
from src.bugfixer.tasks import _artifact, _report, validate_fix_evidence
from src.task_engine.model import TaskState
from src.task_engine.state_machine import InvalidTransition

ENGINE_REPAIR_EVIDENCE = ('repair_execution', 'pre_repair_repro', 'post_repair_repro')
EXECUTOR_ID = 'src.task_engine.repair_executor'


class FixFirstRejected(InvalidTransition):
    pass


def _junit(reference):
    tree = ET.fromstring(_artifact(reference))
    cases = list(tree.iter('testcase'))
    names = {f"{case.get('classname')}::{case.get('name')}" for case in cases}
    failing = {f"{case.get('classname')}::{case.get('name')}" for case in cases
               if case.find('failure') is not None or case.find('error') is not None}
    return names, failing, any(list(tree.iter(tag)) for tag in ('failure', 'error', 'skipped'))


def _probe(reference):
    return None if reference is None else json.loads(_artifact(reference))


def validate_engine_repair(subject, evidence):
    """Engine-executed repair plus re-derived FAIL-before / PASS-after reproduction."""
    execution = _report(evidence['repair_execution'], subject)
    repair = evidence['repair']
    paths = execution.get('changed_paths')
    if (execution.get('executor') != EXECUTOR_ID or execution.get('outcome') != 'APPLIED'
            or execution.get('exit_status') != 0 or execution.get('repair_commit') != subject.git_sha):
        raise ValueError('repair was not applied by the engine executor for this code version')
    if not isinstance(paths, list) or len(paths) != 1 or paths[0] not in execution.get('allowed_paths', ()):
        raise ValueError('engine repair must change exactly one allowlisted file')
    if (execution['pre_sha256'].get(paths[0]) != repair['before']['sha256']
            or execution['post_sha256'].get(paths[0]) != repair['after']['sha256']):
        raise ValueError('engine repair hashes do not match the repair artifacts')
    if not _artifact(execution['git_diff']).strip() or not execution.get('workspace_marker', {}).get('workspace_id'):
        raise ValueError('engine diff or disposable workspace marker missing')
    pre = _report(evidence['pre_repair_repro'], subject)
    _, failing_before, _ = _junit(pre['junit'])
    before_probe = _probe(pre.get('probe'))
    if not failing_before or pre.get('defect_commit') != execution.get('defect_commit'):
        raise ValueError('defect did not fail as expected before the repair')
    if before_probe is not None and before_probe.get('defect_present') is not True:
        raise ValueError('runtime probe did not show the defect before the repair')
    post = _report(evidence['post_repair_repro'], subject)
    names_after, _, unclean = _junit(post['junit'])
    after_probe = _probe(post.get('probe'))
    if not names_after or unclean or not failing_before <= names_after:
        raise ValueError('previously failing tests do not all pass after the repair')
    if after_probe is not None and after_probe.get('defect_present') is not False:
        raise ValueError('runtime probe still shows the defect after the repair')


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
            if 'repair_execution' in task.required_evidence:
                validate_engine_repair(subject, evidence)
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
