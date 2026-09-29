"""Issue #12 P1.6 contract: durable session handoff and cold-start resume."""
import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from src.task_engine import Task, TaskState
from src.task_engine.handoff import dumps, resumable_tasks, session_handoff, snapshot
from src.task_engine.repository import SqliteTaskRepository

S = TaskState
ROOT = Path(__file__).resolve().parents[1]
T = '2026-09-29T10:00:00+00:00'
SHA = 'c' * 40


@pytest.fixture
def repo(tmp_path):
    with SqliteTaskRepository(tmp_path / 'tasks.sqlite3') as repository:
        yield repository


def drive(repo, task_id, *targets, reason=None):
    for target in targets:
        repo.transition(task_id, target, at=T, reason=reason)


def test_snapshot_contains_the_full_resume_contract(repo):
    repo.create(Task(task_id='t', type='BUGFIX', git_sha=SHA, code_version='v1', config_hash='h' * 64,
                     next_action='step one'))
    drive(repo, 't', S.PLANNED, S.READY, S.IN_PROGRESS)
    repo.checkpoint('t', 'one', at=T, next_action='step two', metadata={'verification': 'TARGETED_PASS'})
    data = snapshot(repo, 't')
    assert data == {
        'snapshot_version': 1, 'task_id': 't', 'parent_task_id': None, 'type': 'BUGFIX',
        'state': 'IN_PROGRESS', 'attempt_count': 1,
        'last_completed_step': {'step_id': 'one', 'at': T, 'metadata': {'verification': 'TARGETED_PASS'}},
        'completed_steps': ['one'], 'next_action': 'step two', 'blockers': [],
        'code_version': 'v1', 'git_sha': SHA, 'config_hash': 'h' * 64,
        'verification': {'status': 'TARGETED_PASS', 'step_id': 'one', 'at': T},
    }
    assert json.loads(dumps(data)) == data


def test_snapshot_without_checkpoints_reports_not_recorded(repo):
    repo.create(Task(task_id='t'))
    data = snapshot(repo, 't')
    assert data['last_completed_step'] is None and data['completed_steps'] == []
    assert data['verification'] == {'status': 'NOT_RECORDED', 'step_id': None, 'at': None}


def test_snapshot_surfaces_own_and_dependency_blockers(repo):
    repo.create(Task(task_id='dep'))
    drive(repo, 'dep', S.FAILED, reason='could not reproduce')
    repo.create(Task(task_id='t', dependencies=['dep']))
    drive(repo, 't', S.PLANNED)
    assert snapshot(repo, 't')['blockers'] == [{'code': 'DEPENDENCY_FAILED', 'task_id': 'dep', 'state': 'FAILED'}]
    drive(repo, 't', S.BLOCKED, reason='waiting for dep')
    assert snapshot(repo, 't')['blockers'] == [
        {'code': 'TASK_BLOCKED', 'task_id': 't', 'state': 'BLOCKED', 'reason': 'waiting for dep'},
        {'code': 'DEPENDENCY_FAILED', 'task_id': 'dep', 'state': 'FAILED'}]


def test_resume_order_prefers_active_work_and_never_picks_held_tasks(repo):
    for task_id in ('a-new', 'b-planned', 'c-blocked', 'd-progress', 'e-failed', 'f-stop', 'g-fixed'):
        repo.create(Task(task_id=task_id))
    drive(repo, 'b-planned', S.PLANNED)
    drive(repo, 'c-blocked', S.BLOCKED, reason='r')
    drive(repo, 'd-progress', S.PLANNED, S.READY, S.IN_PROGRESS)
    drive(repo, 'e-failed', S.FAILED, reason='r')
    drive(repo, 'f-stop', S.SAFE_STOP, reason='r')
    drive(repo, 'g-fixed', S.PLANNED, S.READY, S.IN_PROGRESS, S.VERIFYING, S.FIXED)
    assert [t.task_id for t in resumable_tasks(repo)] == ['d-progress', 'b-planned', 'a-new']
    handoff = session_handoff(repo)
    assert handoff['current']['task_id'] == 'd-progress'
    assert handoff['held_task_ids'] == ['c-blocked', 'f-stop', 'e-failed']
    assert handoff['wip_violation'] is False


