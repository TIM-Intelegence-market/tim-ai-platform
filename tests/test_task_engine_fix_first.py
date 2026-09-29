"""Issue #12 P1.7 contract: analysis-only closure is rejected; real repair evidence closes."""
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from src.task_engine import Task, TaskState
from src.task_engine.fix_first import FixFirstRejected, fix_first_guard, validate_fixed
from src.task_engine.repository import SqliteTaskRepository
from src.task_engine.state_machine import InvalidTransition
from tests.bugfixer.repair_fixture import evidence as synthetic_evidence

S = TaskState
SHA = 'e' * 40
T = '2026-09-29T10:00:00+00:00'


def bugfix(**changes):
    values = dict(task_id='bug-1', type='BUGFIX', state=S.VERIFYING, attempt_count=1, git_sha=SHA)
    values.update(changes)
    return Task(**values)


def valid_evidence(tmp_path, task):
    subject = SimpleNamespace(id=task.task_id, attempt_count=task.attempt_count, git_sha=task.git_sha)
    return synthetic_evidence(tmp_path, subject)


def rewrite(reference, mutate):
    """Rewrite an evidence file consistently (new hash) to model a forged or wrong artifact."""
    path = reference['path']
    with open(path) as handle:
        data = mutate(handle.read())
    with open(path, 'w') as handle:
        handle.write(data)
    return {'path': path, 'sha256': hashlib.sha256(data.encode()).hexdigest()}


def edit_report(reference, **fields):
    return rewrite(reference, lambda text: json.dumps({**json.loads(text), **fields}))


def test_complete_repair_and_verification_evidence_passes(tmp_path):
    task = bugfix()
    validate_fixed(task, valid_evidence(tmp_path, task))


@pytest.mark.parametrize('evidence', [
    {},
    {'root_cause': 'Hash check missing in evidence gate'},
    {'root_cause': 'analysis', 'analysis': 'long reflection', 'report': 'documented'},
    {'root_cause': 'x', 'repair': True, 'targeted_tests': True, 'regression_tests': True, 'safety': True,
     'runtime': True, 'integrity': True, 'recurrence': True, 'reproduction': True},
    {'model_verdict': 'FIXED', 'model': 'external-llm', 'confidence': 0.99},
    'FIXED',
    None,
])
def test_analysis_only_or_claimed_evidence_is_rejected(evidence):
    with pytest.raises(FixFirstRejected):
        validate_fixed(bugfix(), evidence)


@pytest.mark.parametrize('missing', ['root_cause', 'reproduction', 'repair', 'targeted_tests',
                                     'regression_tests', 'safety', 'runtime', 'integrity', 'recurrence'])
def test_each_required_gate_is_mandatory(tmp_path, missing):
    task = bugfix()
    evidence = valid_evidence(tmp_path, task)
    del evidence[missing]
    with pytest.raises(FixFirstRejected):
        validate_fixed(task, evidence)


def test_repair_without_actual_code_change_is_rejected(tmp_path):
    task = bugfix()
    evidence = valid_evidence(tmp_path, task)
    evidence['repair']['after'] = evidence['repair']['before']
    with pytest.raises(FixFirstRejected):
        validate_fixed(task, evidence)


def test_patch_not_matching_before_after_is_rejected(tmp_path):
    task = bugfix()
    evidence = valid_evidence(tmp_path, task)
    evidence['repair']['patch'] = rewrite(evidence['repair']['patch'], lambda text: text + '+extra\n')
    with pytest.raises(FixFirstRejected):
        validate_fixed(task, evidence)


def test_operational_remediation_claim_is_rejected_without_verifier(tmp_path):
    task = bugfix()
    evidence = valid_evidence(tmp_path, task)
    evidence['repair'] = {'kind': 'OPERATIONAL', 'description': 'restarted the service'}
    with pytest.raises(FixFirstRejected):
        validate_fixed(task, evidence)


def test_tampered_artifact_is_rejected(tmp_path):
    task = bugfix()
    evidence = valid_evidence(tmp_path, task)
    with open(evidence['runtime']['path'], 'a') as handle:
        handle.write(' ')
    with pytest.raises(FixFirstRejected):
        validate_fixed(task, evidence)


