"""Checkup policy (`config/tim_checkup.json`) and runtime settings (`TIM_CHECKUP_*` from /etc/tim/tim.env).

The policy is reviewed data. `load_policy` rejects unknown keys, duplicate keys and wrong types at every level, so a
typo can never switch a rule off silently. Every class, check name and label must be one this module knows.
The label allowlist is code, not data: the config may pick labels from it, never add to it (design E4).

The `agent` block (PR-2, design C.4) configures the read-only Qwen diagnosis. Values that can only be measured on the
server (model digest and config hash, prompt/generation speed, cache, Ollama CPU list, resolver) ship as null; while
any of them is null `AgentPolicy.calibrated` is False and the diagnosis must not call Ollama (fail-closed).
`compute_budget` is the pure budget formula of design section 7.

`load_settings` never fails: an invalid value forces reporting to 'off' and names the variable in a fixed reason,
never its value (a pasted secret must not reach the journal).
"""
from __future__ import annotations

import ipaddress
import json
import math
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from src.task_governance.repository_names import normalize_repository

from .redaction import final_scan

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / 'config' / 'tim_checkup.json'
POLICY_VERSION = 1

BASE_LABELS = ('incident', 'source:tim-checkup')
LABEL_ALLOWLIST = frozenset({
    'incident', 'source:tim-checkup', 'priority:p1',
    'incident:network', 'incident:ops', 'incident:code', 'incident:unknown', 'incident:safety',
    'selftest',
})
CONTROL_LABELS = frozenset({'checkup:silence', 'checkup:pause-qwen', 'checkup:selftest'})
# incident:code is set only from a verified diagnosis (PR-2), never statically per class.
_DYNAMIC_LABELS = frozenset({'incident:code'})

CHAIN_CLASSES = ('HEALTH_STALE', 'DISK', 'DATABASE', 'RUNTIME', 'NETWORK', 'DATA_FLOW', 'WATCHDOG')
INDEPENDENT_CLASSES = ('SAFETY', 'BACKUP', 'TIME_SYNC', 'UNIT', 'SELFTEST')
CLASS_NAMES = CHAIN_CLASSES + INDEPENDENT_CLASSES
CATEGORIES = frozenset({'ops', 'network', 'code', 'unknown', 'safety', 'selftest'})

HEALTH_CHECKS = frozenset({'runtime', 'candle_freshness', 'gap_last_60m', 'disk', 'time_sync', 'backup'})
WATCHDOG_CHECKS = frozenset({
    'runtime_process', 'single_collector', 'dashboard', 'collector_freshness', 'postgres_listener', 'data_age',
    'queue_age', 'cursor_age', 'gap_incidents', 'disk_space', 'log_growth', 'observe_only', 'trading_action_count',
})
DERIVED_CHECKS = frozenset({
    'health_file',        # server_health.json older than health.stale_seconds or unreadable
    'database',           # health reason "database unavailable (...)"
    'runtime_unit',       # tim-runtime.service not active (systemctl show)
    'statvfs',            # a disk.statvfs_paths entry at or above disk.red_percent
    'net_probe',          # TCP probe to an outage host failed
    'net_pattern',        # network pattern in the runtime journal near a gap
    'past_gap',           # gap_last_60m RED, candles fresh again, no foreign traceback
    'backup_last_run',    # backup_last_run.json says FAIL
    'restore_test',       # restore_test.json says FAIL
    'unit',               # a watched unit not active
    'selftest',           # label checkup:selftest on the authority issue
})
CHECK_NAMES = frozenset(HEALTH_CHECKS | DERIVED_CHECKS | {'watchdog.' + name for name in WATCHDOG_CHECKS})

REPORTING_MODES = ('off', 'dry-run', 'on')
DIAGNOSIS_MODES = ('off', 'on')
AUTHORITY_STATES = frozenset({'open', 'closed', 'missing', 'unknown', 'not_configured'})

AGENT_TOOL_MODES = ('native', 'schema', 'einschuss')
BUDGET_MODES = AGENT_TOOL_MODES + ('no-go', 'not-calibrated')
AGENT_MODEL = 'qwen3-coder:30b'
AGENT_HOST = '127.0.0.2'             # the Ollama drop-in binds here; tim-agent may reach no other loopback address
MIN_EVIDENCE_TOKENS = 1024           # below this an incident cannot be explained at all: no-go (not in design section 7)

