"""src/tim_incident/policy.py and config/tim_checkup.json: strict loading, fixed label allowlist, settings validation."""
from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

import pytest

from src.task_governance.repository_names import PRODUCTION_REPOSITORY
from src.tim_incident import policy as policy_module
from src.tim_incident.policy import (
    BASE_LABELS, CHAIN_CLASSES, CHECK_NAMES, CLASS_NAMES, CONTROL_LABELS, LABEL_ALLOWLIST, NOT_CONFIGURED,
    Controls, PolicyError, load_policy, load_settings, policy_from_dict,
)
from src.tim_incident.redaction import final_scan

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config' / 'tim_checkup.json'
REPO_UNITS = ('tim-candle-finalizer.timer', 'tim-rolling-liveness.timer', 'tim-maintenance.timer',
              'tim-coverage-worker.timer', 'tim-backup.timer', 'tim-restore-test.timer', 'tim-server-health.timer',
              'tim-watchdog.service')


def raw() -> dict:
    return json.loads(CONFIG.read_text(encoding='utf-8'))


def write(tmp_path: Path, data) -> Path:
    path = tmp_path / 'tim_checkup.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


# --- shipped config ------------------------------------------------------------------------------------------------

def test_shipped_config_loads():
    policy = load_policy(CONFIG)
    assert policy == load_policy()                       # default path is the shipped file
    assert policy.version == 1
    assert policy.normalized_repository == PRODUCTION_REPOSITORY
    assert policy.host == 'tim-core-01'
    assert policy.chain_order == CHAIN_CLASSES
    assert tuple(policy.classes) == CLASS_NAMES
    assert policy.independent_classes == ('SAFETY', 'BACKUP', 'TIME_SYNC', 'UNIT', 'SELFTEST')
    assert policy.classes['UNIT'].units == REPO_UNITS
    for name in REPO_UNITS:
        assert (ROOT / 'ops' / 'systemd' / name).is_file(), name
    assert policy.network.probes == (('stream.binance.com', 9443), ('api.binance.com', 443), ('api.github.com', 443))
    assert policy.network.matches('OSError: [Errno 101] Network is unreachable')
    assert policy.network.matches('Binance public stream disconnected (timeout); retrying in 5s')
    assert not policy.network.matches('ValueError: bad candle')
    assert policy.hysteresis.window_minutes == 16 and policy.hysteresis.resolve_clean_runs == 2
    assert policy.limits.evidence_comment_bytes == 49152
    assert policy.rate_limits.new_issues_per_hour == 3 and policy.rate_limits.changed_per_episode == 3


def test_shipped_classes_match_design_table():
    classes = load_policy(CONFIG).classes
    expected = {
        'HEALTH_STALE': ('priority:p1', 'incident:unknown'), 'DISK': ('incident:ops',), 'DATABASE': ('priority:p1',),
        'RUNTIME': ('priority:p1',), 'NETWORK': ('incident:network',), 'DATA_FLOW': ('priority:p1',),
        'WATCHDOG': ('priority:p1',), 'SAFETY': ('priority:p1', 'incident:safety'), 'BACKUP': ('priority:p1',),
        'TIME_SYNC': ('incident:ops',), 'UNIT': ('incident:ops',), 'SELFTEST': ('selftest',),
    }
    qwen = {'HEALTH_STALE', 'DATABASE', 'RUNTIME', 'DATA_FLOW', 'WATCHDOG', 'SAFETY', 'BACKUP', 'SELFTEST'}
    for name, cls in classes.items():
        assert cls.labels == expected[name], name
        assert cls.issue_labels[:2] == BASE_LABELS
        assert cls.qwen == (name in qwen), name
        assert set(cls.checks) <= CHECK_NAMES
        assert not final_scan(cls.remedy)
    assert classes['DATABASE'].open_red_samples == 3 and classes['DATA_FLOW'].open_red_samples == 3
    assert classes['RUNTIME'].open_red_samples == 3 and classes['RUNTIME'].open_runs == 2
    assert classes['UNIT'].open_runs == 2 and classes['SAFETY'].open_red_samples == 1
    assert set(classes['WATCHDOG'].checks) == {'watchdog.single_collector', 'watchdog.postgres_listener',
                                               'watchdog.queue_age'}


