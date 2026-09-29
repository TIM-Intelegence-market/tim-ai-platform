"""Issue #12 P1.1 contract: Task model, TaskState, defaults, validation, serialization."""
from dataclasses import fields
import json

import pytest

import src.task_engine as task_engine
from src.task_engine import Task, TaskState

STATES = ['NEW', 'PLANNED', 'READY', 'IN_PROGRESS', 'VERIFYING',
          'BLOCKED', 'SAFE_STOP', 'FIXED', 'FAILED']
FIELDS = ['task_id', 'parent_task_id', 'source', 'type', 'priority', 'risk', 'state',
          'title', 'objective', 'acceptance_criteria', 'required_evidence', 'dependencies',
          'timestamps', 'attempt_count', 'failure_reason', 'blocker_reason', 'next_action',
          'code_version', 'git_sha', 'config_hash']


def full_task(**changes):
    values = dict(
        task_id='task-1', parent_task_id='parent-1', source='issue-12', type='BUGFIX',
        priority='P1', risk='LOW', state=TaskState.READY, title='Fix gate',
        objective='Reject unhashed reports', acceptance_criteria=['gate rejects'],
        required_evidence=['root_cause', 'repair'], dependencies=['dep-1'],
        timestamps={'created_at': '2026-09-29T00:00:00+00:00'}, attempt_count=2,
        failure_reason=None, blocker_reason='waiting', next_action='run tests',
        code_version='1.0', git_sha='a' * 40, config_hash='b' * 64)
    values.update(changes)
    return Task(**values)


def test_public_api_is_task_and_taskstate_only():
    assert task_engine.__all__ == ['Task', 'TaskState']
    assert not hasattr(task_engine, 'TaskModel')
    assert not hasattr(task_engine, 'TaskStatus')


def test_taskstate_has_exactly_the_nine_contract_states():
    assert [s.name for s in TaskState] == STATES
    assert [s.value for s in TaskState] == STATES


@pytest.mark.parametrize('legacy', ['PENDING', 'RUN', 'RUNNING', 'COMPLETED', 'CANCELLED'])
def test_legacy_states_do_not_exist(legacy):
    assert legacy not in TaskState.__members__


def test_taskstate_matches_existing_bugfixer_states():
    from src.bugfixer.tasks import TaskState as BugfixerTaskState
    assert [s.value for s in TaskState] == [s.value for s in BugfixerTaskState]


def test_task_has_exactly_the_contract_fields():
    assert [f.name for f in fields(Task)] == FIELDS


def test_defaults():
    task = Task(task_id='t')
    assert task.state is TaskState.NEW
    assert task.attempt_count == 0
    assert task.parent_task_id is None
    assert (task.acceptance_criteria, task.required_evidence, task.dependencies, task.timestamps) == ([], [], [], {})
    for name in ('failure_reason', 'blocker_reason', 'next_action', 'code_version', 'git_sha', 'config_hash'):
        assert getattr(task, name) is None


def test_mutable_defaults_are_isolated():
    first, second = Task(task_id='a'), Task(task_id='b')
    first.acceptance_criteria.append('x')
    first.required_evidence.append('x')
    first.dependencies.append('x')
    first.timestamps['created_at'] = 'x'
    assert (second.acceptance_criteria, second.required_evidence, second.dependencies, second.timestamps) == ([], [], [], {})


@pytest.mark.parametrize('state', list(TaskState))
def test_every_state_is_accepted(state):
    assert Task(task_id='t', state=state).state is state


@pytest.mark.parametrize('state', ['READY', 'PENDING', 'RUNNING', None, 3])
def test_non_taskstate_state_is_rejected(state):
    with pytest.raises(ValueError):
        Task(task_id='t', state=state)


@pytest.mark.parametrize('task_id', ['', '   ', None, 7, 'x' * 129])
def test_invalid_task_id_is_rejected(task_id):
    with pytest.raises(ValueError):
        Task(task_id=task_id)


@pytest.mark.parametrize('parent', ['', 5, 't'])
def test_invalid_parent_is_rejected(parent):
    with pytest.raises(ValueError):
        Task(task_id='t', parent_task_id=parent)


@pytest.mark.parametrize('name,value', [
    ('acceptance_criteria', 'not a list'), ('acceptance_criteria', [1]),
    ('required_evidence', ('tuple',)), ('required_evidence', [None]),
    ('dependencies', 'dep'), ('dependencies', ['']),
    ('timestamps', []), ('timestamps', {'created_at': 1}),
    ('title', None), ('type', 3), ('next_action', 5),
])
def test_invalid_field_types_are_rejected(name, value):
    with pytest.raises(ValueError):
        Task(task_id='t', **{name: value})


@pytest.mark.parametrize('count', [-1, 1.0, True, '0'])
def test_invalid_attempt_count_is_rejected(count):
    with pytest.raises(ValueError):
        Task(task_id='t', attempt_count=count)


def test_to_dict_serializes_state_as_string_and_is_json_compatible():
    data = full_task().to_dict()
    assert list(data) == FIELDS
    assert data['state'] == 'READY' and type(data['state']) is str
    assert json.loads(json.dumps(data)) == data


def test_from_dict_restores_taskstate():
    task = Task.from_dict({'task_id': 't', 'state': 'READY'})
    assert task.state is TaskState.READY


def test_roundtrip_is_exact_and_deterministic():
    task = full_task()
    data = task.to_dict()
    assert Task.from_dict(data) == task
    assert Task.from_dict(data).to_dict() == data
    assert json.dumps(data, sort_keys=True) == json.dumps(Task.from_dict(data).to_dict(), sort_keys=True)


def test_serialization_does_not_share_containers():
    task = full_task()
    data = task.to_dict()
    data['dependencies'].append('leak')
    data['timestamps']['leak'] = 'x'
    assert task.dependencies == ['dep-1'] and 'leak' not in task.timestamps
    restored = Task.from_dict(data)
    data['acceptance_criteria'].append('leak')
    assert restored.acceptance_criteria == ['gate rejects']


@pytest.mark.parametrize('state', ['PENDING', 'RUNNING', 'UNKNOWN', 'ready', '', None, 1])
def test_from_dict_rejects_invalid_serialized_state(state):
    with pytest.raises(ValueError):
        Task.from_dict({'task_id': 't', 'state': state})


@pytest.mark.parametrize('data', [None, [], {'state': 'NEW'}, {'task_id': 't', 'status': 'NEW'}])
def test_from_dict_rejects_invalid_schema(data):
    with pytest.raises(ValueError):
        Task.from_dict(data)
