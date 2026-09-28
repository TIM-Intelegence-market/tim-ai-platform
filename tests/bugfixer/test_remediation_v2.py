"""Pure recipe-contract tests: no service, market DB or action adapter exists."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from src.bugfixer.processing import Event, fingerprint
from src.bugfixer.remediation import FORBIDDEN_ACTIONS, dry_run, load_registry
from src.bugfixer.safety import Policy, SafetyViolation

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / 'schemas/bugfixer/remediations.v2.json'
AT = '2026-09-09T00:00:00+00:00'
EVENT = Event(AT, 'collector', 'TimeoutError', 'network timeout')


@pytest.fixture
def recipe():
    return deepcopy(load_registry(REGISTRY)[0])


def write_registry(tmp_path, entries, version=2):
    path = tmp_path / 'recipes.json'
    path.write_text(json.dumps({'schema_version': version, 'entries': entries}))
    return path


def attest(recipe):
    return dict.fromkeys(recipe['preconditions'], True)


def test_v2_registry_requires_explicit_preconditions_before_proposal(recipe):
    entries = load_registry(REGISTRY)
    blocked = dry_run(EVENT, entries)
    assert blocked['registry_schema_version'] == 2
    assert blocked['legacy_registry'] is False
    assert blocked['proposals'] == []
    assert blocked['gates'][0]['missing_preconditions'] == recipe['preconditions']
    proposed = dry_run(EVENT, entries, satisfied_preconditions=attest(recipe))
    assert proposed['proposals'] == [recipe]
    assert proposed['gates'][0]['decision'] == 'PROPOSED'
    assert proposed['executed'] is False
    assert proposed['gates'][0]['executed'] is False
    assert proposed['auto_remediation'] == 'NOT_SAFE'


@pytest.mark.parametrize('field', [
    'remediation_id', 'version', 'matching_rules', 'confidence', 'risk', 'autonomy_level',
    'preconditions', 'actions', 'forbidden_actions', 'rollback', 'targeted_tests',
    'runtime_verification', 'integrity_verification', 'recurrence_check',
])
def test_every_v2_recipe_field_is_mandatory(tmp_path, recipe, field):
    del recipe[field]
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, [recipe]))


@pytest.mark.parametrize(('field', 'value'), [
    ('version', 2), ('version', '2'), ('version', '01.0.0'),
    ('confidence', True), ('confidence', '0.95'), ('confidence', -0.1),
    ('confidence', 1.1), ('confidence', float('nan')), ('confidence', float('inf')),
    ('risk', []), ('autonomy_level', {}), ('preconditions', []), ('actions', 'bounded_reconnect'),
    ('rollback', []), ('targeted_tests', []), ('runtime_verification', []),
    ('integrity_verification', []), ('recurrence_check', []),
    ('targeted_tests', [True]), ('recurrence_check', ['same', 'same']),
    ('matching_rules', {'category': 'NETWORK'}),
])
def test_v2_schema_rejects_invalid_types_and_empty_contracts(tmp_path, recipe, field, value):
    recipe[field] = value
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, [recipe]))


@pytest.mark.parametrize('field', ['fingerprint', 'category', 'exception'])
def test_matching_rules_types_are_strict(tmp_path, recipe, field):
    recipe['matching_rules'][field] = []
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, [recipe]))


def test_matching_requires_category_or_valid_fingerprint(tmp_path, recipe):
    recipe['matching_rules'].update(category='', fingerprint='')
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, [recipe]))
    recipe['matching_rules']['fingerprint'] = 'x' * 64
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, [recipe]))


@pytest.mark.parametrize('forbidden', sorted(FORBIDDEN_ACTIONS))
def test_hard_safety_actions_cannot_be_declared_or_used_as_rollback(tmp_path, recipe, forbidden):
    recipe['actions'] = [forbidden]
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, [recipe]))
    recipe['actions'] = ['bounded_reconnect']
    recipe['rollback'] = [forbidden]
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, [recipe]))


def test_cannot_remove_safety_prohibition_or_bypass_validation_in_memory(tmp_path, recipe):
    recipe['forbidden_actions'].remove('clear_outbox')
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, [recipe]))
    with pytest.raises(ValueError):
        dry_run(EVENT, [recipe])


def test_recipe_specific_prohibited_actions_are_respected(tmp_path, recipe):
    recipe['forbidden_actions'].append('bounded_reconnect')
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, [recipe]))


@pytest.mark.parametrize(('autonomy', 'risk', 'action', 'decision'), [
    ('A0', 'LOW', 'observe', 'OBSERVE_ONLY'),
    ('A1', 'LOW', 'bounded_reconnect', 'PROPOSED'),
    ('A1', 'MEDIUM', 'bounded_reconnect', 'BLOCKED'),
    ('A1', 'LOW', 'review_log_path_permissions', 'BLOCKED'),
    ('A2', 'MEDIUM', 'review_log_path_permissions', 'PROPOSED'),
    ('A2', 'HIGH', 'review_log_path_permissions', 'BLOCKED'),
    ('A2', 'LOW', 'isolated_code_patch', 'BLOCKED'),
    ('A3', 'HIGH', 'isolated_code_patch', 'REVIEW_REQUIRED'),
    ('A4', 'CRITICAL', 'safe_stop_and_escalate', 'SAFE_STOP'),
])
def test_a0_through_a4_gates_never_execute(recipe, autonomy, risk, action, decision):
    recipe.update(autonomy_level=autonomy, risk=risk, actions=[action])
    result = dry_run(EVENT, [recipe], satisfied_preconditions=attest(recipe))
    assert result['gates'][0]['decision'] == decision
    assert bool(result['proposals']) == (decision == 'PROPOSED')
    assert result['executed'] is False
    if autonomy == 'A3':
        assert 'isolated tests and review' in result['gates'][0]['reason']
        assert result['escalate'] is True
    if autonomy == 'A4':
        assert result['safe_stop'] is result['escalate'] is True


def test_low_confidence_blocks_known_recipe(recipe):
    recipe['confidence'] = .89
    result = dry_run(EVENT, [recipe], satisfied_preconditions=attest(recipe))
    assert result['proposals'] == []
    assert result['gates'][0]['decision'] == 'BLOCKED'
    assert 'confidence' in result['gates'][0]['reason']


@pytest.mark.parametrize('value', [1, 'true', None])
def test_precondition_truthiness_cannot_bypass_boolean_gate(recipe, value):
    supplied = attest(recipe)
    supplied[recipe['preconditions'][0]] = value
    with pytest.raises(ValueError):
        dry_run(EVENT, [recipe], satisfied_preconditions=supplied)


def test_false_precondition_blocks(recipe):
    supplied = attest(recipe)
    supplied[recipe['preconditions'][0]] = False
    assert dry_run(EVENT, [recipe], satisfied_preconditions=supplied)['proposals'] == []


def test_matching_uses_all_declared_rules_and_stable_fingerprint(recipe):
    recipe['matching_rules']['fingerprint'] = fingerprint(EVENT)
    conditions = attest(recipe)
    later = replace(EVENT, timestamp='2026-09-10T00:00:00+00:00')
    assert dry_run(EVENT, [recipe], satisfied_preconditions=conditions) == dry_run(later, [recipe], satisfied_preconditions=conditions)
    for different in (replace(EVENT, component='other'), replace(EVENT, exception='OtherError'),
                      replace(EVENT, message='connection timeout')):
        assert dry_run(different, [recipe], satisfied_preconditions=conditions)['proposals'] == []
    recipe['matching_rules']['category'] = 'CONFIGURATION'
    assert dry_run(EVENT, [recipe], satisfied_preconditions=conditions)['proposals'] == []


@pytest.mark.parametrize(('message', 'category', 'safe_stop'), [
    ('out-of-order trade', 'TERMINAL_BLOCKED', True),
    ('invariant violation', 'INVARIANT_VIOLATION', True),
    ('unexpected frobnication', 'UNKNOWN', True),
])
def test_critical_and_unknown_incidents_escalate_with_and_without_matching_recipe(recipe, message, category, safe_stop):
    event = replace(EVENT, message=message, exception='')
    recipe['matching_rules']['exception'] = ''
    unmatched = dry_run(event, [recipe], satisfied_preconditions=attest(recipe))
    assert unmatched['proposals'] == []
    assert unmatched['escalate'] is True
    assert unmatched['safe_stop'] is safe_stop
    recipe['matching_rules']['category'] = category
    matched = dry_run(event, [recipe], satisfied_preconditions=attest(recipe))
    assert matched['proposals'] == []
    assert matched['escalate'] is True
    assert matched['safe_stop'] is safe_stop


def test_duplicate_recipe_version_rejected_and_multiple_versions_ordered(tmp_path, recipe):
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, [recipe, recipe]))
    older = deepcopy(recipe)
    older['version'] = '1.0.0'
    entries = load_registry(write_registry(tmp_path, [recipe, older]))
    assert [row['version'] for row in dry_run(EVENT, entries, satisfied_preconditions=attest(recipe))['proposals']] == ['1.0.0', '2.0.0']


@pytest.mark.parametrize('version', [True, 0, 3, '2'])
def test_registry_version_is_explicit_and_strict(tmp_path, recipe, version):
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, [recipe], version))


def test_legacy_v1_loader_and_output_are_explicitly_legacy():
    path = ROOT / 'schemas/bugfixer/remediations.v1.json'
    entries = load_registry(path)
    assert entries == json.loads(path.read_text())['entries']
    result = dry_run(EVENT, entries)
    assert result['registry_schema_version'] == 1
    assert result['legacy_registry'] is True
    assert result['proposals'][0]['id'] == 'NETWORK_TIMEOUT_V1'
    assert result['executed'] is False
    assert 'Legacy' in result['reason']


def test_empty_v2_registry_retains_its_schema_version(tmp_path):
    entries = load_registry(write_registry(tmp_path, []))
    result = dry_run(EVENT, entries)
    assert result['registry_schema_version'] == 2
    assert result['legacy_registry'] is False
    assert result['proposals'] == result['gates'] == []


@pytest.mark.parametrize(('field', 'value'), [
    ('mode', 'REPAIR'), ('execution', True), ('live_trading', True), ('auto_remediate', True),
    ('mutate_queue', True), ('mutate_outbox', True), ('reset_attempts', True), ('skip_events', True),
    ('strict_ordering', False), ('determinism', False), ('lookahead_safety', False),
])
def test_recipe_preconditions_cannot_override_policy(recipe, field, value):
    with pytest.raises(SafetyViolation):
        dry_run(EVENT, [recipe], replace(Policy(), **{field: value}), satisfied_preconditions=attest(recipe))


def test_registry_is_bounded_and_rejects_unknown_fields(tmp_path, recipe):
    recipe['command'] = 'untrusted action'
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, [recipe]))
    path = tmp_path / 'oversized.json'
    path.write_bytes(b' ' * 65537)
    with pytest.raises(ValueError, match='size'):
        load_registry(path)
