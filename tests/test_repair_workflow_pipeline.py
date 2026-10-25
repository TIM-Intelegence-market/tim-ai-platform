"""#17/#18/#20: a novel SOFTWARE_BUG candidate moves through the complete isolated workflow and stops before merge."""
import hashlib

import pytest

from src.repair_workflow.pipeline import REQUIRED_GATES, gate_results, run_patch_pipeline

DIGEST = hashlib.sha256(b'replay').hexdigest()
PATCH = ('diff --git a/src/demo/fix.py b/src/demo/fix.py\n'
         '--- a/src/demo/fix.py\n+++ b/src/demo/fix.py\n'
         '@@ -1 +1 @@\n-return a / b\n+return a / b if b else 0\n')


def good_evidence(**changes):
    evidence = {'first_digest': DIGEST, 'second_digest': DIGEST,
                'events': [{'timestamp': '2026-10-25T09:00:00+00:00'}], 'cutoff': '2026-10-25T10:00:00+00:00',
                'test_db_url': 'postgresql://127.0.0.1:5434/tim_test', 'runtime_db_url': 'postgresql://127.0.0.1:5432/tim',
                'queue_before': {'pending': 3, 'attempts': {'a': 1}}, 'queue_after': {'pending': 3, 'attempts': {'a': 1}},
                'test_reports': {'tests/test_demo.py': 'PASS'}}
    evidence.update(changes)
    return evidence


def defect_present(workspace, payload):
    assert workspace.is_dir()
    return payload['b'] == 0


def run(**changes):
    args = dict(incident_id='inc-1', task_id='task-1', case_id='case-1', reproduce=defect_present,
                payload={'a': 1, 'b': 0}, patch_diff=PATCH, allowed_paths=['src/demo/fix.py'],
                evidence=good_evidence())
    args.update(changes)
    return run_patch_pipeline(**args)


def test_full_run_reaches_human_review_and_never_merges_or_fixes():
    result = run()
    assert result['stage'] == 'REVIEW'
    assert result['candidate']['status'] == 'READY_FOR_REVIEW'
    assert result['review_artifact']['verdict'] == 'READY_FOR_HUMAN_REVIEW'
    assert result['gate_decision'] == {'status': 'PASS', 'escalate': False, 'reasons': []}
    assert result['fixed'] is False and result['auto_merge'] is False
    assert result['candidate']['fixed'] is False and result['candidate']['auto_merge'] is False


def test_linkage_from_incident_to_verification_is_persistable_and_deterministic():
    first, second = run(), run()
    link = first['linkage']
    assert link['incident_id'] == 'inc-1' and link['task_id'] == 'task-1' and link['case_id'] == 'case-1'
    assert link['reproduction_refs'] and link['reproduction_refs'][0].startswith('sha256:')
    assert link['patch_sha256'] == hashlib.sha256(PATCH.encode()).hexdigest()
    assert link == second['linkage']                    # same inputs, same artifact digest


@pytest.mark.parametrize('reproduce, expected', [
    (lambda ws, p: False, 'NOT_REPRODUCED'),
    (lambda ws, p: 'yes', 'INSUFFICIENT_EVIDENCE'),
])
def test_no_patch_is_checked_before_the_defect_is_reproduced(reproduce, expected):
    result = run(reproduce=reproduce)
    assert result['stage'] == 'REPRODUCTION' and result['candidate']['status'] == 'BLOCKED'
    assert 'diff_check' not in result and 'review_artifact' not in result
    assert expected in result['candidate']['reasons'][0]


def test_flaky_reproduction_never_counts():
    calls = []

    def flaky(ws, p):
        calls.append(1)
        return len(calls) == 1
    result = run(reproduce=flaky)
    assert result['stage'] == 'REPRODUCTION' and len(calls) == 2


def test_a_documented_waiver_lets_insufficient_evidence_reach_review():
    result = run(reproduce=lambda ws, p: 'yes', reproduction_waiver='host-only failure, operator #999')
    assert result['stage'] == 'REVIEW' and result['candidate']['status'] == 'READY_FOR_REVIEW'
    assert result['review_artifact']['verdict'] == 'BLOCKED'      # the artifact still says: not reproduced


def test_failed_tests_prevent_ready():
    result = run(evidence=good_evidence(test_reports={'tests/test_demo.py': 'FAIL'}))
    assert result['candidate']['status'] == 'FAILED' and result['gate_decision']['status'] == 'FAIL'
    assert result['review_artifact']['verdict'] == 'BLOCKED'


@pytest.mark.parametrize('change', [
    {'second_digest': hashlib.sha256(b'other').hexdigest()},
    {'events': [{'timestamp': '2026-10-25T11:00:00+00:00'}]},
    {'test_db_url': 'postgresql://127.0.0.1:5432/tim'},
    {'queue_after': {'pending': 0, 'attempts': {'a': 1}}},
    {'queue_after': {'pending': 3, 'attempts': {'a': 0}}},
])
def test_critical_integrity_failures_escalate_to_safe_stop(change):
    result = run(evidence=good_evidence(**change))
    assert result['gate_decision']['status'] == 'SAFE_STOP' and result['gate_decision']['escalate'] is True
    assert result['candidate']['status'] == 'SAFE_STOP'
    assert result['fixed'] is False and result['auto_merge'] is False


def test_patch_outside_allowed_paths_fails_even_with_green_gates():
    result = run(allowed_paths=['src/other.py'])
    assert result['diff_check']['ok'] is False and result['candidate']['status'] == 'FAILED'


def test_missing_evidence_is_never_a_pass():
    results = gate_results({})
    assert [r.gate for r in results] == list(REQUIRED_GATES)
    assert all(r.status.value == 'fail' for r in results)
    assert run(evidence=None)['candidate']['status'] == 'SAFE_STOP'


@pytest.mark.parametrize('bad', [{'incident_id': ''}, {'task_id': None}, {'case_id': ' '}])
def test_invalid_identity_stops_before_anything_runs(bad):
    calls = []
    result = run(reproduce=lambda ws, p: calls.append(1) or True, **bad)
    assert result['stage'] == 'INPUT' and calls == []


def test_reproduction_cannot_mutate_the_callers_payload():
    payload = {'a': 1, 'b': 0}

    def mutate(ws, p):
        p['b'] = 5
        return True
    run(reproduce=mutate, payload=payload)
    assert payload == {'a': 1, 'b': 0}
