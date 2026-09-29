"""Checkpointed step execution (Issue #12, P1.5).

A task's work is an ordered list of atomic steps. After each step the
repository records the checkpoint and the exact next incomplete action in
one transaction. A resumed run reads completed steps from storage, not from
memory, and skips them. A crash between a step's effect and its checkpoint
re-runs only that step, so step actions must be idempotent.
"""
from dataclasses import dataclass
from typing import Callable

from src.task_engine.model import TaskState

WORK_STATES = frozenset({TaskState.IN_PROGRESS, TaskState.VERIFYING})


@dataclass(frozen=True)
class Step:
    step_id: str
    description: str
    action: Callable[[], dict | None]


def completed_steps(repo, task_id):
    return [item['step_id'] for item in repo.checkpoints(task_id)]


def resume_point(repo, task_id, steps):
    """First step without a checkpoint, or None when all are done."""
    done = set(completed_steps(repo, task_id))
    return next((step for step in steps if step.step_id not in done), None)


def run_steps(repo, task_id, steps, *, now, final_next_action):
    """Run the incomplete steps in order; return the step_ids executed by this call."""
    ids = [step.step_id for step in steps]
    if len(set(ids)) != len(ids):
        raise ValueError('step ids must be unique')
    task = repo.get(task_id)
    if task.state not in WORK_STATES:
        raise ValueError(f'steps run only in {sorted(WORK_STATES)}, task is {task.state}')
    done = set(completed_steps(repo, task_id))
    executed = []
    for index, step in enumerate(steps):
        if step.step_id in done:
            continue
        metadata = step.action() or {}
        following = next((later.description for later in steps[index + 1:] if later.step_id not in done),
                         final_next_action)
        repo.checkpoint(task_id, step.step_id, at=now(), next_action=following, metadata=metadata)
        done.add(step.step_id)
        executed.append(step.step_id)
    return executed