_UNIT = re.compile(r'^[A-Za-z0-9@_.:-]{1,120}\.(?:service|timer|path|socket|target|mount)$')
_LABEL = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
_HOST = re.compile(rf'^(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})*$')
_REPOSITORY = re.compile(r'^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$')
_ABS_PATH = re.compile(r'^/(?:[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)?$')
_REMEDY = re.compile(r'^[^\n\r<>`@#\[\]|]{1,300}$')
_NUMBER = re.compile(r'^[1-9][0-9]{0,18}$')
_LOGIN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,38}$')
_BOT_LOGIN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,38}\[bot\]$')
_MODEL = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}$')
_DIGEST = re.compile(r'^(?:sha256:)?[0-9a-f]{64}$')
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_ENDPOINT = re.compile(r'^http://127\.0\.0\.2:([1-9][0-9]{0,4})$')
_CPU_LIST = re.compile(r'^[0-9]{1,3}(?:-[0-9]{1,3})?(?:,[0-9]{1,3}(?:-[0-9]{1,3})?){0,31}$')
_WORD = re.compile(r'^[a-z0-9][a-z0-9_.+-]{0,39}$')
_DOMAIN = re.compile(r'^(?=.{1,253}$)(?!.*\.\.)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$')


class PolicyError(ValueError):
    """The policy file is not acceptable. The message names the key path, never secrets."""


@dataclass(frozen=True)
class ClassPolicy:
    name: str
    checks: tuple[str, ...]
    open_red_samples: int       # opens when this many RED samples lie in the window (0 = not used, 1 = at once)
    open_runs: int              # opens after this many checkup runs in a row with a finding (0 = not used)
    units: tuple[str, ...]      # unit status and journal go into the evidence
    labels: tuple[str, ...]     # in addition to BASE_LABELS
    qwen: bool                  # diagnosis wanted (PR-2); read, no effect in PR-1
    category: str               # "Einordnung (feste Regel)" in the issue body
    remedy: str                 # fixed German text for "Behebung" in the issue body

    @property
    def issue_labels(self) -> tuple[str, ...]:
        return BASE_LABELS + self.labels


@dataclass(frozen=True)
class HealthPolicy:
    stale_seconds: int


@dataclass(frozen=True)
class DiskPolicy:
    statvfs_paths: tuple[str, ...]
    red_percent: float


@dataclass(frozen=True)
class NetworkPolicy:
    probes: tuple[tuple[str, int], ...]
    outage_hosts: tuple[str, ...]       # probes that count for NETWORK rule (a); the others are evidence only
    runtime_patterns: tuple[str, ...]
    min_missing_minutes: int
    probe_timeout_seconds: float
    probe_history_runs: int
    gap_context_minutes: int

    @cached_property
    def patterns(self) -> tuple[re.Pattern[str], ...]:
        return tuple(re.compile(pattern) for pattern in self.runtime_patterns)

    def matches(self, line: str) -> bool:
        return any(pattern.search(line) for pattern in self.patterns)


@dataclass(frozen=True)
class HysteresisPolicy:
    window_minutes: int
    resolve_clean_runs: int
    resolve_max_clean_runs: int
    reopen_cooldown_hours: float
    status_line_hours: float


@dataclass(frozen=True)
class LimitsPolicy:
    evidence_comment_bytes: int
    journal_lines: int
    journal_bytes: int
    journal_before_open_minutes: int
    gap_incidents_lines: int
    run_timeout_seconds: int
    create_min_remaining_seconds: int
    command_timeout_seconds: int
    spool_coalesce_after: int
    spool_alarm_minutes: int
    request_bytes: int                  # largest diagnosis request (requests/<rid>.json) either side accepts


@dataclass(frozen=True)
class RateLimits:
    new_issues_per_hour: int
    new_issues_per_day: int
    writes_per_run: int
    comments_per_incident_per_day: int
    changed_per_episode: int
    pause_after_forbidden_minutes: int
    pause_after_rate_limit_minutes: int


@dataclass(frozen=True)
class EvidencePolicy:
    statvfs_paths: tuple[str, ...]


@dataclass(frozen=True)
class MeasuredPolicy:
    """P2 measurement (design section 7); every value is None until the owner pastes the calibrate output."""
    prompt_tok_s: float | None
    gen_tok_s: float | None
    cache_ok: bool | None


@dataclass(frozen=True)
class GatePolicy:
    """The diagnosis is postponed while any limit is crossed (design C.1 item 4)."""
    min_mem_available_gib: float
    max_load1: float
    psi_cpu: float          # /proc/pressure/cpu some avg10
    psi_io: float           # /proc/pressure/io some avg10
    psi_memory: float       # /proc/pressure/memory some avg10


# The agent keys whose None value means "not calibrated yet" (measured.* are listed with their prefix).
CALIBRATION_KEYS = ('model_digest', 'model_config_sha256', 'measured.prompt_tok_s', 'measured.gen_tok_s',
                    'measured.cache_ok', 'ollama_allowed_cpus', 'resolver')


