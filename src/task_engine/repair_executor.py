"""Minimal repair executor (Issue #12, P1.11).

Applies one approved, bounded repair recipe to a disposable workspace and
records exactly what happened. It never touches the repository it runs from,
never deploys, and never moves a task to FIXED: success leaves the task in
progress for verification, any failure moves it to BLOCKED (precondition or
apply failure) or SAFE_STOP (workspace or allowlist violation).

A disposable workspace is a local clone under the system temp directory with
no remote and a marker written by create_disposable_workspace().
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import uuid

from src.task_engine.model import TaskState

MARKER = 'tim-disposable-workspace.json'
EXECUTOR_ID = 'src.task_engine.repair_executor'
_GIT_IDENTITY = ['-c', 'user.name=tim-repair-executor', '-c', 'user.email=repair-executor@localhost',
                 '-c', 'commit.gpgsign=false']


class RepairFailed(RuntimeError):
    def __init__(self, message, *, outcome, record):
        super().__init__(message)
        self.outcome = outcome
        self.record = record


@dataclass(frozen=True)
class RepairRecipe:
    """An approved repair: a patch limited to allowlisted files with expected hashes."""
    case_id: str
    approved_commit: str
    patch: str
    allowed_paths: tuple[str, ...]
    before_sha256: dict
    after_sha256: dict
    targeted_tests: tuple[str, ...] = ()
    regression_tests: tuple[str, ...] = ()
    detection_tests: tuple[str, ...] = ()
    probe: dict = field(default_factory=dict)  # {'path': repo-relative script, 'sha256': ...}

    def to_dict(self):
        data = asdict(self)
        for name in ('allowed_paths', 'targeted_tests', 'regression_tests', 'detection_tests'):
            data[name] = list(data[name])
        return data

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        for name in ('allowed_paths', 'targeted_tests', 'regression_tests', 'detection_tests'):
            data[name] = tuple(data.get(name, ()))
        return cls(**data)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git(workspace, *args, check=True):
    return subprocess.run(['git', *_GIT_IDENTITY, *args], cwd=workspace, capture_output=True, text=True,
                          timeout=120, check=check)


def create_disposable_workspace(source_repo, commit, *, sandbox_root=None):
    """Clone ``commit`` of ``source_repo`` into a fresh directory under the temp dir."""
    root = Path(sandbox_root or tempfile.gettempdir()).resolve()
    workspace = Path(tempfile.mkdtemp(prefix='tim-repair-', dir=root)).resolve() / 'repo'
    subprocess.run(['git', 'clone', '--quiet', '--no-checkout', str(source_repo), str(workspace)],
                   check=True, capture_output=True, timeout=300)
    _git(workspace, 'remote', 'remove', 'origin')
    _git(workspace, 'checkout', '--quiet', '--detach', commit)
    marker = {'workspace_id': str(uuid.uuid4()), 'source_commit': _git(workspace, 'rev-parse', 'HEAD').stdout.strip(),
              'created_at': datetime.now(timezone.utc).isoformat()}
    (workspace / '.git' / MARKER).write_text(json.dumps(marker, sort_keys=True))
    return workspace


def workspace_violations(workspace, *, forbidden_roots=()):
    """Reasons ``workspace`` may not be modified; empty when it is a valid disposable workspace."""
    workspace = Path(workspace)
    problems = []
    if workspace.is_symlink():
        problems.append('workspace is a symlink')
    workspace = workspace.resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if temp not in workspace.parents:
        problems.append('workspace is not under the system temp directory')
    for root in forbidden_roots:
        root = Path(root).resolve()
        if workspace == root or root in workspace.parents or workspace in root.parents:
            problems.append(f'workspace overlaps protected path {root}')
    if not (workspace / '.git' / MARKER).is_file():
        problems.append('disposable workspace marker missing')
    elif _git(workspace, 'remote', check=False).stdout.strip():
        problems.append('workspace has a git remote')
    return problems


def _patch_paths(workspace, patch_file):
    result = _git(workspace, 'apply', '--numstat', '--summary', str(patch_file), check=False)
    if result.returncode != 0:
        return None, result
    paths, modes = [], []
    for line in result.stdout.splitlines():
        parts = line.split('\t')
        if len(parts) == 3:
            paths.append(parts[2])
        elif line.strip():
            modes.append(line.strip())  # create/delete/rename/mode change lines
    return (paths, modes), result


def execute_repair(engine, task_id, recipe, workspace, evidence_dir, *, forbidden_roots=()):
    """Apply ``recipe`` in ``workspace`` for ``task_id``; return the execution record.

    On failure the task is moved to BLOCKED or SAFE_STOP and RepairFailed is raised.
    """
    workspace, evidence_dir = Path(workspace), Path(evidence_dir)
    started = datetime.now(timezone.utc).isoformat()
    record = {'executor': EXECUTOR_ID, 'task_id': task_id, 'case_id': recipe.case_id,
              'approved_commit': recipe.approved_commit, 'workspace': str(workspace), 'started_at': started,
              'allowed_paths': list(recipe.allowed_paths)}

    def fail(outcome, reason):
        record.update(outcome=outcome, reason=reason, finished_at=datetime.now(timezone.utc).isoformat())
        task = engine.get_task(task_id)
        if task.state not in {TaskState.BLOCKED, TaskState.SAFE_STOP}:
            (engine.safe_stop if outcome == 'SAFE_STOP' else engine.block)(task_id, f'repair executor: {reason}')
        raise RepairFailed(reason, outcome=outcome, record=record)

    task = engine.get_task(task_id)
    if task.type != 'BUGFIX' or task.state is not TaskState.IN_PROGRESS:
        raise RepairFailed('executor runs only for a BUGFIX task IN_PROGRESS', outcome='REJECTED', record=record)
    problems = workspace_violations(workspace, forbidden_roots=forbidden_roots)
    if problems:
        fail('SAFE_STOP', '; '.join(problems))
    workspace = workspace.resolve()
    record['workspace_marker'] = json.loads((workspace / '.git' / MARKER).read_text())
    if _git(workspace, 'status', '--porcelain').stdout.strip():
        fail('BLOCKED', 'workspace has uncommitted changes before repair')
    record['defect_commit'] = _git(workspace, 'rev-parse', 'HEAD').stdout.strip()

    patch_file = workspace / '.git' / f'repair-{recipe.case_id}.patch'
    patch_file.write_text(recipe.patch)
    parsed, check = _patch_paths(workspace, patch_file)
    if parsed is None:
        record['check_stderr'] = check.stderr[-2000:]
        fail('BLOCKED', 'patch is not applicable')
    paths, modes = parsed
    record['patch_paths'] = paths
    if not paths or modes or any(path not in recipe.allowed_paths for path in paths):
        fail('SAFE_STOP', f'patch touches paths outside the allowlist or changes file modes: {paths} {modes}')
    for path in paths:
        target = workspace / path
        if target.is_symlink() or not target.is_file():
            fail('SAFE_STOP', f'target is not a regular file: {path}')
    record['pre_sha256'] = {path: sha256_file(workspace / path) for path in paths}
    if record['pre_sha256'] != {p: recipe.before_sha256.get(p) for p in paths}:
        fail('BLOCKED', 'pre-repair hashes differ from the recipe (code drift)')

    applied = _git(workspace, 'apply', '--whitespace=nowarn', str(patch_file), check=False)
    record.update(apply_command=['git', 'apply', '--whitespace=nowarn', patch_file.name],
                  exit_status=applied.returncode, apply_stderr=applied.stderr[-2000:])
    if applied.returncode != 0:
        fail('BLOCKED', f'git apply exited {applied.returncode}')
    record['post_sha256'] = {path: sha256_file(workspace / path) for path in paths}
    diff = _git(workspace, 'diff', '--', *paths).stdout
    if record['post_sha256'] != {p: recipe.after_sha256.get(p) for p in paths} or not diff:
        _git(workspace, 'checkout', '--', *paths)
        fail('BLOCKED', 'post-repair hashes differ from the recipe; change reverted')
    changed = sorted(filter(None, _git(workspace, 'diff', '--name-only').stdout.splitlines()))
    if changed != sorted(paths):
        fail('SAFE_STOP', f'unexpected files changed: {changed}')

    _git(workspace, 'add', '--', *paths)
    _git(workspace, 'commit', '--quiet', '-m', f'repair {recipe.case_id} for task {task_id}')
    record['repair_commit'] = _git(workspace, 'rev-parse', 'HEAD').stdout.strip()
    record['changed_paths'] = changed
    evidence_dir.mkdir(parents=True, exist_ok=True)
    diff_path = evidence_dir / 'engine_repair.diff'
    diff_path.write_text(diff)
    record['git_diff'] = {'path': str(diff_path.resolve()), 'sha256': sha256_file(diff_path)}
    record.update(outcome='APPLIED', finished_at=datetime.now(timezone.utc).isoformat())
    engine.set_code_version(task_id, git_sha=record['repair_commit'], code_version=record['repair_commit'])
    engine.checkpoint(task_id, 'engine_repair', next_action='collect post-repair evidence',
                      metadata={'repair_commit': record['repair_commit'], 'exit_status': 0})
    return record
