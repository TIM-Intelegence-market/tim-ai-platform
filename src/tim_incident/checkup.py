"""TIM checkup (design part A): judge the server's health with fixed rules and queue reports for the incident reporter.

OBSERVE only. The checkup never restarts, repairs, fills gaps or empties queues, and never runs git. Its only
subprocesses are `journalctl` and `systemctl` with fixed argv and a timeout, through an injectable runner.

One run (`run()`):
1. PR_SET_DUMPABLE=0, flock on data/incidents/checkup.lock, checkup_last_run.json at start and end;
2. controls: one GET of the authority issue through `reporter.read_controls()`;
3. observe: health file and 16-min health history (journal), watchdog files, backup/restore status, systemctl show,
   statvfs, TCP probes, network patterns in the runtime journal around a gap;
4. evaluate (findings per class) -> classify (precedence) -> advance (hysteresis state machine, data/incidents/state.json
   with a .prev copy);
5. outbox entries for the reporter: fixed German text only; log text enters a comment only through
   `redaction.untrusted_block`;
6. `reporter.deliver(spool, deadline=...)`, then ONE JSON line `{"event": "checkup_end", ...}` on stdout.

Qwen diagnosis is PR-2: `ClassPolicy.qwen` and `Settings.diagnosis` are read here but change nothing yet.
"""
from __future__ import annotations

import copy
import ctypes
import errno
import fcntl
import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .policy import CHAIN_CLASSES, CLASS_NAMES, HEALTH_CHECKS, NOT_CONFIGURED, WATCHDOG_CHECKS, Controls, Policy, Settings
from .redaction import final_scan, redact, untrusted_block

UTC = timezone.utc
STATE_VERSION = 1
ENTRY_VERSION = 1

HEALTH_UNIT = 'tim-server-health.service'
RUNTIME_UNIT = 'tim-runtime.service'
BACKUP_DIR = Path('/var/backups/tim')
SERVER_ROOT = Path('/opt/tim')
UNIT_PROPERTIES = ('LoadState', 'ActiveState', 'SubState', 'Result', 'NRestarts', 'ExecMainStatus')

ALLOWED_COMMANDS = frozenset({'journalctl', 'systemctl'})
RUNNER_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_TAIL_BYTES = 1024 * 1024
RUNTIME_JOURNAL_LINES = 2000
WATCHDOG_FACTS_MAX_AGE = 300        # seconds; older watchdog facts never make a SAFETY finding definite
FUTURE_TOLERANCE = timedelta(seconds=60)
MINOR_SEEN_KEPT = 200
EVIDENCE_UNITS_MAX = 8
PATTERN_LINES_MAX = 20
STATUS_MAX_CHARS = 280              # the reporter accepts status lines up to 300 characters
NOTES_MAX = 20                      # reporter notes in the checkup_end line
NOTE_MAX_CHARS = 300

_PR_SET_DUMPABLE = 4
_REPORT_RANK = {None: 0, 'dry-run': 1, 'on': 2}

# Checks the run observes itself. They count toward `open_runs` (runs in a row); only the "instant" ones also count
# as one RED sample, so a single restart caught by systemctl never adds to RUNTIME's sample count.
_RUN_CHECKS = frozenset({'health_file', 'runtime_unit', 'unit', 'selftest', 'net_probe', 'statvfs', 'backup_last_run',
                         'restore_test'})
_INSTANT_CHECKS = frozenset({'statvfs', 'backup_last_run', 'restore_test'})
_SAMPLE_HEALTH = HEALTH_CHECKS | {'database'}
_DATABASE_REASON = 'database unavailable ('
_UNIT_UP = frozenset({'active', 'activating', 'reloading'})
_JOURNAL_DENIED = ('No journal files were', 'insufficient permissions', 'not seeing messages from other users',
                   'Permission denied', 'Access denied')
_TRACEBACK = 'Traceback (most recent call last)'
# Lines that match a network pattern but name an internal cause: a loopback connection (PostgreSQL on this host) or
# the runtime's own catch-up back-pressure (src/data_ingestion, "live resume blocked by incomplete catch-up").
_NOT_NETWORK = re.compile(r"127\.0\.0\.1|'::1'|\[::1\]|\blocalhost\b|incomplete catch-up|durable outbox", re.I)
_NETWORK_RULES = frozenset({'net_pattern', 'past_gap'})
_SHA = re.compile(r'^[0-9a-f]{40}(?:[0-9a-f]{24})?$')
_REF = re.compile(r'^refs/[A-Za-z0-9._/-]{1,200}$')
_EPISODE = re.compile(r'^\d{8}T\d{4}Z$')

Runner = Callable[[list[str], float], tuple[int, str]]


class CheckupError(RuntimeError):
    """Internal error with a fixed text (exit 1)."""


# --- time and files ----------------------------------------------------------------------------------------------

def _utc(value) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromtimestamp(float(value), UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec='seconds')