def test_policy_is_immutable():
    policy = load_policy(CONFIG)
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.host = 'elsewhere'
    with pytest.raises(TypeError):
        policy.classes['DISK'] = policy.classes['UNIT']
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.classes['DISK'].labels = ('priority:p0',)


# --- strict loading ---------------------------------------------------------------------------------------------------

def _set(data: dict, path: tuple, value) -> dict:
    data = copy.deepcopy(data)
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return data


def _drop(data: dict, path: tuple) -> dict:
    data = copy.deepcopy(data)
    target = data
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    return data


@pytest.mark.parametrize('path', [
    ('agent',), ('label_allowlist',), ('classes', 'DISK', 'priority'), ('network', 'dns'), ('hysteresis', 'x'),
    ('limits', 'request_bytes'), ('rate_limits', 'burst'), ('health', 'journal_unit'), ('classes', 'NEW_CLASS'),
])
def test_unknown_keys_rejected(tmp_path, path):
    with pytest.raises(PolicyError, match='unknown key'):
        load_policy(write(tmp_path, _set(raw(), path, {} if path[-1] == 'NEW_CLASS' else 1)))


@pytest.mark.parametrize('path', [
    ('version',), ('classes', 'UNIT'), ('classes', 'DISK', 'remedy'), ('network', 'outage_hosts'), ('evidence',),
])
def test_missing_keys_rejected(tmp_path, path):
    with pytest.raises(PolicyError, match='missing key'):
        load_policy(write(tmp_path, _drop(raw(), path)))


@pytest.mark.parametrize('path, value', [
    (('version',), '1'),
    (('version',), 2),
    (('version',), True),
    (('repository',), 'not a repo'),
    (('host',), 'tim core'),
    (('postgres_unit',), 'postgresql'),
    (('classes', 'DATA_FLOW', 'open_red_samples'), True),
    (('classes', 'DATA_FLOW', 'open_red_samples'), 3.0),
    (('classes', 'DATA_FLOW', 'open_red_samples'), -1),
    (('classes', 'DATA_FLOW', 'qwen'), 'yes'),
    (('classes', 'DATA_FLOW', 'labels'), 'priority:p1'),
    (('classes', 'DATA_FLOW', 'checks'), ['candle_freshness', 'candle_freshness']),
    (('classes', 'DATA_FLOW', 'checks'), ['candle_freshnes']),
    (('classes', 'DATA_FLOW', 'checks'), []),
    (('classes', 'DATA_FLOW', 'units'), ['tim-runtime']),
    (('classes', 'DATA_FLOW', 'category'), 'other'),
    (('classes', 'DISK', 'open_red_samples'), 0),
    (('classes', 'DISK', 'remedy'), 'cc @uezeyiraydin-cell'),
    (('classes', 'DISK', 'remedy'), 'siehe <!-- marker -->'),
    (('classes', 'DISK', 'remedy'), 'Token 9fK2mPx7Lw4Rt8Vn3Bc6Hs1Dg5Jy0EaQzX'),
    (('chain_order',), ['DISK', 'HEALTH_STALE', 'DATABASE', 'RUNTIME', 'NETWORK', 'DATA_FLOW']),
    (('chain_order',), ['HEALTH_STALE', 'DISK', 'DATABASE', 'RUNTIME', 'NETWORK', 'DATA_FLOW', 'WATCHDOG', 'SAFETY']),
    (('network', 'probes'), [['api.github.com', '443']]),
    (('network', 'probes'), [['api.github.com', 70000]]),
    (('network', 'probes'), [['api.github.com']]),
    (('network', 'outage_hosts'), ['example.com']),
    (('network', 'runtime_patterns'), ['Errno (101']),
    (('network', 'probe_timeout_seconds'), 0),
    (('hysteresis', 'reopen_cooldown_hours'), '2'),
    (('hysteresis', 'resolve_max_clean_runs'), 1),
    (('limits', 'journal_lines'), 80.5),
    (('rate_limits', 'writes_per_run'), None),
    (('disk', 'statvfs_paths'), ['var']),
    (('disk', 'red_percent'), 101),
    (('evidence', 'statvfs_paths'), '/'),
])
def test_wrong_types_and_values_rejected(tmp_path, path, value):
    with pytest.raises(PolicyError):
        load_policy(write(tmp_path, _set(raw(), path, value)))


@pytest.mark.parametrize('label', ['status:ready', 'agent:codex', 'priority:p0', 'governance', 'checkup:silence',
                                   'incident:code', 'incident', 'source:tim-checkup', 'selftest', 'bug'])