@dataclass(frozen=True)
class AgentPolicy:
    model: str
    model_digest: str | None            # /api/tags digest of `model` (64 hex, optional 'sha256:' prefix)
    model_config_sha256: str | None     # sha256 over json.dumps([template, system, parameters]) of /api/show
    endpoint: str                       # always http://127.0.0.2:<port>
    tool_mode: str                      # AGENT_TOOL_MODES
    measured: MeasuredPolicy
    ollama_allowed_cpus: str | None     # AllowedCPUs= of the Ollama drop-in, e.g. '2-3,6-7'; the installer gets it as
                                        # --ollama-cpus, this copy only records that calibration happened
    resolver: str | None                # 'public' or the IP of a private resolver (IPAddressAllow of tim-agent)
    num_ctx: int
    num_thread: int
    per_call_timeout_seconds: int       # T of the budget formula
    deadline_seconds: int               # D of the budget formula
    evidence_tokens_max: int
    tool_output_chars: int
    ctx_stop_ratio: float
    num_predict_round: int
    num_predict_final: int
    round_prompt_tokens: int            # prompt tokens a tool round adds (1300 in design section 7)
    max_rounds_cap: int
    max_tool_calls: int
    max_tool_calls_per_round: int
    max_searches: int
    max_fetches: int
    search_interval_seconds: int
    units_allowlist: tuple[str, ...]
    fetch_domains: tuple[str, ...]
    query_vocabulary: tuple[str, ...]
    gate: GatePolicy
    daily_limit: int
    per_episode: int
    attempts: int
    root_owned: bool = False            # git_log only after P0/P3 confirmed /opt/tim is root-owned (config PR)

    @property
    def port(self) -> int:
        return int(_ENDPOINT.match(self.endpoint).group(1))

    @property
    def missing_calibration(self) -> tuple[str, ...]:
        """Names (CALIBRATION_KEYS) of the values still None, in a fixed order."""
        values = {'model_digest': self.model_digest, 'model_config_sha256': self.model_config_sha256,
                  'measured.prompt_tok_s': self.measured.prompt_tok_s, 'measured.gen_tok_s': self.measured.gen_tok_s,
                  'measured.cache_ok': self.measured.cache_ok, 'ollama_allowed_cpus': self.ollama_allowed_cpus,
                  'resolver': self.resolver}
        return tuple(key for key in CALIBRATION_KEYS if values[key] is None)

    @property
    def calibrated(self) -> bool:
        return not self.missing_calibration


@dataclass(frozen=True)
class Policy:
    version: int
    repository: str
    host: str
    postgres_unit: str
    chain_order: tuple[str, ...]
    classes: Mapping[str, ClassPolicy]      # read-only mapping, in CLASS_NAMES order
    health: HealthPolicy
    disk: DiskPolicy
    network: NetworkPolicy
    hysteresis: HysteresisPolicy
    limits: LimitsPolicy
    rate_limits: RateLimits
    evidence: EvidencePolicy
    hold_checks: tuple[str, ...]            # watchdog check names (without prefix); not GREEN -> requests/HOLD
    agent: AgentPolicy

    @property
    def normalized_repository(self) -> str:
        return normalize_repository(self.repository)

    @property
    def independent_classes(self) -> tuple[str, ...]:
        return tuple(name for name in self.classes if name not in self.chain_order)


@dataclass(frozen=True)
class Controls:
    authority: str  # 'open' | 'closed' | 'missing' | 'unknown' | 'not_configured'
    labels: frozenset[str]

    def __post_init__(self):
        if self.authority not in AUTHORITY_STATES:
            raise ValueError('unknown authority state')
        labels = frozenset(self.labels)
        if not all(isinstance(label, str) for label in labels):
            raise ValueError('labels must be strings')
        object.__setattr__(self, 'labels', labels)

    @property
    def open(self) -> bool:
        return self.authority == 'open'

    @property
    def silenced(self) -> bool:
        return 'checkup:silence' in self.labels

    @property
    def pause_qwen(self) -> bool:
        return 'checkup:pause-qwen' in self.labels

    @property
    def selftest(self) -> bool:
        return 'checkup:selftest' in self.labels


NOT_CONFIGURED = Controls('not_configured', frozenset())


@dataclass(frozen=True)
class Settings:
    reporting: str                      # 'off' | 'dry-run' | 'on' (effective)
    diagnosis: str                      # 'off' | 'on'; read, no effect in PR-1
    app_id: int | None
    installation_id: int | None
    authority_issue: int | None
    watch_issue: int | None
    reporter_login: str | None          # '<app-slug>[bot]'
    owner_login: str | None
    requested: str                      # the reporting mode asked for: off | dry-run | on | invalid
    problems: tuple[str, ...]           # fixed texts; non-empty forces reporting to 'off'
    credentials_directory: str | None = None   # $CREDENTIALS_DIRECTORY (systemd LoadCredential=)
    database_secret_file: str | None = None    # $TIM_DATABASE_SECRET_FILE, for literal redaction only

    @property
    def reason(self) -> str:
        return '; '.join(self.problems)

    @property
    def complete(self) -> bool:
        return None not in (self.app_id, self.installation_id, self.authority_issue, self.reporter_login,
                            self.owner_login)


# --- load_policy -------------------------------------------------------------------------------------------------

def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError(f'duplicate key {key!r}')
        result[key] = value
    return result


