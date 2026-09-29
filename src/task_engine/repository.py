"""Persistent task repository (Issue #12, P1.3).

Dedicated SQLite file per engine, following src/bugfixer/store.py: own
application_id, versioned schema, synchronous=FULL, BEGIN IMMEDIATE
transactions. There is no default path, so callers always name the file;
tests use temporary directories and never the production database.

State only changes through transition(), which applies the P1.2 state
machine and appends history in the same transaction as the task write.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import sqlite3

from src.task_engine.model import Task, TaskState
from src.task_engine.state_machine import _instant, transition as apply_transition

APP_ID = 0x54494D54  # 'TIMT'
SCHEMA_VERSION = 1

_SCHEMA = '''
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY, parent_task_id TEXT, type TEXT NOT NULL,
    state TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS tasks_state ON tasks(state);
CREATE INDEX IF NOT EXISTS tasks_type ON tasks(type);
CREATE INDEX IF NOT EXISTS tasks_parent ON tasks(parent_task_id);
CREATE TABLE IF NOT EXISTS task_transitions (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
    from_state TEXT NOT NULL, to_state TEXT NOT NULL, at TEXT NOT NULL,
    reason TEXT, attempt_count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS task_checkpoints (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, step_id TEXT NOT NULL,
    at TEXT NOT NULL, next_action TEXT NOT NULL, metadata TEXT NOT NULL,
    UNIQUE(task_id, step_id));
'''


class TaskNotFound(KeyError):
    pass


class TaskExists(ValueError):
    pass


class RevisionConflict(ValueError):
    """The caller's view of the task is stale; nothing was written."""


class CorruptTaskRecord(RuntimeError):
    pass


class TaskRepository(ABC):
    """Storage contract later phases depend on; backends stay interchangeable."""

    @abstractmethod
    def create(self, task: Task, *, guard=None) -> int: ...

    @abstractmethod
    def get(self, task_id: str) -> Task: ...

    @abstractmethod
    def revision(self, task_id: str) -> int: ...

    @abstractmethod
    def update(self, task: Task, *, expected_revision: int, guard=None) -> int: ...

    @abstractmethod
    def transition(self, task_id: str, target: TaskState, *, at: str, reason: str | None = None,
                   expected_revision: int | None = None, guard=None) -> Task: ...

    @abstractmethod
    def list(self, *, state: TaskState | None = None, type: str | None = None,
             parent_task_id: str | None = None) -> list[Task]: ...

    @abstractmethod
    def history(self, task_id: str) -> list[dict]: ...

    @abstractmethod
    def checkpoint(self, task_id: str, step_id: str, *, at: str, next_action: str,
                   metadata: dict | None = None) -> dict: ...

    @abstractmethod
    def checkpoints(self, task_id: str) -> list[dict]: ...


def _payload(task):
    return json.dumps(task.to_dict(), sort_keys=True, separators=(',', ':'))


