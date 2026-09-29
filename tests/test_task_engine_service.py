"""Issue #12 P1.8 contract: stable service surface with gates always applied."""
from itertools import count
from types import SimpleNamespace

import pytest

from src.task_engine import TaskState
from src.task_engine.fix_first import FixFirstRejected
from src.task_engine.gating import GateRejected
from src.task_engine.repository import SqliteTaskRepository, TaskNotFound
from src.task_engine.service import TaskEngine
from src.task_engine.state_machine import InvalidTransition
from tests.bugfixer.repair_fixture import evidence as synthetic_evidence

S = TaskState
SHA = 'a' * 40


def clock():
    ticks = count()
    return lambda: f'2026-09-29T11:{next(ticks):02d}:00+00:00'


@pytest.fixture
def engine(tmp_path):
    with SqliteTaskRepository(tmp_path / 'tasks.sqlite3') as repo:
        yield TaskEngine(repo, clock=clock())


def advance(engine, task_id, *targets):
    for target in targets:
        engine.transition_task(task_id, target)


def test_create_task_starts_new_with_clock_timestamps(engine):
    task = engine.create_task('t', type='BUGFIX', title='x', acceptance_criteria=['a'])
    assert task.state is S.NEW and task.attempt_count == 0
    assert task.timestamps == {'created_at': '2026-09-29T11:00:00+00:00', 'updated_at': '2026-09-29T11:00:00+00:00'}
    assert engine.get_task('t') == task and engine.revision('t') == 1


def test_create_task_validates_references(engine):
    with pytest.raises(GateRejected):
        engine.create_task('t', type='BUGFIX', dependencies=['ghost'])
    with pytest.raises(GateRejected):
        engine.create_task('t', type='BUGFIX', parent_task_id='ghost')
    assert engine.tasks() == []


def test_transition_accepts_state_names_and_rejects_unknown(engine):
    engine.create_task('t', type='BUGFIX')
    assert engine.transition_task('t', 'PLANNED').state is S.PLANNED
    for bad in ('RUNNING', 'planned', 3):
        with pytest.raises(InvalidTransition):
            engine.transition_task('t', bad)


def test_dependency_gating_is_always_applied(engine):
    engine.create_task('dep', type='INVESTIGATION')
    engine.create_task('t', type='BUGFIX', dependencies=['dep'])
    engine.transition_task('t', S.PLANNED)
    with pytest.raises(GateRejected):
        engine.transition_task('t', S.READY)


def test_fix_first_is_always_applied_and_evidence_refs_persist(engine, tmp_path):
    engine.create_task('bug', type='BUGFIX', git_sha=SHA)
    advance(engine, 'bug', S.PLANNED, S.READY, S.IN_PROGRESS, S.VERIFYING)
    engine.attach_evidence_ref('bug', 'root_cause', 'analysis says the hash check is missing')
    with pytest.raises(FixFirstRejected):
        engine.transition_task('bug', S.FIXED)
    assert engine.get_task('bug').state is S.VERIFYING
    task = engine.get_task('bug')
    refs = synthetic_evidence(tmp_path, SimpleNamespace(id='bug', attempt_count=task.attempt_count, git_sha=SHA))
    for name, reference in refs.items():
        engine.attach_evidence_ref('bug', name, reference)
    assert engine.evidence('bug') == refs
    assert engine.transition_task('bug', S.FIXED).state is S.FIXED
    with pytest.raises(ValueError):
        engine.attach_evidence_ref('bug', 'late', 'x')


def test_latest_evidence_reference_wins(engine):
    engine.create_task('t', type='BUGFIX')
    engine.attach_evidence_ref('t', 'root_cause', 'first guess')
    engine.attach_evidence_ref('t', 'root_cause', 'confirmed cause')
    assert engine.evidence('t') == {'root_cause': 'confirmed cause'}


@pytest.mark.parametrize('name,reference', [('', 'x'), ('n', object()), ('n', float('nan'))])
def test_invalid_evidence_reference_is_rejected(engine, name, reference):
    engine.create_task('t', type='BUGFIX')
    with pytest.raises(ValueError):
        engine.attach_evidence_ref('t', name, reference)
    assert engine.evidence('t') == {}


def test_block_and_safe_stop_require_reasons(engine):
    engine.create_task('t', type='BUGFIX')
    with pytest.raises(InvalidTransition):
        engine.block('t', '')
    assert engine.block('t', 'waiting for owner').blocker_reason == 'waiting for owner'
    stopped = engine.safe_stop('t', 'invariant violated')
    assert stopped.state is S.SAFE_STOP and stopped.blocker_reason == 'invariant violated'


def test_checkpoint_and_resumable_work(engine):
    engine.create_task('a', type='BUGFIX')
    engine.create_task('b', type='BUGFIX', next_action='start')
    advance(engine, 'b', S.PLANNED, S.READY, S.IN_PROGRESS)
    engine.checkpoint('b', 'reproduce', next_action='write failing test', metadata={'verification': 'REPRO_OK'})
    assert [t.task_id for t in engine.resumable_work()] == ['b', 'a']
    handoff = engine.handoff()
    assert handoff['current']['task_id'] == 'b'
    assert handoff['current']['next_action'] == 'write failing test'
    assert engine.snapshot('b')['completed_steps'] == ['reproduce']
    assert [c['step_id'] for c in engine.checkpoints('b')] == ['reproduce']


def test_incident_can_be_linked_through_source_without_storage_access(engine):
    """What #13 needs: create/find the task for an incident via the service only."""
    source = 'incident:3f2a9c'
    engine.create_task('bugfix-3f2a9c', type='BUGFIX', source=source, title='Evidence gate accepts bad hash')
    engine.create_task('other', type='BUGFIX', source='incident:other')
    linked = engine.tasks(source=source)
    assert [t.task_id for t in linked] == ['bugfix-3f2a9c']
    assert engine.tasks(source=source, state='NEW') == linked
    assert engine.history('bugfix-3f2a9c') == []


def test_unknown_task_is_reported(engine):
    with pytest.raises(TaskNotFound):
        engine.transition_task('ghost', S.PLANNED)


def test_set_code_version_rebinds_evidence_and_is_validated(engine, tmp_path):
    engine.create_task('bug', type='BUGFIX', git_sha=SHA)
    advance(engine, 'bug', S.PLANNED, S.READY, S.IN_PROGRESS, S.VERIFYING)
    task = engine.get_task('bug')
    for name, reference in synthetic_evidence(
            tmp_path, SimpleNamespace(id='bug', attempt_count=task.attempt_count, git_sha=SHA)).items():
        engine.attach_evidence_ref('bug', name, reference)
    updated = engine.set_code_version('bug', git_sha='b' * 40, code_version='after-repair')
    assert (updated.git_sha, updated.code_version) == ('b' * 40, 'after-repair')
    assert engine.get_task('bug') == updated and engine.revision('bug') == 6
    with pytest.raises(FixFirstRejected):  # reports bound to the old SHA no longer count
        engine.transition_task('bug', S.FIXED)
    for bad in ('abc', 'B' * 40, None):
        with pytest.raises(ValueError):
            engine.set_code_version('bug', git_sha=bad)


def test_stale_revision_is_rejected(engine):
    engine.create_task('t', type='BUGFIX')
    engine.transition_task('t', S.PLANNED, expected_revision=1)
    with pytest.raises(ValueError):
        engine.transition_task('t', S.READY, expected_revision=1)
