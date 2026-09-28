"""Versioned recipe validation and proposal gates, never an action dispatcher.

Version 1 is retained as a legacy proposal format. Version 2 requires complete
repair contracts; satisfied preconditions are caller attestations, not evidence
that this module executed or verified a repair.
"""
import json
import math
import os
from pathlib import Path
import re
import stat

from src.bugfixer.model import ErrorClass
from src.bugfixer.processing import Event, classify, fingerprint
from src.bugfixer.safety import Policy

_LEGACY_FIELDS = {'id', 'category', 'exception', 'risk', 'autonomy', 'action', 'verification'}
_LEGACY_ACTIONS = {'bounded_reconnect', 'review_log_path_permissions'}
_FIELDS = {'remediation_id', 'version', 'matching_rules', 'confidence', 'risk',
           'autonomy_level', 'preconditions', 'actions', 'forbidden_actions', 'rollback',
           'targeted_tests', 'runtime_verification', 'integrity_verification', 'recurrence_check'}
# These symbolic names have no executable dispatch implementation.
_ACTIONS = _LEGACY_ACTIONS | {'observe', 'isolated_code_patch', 'safe_stop_and_escalate'}
FORBIDDEN_ACTIONS = frozenset({
    'delete_production_data', 'truncate_production_data', 'clear_queue', 'clear_outbox',
    'reset_attempts', 'skip_events', 'disable_strict_ordering', 'disable_determinism',
    'disable_lookahead_safety', 'test_production_database', 'mutate_production_test_data',
    'invent_data_gaps', 'expose_secrets', 'enable_live_trading', 'enable_execution', 'create_real_orders',
})
_CRITICAL = {'INVARIANT_VIOLATION', 'TERMINAL_BLOCKED'}
_IDENTIFIER = re.compile(r'[A-Z][A-Z0-9_]{1,80}')
_CHECK = re.compile(r'[a-z][a-z0-9_]{0,79}')


class RegistryEntries(list):
    """List-compatible result retaining the version even for an empty registry."""

    def __init__(self, entries, schema_version):
        super().__init__(entries)
        self.schema_version = schema_version


def _names(value, field):
    if (not isinstance(value, list) or not value or len(value) > 100
            or not all(isinstance(item, str) and _CHECK.fullmatch(item) for item in value)
            or len(set(value)) != len(value)):
        raise ValueError('invalid recipe ' + field)
    return value


def _category(value, *, optional=False):
    if not isinstance(value, str):
        raise ValueError('invalid recipe category')
    if not (optional and value == ''):
        ErrorClass(value)


def _validate_legacy(row):
    if not isinstance(row, dict) or set(row) != _LEGACY_FIELDS:
        raise ValueError('invalid legacy registry entry')
    _category(row['category'])
    if (row['category'] in {'UNKNOWN', *_CRITICAL}
            or not isinstance(row['risk'], str) or row['risk'] not in {'LOW', 'MEDIUM'}
            or not isinstance(row['autonomy'], str) or row['autonomy'] not in {'A1', 'A2'}
            or not isinstance(row['action'], str) or row['action'] not in _LEGACY_ACTIONS
            or not isinstance(row['exception'], str)):
        raise ValueError('unsafe legacy remediation entry')
    _names(row['verification'], 'verification')
    return row['id'], None


def _validate_recipe(row):
    if not isinstance(row, dict) or set(row) != _FIELDS:
        raise ValueError('invalid v2 registry entry')
    version = row['version']
    if not isinstance(version, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', version):
        raise ValueError('invalid recipe version')
    rules = row['matching_rules']
    if not isinstance(rules, dict) or set(rules) != {'fingerprint', 'category', 'exception'}:
        raise ValueError('invalid matching rules')
    _category(rules['category'], optional=True)
    if (not isinstance(rules['fingerprint'], str)
            or rules['fingerprint'] and not re.fullmatch(r'[0-9a-f]{64}', rules['fingerprint'])
            or not isinstance(rules['exception'], str) or len(rules['exception']) > 256
            or not (rules['fingerprint'] or rules['category'])):
        raise ValueError('matching requires a fingerprint or category and exact optional exception')
    confidence = row['confidence']
    if type(confidence) not in {int, float} or not 0 <= confidence <= 1 or not math.isfinite(confidence):
        raise ValueError('invalid recipe confidence')
    if not isinstance(row['risk'], str) or row['risk'] not in {'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'}:
        raise ValueError('invalid recipe risk')
    if not isinstance(row['autonomy_level'], str) or row['autonomy_level'] not in {'A0', 'A1', 'A2', 'A3', 'A4'}:
        raise ValueError('invalid recipe autonomy')
    for field in ('preconditions', 'actions', 'forbidden_actions', 'rollback', 'targeted_tests',
                  'runtime_verification', 'integrity_verification', 'recurrence_check'):
        _names(row[field], field)
    forbidden = set(row['forbidden_actions'])
    if not FORBIDDEN_ACTIONS <= forbidden:
        raise ValueError('recipe must preserve every hard safety prohibition')
    if not set(row['actions']) <= _ACTIONS or set(row['actions']) & forbidden:
        raise ValueError('forbidden or unsupported recipe action')
    if set(row['rollback']) & FORBIDDEN_ACTIONS:
        raise ValueError('forbidden rollback action')
    return row['remediation_id'], version


def _validate_entries(entries, version):
    if type(version) is not int or version not in {1, 2}:
        raise ValueError('unsupported registry schema')
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError('registry entries must be a bounded list')
    ids = set()
    for row in entries:
        identifier, recipe_version = (_validate_legacy(row) if version == 1 else _validate_recipe(row))
        if (not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier)
                or (identifier, recipe_version) in ids):
            raise ValueError('invalid or duplicate remediation ID and version')
        ids.add((identifier, recipe_version))
    return entries


