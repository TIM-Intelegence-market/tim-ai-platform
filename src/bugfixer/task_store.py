"""Task storage in the observer's existing SQLite transaction boundary."""
from dataclasses import replace
import json

from .model import State
from .tasks import Task, TaskState, utc_now, validate_fix_evidence, validate_task_transition
from .processing import redact_text


TASK_SCHEMA = '''
CREATE TABLE IF NOT EXISTS repair_tasks (
    id TEXT PRIMARY KEY, incident_id TEXT, state TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS repair_tasks_incident ON repair_tasks(incident_id);
CREATE TABLE IF NOT EXISTS task_history (
    sequence INTEGER PRIMARY KEY, task_id TEXT NOT NULL,
    from_state TEXT NOT NULL, to_state TEXT NOT NULL, reason TEXT NOT NULL,
    timestamp TEXT NOT NULL, attempt_count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS incident_repair (
    incident_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, code_version TEXT NOT NULL,
    root_cause TEXT NOT NULL DEFAULT '', remediation TEXT NOT NULL DEFAULT '',
    verification_result TEXT NOT NULL DEFAULT 'NOT_VERIFIED',
    recurrence_state TEXT NOT NULL DEFAULT 'NOT_VERIFIED');
'''


class TaskStoreMixin:
    def _initialize_task_links(self):
        # v1 observer records survive unchanged, including their original history.
        # Legacy RESOLVED rows get an explicitly unverified task for review.
        for row in self.db.execute('SELECT id,state,category FROM incidents').fetchall():
            if self.db.execute('SELECT 1 FROM incident_repair WHERE incident_id=?', (row['id'],)).fetchone() is None:
                self._ensure_incident_task(dict(row), legacy=True)

    def _ensure_incident_task(self, incident, *, legacy=False, recurrence=False):
        identity = incident['id']
        link = self.db.execute('SELECT * FROM incident_repair WHERE incident_id=?', (identity,)).fetchone()
        if link and not recurrence:
            return link['task_id']
        critical = incident['category'] in {'INVARIANT_VIOLATION', 'TERMINAL_BLOCKED'}
        stopped = critical or incident['category'] == 'UNKNOWN'
        blocked = incident['category'] == 'UNKNOWN' or (legacy and incident['state'] == 'RESOLVED')
        task = Task(incident_id=identity, parent_task=link['task_id'] if link else None,
                    priority='P0' if critical else 'P2', risk='CRITICAL' if critical else 'MEDIUM',
                    state=TaskState.SAFE_STOP if stopped else TaskState.BLOCKED if blocked else TaskState.NEW,
                    blocker_reason='Unknown or critical incident: SAFE_STOP and escalate' if stopped else
                                   'Evidence review required; no proven repair' if blocked else '',
                    git_sha=self.code_version)
        self._insert_task(task)
        self.db.execute('''INSERT INTO incident_repair(incident_id,task_id,code_version,recurrence_state)
            VALUES(?,?,?,?) ON CONFLICT(incident_id) DO UPDATE SET task_id=excluded.task_id,
            recurrence_state=excluded.recurrence_state,verification_result='NOT_VERIFIED' ''',
            (identity, task.id, self.code_version, 'RECURRED' if recurrence else 'LEGACY_UNVERIFIED' if legacy else 'NOT_VERIFIED'))
        return task.id

    def _insert_task(self, task):
        self._require_transaction()
        safe = task.safe_dict()
        Task.from_dict(safe)
        self.db.execute('INSERT INTO repair_tasks VALUES(?,?,?,?)',
                        (task.id, task.incident_id, task.state, json.dumps(safe, sort_keys=True)))
        self.db.execute('INSERT INTO task_history(task_id,from_state,to_state,reason,timestamp,attempt_count) VALUES(?,?,?,?,?,?)',
                        (task.id, '', task.state, 'Task created; no remediation executed', task.created_at, task.attempt_count))

    def create_task(self, task: Task):
        self._require_transaction()
        if task.state != TaskState.NEW or task.attempt_count or task.completion_evidence:
            raise ValueError('new tasks must begin without attempts or completion claims')
        if task.incident_id is not None:
            raise ValueError('incident tasks are created atomically by record')
        if task.parent_task:
            self.task(task.parent_task)
        for identity in task.dependencies:
            self.task(identity)
        self._insert_task(task)
        return task.id

    def task(self, identity):
        row = self.db.execute('SELECT payload FROM repair_tasks WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('unknown task')
        return Task.from_dict(json.loads(row[0]))

    def task_for_incident(self, identity):
        row = self.db.execute('SELECT task_id FROM incident_repair WHERE incident_id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('incident task missing')
        return self.task(row[0])

    def resume_tasks(self, limit=100):
        """Read-only resume: preserve state, attempts, evidence and next action."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('invalid task limit')
        return [Task.from_dict(json.loads(row[0])) for row in self.db.execute(
            "SELECT payload FROM repair_tasks WHERE state NOT IN ('FIXED','FAILED') ORDER BY id LIMIT ?", (limit,))]

    def plan_task(self, identity, *, dependencies=None, acceptance_criteria=None, next_action=None, git_sha=None):
        self._require_transaction()
        task = self.task(identity)
        if task.state not in {TaskState.NEW, TaskState.PLANNED, TaskState.BLOCKED}:
            raise ValueError('task cannot be replanned while active or complete')
        changes = {'updated_at': utc_now()}
        for key, value in (('dependencies', dependencies), ('acceptance_criteria', acceptance_criteria),
                           ('next_action', next_action), ('git_sha', git_sha)):
            if value is not None:
                changes[key] = tuple(value) if key in {'dependencies', 'acceptance_criteria'} else value
        candidate = replace(task, **changes)
        for dependency in candidate.dependencies:
            pending, seen = [dependency], set()
            while pending:
                current = pending.pop()
                if current == identity:
                    raise ValueError('cyclic task dependency')
                if current not in seen:
                    seen.add(current)
                    pending.extend(self.task(current).dependencies)
        self._write_task(candidate)
        return candidate

    def _write_task(self, task):
        safe = task.safe_dict()
        Task.from_dict(safe)
        self.db.execute('UPDATE repair_tasks SET state=?,payload=? WHERE id=?',
                        (task.state, json.dumps(safe, sort_keys=True), task.id))

    def transition_task(self, identity, target, *, reason, next_action, evidence=None):
        self._require_transaction()
        task = self.task(identity)
        target = validate_task_transition(task.state, target)
        if not isinstance(reason, str) or not reason.strip() or not isinstance(next_action, str) or not next_action.strip():
            raise ValueError('transition reason and exact next action required')
        if target in {TaskState.READY, TaskState.IN_PROGRESS, TaskState.FIXED}:
            if any(self.task(item).state != TaskState.FIXED for item in task.dependencies):
                raise ValueError('unmet task dependencies')
        if target == TaskState.FIXED:
            if task.risk == 'CRITICAL':
                raise ValueError('A4 requires safe escalation, no automatic completion')
            if task.incident_id and self.inspect(task.incident_id)['state'] == State.SAFE_STOP:
                raise ValueError('incident invariant remains stopped')
            validate_fix_evidence(task, evidence)
        now = utc_now()
        updated = replace(task, state=target, updated_at=now, next_action=next_action,
                          attempt_count=task.attempt_count + (target == TaskState.IN_PROGRESS),
                          started_at=now if target == TaskState.IN_PROGRESS else task.started_at,
                          completed_at=now if target == TaskState.FIXED else None,
                          failure_reason=reason if target == TaskState.FAILED else task.failure_reason,
                          blocker_reason=reason if target in {TaskState.BLOCKED, TaskState.SAFE_STOP} else '',
                          completion_evidence=evidence if target == TaskState.FIXED else {})
        self._write_task(updated)
        self.db.execute('INSERT INTO task_history(task_id,from_state,to_state,reason,timestamp,attempt_count) VALUES(?,?,?,?,?,?)',
                        (identity, task.state, target, redact_text(reason), now, updated.attempt_count))
        if task.incident_id:
            incident = self.inspect(task.incident_id)
            if target == TaskState.IN_PROGRESS and incident['state'] in {State.CLASSIFIED, State.ESCALATED}:
                self.transition(task.incident_id, State.INVESTIGATING, 'Repair task investigation started')
            if target == TaskState.FIXED:
                for step in (State.INVESTIGATING, State.REPRODUCED, State.ROOT_CAUSE_FOUND,
                             State.FIX_PROPOSED, State.FIX_TESTING, State.RESOLVED):
                    current = State(self.inspect(task.incident_id)['state'])
                    if list(State).index(current) < list(State).index(step):
                        self.transition(task.incident_id, step, 'Content-bound repair verification: task ' + task.id)
                self.db.execute('''UPDATE incident_repair SET root_cause=?,remediation=?,
                    verification_result='PASS',recurrence_state='PROTECTED',code_version=? WHERE incident_id=?''',
                    (redact_text(evidence['root_cause']), json.dumps(updated.safe_dict()['completion_evidence']['repair'], sort_keys=True),
                     task.git_sha, task.incident_id))
        return self.task(identity)
