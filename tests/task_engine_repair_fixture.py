"""Synthetic repository with a real defect for P1.11-P1.14 tests (unit-test only)."""
import hashlib
import subprocess
import sys

from src.task_engine import TaskState
from src.task_engine.evidence_collector import EvidenceCollector
from src.task_engine.repair_executor import RepairRecipe, create_disposable_workspace, execute_repair, sha256_file

S = TaskState
BROKEN = 'def add(a, b):\n    return a - b\n'
FIXED = 'def add(a, b):\n    return a + b\n'
TEST = 'from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n'
OTHER = 'def test_other():\n    assert True\n'
PROBE = ('import json, sys\nsys.path.insert(0, ".")\nfrom calc import add\n'
         'ok = add(2, 3) == 5\n'
         'print(json.dumps({"defect_present": not ok, "checks": {"adds_correctly": ok}}))\n')
BUGFIX_EVIDENCE = ['root_cause', 'reproduction', 'repair', 'targeted_tests', 'regression_tests', 'safety',
                   'runtime', 'integrity', 'recurrence', 'repair_execution', 'pre_repair_repro', 'post_repair_repro']


def git(cwd, *args):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout


def make_source(root, code=BROKEN):
    repo = root / 'source'
    (repo / 'tests').mkdir(parents=True)
    git(repo, 'init', '-q')
    (repo / 'calc.py').write_text(code)
    (repo / 'tests' / 'test_calc.py').write_text(TEST)
    (repo / 'tests' / 'test_other.py').write_text(OTHER)
    (repo / 'probe.py').write_text(PROBE)
    (repo / '.gitignore').write_text('__pycache__/\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'source')
    return repo


def recipe(repo, before=BROKEN):
    current = (repo / 'calc.py').read_text()
    (repo / 'calc.py').write_text(FIXED)
    patch = git(repo, 'diff')
    (repo / 'calc.py').write_text(current)
    return RepairRecipe(
        case_id='calc-sign', approved_commit=git(repo, 'rev-parse', 'HEAD').strip(), patch=patch,
        allowed_paths=('calc.py',), before_sha256={'calc.py': hashlib.sha256(before.encode()).hexdigest()},
        after_sha256={'calc.py': hashlib.sha256(FIXED.encode()).hexdigest()},
        targeted_tests=('tests/test_calc.py',), regression_tests=('tests/test_calc.py', 'tests/test_other.py'),
        detection_tests=('tests/test_calc.py', 'tests/test_other.py'),
        probe={'path': 'probe.py', 'sha256': sha256_file(repo / 'probe.py')})


def start_bugfix(engine, task_id='bug'):
    engine.create_task(task_id, type='BUGFIX', git_sha='0' * 40, required_evidence=BUGFIX_EVIDENCE)
    for target in (S.PLANNED, S.READY, S.IN_PROGRESS):
        engine.transition_task(task_id, target)


def repair_with_evidence(engine, tmp_path, task_id='bug'):
    source = make_source(tmp_path)
    rec = recipe(source)
    workspace = create_disposable_workspace(source, 'HEAD', sandbox_root=tmp_path)
    collector = EvidenceCollector(engine, task_id, rec, workspace, tmp_path / 'evidence', python=sys.executable)
    pre = collector.collect_pre_repair()
    execution = execute_repair(engine, task_id, rec, workspace, tmp_path / 'evidence', forbidden_roots=[source])
    bundle = collector.collect_post_repair(execution, root_cause='add() subtracts instead of adding')
    return pre, execution, bundle