def test_label_outside_allowlist_or_reserved_rejected(tmp_path, label):
    with pytest.raises(PolicyError, match='labels'):
        load_policy(write(tmp_path, _set(raw(), ('classes', 'DISK', 'labels'), ['incident:ops', label])))


def test_selftest_label_rules(tmp_path):
    with pytest.raises(PolicyError):
        load_policy(write(tmp_path, _set(raw(), ('classes', 'SELFTEST', 'labels'), ['selftest', 'priority:p1'])))
    with pytest.raises(PolicyError):
        load_policy(write(tmp_path, _set(raw(), ('classes', 'SELFTEST', 'labels'), [])))


def test_allowlist_is_code_and_cannot_be_extended_from_config(tmp_path):
    assert isinstance(LABEL_ALLOWLIST, frozenset)
    assert LABEL_ALLOWLIST == {'incident', 'source:tim-checkup', 'priority:p1', 'incident:network', 'incident:ops',
                               'incident:code', 'incident:unknown', 'incident:safety', 'selftest'}
    assert CONTROL_LABELS == {'checkup:silence', 'checkup:pause-qwen', 'checkup:selftest'}
    assert not LABEL_ALLOWLIST & CONTROL_LABELS
    assert not any(label.startswith(('status:', 'agent:')) or label in {'priority:p0', 'governance'}
                   for label in LABEL_ALLOWLIST)
    data = raw()
    data['label_allowlist'] = ['status:ready']
    with pytest.raises(PolicyError, match='unknown key'):
        load_policy(write(tmp_path, data))
    assert 'status:ready' not in policy_module.LABEL_ALLOWLIST


def test_duplicate_json_keys_and_bad_files_rejected(tmp_path):
    path = tmp_path / 'dup.json'
    text = CONFIG.read_text(encoding='utf-8')
    path.write_text(text.replace('"host": "tim-core-01",', '"host": "tim-core-01", "host": "other",'), encoding='utf-8')
    with pytest.raises(PolicyError, match='duplicate key'):
        load_policy(path)
    path.write_text('{not json', encoding='utf-8')
    with pytest.raises(PolicyError, match='not valid JSON'):
        load_policy(path)
    with pytest.raises(PolicyError, match='unreadable'):
        load_policy(tmp_path / 'missing.json')
    with pytest.raises(PolicyError):
        policy_from_dict([])


def test_policy_from_dict_matches_file():
    assert policy_from_dict(raw()) == load_policy(CONFIG)


# --- controls ---------------------------------------------------------------------------------------------------------

def test_controls():
    controls = Controls('open', ['checkup:silence', 'checkup:selftest', 'bug'])
    assert controls.open and controls.silenced and controls.selftest and not controls.pause_qwen
    assert isinstance(controls.labels, frozenset)
    assert not NOT_CONFIGURED.open and NOT_CONFIGURED.authority == 'not_configured'
    with pytest.raises(ValueError):
        Controls('revoked', frozenset())
    with pytest.raises(dataclasses.FrozenInstanceError):
        controls.authority = 'closed'


# --- settings ---------------------------------------------------------------------------------------------------------

FULL = {
    'TIM_CHECKUP_REPORTING': 'on', 'TIM_CHECKUP_DIAGNOSIS': 'off', 'TIM_CHECKUP_APP_ID': '123456',
    'TIM_CHECKUP_INSTALLATION_ID': '7890123', 'TIM_CHECKUP_AUTHORITY_ISSUE': '170', 'TIM_CHECKUP_WATCH_ISSUE': '171',
    'TIM_CHECKUP_REPORTER_LOGIN': 'tim-reporter[bot]', 'TIM_CHECKUP_OWNER_LOGIN': 'uezeyiraydin-cell',
    'CREDENTIALS_DIRECTORY': '/run/credentials/tim-checkup.service',
    'TIM_DATABASE_SECRET_FILE': '/etc/tim/database-password',
}


def test_settings_default_off():
    settings = load_settings({})
    assert settings.reporting == 'off' and settings.diagnosis == 'off' and settings.requested == 'off'
    assert settings.problems == () and settings.reason == '' and not settings.complete
    assert settings.app_id is None and settings.watch_issue is None