class SqliteTaskRepository(TaskRepository):
    def __init__(self, path):
        path = Path(path)
        if path.is_symlink():
            raise ValueError('task store symlinks are forbidden')
        if path.exists() and path.stat().st_size:
            probe = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                if probe.execute('PRAGMA application_id').fetchone()[0] != APP_ID:
                    raise ValueError('not a task engine database')
                if probe.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                    raise ValueError('unsupported task engine schema')
            finally:
                probe.close()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path.resolve()
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript(f'''
            BEGIN IMMEDIATE;
            PRAGMA application_id={APP_ID};
            PRAGMA user_version={SCHEMA_VERSION};
            {_SCHEMA}
            COMMIT;
        ''')
        self.path.chmod(0o600)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @contextmanager
    def _transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def _row(self, task_id):
        row = self.db.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        if row is None:
            raise TaskNotFound(task_id)
        return row

    @staticmethod
    def _decode(row):
        try:
            task = Task.from_dict(json.loads(row['payload']))
        except (ValueError, TypeError) as error:
            raise CorruptTaskRecord(f'unreadable task record {row["task_id"]!r}') from error
        if (task.task_id, task.parent_task_id, task.type, task.state.value) != (
                row['task_id'], row['parent_task_id'], row['type'], row['state']):
            raise CorruptTaskRecord(f'task record {row["task_id"]!r} disagrees with its index columns')
        return task

    def create(self, task, *, guard=None):
        if not isinstance(task, Task):
            raise TypeError('task must be a Task')
        with self._transaction():
            if self.db.execute('SELECT 1 FROM tasks WHERE task_id=?', (task.task_id,)).fetchone():
                raise TaskExists(task.task_id)
            if guard is not None:
                guard(task)
            self.db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?)',
                            (task.task_id, task.parent_task_id, task.type, task.state.value, 1, _payload(task)))
        return 1

    def get(self, task_id):
        return self._decode(self._row(task_id))

    def revision(self, task_id):
        return self._row(task_id)['revision']

    def _write(self, task, revision):
        self.db.execute('UPDATE tasks SET parent_task_id=?,type=?,state=?,revision=?,payload=? WHERE task_id=?',
                        (task.parent_task_id, task.type, task.state.value, revision + 1, _payload(task), task.task_id))
        return revision + 1

    def update(self, task, *, expected_revision, guard=None):
        """Replace non-state fields; state changes must go through transition()."""
        if not isinstance(task, Task):
            raise TypeError('task must be a Task')
        with self._transaction():
            row = self._row(task.task_id)
            if row['revision'] != expected_revision:
                raise RevisionConflict(task.task_id)
            current = self._decode(row)
            if task.state is not current.state:
                raise ValueError('update cannot change state; use transition()')
            if task.attempt_count < current.attempt_count:
                raise ValueError('attempt_count cannot be reduced')
            if guard is not None:
                guard(task)
            return self._write(task, row['revision'])

    def transition(self, task_id, target, *, at, reason=None, expected_revision=None, guard=None):
        """Apply the state machine; ``guard(current, target)`` may veto inside the transaction."""
        with self._transaction():
            row = self._row(task_id)
            if expected_revision is not None and row['revision'] != expected_revision:
                raise RevisionConflict(task_id)
            current = self._decode(row)
            moved = apply_transition(current, target, at=at, reason=reason)
            if guard is not None:
                guard(current, target)
            self._write(moved, row['revision'])
            self.db.execute('INSERT INTO task_transitions(task_id,from_state,to_state,at,reason,attempt_count) '
                            'VALUES (?,?,?,?,?,?)',
                            (task_id, current.state.value, moved.state.value, at, reason, moved.attempt_count))
        return moved

    def list(self, *, state=None, type=None, parent_task_id=None):
        clauses, params = [], []
        if state is not None:
            if not isinstance(state, TaskState):
                raise ValueError('state filter must be a TaskState')
            clauses.append('state=?')
            params.append(state.value)
        if type is not None:
            clauses.append('type=?')
            params.append(type)
        if parent_task_id is not None:
            clauses.append('parent_task_id=?')
            params.append(parent_task_id)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        rows = self.db.execute(f'SELECT * FROM tasks{where} ORDER BY task_id', params).fetchall()
        return [self._decode(row) for row in rows]

    def history(self, task_id):
        self._row(task_id)
        return [dict(row) for row in self.db.execute(
            'SELECT sequence,task_id,from_state,to_state,at,reason,attempt_count FROM task_transitions '
            'WHERE task_id=? ORDER BY sequence', (task_id,))]

    @staticmethod
    def _checkpoint(row):
        result = dict(row)
        result['metadata'] = json.loads(result['metadata'])
        return result

    def checkpoint(self, task_id, step_id, *, at, next_action, metadata=None):
        """Record a completed atomic step and the next action in one transaction.

        Recording an already completed step is a no-op that returns the original
        checkpoint, so a resumed run cannot duplicate it.
        """
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError('step_id must be a non-empty string')
        if not isinstance(next_action, str) or not next_action.strip():
            raise ValueError('next_action must be a non-empty string')
        metadata = {} if metadata is None else metadata
        if not isinstance(metadata, dict):
            raise ValueError('checkpoint metadata must be a dict')
        encoded = json.dumps(metadata, sort_keys=True, separators=(',', ':'))
        with self._transaction():
            row = self._row(task_id)
            existing = self.db.execute('SELECT * FROM task_checkpoints WHERE task_id=? AND step_id=?',
                                       (task_id, step_id)).fetchone()
            if existing is not None:
                return self._checkpoint(existing)
            current = self._decode(row)
            if current.state is TaskState.FIXED:
                raise ValueError('cannot checkpoint a terminal task')
            previous = current.timestamps.get('updated_at')
            if _instant(at) < _instant(previous or at):
                raise ValueError('checkpoint time precedes the last update')
            timestamps = dict(current.timestamps, updated_at=at, checkpoint_at=at)
            self._write(replace(current, next_action=next_action, timestamps=timestamps), row['revision'])
            self.db.execute('INSERT INTO task_checkpoints(task_id,step_id,at,next_action,metadata) '
                            'VALUES (?,?,?,?,?)', (task_id, step_id, at, next_action, encoded))
            return self._checkpoint(self.db.execute(
                'SELECT * FROM task_checkpoints WHERE task_id=? AND step_id=?', (task_id, step_id)).fetchone())

    def checkpoints(self, task_id):
        self._row(task_id)
        return [self._checkpoint(row) for row in self.db.execute(
            'SELECT * FROM task_checkpoints WHERE task_id=? ORDER BY sequence', (task_id,))]
