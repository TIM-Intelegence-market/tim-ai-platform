"""Checkup policy (`config/tim_checkup.json`) and runtime settings (`TIM_CHECKUP_*` from /etc/tim/tim.env).

The policy is reviewed data. `load_policy` rejects unknown keys, duplicate keys and wrong types at every level, so a
typo can never switch a rule off silently. Every class, check name and label must be one this module knows.
The label allowlist is code, not data: the config may pick labels from it, never add to it (design E4).

`load_settings` never fails: an invalid value forces reporting to 'off' and names the variable in a fixed reason,
never its value (a pasted secret must not reach the journal).
"""
from __future__ import annotations

import json
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

_UNIT = re.compile(r'^[A-Za-z0-9@_.:-]{1,120}\.(?:service|timer|path|socket|target|mount)$')
_LABEL = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
_HOST = re.compile(rf'^(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})*$')
_REPOSITORY = re.compile(r'^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$')
_ABS_PATH = re.compile(r'^/(?:[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)?$')
_REMEDY = re.compile(r'^[^\n\r<>`@#\[\]|]{1,300}$')
_NUMBER = re.compile(r'^[1-9][0-9]{0,18}$')
_LOGIN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,38}$')
_BOT_LOGIN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,38}\[bot\]$')


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


def policy_from_dict(data: Any) -> Policy:
    """Validate an already parsed policy object (tests build variants this way)."""
    top = _object(data, 'policy', ('version', 'repository', 'host', 'postgres_unit', 'chain_order', 'classes',
                                   'health', 'disk', 'network', 'hysteresis', 'limits', 'rate_limits', 'evidence'))
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
        limits=LimitsPolicy(**{key: _int(limits[key], f'limits.{key}') for key in limit_keys}),
        rate_limits=RateLimits(**{key: _int(rates[key], f'rate_limits.{key}') for key in rate_keys}),
        evidence=EvidencePolicy(_strings(evidence['statvfs_paths'], 'evidence.statvfs_paths', _ABS_PATH)),
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
