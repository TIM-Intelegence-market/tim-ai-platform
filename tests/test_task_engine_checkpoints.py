"""Issue #12 P1.5 contract: next_action + checkpoints survive interruption without duplication."""
from itertools import count
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.task_engine import Task, TaskState
from src.task_engine.checkpoints import Step, completed_steps, resume_point, run_steps
from src.task_engine.repository import SqliteTaskRepository, TaskNotFound

S = TaskState
ROOT = Path(__file__).resolve().parents[1]
T0 = '2026-09-29T10:00:00+00:00'


def clock():
    ticks = count(1)
    return lambda: f'2026-09-29T10:{next(ticks):02d}:00+00:00'


def in_progress(repo, task_id='t'):
    repo.create(Task(task_id=task_id, type='BUGFIX', next_action='step one'))
    for target in (S.PLANNED, S.READY, S.IN_PROGRESS):
        repo.transition(task_id, target, at=T0)


class Crash(RuntimeError):
    pass


def steps(log, crash_at=None):
    def action(name):
        def run():
            if name == crash_at:
                raise Crash(name)
            log.append(name)
            return {'step': name}
        return run
    return [Step(name, f'step {name}', action(name)) for name in ('one', 'two', 'three')]


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / 'tasks.sqlite3'


def test_checkpoint_persists_next_action_atomically(db_path):
    with SqliteTaskRepository(db_path) as repo:
        in_progress(repo)
        revision = repo.revision('t')
        record = repo.checkpoint('t', 'one', at='2026-09-29T10:05:00+00:00', next_action='step two',
                                 metadata={'files': ['a.py'], 'tests': 'PASS'})
        assert record['step_id'] == 'one' and record['metadata'] == {'files': ['a.py'], 'tests': 'PASS'}
        task = repo.get('t')
        assert task.next_action == 'step two'
        assert task.timestamps['checkpoint_at'] == '2026-09-29T10:05:00+00:00'
        assert repo.revision('t') == revision + 1


def test_repeated_checkpoint_is_not_duplicated(db_path):
    with SqliteTaskRepository(db_path) as repo:
        in_progress(repo)
        first = repo.checkpoint('t', 'one', at='2026-09-29T10:05:00+00:00', next_action='step two')
        revision = repo.revision('t')
        again = repo.checkpoint('t', 'one', at='2026-09-29T10:09:00+00:00', next_action='other')
        assert again == first
        assert len(repo.checkpoints('t')) == 1
        assert repo.get('t').next_action == 'step two' and repo.revision('t') == revision


@pytest.mark.parametrize('kwargs', [
    {'step_id': '', 'next_action': 'x'}, {'step_id': 's', 'next_action': ''},
    {'step_id': 's', 'next_action': 'x', 'metadata': ['not', 'dict']},
    {'step_id': 's', 'next_action': 'x', 'at': '2026-09-29T09:00:00+00:00'},
])
def test_invalid_checkpoint_writes_nothing(db_path, kwargs):
    with SqliteTaskRepository(db_path) as repo:
        in_progress(repo)
        before = repo.get('t'), repo.revision('t')
        kwargs = {'at': '2026-09-29T10:05:00+00:00', **kwargs}
        with pytest.raises(ValueError):
            repo.checkpoint('t', kwargs.pop('step_id'), **kwargs)
        assert (repo.get('t'), repo.revision('t')) == before and repo.checkpoints('t') == []


def test_terminal_and_unknown_tasks_cannot_be_checkpointed(db_path):
    with SqliteTaskRepository(db_path) as repo:
        in_progress(repo)
        repo.transition('t', S.VERIFYING, at=T0)
        repo.transition('t', S.FIXED, at=T0)
        with pytest.raises(ValueError):
            repo.checkpoint('t', 'late', at=T0, next_action='x')
        with pytest.raises(TaskNotFound):
            repo.checkpoint('ghost', 'one', at=T0, next_action='x')


def test_interrupted_run_resumes_at_next_action_without_duplication(db_path):
    log = []
    with SqliteTaskRepository(db_path) as repo:
        in_progress(repo)
        with pytest.raises(Crash):
            run_steps(repo, 't', steps(log, crash_at='two'), now=clock(), final_next_action='verify')
        assert log == ['one']
        assert repo.get('t').next_action == 'step two'
    # New process-equivalent: fresh connection, no in-memory state carried over.
    with SqliteTaskRepository(db_path) as repo:
        assert resume_point(repo, 't', steps([])).step_id == 'two'
        executed = run_steps(repo, 't', steps(log), now=clock(), final_next_action='verify')
        assert executed == ['two', 'three']
        assert log == ['one', 'two', 'three']
        assert completed_steps(repo, 't') == ['one', 'two', 'three']
        assert repo.get('t').next_action == 'verify'
        assert run_steps(repo, 't', steps(log), now=clock(), final_next_action='verify') == []
        assert log == ['one', 'two', 'three']
        assert resume_point(repo, 't', steps([])) is None


def test_restart_in_separate_process_skips_completed_steps(db_path, tmp_path):
    marker = tmp_path / 'effects.log'
    script = textwrap.dedent(f'''
        import sys
        from pathlib import Path
        from src.task_engine.checkpoints import Step, run_steps
        from src.task_engine.repository import SqliteTaskRepository
        start, crash = int(sys.argv[1]), (sys.argv[2] if len(sys.argv) > 2 else None)
        marker = Path({str(marker)!r})
        def action(name):
            def run():
                if name == crash:
                    raise SystemExit(3)
                with marker.open('a') as handle:
                    handle.write(name + '\\n')
            return run
        steps = [Step(n, 'step ' + n, action(n)) for n in ('one', 'two', 'three')]
        ticks = iter(range(start, 60))
        with SqliteTaskRepository({str(db_path)!r}) as repo:
            run_steps(repo, 't', steps, now=lambda: f'2026-09-29T10:{{next(ticks)}}:00+00:00',
                      final_next_action='verify')
    ''')
    with SqliteTaskRepository(db_path) as repo:
        in_progress(repo)
    first = subprocess.run([sys.executable, '-c', script, '10', 'three'], cwd=ROOT, timeout=60)
    assert first.returncode == 3
    assert marker.read_text().split() == ['one', 'two']
    subprocess.run([sys.executable, '-c', script, '30'], cwd=ROOT, check=True, timeout=60)
    assert marker.read_text().split() == ['one', 'two', 'three']
    with SqliteTaskRepository(db_path) as repo:
        assert completed_steps(repo, 't') == ['one', 'two', 'three']
        assert repo.get('t').next_action == 'verify'


def test_steps_only_run_while_task_is_in_work_state(db_path):
    with SqliteTaskRepository(db_path) as repo:
        repo.create(Task(task_id='t'))
        with pytest.raises(ValueError):
            run_steps(repo, 't', steps([]), now=clock(), final_next_action='x')


def test_duplicate_step_ids_are_rejected(db_path):
    with SqliteTaskRepository(db_path) as repo:
        in_progress(repo)
        duplicated = steps([])[:1] * 2
        with pytest.raises(ValueError):
            run_steps(repo, 't', duplicated, now=clock(), final_next_action='x')