def _object(value, where: str, required: tuple[str, ...]) -> dict:
    if not isinstance(value, dict):
        raise PolicyError(f'{where}: object expected')
    unknown = sorted(set(value) - set(required))
    if unknown:
        raise PolicyError(f'{where}: unknown key {unknown[0]!r}')
    missing = [key for key in required if key not in value]
    if missing:
        raise PolicyError(f'{where}: missing key {missing[0]!r}')
    return value


def _int(value, where: str, low: int = 1, high: int = 10 ** 7) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PolicyError(f'{where}: integer expected')
    if not low <= value <= high:
        raise PolicyError(f'{where}: out of range {low}..{high}')
    return value


def _number(value, where: str, low: float, high: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise PolicyError(f'{where}: number expected')
    if not low <= value <= high:
        raise PolicyError(f'{where}: out of range {low}..{high}')
    return float(value)


def _bool(value, where: str) -> bool:
    if not isinstance(value, bool):
        raise PolicyError(f'{where}: boolean expected')
    return value


def _str(value, where: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise PolicyError(f'{where}: invalid text')
    return value


def _list(value, where: str, *, empty: bool = False) -> list:
    if not isinstance(value, list):
        raise PolicyError(f'{where}: list expected')
    if not value and not empty:
        raise PolicyError(f'{where}: must not be empty')
    if len(value) != len({json.dumps(item, sort_keys=True) for item in value}):
        raise PolicyError(f'{where}: duplicate entries')
    return value


def _strings(value, where: str, pattern: re.Pattern[str], *, empty: bool = False) -> tuple[str, ...]:
    return tuple(_str(item, f'{where}[{index}]', pattern) for index, item in enumerate(_list(value, where, empty=empty)))


def _class(name: str, value) -> ClassPolicy:
    where = f'classes.{name}'
    data = _object(value, where, ('checks', 'open_red_samples', 'open_runs', 'units', 'labels', 'qwen', 'category',
                                  'remedy'))
    checks = _strings(data['checks'], f'{where}.checks', re.compile(r'^[a-z0-9_.]{1,64}$'))
    for check in checks:
        if check not in CHECK_NAMES:
            raise PolicyError(f'{where}.checks: unknown check {check!r}')
    samples = _int(data['open_red_samples'], f'{where}.open_red_samples', 0, 100)
    runs = _int(data['open_runs'], f'{where}.open_runs', 0, 100)
    if not samples and not runs:
        raise PolicyError(f'{where}: open_red_samples or open_runs must be at least 1')
    units = _strings(data['units'], f'{where}.units', _UNIT, empty=True)
    labels = _strings(data['labels'], f'{where}.labels', re.compile(r'^[a-z0-9:_-]{1,50}$'), empty=True)
    for label in labels:
        if label not in LABEL_ALLOWLIST or label in BASE_LABELS or label in _DYNAMIC_LABELS:
            raise PolicyError(f'{where}.labels: label {label!r} is not allowed')
    if ('selftest' in labels) != (name == 'SELFTEST'):
        raise PolicyError(f'{where}.labels: selftest belongs to class SELFTEST only')
    if name == 'SELFTEST' and labels != ('selftest',):
        raise PolicyError(f'{where}.labels: the selftest carries no other label')
    category = data['category']
    if category not in CATEGORIES:
        raise PolicyError(f'{where}.category: unknown category')
    remedy = data['remedy']
    if not isinstance(remedy, str) or not _REMEDY.match(remedy) or final_scan(remedy):
        raise PolicyError(f'{where}.remedy: fixed plain text without markup expected')
    return ClassPolicy(name, checks, samples, runs, units, labels, _bool(data['qwen'], f'{where}.qwen'), category, remedy)


def _probes(value, where: str) -> tuple[tuple[str, int], ...]:
    probes = []
    for index, item in enumerate(_list(value, where)):
        if not isinstance(item, list) or len(item) != 2:
            raise PolicyError(f'{where}[{index}]: [host, port] expected')
        probes.append((_str(item[0], f'{where}[{index}][0]', _HOST), _int(item[1], f'{where}[{index}][1]', 1, 65535)))
    return tuple(probes)


def _patterns(value, where: str) -> tuple[str, ...]:
    patterns = []
    for index, item in enumerate(_list(value, where)):
        if not isinstance(item, str) or not 0 < len(item) <= 200:
            raise PolicyError(f'{where}[{index}]: pattern text expected')
        try:
            re.compile(item)
        except re.error:
            raise PolicyError(f'{where}[{index}]: invalid regular expression') from None
        patterns.append(item)
    return tuple(patterns)


def _optional(value, where: str, check):
    return None if value is None else check(value, where)


def _ip(value, where: str) -> str:
    if not isinstance(value, str):
        raise PolicyError(f'{where}: text expected')
    if value == 'public':
        return value
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise PolicyError(f'{where}: "public" or an IP address expected') from None
    if address.is_unspecified or address.is_multicast or str(address) != value:
        raise PolicyError(f'{where}: "public" or an IP address expected')
    return value


def _cpu_list(value, where: str) -> str:
    value = _str(value, where, _CPU_LIST)
    for part in value.split(','):
        low, _, high = part.partition('-')
        if high and int(high) <= int(low):
            raise PolicyError(f'{where}: invalid CPU range')
    return value


_AGENT_KEYS = tuple(AgentPolicy.__dataclass_fields__)
_AGENT_INTS = {
    'num_ctx': (2048, 131072), 'num_thread': (1, 64), 'per_call_timeout_seconds': (30, 3600),
    'deadline_seconds': (60, 7200), 'evidence_tokens_max': (512, 32768), 'tool_output_chars': (500, 16000),
    'num_predict_round': (16, 4096), 'num_predict_final': (64, 8192), 'round_prompt_tokens': (100, 16384),
    'max_rounds_cap': (0, 20), 'max_tool_calls': (0, 50), 'max_tool_calls_per_round': (1, 10),
    'max_searches': (0, 10), 'max_fetches': (0, 10), 'search_interval_seconds': (1, 600),
    'daily_limit': (0, 100), 'per_episode': (0, 20), 'attempts': (1, 5),
}


def _agent(value, qwen_units: set[str]) -> AgentPolicy:
    data = _object(value, 'agent', _AGENT_KEYS)
    model = _str(data['model'], 'agent.model', _MODEL)
    if model != AGENT_MODEL:
        raise PolicyError(f'agent.model: only {AGENT_MODEL} is allowed')
    tool_mode = data['tool_mode']
    if tool_mode not in AGENT_TOOL_MODES:
        raise PolicyError('agent.tool_mode: unknown mode')
    raw_measured = _object(data['measured'], 'agent.measured', ('prompt_tok_s', 'gen_tok_s', 'cache_ok'))
    measured = MeasuredPolicy(
        _optional(raw_measured['prompt_tok_s'], 'agent.measured.prompt_tok_s', lambda v, w: _number(v, w, 0.01, 10000)),
        _optional(raw_measured['gen_tok_s'], 'agent.measured.gen_tok_s', lambda v, w: _number(v, w, 0.01, 10000)),
        _optional(raw_measured['cache_ok'], 'agent.measured.cache_ok', _bool))
    gate = _object(data['gate'], 'agent.gate', tuple(GatePolicy.__dataclass_fields__))
    ints = {key: _int(data[key], f'agent.{key}', low, high) for key, (low, high) in _AGENT_INTS.items()}
    if ints['deadline_seconds'] < ints['per_call_timeout_seconds']:
        raise PolicyError('agent.deadline_seconds: below per_call_timeout_seconds')
    if ints['max_tool_calls_per_round'] > max(ints['max_tool_calls'], 1):
        raise PolicyError('agent.max_tool_calls_per_round: above max_tool_calls')
    units = _strings(data['units_allowlist'], 'agent.units_allowlist', _UNIT)
    missing = sorted(qwen_units - set(units))
    if missing:
        raise PolicyError(f'agent.units_allowlist: misses unit {missing[0]!r} of a class with qwen')
    domains = _strings(data['fetch_domains'], 'agent.fetch_domains', _DOMAIN)
    if any(not re.search('[a-z]', domain.rsplit('.', 1)[-1]) for domain in domains):
        raise PolicyError('agent.fetch_domains: host names only, no IP addresses')
    vocabulary = _strings(data['query_vocabulary'], 'agent.query_vocabulary', _WORD)
    if len(vocabulary) > 500 or len(domains) > 50 or len(units) > 100:
        raise PolicyError('agent: list too long')
    endpoint = _str(data['endpoint'], 'agent.endpoint', _ENDPOINT)
    if not 1 <= int(_ENDPOINT.match(endpoint).group(1)) <= 65535:
        raise PolicyError('agent.endpoint: port out of range')
    return AgentPolicy(
        model=model,
        model_digest=_optional(data['model_digest'], 'agent.model_digest', lambda v, w: _str(v, w, _DIGEST)),
        model_config_sha256=_optional(data['model_config_sha256'], 'agent.model_config_sha256',
                                      lambda v, w: _str(v, w, _SHA256)),
        endpoint=endpoint, tool_mode=tool_mode, measured=measured,
        ollama_allowed_cpus=_optional(data['ollama_allowed_cpus'], 'agent.ollama_allowed_cpus', _cpu_list),
        resolver=_optional(data['resolver'], 'agent.resolver', _ip),
        ctx_stop_ratio=_number(data['ctx_stop_ratio'], 'agent.ctx_stop_ratio', 0.3, 0.95),
        units_allowlist=units, fetch_domains=domains, query_vocabulary=vocabulary,
        gate=GatePolicy(
            min_mem_available_gib=_number(gate['min_mem_available_gib'], 'agent.gate.min_mem_available_gib', 0, 4096),
            max_load1=_number(gate['max_load1'], 'agent.gate.max_load1', 0.1, 1024),
            psi_cpu=_number(gate['psi_cpu'], 'agent.gate.psi_cpu', 0, 100),
            psi_io=_number(gate['psi_io'], 'agent.gate.psi_io', 0, 100),
            psi_memory=_number(gate['psi_memory'], 'agent.gate.psi_memory', 0, 100)),
        root_owned=_bool(data['root_owned'], 'agent.root_owned'),
        **ints,
    )


def policy_from_dict(data: Any) -> Policy:
    """Validate an already parsed policy object (tests build variants this way)."""
    top = _object(data, 'policy', ('version', 'repository', 'host', 'postgres_unit', 'chain_order', 'classes',
                                   'health', 'disk', 'network', 'hysteresis', 'limits', 'rate_limits', 'evidence',
                                   'hold_checks', 'agent'))
    version = _int(top['version'], 'version', 1, 1000)
    if version != POLICY_VERSION:
        raise PolicyError('version: unsupported')
    repository = _str(top['repository'], 'repository', _REPOSITORY)
    host = _str(top['host'], 'host', _HOST)
    postgres_unit = _str(top['postgres_unit'], 'postgres_unit', _UNIT)

    raw_classes = _object(top['classes'], 'classes', CLASS_NAMES)
    classes = MappingProxyType({name: _class(name, raw_classes[name]) for name in CLASS_NAMES})
    chain = _strings(top['chain_order'], 'chain_order', re.compile(r'^[A-Z_]{1,32}$'))
    if set(chain) != set(CHAIN_CLASSES):
        raise PolicyError('chain_order: must name each chain class exactly once')

    health = _object(top['health'], 'health', ('stale_seconds',))
    disk = _object(top['disk'], 'disk', ('statvfs_paths', 'red_percent'))
    network = _object(top['network'], 'network', ('probes', 'outage_hosts', 'runtime_patterns', 'min_missing_minutes',
                                                  'probe_timeout_seconds', 'probe_history_runs', 'gap_context_minutes'))
    probes = _probes(network['probes'], 'network.probes')
    outage_hosts = _strings(network['outage_hosts'], 'network.outage_hosts', _HOST)
    if not set(outage_hosts) <= {probe_host for probe_host, _ in probes}:
        raise PolicyError('network.outage_hosts: every host must also be a probe')
    hysteresis = _object(top['hysteresis'], 'hysteresis', ('window_minutes', 'resolve_clean_runs',
                                                           'resolve_max_clean_runs', 'reopen_cooldown_hours',
                                                           'status_line_hours'))
    limit_keys = tuple(LimitsPolicy.__dataclass_fields__)
    limits = _object(top['limits'], 'limits', limit_keys)
    rate_keys = tuple(RateLimits.__dataclass_fields__)
    rates = _object(top['rate_limits'], 'rate_limits', rate_keys)
    evidence = _object(top['evidence'], 'evidence', ('statvfs_paths',))

    request_bytes = _int(limits['request_bytes'], 'limits.request_bytes', 4096, 262144)
    hold_checks = _strings(top['hold_checks'], 'hold_checks', re.compile(r'^[a-z0-9_]{1,64}$'))
    for check in hold_checks:
        if check not in WATCHDOG_CHECKS:
            raise PolicyError(f'hold_checks: unknown watchdog check {check!r}')
    qwen_units = {unit for cls in classes.values() if cls.qwen for unit in cls.units} | {postgres_unit}
    agent = _agent(top['agent'], qwen_units)

    resolve_runs = _int(hysteresis['resolve_clean_runs'], 'hysteresis.resolve_clean_runs', 1, 100)
    resolve_max = _int(hysteresis['resolve_max_clean_runs'], 'hysteresis.resolve_max_clean_runs', 1, 1000)
    if resolve_max < resolve_runs:
        raise PolicyError('hysteresis.resolve_max_clean_runs: below resolve_clean_runs')
    return Policy(
        version=version, repository=repository, host=host, postgres_unit=postgres_unit, chain_order=chain,
        classes=classes,
        health=HealthPolicy(_int(health['stale_seconds'], 'health.stale_seconds', 60, 86400)),
        disk=DiskPolicy(_strings(disk['statvfs_paths'], 'disk.statvfs_paths', _ABS_PATH),
                        _number(disk['red_percent'], 'disk.red_percent', 50, 100)),
        network=NetworkPolicy(
            probes=probes, outage_hosts=outage_hosts,
            runtime_patterns=_patterns(network['runtime_patterns'], 'network.runtime_patterns'),
            min_missing_minutes=_int(network['min_missing_minutes'], 'network.min_missing_minutes', 1, 60),
            probe_timeout_seconds=_number(network['probe_timeout_seconds'], 'network.probe_timeout_seconds', 0.5, 30),
            probe_history_runs=_int(network['probe_history_runs'], 'network.probe_history_runs', 1, 100),
            gap_context_minutes=_int(network['gap_context_minutes'], 'network.gap_context_minutes', 0, 60)),
        hysteresis=HysteresisPolicy(
            window_minutes=_int(hysteresis['window_minutes'], 'hysteresis.window_minutes', 1, 1440),
            resolve_clean_runs=resolve_runs, resolve_max_clean_runs=resolve_max,
            reopen_cooldown_hours=_number(hysteresis['reopen_cooldown_hours'], 'hysteresis.reopen_cooldown_hours', 0, 720),
            status_line_hours=_number(hysteresis['status_line_hours'], 'hysteresis.status_line_hours', 1, 720)),
        limits=LimitsPolicy(**{key: _int(limits[key], f'limits.{key}') for key in limit_keys
                               if key != 'request_bytes'}, request_bytes=request_bytes),
        rate_limits=RateLimits(**{key: _int(rates[key], f'rate_limits.{key}') for key in rate_keys}),
        evidence=EvidencePolicy(_strings(evidence['statvfs_paths'], 'evidence.statvfs_paths', _ABS_PATH)),
        hold_checks=hold_checks, agent=agent,
    )


def load_policy(path: Path | str = DEFAULT_POLICY_PATH) -> Policy:
    """Read and validate the policy file; raises PolicyError (also for unreadable or malformed files)."""
    try:
        text = Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        raise PolicyError('policy file unreadable') from None
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicates)
    except PolicyError:
        raise
    except (ValueError, RecursionError):
        raise PolicyError('policy file is not valid JSON') from None
    return policy_from_dict(data)


# --- budget formula (design section 7) -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Budget:
    mode: str                   # BUDGET_MODES: native | schema | einschuss (go) or no-go | not-calibrated
    max_rounds: int             # tool rounds between the initial and the final call (0 in einschuss and no-go)
    evidence_tokens: int        # E
    evidence_chars: int         # 3 * E, the evidence text Qwen may get
    t_initial: float            # seconds
    t_round: float
    t_final: float
    reason: str                 # fixed English text for the journal

    @property
    def go(self) -> bool:
        return self.mode in AGENT_TOOL_MODES


def _no_go(mode: str, reason: str, evidence: int = 0, t_initial: float = 0.0, t_round: float = 0.0,
           t_final: float = 0.0) -> Budget:
    return Budget(mode, 0, evidence, 3 * evidence, t_initial, t_round, t_final, reason)


def compute_budget(prompt_tok_s: float, gen_tok_s: float, *, cache_ok: bool, tool_calls_ok: bool = True,
                   red_during_measurement: bool = False, per_call_timeout: float = 420, deadline: float = 900,
                   evidence_tokens_max: int = 4096, round_prompt_tokens: int = 1300, num_predict_round: int = 256,
                   num_predict_final: int = 768, max_rounds_cap: int = 6) -> Budget:
    """Pure budget formula and go/no-go table of design section 7 (p = prompt tok/s, g = generation tok/s).

    E = min(E_max, floor(0.5 * T * p)); t_initial = E/p + 256/g; t_round = 1300/p + 256/g; t_final = 768/g;
    max_rounds = clamp(floor((D - t_initial - t_final) / t_round), 0, cap).
    Go native (schema when the tool calls were broken) needs max_rounds >= 2 and a working prompt cache.
    Otherwise einschuss (evidence, then submit_result at once) when t_initial + t_final <= 0.8 * T; t_round assumes
    the cache, so without it only einschuss is possible. Everything else is no-go, as is any RED during the
    measurement and an evidence budget below MIN_EVIDENCE_TOKENS.
    """
    for value in (prompt_tok_s, gen_tok_s, per_call_timeout, deadline):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            return _no_go('no-go', 'measurement missing or not positive')
    p, g, timeout = float(prompt_tok_s), float(gen_tok_s), float(per_call_timeout)
    evidence = min(int(evidence_tokens_max), math.floor(0.5 * timeout * p))
    t_initial = evidence / p + num_predict_round / g
    t_round = round_prompt_tokens / p + num_predict_round / g
    t_final = num_predict_final / g
    rounds = max(0, min(int(max_rounds_cap), math.floor((float(deadline) - t_initial - t_final) / t_round)))
    times = (evidence, t_initial, t_round, t_final)
    if red_during_measurement:
        return _no_go('no-go', 'TIM was RED during the measurement', *times)
    if evidence < MIN_EVIDENCE_TOKENS:
        return _no_go('no-go', 'evidence budget too small', *times)
    if rounds >= 2 and cache_ok is True:
        mode = 'native' if tool_calls_ok else 'schema'
        return Budget(mode, rounds, evidence, 3 * evidence, t_initial, t_round, t_final, 'tool rounds fit')
    if t_initial + t_final <= 0.8 * timeout:
        return Budget('einschuss', 0, evidence, 3 * evidence, t_initial, t_round, t_final,
                      'one call fits, tool rounds do not')
    return _no_go('no-go', 'too slow for a diagnosis', *times)


_MODE_RANK = {'einschuss': 0, 'schema': 1, 'native': 2}


def agent_budget(agent: AgentPolicy) -> Budget:
    """Budget from the shipped measurement. Not calibrated -> mode 'not-calibrated' (never call Ollama). The
    configured tool_mode can only narrow the measured mode (native > schema > einschuss), never widen it;
    tool_mode 'schema' also means the measurement found the native tool calls broken."""
    if not agent.calibrated:
        return _no_go('not-calibrated', 'not calibrated')
    budget = compute_budget(agent.measured.prompt_tok_s, agent.measured.gen_tok_s, cache_ok=agent.measured.cache_ok,
                            tool_calls_ok=agent.tool_mode == 'native', per_call_timeout=agent.per_call_timeout_seconds,
                            deadline=agent.deadline_seconds, evidence_tokens_max=agent.evidence_tokens_max,
                            round_prompt_tokens=agent.round_prompt_tokens, num_predict_round=agent.num_predict_round,
                            num_predict_final=agent.num_predict_final, max_rounds_cap=agent.max_rounds_cap)
    if not budget.go or _MODE_RANK[agent.tool_mode] >= _MODE_RANK[budget.mode]:
        return budget
    if agent.tool_mode == 'einschuss':
        if budget.t_initial + budget.t_final > 0.8 * agent.per_call_timeout_seconds:
            return _no_go('no-go', 'einschuss set in the policy, but one call does not fit', budget.evidence_tokens,
                          budget.t_initial, budget.t_round, budget.t_final)
        return Budget('einschuss', 0, budget.evidence_tokens, budget.evidence_chars, budget.t_initial,
                      budget.t_round, budget.t_final, 'einschuss set in the policy')
    return Budget(agent.tool_mode, budget.max_rounds, budget.evidence_tokens, budget.evidence_chars, budget.t_initial,
                  budget.t_round, budget.t_final, 'tool mode set in the policy')


# --- load_settings -----------------------------------------------------------------------------------------------

def _env(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def load_settings(environ: Mapping[str, str]) -> Settings:
    """Settings from the environment. Missing optional values stay None; anything invalid, or dry-run/on without the
    values reporting needs, forces reporting to 'off' with fixed problem texts."""
    problems: list[str] = []

    def choice(name: str, allowed: tuple[str, ...]) -> str:
        raw = _env(environ, name)
        if raw is None:
            return 'off'
        if raw.lower() in allowed:
            return raw.lower()
        problems.append(f'{name} invalid')
        return 'invalid'

    def number(name: str) -> int | None:
        raw = _env(environ, name)
        if raw is None:
            return None
        if _NUMBER.match(raw):
            return int(raw)
        problems.append(f'{name} invalid')
        return None

    def login(name: str, pattern: re.Pattern[str]) -> str | None:
        raw = _env(environ, name)
        if raw is None:
            return None
        if pattern.match(raw):
            return raw
        problems.append(f'{name} invalid')
        return None

    requested = choice('TIM_CHECKUP_REPORTING', REPORTING_MODES)
    diagnosis = choice('TIM_CHECKUP_DIAGNOSIS', DIAGNOSIS_MODES)
    app_id = number('TIM_CHECKUP_APP_ID')
    installation_id = number('TIM_CHECKUP_INSTALLATION_ID')
    authority_issue = number('TIM_CHECKUP_AUTHORITY_ISSUE')
    watch_issue = number('TIM_CHECKUP_WATCH_ISSUE')
    reporter_login = login('TIM_CHECKUP_REPORTER_LOGIN', _BOT_LOGIN)
    owner_login = login('TIM_CHECKUP_OWNER_LOGIN', _LOGIN)
    if watch_issue is not None and watch_issue == authority_issue:
        problems.append('TIM_CHECKUP_WATCH_ISSUE equals TIM_CHECKUP_AUTHORITY_ISSUE')
    if requested in ('dry-run', 'on'):
        for name, value in (('TIM_CHECKUP_APP_ID', app_id), ('TIM_CHECKUP_INSTALLATION_ID', installation_id),
                            ('TIM_CHECKUP_AUTHORITY_ISSUE', authority_issue),
                            ('TIM_CHECKUP_REPORTER_LOGIN', reporter_login), ('TIM_CHECKUP_OWNER_LOGIN', owner_login)):
            if value is None and f'{name} invalid' not in problems:
                problems.append(f'{name} missing')

    credentials = _env(environ, 'CREDENTIALS_DIRECTORY')
    secret_file = _env(environ, 'TIM_DATABASE_SECRET_FILE')
    return Settings(
        reporting='off' if problems or requested == 'invalid' else requested,
        diagnosis='on' if diagnosis == 'on' and not problems else 'off',
        app_id=app_id, installation_id=installation_id, authority_issue=authority_issue, watch_issue=watch_issue,
        reporter_login=reporter_login, owner_login=owner_login, requested=requested, problems=tuple(problems),
        credentials_directory=credentials if credentials and credentials.startswith('/') else None,
        database_secret_file=secret_file if secret_file and secret_file.startswith('/') else None,
    )
