"""src/tim_incident/checkup.py: classes, precedence, network rule, hysteresis, evidence, run() (design part A, section 15).

Everything runs against a fake world: no network, no journal, no systemctl, no git. The reporter is a small fake with
read_controls/deliver; the real one (github.py) is tested in tests/test_tim_incident_github.py.
"""
from __future__ import annotations

import base64
import contextlib
import copy
import errno
import fcntl
import io
import json
import os
import socket
import subprocess
import sys
import types
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import tim_server_health
from src.tim_incident import checkup
from src.tim_incident.policy import (
    LABEL_ALLOWLIST, NOT_CONFIGURED, Controls, load_policy, load_settings, policy_from_dict,
)
from src.tim_incident.redaction import final_scan

UTC = timezone.utc
NOW = datetime(2026, 10, 7, 3, 15, tzinfo=UTC)
POLICY = load_policy()
CONFIG = Path(__file__).resolve().parents[1] / 'config' / 'tim_checkup.json'
OWNER = 'uezeyiraydin-cell'
MIN = timedelta(minutes=1)
RUN = timedelta(minutes=15)

CANDLE_RED = {'status': 'RED', 'age_seconds': 900.0, 'max_age_seconds': 180}
DB_DOWN = {'candle_freshness': {'status': 'RED', 'reason': 'database unavailable (ConnectionRefusedError)'},
           'gap_last_60m': {'status': 'RED', 'reason': 'database unavailable (ConnectionRefusedError)'}}
RUNTIME_RED = {'status': 'RED', 'active': 'failed', 'sub': 'failed'}
WATCHDOG_NAMES = ('runtime_process', 'single_collector', 'dashboard', 'collector_freshness', 'postgres_listener',
                  'data_age', 'queue_age', 'cursor_age', 'gap_incidents', 'disk_space', 'log_growth', 'observe_only',
                  'trading_action_count')
# Synthetic values only; none of them is or was a real credential.
DB_PASSWORD = 'Qm7Lx2Vb9Nc4Zt8Wk1Rp6Hs3Jd5Fg0Ya2Ue7Io4P'
KEY_LINE = 'MIIEpAIBAAKCAQEAu1SU1LfVLPHCozMxH2Mo4lgOEePzNm0tRgeLezV6ffAt0gun'
GHP = 'ghp_' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8'
REAL_DISABLE_CORE_DUMPS = checkup.disable_core_dumps      # the autouse fixture replaces it during runs


def gap_red(first: datetime, missing: int) -> dict:
    listed = [(first + offset * MIN).isoformat() for offset in range(min(missing, 10))]
    return {'status': 'RED', 'missing': missing, 'first_missing': listed, 'expected': 60,
            'window_end': (first + 60 * MIN).isoformat()}


def health_report(at: datetime, **overrides) -> dict:
    checks = {
        'runtime': {'status': 'GREEN', 'active': 'active', 'sub': 'running'},
        'candle_freshness': {'status': 'GREEN', 'age_seconds': 30.0, 'max_age_seconds': 180},
        'gap_last_60m': {'status': 'GREEN', 'missing': 0, 'first_missing': [], 'expected': 60},
        'disk': {'status': 'GREEN', 'path': '/opt/tim', 'used_percent': 41.0},
        'time_sync': {'status': 'GREEN', 'ntp_synchronized': True},
        'backup': {'status': 'GREEN', 'newest': 'tim-20261007T0200Z.dump', 'age_hours': 1.2},
    }
    for name, value in overrides.items():
        checks[name] = copy.deepcopy(value) if isinstance(value, dict) else {'status': value}
    status = 'RED' if any(check['status'] == 'RED' for check in checks.values()) else 'GREEN'
    return {'timestamp': at.isoformat(), 'status': status, 'checks': checks, 'mode': 'OBSERVE', 'trading_actions': 0}


def watchdog_record(at: datetime, **overrides) -> dict:
    checks = {name: {'status': 'GREEN', 'value': 1, 'reason': 'fixture'} for name in WATCHDOG_NAMES}
    checks['observe_only']['value'] = True
    checks['trading_action_count']['value'] = 0
    for name, value in overrides.items():
        checks[name] = copy.deepcopy(value) if isinstance(value, dict) else {'status': value, 'value': None,
                                                                             'reason': 'fixture'}
    status = 'RED' if any(check['status'] == 'RED' for check in checks.values()) else 'GREEN'
    return {'timestamp': at.isoformat(), 'event': 'WATCHDOG_CHECK', 'severity': 'INFO', 'status': status,
            'checks': checks, 'mode': 'OBSERVE', 'trading_actions': checks['trading_action_count']['value']}


def env_for(mode: str, **extra) -> dict:
    env = {'TIM_CHECKUP_REPORTING': mode}
    if mode != 'off':
        env.update(TIM_CHECKUP_APP_ID='12345', TIM_CHECKUP_INSTALLATION_ID='67890', TIM_CHECKUP_AUTHORITY_ISSUE='42',
                   TIM_CHECKUP_REPORTER_LOGIN='tim-reporter[bot]', TIM_CHECKUP_OWNER_LOGIN=OWNER)
    env.update(extra)
    return env


class MemorySpool:
    """Stands in for github.Spool: ordered, JSON only, done entries are kept."""

    def __init__(self):
        self.items, self.done, self.sequence = [], [], 0

    def enqueue(self, entry: dict) -> str:
        entry = json.loads(json.dumps(entry))          # must be JSON-serialisable
        self.sequence += 1
        entry['_id'] = f'{self.sequence:06d}-{entry["kind"]}'
        self.items.append(entry)
        return entry['_id']

    def pending(self) -> list[dict]:
        return [dict(item) for item in self.items]

    def mark_done(self, entry_id: str, note: str = '') -> None:
        for item in list(self.items):
            if item['_id'] == entry_id:
                self.items.remove(item)
                self.done.append((item, note))

    def oldest_pending_seconds(self, now: float):
        return None


class FakeReporter:
    def __init__(self, mode: str = 'on', labels=(), authority: str = 'open', exit_code: int = 0,
                 reporting: str | None = None):
        self.mode, self.labels, self.authority = mode, set(labels), authority
        self.exit_code, self.reporting = exit_code, reporting
        self.delivered, self.deadlines, self.reads = [], [], 0

    def read_controls(self) -> Controls:
        self.reads += 1
        if self.mode == 'off':
            return NOT_CONFIGURED
        return Controls(self.authority, frozenset(self.labels))

    def deliver(self, spool, *, deadline: float):
        self.deadlines.append(deadline)
        pending = spool.pending()
        for entry in pending:
            self.delivered.append({key: value for key, value in entry.items() if key != '_id'})
            spool.mark_done(entry['_id'], note=self.mode)
        return SimpleNamespace(reporting=self.reporting or self.mode, preflight='ok' if self.mode != 'off' else 'skipped',
                               delivered=len(pending), pending=0, oldest_pending_seconds=None,
                               exit_code=self.exit_code)


@dataclass
class Result:
    code: int
    entries: list[dict]
    summary: dict
    lines: list[str]

    def kinds(self) -> list[str]:
        return [entry['kind'] for entry in self.entries]

    def opens(self) -> list[dict]:
        return [entry for entry in self.entries if entry['kind'] == 'open']


def _since(argv: list[str], flag: str) -> datetime:
    return datetime.strptime(argv[argv.index(flag) + 1], '%Y-%m-%d %H:%M:%S UTC').replace(tzinfo=UTC)


