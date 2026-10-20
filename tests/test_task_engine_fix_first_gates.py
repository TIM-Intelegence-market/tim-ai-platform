"""Issue #242 contract: FIXED requires declared repair gates to aggregate to PASS."""
import pytest

from src.task_engine.fix_first import REPAIR_GATES_EVIDENCE, FixFirstRejected, validate_fixed
from src.task_engine.model import Task

REQUIRED = ['targeted_tests', 'regression_tests', 'db_integrity']


@pytest.fixture
def task():
    return Task(task_id='T-1', type='MAINTENANCE', required_evidence=['repair_gates'])


def ok(gate):
    return {'gate': gate, 'status': 'pass'}


def gates(results, required=REQUIRED):
    return {'repair_gates': {'required': list(required), 'results': results}}


def all_pass():
    return [ok(name) for name in REQUIRED]


def reject(task, evidence):
    with pytest.raises(FixFirstRejected) as excinfo:
        validate_fixed(task, evidence)
    return str(excinfo.value)


def test_constant_names_the_evidence():
    assert REPAIR_GATES_EVIDENCE == 'repair_gates'


def test_all_required_gates_pass(task):
    assert validate_fixed(task, gates(all_pass())) is None


def test_one_failing_gate_rejects(task):
    results = all_pass()
    results[0] = {'gate': 'targeted_tests', 'status': 'fail', 'reason': 'test failed'}
    message = reject(task, gates(results))
    assert 'FAIL' in message
    assert 'targeted_tests' in message


@pytest.mark.parametrize('status', ['blocked', 'skip'])
def test_blocked_or_skipped_gate_rejects(task, status):
    results = all_pass()
    results[1] = {'gate': 'regression_tests', 'status': status, 'reason': 'not run'}
    reject(task, gates(results))


def test_missing_required_gate_rejects(task):
    message = reject(task, gates(all_pass()[:-1]))
    assert 'missing gate: db_integrity' in message


def test_critical_gate_failure_is_safe_stop(task):
    results = all_pass()
    results[2] = {'gate': 'db_integrity', 'status': 'fail', 'reason': 'database not isolated'}
    message = reject(task, gates(results))
    assert 'SAFE_STOP' in message


@pytest.mark.parametrize('result', [
    {'gate': 'targeted_tests', 'status': 'fail'},          # non-pass without reason
    {'gate': 'targeted_tests', 'status': 'PASS'},          # unknown status spelling
    {'gate': 'targeted_tests'},                            # status missing
    {'gate': '', 'status': 'pass'},                        # empty gate name
    {'gate': 'targeted_tests', 'status': 'pass', 'extra': 1},
    'targeted_tests',
    None,
])
def test_malformed_result_rejects(task, result):
    reject(task, gates([result, *all_pass()[1:]]))


@pytest.mark.parametrize('value', [
    None,
    [],
    'PASS',
    {'required': REQUIRED},                                # results missing
    {'results': []},                                       # required missing
    {'required': [], 'results': []},                       # required empty
    {'required': 'targeted_tests', 'results': []},         # required not a list
    {'required': ['targeted_tests', 1], 'results': []},    # required item not str
    {'required': REQUIRED, 'results': ok('targeted_tests')},  # results not a list
])
def test_malformed_repair_gates_value_rejects(task, value):
    reject(task, {'repair_gates': value})


def test_unexpected_gate_rejects(task):
    reject(task, gates([*all_pass(), ok('surprise')]))


def test_evidence_without_repair_gates_rejects(task):
    message = reject(task, {'other': 'x'})
    assert 'repair_gates' in message


def test_non_dict_evidence_rejects(task):
    reject(task, None)


def test_task_without_repair_gates_is_unaffected():
    plain = Task(task_id='T-2', type='MAINTENANCE', required_evidence=['report'])
    assert validate_fixed(plain, {'report': 'ok'}) is None
    with pytest.raises(FixFirstRejected):
        validate_fixed(plain, {})
    no_evidence = Task(task_id='T-3', type='MAINTENANCE')
    assert validate_fixed(no_evidence, {}) is None


def test_other_required_evidence_still_checked_first():
    both = Task(task_id='T-4', type='MAINTENANCE', required_evidence=['report', 'repair_gates'])
    message = reject(both, gates(all_pass()))
    assert "missing required evidence: ['report']" in message
    assert validate_fixed(both, {'report': 'ok', **gates(all_pass())}) is None