def test_settings_full():
    settings = load_settings(FULL)
    assert settings.reporting == 'on' and settings.problems == () and settings.complete
    assert (settings.app_id, settings.installation_id, settings.authority_issue, settings.watch_issue) == (
        123456, 7890123, 170, 171)
    assert settings.reporter_login == 'tim-reporter[bot]' and settings.owner_login == 'uezeyiraydin-cell'
    assert settings.credentials_directory == '/run/credentials/tim-checkup.service'
    assert settings.database_secret_file == '/etc/tim/database-password'
    assert load_settings({**FULL, 'TIM_CHECKUP_REPORTING': 'dry-run'}).reporting == 'dry-run'
    assert load_settings({**FULL, 'TIM_CHECKUP_REPORTING': ' On '}).reporting == 'on'
    assert load_settings({**FULL, 'TIM_CHECKUP_DIAGNOSIS': 'on'}).diagnosis == 'on'
    without_watch = {key: value for key, value in FULL.items() if key != 'TIM_CHECKUP_WATCH_ISSUE'}
    assert load_settings(without_watch).reporting == 'on'


@pytest.mark.parametrize('name, value', [
    ('TIM_CHECKUP_REPORTING', 'yes'),
    ('TIM_CHECKUP_REPORTING', 'ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8'),
    ('TIM_CHECKUP_DIAGNOSIS', 'maybe'),
    ('TIM_CHECKUP_APP_ID', '12a'),
    ('TIM_CHECKUP_APP_ID', '-5'),
    ('TIM_CHECKUP_APP_ID', '0'),
    ('TIM_CHECKUP_INSTALLATION_ID', '1e3'),
    ('TIM_CHECKUP_AUTHORITY_ISSUE', '#170'),
    ('TIM_CHECKUP_WATCH_ISSUE', '170'),                      # same issue as the authority
    ('TIM_CHECKUP_REPORTER_LOGIN', 'tim-reporter'),          # an app login ends in [bot]
    ('TIM_CHECKUP_REPORTER_LOGIN', 'tim reporter[bot]'),
    ('TIM_CHECKUP_OWNER_LOGIN', 'uezeyiraydin-cell[bot]'),
    ('TIM_CHECKUP_OWNER_LOGIN', '-leading-dash'),
])
def test_invalid_settings_force_reporting_off(name, value):
    settings = load_settings({**FULL, name: value})
    assert settings.reporting == 'off' and settings.diagnosis == 'off'
    assert settings.problems and name in settings.reason
    assert value not in settings.reason                      # never echo a value (it might be a pasted secret)


@pytest.mark.parametrize('mode', ['on', 'dry-run'])
@pytest.mark.parametrize('name', ['TIM_CHECKUP_APP_ID', 'TIM_CHECKUP_INSTALLATION_ID', 'TIM_CHECKUP_AUTHORITY_ISSUE',
                                  'TIM_CHECKUP_REPORTER_LOGIN', 'TIM_CHECKUP_OWNER_LOGIN'])
def test_incomplete_settings_force_reporting_off(mode, name):
    environ = {key: value for key, value in FULL.items() if key != name}
    settings = load_settings({**environ, 'TIM_CHECKUP_REPORTING': mode})
    assert settings.reporting == 'off' and settings.requested == mode
    assert settings.problems == (f'{name} missing',)


def test_relative_paths_ignored():
    settings = load_settings({**FULL, 'CREDENTIALS_DIRECTORY': 'run/creds', 'TIM_DATABASE_SECRET_FILE': ''})
    assert settings.credentials_directory is None and settings.database_secret_file is None
    assert settings.reporting == 'on'


# --- independence (design E8) -------------------------------------------------------------------------------------------

FORBIDDEN_IMPORTS = ('src.bugfixer', 'src.graph_mcp', 'src.operational', 'src.agents')


def _imports(path: Path) -> set[str]:
    import ast

    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(('.' * node.level) + (node.module or ''))
    return names


def test_tim_incident_never_imports_worker_editable_modules():
    package = ROOT / 'src' / 'tim_incident'
    assert (package / '__init__.py').read_text(encoding='utf-8').strip() == ''
    for path in sorted(package.glob('*.py')):
        for name in _imports(path):
            assert not name.startswith(FORBIDDEN_IMPORTS), (path.name, name)
            assert not name.startswith('..'), (path.name, name)
    # The redaction is a self-contained copy: standard library only.
    assert not {name for name in _imports(package / 'redaction.py') if name.startswith(('src', '.'))}