def _human(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')


def _journal_time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def episode_id(moment: datetime) -> str:
    """`20261007T0315Z`: UTC minute of the first detection."""
    return moment.astimezone(UTC).strftime('%Y%m%dT%H%MZ')


def _duration(seconds: float) -> str:
    minutes = max(0, int(seconds // 60))
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    parts = ([f'{days} d'] if days else []) + ([f'{hours} h'] if hours or days else []) + [f'{mins} min']
    return ' '.join(parts)


def _read_bytes(path: Path, limit: int) -> bytes:
    with open(path, 'rb') as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise OSError(errno.EFBIG, 'file too large')
    return data


def _read_json(path: Path, now: datetime, limit: int = MAX_FILE_BYTES) -> dict:
    """{'data': dict | None, 'age': seconds since mtime | None, 'error': None | 'missing' | 'unreadable' | 'invalid'}."""
    try:
        mtime = path.stat().st_mtime
        raw = _read_bytes(path, limit)
    except FileNotFoundError:
        return {'data': None, 'age': None, 'error': 'missing'}
    except OSError:
        return {'data': None, 'age': None, 'error': 'unreadable'}
    age = now.timestamp() - mtime
    try:
        data = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return {'data': None, 'age': age, 'error': 'invalid'}
    if not isinstance(data, dict):
        return {'data': None, 'age': age, 'error': 'invalid'}
    return {'data': data, 'age': age, 'error': None}


def _tail_lines(path: Path, limit: int) -> list[str]:
    try:
        with open(path, 'rb') as handle:
            size = handle.seek(0, os.SEEK_END)
            start = max(0, size - limit)
            handle.seek(start)
            data = handle.read(limit)
    except OSError:
        return []
    lines = data.split(b'\n')
    if start > 0:
        lines = lines[1:]           # the first line may be cut
    return [line.decode('utf-8', 'replace') for line in lines if line.strip()]


def _write_atomic(path: Path, data: bytes) -> None:
    """Private temp name per process (never a fixed .tmp shared with other writers), fsync, rename, mode 0600."""
    temporary = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _write_json(path: Path, value) -> None:
    _write_atomic(path, (json.dumps(value, indent=1, sort_keys=True) + '\n').encode('utf-8'))


def _append_line(path: Path, value) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        os.write(descriptor, (json.dumps(value, sort_keys=True) + '\n').encode('utf-8'))
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class CheckupPaths:
    data: Path

    @property
    def operational(self) -> Path:
        return self.data / 'operational'

    @property
    def incidents(self) -> Path:
        return self.data / 'incidents'

    @property
    def state(self) -> Path:
        return self.incidents / 'state.json'

    @property
    def state_prev(self) -> Path:
        return self.incidents / 'state.json.prev'

    @property
    def lock(self) -> Path:
        return self.incidents / 'checkup.lock'

    @property
    def last_run(self) -> Path:
        return self.incidents / 'checkup_last_run.json'

    @property
    def minor(self) -> Path:
        return self.incidents / 'minor.jsonl'

    @property
    def outbox(self) -> Path:
        return self.incidents / 'outbox'

    @property
    def evidence(self) -> Path:
        return self.incidents / 'evidence'


# --- process hardening and subprocesses --------------------------------------------------------------------------

def disable_core_dumps(libc=None) -> bool:
    """PR_SET_DUMPABLE=0: no core dump, no ptrace and no /proc/<pid>/mem for other processes of UID tim (design E1).
    False when not on Linux or prctl fails; the run goes on."""
    if libc is None:
        if not sys.platform.startswith('linux'):
            return False
        try:
            libc = ctypes.CDLL(None, use_errno=True)
        except OSError:
            return False
    try:
        return libc.prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0) == 0
    except Exception:
        return False


def default_runner(argv: list[str], timeout: float) -> tuple[int, str]:
    """Fixed argv, no shell, minimal environment (PATH, LANG), stderr merged (journal hints), output capped.
    Never raises: a timeout gives (124, ''), a missing binary (127, '')."""
    if not isinstance(argv, list) or not argv or argv[0] not in ALLOWED_COMMANDS:
        raise ValueError('command not allowed')
    if not all(isinstance(part, str) and '\0' not in part for part in argv):
        raise ValueError('invalid argument')
    try:
        completed = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   env=dict(RUNNER_ENV), timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, ''
    except OSError:
        return 127, ''
    return completed.returncode, completed.stdout[-MAX_OUTPUT_BYTES:].decode('utf-8', 'replace')


def _call(runner: Runner, argv: list[str], timeout: float) -> tuple[int, str]:
    try:
        code, text = runner(list(argv), float(timeout))
    except Exception:
        return 1, ''
    return (code if isinstance(code, int) else 1), (text if isinstance(text, str) else '')


def _journal_denied(text: str) -> bool:
    return any(marker in text for marker in _JOURNAL_DENIED)


# --- reading -----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Sample:
    at: datetime
    red: frozenset[str]             # RED check names: health plain (+ 'database'), watchdog as 'watchdog.<name>'
    checks: Mapping[str, Any]       # raw checks, for evidence and the gap rule


def health_sample(report) -> Sample | None:
    if not isinstance(report, dict):
        return None
    at, checks = _parse_time(report.get('timestamp')), report.get('checks')
    if at is None or not isinstance(checks, dict):
        return None
    red = set()
    for name, check in checks.items():
        if not isinstance(check, dict) or check.get('status') != 'RED':
            continue
        reason = check.get('reason')
        if name in ('candle_freshness', 'gap_last_60m') and isinstance(reason, str) \
                and reason.startswith(_DATABASE_REASON):
            red.add('database')       # a consequence of the database outage, not a data-flow finding
        elif name in HEALTH_CHECKS:
            red.add(name)
    return Sample(at, frozenset(red), checks)


def watchdog_sample(record) -> Sample | None:
    if not isinstance(record, dict):
        return None
    at, checks = _parse_time(record.get('timestamp') or record.get('checked_at')), record.get('checks')
    if at is None or not isinstance(checks, dict):
        return None
    red = {f'watchdog.{name}' for name, check in checks.items()
           if name in WATCHDOG_CHECKS and isinstance(check, dict) and check.get('status') == 'RED'}
    return Sample(at, frozenset(red), checks)


def read_snapshot(data_dir: Path, now: datetime, *, window_minutes: int = 16) -> dict:
    """Status files with their age, plus the WATCHDOG_CHECK samples of the window from the tail of watchdog.jsonl."""
    now = _utc(now)
    operational = CheckupPaths(Path(data_dir)).operational
    snapshot = {name: _read_json(operational / f'{name}.json', now)
                for name in ('server_health', 'watchdog_status', 'watchdog_recovery_state', 'backup_last_run',
                             'restore_test', 'maintenance_last_run')}
    for name, key in (('server_health', 'timestamp'), ('watchdog_status', 'checked_at')):
        entry = snapshot[name]
        stamp = _parse_time(entry['data'].get(key)) if entry['data'] else None
        if stamp is not None and entry['age'] is not None:
            entry['age'] = max(entry['age'], (now - stamp).total_seconds())     # the older reading wins
    since = now - timedelta(minutes=window_minutes)
    samples = []
    for line in _tail_lines(operational / 'watchdog.jsonl', MAX_TAIL_BYTES):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get('event') != 'WATCHDOG_CHECK':
            continue
        sample = watchdog_sample(record)
        if sample is not None and since <= sample.at <= now + FUTURE_TOLERANCE:
            samples.append(sample)
    snapshot['watchdog_samples'] = sorted(samples, key=lambda item: item.at)
    snapshot['gap_incidents_tail'] = _tail_lines(operational / 'gap_incidents.jsonl', 64 * 1024)
    return snapshot


def health_history(runner: Runner, since: datetime, *, timeout: float) -> tuple[str, list[dict]]:
    """Health reports from the journal of tim-server-health.service ('ok', reports) or ('denied', [])."""
    argv = ['journalctl', '-u', HEALTH_UNIT, '--since', _journal_time(since), '-o', 'cat', '--no-pager']
    code, text = _call(runner, argv, timeout)
    if code != 0 or _journal_denied(text):
        return 'denied', []
    reports = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            value = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(value, dict) and isinstance(value.get('checks'), dict):
            reports.append(value)
    return 'ok', reports


def fresh_health(*, root: Path, backup_dir: Path = BACKUP_DIR, collect=None) -> dict | None:
    """One report collected in-process when server_health.json is stale. Calls `collect()` only, never `main()`:
    main() writes the fixed server_health.json.tmp that the health timer uses as well."""
    try:
        if collect is None:
            from scripts.tim_server_health import collect
        report = collect(backup_dir, Path(root))
    except Exception:
        return None
    return report if isinstance(report, dict) else None


def unit_states(runner: Runner, units, *, timeout: float) -> dict[str, dict]:
    states = {}
    for unit in units:
        argv = ['systemctl', 'show', unit, '--property=' + ','.join(UNIT_PROPERTIES), '--no-pager']
        code, text = _call(runner, argv, timeout)
        fields = dict(line.split('=', 1) for line in text.splitlines() if '=' in line) if code == 0 else {}
        state = {key: fields.get(key) for key in UNIT_PROPERTIES}
        state['query'] = 'ok' if code == 0 and fields.get('ActiveState') else 'failed'
        states[unit] = state
    return states


def _runtime_down(state: Mapping | None) -> bool:
    if not state or state.get('query') != 'ok':
        return False
    return state.get('ActiveState') not in _UNIT_UP or state.get('SubState') == 'auto-restart'


def _tcp_connect(host: str, port: int, timeout: float) -> None:
    with socket.create_connection((host, port), timeout=timeout):
        pass


def net_probe(probes, *, connect=None, timeout: float = 5.0, monotonic=time.monotonic) -> list[dict]:
    """DNS + TCP per probe, in Python. The error is a fixed word, never exception text."""
    connect = connect or _tcp_connect
    results = []
    for host, port in probes:
        started = monotonic()
        try:
            connect(host, port, timeout)
            error = None
        except socket.gaierror:
            error = 'dns'
        except TimeoutError:
            error = 'timeout'
        except ConnectionRefusedError:
            error = 'refused'
        except OSError as exc:
            error = 'unreachable' if exc.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH) else 'error'
        except Exception:
            error = 'error'
        results.append({'host': host, 'port': int(port), 'ok': error is None, 'error': error,
                        'ms': int(max(0.0, monotonic() - started) * 1000)})
    return results


def runtime_journal(runner: Runner, start: datetime, end: datetime, *, timeout: float) -> tuple[str, list[str]]:
    argv = ['journalctl', '-u', RUNTIME_UNIT, '--since', _journal_time(start), '--until', _journal_time(end),
            '-o', 'cat', '--no-pager', '-n', str(RUNTIME_JOURNAL_LINES)]
    code, text = _call(runner, argv, timeout)
    if code != 0 or _journal_denied(text):
        return 'denied', []
    return 'ok', text.splitlines()


def _net_match(network, text: str) -> bool:
    return network.matches(text) and not _NOT_NETWORK.search(text)


def runtime_net_signals(lines, network) -> dict:
    """Network patterns, and whether a traceback with a non-network exception appears (rule A.3 c). A pattern hit
    that names a loopback address or the runtime's catch-up back-pressure is an internal cause, not the network."""
    pattern_lines = [line for line in lines if _net_match(network, line)]
    foreign = False
    block: list[str] | None = None
    for line in list(lines) + ['']:
        if _TRACEBACK in line:
            if block is not None and not _net_match(network, '\n'.join(block)):
                foreign = True
            block = [line]
        elif block is not None:
            block.append(line)
            if line and not line[:1].isspace():         # the exception line closes the traceback
                if not _net_match(network, '\n'.join(block)):
                    foreign = True
                block = None
    if block is not None and len(block) > 1 and not _net_match(network, '\n'.join(block)):
        foreign = True
    return {'net_pattern': bool(pattern_lines), 'foreign_traceback': foreign,
            'pattern_lines': pattern_lines[-PATTERN_LINES_MAX:]}


def disk_usage(paths, statvfs=os.statvfs) -> dict[str, dict | None]:
    usage = {}
    for path in paths:
        try:
            result = statvfs(path)
        except OSError:
            usage[path] = None
            continue
        used = result.f_blocks - result.f_bfree
        total = used + result.f_bavail
        usage[path] = {'used_percent': round(100.0 * used / total, 1) if total > 0 else None,
                       'free_bytes': int(result.f_bavail * result.f_frsize)}
    return usage


def manifest_observe(root: Path) -> bool | None:
    """True/False from config/core_manifest.json (FROZEN and OBSERVE), None when unreadable."""
    try:
        data = json.loads(_read_bytes(Path(root) / 'config' / 'core_manifest.json', MAX_FILE_BYTES).decode('utf-8'))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    return data.get('status') == 'FROZEN' and data.get('operating_mode') == 'OBSERVE'


def read_commit(root: Path) -> dict:
    """HEAD of the checkout from .git in Python: refs, packed-refs, detached HEAD, worktree `gitdir:` files.
    Git is never executed (design E9)."""
    result = {'sha': None, 'ref': None, 'detached': None, 'error': None}
    git = Path(root) / '.git'
    try:
        common = git
        if git.is_file():
            pointer = _read_bytes(git, 4096).decode('utf-8').strip()
            if not pointer.startswith('gitdir:'):
                return {**result, 'error': 'invalid .git file'}
            target = Path(pointer[len('gitdir:'):].strip())
            git = target if target.is_absolute() else Path(root) / target
            common = git
            if (git / 'commondir').is_file():
                pointer = _read_bytes(git / 'commondir', 4096).decode('utf-8').strip()
                common = Path(pointer) if Path(pointer).is_absolute() else git / pointer
        head = _read_bytes(git / 'HEAD', 4096).decode('utf-8').strip()
    except (OSError, UnicodeDecodeError):
        return {**result, 'error': 'unreadable'}
    if _SHA.match(head):
        return {**result, 'sha': head, 'detached': True}
    if not head.startswith('ref:'):
        return {**result, 'error': 'invalid HEAD'}
    ref = head[len('ref:'):].strip()
    if not _REF.match(ref) or '..' in ref.split('/') or '//' in ref:
        return {**result, 'error': 'invalid ref'}
    result.update(ref=ref, detached=False)
    for base in dict.fromkeys((git, common)):
        try:
            value = _read_bytes(base / ref, 4096).decode('utf-8').strip()
        except (OSError, UnicodeDecodeError):
            continue
        if _SHA.match(value):
            return {**result, 'sha': value}
    for base in dict.fromkeys((common, git)):
        try:
            packed = _read_bytes(base / 'packed-refs', 8 * 1024 * 1024).decode('utf-8', 'replace')
        except OSError:
            continue
        for line in packed.splitlines():
            if line.startswith(('#', '^')):
                continue
            parts = line.split(' ', 1)
            if len(parts) == 2 and parts[1].strip() == ref and _SHA.match(parts[0]):
                return {**result, 'sha': parts[0]}
    return {**result, 'error': 'ref not found'}


def _short_sha(commit: Mapping) -> str | None:
    sha = commit.get('sha') if commit else None
    return sha[:12] if isinstance(sha, str) and _SHA.match(sha) else None


# --- observation -------------------------------------------------------------------------------------------------

@dataclass
class Observation:
    now: datetime
    controls: Controls
    journal_access: str                     # 'ok' | 'denied' (health history)
    health_samples: list[Sample]            # in the window, oldest first
    health_age: float | None
    health_stale: bool
    health_collected: bool                  # fresh_health() supplied a report
    watchdog_samples: list[Sample]
    snapshot: dict
    units: dict[str, dict]
    probes: list[dict]
    gap: dict | None                        # newest RED gap_last_60m with minute details in the window
    runtime: dict                           # runtime journal around the gap: access, net_pattern, foreign_traceback
    disk: dict
    manifest_observe: bool | None

    @property
    def latest_health(self) -> Sample | None:
        return self.health_samples[-1] if self.health_samples else None

    def file(self, name: str) -> dict | None:
        entry = self.snapshot.get(name) or {}
        return entry.get('data')

    def age(self, name: str) -> float | None:
        return (self.snapshot.get(name) or {}).get('age')


def _gap_from(samples: list[Sample]) -> dict | None:
    for sample in reversed(samples):
        check = sample.checks.get('gap_last_60m')
        if not isinstance(check, dict) or check.get('status') != 'RED':
            continue
        missing, first = check.get('missing'), check.get('first_missing')
        if not isinstance(missing, int) or isinstance(missing, bool) or missing <= 0 or not isinstance(first, list):
            continue
        minutes = sorted(moment for moment in (_parse_time(item) for item in first) if moment is not None)
        if not minutes:
            continue
        end = minutes[-1] + timedelta(minutes=1)
        if missing > len(minutes):
            end = max(end, _parse_time(check.get('window_end')) or sample.at)
        return {'at': sample.at, 'missing': missing, 'first': minutes[0], 'end': min(end, minutes[0] + timedelta(hours=1)),
                'first_missing': [_iso(moment) for moment in minutes]}
    return None


def observe(*, root: Path, data_dir: Path, policy: Policy, controls: Controls, now: datetime, runner: Runner,
            connect=None, collect=None, statvfs=os.statvfs, timeout: float = 10.0) -> Observation:
    window = timedelta(minutes=policy.hysteresis.window_minutes)
    since = now - window
    snapshot = read_snapshot(data_dir, now, window_minutes=policy.hysteresis.window_minutes)
    access, reports = health_history(runner, since, timeout=timeout)
    health_file = snapshot['server_health']
    stale = health_file['data'] is None or health_file['age'] is None \
        or health_file['age'] > policy.health.stale_seconds
    if health_file['data'] is not None:
        reports.append(health_file['data'])
    collected = None
    if stale:
        collected = fresh_health(root=root, collect=collect)
        if collected is not None:
            reports.append(collected)
    by_time: dict[datetime, Sample] = {}
    for report in reports:
        sample = health_sample(report)
        if sample is not None and since <= sample.at <= now + FUTURE_TOLERANCE:
            by_time[sample.at] = sample
    samples = [by_time[moment] for moment in sorted(by_time)]

    units = unit_states(runner, dict.fromkeys((RUNTIME_UNIT,) + policy.classes['UNIT'].units), timeout=timeout)
    probes = net_probe(policy.network.probes, connect=connect, timeout=policy.network.probe_timeout_seconds)
    gap = _gap_from(samples)
    runtime = {'access': 'skipped', 'net_pattern': False, 'foreign_traceback': False, 'pattern_lines': []}
    if gap is not None:
        context = timedelta(minutes=policy.network.gap_context_minutes)
        start, end = gap['first'] - context, min(gap['end'] + context, now + FUTURE_TOLERANCE)
        journal_access, lines = runtime_journal(runner, start, end, timeout=timeout)
        runtime = {'access': journal_access, 'start': _iso(start), 'end': _iso(end),
                   **runtime_net_signals(lines, policy.network)}
    return Observation(
        now=now, controls=controls, journal_access=access, health_samples=samples, health_age=health_file['age'],
        health_stale=stale, health_collected=collected is not None, watchdog_samples=snapshot['watchdog_samples'],
        snapshot=snapshot, units=units, probes=probes, gap=gap, runtime=runtime,
        disk=disk_usage(policy.disk.statvfs_paths, statvfs), manifest_observe=manifest_observe(root))


# --- evaluation --------------------------------------------------------------------------------------------------

@dataclass
class ClassFinding:
    name: str
    checks: set[str]                # failing checks of the class (window and this run)
    samples: int                    # RED samples in the window (+1 for an instant run check)
    run_hit: bool                   # a finding in this run's own view
    runs: int                       # runs in a row with run_hit, this one included
    open_worthy: bool               # the opening rule of the class holds
    minor: bool = False             # NETWORK below min_missing_minutes: logged, never an issue, never blocks
    details: list[str] = field(default_factory=list)


@dataclass
class Evaluation:
    now: datetime
    classes: dict[str, ClassFinding]        # only classes with a finding
    run_hits: dict[str, int]
    red_runs: dict[str, int]                # runs in a row with RED in the newest health sample (journal fallback)
    sub_findings: set[str]                  # every RED check of the window and run
    safety_unknown: set[str]
    suppressed: set[str]                    # DATA_FLOW checks explained by a network finding
    network_rules: set[str]
    minor: list[dict]
    journal_access: str
    explained_gap: str | None = None        # first missing minute of a gap with a non-network cause (kept in state)


def _run_checks(obs: Observation, policy: Policy) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    if obs.health_stale:
        hits['health_file'] = ['server_health.json']
    if _runtime_down(obs.units.get(RUNTIME_UNIT)):
        hits['runtime_unit'] = [RUNTIME_UNIT]
    full = [path for path, usage in obs.disk.items()
            if usage and usage['used_percent'] is not None and usage['used_percent'] >= policy.disk.red_percent]
    if full:
        hits['statvfs'] = full
    failed = [f"{item['host']}:{item['port']}" for item in obs.probes
              if not item['ok'] and item['host'] in policy.network.outage_hosts]
    if failed:
        hits['net_probe'] = failed
    for name in ('backup_last_run', 'restore_test'):
        data = obs.file(name)
        if data is not None and data.get('status') == 'FAIL':
            hits[name] = [f'{name}.json']
    down = [unit for unit in policy.classes['UNIT'].units
            if (obs.units.get(unit) or {}).get('query') == 'ok' and obs.units[unit].get('ActiveState') != 'active']
    if obs.health_stale:            # HEALTH_STALE includes the health timer itself
        folded = [unit for unit in down if unit.startswith('tim-server-health.')]
        hits['health_file'] += folded
        down = [unit for unit in down if unit not in folded]
    if down:
        hits['unit'] = down
    if obs.controls.selftest:
        hits['selftest'] = ['checkup:selftest']
    return hits


def _safety(obs: Observation, watch: list[Sample]) -> tuple[set[str], int, set[str]]:
    """Definite SAFETY findings and unknown ones. observe_only=False counts only when the dashboard answered 200 and
    said so, or the manifest itself says not OBSERVE; the watchdog also reports False when the dashboard is down.
    trading_action_count counts only as an int > 0; None (database down) stays unknown.
    Returns (definite checks, number of samples with a definite finding, unknown checks)."""
    definite, unknown, samples = set(), set(), 0
    status, age = obs.file('watchdog_status'), obs.age('watchdog_status')
    fresh = status is not None and age is not None and age <= WATCHDOG_FACTS_MAX_AGE
    checks = status.get('checks') if fresh and isinstance(status.get('checks'), dict) else {}
    observed = status.get('observed') if fresh and isinstance(status.get('observed'), dict) else {}
    check = checks.get('observe_only')
    if isinstance(check, dict) and check.get('status') == 'RED':
        said_no = observed.get('dashboard_status') == 200 and observed.get('dashboard_observe_only') is False
        manifest_no = observed.get('manifest_observe_only') is False and obs.manifest_observe is False
        if check.get('value') is False and (said_no or manifest_no):
            definite.add('watchdog.observe_only')
            samples += 1
        else:
            unknown.add('watchdog.observe_only')
    for source in [sample.checks for sample in watch] or ([checks] if checks else []):
        check = source.get('trading_action_count')
        if not isinstance(check, dict):
            continue
        value = check.get('value')
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            definite.add('watchdog.trading_action_count')
            samples += 1
        elif check.get('status') == 'RED':
            unknown.add('watchdog.trading_action_count')
    return definite, samples, unknown - definite


def _gap_explained(obs: Observation, policy: Policy, state: Mapping, health: list[Sample],
                   hits: Mapping[str, list[str]]) -> bool:
    """The gap already has a cause other than the network: an active chain episode of another class, or any finding
    (even below its threshold) of a chain class above NETWORK, such as a PostgreSQL restart, seen in this run or in
    an earlier run while the same gap was in the 60-min window."""
    if obs.gap is not None and state.get('explained_gap') == _iso(obs.gap['first']):
        return True
    chain = state.get('chain')
    if chain and chain.get('status') == 'active' and chain.get('top') != 'NETWORK':
        return True
    order = policy.chain_order
    above = order[:order.index('NETWORK')] if 'NETWORK' in order else ()
    for name in above:
        checks = set(policy.classes[name].checks)
        if checks & set(hits) or any(sample.red & checks for sample in health):
            return True
    return False


def _recent_outage(state: Mapping, policy: Policy, now: datetime) -> bool:
    """A probe to an outage host failed in one of the earlier runs of the last hour (state['probes'])."""
    since = now - timedelta(minutes=60)
    for record in state.get('probes') or []:
        at = _parse_time(record.get('at')) if isinstance(record, dict) else None
        if at is None or at < since:
            continue
        for item in record.get('results') or []:
            if isinstance(item, dict) and not item.get('ok') and item.get('host') in policy.network.outage_hosts:
                return True
    return False


def _network_rules(obs: Observation) -> set[str]:
    """Rule A.3 (b) and (c) on the newest RED gap of the window."""
    rules: set[str] = set()
    if obs.gap is None or obs.runtime.get('access') != 'ok':
        return rules
    if obs.runtime.get('net_pattern'):
        rules.add('net_pattern')
    latest = obs.latest_health
    candle = latest.checks.get('candle_freshness') if latest else None
    if isinstance(candle, dict) and candle.get('status') == 'GREEN' and not obs.runtime.get('foreign_traceback'):
        rules.add('past_gap')
    return rules


def evaluate(obs: Observation, policy: Policy, state: Mapping) -> Evaluation:
    """Findings per class for this run. Pure apart from reading the previous run counters from `state`."""
    window_start = obs.now - timedelta(minutes=policy.hysteresis.window_minutes)
    health = [sample for sample in obs.health_samples if sample.at >= window_start]
    watch = [sample for sample in obs.watchdog_samples if sample.at >= window_start]
    latest_health = health[-1] if health else None
    latest_watch = watch[-1] if watch else None
    hits = _run_checks(obs, policy)
    selftest = (state.get('independent') or {}).get('SELFTEST')
    if obs.controls.authority == 'unknown' and selftest and selftest.get('status') == 'active':
        hits['selftest'] = ['checkup:selftest']     # labels unreadable this run: the selftest neither ends nor counts
    explained = obs.gap is not None and _gap_explained(obs, policy, state, health, hits)
    rules = set() if explained else _network_rules(obs)
    missing = obs.gap['missing'] if obs.gap else 0
    network_minor = bool(rules) and missing < policy.network.min_missing_minutes
    chain = state.get('chain')
    # while a NETWORK episode runs and the probes failed within the last hour, a stale-candle or gap finding is the
    # catch-up after the outage, not a new DATA_FLOW cause; it keeps the NETWORK episode from counting clean runs
    network_episode = bool(chain and chain.get('status') == 'active' and chain.get('top') == 'NETWORK'
                           and _recent_outage(state, policy, obs.now))
    network_present = 'net_probe' in hits or bool(rules) or network_episode
    definite, safety_samples, unknown = _safety(obs, watch)
    denied = obs.journal_access != 'ok'
    previous_hits = state.get('run_hits') or {}
    previous_red = state.get('red_runs') or {}

    classes: dict[str, ClassFinding] = {}
    run_hits: dict[str, int] = {}
    red_runs: dict[str, int] = {}
    suppressed: set[str] = set()
    for name, policy_class in policy.classes.items():
        checks = set(policy_class.checks)
        latest_red = bool(latest_health and latest_health.red & checks)
        red_runs[name] = previous_red.get(name, 0) + 1 if latest_red else 0
        if name == 'SAFETY':
            failing, samples, run_hit, details = set(definite), safety_samples, bool(definite), []
        else:
            failing = set()
            health_samples = 0
            for sample in health:
                if sample.red & checks:
                    health_samples += 1
                    failing |= sample.red & checks
            watch_samples = 0
            for sample in watch:
                if sample.red & checks:
                    watch_samples += 1
                    failing |= sample.red & checks
            if denied and checks & _SAMPLE_HEALTH:
                health_samples = red_runs[name]     # fallback: RED in consecutive checkup runs
            run_level = sorted(check for check in checks & _RUN_CHECKS if check in hits)
            failing |= set(run_level)
            details = [detail for check in run_level for detail in hits[check]]
            samples = health_samples + watch_samples + (1 if set(run_level) & _INSTANT_CHECKS else 0)
            run_hit = bool(run_level) or latest_red or bool(latest_watch and latest_watch.red & checks)
            if name == 'NETWORK':
                failing |= rules
                run_hit = 'net_probe' in hits           # rule (a): probes failing in runs in a row
            if name == 'DATA_FLOW' and network_present:
                suppressed |= failing
                failing, run_hit = set(), False
        runs = previous_hits.get(name, 0) + 1 if run_hit else 0
        run_hits[name] = runs
        if not failing:
            continue
        open_worthy = bool((policy_class.open_red_samples and samples >= policy_class.open_red_samples)
                           or (policy_class.open_runs and runs >= policy_class.open_runs))
        minor = False
        if name == 'NETWORK' and rules:
            if not network_minor:
                open_worthy = True                      # rules (b) and (c) open at once
            elif not open_worthy:
                minor = True
        classes[name] = ClassFinding(name, failing, samples, run_hit, runs, open_worthy, minor, details)
    if network_episode and suppressed and 'NETWORK' not in classes:
        classes['NETWORK'] = ClassFinding('NETWORK', set(suppressed), 0, False, 0, False)    # present, never opens

    sub_findings = set().union(*(sample.red for sample in health + watch)) | set(hits) | rules | unknown | definite
    minor_entries = []
    if 'NETWORK' in classes and classes['NETWORK'].minor and obs.gap:
        minor_entries.append({'at': _iso(obs.now), 'class': 'NETWORK', 'rules': sorted(rules), 'missing': missing,
                              'first_missing': obs.gap['first_missing']})
    return Evaluation(obs.now, classes, run_hits, red_runs, sub_findings, unknown, suppressed, rules, minor_entries,
                      obs.journal_access, _iso(obs.gap['first']) if explained else None)


@dataclass
class Classification:
    chain_present: list[str]
    chain_open: list[str]
    primary: str | None             # chain class that leads now (opens or is the current class of the episode)
    blocked_by: str | None          # higher chain class with a finding that has not met its opening rule yet
    independent_present: list[str]
    independent_open: list[str]


def classify(evaluation: Evaluation, policy: Policy) -> Classification:
    """Precedence: only the highest chain class gets an issue. A higher class that is still below its threshold blocks
    the lower ones (they are likely its consequences); a minor network finding does not block."""
    present = [name for name in policy.chain_order if name in evaluation.classes]
    open_now = [name for name in present if evaluation.classes[name].open_worthy]
    primary = blocked = None
    for name in present:
        finding = evaluation.classes[name]
        if finding.open_worthy:
            primary = name
            break
        if finding.minor:
            continue
        blocked = name
        break
    independent = [name for name in policy.independent_classes if name in evaluation.classes]
    return Classification(present, open_now, primary, blocked, independent,
                          [name for name in independent if evaluation.classes[name].open_worthy])


# --- hysteresis --------------------------------------------------------------------------------------------------

def empty_state() -> dict:
    return {'v': STATE_VERSION, 'updated_at': None, 'chain': None, 'independent': {}, 'run_hits': {}, 'red_runs': {},
            'probes': [], 'minor_seen': [], 'state_lost_at': None, 'explained_gap': None}


def _chain_rank(name: str) -> int:
    return CHAIN_CLASSES.index(name) if name in CHAIN_CLASSES else len(CHAIN_CLASSES)


def _signature(evaluation: Evaluation, names) -> set[str]:
    signature = set()
    for name in names:
        finding = evaluation.classes.get(name)
        if finding:
            signature |= finding.checks
            signature |= {f'{name.lower()}:{detail}' for detail in finding.details}
    return signature


def resolve_threshold(policy: Policy, reopen_count: int) -> int:
    hysteresis = policy.hysteresis
    return min(hysteresis.resolve_clean_runs * 2 ** min(reopen_count, 16), hysteresis.resolve_max_clean_runs)


def _new_episode(name: str, now: datetime, signature: set[str], seen: list[str], adopt_only: bool) -> dict:
    return {'episode': episode_id(now), 'class': name, 'current': name, 'top': name, 'status': 'active',
            'opened_at': _iso(now), 'last_seen_at': _iso(now), 'resolved_at': None, 'reopen_count': 0,
            'clean_runs': 0, 'changed': 0, 'seen_classes': sorted(set(seen) | {name}), 'seen_checks': sorted(signature),
            'last_status_at': _iso(now), 'announced_mode': None, 'resolve_mode': None, 'adopt_only': bool(adopt_only)}


def _lower_check(check: str, top: str, slot: str, policy: Policy) -> bool:
    """A check that does not raise the severity of a chain episode: a network rule (b)/(c) restating the network
    class, or a check of a chain class below the episode's top class (a likely consequence)."""
    if slot != 'chain':
        return False
    if check in _NETWORK_RULES:
        return True
    for name in policy.chain_order[policy.chain_order.index(top) + 1:] if top in policy.chain_order else ():
        if check in policy.classes[name].checks or check.startswith(f'{name.lower()}:'):
            return True
    return False


def _step(episode: dict | None, *, slot: str, primary: str | None, present: bool, signature: set[str],
          seen: list[str], policy: Policy, now: datetime, adopt_only: bool) -> tuple[dict | None, dict | None]:
    hysteresis = policy.hysteresis
    if episode is None or episode['status'] == 'resolved':
        if primary is None:
            return episode, None
        if episode is not None:
            resolved_at = _parse_time(episode.get('resolved_at')) or now
            recent = now - resolved_at <= timedelta(hours=hysteresis.reopen_cooldown_hours)
            if recent and (slot != 'chain' or primary in episode['seen_classes']):
                episode = copy.deepcopy(episode)
                episode.update(status='active', resolved_at=None, clean_runs=0, current=primary, resolve_mode=None,
                               last_seen_at=_iso(now), reopen_count=episode['reopen_count'] + 1)
                episode['seen_classes'] = sorted(set(episode['seen_classes']) | set(seen) | {primary})
                episode['seen_checks'] = sorted(set(episode['seen_checks']) | signature)
                return episode, {'kind': 'reopened', 'number': episode['reopen_count'],
                                 'threshold': resolve_threshold(policy, episode['reopen_count'])}
        return _new_episode(primary, now, signature, seen, adopt_only), {'kind': 'opened'}

    episode = copy.deepcopy(episode)
    if not present:
        episode['clean_runs'] += 1
        if episode['clean_runs'] >= resolve_threshold(policy, episode['reopen_count']):
            episode.update(status='resolved', resolved_at=_iso(now))
            opened = _parse_time(episode['opened_at']) or now
            return episode, {'kind': 'resolved', 'clean_runs': episode['clean_runs'],
                             'duration_seconds': (now - opened).total_seconds()}
        return episode, None

    episode['clean_runs'] = 0
    episode['last_seen_at'] = _iso(now)
    new_class = None
    if primary is not None:
        episode['current'] = primary
        if slot == 'chain' and _chain_rank(primary) < _chain_rank(episode['top']):
            new_class, previous = primary, episode['top']
            episode['top'] = primary
    new_checks = sorted(check for check in signature - set(episode['seen_checks'])
                        if not _lower_check(check, episode['top'], slot, policy))
    episode['seen_classes'] = sorted(set(episode['seen_classes']) | set(seen))
    episode['seen_checks'] = sorted(set(episode['seen_checks']) | signature)
    if new_class or new_checks:
        change = {'new_class': new_class, 'previous_class': previous if new_class else None, 'new_checks': new_checks}
        if episode['changed'] < policy.rate_limits.changed_per_episode:
            episode['changed'] += 1
            return episode, {'kind': 'changed', 'number': episode['changed'], **change}
        episode['last_status_at'] = _iso(now)
        return episode, {'kind': 'status', 'reason': 'changed', **change}
    last = _parse_time(episode.get('last_status_at')) or _parse_time(episode['opened_at']) or now
    if now - last >= timedelta(hours=hysteresis.status_line_hours):
        episode['last_status_at'] = _iso(now)
        return episode, {'kind': 'status', 'reason': 'ongoing'}
    return episode, None


def advance(state: Mapping, evaluation: Evaluation, classification: Classification, policy: Policy, now: datetime, *,
            adopt_only: bool = False) -> tuple[dict, list[dict]]:
    """The hysteresis state machine (design A.3): one chain episode, one episode per independent class.
    Returns the new state and the transitions (opened, changed, status, resolved, reopened). Pure."""
    new = copy.deepcopy(dict(state))
    transitions = []
    slots = [('chain', classification.primary, bool(classification.chain_present),
              _signature(evaluation, classification.chain_open), classification.chain_open)]
    for name in policy.independent_classes:
        slots.append((name, name if name in classification.independent_open else None,
                      name in classification.independent_present, _signature(evaluation, [name]), [name]))
    independent = dict(new.get('independent') or {})
    for slot, primary, present, signature, seen in slots:
        episode = new.get('chain') if slot == 'chain' else independent.get(slot)
        episode, transition = _step(episode, slot=slot, primary=primary, present=present, signature=signature,
                                    seen=seen, policy=policy, now=now, adopt_only=adopt_only)
        if slot == 'chain':
            new['chain'] = episode
        elif episode is not None:
            independent[slot] = episode
        if transition is not None:
            transitions.append({'slot': slot, 'episode': episode['episode'], 'class': episode['class'], **transition})
    new['independent'] = independent
    new['explained_gap'] = evaluation.explained_gap
    new['run_hits'] = dict(evaluation.run_hits)
    new['red_runs'] = dict(evaluation.red_runs)
    new['updated_at'] = _iso(now)
    return new, transitions


def active_episodes(state: Mapping) -> list[tuple[str, dict]]:
    episodes = []
    if state.get('chain'):
        episodes.append(('chain', state['chain']))
    for name, episode in (state.get('independent') or {}).items():
        if episode:
            episodes.append((name, episode))
    return [(slot, episode) for slot, episode in episodes if episode['status'] == 'active']


def adopt_incidents(state: dict, incidents, policy: Policy) -> list[str]:
    """After a lost state.json (design A.3): take over the open incident issues of this host as active episodes, so
    they resolve and close as usual and no second issue opens for the same cause. `incidents` comes from
    `reporter.open_incidents()` (open issues with a TIM_INCIDENT_V1 marker, opened by the reporter). Only empty slots
    are filled, the newest episode per slot wins. A slot also counts as empty when it holds an adopt_only episode that
    matches no open issue: a lost-state run with GitHub unreadable started it, and it can never get an issue of its
    own. The episodes keep adopt_only: their open entry never creates.
    Returns the adopted 'CLASS/episode' names; changes `state` in place."""
    adopted = []
    items = [item for item in incidents or () if isinstance(item, dict) and isinstance(item.get('episode'), str)]
    known = {(item.get('class'), item['episode']) for item in items if item.get('host') == policy.host}
    for item in sorted(items, key=lambda item: item['episode'], reverse=True):
        name, episode = item.get('class'), item['episode']
        if item.get('host') != policy.host or name not in policy.classes or not _EPISODE.match(episode):
            continue
        try:
            opened = datetime.strptime(episode, '%Y%m%dT%H%MZ').replace(tzinfo=UTC)
        except ValueError:
            continue
        slot = 'chain' if name in policy.chain_order else name
        independent = state.setdefault('independent', {})
        current = state.get('chain') if slot == 'chain' else independent.get(slot)
        if current is not None and not (current.get('adopt_only')
                                        and (current.get('class'), current.get('episode')) not in known):
            continue
        new = _new_episode(name, opened, set(), [], True)
        if slot == 'chain':
            state['chain'] = new
        else:
            independent[slot] = new
        adopted.append(f'{name}/{episode}')
    return adopted


# --- state file --------------------------------------------------------------------------------------------------

def _valid_episode(value) -> bool:
    if not isinstance(value, dict):
        return False
    text = lambda key: isinstance(value.get(key), str)              # noqa: E731
    count = lambda key: isinstance(value.get(key), int) and not isinstance(value.get(key), bool) \
        and value[key] >= 0                                          # noqa: E731
    names = lambda key: isinstance(value.get(key), list) and all(isinstance(item, str) for item in value[key])  # noqa: E731
    return (text('episode') and bool(_EPISODE.match(value['episode'])) and value.get('class') in CLASS_NAMES
            and value.get('current') in CLASS_NAMES and value.get('top') in CLASS_NAMES
            and value.get('status') in ('active', 'resolved') and _parse_time(value.get('opened_at')) is not None
            and all(count(key) for key in ('reopen_count', 'clean_runs', 'changed'))
            and names('seen_classes') and names('seen_checks')
            and value.get('announced_mode') in _REPORT_RANK and value.get('resolve_mode') in _REPORT_RANK
            and isinstance(value.get('adopt_only'), bool)
            and all(value.get(key) is None or isinstance(value.get(key), str)
                    for key in ('resolved_at', 'last_status_at', 'last_seen_at')))


def _valid_state(data) -> dict | None:
    if not isinstance(data, dict) or data.get('v') != STATE_VERSION:
        return None
    state = empty_state()
    chain = data.get('chain')
    if chain is not None and not _valid_episode(chain):
        return None
    state['chain'] = chain
    independent = data.get('independent') or {}
    if not isinstance(independent, dict) or not all(name in CLASS_NAMES and _valid_episode(episode)
                                                    for name, episode in independent.items()):
        return None
    state['independent'] = independent
    for key in ('run_hits', 'red_runs'):
        counters = data.get(key) or {}
        if not isinstance(counters, dict) or not all(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in counters.values()):
            return None
        state[key] = counters
    for key, kind in (('probes', dict), ('minor_seen', str)):
        value = data.get(key) or []
        if not isinstance(value, list):
            return None
        state[key] = [item for item in value if isinstance(item, kind)]
    for key in ('updated_at', 'state_lost_at', 'explained_gap'):
        value = data.get(key)
        state[key] = value if isinstance(value, str) else None
    return state


def _load_state_file(path: Path) -> tuple[dict | None, bool]:
    try:
        raw = _read_bytes(path, 4 * MAX_FILE_BYTES)
    except FileNotFoundError:
        return None, False
    except OSError:
        return None, True
    try:
        return _valid_state(json.loads(raw.decode('utf-8'))), True
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None, True


def load_state(data_dir: Path, *, previous_run: bool = True) -> tuple[dict, str]:
    """('ok' | 'prev' | 'lost' | 'new'). 'lost': both files missing or unreadable after earlier runs, so the reporter
    must adopt open marker issues instead of creating new ones (design A.3)."""
    paths = CheckupPaths(Path(data_dir))
    existed = False
    for path, status in ((paths.state, 'ok'), (paths.state_prev, 'prev')):
        state, exists = _load_state_file(path)
        existed |= exists
        if state is not None:
            return state, status
    return empty_state(), 'lost' if existed or previous_run else 'new'


def save_state(data_dir: Path, state: Mapping, *, rotate: bool = True) -> None:
    """state.json atomically; with `rotate` the previous valid state goes to state.json.prev first."""
    paths = CheckupPaths(Path(data_dir))
    if rotate:
        current, _ = _load_state_file(paths.state)
        if current is not None:
            _write_json(paths.state_prev, current)
    _write_json(paths.state, state)


# --- texts -------------------------------------------------------------------------------------------------------

def incident_marker(name: str, episode: str, host: str) -> str:
    return f'<!-- TIM_INCIDENT_V1 class={name} episode={episode} host={host} -->'


def _names(values, limit: int = 24) -> str:
    values = sorted(dict.fromkeys(values))
    if not values:
        return 'keine'
    text = ', '.join(values[:limit])
    return text + (f' (+{len(values) - limit})' if len(values) > limit else '')


def _failing_text(evaluation: Evaluation, name: str) -> str:
    finding = evaluation.classes.get(name)
    if finding is None:
        return 'keine'
    text = _names(finding.checks)
    return f'{text} ({_names(finding.details)})' if finding.details else text


def _sub_findings(evaluation: Evaluation, policy: Policy, slot: str, name: str) -> set[str]:
    if slot != 'chain':
        return set()
    own = set(policy.classes[name].checks) | (evaluation.classes[name].checks if name in evaluation.classes else set())
    independent = set()
    for other in policy.independent_classes:
        if other in evaluation.classes:
            independent |= set(policy.classes[other].checks)
    return (evaluation.sub_findings - own - independent) | evaluation.safety_unknown


def _commit_line(root: Path, commit: Mapping) -> str:
    label = 'Commit /opt/tim' if Path(root) == SERVER_ROOT else 'Commit des Checkouts'
    return f'- {label}: {_short_sha(commit) or "unbekannt"} (aus .git gelesen)'


def issue_title(name: str, host: str, opened: datetime) -> str:
    return f'Vorfall {name} auf {host} seit {_human(opened)}'


def issue_body(episode: Mapping, evaluation: Evaluation, policy: Policy, settings: Settings, *, root: Path,
               commit: Mapping, slot: str) -> str:
    """Deterministic body (design B.5), managed part only: no log text, no model text. The reporter keeps the status
    section (TIM_INCIDENT_STATUS_BEGIN/END) outside this part; the diagnosis fields block follows in PR-2."""
    name, host = episode['class'], policy.host
    policy_class = policy.classes[name]
    opened = _parse_time(episode['opened_at'])
    lines = [f'## Vorfall {name} auf {host}']
    if settings.owner_login:
        lines.append(f'cc @{settings.owner_login}')
    current = episode.get('current') or name
    lines.append(f'- Erkannt: {_human(opened)} (Checkup); fehlschlagende Prüfungen: {_failing_text(evaluation, current)}')
    lines.append(f'- Unterbefunde: {_names(_sub_findings(evaluation, policy, slot, current))}')
    lines.append(_commit_line(root, commit))
    lines.append(f'- Einordnung (feste Regel): {policy_class.category}')
    lines.append(f'- Behebung: {policy_class.remedy}, siehe docs/TIM_CHECKUP.md. '
                 'Pipeline nur nach Label status:ready durch den Inhaber.')
    if policy_class.qwen and settings.diagnosis == 'on':
        lines.append('- Evidenz und Qwen-Diagnose (ungeprüft) stehen nur in Kommentaren.')
    else:
        lines.append('- Evidenz steht nur in Kommentaren.')
    lines.append(incident_marker(name, episode['episode'], host))
    return '\n'.join(lines)


def _clip(text: str, budget: int, keep: str) -> str:
    data = text.encode('utf-8')
    if len(data) <= budget:
        return text
    if keep == 'tail':
        piece = data[-budget:].decode('utf-8', 'ignore')
        return '[... gekürzt]\n' + piece.split('\n', 1)[-1]
    piece = data[:budget].decode('utf-8', 'ignore')
    return piece.rsplit('\n', 1)[0] + '\n[... gekürzt]'


def _size(text: str) -> int:
    return len(text.encode('utf-8'))


def _section(heading: str, text: str, literals, budget: int | None, keep: str) -> str:
    # Redact before clipping (a cut secret would escape the literal check), then the only way out: untrusted_block.
    body = redact(text, literals)
    if budget is not None:
        body = _clip(body, budget, keep)
    return f'### {heading}\n{untrusted_block(body, literals)}'


def format_evidence(intro: str, sections, literals, limit: int) -> str:
    """Intro (fixed text) and sections (heading, raw text, 'head'|'tail'); at most `limit` bytes in UTF-8."""
    note = '[Evidenz gekürzt: Grenze für Kommentare erreicht]'
    sections = list(sections)
    rendered = [_section(heading, text, literals, None, keep) for heading, text, keep in sections]
    text = '\n\n'.join([intro] + rendered)
    if _size(text) <= limit:
        return text
    budget = max(256, (limit - _size(intro) - _size(note) - 200 * max(1, len(sections))) // max(1, len(sections)))
    rendered = [_section(heading, raw, literals, budget, keep) for heading, raw, keep in sections]
    while True:
        text = '\n\n'.join([intro] + rendered + [note])
        if _size(text) <= limit or not rendered:
            break
        rendered.pop()
    return text if _size(text) <= limit else _clip(intro, max(64, limit - 32), 'head')


def _guard(text: str, fallback: str) -> str:
    """Every outgoing text must pass the independent final scan; a hit replaces it by a fixed text."""
    return fallback if final_scan(text) else text


def _json(value) -> str:
    return json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False, default=str)


# --- evidence ----------------------------------------------------------------------------------------------------

def _proc_text(proc_dir: Path) -> str:
    lines = []
    try:
        for line in _read_bytes(proc_dir / 'meminfo', 64 * 1024).decode('utf-8', 'replace').splitlines():
            if line.startswith(('MemAvailable:', 'MemTotal:', 'SwapFree:')):
                lines.append(line)
    except OSError:
        lines.append('meminfo: nicht lesbar')
    for name in ('loadavg', 'pressure/cpu', 'pressure/memory', 'pressure/io'):
        try:
            content = _read_bytes(proc_dir / name, 16 * 1024).decode('utf-8', 'replace').strip()
        except OSError:
            continue
        lines.append(f'{name}:')
        lines.extend(content.splitlines())
    return '\n'.join(lines) or 'nicht verfügbar'


@dataclass
class EvidenceContext:
    runner: Runner
    root: Path
    policy: Policy
    literals: list[str]
    time_left: Callable[[], float]
    proc_dir: Path
    statvfs: Callable
    commit: dict
    probe_history: list
    units: dict


def collect_evidence(obs: Observation, evaluation: Evaluation, episode: Mapping, slot: str,
                     context: EvidenceContext) -> list[tuple[str, str, str]]:
    """Evidence sections (design A.4) as (heading, raw text, keep); raw text is redacted when it is formatted."""
    policy = context.policy
    limits = policy.limits
    name = episode.get('current') or episode['class']
    finding = evaluation.classes.get(name)
    latest = obs.latest_health
    sections = []
    summary = {
        'klasse': name, 'episode': episode['episode'],
        'fehlschlagend': sorted(finding.checks) if finding else [],
        'details': list(finding.details) if finding else [],
        'unterbefunde': sorted(_sub_findings(evaluation, policy, slot, name)),
        'health_alter_s': round(obs.health_age, 1) if isinstance(obs.health_age, (int, float)) else None,
        'health_frisch_gesammelt': obs.health_collected, 'journal_zugriff': obs.journal_access,
        'health': {key: value for key, value in (latest.checks.items() if latest else ())
                   if not (isinstance(value, dict) and value.get('status') == 'GREEN')},
    }
    sections.append(('1. Fehlschlagende Prüfungen und Unterbefunde', _json(summary), 'head'))

    units = list(dict.fromkeys(policy.classes[name].units + tuple(finding.details if finding and name == 'UNIT'
                                                                  else ())))[:EVIDENCE_UNITS_MAX]
    timeout = float(limits.command_timeout_seconds)
    missing_units = [unit for unit in units if unit not in context.units]
    if missing_units and context.time_left() > timeout + limits.create_min_remaining_seconds:
        context.units.update(unit_states(context.runner, missing_units, timeout=timeout))
    lines = []
    for unit in units:
        state = context.units.get(unit)
        lines.append(f'{unit}: ' + (' '.join(f'{key}={state.get(key)}' for key in UNIT_PROPERTIES)
                                    if state and state.get('query') == 'ok' else 'nicht abfragbar'))
    sections.append(('2. Unit-Status', '\n'.join(lines) or 'keine Units', 'head'))

    opened = _parse_time(episode['opened_at']) or obs.now
    since = opened - timedelta(minutes=limits.journal_before_open_minutes)
    for unit in units:
        if context.time_left() <= timeout + limits.create_min_remaining_seconds:
            sections.append((f'3. Journal {unit}', 'übersprungen: Zeitlimit des Laufs', 'tail'))
            continue
        argv = ['journalctl', '-u', unit, '--since', _journal_time(since), '-n', str(limits.journal_lines),
                '-o', 'short-iso', '--no-pager']
        code, text = _call(context.runner, argv, timeout)
        text = _clip(redact(text, context.literals), limits.journal_bytes, 'tail') if code == 0 \
            else f'journalctl Exit {code}'
        sections.append((f'3. Journal {unit}', text or 'keine Einträge', 'tail'))

    sections.append(('4. Commit', _json(context.commit), 'head'))
    gap = latest.checks.get('gap_last_60m') if latest else None
    gap_text = _json({'missing': gap.get('missing'), 'first_missing': gap.get('first_missing'),
                      'status': gap.get('status')} if isinstance(gap, dict) else None)
    tail = obs.snapshot.get('gap_incidents_tail') or []
    sections.append(('5. Lücken', gap_text + '\n' + '\n'.join(tail[-limits.gap_incidents_lines:]), 'head'))
    disk = []
    for path, usage in disk_usage(policy.evidence.statvfs_paths, context.statvfs).items():
        disk.append(f'{path}: nicht vorhanden' if usage is None
                    else f"{path}: {usage['used_percent']} % belegt, {usage['free_bytes']} Bytes frei")
    sections.append(('6. Speicherplatz', '\n'.join(disk), 'head'))
    sections.append(('7. Speicher und Last', _proc_text(context.proc_dir), 'head'))
    network = [f"Regeln: {_names(evaluation.network_rules)}; Runtime-Journal: {obs.runtime.get('access')}; "
               f"fremder Traceback: {'ja' if obs.runtime.get('foreign_traceback') else 'nein'}"]
    for run in context.probe_history[-policy.network.probe_history_runs:]:
        if not isinstance(run, dict):
            continue
        probes = ', '.join(f"{item.get('host')}:{item.get('port')} {'ok' if item.get('ok') else item.get('error')} "
                           f"{item.get('ms')} ms" for item in run.get('results') or [] if isinstance(item, dict))
        network.append(f"{run.get('at')}: {probes}")
    network.extend(obs.runtime.get('pattern_lines') or [])
    sections.append(('8. Netzproben und Netzmuster', '\n'.join(network), 'tail'))
    status = obs.file('watchdog_status') or {}
    recovery = obs.file('watchdog_recovery_state') or {}
    maintenance = obs.file('maintenance_last_run') or {}
    watchdog = {
        'status': status.get('status'), 'checked_at': status.get('checked_at'),
        'nicht_gruen': {key: value for key, value in (status.get('checks') or {}).items()
                        if isinstance(value, dict) and value.get('status') != 'GREEN'},
        'letzter_neustart': recovery.get('last_restart_attempt_at'),
        'restartable_red_in_folge': recovery.get('consecutive_restartable_red'),
        'wartung': {key: maintenance.get(key) for key in ('status', 'completed_at') if key in maintenance},
    }
    sections.append(('9. Watchdog', _json(watchdog), 'head'))
    return sections


def secret_literals(settings: Settings, environ: Mapping[str, str]) -> list[str]:
    """Known secrets for literal redaction: the DB password and every line of the App key. Never logged."""
    literals = []
    secret_file = settings.database_secret_file or environ.get('TIM_DATABASE_SECRET_FILE')
    if isinstance(secret_file, str) and secret_file.startswith('/'):
        try:
            value = _read_bytes(Path(secret_file), 64 * 1024).decode('utf-8', 'replace').strip()
            if value:
                literals.append(value)
        except OSError:
            pass
    if settings.credentials_directory:
        try:
            key = _read_bytes(Path(settings.credentials_directory) / 'github-app-key', 64 * 1024)
            literals.extend(line.strip() for line in key.decode('utf-8', 'replace').splitlines() if line.strip())
        except OSError:
            pass
    return literals


def reporter_literals(reporter) -> list[str]:
    """The reporter's known secrets (App key lines, DB password and, after read_controls, the installation token)."""
    try:
        values = getattr(reporter, 'literals', ()) or ()
        return [value for value in values if isinstance(value, str) and value]
    except Exception:
        return []


# --- outbox entries ----------------------------------------------------------------------------------------------

def plan_reports(state: Mapping, transitions: list[dict], reporting: str) -> tuple[list, list]:
    """(plan, marks). plan: (action, slot, episode, transition) in delivery order; marks: (slot, episode, key, value)
    to apply with `apply_marks` once the entries are queued. Nothing while reporting is 'off'.

    - An active episode announced below the current mode is announced now (open entry with its original detection
      time), so an episode that started in off or dry-run gets its issue once reporting is 'on'.
    - A resolved episode gets its resolve entry once, in the mode it was announced in; when reporting is elsewhere
      at that moment, the entry waits (an issue opened while 'on' is closed only by an 'on' run).
    - changed, status and reopen entries come from this run's transitions."""
    if reporting not in ('dry-run', 'on'):
        return [], []
    by_slot: dict[str, list[dict]] = {}
    for transition in transitions:
        by_slot.setdefault(transition['slot'], []).append(transition)
    episodes = ([('chain', state['chain'])] if state.get('chain') else []) + \
        [(name, episode) for name, episode in (state.get('independent') or {}).items() if episode]
    plan, marks = [], []
    for slot, episode in episodes:
        announced = episode.get('announced_mode')
        if episode['status'] == 'active' and _REPORT_RANK[announced] < _REPORT_RANK[reporting]:
            plan.append(('announce', slot, episode, None))
            marks.append((slot, episode['episode'], 'announced_mode', reporting))
            continue
        if announced is None:
            continue
        for transition in by_slot.get(slot, []):
            if transition['episode'] == episode['episode'] and transition['kind'] not in ('opened', 'resolved'):
                plan.append((transition['kind'], slot, episode, transition))
        if episode['status'] == 'resolved' and reporting == announced \
                and _REPORT_RANK[episode.get('resolve_mode')] < _REPORT_RANK[announced]:
            plan.append(('resolved', slot, episode, None))
            marks.append((slot, episode['episode'], 'resolve_mode', reporting))
    return plan, marks


def apply_marks(state: dict, marks) -> None:
    for slot, episode_id, key, value in marks:
        episode = state.get('chain') if slot == 'chain' else (state.get('independent') or {}).get(slot)
        if episode and episode['episode'] == episode_id:
            episode[key] = value


def _entry(kind: str, episode: Mapping, host: str, at: str, active: bool, commit: str | None, **fields) -> dict:
    entry = {'v': ENTRY_VERSION, 'kind': kind, 'episode': episode['episode'], 'class': episode['class'], 'host': host,
             'at': at, 'active': active, **fields}
    if commit:
        entry['commit'] = commit
    return entry


def _one_line(text: str, limit: int = STATUS_MAX_CHARS) -> str:
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit - 4].rstrip() + ' ...'


