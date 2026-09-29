"""Issue #12 P1.12 contract: machine-readable repair evidence around an engine repair."""
from dataclasses import replace
import hashlib
import json
import sys

import pytest

from src.task_engine.evidence_collector import EvidenceCollector, ReproductionFailed
from src.task_engine.repair_executor import create_disposable_workspace
from src.task_engine.repository import SqliteTaskRepository
from src.task_engine.service import TaskEngine
from tests.task_engine_repair_fixture import (
    BUGFIX_EVIDENCE, FIXED, S, make_source, recipe, repair_with_evidence, start_bugfix)


@pytest.fixture
def engine(tmp_path):
    with SqliteTaskRepository(tmp_path / 'store' / 'tasks.sqlite3') as repo:
        engine = TaskEngine(repo)
        start_bugfix(engine)
        yield engine


def test_bundle_records_repro_tests_hashes_diff_task_sha_and_times(engine, tmp_path):
    pre, execution, bundle = repair_with_evidence(engine, tmp_path)
    task = engine.get_task('bug')
    assert pre['status'] == 'FAIL_AS_EXPECTED' and pre['targeted']['failing'] == ['tests.test_calc::test_add']
    assert pre['probe']['defect_present'] is True
    assert bundle['task_id'] == 'bug' and bundle['git_sha'] == task.git_sha == execution['repair_commit']
    assert bundle['defect_commit'] == execution['defect_commit'] != execution['repair_commit']
    assert bundle['pre_repair_repro'] == 'FAIL_AS_EXPECTED' and bundle['post_repair_repro'] == 'PASS'
    assert bundle['targeted_tests'] == {'testcase': 1, 'failure': 0, 'error': 0, 'skipped': 0}
    assert bundle['regression_tests']['testcase'] == 2 and bundle['regression_tests']['failure'] == 0
    assert bundle['pre_sha256'] != bundle['post_sha256'] and bundle['collected_at']
    for group in ('runtime_checks', 'safety_checks', 'integrity_checks', 'recurrence_checks'):
        assert bundle[group] and all(bundle[group].values()), group
    saved = json.loads((tmp_path / 'evidence' / 'bundle.json').read_text())
    assert saved['case_id'] == 'calc-sign' and saved['evidence']['repair']['kind'] == 'CODE_PATCH'
    assert '+    return a + b' in (tmp_path / 'evidence' / 'engine_repair.diff').read_text()
    assert set(BUGFIX_EVIDENCE) <= set(engine.evidence('bug'))
    for name in ('repair_execution', 'pre_repair_repro', 'post_repair_repro', 'targeted_tests'):
        report = json.loads(open(engine.evidence('bug')[name]['path']).read())
        assert (report['task_id'], report['git_sha'], report['attempt_count']) == ('bug', task.git_sha, 1)
        assert report['collected_at']
    assert [c['step_id'] for c in engine.checkpoints('bug')] == [
        'pre_repair_repro', 'engine_repair', 'post_repair_evidence']
    assert engine.get_task('bug').state is S.IN_PROGRESS  # the collector never decides FIXED


def test_defect_that_does_not_reproduce_blocks(engine, tmp_path):
    source = make_source(tmp_path, FIXED)
    rec = replace(recipe(source, before=FIXED), before_sha256={'calc.py': hashlib.sha256(FIXED.encode()).hexdigest()})
    workspace = create_disposable_workspace(source, 'HEAD', sandbox_root=tmp_path)
    collector = EvidenceCollector(engine, 'bug', rec, workspace, tmp_path / 'evidence', python=sys.executable)
    with pytest.raises(ReproductionFailed):
        collector.collect_pre_repair()
    assert engine.get_task('bug').state is S.BLOCKED


def test_probe_not_matching_recipe_is_not_executed(engine, tmp_path):
    source = make_source(tmp_path)
    rec = replace(recipe(source), probe={'path': 'probe.py', 'sha256': '0' * 64})
    workspace = create_disposable_workspace(source, 'HEAD', sandbox_root=tmp_path)
    collector = EvidenceCollector(engine, 'bug', rec, workspace, tmp_path / 'evidence', python=sys.executable)
    with pytest.raises(ReproductionFailed):
        collector.collect_pre_repair()


def test_post_repair_requires_pre_repair_reproduction(engine, tmp_path):
    source = make_source(tmp_path)
    collector = EvidenceCollector(engine, 'bug', recipe(source), source, tmp_path / 'evidence', python=sys.executable)
    with pytest.raises(ReproductionFailed):
        collector.collect_post_repair({'outcome': 'APPLIED', 'changed_paths': ['calc.py']}, root_cause='x')
