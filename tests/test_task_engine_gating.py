"""Issue #12 P1.4 contract: dependency gating, parent/child completion, references."""
from dataclasses import replace

import pytest

from src.task_engine import Task, TaskState
from src.task_engine.gating import (
    Blocker, GateRejected, reference_guard, transition_blockers, transition_guard)
from src.task_engine.repository import SqliteTaskRepository
from src.task_engine.state_machine import InvalidTransition

S = TaskState
T = '2026-09-29T10:00:00+00:00'
PATH_TO = {
    S.PLANNED: [S.PLANNED], S.READY: [S.PLANNED, S.READY],
    S.IN_PROGRESS: [S.PLANNED, S.READY, S.IN_PROGRESS],
    S.VERIFYING: [S.PLANNED, S.READY, S.IN_PROGRESS, S.VERIFYING],
    S.FIXED: [S.PLANNED, S.READY, S.IN_PROGRESS, S.VERIFYING, S.FIXED],
}


@pytest.fixture
def repo(tmp_path):
    with SqliteTaskRepository(tmp_path / 'tasks.sqlite3') as repository:
        yield repository


def add(repo, task_id, **fields):
    repo.create(Task(task_id=task_id, **fields), guard=reference_guard(repo))


def move(repo, task_id, *targets, reason=None):
    for target in targets:
        repo.transition(task_id, target, at=T, reason=reason, guard=transition_guard(repo))


def drive(repo, task_id, state):
    """Bring a task to ``state`` through legal transitions."""
    escape = {S.BLOCKED: 'blocked', S.SAFE_STOP: 'stop', S.FAILED: 'failed'}
    if state in escape:
        move(repo, task_id, S.PLANNED)
        repo.transition(task_id, state, at=T, reason=escape[state])
    else:
        move(repo, task_id, *PATH_TO.get(state, []))


def test_dependent_task_cannot_become_ready_until_dependency_fixed(repo):
    add(repo, 'dep')
    add(repo, 'task', dependencies=['dep'])
    move(repo, 'task', S.PLANNED)
    with pytest.raises(GateRejected) as rejected:
        move(repo, 'task', S.READY)
    assert rejected.value.blockers == [Blocker('DEPENDENCY_INCOMPLETE', 'dep', 'NEW')]
    assert repo.get('task').state is S.PLANNED and len(repo.history('task')) == 1
    drive(repo, 'dep', S.FIXED)
    move(repo, 'task', S.READY)
    assert repo.get('task').state is S.READY


@pytest.mark.parametrize('state,code', [
    (S.NEW, 'DEPENDENCY_INCOMPLETE'), (S.PLANNED, 'DEPENDENCY_INCOMPLETE'),
    (S.READY, 'DEPENDENCY_INCOMPLETE'), (S.IN_PROGRESS, 'DEPENDENCY_INCOMPLETE'),
    (S.VERIFYING, 'DEPENDENCY_INCOMPLETE'), (S.BLOCKED, 'DEPENDENCY_BLOCKED'),
    (S.SAFE_STOP, 'DEPENDENCY_SAFE_STOP'), (S.FAILED, 'DEPENDENCY_FAILED'),
])
def test_unfinished_dependency_yields_machine_readable_blocker(repo, state, code):
    add(repo, 'dep')
    drive(repo, 'dep', state)
    add(repo, 'task', dependencies=['dep'])
    move(repo, 'task', S.PLANNED)
    with pytest.raises(GateRejected) as rejected:
        move(repo, 'task', S.READY)
    assert [b.to_dict() for b in rejected.value.blockers] == [
        {'code': code, 'task_id': 'dep', 'state': state.value}]
    assert isinstance(rejected.value, InvalidTransition)


def test_all_unfinished_dependencies_are_reported(repo):
    add(repo, 'a')
    add(repo, 'b')
    drive(repo, 'b', S.FAILED)
    add(repo, 'c')
    drive(repo, 'c', S.FIXED)
    add(repo, 'task', dependencies=['a', 'b', 'c'])
    blockers = transition_blockers(repo, repo.get('task'), S.READY)
    assert [(b.code, b.task_id) for b in blockers] == [('DEPENDENCY_INCOMPLETE', 'a'), ('DEPENDENCY_FAILED', 'b')]


@pytest.mark.parametrize('target', [S.PLANNED, S.BLOCKED, S.SAFE_STOP, S.FAILED])
def test_non_progress_moves_are_not_dependency_gated(repo, target):
    add(repo, 'dep')
    add(repo, 'task', dependencies=['dep'])
    repo.transition('task', target, at=T, reason='r', guard=transition_guard(repo))
    assert repo.get('task').state is target


