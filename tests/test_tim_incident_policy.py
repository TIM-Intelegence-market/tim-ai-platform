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
    ('agent', 'cloud_model'), ('label_allowlist',), ('classes', 'DISK', 'priority'), ('network', 'dns'),
    ('hysteresis', 'x'), ('limits', 'result_bytes'), ('rate_limits', 'burst'), ('health', 'journal_unit'),
    ('classes', 'NEW_CLASS'), ('agent', 'measured', 'tool_calls_ok'), ('agent', 'gate', 'psi_irq'),
])
def test_unknown_keys_rejected(tmp_path, path):
    with pytest.raises(PolicyError, match='unknown key'):
        load_policy(write(tmp_path, _set(raw(), path, {} if path[-1] == 'NEW_CLASS' else 1)))


@pytest.mark.parametrize('path', [
    ('version',), ('classes', 'UNIT'), ('classes', 'DISK', 'remedy'), ('network', 'outage_hosts'), ('evidence',),
    ('agent',), ('hold_checks',), ('limits', 'request_bytes'), ('agent', 'model_digest'), ('agent', 'measured'),
    ('agent', 'measured', 'cache_ok'), ('agent', 'gate', 'psi_io'), ('agent', 'resolver'),
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


# --- agent block, hold_checks, request_bytes (PR-2, design C.4) -----------------------------------------------------------

from src.tim_incident.policy import (  # noqa: E402
    AGENT_TOOL_MODES, CALIBRATION_KEYS, MIN_EVIDENCE_TOKENS, Budget, agent_budget, compute_budget,
)

CALIBRATED = {
    'model_digest': 'a' * 64, 'model_config_sha256': 'b' * 64,
    'measured': {'prompt_tok_s': 20, 'gen_tok_s': 6, 'cache_ok': True},
    'ollama_allowed_cpus': '2-3,6-7', 'resolver': 'public',
}


def calibrated(**changes) -> dict:
    data = raw()
    data['agent'].update(copy.deepcopy(CALIBRATED))
    for key, value in changes.items():
        data['agent'][key] = value
    return data


def test_shipped_agent_block_is_uncalibrated_and_fail_closed():
    policy = load_policy(CONFIG)
    agent = policy.agent
    assert agent.model == 'qwen3-coder:30b' and agent.endpoint == 'http://127.0.0.2:11434' and agent.port == 11434
    assert agent.tool_mode == 'native' and agent.num_ctx == 16384 and agent.num_thread == 2
    assert (agent.per_call_timeout_seconds, agent.deadline_seconds, agent.evidence_tokens_max) == (420, 900, 4096)
    assert (agent.tool_output_chars, agent.ctx_stop_ratio) == (4000, 0.75)
    assert (agent.num_predict_round, agent.num_predict_final, agent.round_prompt_tokens) == (256, 768, 1300)
    assert (agent.max_tool_calls, agent.max_tool_calls_per_round, agent.max_searches, agent.max_fetches) == (12, 3, 3, 4)
    assert (agent.daily_limit, agent.per_episode, agent.attempts) == (6, 3, 2)
    assert (agent.gate.min_mem_available_gib, agent.gate.max_load1) == (26, 4)
    assert (agent.gate.psi_cpu, agent.gate.psi_io, agent.gate.psi_memory) == (40, 20, 5)
    # values only the server can measure ship as null
    assert agent.model_digest is None and agent.model_config_sha256 is None
    assert agent.measured.prompt_tok_s is None and agent.measured.gen_tok_s is None and agent.measured.cache_ok is None
    assert agent.ollama_allowed_cpus is None and agent.resolver is None
    assert agent.root_owned is False                    # git_log stays off until P0/P3 confirm root ownership
    assert not agent.calibrated and agent.missing_calibration == CALIBRATION_KEYS
    budget = agent_budget(agent)
    assert budget.mode == 'not-calibrated' and not budget.go and budget.max_rounds == 0
    assert policy.hold_checks == ('queue_age', 'cursor_age', 'data_age')
    assert policy.limits.request_bytes == 65536


def test_shipped_agent_lists():
    policy = load_policy(CONFIG)
    agent = policy.agent
    assert agent.fetch_domains == (
        'docs.python.org', 'peps.python.org', 'pypi.org', 'github.com', 'raw.githubusercontent.com',
        'www.postgresql.org', 'magicstack.github.io', 'developers.binance.com', 'manpages.debian.org',
        'www.freedesktop.org', 'stackoverflow.com')
    for unit in {unit for cls in policy.classes.values() if cls.qwen for unit in cls.units}:
        assert unit in agent.units_allowlist
    assert policy.postgres_unit in agent.units_allowlist
    assert 'tim-qwen-diagnose.service' not in agent.units_allowlist
    for word in ('python', 'asyncpg', 'postgresql', 'systemd', 'binance', 'websocket', 'timeout'):
        assert word in agent.query_vocabulary
    assert all(word == word.lower() and len(word) <= 40 for word in agent.query_vocabulary)
    assert not any(final_scan(word) for word in agent.query_vocabulary)


def test_calibrated_agent_block_loads():
    agent = policy_from_dict(calibrated()).agent
    assert agent.calibrated and agent.missing_calibration == ()
    budget = agent_budget(agent)
    assert budget.go and budget.mode == 'native' and budget.max_rounds == 4
    assert policy_from_dict(calibrated(model_digest='sha256:' + 'c' * 64)).agent.calibrated
    assert policy_from_dict(calibrated(resolver='192.168.1.1')).agent.resolver == '192.168.1.1'
    assert policy_from_dict(calibrated(resolver='127.0.0.53')).agent.resolver == '127.0.0.53'
    assert policy_from_dict(calibrated(ollama_allowed_cpus='2,3')).agent.ollama_allowed_cpus == '2,3'


@pytest.mark.parametrize('key', ['model_digest', 'model_config_sha256', 'ollama_allowed_cpus', 'resolver'])
def test_each_missing_calibration_value_is_fail_closed(key):
    agent = policy_from_dict(calibrated(**{key: None})).agent
    assert not agent.calibrated and agent.missing_calibration == (key,)
    assert agent_budget(agent).mode == 'not-calibrated'


@pytest.mark.parametrize('key', ['prompt_tok_s', 'gen_tok_s', 'cache_ok'])
def test_each_missing_measurement_is_fail_closed(key):
    data = calibrated()
    data['agent']['measured'][key] = None
    agent = policy_from_dict(data).agent
    assert agent.missing_calibration == (f'measured.{key}',) and agent_budget(agent).mode == 'not-calibrated'


@pytest.mark.parametrize('path, value', [
    (('agent', 'model'), 'qwen3-coder:480b-cloud'),
    (('agent', 'model'), 'llama3:8b'),
    (('agent', 'model_digest'), 'A' * 64),
    (('agent', 'model_digest'), 'a' * 63),
    (('agent', 'model_digest'), ''),
    (('agent', 'model_config_sha256'), 'sha256:' + 'a' * 64),
    (('agent', 'endpoint'), 'http://127.0.0.1:11434'),
    (('agent', 'endpoint'), 'https://127.0.0.2:11434'),
    (('agent', 'endpoint'), 'http://localhost:11434'),
    (('agent', 'endpoint'), 'http://127.0.0.2:99999'),
    (('agent', 'endpoint'), 'http://ollama.com:443'),
    (('agent', 'tool_mode'), 'cloud'),
    (('agent', 'measured', 'prompt_tok_s'), 0),
    (('agent', 'measured', 'prompt_tok_s'), '20'),
    (('agent', 'measured', 'cache_ok'), 'yes'),
    (('agent', 'ollama_allowed_cpus'), 'all'),
    (('agent', 'ollama_allowed_cpus'), '3-2'),
    (('agent', 'ollama_allowed_cpus'), ''),
    (('agent', 'resolver'), '0.0.0.0'),
    (('agent', 'resolver'), '224.0.0.1'),
    (('agent', 'resolver'), 'dns.example'),
    (('agent', 'resolver'), '192.168.001.1'),
    (('agent', 'num_ctx'), 1024),
    (('agent', 'num_thread'), 0),
    (('agent', 'num_thread'), True),
    (('agent', 'deadline_seconds'), 300),
    (('agent', 'ctx_stop_ratio'), 1.0),
    (('agent', 'max_tool_calls_per_round'), 20),
    (('agent', 'attempts'), 0),
    (('agent', 'units_allowlist'), ['tim-runtime.service']),        # misses units of qwen classes
    (('agent', 'units_allowlist'), ['tim-runtime']),
    (('agent', 'fetch_domains'), ['docs.python.org', '127.0.0.1']),
    (('agent', 'fetch_domains'), ['https://pypi.org']),
    (('agent', 'fetch_domains'), ['Docs.Python.org']),
    (('agent', 'fetch_domains'), ['pypi.org', 'pypi.org']),
    (('agent', 'fetch_domains'), []),
    (('agent', 'query_vocabulary'), ['python', 'two words']),
    (('agent', 'query_vocabulary'), ['Python']),
    (('agent', 'query_vocabulary'), ['x' * 41]),
    (('agent', 'gate', 'psi_cpu'), 101),
    (('agent', 'gate', 'max_load1'), None),
    (('agent', 'root_owned'), 'yes'),
    (('agent', 'root_owned'), None),
    (('agent', 'root_owned'), 1),
    (('hold_checks',), ['queue_age', 'watchdog.cursor_age']),
    (('hold_checks',), ['made_up']),
    (('hold_checks',), []),
    (('limits', 'request_bytes'), 1024),
    (('limits', 'request_bytes'), 10 ** 6),
])
def test_agent_wrong_values_rejected(tmp_path, path, value):
    with pytest.raises(PolicyError):
        load_policy(write(tmp_path, _set(raw(), path, value)))


def test_agent_error_messages_name_key_not_value(tmp_path):
    secret = 'ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8'
    with pytest.raises(PolicyError) as caught:
        load_policy(write(tmp_path, _set(raw(), ('agent', 'model_digest'), secret)))
    assert 'agent.model_digest' in str(caught.value) and secret not in str(caught.value)


# --- budget formula (design section 7) ---------------------------------------------------------------------------------

def test_budget_design_examples():
    fast = compute_budget(20, 6, cache_ok=True)
    assert fast.mode == 'native' and fast.go and fast.max_rounds == 4
    assert fast.evidence_tokens == 4096 and fast.evidence_chars == 3 * 4096
    assert fast.t_initial == pytest.approx(4096 / 20 + 256 / 6)
    assert fast.t_round == pytest.approx(1300 / 20 + 256 / 6)
    assert fast.t_final == pytest.approx(768 / 6)
    medium = compute_budget(15, 4, cache_ok=True)
    assert medium.mode == 'native' and medium.max_rounds == 2 and medium.evidence_tokens == 3150
    slow = compute_budget(10, 3, cache_ok=True)
    assert slow.mode == 'no-go' and not slow.go and slow.max_rounds == 0 and slow.evidence_tokens == 2100


def test_budget_go_no_go_table():
    # broken tool calls: schema mode, same rounds
    schema = compute_budget(20, 6, cache_ok=True, tool_calls_ok=False)
    assert schema.mode == 'schema' and schema.max_rounds == 4
    # fewer than 2 rounds, but one call fits into 0.8 * T: einschuss
    one = compute_budget(12, 12, cache_ok=True, deadline=500)
    assert one.max_rounds == 0 and one.mode == 'einschuss' and one.go
    assert one.t_initial + one.t_final <= 0.8 * 420
    # no cache: tool rounds are not valid, einschuss only if one call fits
    assert compute_budget(50, 20, cache_ok=False).mode == 'einschuss'
    assert compute_budget(20, 6, cache_ok=False).mode == 'no-go'
    # RED during the measurement is always no-go
    assert compute_budget(50, 20, cache_ok=True, red_during_measurement=True).mode == 'no-go'
    # rounds are capped
    assert compute_budget(1000, 1000, cache_ok=True).max_rounds == 6
    assert compute_budget(1000, 1000, cache_ok=True, max_rounds_cap=3).max_rounds == 3


@pytest.mark.parametrize('p, g', [(0, 6), (20, 0), (-1, 6), (float('nan'), 6), (float('inf'), 6), (None, 6),
                                  (True, 6), ('20', 6)])
def test_budget_invalid_measurement_is_no_go(p, g):
    budget = compute_budget(p, g, cache_ok=True)
    assert budget.mode == 'no-go' and not budget.go and budget.max_rounds == 0


def test_budget_tiny_evidence_is_no_go():
    budget = compute_budget(2, 50, cache_ok=True)      # E = floor(0.5 * 420 * 2) = 420 tokens
    assert budget.evidence_tokens < MIN_EVIDENCE_TOKENS and budget.mode == 'no-go'


def test_budget_is_pure_and_frozen():
    assert compute_budget(20, 6, cache_ok=True) == compute_budget(20, 6, cache_ok=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        compute_budget(20, 6, cache_ok=True).max_rounds = 6
    assert isinstance(compute_budget(20, 6, cache_ok=True), Budget)


def test_agent_budget_policy_mode_only_narrows():
    def budget(**measured_and_mode):
        mode = measured_and_mode.pop('tool_mode', 'native')
        data = calibrated(tool_mode=mode)
        data['agent']['measured'].update(measured_and_mode)
        return agent_budget(policy_from_dict(data).agent)

    assert budget().mode == 'native'
    assert budget(tool_mode='schema').mode == 'schema' and budget(tool_mode='schema').max_rounds == 4
    # einschuss set, but p=20/g=6 needs 375 s for one call > 0.8 * 420: no-go instead of a timeout
    assert budget(tool_mode='einschuss').mode == 'no-go'
    fast_one = budget(tool_mode='einschuss', prompt_tok_s=50, gen_tok_s=20)
    assert fast_one.mode == 'einschuss' and fast_one.max_rounds == 0
    # the policy can never widen: measured einschuss stays einschuss with tool_mode native
    assert budget(prompt_tok_s=50, gen_tok_s=20, cache_ok=False).mode == 'einschuss'
    assert budget(prompt_tok_s=10, gen_tok_s=3).mode == 'no-go'
    assert set(AGENT_TOOL_MODES) == {'native', 'schema', 'einschuss'}