def _resolve_tag(episode: Mapping) -> str:
    return 'resolved' if episode['reopen_count'] == 0 else f"resolved-{episode['reopen_count']}"


def build_entries(plan, obs: Observation, evaluation: Evaluation, policy: Policy, settings: Settings, *, root: Path,
                  context: EvidenceContext, evidence_dir: Path | None = None) -> list[dict]:
    host, now = policy.host, obs.now
    limit = policy.limits.evidence_comment_bytes
    commit = _short_sha(context.commit)
    withheld = '[Text zurückgehalten: Schlussprüfung]'
    entries = []

    def evidence(slot: str, episode: Mapping, intro: str, tag: str) -> str:
        sections = collect_evidence(obs, evaluation, episode, slot, context)
        text = _guard(format_evidence(intro, sections, context.literals, limit), intro + '\n\n' + withheld)
        if evidence_dir is not None:
            try:
                directory = evidence_dir / episode['episode']
                directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                _write_atomic(directory / f"{episode['class']}-{tag}.md", text.encode('utf-8'))
            except OSError:
                pass
        return text

    for action, slot, episode, transition in plan:
        name, current = episode['class'], episode.get('current') or episode['class']
        label = f"Vorfall {name} auf {host} (Episode {episode['episode']})"
        if action == 'announce':
            opened = _parse_time(episode['opened_at'])
            title = issue_title(name, host, opened)
            body = issue_body(episode, evaluation, policy, settings, root=root, commit=context.commit, slot=slot)
            if final_scan(title) or final_scan(body):
                raise CheckupError('fixed issue text failed the final scan')
            entries.append(_entry('open', episode, host, episode['opened_at'], True, commit, title=title, body=body,
                                  labels=list(policy.classes[name].issue_labels),
                                  adopt_only=bool(episode.get('adopt_only'))))
            intro = (f'Evidenz zum {label}, gesammelt {_human(now)}. '
                     'Alle Auszüge sind maschinell redigiert und ungeprüft.')
            entries.append(_entry('comment', episode, host, _iso(now), True, commit, tag='evidence',
                                  text=evidence(slot, episode, intro, 'evidence')))
        elif action == 'changed':
            lines = [f'Verändert: {label}, {_human(now)}.']
            if transition.get('new_class'):
                lines.append(f"- Neue Klasse: {transition['new_class']} (vorher {transition['previous_class']})")
            if transition.get('new_checks'):
                lines.append(f"- Neue Prüfungen: {_names(transition['new_checks'])}")
            lines.append(f'- Höchstens {policy.rate_limits.changed_per_episode} solche Kommentare je Episode, '
                         'danach nur die Statuszeile.')
            tag = f"changed-{transition['number']}"
            entries.append(_entry('comment', episode, host, _iso(now), True, commit, tag=tag,
                                  text=evidence(slot, episode, '\n'.join(lines), tag)))
        elif action == 'status':
            if transition.get('reason') == 'changed':
                detail = '; '.join(part for part in (
                    f"neue Klasse {transition['new_class']}" if transition.get('new_class') else '',
                    f"neue Prüfungen {_names(transition.get('new_checks') or [])}"
                    if transition.get('new_checks') else '') if part)
                status = f'Stand {_human(now)}: verändert ({detail}), Kommentargrenze erreicht; Klasse {current}'
            else:
                status = (f'Stand {_human(now)}: weiterhin aktiv; Klasse {current}; '
                          f'Prüfungen: {_failing_text(evaluation, current)}')
            entries.append(_entry('status_line', episode, host, _iso(now), True, commit,
                                  status=_guard(_one_line(status), f'Stand {_human(now)}: weiterhin aktiv')))
        elif action == 'reopened':
            tag = f"reopen-{transition['number']}"
            lines = [f'Wieder aktiv: {label}, {_human(now)}, innerhalb von '
                     f'{policy.hysteresis.reopen_cooldown_hours:g} h nach der Erholung (Wiederöffnung '
                     f"{transition['number']}).",
                     f'- Fehlschlagende Prüfungen: {_failing_text(evaluation, current)}',
                     f"- Neue Auflöseschwelle: {transition['threshold']} saubere Läufe"]
            entries.append(_entry('reopen', episode, host, _iso(now), True, commit, tag=tag,
                                  text=evidence(slot, episode, '\n'.join(lines), tag)))
        elif action == 'resolved':
            opened = _parse_time(episode['opened_at']) or now
            resolved = _parse_time(episode.get('resolved_at')) or now
            text = '\n'.join([
                f"Erholt: {label} ist seit {episode['clean_runs']} sauberen Läufen ohne RED-Befund.",
                f'- Dauer: {_duration((resolved - opened).total_seconds())} '
                f'(erkannt {_human(opened)}, erholt {_human(resolved)})',
                _commit_line(root, context.commit),
                'Der Melder schließt das Issue.'])
            entries.append(_entry('resolve', episode, host, _iso(resolved), False, commit, tag=_resolve_tag(episode),
                                  text=_guard(text, f'Erholt: {label}.')))
    if settings.reporting in ('dry-run', 'on'):
        for item in entries:
            item['mode'] = settings.reporting       # a dry-run run keeps entries of 'on' for the next 'on' run
    return entries


