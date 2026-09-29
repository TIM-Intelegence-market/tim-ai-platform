"""Issue #12 P1.13 contract: FIXED only with complete, real, engine-executed repair evidence."""
import json
from pathlib import Path

import pytest

from src.task_engine.fix_first import ENGINE_REPAIR_EVIDENCE, FixFirstRejected, validate_fixed
from src.task_engine.repair_executor import sha256_file
from src.task_engine.repository import SqliteTaskRepository
from src.task_engine.service import TaskEngine
from tests.task_engine_repair_fixture import BUGFIX_EVIDENCE, S, repair_with_evidence, start_bugfix


@pytest.fixture
def engine(tmp_path):
    with SqliteTaskRepository(tmp_path / 'store' / 'tasks.sqlite3') as repo:
        engine = TaskEngine(repo)
        start_bugfix(engine)
        yield engine


@pytest.fixture
def repaired(engine, tmp_path):
    repair_with_evidence(engine, tmp_path)
    return engine


def rewrite_report(reference, **fields):
    path = Path(reference['path'])
    path.write_text(json.dumps({**json.loads(path.read_text()), **fields}))
    return {'path': str(path), 'sha256': sha256_file(path)}


def reject(engine, evidence):
    with pytest.raises(FixFirstRejected):
        validate_fixed(engine.get_task('bug'), evidence)


def test_required_evidence_names_match_the_gate():
    assert set(ENGINE_REPAIR_EVIDENCE) <= set(BUGFIX_EVIDENCE)


def test_complete_engine_repair_evidence_allows_fixed(repaired):
    repaired.transition_task('bug', S.VERIFYING)
    assert repaired.transition_task('bug', S.FIXED).state is S.FIXED


@pytest.mark.parametrize('missing', ENGINE_REPAIR_EVIDENCE)
def test_engine_repair_evidence_is_mandatory(repaired, missing):
    evidence = repaired.evidence('bug')
    del evidence[missing]
    reject(repaired, evidence)


@pytest.mark.parametrize('fields', [{'exit_status': 1}, {'executor': 'chatgpt'}, {'outcome': 'PROPOSED'},
                                    {'repair_commit': 'f' * 40}, {'changed_paths': ['calc.py', 'other.py']},
                                    {'pre_sha256': {'calc.py': 'x'}}, {'workspace_marker': {}}])
def test_forged_or_failed_execution_is_rejected(repaired, fields):
    evidence = repaired.evidence('bug')
    evidence['repair_execution'] = rewrite_report(evidence['repair_execution'], **fields)
    reject(repaired, evidence)


def test_status_field_cannot_replace_a_real_failing_reproduction(repaired):
    evidence = repaired.evidence('bug')
    passing_junit = json.loads(Path(evidence['post_repair_repro']['path']).read_text())['junit']
    evidence['pre_repair_repro'] = rewrite_report(evidence['pre_repair_repro'], status='FAIL_AS_EXPECTED',
                                                  junit=passing_junit)
    reject(repaired, evidence)


def test_status_field_cannot_hide_a_failing_post_repair_run(repaired):
    evidence = repaired.evidence('bug')
    failing_junit = json.loads(Path(evidence['pre_repair_repro']['path']).read_text())['junit']
    evidence['post_repair_repro'] = rewrite_report(evidence['post_repair_repro'], status='PASS', junit=failing_junit)
    reject(repaired, evidence)


def test_probe_still_showing_defect_is_rejected(repaired, tmp_path):
    evidence = repaired.evidence('bug')
    fake = tmp_path / 'fake_probe.json'
    fake.write_text(json.dumps({'defect_present': True, 'checks': {}}))
    evidence['post_repair_repro'] = rewrite_report(evidence['post_repair_repro'],
                                                   probe={'path': str(fake), 'sha256': sha256_file(fake)})
    reject(repaired, evidence)


def test_llm_or_report_only_evidence_never_fixes(engine):
    reject(engine, {'root_cause': 'model analysis', 'model_verdict': 'FIXED', 'repair_execution': 'done',
                    'pre_repair_repro': 'FAIL_AS_EXPECTED', 'post_repair_repro': 'PASS'})
    engine.attach_evidence_ref('bug', 'model_verdict', {'provider': 'external-llm', 'verdict': 'FIXED'})
    engine.transition_task('bug', S.VERIFYING)
    with pytest.raises(FixFirstRejected):
        engine.transition_task('bug', S.FIXED)
    assert engine.get_task('bug').state is S.VERIFYING
