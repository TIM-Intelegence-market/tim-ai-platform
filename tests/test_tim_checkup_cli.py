"""scripts/tim_checkup.py end to end: checkup, real reporter and spool against a fake tim-core-01 and a fake GitHub.

No network, no journal, no systemctl, no openssl: the journal and systemctl answer through a fake runner, sockets
through a fake connect, GitHub is `FakeRest` behind the injectable transport, openssl is a fake runner.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from scripts import tim_checkup
from src.task_governance import TaskRegistry
from src.task_governance.create_authority import authority_body
from src.tim_incident import checkup
from src.tim_incident import github as gh
from src.tim_incident.policy import CONTROL_LABELS, LABEL_ALLOWLIST, load_policy
from src.tim_incident.redaction import LITERAL_REMOVED, literal_variants
from tests.task_governance.fake_rest import FakeRest

UTC = timezone.utc
NOW = datetime(2026, 10, 7, 3, 15, tzinfo=UTC)
MIN, RUN = timedelta(minutes=1), timedelta(minutes=15)
POLICY = load_policy()
REPO, HOST = POLICY.repository, POLICY.host
EPISODE = '20261007T0315Z'
OWNER, BOT = 'uezeyiraydin-cell', 'tim-reporter[bot]'
AUTHORITY = 7
SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'tim_checkup.py'
# Synthetic values only; none of them is or was a real credential.
TOKEN = 'ghs_' + 'Xc8Vb2Nm5Lk7Jh4Gf1Ds9Aq3Wz6Er0Ty5Ui'
KEY = ('-----BEGIN PRIVATE KEY-----\n'
       'MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7testkeyline01\n'
       '-----END PRIVATE KEY-----\n')
DB_PASSWORD = 'Rz4Tq8Wm2Xn6Bv1Kc9Lp3Hs7Jd5Fg0Ya'
SIGNATURE = b'\x02fake-rsa-signature\xfe'
CANDLE_RED = {'status': 'RED', 'age_seconds': 900.0, 'max_age_seconds': 180}
UNIT_SHOW = 'LoadState=loaded\nActiveState=active\nSubState=running\nResult=success\nNRestarts=0\nExecMainStatus=0\n'


class GitHub(FakeRest):
    """FakeRest plus the App token endpoint, repository labels, label and comment writes with authors, and
    closed_by/state_reason on PATCH. `requests` records every call as (method, path, body)."""

    def __init__(self):
        super().__init__(REPO)
        self.login = BOT                        # the account behind the installation token
        self.repo_labels = set(LABEL_ALLOWLIST | CONTROL_LABELS)
        self.requests: list[tuple[str, str, bytes]] = []
        self._ids = 0

    def seed(self, number, body='', state='open', login=BOT, pr=False, labels=(), closed_by=None):
        super().seed(number, body, state, login, pr)
        self.issues[number].update(labels=[{'name': name} for name in labels], state_reason=None,
                                   closed_by={'login': closed_by} if closed_by else None)
        self.next_number = max(self.next_number, number)

    def writes_to_repo(self) -> list[tuple[str, str]]:
        return [(method, path) for method, path, _ in self.requests if method != 'GET' and path.startswith('/repos/')]

    def incidents(self) -> list[int]:
        return [number for number in sorted(self.issues) if number != AUTHORITY]

    def bot_comments(self, number) -> list[str]:
        return [item['body'] for item in self.comments.get(number, []) if (item.get('user') or {}).get('login') == BOT]

    def __call__(self, method, url, headers, body, timeout):
        parsed = urlparse(url)
        path, base = parsed.path, f'/repos/{self.repo}'
        self.requests.append((method, path, body or b''))
        payload = json.loads(body) if body else None
        if method == 'POST' and re.fullmatch(r'/app/installations/\d+/access_tokens', path):
            return 201, json.dumps({'token': TOKEN, 'permissions': {'issues': 'write', 'metadata': 'read'},
                                    'repositories': [{'name': 'tim-ai-platform'}]}).encode()
        if method == 'GET' and path == f'{base}/labels':
            query = parse_qs(parsed.query)
            per, page = int(query['per_page'][0]), int(query['page'][0])
            items = [{'name': name} for name in sorted(self.repo_labels)]
            return 200, json.dumps(items[(page - 1) * per: page * per]).encode()
        match = re.fullmatch(re.escape(base) + r'/issues/(\d+)/(labels|comments)', path)
        if match and method == 'POST':
            number = int(match.group(1))
            if match.group(2) == 'labels':
                labels = self.issues[number]['labels']
                labels.extend({'name': name} for name in payload['labels'] if {'name': name} not in labels)
                return 200, json.dumps(labels).encode()
            self._ids += 1
            comment = {'id': self._ids, 'body': payload['body'], 'user': {'login': self.login}}
            self.comments.setdefault(number, []).append(comment)
            return 201, json.dumps(comment).encode()
        match = re.fullmatch(re.escape(base) + r'/issues/(\d+)', path)
        if match and method == 'PATCH' and int(match.group(1)) in self.issues:
            item = self.issues[int(match.group(1))]
            if payload.get('state') == 'closed':
                item.update(state='closed', closed_by={'login': self.login},
                            state_reason=payload.get('state_reason') or 'completed')
            elif payload.get('state') == 'open':
                item.update(state='open', closed_by=None, state_reason='reopened')
            if 'body' in payload:
                item['body'] = payload['body']
            return 200, json.dumps(item).encode()
        return super().__call__(method, url, headers, body, timeout)


def health_report(at: datetime, red: bool) -> dict:
    checks = {
        'runtime': {'status': 'GREEN', 'active': 'active', 'sub': 'running'},
        'candle_freshness': dict(CANDLE_RED) if red else {'status': 'GREEN', 'age_seconds': 30.0,
                                                          'max_age_seconds': 180},
        'gap_last_60m': {'status': 'GREEN', 'missing': 0, 'first_missing': [], 'expected': 60},
        'disk': {'status': 'GREEN', 'path': '/opt/tim', 'used_percent': 41.0},
        'time_sync': {'status': 'GREEN', 'ntp_synchronized': True},
        'backup': {'status': 'GREEN', 'newest': 'tim-20261007T0200Z.dump', 'age_hours': 1.2},
    }
    return {'timestamp': at.isoformat(), 'status': 'RED' if red else 'GREEN', 'checks': checks, 'mode': 'OBSERVE',
            'trading_actions': 0}


class Server:
    """A fake tim-core-01 behind scripts/tim_checkup.py: status files, journal, systemctl, sockets, statvfs, /proc,
    clock, credentials and GitHub. `run()` is one timer run; `red` lists the windows with candle_freshness RED."""

    def __init__(self, tmp_path: Path, mode: str | None = 'on', *, authority_state: str = 'open'):
        self.tmp = tmp_path
        self.root = tmp_path / 'opt-tim'
        self.data = self.root / 'data'
        (self.data / 'operational').mkdir(parents=True)
        (self.data / 'incidents').mkdir(mode=0o700)
        (self.root / 'config').mkdir()
        (self.root / 'config' / 'core_manifest.json').write_text(
            json.dumps({'status': 'FROZEN', 'operating_mode': 'OBSERVE'}), encoding='utf-8')
        self.proc = tmp_path / 'proc'
        self.proc.mkdir()
        (self.proc / 'meminfo').write_text('MemTotal: 64000000 kB\nMemAvailable: 30000000 kB\n', encoding='utf-8')
        (self.proc / 'loadavg').write_text('0.50 0.40 0.30 1/200 1234\n', encoding='utf-8')
        self.credentials = tmp_path / 'credentials'
        self.credentials.mkdir()
        (self.credentials / 'github-app-key').write_text(KEY, encoding='utf-8')
        secret = tmp_path / 'database-password'
        secret.write_text(DB_PASSWORD + '\n', encoding='utf-8')
        registry = TaskRegistry(str(self.data / 'incidents' / 'registry.sqlite'))
        self.registry_id = registry.registry_id
        registry.close()
        self.github = GitHub()
        self.github.seed(AUTHORITY, authority_body(self.registry_id, REPO), state=authority_state, login=OWNER,
                         labels=('governance',), closed_by=OWNER if authority_state == 'closed' else None)
        self.env = {'CREDENTIALS_DIRECTORY': str(self.credentials), 'TIM_DATABASE_SECRET_FILE': str(secret)}
        if mode is not None:
            self.env.update(TIM_CHECKUP_REPORTING=mode, TIM_CHECKUP_DIAGNOSIS='off', TIM_CHECKUP_APP_ID='12345',
                            TIM_CHECKUP_INSTALLATION_ID='67890', TIM_CHECKUP_AUTHORITY_ISSUE=str(AUTHORITY),
                            TIM_CHECKUP_REPORTER_LOGIN=BOT, TIM_CHECKUP_OWNER_LOGIN=OWNER)
        self.now = NOW
        self.red: list[tuple[datetime, datetime]] = []
        self.commands: list[list[str]] = []
        self.signed: list[bytes] = []
        self.probes: list[tuple[str, int]] = []
        self.stdout: list[str] = []

    # --- fakes -----------------------------------------------------------------------------------------------------
    def is_red(self, at: datetime) -> bool:
        return any(start <= at <= end for start, end in self.red)

    def minutes(self, since: datetime) -> list[datetime]:
        moment, found = since.replace(second=0, microsecond=0), []
        while moment <= self.now:
            if moment >= since:
                found.append(moment)
            moment += MIN
        return found

    def runner(self, argv: list[str], timeout: float) -> tuple[int, str]:
        assert argv[0] in ('journalctl', 'systemctl') and timeout > 0, argv
        self.commands.append(list(argv))
        if argv[0] == 'systemctl':
            assert argv[1] == 'show'
            return 0, UNIT_SHOW
        unit, output = argv[argv.index('-u') + 1], argv[argv.index('-o') + 1]
        if unit == checkup.HEALTH_UNIT and output == 'cat':
            since = datetime.strptime(argv[argv.index('--since') + 1], '%Y-%m-%d %H:%M:%S UTC').replace(tzinfo=UTC)
            reports = [json.dumps(health_report(at, self.is_red(at))) for at in self.minutes(since)]
            return 0, 'tim-server-health starting\n' + '\n'.join(reports) + '\n'
        if output == 'cat':
            return 0, ''
        assert output == 'short-iso'
        return 0, (f'2026-10-07T03:10:00+0000 {HOST} {unit}: candle lag\n'
                   f'2026-10-07T03:11:00+0000 {HOST} {unit}: connecting with password {DB_PASSWORD}\n')

    def connect(self, host: str, port: int, timeout: float) -> None:
        self.probes.append((host, port))

    def openssl(self, argv, *, input, timeout):
        assert argv[:4] == ['openssl', 'dgst', '-sha256', '-sign'] and argv[-1] == '-binary'
        self.signed.append(input)
        return SimpleNamespace(returncode=0, stdout=SIGNATURE, stderr=b'')

    @staticmethod
    def statvfs(path: str):
        return SimpleNamespace(f_blocks=10_000, f_bfree=6_000, f_bavail=6_000, f_frsize=4096)

    def collect(self, backup_dir, root):
        raise AssertionError('the health file is fresh: collect() must not run')

    def write_health_file(self) -> None:
        at = self.minutes(self.now - timedelta(minutes=5))[-1]
        path = self.data / 'operational' / 'server_health.json'
        path.write_text(json.dumps(health_report(at, self.is_red(at))), encoding='utf-8')
        os.utime(path, (at.timestamp(), at.timestamp()))

    # --- running ---------------------------------------------------------------------------------------------------
    def run(self, *, at: datetime | None = None, **overrides) -> tuple[int, dict]:
        if at is not None:
            self.now = at
        self.write_health_file()
        out = io.StringIO()
        arguments = dict(root=self.root, data_dir=self.data, environ=self.env, clock=lambda: self.now.timestamp(),
                         monotonic=lambda: 1000.0, transport=self.github, openssl=self.openssl, runner=self.runner,
                         connect=self.connect, health_collect=self.collect, statvfs=self.statvfs, proc_dir=self.proc)
        arguments.update(overrides)
        with contextlib.redirect_stdout(out):
            code = tim_checkup.run_checkup(**arguments)
        lines = out.getvalue().splitlines()
        assert len(lines) == 1, lines                   # exactly one JSON line per run, nothing else on stdout
        self.stdout.extend(lines)
        summary = json.loads(lines[0])
        assert summary['event'] == 'checkup_end' and summary['exit_code'] == code
        return code, summary

    def next(self, **overrides) -> tuple[int, dict]:
        return self.run(at=self.now + RUN, **overrides)

    def incidents_dir(self) -> Path:
        return self.data / 'incidents'

    def pending(self) -> list[str]:
        return sorted(path.name for path in (self.incidents_dir() / 'outbox').glob('*.json'))

    def done_notes(self) -> list[str]:
        return [json.loads(path.read_text(encoding='utf-8'))['done']['note']
                for path in sorted((self.incidents_dir() / 'outbox' / 'done').glob('*.json'))]

    def local_text(self) -> str:
        """Everything the checkup and the reporter wrote locally, plus stdout."""
        parts = list(self.stdout)
        for path in sorted(self.data.rglob('*')):
            if path.is_file() and path.suffix != '.sqlite':
                parts.append(path.read_text(encoding='utf-8', errors='replace'))
        return '\n'.join(parts)


@pytest.fixture(autouse=True)
def _no_prctl(monkeypatch):
    monkeypatch.setattr(checkup, 'disable_core_dumps', lambda: True)


def assert_no_secret(text: str) -> None:
    key_lines = [line for line in KEY.splitlines() if 'BEGIN' not in line and 'END' not in line]
    for secret in (DB_PASSWORD, TOKEN, *key_lines):
        for variant in literal_variants(secret) or [secret]:
            assert variant not in text


# --- (a) reporting off ---------------------------------------------------------------------------------------------

def test_reporting_off_talks_to_nobody(tmp_path):
    server = Server(tmp_path, mode=None)                # TIM_CHECKUP_* unset: the first timer run after install
    server.red.append((NOW - 2 * MIN, NOW + RUN))
    code, summary = server.run()
    assert code == 0
    assert (summary['reporting'], summary['preflight'], summary['journal_access']) == ('off', 'skipped', 'ok')
    assert (summary['authority'], summary['settings'], summary['state']) == ('not_configured', 'ok', 'new')
    assert summary['open'] == [{'class': 'DATA_FLOW', 'episode': EPISODE, 'current': 'DATA_FLOW', 'announced': None}]
    assert summary['enqueued'] == summary['delivered'] == summary['pending'] == 0
    assert server.github.requests == [] and server.signed == []          # no HTTP, no openssl
    assert server.pending() == []
    last = json.loads((server.incidents_dir() / 'checkup_last_run.json').read_text(encoding='utf-8'))
    assert (last['phase'], last['exit_code'], last['reporting']) == ('finished', 0, 'off')
    code, summary = server.next()
    assert code == 0 and server.github.requests == [] and summary['state'] == 'ok'


# --- (b) dry run, then on ------------------------------------------------------------------------------------------

def test_dry_run_reads_only_then_on_creates_once(tmp_path):
    server = Server(tmp_path, mode='dry-run')
    server.red.append((NOW - 2 * MIN, NOW + 2 * RUN))
    code, summary = server.run()
    assert code == 0
    assert (summary['reporting'], summary['preflight'], summary['journal_access']) == ('dry-run', 'ok', 'ok')
    assert (summary['enqueued'], summary['delivered'], summary['pending']) == (2, 2, 0)
    rest = server.github
    others = [(method, path) for method, path, _ in rest.requests if method != 'GET']
    assert others == [('POST', '/app/installations/67890/access_tokens')]       # the token; every repo call is a GET
    assert rest.writes_to_repo() == [] and rest.incidents() == []
    records = [json.loads(line) for line in
               (server.incidents_dir() / 'dryrun.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [record['would'] for record in records] == ['create_issue', 'comment']
    assert records[0]['title'] == 'Vorfall DATA_FLOW auf tim-core-01 seit 2026-10-07 03:15 UTC'
    assert records[0]['labels'] == ['incident', 'source:tim-checkup', 'priority:p1']
    assert records[1]['tag'] == 'evidence' and LITERAL_REMOVED in records[1]['text']
    assert server.done_notes() == ['dry-run', 'dry-run'] and server.pending() == []

    server.env['TIM_CHECKUP_REPORTING'] = 'on'          # the owner's explicit yes after 24 h of dry run
    code, summary = server.next()
    assert code == 0 and (summary['reporting'], summary['preflight']) == ('on', 'ok')
    [number] = rest.incidents()
    assert rest.issues[number]['title'] == 'Vorfall DATA_FLOW auf tim-core-01 seit 2026-10-07 03:15 UTC'
    assert len(rest.bot_comments(number)) == 1
    code, summary = server.next()
    assert code == 0 and rest.incidents() == [number] and summary['enqueued'] == 0
    assert_no_secret(server.local_text())


# --- (c) on: open once, evidence, recovery ---------------------------------------------------------------------------

def test_on_opens_one_issue_with_evidence_and_closes_after_recovery(tmp_path):
    server = Server(tmp_path, mode='on')
    server.red.append((NOW - 2 * MIN, NOW + RUN))
    rest = server.github
    code, summary = server.run()
    assert code == 0
    assert (summary['reporting'], summary['preflight'], summary['authority']) == ('on', 'ok', 'open')
    assert summary['transitions'] == [f'opened:DATA_FLOW:{EPISODE}'] and summary['delivered'] == 2
    [number] = rest.incidents()
    issue = rest.issues[number]
    assert issue['user']['login'] == BOT and issue['state'] == 'open'
    assert gh.parse_incident_marker(issue['body']) == ('DATA_FLOW', EPISODE, HOST)
    assert f'cc @{OWNER}' in issue['body'] and 'fehlschlagende Prüfungen: candle_freshness' in issue['body']
    assert [label['name'] for label in issue['labels']] == ['incident', 'source:tim-checkup', 'priority:p1']
    [evidence] = rest.bot_comments(number)
    assert evidence.startswith(gh.tag_marker(EPISODE, 'evidence'))
    assert '### 1. Fehlschlagende Prüfungen und Unterbefunde' in evidence and '### 9. Watchdog' in evidence
    assert LITERAL_REMOVED in evidence                  # the journal block with the DB password is gone whole
    assert rest.writes_to_repo() == [('POST', f'/repos/{REPO}/issues'),
                                     ('POST', f'/repos/{REPO}/issues/{number}/labels'),
                                     ('POST', f'/repos/{REPO}/issues/{number}/comments')]

    writes = len(rest.writes_to_repo())
    code, summary = server.next()                       # NOW+15: still RED, ONGOING is silent
    assert code == 0 and summary['enqueued'] == 0 and len(rest.writes_to_repo()) == writes
    code, summary = server.next()                       # NOW+30: RED samples still in the 16-min window
    assert summary['open'] and len(rest.writes_to_repo()) == writes
    code, summary = server.next()                       # NOW+45: first clean run
    assert summary['open'] and len(rest.writes_to_repo()) == writes
    code, summary = server.next()                       # NOW+60: second clean run, resolved
    assert code == 0 and summary['open'] == [] and summary['transitions'] == [f'resolved:DATA_FLOW:{EPISODE}']
    assert rest.writes_to_repo()[writes:] == [('POST', f'/repos/{REPO}/issues/{number}/comments'),
                                              ('PATCH', f'/repos/{REPO}/issues/{number}')]
    assert (issue['state'], issue['state_reason'], issue['closed_by']['login']) == ('closed', 'completed', BOT)
    resolved = rest.bot_comments(number)[1]
    assert resolved.startswith(gh.tag_marker(EPISODE, 'resolved')) and 'Dauer: 1 h 0 min' in resolved
    code, summary = server.next()
    assert code == 0 and len(rest.writes_to_repo()) == writes + 2 and rest.incidents() == [number]

    sent = b'\n'.join(body for _, _, body in rest.requests).decode('utf-8')
    assert_no_secret(sent)
    assert_no_secret(server.local_text())
    assert all(TOKEN not in line for line in server.stdout)


# --- (d) authority closed ------------------------------------------------------------------------------------------

def test_closed_authority_means_zero_writes(tmp_path):
    server = Server(tmp_path, mode='on', authority_state='closed')
    server.red.append((NOW - 2 * MIN, NOW + 2 * RUN))
    code, summary = server.run()
    assert code == 0
    assert (summary['reporting'], summary['preflight'], summary['authority']) == ('revoked', 'authority closed',
                                                                                  'closed')
    assert server.github.writes_to_repo() == [] and server.github.incidents() == []
    assert summary['pending'] == 2 and len(server.pending()) == 2         # kept, nothing lost, nothing sent
    code, summary = server.next()
    assert code == 0 and summary['reporting'] == 'revoked' and server.github.writes_to_repo() == []
    assert summary['pending'] == 2 and summary['enqueued'] == 0


# --- owner acceptance steps on the server ----------------------------------------------------------------------------

def test_selftest_label_opens_one_issue_and_closes_it_after_removal(tmp_path):
    server = Server(tmp_path, mode='on')
    rest = server.github
    rest.issues[AUTHORITY]['labels'].append({'name': 'checkup:selftest'})
    code, summary = server.run()
    assert code == 0 and summary['transitions'] == [f'opened:SELFTEST:{EPISODE}']
    [number] = rest.incidents()
    assert [label['name'] for label in rest.issues[number]['labels']] == ['incident', 'source:tim-checkup', 'selftest']
    assert gh.parse_incident_marker(rest.issues[number]['body']) == ('SELFTEST', EPISODE, HOST)
    server.next()
    server.next()
    assert rest.incidents() == [number] and len(rest.bot_comments(number)) == 1
    rest.issues[AUTHORITY]['labels'] = [{'name': 'governance'}]
    server.next()
    code, summary = server.next()
    assert code == 0 and summary['transitions'] == [f'resolved:SELFTEST:{EPISODE}']
    assert rest.issues[number]['state'] == 'closed' and len(rest.bot_comments(number)) == 2
    assert rest.writes_to_repo()[0] == ('POST', f'/repos/{REPO}/issues') and rest.incidents() == [number]


def test_on_before_the_key_is_pasted_is_exit3_and_keeps_the_outbox(tmp_path):
    server = Server(tmp_path, mode='on')
    (server.credentials / 'github-app-key').write_text('', encoding='utf-8')     # the installer's placeholder
    server.red.append((NOW - 2 * MIN, NOW + 2 * RUN))
    code, summary = server.run()
    assert code == 3
    assert (summary['reporting'], summary['preflight'], summary['authority']) == ('key_missing', 'app key missing',
                                                                                  'unknown')
    assert server.github.requests == [] and server.signed == [] and len(server.pending()) == 2
    (server.credentials / 'github-app-key').write_text(KEY, encoding='utf-8')    # --app-key
    code, summary = server.next()
    assert code == 0 and summary['reporting'] == 'on' and summary['pending'] == 0
    [number] = server.github.incidents()
    assert server.github.issues[number]['title'] == 'Vorfall DATA_FLOW auf tim-core-01 seit 2026-10-07 03:15 UTC'


# --- (e) status ----------------------------------------------------------------------------------------------------

def tree(path: Path) -> dict:
    return {str(item.relative_to(path)): (item.stat().st_mtime_ns, item.stat().st_size, item.stat().st_mode)
            for item in sorted(path.rglob('*'))}


def status(server: Server, *arguments: str, now: datetime) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = tim_checkup.main(['status', *arguments], data_dir=server.data, now=now)
    return code, out.getvalue()


def test_status_shows_episodes_spool_minor_gaps_and_dry_run_actions(tmp_path):
    server = Server(tmp_path, mode='dry-run')
    server.red.append((NOW - 2 * MIN, NOW + RUN))
    server.run()
    with open(server.incidents_dir() / 'minor.jsonl', 'a', encoding='utf-8') as handle:
        handle.write(json.dumps({'at': NOW.isoformat(), 'class': 'NETWORK', 'rules': ['past_gap'], 'missing': 2,
                                 'first_missing': ['2026-10-07T03:01:00+00:00'], 'host': HOST}) + '\n')
    before = tree(server.data)
    code, text = status(server, '--since', '24h', now=NOW + 10 * MIN)
    assert code == 0
    assert tree(server.data) == before                  # status never writes
    assert 'Letzter Lauf: beendet 2026-10-07 03:15 UTC, Exit 0, Melden dry-run, Journal ok' in text
    assert 'Offene Episoden: 1' in text
    assert f'DATA_FLOW Episode {EPISODE}, aktuell DATA_FLOW, seit 2026-10-07 03:15 UTC, gemeldet: dry-run' in text
    assert 'Puffer: 0 offen, ältester Eintrag -' in text
    assert 'Kleine Lücken im Fenster (minor.jsonl): 1' in text and '2 min fehlen ab 2026-10-07 03:01 UTC' in text
    assert 'Dry-run im Fenster (dryrun.jsonl): 2 Schreibzugriffe wären erfolgt (comment 1, create_issue 1)' in text
    assert ('create_issue: Vorfall DATA_FLOW auf tim-core-01 seit 2026-10-07 03:15 UTC '
            '[incident, source:tim-checkup, priority:p1]') in text
    assert LITERAL_REMOVED not in text and 'Fehlschlagende' not in text            # no comment text on the terminal

    code, text = status(server, '--since', '30m', now=NOW + 2 * timedelta(hours=1))
    assert code == 0 and 'Dry-run im Fenster (dryrun.jsonl): 0 Schreibzugriffe' in text
    assert 'Kleine Lücken im Fenster (minor.jsonl): 0' in text and 'Offene Episoden: 1' in text
    for bad in ('24', '0h', 'abc', '24h;id', '24h\n', '-1h'):
        with pytest.raises(SystemExit) as stop:
            status(server, '--since', bad, now=NOW)
        assert stop.value.code == 2


def test_status_counts_the_pending_outbox_and_handles_a_fresh_install(tmp_path):
    server = Server(tmp_path, mode='on', authority_state='closed')
    server.red.append((NOW - 2 * MIN, NOW + RUN))
    server.run()
    code, text = status(server, now=NOW + 30 * MIN)
    assert code == 0 and 'Puffer: 2 offen (comment 1, open 1), ältester Eintrag 30 min' in text
    assert 'Melden revoked' in text
    empty = tmp_path / 'empty'
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert tim_checkup.main(['status'], data_dir=empty, now=NOW) == 0
    assert 'Noch kein Checkup-Lauf' in out.getvalue() and not empty.exists()


# --- state loss: adopt, never a second issue ------------------------------------------------------------------------

def test_lost_state_adopts_the_open_issue_and_still_closes_it(tmp_path):
    server = Server(tmp_path, mode='on')
    server.red.append((NOW - 2 * MIN, NOW + RUN))
    rest = server.github
    server.run()
    [number] = rest.incidents()
    for name in ('state.json', 'state.json.prev'):
        (server.incidents_dir() / name).unlink(missing_ok=True)
    code, summary = server.next()                       # NOW+15, still RED, state lost
    assert code == 0 and summary['state'] == 'lost' and summary['adopted'] == [f'DATA_FLOW/{EPISODE}']
    assert [item['episode'] for item in summary['open']] == [EPISODE]
    assert rest.incidents() == [number] and len(rest.bot_comments(number)) == 1
    for _ in range(3):                                  # NOW+30 window still RED, then two clean runs
        code, summary = server.next()
    assert summary['open'] == [] and rest.issues[number]['state'] == 'closed'
    assert rest.incidents() == [number] and len(rest.bot_comments(number)) == 2


# --- errors, settings, commands -------------------------------------------------------------------------------------

def test_invalid_settings_force_off_without_echoing_values(tmp_path):
    server = Server(tmp_path, mode='on')
    pasted = 'ghp_' + 'Lk2Jh7Gf4Ds9Aq1Wz6Er3Ty8Ui5Op0Mn'
    server.env['TIM_CHECKUP_REPORTER_LOGIN'] = pasted
    code, summary = server.run()
    assert code == 3                                    # asked for on, running off
    assert (summary['reporting'], summary['settings']) == ('off', 'TIM_CHECKUP_REPORTER_LOGIN invalid')
    assert server.github.requests == [] and pasted not in server.stdout[0]


def test_setup_and_run_failures_print_one_fixed_line(tmp_path, monkeypatch):
    server = Server(tmp_path, mode='on')
    secret_key = 'ghp_' + 'Pq9Wr2Et5Yu8Io1As4Df7Gh0Jk3Lz6Xc'
    bad = tmp_path / 'policy.json'
    bad.write_text(json.dumps({'version': 1, secret_key: 1}), encoding='utf-8')
    code, summary = server.run(policy_path=bad)
    assert code == 1
    assert summary == {'event': 'checkup_end', 'host': 'unknown', 'exit_code': 1, 'error': 'PolicyError',
                       'stage': 'policy', 'reporting': 'unknown', 'preflight': 'skipped',
                       'journal_access': 'unknown', 'open': []}
    assert secret_key not in server.stdout[-1]

    def explode(**kwargs):
        raise RuntimeError(f'boom {TOKEN} {DB_PASSWORD}')

    monkeypatch.setattr(checkup, 'run', explode)
    code, summary = server.run()
    assert code == 1 and (summary['error'], summary['stage'], summary['host']) == ('RuntimeError', 'run', HOST)
    assert_no_secret(server.stdout[-1])


def test_later_commands_and_root_are_refused(tmp_path, monkeypatch, capsys):
    for command, part in (('diagnose', 'PR-2'), ('watch', 'PR-3')):
        assert tim_checkup.main([command], data_dir=tmp_path / 'data') == 2
        assert part in capsys.readouterr().err
    monkeypatch.setattr(tim_checkup.os, 'geteuid', lambda: 0)
    assert tim_checkup.main(['run'], data_dir=tmp_path / 'data') == 1
    assert 'nicht als root' in capsys.readouterr().err and not (tmp_path / 'data').exists()
    with pytest.raises(SystemExit) as stop:
        tim_checkup.main(['repair'], data_dir=tmp_path / 'data')
    assert stop.value.code == 2


def test_script_runs_from_any_working_directory(tmp_path):
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONDONTWRITEBYTECODE': '1'}
    for argv, expected in ((['--help'], 0), (['diagnose'], 2), (['status', '--since', '1h'], 0)):
        result = subprocess.run([sys.executable, str(SCRIPT), *argv], cwd=tmp_path, env=env, capture_output=True,
                                text=True, timeout=60)
        assert result.returncode == expected, result.stderr
        assert 'Traceback' not in result.stdout + result.stderr
