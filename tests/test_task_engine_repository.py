"""Issue #12 P1.3 contract: durable task repository, reload and restart."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap

import pytest

from src.task_engine import Task, TaskState
from src.task_engine.repository import (
    CorruptTaskRecord, RevisionConflict, SqliteTaskRepository, TaskExists, TaskNotFound,
    TaskRepository)
from src.task_engine.state_machine import InvalidTransition

S = TaskState
ROOT = Path(__file__).resolve().parents[1]
T0 = '2026-09-29T10:00:00+00:00'
T1 = '2026-09-29T10:01:00+00:00'
T2 = '2026-09-29T10:02:00+00:00'


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / 'engine' / 'tasks.sqlite3'


@pytest.fixture
def repo(db_path):
    with SqliteTaskRepository(db_path) as repository:
        yield repository


def make(task_id='t1', **changes):
    values = dict(task_id=task_id, type='BUGFIX', title='title', objective='objective',
                  acceptance_criteria=['a'], required_evidence=['root_cause'], priority='P1', risk='LOW')
    values.update(changes)
    return Task(**values)


def test_sqlite_backend_implements_the_storage_contract(repo):
    assert isinstance(repo, TaskRepository)


def test_create_and_get_roundtrip(repo):
    task = make()
    assert repo.create(task) == 1
    assert repo.get('t1') == task
    assert repo.revision('t1') == 1


def test_duplicate_create_is_rejected_and_original_kept(repo):
    repo.create(make(title='original'))
    with pytest.raises(TaskExists):
        repo.create(make(title='replacement'))
    assert repo.get('t1').title == 'original'


def test_unknown_task_raises(repo):
    for call in (lambda: repo.get('nope'), lambda: repo.revision('nope'), lambda: repo.history('nope'),
                 lambda: repo.transition('nope', S.PLANNED, at=T0)):
        with pytest.raises(TaskNotFound):
            call()


def test_update_is_revision_checked(repo):
    repo.create(make())
    assert repo.update(make(title='v2'), expected_revision=1) == 2
    with pytest.raises(RevisionConflict):
        repo.update(make(title='stale'), expected_revision=1)
    assert repo.get('t1').title == 'v2'


def test_update_cannot_change_state_or_reduce_attempts(repo):
    repo.create(make(attempt_count=2))
    with pytest.raises(ValueError):
        repo.update(make(attempt_count=2, state=S.FIXED), expected_revision=1)
    with pytest.raises(ValueError):
        repo.update(make(attempt_count=0), expected_revision=1)
    assert repo.get('t1').state is S.NEW and repo.revision('t1') == 1


def test_transition_persists_state_and_history_atomically(repo):
    repo.create(make())
    repo.transition('t1', S.PLANNED, at=T0)
    repo.transition('t1', S.READY, at=T1)
    moved = repo.transition('t1', S.IN_PROGRESS, at=T2)
    assert repo.get('t1') == moved
    assert moved.state is S.IN_PROGRESS and moved.attempt_count == 1
    assert repo.revision('t1') == 4
    assert [(h['from_state'], h['to_state'], h['at']) for h in repo.history('t1')] == [
        ('NEW', 'PLANNED', T0), ('PLANNED', 'READY', T1), ('READY', 'IN_PROGRESS', T2)]


def test_illegal_transition_writes_nothing(repo):
    repo.create(make())
    with pytest.raises(InvalidTransition):
        repo.transition('t1', S.FIXED, at=T0)
    assert repo.get('t1').state is S.NEW and repo.revision('t1') == 1 and repo.history('t1') == []


def test_stale_transition_is_rejected(repo):
    repo.create(make())
    repo.transition('t1', S.PLANNED, at=T0, expected_revision=1)
    with pytest.raises(RevisionConflict):
        repo.transition('t1', S.READY, at=T1, expected_revision=1)
    assert repo.get('t1').state is S.PLANNED


def test_failure_inside_transition_rolls_back_task_write(repo):
    repo.create(make())
    repo.db.execute('DROP TABLE task_transitions')  # history insert will fail after the task write
    with pytest.raises(sqlite3.OperationalError):
        repo.transition('t1', S.PLANNED, at=T0)
    assert repo.get('t1').state is S.NEW and repo.revision('t1') == 1


def test_list_and_query_by_state_type_parent(repo):
    repo.create(make('p', type='MAINTENANCE'))
    repo.create(make('c1', parent_task_id='p'))
    repo.create(make('c2', parent_task_id='p', type='INVESTIGATION'))
    repo.create(make('x'))
    repo.transition('c1', S.PLANNED, at=T0)
    ids = lambda tasks: [t.task_id for t in tasks]
    assert ids(repo.list()) == ['c1', 'c2', 'p', 'x']
    assert ids(repo.list(state=S.NEW)) == ['c2', 'p', 'x']
    assert ids(repo.list(type='BUGFIX')) == ['c1', 'x']
    assert ids(repo.list(parent_task_id='p')) == ['c1', 'c2']
    assert ids(repo.list(parent_task_id='p', state=S.PLANNED, type='BUGFIX')) == ['c1']
    with pytest.raises(ValueError):
        repo.list(state='NEW')


def test_reload_after_close_restores_exact_state(db_path):
    with SqliteTaskRepository(db_path) as first:
        first.create(make())
        first.transition('t1', S.PLANNED, at=T0)
        first.transition('t1', S.BLOCKED, at=T1, reason='waiting for dep')
        expected, history = first.get('t1').to_dict(), first.history('t1')
    with SqliteTaskRepository(db_path) as second:
        assert second.get('t1').to_dict() == expected
        assert second.history('t1') == history
        assert second.revision('t1') == 3


def test_restart_in_separate_process_keeps_state(db_path):
    script = textwrap.dedent(f'''
        from src.task_engine import Task, TaskState
        from src.task_engine.repository import SqliteTaskRepository
        with SqliteTaskRepository({str(db_path)!r}) as repo:
            repo.create(Task(task_id='proc', type='BUGFIX'))
            repo.transition('proc', TaskState.PLANNED, at={T0!r})
            repo.transition('proc', TaskState.READY, at={T1!r})
            repo.transition('proc', TaskState.IN_PROGRESS, at={T2!r})
    ''')
    subprocess.run([sys.executable, '-c', script], cwd=ROOT, check=True, timeout=60)
    with SqliteTaskRepository(db_path) as repo:
        task = repo.get('proc')
        assert task.state is S.IN_PROGRESS and task.attempt_count == 1
        assert task.timestamps['in_progress_at'] == T2
        assert len(repo.history('proc')) == 3
        repo.transition('proc', S.VERIFYING, at=T2)
        assert repo.get('proc').state is S.VERIFYING


def test_foreign_database_is_rejected_without_modification(tmp_path):
    foreign = tmp_path / 'other.sqlite3'
    connection = sqlite3.connect(foreign)
    connection.execute('CREATE TABLE production(x)')
    connection.commit()
    connection.close()
    before = foreign.read_bytes()
    with pytest.raises(ValueError):
        SqliteTaskRepository(foreign)
    assert foreign.read_bytes() == before


def test_symlinked_store_is_rejected(tmp_path, db_path):
    SqliteTaskRepository(db_path).close()
    link = tmp_path / 'link.sqlite3'
    link.symlink_to(db_path)
    with pytest.raises(ValueError):
        SqliteTaskRepository(link)


def test_store_file_is_private(db_path):
    SqliteTaskRepository(db_path).close()
    assert os.stat(db_path).st_mode & 0o777 == 0o600


def test_tampered_record_is_detected(repo):
    repo.create(make())
    repo.db.execute("UPDATE tasks SET state='FIXED' WHERE task_id='t1'")
    with pytest.raises(CorruptTaskRecord):
        repo.get('t1')
    payload = json.dumps({'task_id': 't1', 'state': 'RUNNING'})
    repo.db.execute("UPDATE tasks SET state='NEW', payload=? WHERE task_id='t1'", (payload,))
    with pytest.raises(CorruptTaskRecord):
        repo.get('t1')