def load_registry(path: Path) -> list[dict]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError('registry must be a regular file')
        raw = handle.read(65537)
    if len(raw) > 65536:
        raise ValueError('registry exceeds size limit')
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError, UnicodeError):
        raise ValueError('invalid registry JSON') from None
    if (not isinstance(payload, dict) or set(payload) != {'schema_version', 'entries'}
            or type(payload['schema_version']) is not int or payload['schema_version'] not in {1, 2}):
        raise ValueError('unsupported registry schema')
    return RegistryEntries(_validate_entries(payload['entries'], payload['schema_version']), payload['schema_version'])


def _gate(row, category, satisfied):
    autonomy = row['autonomy_level']
    result = {'remediation_id': row['remediation_id'], 'version': row['version'],
              'autonomy_level': autonomy, 'executed': False, 'escalate': False}
    if autonomy == 'A4' or category in _CRITICAL or row['risk'] == 'CRITICAL':
        return {**result, 'decision': 'SAFE_STOP', 'escalate': True,
                'reason': 'Critical integrity requires preserved evidence, safe stop and escalation'}
    if category == 'UNKNOWN':
        return {**result, 'decision': 'SAFE_STOP', 'escalate': True,
                'reason': 'Unknown incidents require investigation before repair proposals'}
    if autonomy == 'A0':
        return {**result, 'decision': 'OBSERVE_ONLY', 'reason': 'A0 permits observation only'}
    if autonomy == 'A3':
        return {**result, 'decision': 'REVIEW_REQUIRED', 'escalate': True,
                'reason': 'Generated patches require isolated tests and review; this foundation has no patch executor'}
    if row['confidence'] < .9:
        return {**result, 'decision': 'BLOCKED', 'reason': 'Recipe confidence is below 0.9'}
    allowed_risks = {'LOW'} if autonomy == 'A1' else {'LOW', 'MEDIUM'}
    allowed_actions = {'observe', 'bounded_reconnect'} if autonomy == 'A1' else _LEGACY_ACTIONS | {'observe'}
    if row['risk'] not in allowed_risks or not set(row['actions']) <= allowed_actions:
        return {**result, 'decision': 'BLOCKED', 'reason': 'Risk or action exceeds this autonomy level'}
    missing = [name for name in row['preconditions'] if satisfied.get(name) is not True]
    if missing:
        return {**result, 'decision': 'BLOCKED', 'missing_preconditions': missing,
                'reason': 'Every declared precondition requires an explicit satisfied attestation'}
    return {**result, 'decision': 'PROPOSED',
            'reason': 'Known recipe eligible for review only; execution and repair verification remain unavailable'}


def dry_run(event: Event, registry: list[dict], policy: Policy = Policy(), *,
            satisfied_preconditions: dict[str, bool] | None = None) -> dict:
    policy.verify()
    if not isinstance(registry, list):
        raise ValueError('registry must be a list')
    # Revalidate in-memory entries too, so mutation cannot bypass the loader.
    inferred = 2 if registry and isinstance(registry[0], dict) and 'remediation_id' in registry[0] else 1
    version = getattr(registry, 'schema_version', inferred)
    _validate_entries(registry, version)
    satisfied = {} if satisfied_preconditions is None else satisfied_preconditions
    if (not isinstance(satisfied, dict)
            or not all(isinstance(key, str) and _CHECK.fullmatch(key) and type(value) is bool
                       for key, value in satisfied.items())):
        raise ValueError('precondition attestations require named boolean values')
    category = classify(event).category
    result = {'mode': 'DRY_RUN', 'executed': False, 'category': category,
              'registry_schema_version': version, 'legacy_registry': version == 1,
              'escalate': category in _CRITICAL or category == 'UNKNOWN',
              'safe_stop': category in _CRITICAL or category == 'UNKNOWN',
              'auto_remediation': 'NOT_SAFE'}
    if version == 1:
        matches = [row for row in registry if row['category'] == category and
                   (not row['exception'] or row['exception'] == event.exception)]
        return {**result, 'proposals': matches,
                'reason': 'Legacy v1 proposals lack complete repair contracts; no operational action executor'}
    identity = fingerprint(event)
    matches = [row for row in registry if
               (not row['matching_rules']['category'] or row['matching_rules']['category'] == category) and
               (not row['matching_rules']['exception'] or row['matching_rules']['exception'] == event.exception) and
               (not row['matching_rules']['fingerprint'] or row['matching_rules']['fingerprint'] == identity)]
    matches.sort(key=lambda row: (row['remediation_id'], tuple(map(int, row['version'].split('.')))))
    gates = [_gate(row, category, satisfied) for row in matches]
    return {**result, 'proposals': [row for row, gate in zip(matches, gates) if gate['decision'] == 'PROPOSED'],
            'gates': gates, 'escalate': category in _CRITICAL or category == 'UNKNOWN' or any(g['escalate'] for g in gates),
            'safe_stop': category in _CRITICAL or category == 'UNKNOWN' or any(g['decision'] == 'SAFE_STOP' for g in gates),
            'reason': 'Complete recipe contracts and proposal gates only; no action execution or verified-repair claim'}
