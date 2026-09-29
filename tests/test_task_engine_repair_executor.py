"""Issue #12 P1.11 contract: bounded repair in a disposable workspace; failures never FIXED."""
import json
from pathlib import Path
import subprocess

import pytest

from src.task_engine import TaskState
from src.task_engine.repair_executor import (
    MARKER, RepairFailed, RepairRecipe, create_disposable_workspace, execute_repair, sha256_file,
    workspace_violations)
from src.task_engine.repository import SqliteTaskRepository
from src.task_engine.service import TaskEngine

S = TaskState
BROKEN = 'def add(a, b):\n    return a - b\n'
FIXED = 'def add(a, b):\n    return a + b\n'


def git(cwd, *args):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false',
                           *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / 'source'
    repo.mkdir()
    git(repo, 'init', '-q')
    (repo / 'calc.py').write_text(BROKEN)
    (repo / 'other.py').write_text('X = 1\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'defect')
    return repo


def recipe_for(source, **changes):
    base = git(source, 'rev-parse', 'HEAD').strip()
    (source / 'calc.py').write_text(FIXED)
    patch = git(source, 'diff')
    git(source, 'checkout', '--', 'calc.py')
    values = dict(case_id='calc-sign', approved_commit=base, patch=patch, allowed_paths=('calc.py',),
                  before_sha256={'calc.py': sha256_file(source / 'calc.py')},
                  after_sha256={'calc.py': __import__('hashlib').sha256(FIXED.encode()).hexdigest()})
    values.update(changes)
    return base, RepairRecipe(**values)


@pytest.fixture
def engine(tmp_path):
    with SqliteTaskRepository(tmp_path / 'store' / 'tasks.sqlite3') as repo:
        engine = TaskEngine(repo)
        engine.create_task('bug', type='BUGFIX', git_sha='0' * 40)
        for target in (S.PLANNED, S.READY, S.IN_PROGRESS):
            engine.transition_task('bug', target)
        yield engine


def test_applies_recipe_and_records_exact_evidence(engine, source, tmp_path):
    base, recipe = recipe_for(source)
    workspace = create_disposable_workspace(source, base, sandbox_root=tmp_path)
    record = execute_repair(engine, 'bug', recipe, workspace, tmp_path / 'evidence', forbidden_roots=[source])
    assert record['outcome'] == 'APPLIED' and record['exit_status'] == 0
    assert record['pre_sha256'] == recipe.before_sha256 and record['post_sha256'] == recipe.after_sha256
    assert record['changed_paths'] == ['calc.py'] and record['defect_commit'] == base
    diff = Path(record['git_diff']['path']).read_text()
    assert '-    return a - b' in diff and '+    return a + b' in diff
    assert sha256_file(record['git_diff']['path']) == record['git_diff']['sha256']
    assert (workspace / 'calc.py').read_text() == FIXED
    assert (source / 'calc.py').read_text() == BROKEN  # the source repository is never touched
    task = engine.get_task('bug')
    assert task.state is S.IN_PROGRESS and task.git_sha == record['repair_commit']
    assert [c['step_id'] for c in engine.checkpoints('bug')] == ['engine_repair']


def test_workspace_has_no_remote_and_a_marker(source, tmp_path):
    base, _ = recipe_for(source)
    workspace = create_disposable_workspace(source, base, sandbox_root=tmp_path)
    assert workspace_violations(workspace) == []
    assert json.loads((workspace / '.git' / MARKER).read_text())['source_commit'] == base
    assert git(workspace, 'remote').strip() == ''


def assert_stopped(engine, error, outcome, state):
    assert error.value.outcome == outcome
    task = engine.get_task('bug')
    assert task.state is state and task.state is not S.FIXED
    assert task.blocker_reason.startswith('repair executor:')


def test_non_disposable_workspace_is_safe_stopped(engine, source, tmp_path):
    _, recipe = recipe_for(source)
    with pytest.raises(RepairFailed) as error:
        execute_repair(engine, 'bug', recipe, source, tmp_path / 'evidence')
    assert_stopped(engine, error, 'SAFE_STOP', S.SAFE_STOP)
    assert (source / 'calc.py').read_text() == BROKEN


def test_protected_root_is_safe_stopped(engine, source, tmp_path):
    base, recipe = recipe_for(source)
    workspace = create_disposable_workspace(source, base, sandbox_root=tmp_path)
    with pytest.raises(RepairFailed) as error:
        execute_repair(engine, 'bug', recipe, workspace, tmp_path / 'evidence', forbidden_roots=[workspace.parent])
    assert_stopped(engine, error, 'SAFE_STOP', S.SAFE_STOP)


def test_workspace_with_remote_is_safe_stopped(engine, source, tmp_path):
    base, recipe = recipe_for(source)
    workspace = create_disposable_workspace(source, base, sandbox_root=tmp_path)
    git(workspace, 'remote', 'add', 'origin', str(source))
    with pytest.raises(RepairFailed) as error:
        execute_repair(engine, 'bug', recipe, workspace, tmp_path / 'evidence')
    assert_stopped(engine, error, 'SAFE_STOP', S.SAFE_STOP)


def test_patch_outside_allowlist_is_safe_stopped(engine, source, tmp_path):
    base, recipe = recipe_for(source, allowed_paths=('other.py',))
    workspace = create_disposable_workspace(source, base, sandbox_root=tmp_path)
    with pytest.raises(RepairFailed) as error:
        execute_repair(engine, 'bug', recipe, workspace, tmp_path / 'evidence')
    assert_stopped(engine, error, 'SAFE_STOP', S.SAFE_STOP)
    assert (workspace / 'calc.py').read_text() == BROKEN


def test_code_drift_blocks_without_applying(engine, source, tmp_path):
    base, recipe = recipe_for(source, before_sha256={'calc.py': 'f' * 64})
    workspace = create_disposable_workspace(source, base, sandbox_root=tmp_path)
    with pytest.raises(RepairFailed) as error:
        execute_repair(engine, 'bug', recipe, workspace, tmp_path / 'evidence')
    assert_stopped(engine, error, 'BLOCKED', S.BLOCKED)
    assert (workspace / 'calc.py').read_text() == BROKEN


def test_unapplicable_patch_blocks(engine, source, tmp_path):
    base, recipe = recipe_for(source, patch='this is not a patch\n')
    workspace = create_disposable_workspace(source, base, sandbox_root=tmp_path)
    with pytest.raises(RepairFailed) as error:
        execute_repair(engine, 'bug', recipe, workspace, tmp_path / 'evidence')
    assert_stopped(engine, error, 'BLOCKED', S.BLOCKED)


def test_unexpected_result_is_reverted_and_blocked(engine, source, tmp_path):
    base, recipe = recipe_for(source, after_sha256={'calc.py': 'e' * 64})
    workspace = create_disposable_workspace(source, base, sandbox_root=tmp_path)
    with pytest.raises(RepairFailed) as error:
        execute_repair(engine, 'bug', recipe, workspace, tmp_path / 'evidence')
    assert_stopped(engine, error, 'BLOCKED', S.BLOCKED)
    assert (workspace / 'calc.py').read_text() == BROKEN


def test_executor_refuses_tasks_not_in_progress(engine, source, tmp_path):
    base, recipe = recipe_for(source)
    workspace = create_disposable_workspace(source, base, sandbox_root=tmp_path)
    engine.transition_task('bug', S.VERIFYING)
    with pytest.raises(RepairFailed) as error:
        execute_repair(engine, 'bug', recipe, workspace, tmp_path / 'evidence')
    assert error.value.outcome == 'REJECTED' and engine.get_task('bug').state is S.VERIFYING


def test_recipe_roundtrip():
    recipe = RepairRecipe(case_id='c', approved_commit='a' * 40, patch='p', allowed_paths=('x.py',),
                          before_sha256={'x.py': '1'}, after_sha256={'x.py': '2'}, targeted_tests=('t',),
                          probe={'path': 'p.py', 'sha256': '3'})
    assert RepairRecipe.from_dict(json.loads(json.dumps(recipe.to_dict()))) == recipe
