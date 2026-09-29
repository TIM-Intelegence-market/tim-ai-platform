"""Task Engine service surface (Issue #12, P1.8).

The stable interface for later phases (#13 onward). Callers never touch the
repository: every write goes through here, so dependency/parent gating and
the Fix-First gate are always applied, and every timestamp comes from one
injected clock. No incident, log, provider or remediation logic lives here;
an incident is linked to a task through ``source``.
"""
from datetime import datetime, timezone

from src.task_engine.fix_first import fix_first_guard
from src.task_engine.gating import reference_guard, transition_guard
from src.task_engine.handoff import resumable_tasks, session_handoff, snapshot
from src.task_engine.model import Task, TaskState
from src.task_engine.state_machine import InvalidTransition


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _state(value):
    if isinstance(value, TaskState):
        return value
    if isinstance(value, str) and value in TaskState.__members__:
        return TaskState(value)
    raise InvalidTransition(f'unknown task state: {value!r}')


class TaskEngine:
    def __init__(self, repository, *, clock=utc_now):
        self._repo = repository
        self._clock = clock

    # -- tasks -------------------------------------------------------------
    def create_task(self, task_id, *, type, title='', objective='', source='', parent_task_id=None,
                    priority='', risk='', acceptance_criteria=(), required_evidence=(), dependencies=(),
                    next_action=None, code_version=None, git_sha=None, config_hash=None):
        """Create a NEW task with no attempts; references are validated atomically."""
        now = self._clock()
        task = Task(task_id=task_id, parent_task_id=parent_task_id, source=source, type=type,
                    priority=priority, risk=risk, title=title, objective=objective,
                    acceptance_criteria=list(acceptance_criteria), required_evidence=list(required_evidence),
                    dependencies=list(dependencies), timestamps={'created_at': now, 'updated_at': now},
                    next_action=next_action, code_version=code_version, git_sha=git_sha,
                    config_hash=config_hash)
        self._repo.create(task, guard=reference_guard(self._repo))
        return task

    def get_task(self, task_id):
        return self._repo.get(task_id)

    def revision(self, task_id):
        return self._repo.revision(task_id)

    def tasks(self, *, state=None, type=None, parent_task_id=None, source=None):
        return self._repo.list(state=None if state is None else _state(state), type=type,
                               parent_task_id=parent_task_id, source=source)

    def history(self, task_id):
        return self._repo.history(task_id)

    # -- lifecycle ---------------------------------------------------------
    def transition_task(self, task_id, target, *, reason=None, expected_revision=None):
        gate, fix_first = transition_guard(self._repo), fix_first_guard(self._repo.evidence)

        def guard(current, to):
            gate(current, to)
            fix_first(current, to)

        return self._repo.transition(task_id, _state(target), at=self._clock(), reason=reason,
                                     expected_revision=expected_revision, guard=guard)

    def block(self, task_id, reason, *, expected_revision=None):
        return self.transition_task(task_id, TaskState.BLOCKED, reason=reason, expected_revision=expected_revision)

    def safe_stop(self, task_id, reason, *, expected_revision=None):
        return self.transition_task(task_id, TaskState.SAFE_STOP, reason=reason,
                                    expected_revision=expected_revision)

    # -- progress and evidence ---------------------------------------------
    def checkpoint(self, task_id, step_id, *, next_action, metadata=None):
        return self._repo.checkpoint(task_id, step_id, at=self._clock(), next_action=next_action,
                                     metadata=metadata)

    def checkpoints(self, task_id):
        return self._repo.checkpoints(task_id)

    def attach_evidence_ref(self, task_id, name, reference):
        self._repo.attach_evidence(task_id, name, reference, at=self._clock())

    def evidence(self, task_id):
        return self._repo.evidence(task_id)

    # -- resume ------------------------------------------------------------
    def resumable_work(self):
        """Live tasks in resume order (IN_PROGRESS, VERIFYING, READY, PLANNED, NEW)."""
        return resumable_tasks(self._repo)

    def handoff(self):
        return session_handoff(self._repo)

    def snapshot(self, task_id):
        return snapshot(self._repo, task_id)