# --- run ---------------------------------------------------------------------------------------------------------

def _lock(path: Path) -> int | None:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(descriptor)
        return None
    return descriptor


def _emit(summary: Mapping) -> None:
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def _report_value(report, name: str, default):
    return getattr(report, name, default) if report is not None else default


def _record_minor(paths: CheckupPaths, state: dict, minor: list[dict], host: str) -> int:
    seen = list(state.get('minor_seen') or [])
    written = 0
    for item in minor:
        if any(minute in seen for minute in item['first_missing']):
            continue
        _append_line(paths.minor, {**item, 'host': host})
        seen.extend(item['first_missing'])
        written += 1
    state['minor_seen'] = seen[-MINOR_SEEN_KEPT:]
    return written


def run(*, root: Path, data_dir: Path, policy: Policy, settings: Settings, reporter, environ: Mapping[str, str],
        now=None, runner: Runner | None = None, connect=None, monotonic=time.monotonic, spool=None,
        health_collect=None, statvfs=None, proc_dir: Path = Path('/proc')) -> int:
    """One checkup run; returns the exit code: 0 normal (also revoked/silenced), 3 reporting disturbed or journal
    denied, 1 internal error. `reporter.deliver` gets `deadline` = start + limits.run_timeout_seconds on the
    `monotonic` clock (pass the reporter the same clock). Extra keywords are test seams: `spool` (default
    github.Spool(data/incidents/outbox)), `health_collect` (default scripts.tim_server_health.collect), `statvfs`,
    `proc_dir`."""
    started = monotonic()
    base = _utc(now if now is not None else time.time())
    deadline = started + policy.limits.run_timeout_seconds     # a monotonic() value, as Reporter.deliver expects

    def current() -> datetime:
        return base + timedelta(seconds=max(0.0, monotonic() - started))

    def time_left() -> float:
        return policy.limits.run_timeout_seconds - (monotonic() - started)

    disable_core_dumps()
    paths = CheckupPaths(Path(data_dir))
    try:
        paths.incidents.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = _lock(paths.lock)
    except OSError:
        _emit({'event': 'checkup_end', 'host': policy.host, 'exit_code': 1, 'error': 'lock unavailable',
               'reporting': 'unknown', 'preflight': 'skipped', 'journal_access': 'unknown', 'open': []})
        return 1
    if lock is None:
        _emit({'event': 'checkup_end', 'host': policy.host, 'exit_code': 0, 'skipped': 'locked',
               'reporting': 'unknown', 'preflight': 'skipped', 'journal_access': 'unknown', 'open': []})
        return 0
    summary: dict = {'event': 'checkup_end', 'host': policy.host, 'started_at': _iso(base)}
    exit_code = 1
    try:
        previous_run = paths.last_run.exists()
        _write_json(paths.last_run, {'v': 1, 'phase': 'started', 'started_at': _iso(base), 'pid': os.getpid(),
                                     'host': policy.host})
        summary, exit_code = _run_locked(
            root=Path(root), paths=paths, policy=policy, settings=settings, reporter=reporter, environ=environ,
            base=base, current=current, time_left=time_left, deadline=deadline, previous_run=previous_run,
            runner=runner or default_runner, connect=connect, spool=spool, health_collect=health_collect,
            statvfs=statvfs or os.statvfs, proc_dir=Path(proc_dir))
    except Exception as exc:        # fixed text: the type name only, never the message
        exit_code = 1
        summary.update({'exit_code': 1, 'error': type(exc).__name__,
                        'reporting': summary.get('reporting', 'unknown'), 'preflight': 'skipped',
                        'journal_access': summary.get('journal_access', 'unknown'), 'open': summary.get('open', [])})
    finally:
        finished = current()
        summary['exit_code'] = exit_code
        summary['finished_at'] = _iso(finished)
        summary['duration_seconds'] = round(max(0.0, monotonic() - started), 1)
        try:
            _write_json(paths.last_run, {
                'v': 1, 'phase': 'finished', 'started_at': _iso(base), 'finished_at': _iso(finished),
                'exit_code': exit_code, 'reporting': summary.get('reporting'),
                'journal_access': summary.get('journal_access'), 'open': len(summary.get('open') or []),
                'host': policy.host})
        except OSError:
            exit_code = summary['exit_code'] = 1
        _emit(summary)
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
        finally:
            os.close(lock)
    return exit_code


