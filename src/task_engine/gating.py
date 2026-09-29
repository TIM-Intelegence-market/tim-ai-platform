"""Dependency and parent/child gating (Issue #12, P1.4).

Rules, evaluated inside the repository transaction through its guard hook:
- a task cannot make forward progress (READY and beyond) until every
  dependency is FIXED;
- a parent cannot become FIXED while any child is not FIXED;
- references must exist, must not point at the task itself, must not form a
  dependency cycle, and no child may be attached to a FIXED parent.

Every rejection carries machine-readable Blocker records.
"""
from dataclasses import asdict, dataclass

from src.task_engine.model import TaskState
from src.task_engine.repository import TaskNotFound
from src.task_engine.state_machine import InvalidTransition

S = TaskState
PROGRESS_STATES = frozenset({S.READY, S.IN_PROGRESS, S.VERIFYING, S.FIXED})
_STATE_CODES = {S.BLOCKED: 'BLOCKED', S.SAFE_STOP: 'SAFE_STOP', S.FAILED: 'FAILED'}


@dataclass(frozen=True)
class Blocker:
    code: str
    task_id: str
    state: str | None = None

    def to_dict(self):
        return asdict(self)


class GateRejected(InvalidTransition):
    def __init__(self, message, blockers):
        super().__init__(f'{message}: ' + ', '.join(f'{b.code}({b.task_id})' for b in blockers))
        self.blockers = list(blockers)


def _state_blocker(prefix, task):
    return Blocker(f'{prefix}_{_STATE_CODES.get(task.state, "INCOMPLETE")}', task.task_id, task.state.value)


def dependency_blockers(repo, task):
    blockers = []
    for identity in task.dependencies:
        try:
            dependency = repo.get(identity)
        except TaskNotFound:
            blockers.append(Blocker('DEPENDENCY_MISSING', identity))
            continue
        if dependency.state is not S.FIXED:
            blockers.append(_state_blocker('DEPENDENCY', dependency))
    return blockers


def child_blockers(repo, task):
    return [_state_blocker('CHILD', child) for child in repo.list(parent_task_id=task.task_id)
            if child.state is not S.FIXED]


def transition_blockers(repo, task, target):
    blockers = []
    if target in PROGRESS_STATES:
        blockers += dependency_blockers(repo, task)
    if target is S.FIXED:
        blockers += child_blockers(repo, task)
    return blockers


def reference_blockers(repo, task):
    blockers = []
    if task.task_id in task.dependencies:
        blockers.append(Blocker('DEPENDENCY_SELF', task.task_id))
    if len(set(task.dependencies)) != len(task.dependencies):
        blockers.append(Blocker('DEPENDENCY_DUPLICATE', task.task_id))
    if task.parent_task_id is not None:
        try:
            parent = repo.get(task.parent_task_id)
        except TaskNotFound:
            blockers.append(Blocker('PARENT_MISSING', task.parent_task_id))
        else:
            if parent.state is S.FIXED:
                blockers.append(Blocker('PARENT_FIXED', parent.task_id, parent.state.value))
            ancestor, seen = parent, {task.task_id}
            while ancestor is not None:
                if ancestor.task_id in seen:
                    blockers.append(Blocker('PARENT_CYCLE', ancestor.task_id))
                    break
                seen.add(ancestor.task_id)
                try:
                    ancestor = repo.get(ancestor.parent_task_id) if ancestor.parent_task_id else None
                except TaskNotFound:
                    ancestor = None
    pending, seen = list(task.dependencies), set()
    while pending:
        identity = pending.pop()
        if identity == task.task_id:
            blockers.append(Blocker('DEPENDENCY_CYCLE', task.task_id))
            break
        if identity in seen:
            continue
        seen.add(identity)
        try:
            pending.extend(repo.get(identity).dependencies)
        except TaskNotFound:
            blockers.append(Blocker('DEPENDENCY_MISSING', identity))
    if task.state in PROGRESS_STATES:
        blockers += [b for b in dependency_blockers(repo, task) if b.code != 'DEPENDENCY_MISSING']
    return list(dict.fromkeys(blockers))


def reference_guard(repo):
    """Guard for create()/update(): reject invalid, cyclic or hiding references."""
    def guard(task):
        blockers = reference_blockers(repo, task)
        if blockers:
            raise GateRejected('invalid task references', blockers)
    return guard


def transition_guard(repo):
    """Guard for transition(): enforce dependency and parent/child gating."""
    def guard(task, target):
        blockers = transition_blockers(repo, task, target)
        if blockers:
            raise GateRejected(f'{task.state} -> {target} gated', blockers)
    return guard
