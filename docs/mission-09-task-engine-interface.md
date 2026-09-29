# Mission 09 — Task Engine interface (#12 → #13)

Stable surface of the persistent Task Engine from #12. Later phases use
`src.task_engine.service.TaskEngine` only; they never touch the repository or
its SQLite tables.

```python
from src.task_engine.repository import SqliteTaskRepository
from src.task_engine.service import TaskEngine

engine = TaskEngine(SqliteTaskRepository(path_to_dedicated_task_db))
```

`path_to_dedicated_task_db` is a file owned by the Task Engine. There is no
default path; never point it at a production or observer database.

## Operations

| Call | Effect |
| --- | --- |
| `create_task(task_id, *, type, source='', parent_task_id=None, dependencies=(), required_evidence=(), git_sha=None, ...)` | New task in `NEW`, `attempt_count=0`. Parent/dependencies must exist; cycles, self-references and children of a `FIXED` parent are rejected. |
| `transition_task(task_id, target, *, reason=None, expected_revision=None)` | Only legal state-machine moves. Dependency/parent gating and the Fix-First gate always apply. `target` is a `TaskState` or its exact name. |
| `block(task_id, reason)` / `safe_stop(task_id, reason)` | Escape moves; a reason is mandatory. `SAFE_STOP` is released only through `BLOCKED`. |
| `checkpoint(task_id, step_id, *, next_action, metadata=None)` | Records a completed atomic step and the exact next action atomically; repeating a step id is a no-op. |
| `set_code_version(task_id, *, git_sha, code_version=None, config_hash=None)` | Records the code version under verification (e.g. the repair commit). Reports bound to an earlier `git_sha` stop counting. Not allowed on `FIXED` tasks. |
| `attach_evidence_ref(task_id, name, reference)` | Appends an evidence reference (JSON data, ≤64 KiB); the latest per name is current. |
| `tasks(state=, type=, parent_task_id=, source=)`, `get_task`, `history`, `evidence`, `checkpoints` | Read access. |
| `resumable_work()`, `handoff()`, `snapshot(task_id)` | Resume order `IN_PROGRESS > VERIFYING > READY > PLANNED > NEW`; held states are never auto-resumed. |

## Linking an incident (#13)

Use `source` as the link: e.g. `source='incident:<fingerprint>'`, and find
the task again with `engine.tasks(source='incident:<fingerprint>')`. Create a
`BUGFIX` task for a repair; its type cannot be changed later.

## Rules #13 inherits

- States: `NEW, PLANNED, READY, IN_PROGRESS, VERIFYING, BLOCKED, SAFE_STOP, FIXED, FAILED`; `FIXED` is terminal.
- A `BUGFIX` reaches `FIXED` only with content-bound evidence under the names
  `root_cause, reproduction, repair, targeted_tests, regression_tests, safety,
  runtime, integrity, recurrence` (format: `src/bugfixer/tasks.py`
  `validate_fix_evidence`), bound to the task's id, current attempt and
  `git_sha`. Analysis text, booleans or model verdicts never qualify;
  operational remediation is rejected until it has its own verifier.
- Errors: `InvalidTransition` (and subclasses `GateRejected` with
  `.blockers`, `FixFirstRejected`), `TaskNotFound`, `TaskExists`,
  `RevisionConflict`. Nothing is written when a call raises.
- Timestamps come from the engine's injected clock and never go backwards.
