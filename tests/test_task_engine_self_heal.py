"""Issue #12 P1.14 contract: recurrence repaired from the engine's own known case."""
import sys

import pytest

from src.task_engine.repair_executor import create_disposable_workspace
from src.task_engine.repository import SqliteTaskRepository
from src.task_engine.self_heal import BUGFIX_EVIDENCE, find_known_case, self_heal
from src.task_engine.service import TaskEngine
from tests.task_engine_repair_fixture import FIXED, S, make_source, recipe

ROOT_CAUSE = 'add() subtracts instead of adding'
DETECTION = ('tests/test_calc.py', 'tests/test_other.py')


@pytest.fixture
def engine(tmp_path):
    with SqliteTaskRepository(tmp_path / 'store' / 'tasks.sqlite3') as repo:
        yield TaskEngine(repo)


def heal(engine, source, tmp_path, name, **kwargs):
    workspace = create_disposable_workspace(source, 'HEAD', sandbox_root=tmp_path)
    return self_heal(engine, workspace, python=sys.executable, detection_tests=DETECTION,
                     out_dir=tmp_path / name, forbidden_roots=[source], **kwargs)


def test_first_repair_then_recurrence_repaired_without_human_input(engine, tmp_path):
    source = make_source(tmp_path)
    first = heal(engine, source, tmp_path, 'run1', approved_recipe=recipe(source), root_cause=ROOT_CAUSE)
    assert first['outcome'] == 'FIXED' and first['known_case_task_id'] is None
    assert first['detection']['failing'] == ['tests.test_calc::test_add']
    assert find_known_case(engine, first['detection']['source'])[0].task_id == first['task_id']

    second = heal(engine, source, tmp_path, 'run2')  # no recipe, no root cause: engine memory only
    assert second['outcome'] == 'FIXED'
    assert second['known_case_task_id'] == first['task_id'] and second['task_id'] != first['task_id']
    assert second['detection']['fingerprint'] == first['detection']['fingerprint']
    task = engine.get_task(second['task_id'])
    assert task.state is S.FIXED and task.dependencies == [first['task_id']]
    assert set(BUGFIX_EVIDENCE) <= set(engine.evidence(task.task_id))
    assert engine.evidence(task.task_id)['root_cause'] == ROOT_CAUSE
    steps = [c['step_id'] for c in engine.checkpoints(task.task_id)]
    assert steps == ['detect', 'pre_repair_repro', 'engine_repair', 'post_repair_evidence']
    assert (source / 'calc.py').read_text() != FIXED  # the source repository still has the defect


def test_unknown_defect_is_blocked_never_improvised(engine, tmp_path):
    source = make_source(tmp_path)
    result = heal(engine, source, tmp_path, 'run')
    assert result['outcome'] == 'BLOCKED'
    task = engine.get_task(result['task_id'])
    assert task.state is S.BLOCKED and task.blocker_reason.startswith('UNKNOWN_DEFECT_NO_APPROVED_RECIPE')
    assert engine.checkpoints(task.task_id) == []


def test_healthy_workspace_creates_no_task(engine, tmp_path):
    source = make_source(tmp_path, FIXED)
    assert heal(engine, source, tmp_path, 'run')['outcome'] == 'NO_DEFECT'
    assert engine.tasks() == []


def test_held_task_is_not_auto_resumed_or_duplicated(engine, tmp_path):
    source = make_source(tmp_path)
    blocked = heal(engine, source, tmp_path, 'run1')
    again = heal(engine, source, tmp_path, 'run2', approved_recipe=recipe(source), root_cause=ROOT_CAUSE)
    assert again['outcome'] == 'HELD' and again['task_id'] == blocked['task_id']
    assert len(engine.tasks(type='BUGFIX')) == 1


def test_open_task_for_the_same_defect_is_resumed_not_duplicated(engine, tmp_path):
    source = make_source(tmp_path)
    first = heal(engine, source, tmp_path, 'probe')  # creates and blocks (no recipe yet)
    engine.transition_task(first['task_id'], S.READY)  # operator releases it
    resumed = heal(engine, source, tmp_path, 'run', approved_recipe=recipe(source), root_cause=ROOT_CAUSE)
    assert resumed['resumed'] is True and resumed['task_id'] == first['task_id']
    assert resumed['outcome'] == 'FIXED' and len(engine.tasks(type='BUGFIX')) == 1