def test_parent_cannot_be_fixed_while_child_unfinished(repo):
    add(repo, 'parent', type='MAINTENANCE')
    add(repo, 'child', parent_task_id='parent', type='BUGFIX')
    move(repo, 'parent', S.PLANNED, S.READY, S.IN_PROGRESS, S.VERIFYING)
    with pytest.raises(GateRejected) as rejected:
        move(repo, 'parent', S.FIXED)
    assert rejected.value.blockers == [Blocker('CHILD_INCOMPLETE', 'child', 'NEW')]
    assert repo.get('parent').state is S.VERIFYING
    drive(repo, 'child', S.FIXED)
    move(repo, 'parent', S.FIXED)
    assert repo.get('parent').state is S.FIXED


def test_failed_child_is_not_hidden_by_parent_completion(repo):
    add(repo, 'parent')
    add(repo, 'ok', parent_task_id='parent')
    add(repo, 'bad', parent_task_id='parent')
    drive(repo, 'ok', S.FIXED)
    drive(repo, 'bad', S.FAILED)
    drive(repo, 'parent', S.VERIFYING)
    with pytest.raises(GateRejected) as rejected:
        move(repo, 'parent', S.FIXED)
    assert rejected.value.blockers == [Blocker('CHILD_FAILED', 'bad', 'FAILED')]


def test_child_cannot_be_attached_to_fixed_parent(repo):
    add(repo, 'parent')
    drive(repo, 'parent', S.FIXED)
    with pytest.raises(GateRejected) as rejected:
        add(repo, 'late', parent_task_id='parent')
    assert rejected.value.blockers[0].code == 'PARENT_FIXED'
    assert repo.list(parent_task_id='parent') == []


@pytest.mark.parametrize('fields,code', [
    ({'dependencies': ['ghost']}, 'DEPENDENCY_MISSING'),
    ({'parent_task_id': 'ghost'}, 'PARENT_MISSING'),
    ({'dependencies': ['t']}, 'DEPENDENCY_SELF'),
    ({'dependencies': ['d', 'd']}, 'DEPENDENCY_DUPLICATE'),
])
def test_invalid_references_are_rejected_on_create(repo, fields, code):
    add(repo, 'd')
    with pytest.raises(GateRejected) as rejected:
        add(repo, 't', **fields)
    assert code in [b.code for b in rejected.value.blockers]
    assert [t.task_id for t in repo.list()] == ['d']


def test_dependency_cycle_is_rejected_on_update(repo):
    add(repo, 'a')
    add(repo, 'b', dependencies=['a'])
    add(repo, 'c', dependencies=['b'])
    a = repo.get('a')
    with pytest.raises(GateRejected) as rejected:
        repo.update(replace(a, dependencies=['c']), expected_revision=1, guard=reference_guard(repo))
    assert 'DEPENDENCY_CYCLE' in [b.code for b in rejected.value.blockers]
    assert repo.get('a').dependencies == [] and repo.revision('a') == 1


def test_parent_cycle_is_rejected_on_update(repo):
    add(repo, 'root')
    add(repo, 'mid', parent_task_id='root')
    root = repo.get('root')
    with pytest.raises(GateRejected) as rejected:
        repo.update(replace(root, parent_task_id='mid'), expected_revision=1, guard=reference_guard(repo))
    assert 'PARENT_CYCLE' in [b.code for b in rejected.value.blockers]


def test_unfinished_dependency_cannot_be_added_to_task_in_progress(repo):
    add(repo, 'task')
    drive(repo, 'task', S.IN_PROGRESS)
    add(repo, 'new-dep')
    with pytest.raises(GateRejected) as rejected:
        repo.update(replace(repo.get('task'), dependencies=['new-dep']),
                    expected_revision=repo.revision('task'), guard=reference_guard(repo))
    assert rejected.value.blockers == [Blocker('DEPENDENCY_INCOMPLETE', 'new-dep', 'NEW')]


def test_blockers_survive_reload(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    with SqliteTaskRepository(path) as repo:
        add(repo, 'dep')
        drive(repo, 'dep', S.SAFE_STOP)
        add(repo, 'task', dependencies=['dep'])
    with SqliteTaskRepository(path) as repo:
        blockers = transition_blockers(repo, repo.get('task'), S.READY)
        assert blockers == [Blocker('DEPENDENCY_SAFE_STOP', 'dep', 'SAFE_STOP')]