def test_more_than_one_active_task_is_flagged(repo):
    for task_id in ('x', 'y'):
        repo.create(Task(task_id=task_id))
        drive(repo, task_id, S.PLANNED, S.READY, S.IN_PROGRESS)
    handoff = session_handoff(repo)
    assert handoff['wip_violation'] is True and handoff['active_task_ids'] == ['x', 'y']


def test_empty_repository_has_no_current_task(repo):
    assert session_handoff(repo)['current'] is None


SESSION = textwrap.dedent('''
    import os, sys
    from pathlib import Path
    from src.task_engine import Task, TaskState as S
    from src.task_engine.checkpoints import Step, run_steps
    from src.task_engine.handoff import dumps, session_handoff
    from src.task_engine.repository import SqliteTaskRepository
    db, effects, mode = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    repo = SqliteTaskRepository(db)
    def action(name):
        def run():
            if mode == 'first' and name == 'three':
                os._exit(9)  # usage limit hit: no cleanup, no close
            with effects.open('a') as handle:
                handle.write(name + '\\n')
            return {'verification': name.upper() + '_DONE'}
        return run
    steps = [Step(n, 'step ' + n, action(n)) for n in ('one', 'two', 'three')]
    if mode == 'first':
        repo.create(Task(task_id='parent', type='MAINTENANCE'))
        repo.create(Task(task_id='bug', parent_task_id='parent', type='BUGFIX', git_sha='d' * 40,
                         next_action='step one'))
        for target in (S.PLANNED, S.READY, S.IN_PROGRESS):
            repo.transition('bug', target, at='2026-09-29T10:00:00+00:00')
        start = 1
    else:
        handoff = session_handoff(repo)
        print(dumps(handoff))
        start = 30
    ticks = iter(range(start, 60))
    current = 'bug' if mode == 'first' else handoff['current']['task_id']
    run_steps(repo, current, steps, now=lambda: f'2026-09-29T10:{next(ticks):02d}:00+00:00',
              final_next_action='move to VERIFYING')
    repo.close()
''')


def test_cold_start_resume_after_hard_session_loss(tmp_path):
    db, effects = tmp_path / 'tasks.sqlite3', tmp_path / 'effects.log'
    first = subprocess.run([sys.executable, '-c', SESSION, str(db), str(effects), 'first'], cwd=ROOT, timeout=60)
    assert first.returncode == 9
    assert effects.read_text().split() == ['one', 'two']

    second = subprocess.run([sys.executable, '-c', SESSION, str(db), str(effects), 'resume'],
                            cwd=ROOT, timeout=60, capture_output=True, text=True, check=True)
    handoff = json.loads(second.stdout)
    current = handoff['current']
    assert current['task_id'] == 'bug' and current['state'] == 'IN_PROGRESS'
    assert current['completed_steps'] == ['one', 'two']
    assert current['last_completed_step']['step_id'] == 'two'
    assert current['next_action'] == 'step three'
    assert current['git_sha'] == 'd' * 40 and current['attempt_count'] == 1
    assert current['verification']['status'] == 'TWO_DONE'
    assert current['blockers'] == [] and handoff['wip_violation'] is False
    assert effects.read_text().split() == ['one', 'two', 'three']

    with SqliteTaskRepository(db) as repo:
        final = snapshot(repo, 'bug')
        assert final['completed_steps'] == ['one', 'two', 'three']
        assert final['next_action'] == 'move to VERIFYING'
        assert final['attempt_count'] == 1
        assert dumps(session_handoff(repo)) == dumps(session_handoff(repo))