class World:
    """A fake tim-core-01: status files, journal, systemctl, TCP probes, statvfs, /proc, controls."""

    def __init__(self, tmp_path: Path, *, reporting: str = 'on', policy=POLICY, labels=()):
        self.root = tmp_path / 'opt-tim'
        self.data = self.root / 'data'
        self.operational = self.data / 'operational'
        self.operational.mkdir(parents=True)
        (self.root / 'config').mkdir()
        (self.root / 'config' / 'core_manifest.json').write_text(
            json.dumps({'status': 'FROZEN', 'operating_mode': 'OBSERVE'}), encoding='utf-8')
        self.proc = tmp_path / 'proc'
        (self.proc / 'pressure').mkdir(parents=True)
        (self.proc / 'meminfo').write_text('MemTotal: 64000000 kB\nMemAvailable: 30000000 kB\n', encoding='utf-8')
        (self.proc / 'loadavg').write_text('0.50 0.40 0.30 1/200 1234\n', encoding='utf-8')
        (self.proc / 'pressure' / 'cpu').write_text('some avg10=0.00 avg60=0.00 avg300=0.00 total=1\n')
        self.policy = policy
        self.now = NOW
        self.health_rules, self.watch_rules = [], []
        self.health_until = None            # the health timer stopped at this time
        self.health_file = True
        self.health_denied = None           # (code, text) of a refused journal
        self.watch_status_age = 0.0
        self.observed = {'dashboard_status': 200, 'dashboard_healthy': True, 'dashboard_observe_only': True,
                         'manifest_observe_only': True}
        self.units: dict[str, dict] = {}
        self.failing: dict = {}
        self.runtime_lines: list[tuple[datetime, str]] = []
        self.evidence_journal: dict[str, str] = {}
        self.qwen_journal: list[str] = []   # tim-qwen-diagnose.service journal; the cursor is the line count
        self.files: dict[str, dict] = {}
        self.disk: dict[str, float] = {}
        self.calls: list[tuple[list[str], float]] = []
        self.probes: list[tuple] = []
        self.collect_calls: list[tuple] = []
        self.collected = None
        self.reporter = FakeReporter(mode=reporting, labels=labels)
        self.env = env_for(reporting)
        self.spool = MemorySpool()
        self.default_collect = False
        self.agent = None                   # /var/lib/tim-agent stand-in (PR-2); None skips the diagnosis part
        self.agent_uid = os.getuid()        # owner tim-agent of results/ in the fake pwd database

    # --- the world -----------------------------------------------------------------------------------------------
    def health(self, start: datetime, end: datetime, **overrides) -> None:
        self.health_rules.append((start, end, overrides))

    def watch(self, start: datetime, end: datetime, **overrides) -> None:
        self.watch_rules.append((start, end, overrides))

    def health_at(self, at: datetime) -> dict:
        merged = {}
        for start, end, overrides in self.health_rules:
            if start <= at <= end:
                merged.update(overrides)
        return health_report(at, **merged)

    def watch_at(self, at: datetime) -> dict:
        merged = {}
        for start, end, overrides in self.watch_rules:
            if start <= at <= end:
                merged.update(overrides)
        return watchdog_record(at, **merged)

    def health_times(self, since: datetime) -> list[datetime]:
        last = self.now if self.health_until is None else min(self.now, self.health_until)
        moment = since.replace(second=0, microsecond=0)
        times = []
        while moment <= last:
            if moment >= since:
                times.append(moment)
            moment += MIN
        return times

    @property
    def settings(self):
        return load_settings(self.env)

    # --- fakes ---------------------------------------------------------------------------------------------------
    def runner(self, argv: list[str], timeout: float) -> tuple[int, str]:
        self.calls.append((list(argv), timeout))
        assert argv[0] in ('journalctl', 'systemctl'), argv
        if argv[0] == 'systemctl':
            assert argv[1] == 'show'
            state = {'LoadState': 'loaded', 'ActiveState': 'active', 'SubState': 'running', 'Result': 'success',
                     'NRestarts': '0', 'ExecMainStatus': '0', **self.units.get(argv[2], {})}
            return 0, ''.join(f'{key}={value}\n' for key, value in state.items())
        unit = argv[argv.index('-u') + 1]
        output = argv[argv.index('-o') + 1]
        if unit == checkup.HEALTH_UNIT and output == 'cat':
            if self.health_denied:
                return self.health_denied
            reports = [json.dumps(self.health_at(at)) for at in self.health_times(_since(argv, '--since'))]
            return 0, 'tim-server-health starting\n' + '\n'.join(reports) + '\n'
        if unit == checkup.QWEN_UNIT and output == 'cat':
            assert '--show-cursor' in argv
            start = int(argv[argv.index('--after-cursor') + 1].split('i=')[1]) if '--after-cursor' in argv else 0
            lines = self.qwen_journal[start:]
            return 0, ''.join(f'{line}\n' for line in lines) + (
                f'-- cursor: s=fake;i={len(self.qwen_journal)}\n' if lines else '')
        if unit == checkup.RUNTIME_UNIT and output == 'cat':
            if self.health_denied:
                return self.health_denied
            since, until = _since(argv, '--since'), _since(argv, '--until')
            return 0, '\n'.join(line for at, line in self.runtime_lines if since <= at <= until)
        assert output == 'short-iso'
        return 0, self.evidence_journal.get(unit, f'2026-10-07T03:10:00+0000 tim-core-01 {unit}: started\n')

    def connect(self, host: str, port: int, timeout: float) -> None:
        self.probes.append((host, port, timeout))
        error = self.failing.get((host, port)) or self.failing.get(host)
        if error is not None:
            raise error

    def statvfs(self, path: str):
        percent = self.disk.get(path, 40.0)
        used = int(10_000 * percent / 100)
        return SimpleNamespace(f_blocks=10_000, f_bfree=10_000 - used, f_bavail=10_000 - used, f_frsize=4096)

    def collect(self, backup_dir: Path, disk_path: Path) -> dict:
        self.collect_calls.append((backup_dir, disk_path))
        return self.collected or self.health_at(self.now)

    def write_files(self) -> None:
        path = self.operational / 'server_health.json'
        if self.health_file:
            times = self.health_times(self.now - timedelta(hours=2))
            if times:
                at = times[-1]
                path.write_text(json.dumps(self.health_at(at)), encoding='utf-8')
                os.utime(path, (at.timestamp(), at.timestamp()))
        elif path.exists():
            path.unlink()
        records, moment = [], self.now - timedelta(minutes=20)
        while moment <= self.now:
            records.append(self.watch_at(moment))
            moment += timedelta(seconds=30)
        (self.operational / 'watchdog.jsonl').write_text(''.join(json.dumps(item) + '\n' for item in records))
        status = {key: value for key, value in records[-1].items() if key not in ('event', 'severity', 'timestamp')}
        stamp = self.now - timedelta(seconds=self.watch_status_age)
        status.update(checked_at=stamp.isoformat(), observed=dict(self.observed))
        status_path = self.operational / 'watchdog_status.json'
        status_path.write_text(json.dumps(status), encoding='utf-8')
        os.utime(status_path, (stamp.timestamp(), stamp.timestamp()))
        for name, data in self.files.items():
            (self.operational / f'{name}.json').write_text(json.dumps(data), encoding='utf-8')

    # --- running -------------------------------------------------------------------------------------------------
    def run(self, *, at: datetime | None = None, reporter=None, settings=None) -> Result:
        if at is not None:
            self.now = at
        self.write_files()
        reporter = reporter or self.reporter
        before = len(getattr(reporter, 'delivered', []))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = checkup.run(
                root=self.root, data_dir=self.data, policy=self.policy, settings=settings or self.settings,
                reporter=reporter, environ=self.env, now=self.now, runner=self.runner, connect=self.connect,
                monotonic=lambda: 1000.0, spool=self.spool,
                health_collect=None if self.default_collect else self.collect, statvfs=self.statvfs,
                proc_dir=self.proc, agent_dir=self.agent,
                user_lookup=lambda name: SimpleNamespace(pw_uid=self.agent_uid) if name == 'tim-agent' else None)
        lines = out.getvalue().splitlines()
        assert len(lines) == 1, lines
        summary = json.loads(lines[0])
        assert summary['event'] == 'checkup_end' and summary['exit_code'] == code
        return Result(code, list(getattr(reporter, 'delivered', []))[before:], summary, lines)

    def next(self, **kwargs) -> Result:
        return self.run(at=self.now + RUN, **kwargs)

    def state(self) -> dict:
        return json.loads((self.data / 'incidents' / 'state.json').read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def _no_prctl(monkeypatch):
    calls = []
    monkeypatch.setattr(checkup, 'disable_core_dumps', lambda: calls.append(True) or True)
    return calls


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def opened_classes(results) -> list[str]:
    return [entry['class'] for result in results for entry in result.opens()]


# --- opening hysteresis --------------------------------------------------------------------------------------------

def test_single_red_blip_opens_nothing(world):
    world.health(NOW - 5 * MIN, NOW - 5 * MIN, candle_freshness=CANDLE_RED)
    first = world.run()
    second = world.next()
    assert first.code == second.code == 0
    assert first.entries == second.entries == []
    assert first.summary['open'] == second.summary['open'] == []
    assert first.summary['blocked_by'] == 'DATA_FLOW'          # seen, below its threshold


def test_three_red_samples_open_one_incident(world):
    world.health(NOW - 2 * MIN, NOW + 3 * RUN, candle_freshness=CANDLE_RED)
    results = [world.run(), world.next(), world.next()]
    assert opened_classes(results) == ['DATA_FLOW']
    first = results[0]
    assert first.kinds() == ['open', 'comment']
    entry = first.opens()[0]
    assert entry['episode'] == '20261007T0315Z' and entry['host'] == 'tim-core-01'
    assert entry['labels'] == ['incident', 'source:tim-checkup', 'priority:p1']
    assert entry['at'] == NOW.isoformat() and entry['active'] is True and entry['adopt_only'] is False
    assert first.entries[1]['tag'] == 'evidence'
    assert results[1].entries == [] and results[2].entries == []      # ONGOING is silent
    assert [item['class'] for item in results[2].summary['open']] == ['DATA_FLOW']


# --- resolving, flapping -------------------------------------------------------------------------------------------

def test_recovery_needs_clean_window_and_two_runs(world):
    world.health(NOW - 2 * MIN, NOW, candle_freshness=CANDLE_RED)
    world.health(NOW + 10 * MIN, NOW + 10 * MIN, candle_freshness=CANDLE_RED)    # a late blip inside the window
    assert opened_classes([world.run()]) == ['DATA_FLOW']
    assert world.next().entries == []           # NOW+15: RED samples still in the 16-min window
    assert world.next().entries == []           # NOW+30: first clean run
    resolved = world.next()                     # NOW+45: second clean run
    assert resolved.kinds() == ['resolve']
    entry = resolved.entries[0]
    assert entry['tag'] == 'resolved' and entry['active'] is False and entry['episode'] == '20261007T0315Z'
    assert 'Dauer: 45 min' in entry['text'] and 'Commit des Checkouts' in entry['text']
    assert resolved.summary['open'] == []
    assert world.next().entries == []


def test_resolve_threshold_doubles_per_reopen(world):
    assert [checkup.resolve_threshold(POLICY, count) for count in range(5)] == [2, 4, 8, 8, 8]
    labels = world.reporter.labels
    labels.add('checkup:selftest')
    assert world.run().kinds() == ['open', 'comment']
    resolves = []
    for expected_runs, reopen in ((2, None), (4, 'reopen-1'), (8, 'reopen-2'), (8, 'reopen-3')):
        if reopen:
            labels.add('checkup:selftest')
            again = world.next()
            assert again.kinds() == ['reopen'] and again.entries[0]['tag'] == reopen
        labels.discard('checkup:selftest')
        quiet = [world.next() for _ in range(expected_runs - 1)]
        assert all(result.entries == [] for result in quiet)
        done = world.next()
        assert done.kinds() == ['resolve']
        resolves.append(done.entries[0]['tag'])
    assert resolves == ['resolved', 'resolved-1', 'resolved-2', 'resolved-3']


def test_flap_within_cooldown_reopens_same_episode(world):
    world.health(NOW - 2 * MIN, NOW, candle_freshness=CANDLE_RED)
    first = world.run()
    episode = first.opens()[0]['episode']
    world.next()
    world.next()
    assert world.next().kinds() == ['resolve']                        # NOW+45
    world.health(NOW + 58 * MIN, NOW + 4 * RUN, candle_freshness=CANDLE_RED)
    again = world.next()                                               # NOW+60, within 2 h
    assert again.kinds() == ['reopen']
    assert again.entries[0]['episode'] == episode and again.entries[0]['tag'] == 'reopen-1'
    assert 'Neue Auflöseschwelle: 4 saubere Läufe' in again.entries[0]['text']
    assert again.summary['open'][0]['episode'] == episode


def test_after_cooldown_new_episode(world):
    world.health(NOW - 2 * MIN, NOW, candle_freshness=CANDLE_RED)
    first = world.run()
    world.next()
    world.next()
    assert world.next().kinds() == ['resolve']                        # resolved at NOW+45
    later = NOW + 45 * MIN + timedelta(hours=2, minutes=15)
    world.health(later - 2 * MIN, later, candle_freshness=CANDLE_RED)
    second = world.run(at=later)
    assert second.kinds() == ['open', 'comment']
    assert second.opens()[0]['episode'] == checkup.episode_id(later) != first.opens()[0]['episode']


# --- precedence ----------------------------------------------------------------------------------------------------

def test_db_down_one_issue(world):
    world.health(NOW - 20 * MIN, NOW + 3 * RUN, **DB_DOWN)
    world.watch(NOW - 20 * MIN, NOW + 3 * RUN, postgres_listener='RED', data_age='RED', cursor_age='RED',
                collector_freshness='RED', trading_action_count={'status': 'RED', 'value': None, 'reason': 'db'})
    results = [world.run(), world.next(), world.next()]
    assert opened_classes(results) == ['DATABASE']
    entry = results[0].opens()[0]
    assert entry['labels'] == ['incident', 'source:tim-checkup', 'priority:p1']
    body = entry['body']
    assert '- Erkannt: 2026-10-07 03:15 UTC (Checkup); fehlschlagende Prüfungen: database' in body
    subs = next(line for line in body.splitlines() if line.startswith('- Unterbefunde:'))
    assert 'watchdog.postgres_listener' in subs and 'watchdog.trading_action_count' in subs
    assert 'candle_freshness' not in subs                              # a consequence, mapped to database


def test_runtime_down_one_issue(world):
    world.health(NOW - 20 * MIN, NOW + 3 * RUN, runtime=RUNTIME_RED, candle_freshness=CANDLE_RED)
    world.watch(NOW - 20 * MIN, NOW + 3 * RUN, runtime_process='RED', single_collector='RED', dashboard='RED',
                collector_freshness='RED', data_age='RED',
                observe_only={'status': 'RED', 'value': False, 'reason': 'dashboard down'})
    world.observed.update(dashboard_status='UNAVAILABLE', dashboard_healthy=False, dashboard_observe_only=False)
    world.units[checkup.RUNTIME_UNIT] = {'ActiveState': 'failed', 'SubState': 'failed', 'Result': 'exit-code'}
    results = [world.run(), world.next(), world.next()]
    assert opened_classes(results) == ['RUNTIME']            # no SAFETY: the dashboard was down, not answering "no"
    body = results[0].opens()[0]['body']
    assert 'fehlschlagende Prüfungen: runtime, runtime_unit' in body
    subs = next(line for line in body.splitlines() if line.startswith('- Unterbefunde:'))
    for name in ('candle_freshness', 'watchdog.single_collector', 'watchdog.observe_only'):
        assert name in subs


def test_network_outage_no_watchdog_issue(world):
    down = OSError(errno.ENETUNREACH, 'unreachable')
    world.failing = {'stream.binance.com': down, 'api.binance.com': down, 'api.github.com': down}
    world.health(NOW - 20 * MIN, NOW + 4 * RUN, candle_freshness=CANDLE_RED)
    world.watch(NOW - 20 * MIN, NOW + 4 * RUN, queue_age='RED', data_age='RED', collector_freshness='RED')
    first = world.run()
    assert first.entries == [] and first.summary['blocked_by'] == 'NETWORK'     # probes failed once: wait
    results = [first, world.next(), world.next(), world.next()]
    assert opened_classes(results) == ['NETWORK']
    entry = results[1].opens()[0]
    assert entry['labels'] == ['incident', 'source:tim-checkup', 'incident:network']     # no priority
    assert 'fehlschlagende Prüfungen: net_probe (api.binance.com:443, stream.binance.com:9443)' in entry['body']
    subs = next(line for line in entry['body'].splitlines() if line.startswith('- Unterbefunde:'))
    assert 'watchdog.queue_age' in subs and 'candle_freshness' in subs


def test_watchdog_restart_cycle_opens_nothing(world):
    # stale data for 3 watchdog cycles, a controlled restart, the collector gone for two samples, then GREEN
    world.watch(NOW - 6 * MIN, NOW - 5 * MIN, data_age='RED', collector_freshness='RED', cursor_age='RED')
    world.watch(NOW - 4 * MIN, NOW - 4 * MIN + timedelta(seconds=30), runtime_process='RED', single_collector='RED',
                dashboard='RED')
    world.health(NOW - 4 * MIN, NOW - 4 * MIN, runtime={'status': 'AMBER', 'active': 'activating',
                                                         'sub': 'start'})
    world.health(NOW - 3 * MIN, NOW - 3 * MIN, runtime=RUNTIME_RED)
    world.files['watchdog_recovery_state'] = {'consecutive_restartable_red': 0,
                                              'last_restart_attempt_at': (NOW - 4 * MIN).isoformat()}
    results = [world.run(), world.next()]
    assert [result.entries for result in results] == [[], []]
    assert all(result.summary['open'] == [] for result in results)


# --- network rule --------------------------------------------------------------------------------------------------

def test_short_blip_seen_after_recovery_is_network(world):
    first = NOW - 30 * MIN
    world.health(NOW - 20 * MIN, NOW + 2 * RUN, gap_last_60m=gap_red(first, 5))     # candles fresh again
    world.runtime_lines = [(first - MIN, 'INFO stream connected'), (first + 7 * MIN, 'INFO catch-up done')]
    result = world.run()
    assert opened_classes([result]) == ['NETWORK']
    body = result.opens()[0]['body']
    assert 'fehlschlagende Prüfungen: past_gap' in body and 'gap_last_60m' in body
    runtime = [argv for argv, _ in world.calls if checkup.RUNTIME_UNIT in argv and '--until' in argv]
    assert runtime and _since(runtime[0], '--since') == first - 5 * MIN
    assert _since(runtime[0], '--until') == first + 10 * MIN                       # gap end + 5 min
    assert opened_classes([world.next()]) == []


def test_foreign_traceback_keeps_data_flow(world):
    first = NOW - 30 * MIN
    world.health(NOW - 20 * MIN, NOW, gap_last_60m=gap_red(first, 5))
    world.runtime_lines = [(first, 'Traceback (most recent call last):'), (first, '  File "x.py", line 1'),
                           (first, 'ValueError: bad candle')]
    assert opened_classes([world.run()]) == ['DATA_FLOW']


def test_port_9443_unreachable_is_network(world):
    world.failing = {('stream.binance.com', 9443): TimeoutError()}
    world.health(NOW - 20 * MIN, NOW + 2 * RUN, candle_freshness=CANDLE_RED)
    first, second = world.run(), world.next()
    assert first.entries == [] and opened_classes([second]) == ['NETWORK']
    assert 'net_probe (stream.binance.com:9443)' in second.opens()[0]['body']
    probes = [(host, port) for host, port, timeout in world.probes[:3]]
    assert probes == [('stream.binance.com', 9443), ('api.binance.com', 443), ('api.github.com', 443)]
    assert all(timeout == 5.0 for *_, timeout in world.probes)


def test_github_probe_alone_is_not_an_outage(world):
    world.failing = {'api.github.com': socket.gaierror('dns')}
    assert [world.run().entries, world.next().entries] == [[], []]
    assert world.state()['probes'][-1]['results'][2] == {'host': 'api.github.com', 'port': 443, 'ok': False,
                                                         'error': 'dns', 'ms': 0}


def test_gap_below_min_minutes_no_issue(world):
    first = NOW - 20 * MIN
    world.health(NOW - 20 * MIN, NOW + 2 * RUN, gap_last_60m=gap_red(first, 2))
    world.runtime_lines = [(first + timedelta(seconds=30),
                            'Binance public stream disconnected (timeout); retrying in 5s')]
    results = [world.run(), world.next()]
    assert [result.entries for result in results] == [[], []]
    assert [result.summary['open'] for result in results] == [[], []]
    minor = (world.data / 'incidents' / 'minor.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(minor) == 1                                             # logged once per gap
    item = json.loads(minor[0])
    assert item['class'] == 'NETWORK' and item['missing'] == 2 and item['rules'] == ['net_pattern', 'past_gap']
    assert results[0].summary['minor'] == 1 and results[1].summary['minor'] == 0


def test_minor_gap_aging_out_does_not_open_data_flow(world):
    # The gap leaves the 60-min window; the last RED samples still lie in the 16-min window.
    first = NOW - 70 * MIN
    world.health(NOW - 20 * MIN, NOW - 3 * MIN, gap_last_60m=gap_red(first, 2))
    world.runtime_lines = [(first, 'OSError: [Errno 101] Network is unreachable')]
    assert world.run().entries == []


# --- SAFETY --------------------------------------------------------------------------------------------------------

def test_safety_unknown_is_subfinding_definite_opens(tmp_path):
    unknown = World(tmp_path / 'unknown')
    unknown.health(NOW - 20 * MIN, NOW, **DB_DOWN)
    unknown.watch(NOW - 20 * MIN, NOW, trading_action_count={'status': 'RED', 'value': None, 'reason': 'db'},
                  observe_only={'status': 'RED', 'value': False, 'reason': 'dashboard down'})
    unknown.observed.update(dashboard_status='UNAVAILABLE', dashboard_observe_only=False)
    result = unknown.run()
    assert opened_classes([result]) == ['DATABASE']
    subs = next(line for line in result.opens()[0]['body'].splitlines() if line.startswith('- Unterbefunde:'))
    assert 'watchdog.observe_only' in subs and 'watchdog.trading_action_count' in subs

    said_no = World(tmp_path / 'said-no')
    said_no.watch(NOW - MIN, NOW, observe_only={'status': 'RED', 'value': False, 'reason': 'not OBSERVE'})
    said_no.observed.update(dashboard_status=200, dashboard_observe_only=False)
    result = said_no.run()
    assert opened_classes([result]) == ['SAFETY']                      # at once, one sample
    entry = result.opens()[0]
    assert entry['labels'] == ['incident', 'source:tim-checkup', 'priority:p1', 'incident:safety']
    assert 'über priority:p0 entscheidet der Inhaber' in entry['body']

    traded = World(tmp_path / 'traded')
    traded.watch(NOW - MIN, NOW - MIN, trading_action_count={'status': 'RED', 'value': 2, 'reason': 'x'})
    assert opened_classes([traded.run()]) == ['SAFETY']

    stale = World(tmp_path / 'stale')
    stale.watch(NOW - 30 * MIN, NOW, observe_only={'status': 'RED', 'value': False, 'reason': 'not OBSERVE'})
    stale.observed.update(dashboard_status=200, dashboard_observe_only=False)
    stale.watch_status_age = 600                                       # the watchdog stopped writing
    assert opened_classes([stale.run()]) == []


# --- health file, journal ------------------------------------------------------------------------------------------

def test_stale_health_uses_collect_without_writing(world, monkeypatch):
    calls = []

    def fake_collect(backup_dir, disk_path):
        calls.append((backup_dir, disk_path))
        return health_report(world.now, candle_freshness=CANDLE_RED)

    def fake_main(*args, **kwargs):
        raise AssertionError('main() writes the shared .json.tmp and must never run')

    monkeypatch.setattr(tim_server_health, 'collect', fake_collect)
    monkeypatch.setattr(tim_server_health, 'main', fake_main)
    world.default_collect = True
    world.health_until = NOW - 20 * MIN                                 # the health timer stopped
    world.units['tim-server-health.timer'] = {'ActiveState': 'inactive', 'SubState': 'dead'}
    world.write_files()
    health_file = world.operational / 'server_health.json'
    before = (health_file.read_bytes(), health_file.stat().st_mtime)
    first = world.run()
    assert calls == [(Path('/var/backups/tim'), world.root)]
    assert (health_file.read_bytes(), health_file.stat().st_mtime) == before
    assert not list(world.operational.glob('*.tmp')) and not list(world.operational.glob('.*tmp'))
    assert opened_classes([first]) == ['HEALTH_STALE'] and first.summary['health'] == 'stale'
    entry = first.opens()[0]
    assert entry['labels'] == ['incident', 'source:tim-checkup', 'priority:p1', 'incident:unknown']
    assert 'health_file (server_health.json, tim-server-health.timer)' in entry['body']
    second = world.next()
    assert opened_classes([second]) == []                               # no UNIT issue for the health timer
    assert [item['class'] for item in second.summary['open']] == ['HEALTH_STALE']


@pytest.mark.parametrize('refusal', [
    (0, 'Hint: You are currently not seeing messages from other users and the system.\n'
        "      Users in groups 'adm', 'systemd-journal' can see all messages.\n"),
    (1, 'No journal files were opened due to insufficient permissions.\n'),
])
def test_journal_denied_exit3_and_run_fallback(world, refusal):
    world.health_denied = refusal
    world.health(NOW - 60 * MIN, NOW + 3 * RUN, candle_freshness=CANDLE_RED)
    results = [world.run(), world.next(), world.next()]
    assert [result.code for result in results] == [3, 3, 3]
    assert all(result.summary['journal_access'] == 'denied' for result in results)
    # the window has one sample per run; RED in three checkup runs in a row stands in for three samples
    assert [result.entries for result in results[:2]] == [[], []]
    assert opened_classes(results) == ['DATA_FLOW']
    assert world.state()['red_runs']['DATA_FLOW'] == 3


# --- evidence, commit ----------------------------------------------------------------------------------------------

def test_evidence_commands_fixed_argv_with_timeouts(world):
    world.health(NOW - 2 * MIN, NOW, candle_freshness=CANDLE_RED)
    world.run()
    assert world.calls
    for argv, timeout in world.calls:
        assert argv[0] in checkup.ALLOWED_COMMANDS and all(isinstance(part, str) for part in argv)
        assert 0 < timeout <= POLICY.limits.command_timeout_seconds
        assert 'git' not in argv and not any(';' in part or '|' in part or '$' in part for part in argv)
    journals = [argv for argv, _ in world.calls if 'short-iso' in argv]
    assert journals == [
        ['journalctl', '-u', unit, '--since', '2026-10-07 02:45:00 UTC', '-n', '80', '-o', 'short-iso', '--no-pager']
        for unit in ('tim-runtime.service', 'tim-candle-finalizer.service')]
    shows = [argv for argv, _ in world.calls if argv[0] == 'systemctl']
    assert ['systemctl', 'show', 'tim-runtime.service',
            '--property=LoadState,ActiveState,SubState,Result,NRestarts,ExecMainStatus', '--no-pager'] in shows
    assert ['journalctl', '-u', 'tim-server-health.service', '--since', '2026-10-07 02:59:00 UTC', '-o', 'cat',
            '--no-pager'] in [argv for argv, _ in world.calls]


def test_default_runner_fixed_env_timeout_and_allowlist(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return SimpleNamespace(returncode=0, stdout=b'ActiveState=active\n')

    monkeypatch.setattr(subprocess, 'run', fake_run)
    assert checkup.default_runner(['systemctl', 'show', 'x.service'], 7.0) == (0, 'ActiveState=active\n')
    assert seen['argv'] == ['systemctl', 'show', 'x.service'] and seen['timeout'] == 7.0
    assert seen['env'] == {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}
    assert 'shell' not in seen and seen['stdin'] == subprocess.DEVNULL and seen['stderr'] == subprocess.STDOUT
    for argv in (['git', 'rev-parse', 'HEAD'], ['sh', '-c', 'journalctl'], [], 'journalctl -u x'):
        with pytest.raises(ValueError):
            checkup.default_runner(argv, 1.0)

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs['timeout'])

    monkeypatch.setattr(subprocess, 'run', timeout)
    assert checkup.default_runner(['journalctl', '-u', 'x'], 1.0) == (124, '')
    monkeypatch.setattr(subprocess, 'run', lambda argv, **kwargs: (_ for _ in ()).throw(FileNotFoundError()))
    assert checkup.default_runner(['journalctl', '-u', 'x'], 1.0) == (127, '')


def test_commit_read_without_git(tmp_path, monkeypatch, world):
    def forbidden(*args, **kwargs):
        raise AssertionError('no subprocess may run while reading the commit')

    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    sha = '0123456789abcdef0123456789abcdef01234567'
    other = 'fedcba9876543210fedcba9876543210fedcba98'

    detached = tmp_path / 'detached'
    (detached / '.git').mkdir(parents=True)
    (detached / '.git' / 'HEAD').write_text(sha + '\n')
    assert checkup.read_commit(detached) == {'sha': sha, 'ref': None, 'detached': True, 'error': None}

    loose = tmp_path / 'loose'
    (loose / '.git' / 'refs' / 'heads').mkdir(parents=True)
    (loose / '.git' / 'HEAD').write_text('ref: refs/heads/platform-main\n')
    (loose / '.git' / 'refs' / 'heads' / 'platform-main').write_text(other + '\n')
    assert checkup.read_commit(loose)['sha'] == other

    packed = tmp_path / 'packed'
    (packed / '.git').mkdir(parents=True)
    (packed / '.git' / 'HEAD').write_text('ref: refs/heads/main\n')
    (packed / '.git' / 'packed-refs').write_text(
        f'# pack-refs with: peeled fully-peeled sorted\n{other} refs/heads/feature\n{sha} refs/heads/main\n^{other}\n')
    assert checkup.read_commit(packed) == {'sha': sha, 'ref': 'refs/heads/main', 'detached': False, 'error': None}

    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    (worktree / '.git').write_text(f'gitdir: {loose / ".git"}\n')
    assert checkup.read_commit(worktree)['sha'] == other

    hostile = tmp_path / 'hostile'
    (hostile / '.git').mkdir(parents=True)
    (hostile / '.git' / 'HEAD').write_text('ref: refs/../../../etc/passwd\n')
    assert checkup.read_commit(hostile)['error'] == 'invalid ref'
    assert checkup.read_commit(tmp_path / 'missing')['error'] == 'unreadable'

    (world.root / '.git').mkdir()
    (world.root / '.git' / 'HEAD').write_text(sha + '\n')
    world.health(NOW - 2 * MIN, NOW, candle_freshness=CANDLE_RED)
    result = world.run()
    assert '- Commit des Checkouts: 0123456789ab (aus .git gelesen)' in result.opens()[0]['body']
    assert sha in result.entries[1]['text']                            # full SHA in the evidence (exempt from scan)
    assert [entry['commit'] for entry in result.entries] == [sha[:12], sha[:12]]
    assert not any(argv[0] == 'git' or 'git' in argv for argv, _ in world.calls)


def test_evidence_redacts_literals_and_respects_limit(tmp_path):
    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    data['limits']['evidence_comment_bytes'] = 6000
    world = World(tmp_path, policy=policy_from_dict(data))
    secret = tmp_path / 'database-password'
    secret.write_text(DB_PASSWORD + '\n')
    credentials = tmp_path / 'credentials'
    credentials.mkdir()
    (credentials / 'github-app-key').write_text(f'-----BEGIN RSA PRIVATE KEY-----\n{KEY_LINE}\n'
                                                '-----END RSA PRIVATE KEY-----\n')
    world.env.update(TIM_DATABASE_SECRET_FILE=str(secret), CREDENTIALS_DIRECTORY=str(credentials))
    noise = '\n'.join(f'2026-10-07T03:{index % 60:02d}:00+0000 tim-core-01 python[7]: candle {index} closed'
                      for index in range(400))
    # journalctl prints no blank lines; here they split the output into blocks so each secret form is checked alone
    world.evidence_journal['tim-runtime.service'] = (
        f'{noise}\n\n2026-10-07T03:00:00+0000 tim-core-01 python[7]: connect postgresql://tim:{DB_PASSWORD}@db/tim\n'
        f'\n2026-10-07T03:00:01+0000 tim-core-01 python[7]: retry with '
        f'{base64.b64encode(DB_PASSWORD.encode()).decode()}\n'
        f'\n2026-10-07T03:00:02+0000 tim-core-01 python[7]: token {GHP} and key {KEY_LINE}\n'
        f'\n2026-10-07T03:00:03+0000 tim-core-01 python[7]: token {GHP}\n')
    world.evidence_journal['tim-candle-finalizer.service'] = noise + '\n@someone see #12 <!-- TIM_INCIDENT_V1 -->\n'
    world.health(NOW - 2 * MIN, NOW, candle_freshness=CANDLE_RED)
    result = world.run()
    evidence = result.entries[1]['text']
    assert len(evidence.encode('utf-8')) <= 6000
    for text in (DB_PASSWORD, base64.b64encode(DB_PASSWORD.encode()).decode(), GHP, KEY_LINE, 'TIM_INCIDENT_V1',
                 '@someone', '#12'):
        assert text not in evidence
    assert evidence.count('[BLOCK ENTFERNT: bekanntes Geheimnis]') == 3 and 'token [REDACTED]' in evidence
    assert '[Evidenz gekürzt' in evidence or '[... gekürzt]' in evidence
    assert not final_scan(evidence)
    stored = world.data / 'incidents' / 'evidence' / '20261007T0315Z' / 'DATA_FLOW-evidence.md'
    assert stored.read_text(encoding='utf-8') == evidence and stored.stat().st_mode & 0o777 == 0o600


def test_entries_are_json_and_fixed_texts_pass_final_scan(world):
    world.health(NOW - 2 * MIN, NOW + RUN, candle_freshness=CANDLE_RED)
    result = world.run()
    entry, comment = result.entries
    assert set(entry) == {'v', 'kind', 'episode', 'class', 'host', 'at', 'active', 'title', 'body', 'labels',
                          'adopt_only', 'mode'}
    assert set(comment) == {'v', 'kind', 'episode', 'class', 'host', 'at', 'active', 'tag', 'text', 'mode'}
    assert entry['mode'] == comment['mode'] == 'on'
    assert entry['title'] == 'Vorfall DATA_FLOW auf tim-core-01 seit 2026-10-07 03:15 UTC'
    lines = entry['body'].splitlines()
    assert lines[0] == '## Vorfall DATA_FLOW auf tim-core-01' and lines[1] == f'cc @{OWNER}'
    assert lines[-1] == '<!-- TIM_INCIDENT_V1 class=DATA_FLOW episode=20261007T0315Z host=tim-core-01 -->'
    assert '- Einordnung (feste Regel): ops' in lines
    assert any(line.startswith('- Behebung: Datenfluss der Runtime prüfen') and 'siehe docs/TIM_CHECKUP.md' in line
               for line in lines)
    assert '- Evidenz steht nur in Kommentaren.' in lines                 # diagnosis is PR-2
    assert 'TIM_TASK_FINGERPRINT' not in entry['body'] and 'TIM_INCIDENT_STATUS' not in entry['body']
    assert set(entry['labels']) <= LABEL_ALLOWLIST
    for text in (entry['title'], entry['body'], comment['text']):
        assert not final_scan(text)


def test_reporter_literals_reach_evidence_and_default_spool(world, monkeypatch):
    token = 'Zq8Tn3Lp0Wv5Rb7Xc2Md9Kf4Hs6Jy1'                            # synthetic; matches no pattern on its own
    made = []

    class Minting(FakeReporter):
        literals = ()

        def read_controls(self):
            self.literals = (token,)                                     # minted on the first read, like github.py
            return super().read_controls()

    class RecordingSpool(MemorySpool):
        def __init__(self, directory, *, literals=(), coalesce_after=500, clock=None):
            super().__init__()
            made.append((Path(directory), tuple(literals), coalesce_after, clock()))

    fake = types.ModuleType('src.tim_incident.github')                  # github.py itself is never imported here
    fake.Spool = RecordingSpool
    monkeypatch.setitem(sys.modules, 'src.tim_incident.github', fake)
    world.spool = None
    world.evidence_journal['tim-runtime.service'] = f'2026-10-07T03:00:00+0000 tim-core-01 python[7]: header {token}\n'
    world.health(NOW - 2 * MIN, NOW, candle_freshness=CANDLE_RED)
    result = world.run(reporter=Minting('on'))
    evidence = result.entries[1]['text']
    assert token not in evidence and '[BLOCK ENTFERNT: bekanntes Geheimnis]' in evidence
    assert made == [(world.data / 'incidents' / 'outbox', (token,), POLICY.limits.spool_coalesce_after,
                     NOW.timestamp())]                            # queued_at on the run's clock


def test_status_lines_fit_the_reporter_limit(world, monkeypatch):
    monkeypatch.setattr(checkup, '_failing_text', lambda evaluation, name: ', '.join(f'check_{n}' for n in range(200)))
    world.health(NOW - 2 * MIN, NOW + timedelta(hours=30), candle_freshness=CANDLE_RED)
    assert world.run().kinds() == ['open', 'comment']
    status = world.run(at=NOW + timedelta(hours=24, minutes=15))
    assert status.kinds() == ['status_line']
    line = status.entries[0]['status']
    assert len(line) <= checkup.STATUS_MAX_CHARS < 300 and '\n' not in line and line.endswith(' ...')
    assert not final_scan(line)

# --- hysteresis details --------------------------------------------------------------------------------------------

def test_changed_comments_capped_per_episode(world):
    units = POLICY.classes['UNIT'].units
    world.units[units[0]] = {'ActiveState': 'failed'}
    assert world.run().entries == []                                  # UNIT needs two runs in a row
    assert world.next().kinds() == ['open', 'comment']
    tags = []
    for unit in units[1:5]:
        world.units[unit] = {'ActiveState': 'inactive'}
        result = world.next()
        tags.append([(entry['kind'], entry.get('tag')) for entry in result.entries])
    assert tags == [[('comment', 'changed-1')], [('comment', 'changed-2')], [('comment', 'changed-3')],
                    [('status_line', None)]]
    status = world.reporter.delivered[-1]['status']
    assert 'Kommentargrenze erreicht' in status and not final_scan(status)
    assert world.next().entries == []                                 # unchanged: silent


def test_class_change_comment_and_status_line_once_a_day(world):
    world.health(NOW - 2 * MIN, NOW + timedelta(hours=30), candle_freshness=CANDLE_RED)
    assert opened_classes([world.run()]) == ['DATA_FLOW']
    world.health(NOW + 13 * MIN, NOW + 15 * MIN, runtime=RUNTIME_RED)
    changed = world.next()
    assert changed.kinds() == ['comment'] and changed.entries[0]['tag'] == 'changed-1'
    assert '- Neue Klasse: RUNTIME (vorher DATA_FLOW)' in changed.entries[0]['text']
    assert world.run(at=NOW + timedelta(hours=12)).entries == []
    assert world.run(at=NOW + timedelta(hours=23, minutes=50)).entries == []
    status = world.run(at=NOW + timedelta(hours=24, minutes=15))
    assert status.kinds() == ['status_line']
    assert status.entries[0]['status'].startswith('Stand 2026-10-08 03:30 UTC: weiterhin aktiv; Klasse DATA_FLOW')
    assert world.next().entries == []


def test_selftest_label_opens_once_and_resolves_once(world):
    world.reporter.labels.add('checkup:selftest')
    results = [world.run(), world.next(), world.next(), world.next()]
    assert opened_classes(results) == ['SELFTEST']
    entry = results[0].opens()[0]
    assert entry['labels'] == ['incident', 'source:tim-checkup', 'selftest']
    world.reporter.labels.clear()
    after = [world.next(), world.next(), world.next(), world.next()]
    assert [result.kinds() for result in after] == [[], ['resolve'], [], []]


def test_reporting_off_then_on_announces_with_original_time(tmp_path):
    world = World(tmp_path, reporting='off')
    world.health(NOW - 2 * MIN, NOW + 3 * RUN, candle_freshness=CANDLE_RED)
    off = world.run()
    assert off.code == 0 and off.entries == [] and world.spool.done == []
    assert off.summary['reporting'] == 'off' and off.summary['authority'] == 'not_configured'
    assert off.summary['open'] == [{'class': 'DATA_FLOW', 'episode': '20261007T0315Z', 'current': 'DATA_FLOW',
                                    'announced': None}]
    world.env = env_for('on')
    world.reporter = FakeReporter('on')
    on = world.next()
    assert on.kinds() == ['open', 'comment']
    assert on.entries[0]['at'] == NOW.isoformat() and on.entries[0]['episode'] == '20261007T0315Z'
    assert '- Erkannt: 2026-10-07 03:15 UTC' in on.entries[0]['body']
    assert world.next().entries == []


def test_dry_run_entries_then_on_creates_once(tmp_path):
    world = World(tmp_path, reporting='dry-run')
    world.health(NOW - 2 * MIN, NOW + 3 * RUN, candle_freshness=CANDLE_RED)
    dry = world.run()
    assert dry.kinds() == ['open', 'comment'] and world.spool.done[0][1] == 'dry-run'
    assert world.next().entries == []
    world.env = env_for('on')
    world.reporter = FakeReporter('on')
    assert world.next().kinds() == ['open', 'comment']
    assert world.next().entries == []


# --- state ---------------------------------------------------------------------------------------------------------

def test_lost_state_adopts_open_incident(world):
    world.health(NOW - 2 * MIN, NOW + 4 * RUN, candle_freshness=CANDLE_RED)
    first = world.run()
    assert first.summary['state'] == 'new' and first.opens()[0]['adopt_only'] is False
    incidents = world.data / 'incidents'
    (incidents / 'state.json').unlink()
    (incidents / 'state.json.prev').unlink(missing_ok=True)
    lost = world.next()
    assert lost.summary['state'] == 'lost'
    assert lost.kinds() == ['open', 'comment'] and lost.opens()[0]['adopt_only'] is True
    assert world.next().entries == [] and world.state()['state_lost_at'] == lost.summary['started_at']
    # a corrupt state.json falls back to the copy: nothing is announced again
    (incidents / 'state.json').write_text('{broken', encoding='utf-8')
    recovered = world.next()
    assert recovered.summary['state'] == 'prev' and recovered.entries == []


def test_state_written_atomically_with_prev_copy(world):
    world.health(NOW - 2 * MIN, NOW + 2 * RUN, candle_freshness=CANDLE_RED)
    world.run()
    first = world.state()
    world.next()
    incidents = world.data / 'incidents'
    assert json.loads((incidents / 'state.json.prev').read_text(encoding='utf-8')) == first
    for name in ('state.json', 'state.json.prev', 'checkup_last_run.json'):
        assert (incidents / name).stat().st_mode & 0o777 == 0o600
    assert not [path.name for path in incidents.iterdir() if path.name.endswith('.tmp')]
    loaded, status = checkup.load_state(world.data)
    assert status == 'ok' and loaded['chain']['episode'] == '20261007T0315Z'
    assert checkup.load_state(world.data / 'nothing', previous_run=False)[1] == 'new'


# --- run -----------------------------------------------------------------------------------------------------------

def test_last_run_written_at_start_and_end(world):
    seen = {}

    class Watching(FakeReporter):
        def read_controls(self):
            seen.update(json.loads((world.data / 'incidents' / 'checkup_last_run.json').read_text(encoding='utf-8')))
            return super().read_controls()

    result = world.run(reporter=Watching('on'))
    assert seen['phase'] == 'started' and seen['started_at'] == NOW.isoformat() and seen['host'] == 'tim-core-01'
    last = json.loads((world.data / 'incidents' / 'checkup_last_run.json').read_text(encoding='utf-8'))
    assert last['phase'] == 'finished' and last['exit_code'] == 0 == result.code
    assert last['started_at'] == NOW.isoformat() and last['finished_at'] == NOW.isoformat()

    class Broken(FakeReporter):
        def deliver(self, spool, *, deadline):
            raise RuntimeError('boom')

    broken = world.next(reporter=Broken('on'))
    assert broken.code == 1 and broken.summary['error'] == 'RuntimeError'
    last = json.loads((world.data / 'incidents' / 'checkup_last_run.json').read_text(encoding='utf-8'))
    assert last['phase'] == 'finished' and last['exit_code'] == 1


def test_checkup_end_line_and_deadline(world, _no_prctl):
    world.health(NOW - 2 * MIN, NOW, candle_freshness=CANDLE_RED)
    result = world.run()
    assert '"event": "checkup_end"' in result.lines[0]
    for key in ('reporting', 'preflight', 'journal_access', 'open', 'authority', 'settings', 'state', 'transitions'):
        assert key in result.summary
    assert result.summary['reporting'] == 'on' and result.summary['preflight'] == 'ok'
    assert result.summary['journal_access'] == 'ok' and result.summary['settings'] == 'ok'
    assert result.summary['transitions'] == ['opened:DATA_FLOW:20261007T0315Z']
    assert world.reporter.deadlines == [1000.0 + 240]                  # monotonic, as Reporter.deliver expects
    assert world.reporter.reads == 1                                    # one GET of the authority issue per run
    assert _no_prctl == [True]


def test_exit_codes(tmp_path):
    quiet = World(tmp_path / 'ok')
    assert quiet.run().code == 0
    disturbed = World(tmp_path / 'disturbed')
    disturbed.reporter.exit_code = 3
    assert disturbed.run().code == 3
    revoked = World(tmp_path / 'revoked')
    revoked.reporter = FakeReporter('on', authority='closed', reporting='revoked')
    result = revoked.run()
    assert result.code == 0 and result.summary['reporting'] == 'revoked' and result.summary['authority'] == 'closed'
    incomplete = World(tmp_path / 'incomplete')
    incomplete.env = {'TIM_CHECKUP_REPORTING': 'on'}                     # requested on, values missing
    incomplete.reporter = FakeReporter('off')
    incomplete.health(NOW - 2 * MIN, NOW, candle_freshness=CANDLE_RED)
    result = incomplete.run()
    assert result.code == 3 and result.entries == [] and 'TIM_CHECKUP_APP_ID missing' in result.summary['settings']


def test_lock_held_skips_run(world):
    incidents = world.data / 'incidents'
    incidents.mkdir(parents=True)
    with open(incidents / 'checkup.lock', 'a+') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        world.write_files()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = checkup.run(root=world.root, data_dir=world.data, policy=POLICY, settings=world.settings,
                               reporter=world.reporter, environ=world.env, now=NOW, runner=world.runner,
                               connect=world.connect, spool=world.spool, health_collect=world.collect,
                               statvfs=world.statvfs, proc_dir=world.proc)
    assert code == 0 and json.loads(out.getvalue())['skipped'] == 'locked'
    assert not (incidents / 'state.json').exists() and world.calls == [] and world.reporter.reads == 0


def test_disable_core_dumps_uses_prctl():
    calls = []

    class Libc:
        def prctl(self, *args):
            calls.append(args)
            return 0

    class Refusing:
        def prctl(self, *args):
            raise OSError('not permitted')

    assert REAL_DISABLE_CORE_DUMPS(Libc()) is True and calls == [(4, 0, 0, 0, 0)]
    assert REAL_DISABLE_CORE_DUMPS(Refusing()) is False


def test_runtime_net_signals_traceback_blocks():
    network = POLICY.network
    clean = checkup.runtime_net_signals(['Traceback (most recent call last):', '  File "a.py", line 3',
                                         'ConnectionResetError: [Errno 104] reset by peer'], network)
    assert clean == {'net_pattern': True, 'foreign_traceback': False,
                     'pattern_lines': ['ConnectionResetError: [Errno 104] reset by peer']}
    mixed = checkup.runtime_net_signals(['Traceback (most recent call last):', '  File "a.py", line 3',
                                         'KeyError: candle', 'socket.gaierror: [Errno -3] failure'], network)
    assert mixed['foreign_traceback'] is True and mixed['net_pattern'] is True
    cut = checkup.runtime_net_signals(['Traceback (most recent call last):', '  File "b.py", line 9'], network)
    assert cut['foreign_traceback'] is True


def test_queue_failure_repeats_the_same_episode_and_state_failure_queues_nothing(world, monkeypatch):
    world.health(NOW - 2 * MIN, NOW + 4 * RUN, candle_freshness=CANDLE_RED)

    class Failing(MemorySpool):
        def enqueue(self, entry):
            raise OSError(errno.ENOSPC, 'full')

    good = world.spool
    world.spool = Failing()
    broken = world.run()
    assert broken.code == 1 and broken.summary['error'] == 'OSError' and broken.entries == []
    world.spool = good
    again = world.next()                                   # the saved episode is announced again, same identity
    assert again.kinds() == ['open', 'comment'] and again.opens()[0]['episode'] == '20261007T0315Z'
    assert again.opens()[0]['at'] == NOW.isoformat()
    assert world.next().entries == []

    def no_disk(*args, **kwargs):
        raise OSError(errno.ENOSPC, 'full')

    other = World(world.root.parent / 'other')
    other.health(NOW - 2 * MIN, NOW + 4 * RUN, candle_freshness=CANDLE_RED)
    monkeypatch.setattr(checkup, 'save_state', no_disk)
    results = [other.run(), other.next(), other.next()]
    assert [result.code for result in results] == [1, 1, 1]
    assert other.spool.items == [] and other.spool.done == []         # no new episode, no issue per run


def test_resolve_waits_for_the_mode_the_issue_was_opened_in(world):
    world.health(NOW - 2 * MIN, NOW, candle_freshness=CANDLE_RED)
    assert opened_classes([world.run()]) == ['DATA_FLOW']
    world.env = env_for('dry-run')
    world.reporter = FakeReporter('dry-run')
    quiet = [world.next(), world.next(), world.next()]                # resolves at NOW+45 while in dry-run
    assert [result.entries for result in quiet] == [[], [], []]
    assert world.state()['chain']['status'] == 'resolved'
    world.env = env_for('off')
    world.reporter = FakeReporter('off')
    assert world.next().entries == []
    world.env = env_for('on')
    world.reporter = FakeReporter('on')
    late = world.next()
    assert late.kinds() == ['resolve'] and late.entries[0]['tag'] == 'resolved'
    assert late.entries[0]['at'] == (NOW + 45 * MIN).isoformat()
    assert '(erkannt 2026-10-07 03:15 UTC, erholt 2026-10-07 04:00 UTC)' in late.entries[0]['text']
    assert world.next().entries == []


# --- review fixes: network rule, catch-up, selftest, lost state -----------------------------------------------------

OUTBOX_WARNING = ('Binance public stream disconnected (live resume blocked by incomplete catch-up: durable outbox '
                  'capacity 5000 reached; event rejected for catch-up); retrying in 4.2s')


def test_internal_causes_are_not_network_patterns():
    network = POLICY.network
    for line in (OUTBOX_WARNING, "OSError: [Errno 111] Connect call failed ('127.0.0.1', 5432)",
                 "ConnectionRefusedError: [Errno 111] Connect call failed ('::1', 5432, 0, 0)"):
        assert checkup.runtime_net_signals([line], network)['net_pattern'] is False, line
    local = checkup.runtime_net_signals(['Traceback (most recent call last):', '  File "db.py", line 4',
                                         "ConnectionRefusedError: [Errno 111] Connect call failed ('127.0.0.1', "
                                         "5432)"], network)
    assert local['foreign_traceback'] is True                    # a local database failure, not the network
    wan = checkup.runtime_net_signals(['Binance public stream disconnected (Cannot connect to host '
                                       'stream.binance.com:9443); retrying in 2.0s'], network)
    assert wan['net_pattern'] is True


def test_catchup_outbox_incident_stays_data_flow(world):
    first = NOW - 40 * MIN
    world.health(NOW - 20 * MIN, NOW + 3 * RUN, candle_freshness=CANDLE_RED, gap_last_60m=gap_red(first, 40))
    world.runtime_lines = [(first + k * MIN, OUTBOX_WARNING) for k in range(0, 40, 5)]
    result = world.run()
    assert opened_classes([result]) == ['DATA_FLOW']
    assert result.opens()[0]['labels'] == ['incident', 'source:tim-checkup', 'priority:p1']


def test_data_flow_recovery_with_gap_is_not_a_network_change(world):
    first = NOW - 10 * MIN
    world.health(NOW - 10 * MIN, NOW, candle_freshness=CANDLE_RED, gap_last_60m=gap_red(first, 10))
    world.health(NOW + MIN, NOW + 3 * RUN, gap_last_60m=gap_red(first, 10))          # candles fresh, gap remains
    assert opened_classes([world.run()]) == ['DATA_FLOW']
    later = [world.next(), world.next()]
    assert [result.entries for result in later] == [[], []]
    assert world.state()['chain']['current'] == 'DATA_FLOW' and 'past_gap' not in world.state()['chain']['seen_checks']


def test_database_restart_below_threshold_explains_the_gap(world):
    first = NOW - 8 * MIN
    world.health(NOW - 8 * MIN, NOW - 7 * MIN, **DB_DOWN)                              # 2 samples: below threshold
    world.health(NOW - 6 * MIN, NOW + RUN, gap_last_60m=gap_red(first, 4))
    world.runtime_lines = [(first, "OSError: [Errno 111] Connect call failed ('127.0.0.1', 5432)")]
    result = world.run()
    assert result.opens() == [] and 'NETWORK' not in [item['class'] for item in result.summary['open']]
    later = world.next()                                     # the DATABASE samples left the 16-min window
    assert 'NETWORK' not in opened_classes([later]) + [item['class'] for item in later.summary['open']]
    assert world.state()['explained_gap'] == first.isoformat()


def test_long_wan_outage_keeps_network_without_extra_changed(world):
    down = OSError(errno.ENETUNREACH, 'unreachable')
    world.failing = {'stream.binance.com': down, 'api.binance.com': down}
    outage_end = NOW + 2 * RUN
    world.health(NOW - 20 * MIN, outage_end + RUN + 5 * MIN, candle_freshness=CANDLE_RED)     # catch-up runs late
    world.health(outage_end - 50 * MIN, NOW + 10 * RUN, gap_last_60m=gap_red(outage_end - 50 * MIN, 50))
    results = [world.run(), world.next()]
    assert opened_classes(results) == ['NETWORK']
    world.failing = {}
    for _ in range(3):                                           # probes ok, candles still stale, then fresh
        assert world.next().entries == []
        assert world.state()['chain']['status'] == 'active' and world.state()['chain']['current'] == 'NETWORK'


def test_selftest_survives_unreadable_controls(world):
    world.reporter.labels.add('checkup:selftest')
    assert opened_classes([world.run()]) == ['SELFTEST']
    world.reporter.authority = 'unknown'                        # GitHub unreachable: labels unknown
    world.reporter.labels.clear()
    assert [world.next().entries for _ in range(3)] == [[], [], []]
    world.reporter.authority = 'open'
    world.reporter.labels.add('checkup:selftest')
    assert world.next().entries == []                           # no reopen, nothing was resolved
    world.reporter.labels.clear()
    assert [world.next().kinds() for _ in range(2)] == [[], ['resolve']]


class AdoptingReporter(FakeReporter):
    def __init__(self, incidents, **kwargs):
        super().__init__(**kwargs)
        self.incidents = incidents

    def open_incidents(self):
        return self.incidents


def test_lost_state_while_github_unreachable_adopts_later(world):
    world.health(NOW - 2 * MIN, NOW + 8 * RUN, candle_freshness=CANDLE_RED)
    assert opened_classes([world.run()]) == ['DATA_FLOW']
    incidents = world.data / 'incidents'
    (incidents / 'state.json').unlink()
    (incidents / 'state.json.prev').unlink(missing_ok=True)
    world.reporter.authority = 'unknown'
    lost = world.next()
    assert lost.summary['state'] == 'lost' and world.state()['chain']['episode'] == '20261007T0330Z'
    world.reporter = AdoptingReporter([{'number': 8, 'class': 'DATA_FLOW', 'episode': '20261007T0315Z',
                                        'host': POLICY.host, 'labels': []}])
    adopted = world.next()
    assert adopted.summary['adopted'] == ['DATA_FLOW/20261007T0315Z']
    assert world.state()['chain']['episode'] == '20261007T0315Z'
    [entry] = adopted.opens()
    assert entry['episode'] == '20261007T0315Z' and entry['adopt_only'] is True
    assert world.next().summary.get('adopted') is None                     # adopted once, then kept


# --- diagnosis: requests, HOLD, PAUSE, breaker, ingest (PR-2, design C.5, B.8) -----------------------------------

from src.tim_incident import protocol                                           # noqa: E402
from src.tim_incident.policy import agent_budget                                # noqa: E402


def calibrated(**agent) -> object:
    """The shipped policy with the server-only values filled in (fake numbers: no measurement happened)."""
    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    data['agent'].update(model_digest='a' * 64, model_config_sha256='b' * 64, ollama_allowed_cpus='2-3,6-7',
                         resolver='public', measured={'prompt_tok_s': 20.0, 'gen_tok_s': 6.0, 'cache_ok': True})
    data['agent'].update(agent)
    return policy_from_dict(data)


def agent_world(tmp_path: Path, *, policy=None, diagnosis: str = 'on', labels=()) -> World:
    world = World(tmp_path, policy=policy or calibrated(), labels=labels)
    world.env['TIM_CHECKUP_DIAGNOSIS'] = diagnosis
    world.agent = tmp_path / 'tim-agent'
    for name in ('requests', 'results'):
        (world.agent / name).mkdir(parents=True)
    return world


def requests_dir(world: World) -> Path:
    return world.agent / 'requests'


def request_files(world: World) -> list[str]:
    return sorted(path.name for path in requests_dir(world).iterdir())


RID = '20261007T0315Z-data-flow-1'
QWEN_IDLE = {'ExecMainStartTimestamp': '', 'ExecMainExitTimestamp': '', 'Result': 'success', 'ActiveState': 'inactive'}


def qwen_run(start: datetime, end: datetime | None, result: str = 'success') -> dict:
    stamp = lambda moment: moment.strftime('%a %Y-%m-%d %H:%M:%S UTC')              # noqa: E731
    return {'ExecMainStartTimestamp': stamp(start), 'ExecMainExitTimestamp': stamp(end) if end else '',
            'Result': result, 'ActiveState': 'inactive' if end else 'active'}


def test_request_written_for_opened_qwen_class(tmp_path):
    world = agent_world(tmp_path, policy=calibrated(evidence_tokens_max=1024))
    secret = tmp_path / 'database-password'
    secret.write_text(DB_PASSWORD + '\n')
    world.env['TIM_DATABASE_SECRET_FILE'] = str(secret)
    world.units[checkup.QWEN_UNIT] = dict(QWEN_IDLE)
    lines = [f'2026-10-07T03:{index % 60:02d}:00+0000 tim-core-01 python[7]: candle {index} closed\x1b[0m'
             for index in range(400)]
    world.evidence_journal['tim-runtime.service'] = '\n'.join(lines) + (
        f'\n\n2026-10-07T03:14:00+0000 tim-core-01 python[7]: connect postgresql://tim:{DB_PASSWORD}@db/tim\n')
    world.health(NOW - 2 * MIN, NOW + 2 * RUN, candle_freshness=CANDLE_RED)
    first = world.run()
    assert opened_classes([first]) == ['DATA_FLOW'] and first.code == 0
    assert first.summary['qwen']['requests'] == [RID] and request_files(world) == [f'{RID}.json']
    path = requests_dir(world) / f'{RID}.json'
    assert path.stat().st_mode & 0o777 == 0o640
    raw = path.read_bytes()
    assert DB_PASSWORD.encode() not in raw and b'\x1b' not in raw
    request = protocol.validate_request(raw, allowed_units=world.policy.agent.units_allowlist,
                                        max_bytes=world.policy.limits.request_bytes)
    assert (request['episode'], request['class'], request['selftest']) == ('20261007T0315Z', 'DATA_FLOW', False)
    assert len(request['evidence']) <= agent_budget(world.policy.agent).evidence_chars == 3 * 1024
    assert request['units'] == ['tim-runtime.service', 'tim-candle-finalizer.service']
    assert set(request['journal']) <= set(request['units'])
    assert all(len(buffer) <= 200 for buffer in request['journal'].values())
    assert len(request['journal']['tim-runtime.service']) == 200                 # the newest 200 of 400 lines
    assert request['journal']['tim-runtime.service'][-1] == '[BLOCK ENTFERNT: bekanntes Geheimnis]'
    journal_calls = [argv for argv, _ in world.calls if argv[0] == 'journalctl' and 'short-iso' in argv]
    assert sorted(argv[2] for argv in journal_calls) == ['tim-candle-finalizer.service', 'tim-runtime.service']
    assert not final_scan(request['evidence'])
    assert [item['rid'] for item in world.state()['chain']['diagnoses']] == [RID]
    second = world.next()                                                       # ONGOING: no second request
    assert second.summary['qwen']['requests'] == [] and request_files(world) == [f'{RID}.json']


def test_no_request_while_not_calibrated_or_diagnosis_off(tmp_path):
    for name, policy, diagnosis, note in (('shipped', POLICY, 'on', 'no requests: not calibrated'),
                                          ('off', calibrated(), 'off', 'diagnosis off')):
        world = agent_world(tmp_path / name, policy=policy, diagnosis=diagnosis)
        world.health(NOW - 2 * MIN, NOW, candle_freshness=CANDLE_RED)
        result = world.run()
        assert opened_classes([result]) == ['DATA_FLOW']
        assert result.summary['qwen']['requests'] == [] and note in result.summary['qwen']['notes']
        assert request_files(world) == [] and result.code == 0
        assert [argv for argv, _ in world.calls if checkup.QWEN_UNIT in argv]        # HOLD/PAUSE/breaker still run


def test_no_request_for_class_without_qwen(tmp_path):
    world = agent_world(tmp_path)
    world.health(NOW - 20 * MIN, NOW + 3 * RUN, time_sync='RED')
    results = [world.run(), world.next(), world.next()]
    assert opened_classes(results) == ['TIME_SYNC'] and not world.policy.classes['TIME_SYNC'].qwen
    assert all(result.summary['qwen']['requests'] == [] for result in results) and request_files(world) == []


def test_hold_written_while_catching_up(tmp_path):
    world = agent_world(tmp_path)
    hold = requests_dir(world) / 'HOLD'
    world.run()
    assert not hold.exists()
    world.watch(NOW + RUN - 5 * MIN, NOW + RUN, queue_age='RED')
    result = world.next()
    assert hold.exists() and result.summary['qwen']['hold'] == ['watchdog.queue_age']
    assert hold.stat().st_mode & 0o777 == 0o640
    world.health(NOW + 2 * RUN - 5 * MIN, NOW + 2 * RUN, gap_last_60m=gap_red(NOW + RUN, 3))
    result = world.next()
    assert hold.exists() and result.summary['qwen']['hold'] == ['gap_last_60m']
    assert not world.next().summary['qwen']['hold'] and not hold.exists()
    world.health_until = world.now - timedelta(hours=1)                          # no health data at all: fail-closed
    world.health_file = False
    world.collect = lambda backup_dir, disk_path: None                          # the in-process collect fails too
    assert 'health unknown' in world.next().summary['qwen']['hold'] and hold.exists()


def test_pause_label_written_refreshed_and_cleared(tmp_path):
    world = agent_world(tmp_path, labels=('checkup:pause-qwen',))
    world.health(NOW - 2 * MIN, NOW + 4 * RUN, candle_freshness=CANDLE_RED)
    result = world.run()
    pause = protocol.read_pause(requests_dir(world), expected_uid=os.getuid())
    assert pause == {'version': 1, 'reason': 'label', 'until': protocol.iso(NOW + timedelta(minutes=30))}
    assert result.summary['qwen']['pause'] == 'label' and request_files(world) == ['PAUSE']
    assert 'no requests: paused (label)' in result.summary['qwen']['notes']
    world.reporter.authority = 'unknown'                                         # labels unreadable: pause kept
    world.reporter.labels.clear()
    world.next()
    assert protocol.read_pause(requests_dir(world), expected_uid=os.getuid())['until'] == \
        protocol.iso(NOW + RUN + timedelta(minutes=30))
    world.reporter.authority = 'open'
    assert world.next().summary['qwen']['pause'] is None and 'PAUSE' not in request_files(world)


def test_invalid_or_foreign_pause_is_replaced(tmp_path):
    directory = tmp_path / 'requests'
    directory.mkdir()
    (directory / 'PAUSE').write_text('{"reason": "label", "until": "never"}')
    assert protocol.pause_active(directory, NOW, expected_uid=os.getuid())            # the agent stays paused
    flags = checkup.write_hold_pause(directory, now=NOW, hold=False, label=False, own_uid=os.getuid())
    assert flags == {'hold': False, 'pause': None} and not (directory / 'PAUSE').exists()
    until = NOW + timedelta(hours=24)
    checkup.write_hold_pause(directory, now=NOW, hold=True, label=None, breaker_until=until, own_uid=os.getuid())
    flags = checkup.write_hold_pause(directory, now=NOW + RUN, hold=False, label=True, own_uid=os.getuid())
    assert flags == {'hold': False, 'pause': 'breaker'} and not (directory / 'HOLD').exists()
    assert protocol.read_pause(directory, expected_uid=os.getuid())['until'] == protocol.iso(until)
    flags = checkup.write_hold_pause(directory, now=until + MIN, hold=False, label=False, own_uid=os.getuid())
    assert flags['pause'] is None and not (directory / 'PAUSE').exists()


def qwen_end(result: str = 'success') -> str:
    return ('tim-qwen-diagnose.service: Deactivated successfully.' if result == 'success'
            else f"tim-qwen-diagnose.service: Failed with result '{result}'.")


def test_breaker_pauses_on_worsening_and_failed_runs(tmp_path):
    # (c) two runs in a row without success
    world = agent_world(tmp_path / 'failed')
    world.health(NOW - 2 * MIN, NOW + 4 * RUN, candle_freshness=CANDLE_RED)
    world.units[checkup.QWEN_UNIT] = qwen_run(NOW - 10 * MIN, NOW - 3 * MIN, 'timeout')
    world.qwen_journal += ['{"event": "diagnose_end"}', 'tim-qwen-diagnose.service: start operation timed out.',
                           qwen_end('timeout')]
    first = world.run()
    assert first.summary['qwen']['breaker'] == [] and first.summary['qwen']['requests'] == [RID]
    assert world.state()['diagnosis']['failed_streak'] == 1
    assert world.next().summary['qwen']['breaker'] == []                       # the same run is counted once
    world.units[checkup.QWEN_UNIT] = qwen_run(NOW + RUN, NOW + RUN + 8 * MIN, 'oom-kill')
    world.qwen_journal.append(qwen_end('oom-kill'))
    tripped = world.next()
    at = NOW + 2 * RUN
    assert tripped.summary['qwen']['breaker'] == ['failed_runs'] and tripped.summary['qwen']['pause'] == 'breaker'
    pause = protocol.read_pause(requests_dir(world), expected_uid=os.getuid())
    assert pause == {'version': 1, 'reason': 'breaker', 'until': protocol.iso(at + timedelta(hours=24))}
    [comment] = [entry for entry in tripped.entries if entry['kind'] == 'comment']
    assert comment['tag'] == 'qwen-paused-20261007t0345' and comment['class'] == 'DATA_FLOW'
    assert comment['text'].startswith('Qwen pausiert: Verdacht auf Lastwirkung (zwei Läufe in Folge')
    assert not final_scan(comment['text'])
    world.units[checkup.QWEN_UNIT] = qwen_run(NOW + 2 * RUN + MIN, NOW + 2 * RUN + 9 * MIN, 'signal')
    world.qwen_journal += [qwen_end('signal'), qwen_end('signal')]
    again = world.next()                                                        # paused: no second trip or comment
    assert again.summary['qwen']['breaker'] == [] and again.summary['qwen']['pause'] == 'breaker'
    assert [entry for entry in again.entries if entry['kind'] == 'comment'] == []
    assert world.state()['diagnosis']['failed_streak'] == 0                    # nothing counts during the pause

    # (b) data_age rises during the run
    world = agent_world(tmp_path / 'age')
    world.watch(NOW - 9 * MIN, NOW - 4 * MIN, data_age={'status': 'GREEN', 'value': 170.0, 'reason': 'fixture'})
    world.units[checkup.QWEN_UNIT] = qwen_run(NOW - 9 * MIN, NOW - 4 * MIN)
    result = world.run()
    assert result.summary['qwen']['breaker'] == ['age_jump'] and result.summary['qwen']['pause'] == 'breaker'
    assert result.entries == []                                                 # no episode, no request: no comment

    # (a) a chain class turns RED while Qwen runs
    world = agent_world(tmp_path / 'red')
    world.health(NOW - 5 * MIN, NOW, candle_freshness=CANDLE_RED)
    world.units[checkup.QWEN_UNIT] = qwen_run(NOW - 6 * MIN, None)              # still running
    result = world.run()
    assert result.summary['qwen']['breaker'] == ['chain_red'] and result.summary['qwen']['pause'] == 'breaker'
    assert result.summary['qwen']['requests'] == [] and 'no requests: paused (breaker)' in \
        result.summary['qwen']['notes']

    # a quiet run changes nothing
    world = agent_world(tmp_path / 'quiet')
    world.units[checkup.QWEN_UNIT] = qwen_run(NOW - 9 * MIN, NOW - 4 * MIN)
    result = world.run()
    assert result.summary['qwen']['breaker'] == [] and result.summary['qwen']['pause'] is None


def test_breaker_counts_timeout_killed_retries_but_not_exit_code(tmp_path):
    # Two runs killed by TimeoutStartSec, the retry starting at once: the newest window is always the running retry,
    # yet the journal shows both ends (review R2-LOOP-1).
    world = agent_world(tmp_path / 'killed')
    world.units[checkup.QWEN_UNIT] = qwen_run(NOW - 2 * MIN, None)
    world.qwen_journal += [qwen_end('timeout')]
    assert world.run().summary['qwen']['breaker'] == []
    world.units[checkup.QWEN_UNIT] = qwen_run(NOW + RUN - 2 * MIN, None)
    world.qwen_journal += [qwen_end('timeout')]
    assert world.next().summary['qwen']['breaker'] == ['failed_runs']
    # A persistent selfcheck failure (exit 2 every 5 min) is no load symptom: a note, never the breaker (R2-LOOP-5).
    world = agent_world(tmp_path / 'selfcheck')
    world.units[checkup.QWEN_UNIT] = qwen_run(NOW - 2 * MIN, NOW - 2 * MIN, 'exit-code')
    world.qwen_journal += [qwen_end('exit-code')] * 3
    result = world.run()
    assert result.summary['qwen']['breaker'] == [] and world.state()['diagnosis']['failed_streak'] == 0
    assert 'qwen runs failed without load symptom: exit-code (3)' in result.summary['qwen']['notes']
    world.qwen_journal += [qwen_end('exit-code')] * 3
    assert world.next().summary['qwen']['breaker'] == []
    # A success between two load failures resets the streak.
    world = agent_world(tmp_path / 'mixed')
    world.qwen_journal += [qwen_end('timeout'), qwen_end(), qwen_end('signal')]
    assert world.run().summary['qwen']['breaker'] == [] and world.state()['diagnosis']['failed_streak'] == 1


def test_qwen_run_results_reads_systemd_end_lines_and_cursor():
    seen = []

    def runner(argv, timeout):
        seen.append(argv)
        return 0, ('{"event": "diagnose_end", "note": "Failed with result \'timeout\'."}\n'
                   "tim-qwen-diagnose.service: Failed with result 'oom-kill'.\n"
                   'tim-qwen-diagnose.service: Succeeded.\n-- cursor: s=ab12;i=3f;b=cd\n')
    assert checkup.qwen_run_results(runner, None, now=NOW, timeout=5) == (['oom-kill', 'success'], 's=ab12;i=3f;b=cd')
    assert seen[0][:3] == ['journalctl', '-u', checkup.QWEN_UNIT] and '--since' in seen[0]
    checkup.qwen_run_results(runner, 's=ab12;i=3f;b=cd', now=NOW, timeout=5)
    assert seen[1][-2:] == ['--after-cursor', 's=ab12;i=3f;b=cd'] and '--since' not in seen[1]
    assert checkup.qwen_run_results(lambda argv, timeout: (1, ''), 'x', now=NOW, timeout=5) is None
    assert checkup.qwen_run_results(lambda argv, timeout: (0, ''), 'keep', now=NOW, timeout=5) == ([], 'keep')
    assert checkup._valid_diagnosis_state({'journal_cursor': 'a b'})['journal_cursor'] is None


def test_qwen_run_window_parses_systemctl_show():
    def runner(argv, timeout):
        assert argv[:3] == ['systemctl', 'show', checkup.QWEN_UNIT] and '--timestamp=utc' in argv
        return 0, ('ExecMainStartTimestamp=Wed 2026-10-07 03:10:00 UTC\nExecMainExitTimestamp=Wed 2026-10-07 '
                   '03:12:30.123456 UTC\nResult=timeout\nActiveState=failed\n')
    window = checkup.qwen_run_window(runner, timeout=5)
    assert window == {'start': datetime(2026, 10, 7, 3, 10, tzinfo=UTC),
                      'end': datetime(2026, 10, 7, 3, 12, 30, tzinfo=UTC), 'result': 'timeout'}
    assert checkup.qwen_run_window(lambda argv, timeout: (0, 'ExecMainStartTimestamp=\n'), timeout=5) is None
    assert checkup.qwen_run_window(lambda argv, timeout: (1, ''), timeout=5) is None


def test_overdue_request_comment_once_and_ack(tmp_path):
    world = agent_world(tmp_path)
    world.health(NOW - 2 * MIN, NOW + 4 * RUN, candle_freshness=CANDLE_RED)
    world.run()
    path = requests_dir(world) / f'{RID}.json'
    os.utime(path, (NOW.timestamp(), NOW.timestamp()))
    assert world.next().summary['qwen']['missing'] == []                       # 15 min: still waiting
    result = world.run(at=NOW + 61 * MIN)
    assert result.summary['qwen']['missing'] == [RID]
    [comment] = [entry for entry in result.entries if entry['kind'] == 'comment']
    assert comment['tag'] == 'diagnosis-20261007t0315z-data-flow-1' and comment['class'] == 'DATA_FLOW'
    assert comment['text'].startswith('Diagnose ausgefallen: Zum Auftrag 1 zur Klasse DATA_FLOW')
    assert (requests_dir(world) / f'{RID}.ack').exists()
    assert world.next().summary['qwen']['missing'] == []                       # exactly one comment
    assert protocol.pending_rids(requests_dir(world), world.agent / 'results') == []


def test_held_request_is_not_overdue_until_an_hour_after_hold_clears(tmp_path):
    # A RUNTIME/DATA_FLOW incident keeps HOLD up for hours: that time is no failure of the diagnosis (R2-LOOP-2).
    world = agent_world(tmp_path)
    world.health(NOW - 2 * MIN, NOW + 10 * RUN, candle_freshness=CANDLE_RED)
    world.run()
    path = requests_dir(world) / f'{RID}.json'
    os.utime(path, (NOW.timestamp(), NOW.timestamp()))
    held_until = NOW + 90 * MIN
    world.watch(NOW, held_until, queue_age='RED')
    for at in (NOW + 30 * MIN, NOW + 61 * MIN, held_until):
        result = world.run(at=at)
        assert result.summary['qwen']['hold'] and result.summary['qwen']['missing'] == []
    assert path.stat().st_mtime == held_until.timestamp() and not (requests_dir(world) / f'{RID}.ack').exists()
    assert world.run(at=held_until + 30 * MIN).summary['qwen']['missing'] == []
    assert world.run(at=held_until + 61 * MIN).summary['qwen']['missing'] == [RID]


def test_retention_deletes_only_own_acked_requests_after_8_days(tmp_path):
    paths = checkup.AgentPaths(tmp_path)
    paths.requests.mkdir()
    paths.results.mkdir()
    old, fresh = '20260920T0100Z-runtime-1', '20261006T0100Z-runtime-1'
    for rid in (old, fresh):
        (paths.requests / f'{rid}.json').write_text('{}')
        protocol.write_ack(paths.requests, rid, NOW)
    stamp = (NOW - timedelta(days=8)).timestamp()
    os.utime(paths.requests / f'{old}.ack', (stamp, stamp))
    week = (NOW - timedelta(days=7, hours=12)).timestamp()      # the agent prunes its result after 7 days first
    os.utime(paths.requests / f'{fresh}.ack', (week, week))
    assert checkup.retain_requests(paths, NOW, own_uid=os.getuid() + 1) == 0     # foreign files stay
    assert checkup.retain_requests(paths, NOW, own_uid=os.getuid()) == 1
    assert sorted(path.name for path in paths.requests.iterdir()) == [f'{fresh}.ack', f'{fresh}.json']


def _write_result(world: World, rid: str, **overrides) -> None:
    result = {'version': 1, 'rid': rid, 'status': 'ok', 'summary': 'Catch-up blockiert den Live-Stream.',
              'root_cause': 'Die Schleife wartet auf die Outbox.', 'confidence': 0.6, 'fix_kind': 'code_src',
              'locations': [{'path': 'src/data_ingestion/catchup.py', 'line': 251, 'why': 'Wartet ohne Timeout'},
                            {'path': 'src/data_ingestion/missing.py', 'line': 3, 'why': 'erfunden'}],
              'suggestion': 'Timeout setzen.', 'verification': 'Lücke schließt sich.', 'sources': [],
              'fetched_urls': [], 'needs_human': True, 'unverified_locations': 0, 'mode': 'native', 'rounds': 2}
    result.update(overrides)
    protocol.write_result(world.agent / 'results', result)


def test_ingest_through_run_comment_fields_and_ack(tmp_path):
    world = agent_world(tmp_path)
    source = world.root / 'src' / 'data_ingestion'
    source.mkdir(parents=True)
    (source / 'catchup.py').write_text(''.join(f'line {index} INHALT-NIE-ZITIEREN\n' for index in range(300)))
    world.health(NOW - 2 * MIN, NOW + 4 * RUN, candle_freshness=CANDLE_RED)
    world.run()
    _write_result(world, RID)
    result = world.next()
    assert result.summary['qwen']['ingest'] == {'ingested': 1, 'failed': 0, 'rejected': 0, 'unknown': 0,
                                                'skipped': None}
    comment, fields = [entry for entry in result.entries if entry['kind'] in ('comment', 'fields')]
    assert comment['tag'] == 'diagnosis-20261007t0315z-data-flow-1' and comment['class'] == 'DATA_FLOW'
    assert 'INHALT-NIE-ZITIEREN' not in json.dumps(result.entries)
    assert '- Geprüfte Stellen (Datei und Zeile bestätigt, Inhalt nicht zitiert): src/data_ingestion/catchup.py:251' \
        in comment['text'] and '- Nicht bestätigte Stellen, entfernt: 1' in comment['text']
    assert fields['fields'] == {'fix_kind': 'code_src', 'locations': ['src/data_ingestion/catchup.py:251']}
    assert fields['labels'] == ['incident:code'] and fields['mode'] == 'on' and fields['active'] is True
    assert (requests_dir(world) / f'{RID}.ack').exists()
    assert [entry for entry in world.next().entries if entry['kind'] in ('comment', 'fields')] == []


def test_diagnosis_step_errors_keep_exit_code(tmp_path, monkeypatch):
    world = agent_world(tmp_path)
    world.health(NOW - 2 * MIN, NOW, candle_freshness=CANDLE_RED)

    def broken(*args, **kwargs):
        raise OSError('disk gone')
    monkeypatch.setattr(checkup, 'write_hold_pause', broken)
    result = world.run()
    assert result.code == 0 and result.summary['qwen'] == {'error': 'OSError'} and result.opens()


def test_selftest_request_uses_the_recorded_bundle(tmp_path):
    world = agent_world(tmp_path / 'missing', labels=('checkup:selftest',))
    result = world.run()
    assert opened_classes([result]) == ['SELFTEST'] and result.summary['qwen']['requests'] == []
    assert any(note.startswith('SELFTEST/') and 'request not written' in note for note in result.summary['qwen']['notes'])

    world = agent_world(tmp_path / 'bundle', labels=('checkup:selftest',))
    bundle = world.root / checkup.SELFTEST_BUNDLE
    bundle.parent.mkdir(parents=True)
    bundle.write_text(json.dumps({
        'evidence': f'gap 03:01-03:14, catch-up blocked, password={DB_PASSWORD}',
        'units': ['tim-runtime.service'],
        'journal': {'tim-runtime.service': ['2026-09-30T03:12:00+0000 live resume blocked by incomplete catch-up']},
        'expected_paths': ['src/data_ingestion/catchup.py', 'src/data_ingestion/durable.py']}))
    result = world.run()
    [rid] = result.summary['qwen']['requests']
    assert rid == '20261007T0315Z-selftest-1'
    request = json.loads((requests_dir(world) / f'{rid}.json').read_text())
    assert request['selftest'] is True and request['units'] == ['tim-runtime.service']
    assert request['expected_paths'] == ['src/data_ingestion/catchup.py', 'src/data_ingestion/durable.py']
    assert DB_PASSWORD not in request['evidence']


def test_qwen_units_watched_in_unit_class_only_with_diagnosis_on(tmp_path):
    for diagnosis in ('on', 'off'):
        world = agent_world(tmp_path / diagnosis, diagnosis=diagnosis)
        world.units['tim-qwen-diagnose.timer'] = {'ActiveState': 'inactive', 'SubState': 'dead'}
        results = [world.run(), world.next()]
        queried = {argv[2] for argv, _ in world.calls if argv[:2] == ['systemctl', 'show']}
        if diagnosis == 'on':                       # the installer enabled both: a stopped timer is a UNIT incident
            assert set(checkup.DIAGNOSIS_WATCH_UNITS) <= queried
            assert opened_classes(results) == ['UNIT']
            [entry] = [entry for result in results for entry in result.opens()]
            assert 'tim-qwen-diagnose.timer' in entry['body'] and 'tim-checkup.path' not in entry['body']
        else:                                       # disabled on purpose: neither queried nor reported
            assert not set(checkup.DIAGNOSIS_WATCH_UNITS) & queried and opened_classes(results) == []