@pytest.mark.parametrize('gate,fields', [
    ('targeted_tests', {'status': 'FAIL'}),
    ('regression_tests', {'code_sha256': '0' * 64}),
    ('runtime', {'status': 'FAIL'}),
    ('recurrence', {'checks': {'regression_test_added': False}}),
    ('reproduction', {'outcome': 'NOT_ATTEMPTED'}),
])
def test_failed_or_mismatched_verification_is_rejected(tmp_path, gate, fields):
    task = bugfix()
    evidence = valid_evidence(tmp_path, task)
    evidence[gate] = edit_report(evidence[gate], **fields)
    with pytest.raises(FixFirstRejected):
        validate_fixed(task, evidence)


def test_junit_with_failure_or_skip_is_rejected(tmp_path):
    task = bugfix()
    evidence = valid_evidence(tmp_path, task)
    junit = json.loads(open(evidence['targeted_tests']['path']).read())['junit']
    forged = rewrite(junit, lambda _: '<testsuite><testcase name="t"><skipped/></testcase></testsuite>')
    evidence['targeted_tests'] = edit_report(evidence['targeted_tests'], junit=forged)
    with pytest.raises(FixFirstRejected):
        validate_fixed(task, evidence)


@pytest.mark.parametrize('changes', [{'attempt_count': 2}, {'git_sha': 'f' * 40}, {'task_id': 'other'}])
def test_evidence_bound_to_another_task_attempt_or_version_is_rejected(tmp_path, changes):
    task = bugfix()
    evidence = valid_evidence(tmp_path, task)
    with pytest.raises(FixFirstRejected):
        validate_fixed(replace(task, **changes), evidence)


def test_bugfix_without_code_version_is_rejected(tmp_path):
    task = bugfix()
    evidence = valid_evidence(tmp_path, task)
    with pytest.raises(FixFirstRejected):
        validate_fixed(replace(task, git_sha=None), evidence)


def test_task_specific_extra_evidence_is_also_required(tmp_path):
    task = bugfix(required_evidence=['operator_signoff'])
    evidence = valid_evidence(tmp_path, task)
    with pytest.raises(FixFirstRejected):
        validate_fixed(task, evidence)
    evidence['operator_signoff'] = 'reviewed'
    validate_fixed(task, evidence)


def test_non_bugfix_needs_its_declared_evidence():
    task = Task(task_id='m', type='MAINTENANCE', required_evidence=['summary'])
    with pytest.raises(FixFirstRejected):
        validate_fixed(task, {})
    validate_fixed(task, {'summary': 'children fixed'})


def test_guard_blocks_fixed_transition_in_repository_and_writes_nothing(tmp_path):
    stored = {}
    with SqliteTaskRepository(tmp_path / 'tasks.sqlite3') as repo:
        repo.create(Task(task_id='bug-1', type='BUGFIX', git_sha=SHA))
        for target in (S.PLANNED, S.READY, S.IN_PROGRESS, S.VERIFYING):
            repo.transition('bug-1', target, at=T)
        guard = fix_first_guard(lambda task_id: stored.get(task_id, {}))
        stored['bug-1'] = {'root_cause': 'analysis only'}
        with pytest.raises(FixFirstRejected) as rejected:
            repo.transition('bug-1', S.FIXED, at=T, guard=guard)
        assert isinstance(rejected.value, InvalidTransition)
        assert repo.get('bug-1').state is S.VERIFYING and len(repo.history('bug-1')) == 4
        stored['bug-1'] = valid_evidence(tmp_path, repo.get('bug-1'))
        assert repo.transition('bug-1', S.FIXED, at=T, guard=guard).state is S.FIXED


def test_non_fixed_transitions_are_not_evidence_gated(tmp_path):
    with SqliteTaskRepository(tmp_path / 'tasks.sqlite3') as repo:
        repo.create(Task(task_id='bug-1', type='BUGFIX'))
        guard = fix_first_guard(lambda task_id: {})
        repo.transition('bug-1', S.PLANNED, at=T, guard=guard)
        repo.transition('bug-1', S.FAILED, at=T, reason='r', guard=guard)


def test_bugfix_cannot_be_relabelled_to_escape_the_gate(tmp_path):
    with SqliteTaskRepository(tmp_path / 'tasks.sqlite3') as repo:
        repo.create(Task(task_id='bug-1', type='BUGFIX'))
        with pytest.raises(ValueError):
            repo.update(Task(task_id='bug-1', type='MAINTENANCE'), expected_revision=1)
        assert repo.get('bug-1').type == 'BUGFIX'