def _run_locked(*, root, paths: CheckupPaths, policy: Policy, settings: Settings, reporter, environ, base, current,
                time_left, deadline, previous_run, runner, connect, spool, health_collect, statvfs, proc_dir):
    now = base
    state, state_status = load_state(paths.data, previous_run=previous_run)
    if state_status == 'lost':
        state['state_lost_at'] = _iso(now)
    lost_at = _parse_time(state.get('state_lost_at'))
    adopt_only = lost_at is not None and now - lost_at <= timedelta(hours=policy.hysteresis.reopen_cooldown_hours)

    try:
        controls = reporter.read_controls()
        if not isinstance(controls, Controls):
            raise TypeError
    except Exception:
        controls = Controls('unknown', frozenset()) if settings.reporting != 'off' else NOT_CONFIGURED
    adopted = []
    if adopt_only and settings.reporting == 'on' and controls.open:
        try:
            candidate = copy.deepcopy(state)
            adopted = adopt_incidents(candidate, reporter.open_incidents(), policy)
            state = candidate
        except Exception:
            adopted = []        # GitHub not readable: new episodes stay adopt_only, the next run tries again

    timeout = float(policy.limits.command_timeout_seconds)
    obs = observe(root=root, data_dir=paths.data, policy=policy, controls=controls, now=now, runner=runner,
                  connect=connect, collect=health_collect, statvfs=statvfs, timeout=timeout)
    evaluation = evaluate(obs, policy, state)
    classification = classify(evaluation, policy)
    new_state, transitions = advance(state, evaluation, classification, policy, now, adopt_only=adopt_only)
    new_state['probes'] = (list(state.get('probes') or []) + [{'at': _iso(now), 'results': obs.probes}])[
        -policy.network.probe_history_runs:]
    minor_written = _record_minor(paths, new_state, evaluation.minor, policy.host)

    plan, marks = plan_reports(new_state, transitions, settings.reporting)
    literals = secret_literals(settings, environ) + reporter_literals(reporter)
    entries = []
    if plan:
        context = EvidenceContext(runner=runner, root=root, policy=policy, literals=literals,
                                  time_left=time_left, proc_dir=proc_dir, statvfs=statvfs, commit=read_commit(root),
                                  probe_history=new_state['probes'], units=dict(obs.units))
        entries = build_entries(plan, obs, evaluation, policy, settings, root=root, context=context,
                                evidence_dir=paths.evidence)
    if spool is None:
        from .github import Spool
        spool = Spool(paths.outbox, literals=literals, coalesce_after=policy.limits.spool_coalesce_after,
                      clock=lambda: current().timestamp())     # queued_at on the run's clock, like `at`
    # State first, without the marks: if it cannot be written nothing is queued (no new episode per run). A failure
    # while queueing repeats the same entries next run (same episode and tag, idempotent in the reporter).
    save_state(paths.data, new_state)
    for entry in entries:
        spool.enqueue(entry)
    if marks:
        apply_marks(new_state, marks)
        save_state(paths.data, new_state, rotate=False)

    report = reporter.deliver(spool, deadline=deadline)
    reporting = _report_value(report, 'reporting', 'unknown')
    exit_code = 0
    if obs.journal_access != 'ok' or _report_value(report, 'exit_code', 0) == 3 \
            or settings.requested != settings.reporting:
        exit_code = 3
    elif _report_value(report, 'exit_code', 0) not in (0, 3):
        exit_code = 1
    summary = {
        'event': 'checkup_end', 'host': policy.host, 'started_at': _iso(base), 'reporting': reporting,
        'preflight': _report_value(report, 'preflight', 'skipped'), 'journal_access': obs.journal_access,
        'authority': controls.authority, 'settings': settings.reason or 'ok', 'diagnosis': settings.diagnosis,
        'health': 'stale' if obs.health_stale else 'ok', 'state': state_status,
        'open': [{'class': episode['class'], 'episode': episode['episode'], 'current': episode['current'],
                  'announced': episode['announced_mode']} for _, episode in active_episodes(new_state)],
        'transitions': [f"{item['kind']}:{item['class']}:{item['episode']}" for item in transitions],
        'blocked_by': classification.blocked_by, 'minor': minor_written, 'enqueued': len(entries),
        'delivered': _report_value(report, 'delivered', 0), 'pending': _report_value(report, 'pending', 0),
        'oldest_pending_seconds': _report_value(report, 'oldest_pending_seconds', None),
        'notes': _notes(_report_value(report, 'notes', ())),
    }
    if adopted:
        summary['adopted'] = adopted
    return summary, exit_code


def _notes(notes) -> list[str]:
    """The reporter's notes (fixed texts with class, episode, issue number, paths), bounded and on one line each.
    They also carry the confirm-not-created command line for the owner (design B.4)."""
    if not isinstance(notes, (list, tuple)):
        return []
    return [' '.join(str(note).split())[:NOTE_MAX_CHARS] for note in notes[:NOTES_MAX]]
