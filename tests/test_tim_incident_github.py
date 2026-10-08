"""Incident reporter (design B, section 15): GitHub App identity, write guard, spool and delivery. No network:
GitHub is `FakeRest` behind the injectable transport, openssl is a fake runner, sockets are fakes or loopback."""
from __future__ import annotations

import base64
import dataclasses
import errno
import http.server
import json
import os
import re
import socket
import ssl
import stat
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from src.task_governance import CreateNotSent, GitHubError, MappingState, TaskRegistry, fingerprint_marker
from src.task_governance.create_authority import CreateNotAuthorized, authority_body
from src.task_governance.github_gateway import BODY_BEGIN, BODY_END, _NotSent
from src.tim_incident import github as gh
from src.tim_incident import github_app
from src.tim_incident.policy import CONTROL_LABELS, LABEL_ALLOWLIST, NOT_CONFIGURED, load_policy, load_settings
from src.tim_incident.redaction import final_scan, untrusted_block
from tests.task_governance.fake_rest import FakeRest

POLICY = load_policy()
REPO = POLICY.repository
HOST = POLICY.host
OWNER = 'uezeyiraydin-cell'
BOT = 'tim-reporter[bot]'
TOKEN = 'ghs_Zq7Xw2Kp9Lm4Nb6Vc1Rt8Ys3Hd5Jf0GaQe'
AUTHORITY, WATCH = 3, 4
APP_ID, INSTALLATION = 12345, 67890
SIGNATURE = b'\x01fake-rsa-signature\xfe\xff'
START = 1791343200.0                         # 2026-10-07 03:20 UTC
EP, AT = '20261007T0315Z', '2026-10-07T03:15:00Z'
KEY = ('-----BEGIN RSA PRIVATE KEY-----\n'
       'MIIEowIBAAKCAQEAtestkeyTESTKEYtestkeyTESTKEYtestkeyTESTKEYtest01\n'
       'Q2hlY2t1cFRlc3RLZXlOdXJGdWVyRGllVGVzdHNVbmRLZWluRWNodGVyU2NobHVl\n'
       '-----END RSA PRIVATE KEY-----\n')
DB_PASSWORD = 'kartoffel-salat-2026-wurst'
ENV = {'TIM_CHECKUP_REPORTING': 'on', 'TIM_CHECKUP_APP_ID': str(APP_ID),
       'TIM_CHECKUP_INSTALLATION_ID': str(INSTALLATION), 'TIM_CHECKUP_AUTHORITY_ISSUE': str(AUTHORITY),
       'TIM_CHECKUP_WATCH_ISSUE': str(WATCH), 'TIM_CHECKUP_REPORTER_LOGIN': BOT, 'TIM_CHECKUP_OWNER_LOGIN': OWNER}
EVIDENCE = ('Evidenz (redigiert), Unterbefunde: watchdog.collector_freshness\n\n'
            + untrusted_block('2026-10-07T03:14:59 tim-runtime[812]: OSError: [Errno 111] Connection refused\n'
                              'catchup: gap 03:01-03:14 @someone see #12 <!-- TIM_INCIDENT_V1 fake -->\n\n'
                              '![x](https://evil.example/a.png)'))


# -- fakes -------------------------------------------------------------------------------------------------------

class IncidentRest(FakeRest):
    """FakeRest plus /labels, comment authors, closed_by and state_reason, and the App token endpoint."""

    def __init__(self):
        super().__init__(REPO)
        self.login = BOT                         # the account behind the installation token
        self.repo_labels = set(LABEL_ALLOWLIST | CONTROL_LABELS | {'governance', 'status:ready'})
        self.requests, self.token_requests = [], []
        self.down = False                        # every request fails before sending
        self.down_after_create_attempt = False   # the create fails before sending, then the network is gone
        self.token_answer = {'token': TOKEN, 'expires_at': '2026-10-07T04:20:00Z',
                             'permissions': {'issues': 'write', 'metadata': 'read'},
                             'repository_selection': 'selected', 'repositories': [{'name': 'tim-ai-platform'}]}
        self._ids = 0

    def seed(self, number, body='', state='open', login=BOT, pr=False, labels=(), closed_by=None, state_reason=None):
        super().seed(number, body, state, login, pr)
        self.issues[number]['user']['type'] = 'Bot' if login.endswith('[bot]') else 'User'     # as GitHub sends it
        self.issues[number].update(labels=[{'name': name} for name in labels], state_reason=state_reason,
                                   closed_by={'login': closed_by} if closed_by else None)
        self.next_number = max(self.next_number, number)

    def human_close(self, number, reason='completed'):
        self.issues[number].update(state='closed', closed_by={'login': OWNER}, state_reason=reason)

    def set_labels(self, number, names):
        self.issues[number]['labels'] = [{'name': name} for name in names]

    def labels_of(self, number):
        return [label['name'] for label in self.issues[number]['labels']]

    def repo_writes(self):
        return [(method, path) for method, path, _ in self.calls if method != 'GET' and path.startswith('/repos/')]

    def bot_comments(self, number):
        return [c['body'] for c in self.comments.get(number, []) if (c.get('user') or {}).get('login') == BOT]

    def __call__(self, method, url, headers, body, timeout):
        parsed = urlparse(url)
        path = parsed.path
        self.requests.append((method, path, dict(headers), body))
        if self.down:
            raise _NotSent()
        base = f'/repos/{self.repo}'
        if method == 'POST' and path == f'{base}/issues' and self.down_after_create_attempt:
            self.calls.append((method, path, timeout))
            self.down = True
            raise _NotSent()
        handler = self._handler(method, path, base)
        if handler is None:
            return super().__call__(method, url, headers, body, timeout)
        self.calls.append((method, path, timeout))
        for (m, pattern), outcome in self.fail.items():
            if m == method and re.search(pattern, path):
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome, b'{"message": "SECRET-DETAIL"}'
        return handler(parsed, path, json.loads(body) if body else None, headers)

    def _handler(self, method, path, base):
        if method == 'POST' and re.fullmatch(r'/app/installations/\d+/access_tokens', path):
            return self._token
        if method == 'GET' and path == f'{base}/labels':
            return self._list_labels
        if method == 'POST' and re.fullmatch(re.escape(base) + r'/issues/\d+/labels', path):
            return self._add_labels
        if method == 'POST' and re.fullmatch(re.escape(base) + r'/issues/\d+/comments', path):
            return self._add_comment
        if method == 'PATCH' and re.fullmatch(re.escape(base) + r'/issues/\d+', path):
            return self._patch
        return None

    @staticmethod
    def _number(path):
        return int(re.search(r'/issues/(\d+)', path).group(1))

    def _token(self, parsed, path, payload, headers):
        self.token_requests.append((dict(headers), payload))
        return 201, json.dumps(self.token_answer).encode()

    def _list_labels(self, parsed, path, payload, headers):
        query = parse_qs(parsed.query)
        per, page = int(query['per_page'][0]), int(query['page'][0])
        items = [{'name': name} for name in sorted(self.repo_labels)]
        return 200, json.dumps(items[(page - 1) * per: page * per]).encode()

    def _add_labels(self, parsed, path, payload, headers):
        item = self.issues[self._number(path)]
        for name in payload['labels']:
            if name not in [label['name'] for label in item['labels']]:
                item['labels'].append({'name': name})
        return 200, json.dumps(item['labels']).encode()

    def _add_comment(self, parsed, path, payload, headers):
        self._ids += 1
        comment = {'id': self._ids, 'body': payload['body'], 'user': {'login': self.login}}
        self.comments.setdefault(self._number(path), []).append(comment)
        return 201, json.dumps(comment).encode()

    def _patch(self, parsed, path, payload, headers):
        number = self._number(path)
        if number not in self.issues:
            return 404, b'{}'
        item = self.issues[number]
        if payload.get('state') == 'closed':
            item.update(state='closed', closed_by={'login': self.login}, state_reason=payload.get('state_reason') or 'completed')
        elif payload.get('state') == 'open':
            item.update(state='open', closed_by=None, state_reason='reopened')
        item.update({key: value for key, value in payload.items() if key not in ('state', 'state_reason')})
        return 200, json.dumps(item).encode()


class Clock:
    def __init__(self, now=START):
        self.now = float(now)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Openssl:
    def __init__(self, code=0, out=SIGNATURE):
        self.code, self.out, self.calls = code, out, []

    def __call__(self, argv, *, input, timeout):
        self.calls.append((list(argv), input, timeout))
        return SimpleNamespace(returncode=self.code, stdout=self.out, stderr=b'openssl said something')


def body_for(cls='DATA_FLOW', episode=EP, at='2026-10-07 03:15 UTC'):
    return (f'## Vorfall {cls} auf {HOST}\n'
            f'cc @{OWNER}\n'
            f'- Erkannt: {at} (Checkup); fehlschlagende Prüfungen: candle_freshness, gap_last_60m\n'
            '- Unterbefunde: watchdog.collector_freshness, watchdog.data_age\n'
            '- Commit /opt/tim: abc1234 (aus .git gelesen)\n'
            '- Einordnung (feste Regel): ops\n'
            f'- Behebung: {POLICY.classes[cls].remedy}, siehe docs/TIM_CHECKUP.md. '
            'Pipeline nur nach Label status:ready durch den Inhaber.\n'
            '- Evidenz und Qwen-Diagnose (ungeprüft) stehen nur in Kommentaren.\n'
            f'{gh.incident_marker(cls, episode, HOST)}')


def entry(kind, cls='DATA_FLOW', episode=EP, at=AT, active=True, **extra):
    data = {'v': 1, 'kind': kind, 'episode': episode, 'class': cls, 'host': HOST, 'at': at, 'active': active}
    if kind == 'open':
        data.update(title=f'Vorfall {cls} auf {HOST}', body=body_for(cls, episode), labels=list(POLICY.classes[cls].issue_labels))
    elif kind == 'status_line':
        data['status'] = 'weiterhin aktiv'
    elif kind == 'fields':
        data.update(fields={'fix_kind': 'unknown', 'locations': []}, labels=[])
    else:
        data.update(tag={'comment': 'evidence', 'resolve': 'resolved', 'reopen': 'reopen-1'}[kind],
                    text={'comment': EVIDENCE, 'resolve': 'Erholt nach 2 sauberen Läufen, Dauer 45 min, Commit abc1234.',
                          'reopen': 'Wieder aktiv innerhalb von 2 h, dieselbe Episode.'}[kind])
    data.update(extra)
    return data


def b64url_decode(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


class World:
    """One server: data dir, credentials, fake GitHub, clock; `run()` is one checkup run of the reporter."""

    def __init__(self, root: Path, *, env=None, policy=POLICY, authority=True, authority_login=OWNER,
                 authority_labels=(), registry_for_authority=None):
        self.root, self.data, self.creds = root, root / 'data', root / 'creds'
        self.creds.mkdir(parents=True)
        (self.creds / 'github-app-key').write_text(KEY, encoding='utf-8')
        (self.data / 'incidents').mkdir(parents=True)
        registry = TaskRegistry(str(self.data / 'incidents' / 'registry.sqlite'))
        self.registry_id = registry.registry_id
        registry.close()
        self.rest, self.clock, self.policy, self.openssl = IncidentRest(), Clock(), policy, Openssl()
        self.env = {**ENV, **(env or {})}
        if authority:
            self.rest.seed(AUTHORITY, authority_body(registry_for_authority or self.registry_id, REPO),
                           login=authority_login, labels=authority_labels)
        self.rest.seed(WATCH, 'Außenwache', login=OWNER)
        self.spool = gh.Spool(self.data / 'incidents' / 'outbox', clock=self.clock)
        self.reporter = self.controls = None

    def make(self):
        return gh.build_reporter(load_settings(self.env), self.policy, data_dir=self.data, credentials_dir=self.creds,
                                 transport=self.rest, runner=self.openssl, clock=self.clock, monotonic=lambda: 0.0)

    def run(self, *entries, advance=0.0) -> gh.DeliveryReport:
        """Like checkup.run: read the controls, then enqueue (with the known secrets), then deliver."""
        self.clock.advance(advance)
        self.reporter = self.make()
        self.controls = self.reporter.read_controls()
        self.spool = gh.Spool(self.data / 'incidents' / 'outbox', literals=self.reporter.literals, clock=self.clock)
        for item in entries:
            self.spool.enqueue(item)
        return self.reporter.deliver(self.spool, deadline=240.0)

    def incidents(self):
        return [n for n in sorted(self.rest.issues) if n not in (AUTHORITY, WATCH)]

    def done(self):
        notes = {}
        for path in sorted((self.data / 'incidents' / 'outbox' / 'done').glob('*.json')):
            data = json.loads(path.read_text(encoding='utf-8'))
            notes[path.stem] = data['done']['note']
        return notes

    def state(self):
        return json.loads((self.data / 'incidents' / 'delivery.json').read_text(encoding='utf-8'))


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def gateway(rest, **kwargs):
    return gh.IncidentGateway(REPO, TOKEN, reporter_login=BOT, owner_login=OWNER, authority_issue=AUTHORITY,
                              watch_issue=WATCH, transport=rest, **kwargs)


def marked(cls='DATA_FLOW', episode=EP):
    request = gh.task_request(cls, episode, HOST, 'Vorfall', body_for(cls, episode))
    return f'{BODY_BEGIN}\n{request.body}\n{BODY_END}\n\n{fingerprint_marker(request.fingerprint)}'


# -- B.4 basics: dedupe, order, uncertain creates --------------------------------------------------------------

def test_two_runs_one_issue(world):
    report = world.run(entry('open'), entry('comment'))
    assert (report.reporting, report.preflight, report.exit_code) == ('on', 'ok', 0)
    assert (report.delivered, report.pending) == (2, 0)
    [number] = world.incidents()
    issue = world.rest.issues[number]
    assert issue['user']['login'] == BOT and issue['title'] == f'Vorfall DATA_FLOW auf {HOST}'
    assert gh.parse_incident_marker(issue['body']) == ('DATA_FLOW', EP, HOST)
    assert fingerprint_marker(gh.task_request('DATA_FLOW', EP, HOST).fingerprint) in issue['body']
    assert world.rest.labels_of(number) == ['incident', 'source:tim-checkup', 'priority:p1']
    [comment] = world.rest.bot_comments(number)
    assert comment == f'{gh.tag_marker(EP, "evidence")}\n{EVIDENCE}'
    report = world.run(entry('open'), entry('comment'), advance=900)       # the checkup enqueues the same again
    assert report.delivered == 2 and world.incidents() == [number] and len(world.rest.bot_comments(number)) == 1
    assert world.reporter.registry().get(gh.task_request('DATA_FLOW', EP, HOST).fingerprint).github_issue_number == number


def test_network_down_spools_then_delivers_in_order(world):
    rest = world.rest
    rest.down = True
    a_open, a_evidence = entry('open'), entry('comment')
    b_open = entry('open', cls='BACKUP', episode='20261007T0316Z', at='2026-10-07T03:16:00Z')
    a_resolve = entry('resolve', active=False)
    report = world.run(a_open, a_evidence, b_open, a_resolve)
    assert (report.reporting, report.preflight, report.exit_code, report.pending) == \
        ('network_down', 'github not reachable', 0, 4)
    assert rest.calls == [] and world.incidents() == []
    report = world.run(advance=61 * 60)                                     # still down after an hour: alarm
    assert (report.reporting, report.exit_code, report.pending) == ('network_down', 3, 4)
    rest.down = False
    rest.fail[('POST', r'/issues/\d+/comments$')] = _NotSent()              # gone again right before a comment
    report = world.run(advance=900)
    assert report.reporting == 'network_down' and report.pending == 3       # the first open went out, then stop
    del rest.fail[('POST', r'/issues/\d+/comments$')]
    report = world.run(advance=900)
    assert (report.reporting, report.exit_code, report.pending) == ('on', 0, 0)
    a, b = world.incidents()
    assert rest.repo_writes() == [
        ('POST', f'/repos/{REPO}/issues'), ('POST', f'/repos/{REPO}/issues/{a}/labels'),
        ('POST', f'/repos/{REPO}/issues/{a}/comments'),                    # refused before sending, then sent
        ('POST', f'/repos/{REPO}/issues/{a}/comments'),
        ('POST', f'/repos/{REPO}/issues'), ('POST', f'/repos/{REPO}/issues/{b}/labels'),
        ('POST', f'/repos/{REPO}/issues/{a}/comments'), ('PATCH', f'/repos/{REPO}/issues/{a}'),
    ]
    assert len(rest.bot_comments(a)) == 2 and rest.issues[a]['state'] == 'closed'
    assert 'Erkannt: 2026-10-07 03:15 UTC' in rest.issues[a]['body']        # the original detection time


def test_lost_create_reply_never_duplicates(world):
    rest = world.rest
    rest.lose_create_reply = True
    report = world.run(entry('open'))
    assert report.reporting == 'on' and report.pending == 1 and len(world.incidents()) == 1   # created, answer lost
    fp = gh.task_request('DATA_FLOW', EP, HOST).fingerprint
    row = world.reporter.registry().get(fp)
    assert row.state is MappingState.CLAIMED and row.create_intent
    rest.lose_create_reply = False
    rest.fail.clear()
    report = world.run(advance=900)
    assert report.pending == 0 and len(world.incidents()) == 1
    [number] = world.incidents()
    assert world.reporter.registry().get(fp).github_issue_number == number
    assert 'priority:p1' in rest.labels_of(number)
    world.run(entry('open'), advance=900)
    assert len(world.incidents()) == 1 and [w for w in rest.repo_writes() if w[1].endswith('/issues')] == \
        [('POST', f'/repos/{REPO}/issues')]


class _FakeConnection:
    behaviour = {}
    sent = []

    def __init__(self, host, port, timeout=None):
        self.sock = None

    def connect(self):
        action = self.behaviour['connect']
        if isinstance(action, float):
            time.sleep(action)
            return
        if action is not None:
            raise action

    def request(self, method, target, body=None, headers=None):
        self.sent.append((method, target))

    def getresponse(self):
        error = self.behaviour.get('response')
        if error is not None:
            raise error
        return SimpleNamespace(status=201, read=lambda n: b'{"number": 5, "state": "open"}')

    def close(self):
        pass


@pytest.mark.parametrize('error', [
    OSError(errno.EHOSTUNREACH, 'No route to host'), OSError(errno.ENETUNREACH, 'Network is unreachable'),
    TimeoutError('timed out'), ssl.SSLError(1, 'handshake failure'), ConnectionRefusedError(),
    socket.gaierror(-2, 'Name or service not known'), 0.6,      # 0.6: connect still running when the deadline hits
], ids=['ehostunreach', 'enetunreach', 'connect-timeout', 'tls', 'refused', 'dns', 'deadline-while-connecting'])
def test_presend_connect_errors_are_not_sent(monkeypatch, error):
    monkeypatch.setattr(gh, 'HTTPSConnection', _FakeConnection)
    monkeypatch.setattr(_FakeConnection, 'behaviour', {'connect': error})
    monkeypatch.setattr(_FakeConnection, 'sent', [])
    with pytest.raises(_NotSent):
        gh.incident_transport('POST', 'https://api.github.com/repos/o/r/issues', {}, b'{}', 0.2)
    gw = gh.IncidentGateway(REPO, TOKEN, reporter_login=BOT, owner_login=OWNER, authority_issue=AUTHORITY,
                            request_timeout=0.2, max_create_seconds=0.2)
    request = gh.task_request('DATA_FLOW', EP, HOST, 'Vorfall', body_for())
    with pytest.raises(CreateNotSent) as caught:
        gw.create_issue(request, request.fingerprint, timeout=0.2)
    assert not isinstance(caught.value, (gh.CreateRefused, gh.CreateRejected))
    with pytest.raises(gh.NetworkDown):
        gw.get_issue(5)
    time.sleep(0.6 if isinstance(error, float) else 0)
    assert _FakeConnection.sent == []                       # nothing was ever sent, not even after the deadline


def test_a_failure_after_sending_stays_uncertain(monkeypatch):
    monkeypatch.setattr(gh, 'HTTPSConnection', _FakeConnection)
    monkeypatch.setattr(_FakeConnection, 'behaviour', {'connect': None, 'response': ConnectionResetError()})
    monkeypatch.setattr(_FakeConnection, 'sent', [])
    gw = gh.IncidentGateway(REPO, TOKEN, reporter_login=BOT, owner_login=OWNER, authority_issue=AUTHORITY)
    request = gh.task_request('DATA_FLOW', EP, HOST, 'Vorfall', body_for())
    with pytest.raises(GitHubError) as caught:
        gw.create_issue(request, request.fingerprint, timeout=1)
    assert not isinstance(caught.value, CreateNotSent) and _FakeConnection.sent == [('POST', f'/repos/{REPO}/issues')]
    assert 'failed: ConnectionResetError' in str(caught.value)


def test_incident_transport_on_a_loopback_server():
    paths = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            paths.append(self.path)
            if self.path == '/drop':
                self.close_connection = True
                return                                       # request read, no answer: uncertain
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        assert gh.incident_transport('GET', f'{url}/x?a=1', {}, None, 2) == (200, b'{"ok": true}')
        with pytest.raises(GitHubError) as caught:
            gh.incident_transport('GET', f'{url}/drop', {}, None, 2)
        assert not isinstance(caught.value, CreateNotSent)
        with pytest.raises(GitHubError):
            gh.incident_transport('GET', 'http://example.com/x', {}, None, 2)        # plain http only on loopback
        assert paths == ['/x?a=1', '/drop']
    finally:
        server.shutdown()
        server.server_close()


def test_create_that_never_left_is_released_once_the_network_is_back(world):
    rest = world.rest
    rest.down_after_create_attempt = True
    report = world.run(entry('open'))
    assert report.reporting == 'network_down' and report.pending == 1 and world.incidents() == []
    fp = gh.task_request('DATA_FLOW', EP, HOST).fingerprint
    row = world.reporter.registry().get(fp)
    assert row.state is MappingState.CLAIMED and row.create_intent      # ensure_task could not verify: claim kept
    assert world.state()['not_sent'] == {fp: row.claim_token}
    rest.down = rest.down_after_create_attempt = False
    report = world.run(advance=900)
    assert report.reporting == 'on' and report.pending == 0 and len(world.incidents()) == 1
    reasons = [i['reason'] for i in world.reporter.registry().incidents(fp)]
    assert 'CREATE_UNCERTAIN' not in reasons


def test_create_uncertain_waits_for_the_confirm_file(world):
    rest = world.rest
    rest.fail[('POST', r'/issues$')] = TimeoutError('answer lost')       # nothing created, but nobody can know
    world.run(entry('open'))
    report = world.run(advance=900)
    assert report.pending == 1 and any('create uncertain' in note for note in report.notes)
    assert not any(note.startswith('confirm-not-created: sudo') for note in report.notes)
    report = world.run(advance=3700)
    [line] = [note for note in report.notes if note.startswith('confirm-not-created: sudo')]
    marker = world.data / 'incidents' / f'confirm-not-created.DATA_FLOW.{EP}'       # class and episode
    assert str(marker) in line and 'systemctl start tim-checkup.service' in line
    rest.fail.clear()
    report = world.run(advance=900)
    assert world.incidents() == [] and report.pending == 1                  # no file, no create
    marker.write_text('', encoding='utf-8')
    report = world.run(advance=900)
    assert report.pending == 0 and len(world.incidents()) == 1
    assert not marker.exists() and marker.with_name(marker.name + '.used').exists()


def test_adopt_only_entries_never_create(world):
    report = world.run(entry('open', adopt_only=True))
    assert report.pending == 0 and world.incidents() == []
    assert list(world.done().values()) == ['adopt only: no issue found']
    episode = '20261006T2200Z'
    world.rest.seed(9, marked('RUNTIME', episode), login=BOT)               # the issue of a state that was lost
    report = world.run(entry('open', cls='RUNTIME', episode=episode, adopt_only=True), advance=900)
    assert world.incidents() == [9] and report.pending == 0
    assert world.reporter.registry().get(gh.task_request('RUNTIME', episode, HOST).fingerprint).github_issue_number == 9
    assert world.reporter.open_incidents() == [{'number': 9, 'class': 'RUNTIME', 'episode': episode, 'host': HOST,
                                                 'labels': ['incident', 'source:tim-checkup', 'priority:p1']}]


# -- authority: emergency stop and phone controls ---------------------------------------------------------------

def test_no_authority_no_create_spool_kept(tmp_path):
    missing = World(tmp_path / 'missing', authority=False)
    report = missing.run(entry('open'))
    assert (report.reporting, report.preflight, report.exit_code, report.pending) == \
        ('authority_missing', 'authority missing', 0, 1)
    assert missing.controls.authority == 'missing' and missing.rest.repo_writes() == []
    other = World(tmp_path / 'other', registry_for_authority='f' * 32)       # designates another registry
    report = other.run(entry('open'))
    assert (report.reporting, report.preflight, report.pending) == ('authority_missing', 'authority marker invalid', 1)
    assert other.rest.repo_writes() == []
    race = World(tmp_path / 'race')                                         # valid when read, closed before the create
    race.spool.enqueue(entry('open'))
    reporter = race.make()
    assert reporter.read_controls().open
    race.rest.issues[AUTHORITY]['state'] = 'closed'
    report = reporter.deliver(race.spool, deadline=240.0)
    assert report.pending == 1 and race.incidents() == [] and race.rest.repo_writes() == []
    assert any('create not authorized' in note for note in report.notes)


def test_closed_authority_blocks_all_writes(world):
    world.run(entry('open'))
    [number] = world.incidents()
    before = list(world.rest.repo_writes())
    world.rest.issues[AUTHORITY]['state'] = 'closed'
    report = world.run(entry('comment'), entry('status_line'), entry('resolve', active=False),
                       entry('open', cls='DISK', episode='20261007T0400Z'), advance=900)
    assert (report.reporting, report.exit_code, report.pending) == ('revoked', 0, 4)
    assert world.rest.repo_writes() == before and world.rest.bot_comments(number) == []
    assert world.controls.authority == 'closed' and world.state()['quiet'] is True
    report = world.run(advance=7200)                                        # revoked is never an alarm
    assert (report.reporting, report.exit_code) == ('revoked', 0)


def test_bot_opened_authority_not_trusted(tmp_path):
    world = World(tmp_path, authority_login=BOT)
    report = world.run(entry('open'))
    assert (report.reporting, report.preflight) == ('authority_missing', 'authority not opened by the owner')
    assert world.incidents() == [] and world.rest.repo_writes() == []
    gw = gateway(world.rest)
    with pytest.raises(CreateNotAuthorized):                                 # the bot never counts, whatever is passed
        gh.OwnerOnlyAuthority(AUTHORITY, OWNER).check(gw, world.registry_id, [BOT, OWNER])
    world.rest.issues[AUTHORITY]['user']['login'] = OWNER
    gh.OwnerOnlyAuthority(AUTHORITY, OWNER).check(gw, world.registry_id, [BOT])


def test_silence_and_pause_labels(tmp_path):
    world = World(tmp_path, authority_labels=('checkup:silence',))
    report = world.run(entry('open'), entry('comment'))
    assert (report.reporting, report.exit_code, report.pending) == ('silenced', 0, 2)
    assert world.controls.silenced and world.rest.repo_writes() == []
    world.rest.set_labels(AUTHORITY, ['checkup:pause-qwen'])
    report = world.run(advance=900)
    assert world.controls.pause_qwen and not world.controls.silenced     # PR-2 seam: read, no effect on reporting
    assert (report.reporting, report.pending) == ('on', 0) and len(world.incidents()) == 1


def test_reenable_summarizes_resolved_episodes(tmp_path):
    world = World(tmp_path, authority_labels=('checkup:silence',))
    a_open, a_resolve = entry('open'), entry('resolve', active=False)
    b = dict(cls='BACKUP', episode='20261007T0330Z', at='2026-10-07T03:30:00Z')
    report = world.run(a_open, a_resolve, entry('open', **b), entry('comment', **b))
    assert report.reporting == 'silenced' and report.pending == 4
    world.rest.set_labels(AUTHORITY, [])
    report = world.run(advance=900)
    assert report.reporting == 'on' and report.pending == 0
    [summary] = world.rest.bot_comments(AUTHORITY)
    assert summary.startswith('<!-- TIM_INCIDENT_SUMMARY id=') and f'DATA_FLOW, Episode {EP}' in summary
    assert 'kein Issue angelegt' in summary and 'BACKUP' not in summary and not final_scan(summary.split('\n', 1)[1])
    [number] = world.incidents()                                             # only the still active episode
    assert gh.parse_incident_marker(world.rest.issues[number]['body'])[0] == 'BACKUP'
    assert sorted(world.done().values()).count('summarized') == 2
    world.rest.issues[AUTHORITY]['state'] = 'closed'                        # emergency stop, then on again
    world.run(advance=900)
    world.rest.issues[AUTHORITY]['state'] = 'open'
    world.run(advance=900)
    assert len(world.rest.bot_comments(AUTHORITY)) == 1                     # nothing resolved meanwhile: no summary
    assert world.state()['quiet'] is False


# -- no push flood ------------------------------------------------------------------------------------------------

def test_rate_and_comment_limits(tmp_path):
    opens = World(tmp_path / 'opens')
    episodes = [f'20261007T03{minute:02d}Z' for minute in range(10, 15)]
    report = opens.run(*[entry('open', episode=episode) for episode in episodes])
    assert len(opens.incidents()) == 3 and report.pending == 2 and report.exit_code == 0
    assert any('new issue limit reached' in note for note in report.notes)
    report = opens.run(advance=3601)
    assert len(opens.incidents()) == 5 and report.pending == 0

    comments = World(tmp_path / 'comments')
    notes = [entry('comment', tag=f'note-{n}', text=f'Ereignis {n}: weiterhin rot.') for n in range(1, 7)]
    report = comments.run(entry('open'), *notes)
    [number] = comments.incidents()
    assert len(comments.rest.bot_comments(number)) == 4 and report.pending == 0      # 4 per incident and day
    assert 'Kommentargrenze erreicht' in comments.rest.issues[number]['body']
    comments.run(entry('comment', tag='note-7', text='Ereignis 7.'), advance=24 * 3600 + 60)
    assert len(comments.rest.bot_comments(number)) == 5                              # a new day

    changed = World(tmp_path / 'changed')
    steps = [entry('comment', tag=f'changed-{n}', text=f'Schwerer geworden, Schritt {n}.') for n in range(1, 6)]
    changed.run(entry('open'), *steps[:3])
    changed.run(*steps[3:], advance=25 * 3600)
    [number] = changed.incidents()
    assert len(changed.rest.bot_comments(number)) == 3                               # 3 CHANGED per episode

    budget = World(tmp_path / 'budget', policy=dataclasses.replace(
        POLICY, rate_limits=dataclasses.replace(POLICY.rate_limits, writes_per_run=4)))
    report = budget.run(entry('open'), entry('comment'), entry('open', cls='DISK', episode='20261007T0320Z'))
    assert report.writes <= 4 and report.pending >= 1
    while report.pending:
        report = budget.run(advance=900)
        assert report.writes <= 4
    assert len(budget.incidents()) == 2


def test_flapping_bounded_notifications(world):
    world.run(entry('open'), entry('comment'))
    [number] = world.incidents()
    for n in range(1, 6):
        world.run(entry('resolve', tag=f'resolved-{n}', active=False), advance=1800)
        world.run(entry('reopen', tag=f'reopen-{n}'), advance=1800)
    world.run(entry('resolve', tag='resolved-6', active=False), advance=1800)
    assert world.incidents() == [number]                                    # one issue for the whole episode
    assert len(world.rest.bot_comments(number)) == POLICY.rate_limits.comments_per_incident_per_day
    issue = world.rest.issues[number]
    # evidence, resolved-1 (close), reopen-1 (reopen), resolved-2 (close): at the limit reopen-2 still reopens,
    # every later resolve keeps the issue open, so no more close/reopen pairs follow
    states = [payload.get('state') for method, path, _, payload in
              [(m, p, h, json.loads(b) if b else {}) for m, p, h, b in world.rest.requests]
              if method == 'PATCH' and path.endswith(f'/issues/{number}') and 'state' in payload]
    assert states == ['closed', 'open', 'closed', 'open']
    assert issue['state'] == 'open' and 'wegen der Kommentargrenze offen' in issue['body']
    assert not list((world.data / 'incidents' / 'outbox').glob('*.json'))
    assert set(world.state()['kept_open']) == {f'DATA_FLOW/{EP}'}
    world.run(advance=12 * 3600)
    assert issue['state'] == 'open'                                          # not a quiet day yet
    world.run(advance=12 * 3600 + 60)
    assert (issue['state'], issue['state_reason']) == ('closed', 'completed')
    assert world.rest.bot_comments(number)[-1].startswith(gh.tag_marker(EP, 'resolved-6-late'))
    assert 'schließt es jetzt' in world.rest.bot_comments(number)[-1] and world.state()['kept_open'] == {}
    world.run(advance=900)
    assert issue['state'] == 'closed' and len(world.rest.bot_comments(number)) == 5


def test_kept_open_issue_reopens_quietly(world):
    world.run(entry('open'), *[entry('comment', tag=f'note-{n}', text=f'Ereignis {n}.') for n in range(1, 5)])
    [number] = world.incidents()
    world.run(entry('resolve', active=False), advance=900)
    assert world.rest.issues[number]['state'] == 'open' and f'DATA_FLOW/{EP}' in world.state()['kept_open']
    world.run(entry('reopen', tag='reopen-1'), advance=900)
    assert world.state()['kept_open'] == {}                                  # active again: no late close
    world.run(advance=25 * 3600)
    assert world.rest.issues[number]['state'] == 'open'


def test_ongoing_is_status_line_not_comment(world):
    world.run(entry('open'))
    [number] = world.incidents()
    managed = world.rest.issues[number]['body']
    first = world.spool.enqueue(entry('status_line', at='2026-10-07T04:15:00Z'))
    assert world.spool.enqueue(entry('status_line', at='2026-10-07T04:30:00Z')) == first
    assert world.spool.enqueue(entry('status_line', at='2026-10-07T04:45:00Z')) == first      # coalesced
    [pending] = world.spool.pending()
    assert pending['count'] == 3
    world.run(advance=900)
    body = world.rest.issues[number]['body']
    assert world.rest.bot_comments(number) == []
    assert body.startswith(managed) and body.endswith(
        f'{gh.STATUS_BEGIN}\n- Stand 2026-10-07 04:45 UTC: weiterhin aktiv (3 Läufe zusammengefasst)\n{gh.STATUS_END}')
    writes = len(world.rest.repo_writes())
    world.run(entry('status_line', at='2026-10-07T05:45:00Z'), advance=3600)
    assert len(world.rest.repo_writes()) == writes and 'status line too soon' in world.done().values()
    world.run(entry('status_line', at='2026-10-08T06:00:00Z'), advance=25 * 3600)
    body = world.rest.issues[number]['body']
    assert body.count(gh.STATUS_BEGIN) == 1 and '- Stand 2026-10-08 06:00 UTC: weiterhin aktiv' in body
    assert world.rest.bot_comments(number) == []


# -- write guard ---------------------------------------------------------------------------------------------------

def test_write_guard_on_every_write():
    rest = IncidentRest()
    rest.seed(AUTHORITY, marked(), login=BOT)                    # even marked and by the bot: the number decides
    rest.seed(WATCH, marked(), login=BOT)
    rest.seed(10, marked(), login=OWNER)
    rest.seed(11, 'kein Marker', login=BOT)
    rest.seed(12, marked(), login=BOT, pr=True)
    rest.seed(13, marked(), login=BOT)
    rest.seed(14, marked() + '\n' + gh.incident_marker('DISK', EP, HOST), login=BOT)     # two markers
    gw = gateway(rest)
    request = gh.task_request('DATA_FLOW', EP, HOST, 'Vorfall', body_for())
    writes = {
        'add_labels': lambda n: gw.add_labels(n, ['incident']),
        'comment_once': lambda n: gw.comment_once(n, 'evidence', 'Evidenz.'),
        'close_incident': lambda n: gw.close_incident(n),
        'reopen_incident': lambda n: gw.reopen_incident(n),
        'set_status_line': lambda n: gw.set_status_line(n, '- Stand: weiterhin aktiv'),
        'update_issue': lambda n: gw.update_issue(n, request, 'x'),
        'mark_duplicate': lambda n: gw.mark_duplicate(n, 13),
        'reopen_issue': lambda n: gw.reopen_issue(n, request, 'x'),
    }
    for name, write in writes.items():
        for number in (AUTHORITY, WATCH, 10, 11, 12, 14, 99):
            with pytest.raises(gh.GuardError):
                write(number)
            assert rest.repo_writes() == [], (name, number)
    with pytest.raises(gh.GuardError):
        gw.comment_once(13, 'evidence', 'Evidenz.', episode='20261007T0400Z')         # another episode's issue
    with pytest.raises(gh.GuardError):
        gw.comment_once(13, 'Evidence!', 'Evidenz.')                                  # tags are fixed words
    with pytest.raises(gh.GuardError):
        gw.comment_once(13, 'evidence', f'ghp_{"a1B2" * 9}')                           # final scan before sending
    with pytest.raises(gh.CreateRefused):
        gw.create_issue(gh.task_request('DATA_FLOW', EP, HOST, 'x', 'ohne Marker'), request.fingerprint, timeout=5)
    assert rest.repo_writes() == []
    assert gw.comment_once(13, 'evidence', 'Evidenz.') is True and gw.comment_once(13, 'evidence', 'Anders.') is False
    rest.comments[13].insert(0, {'id': 99, 'body': gh.tag_marker(EP, 'other') + '\nvon jemand anderem',
                                 'user': {'login': OWNER}})
    assert gw.comment_once(13, 'other', 'Text.') is True               # a stranger's tagged comment does not count
    with pytest.raises(gh.GuardError):
        gw.post_summary([{'class': 'DATA_FLOW', 'episode': EP, 'at': AT, 'issue': None}])      # authority by the bot
    rest.issues[AUTHORITY]['user']['login'] = OWNER
    items = [{'class': 'DATA_FLOW', 'episode': EP, 'at': AT, 'issue': 13}]
    assert gw.post_summary(items) is True and gw.post_summary(items) is False
    assert rest.repo_writes() == [('POST', f'/repos/{REPO}/issues/13/comments')] * 2 + \
        [('POST', f'/repos/{REPO}/issues/{AUTHORITY}/comments')]


def test_close_only_own_marked_issue():
    rest = IncidentRest()
    rest.seed(10, marked(), login=OWNER)
    rest.seed(11, 'Ein normales Issue ohne Marker', login=BOT)
    rest.seed(12, marked(), login=BOT)
    gw = gateway(rest)
    for number in (10, 11):
        with pytest.raises(gh.GuardError):
            gw.close_incident(number)
        assert rest.issues[number]['state'] == 'open'
    assert gw.close_incident(12) is True and gw.close_incident(12) is False
    assert (rest.issues[12]['state'], rest.issues[12]['state_reason']) == ('closed', 'completed')
    assert rest.repo_writes() == [('PATCH', f'/repos/{REPO}/issues/12')]


def test_human_closed_episode_silent(world):
    world.run(entry('open'), entry('comment'))
    [number] = world.incidents()
    world.rest.human_close(number)
    writes = len(world.rest.repo_writes())
    report = world.run(entry('comment', tag='changed-1', text='Schwerer geworden.', commit='abc1234'),
                       entry('status_line'), entry('reopen', tag='reopen-1'), advance=900)
    assert report.pending == 0
    comments = world.rest.bot_comments(number)
    assert len(comments) == 2 and comments[1].startswith(gh.tag_marker(EP, 'human-closed'))
    assert 'auf Commit abc1234 noch aktiv' in comments[1] and 'von Hand geschlossen' in comments[1]
    assert len(world.rest.repo_writes()) == writes + 1 and world.rest.issues[number]['state'] == 'closed'
    world.run(entry('comment', tag='changed-2', text='Noch schwerer.'), entry('resolve', active=False), advance=900)
    assert len(world.rest.repo_writes()) == writes + 1                      # the episode stays silent
    assert list(world.done().values()).count('silent: closed by a person') >= 3


def test_reopen_only_if_closed_by_reporter(world):
    world.run(entry('open'), entry('resolve', active=False))
    [number] = world.incidents()
    issue = world.rest.issues[number]
    assert (issue['state'], issue['closed_by']['login'], issue['state_reason']) == ('closed', BOT, 'completed')
    world.run(entry('reopen', tag='reopen-1'), advance=1800)
    assert issue['state'] == 'open' and world.rest.bot_comments(number)[-1].startswith(gh.tag_marker(EP, 'reopen-1'))
    world.rest.human_close(number, reason='not_planned')
    world.run(entry('reopen', tag='reopen-2'), advance=1800)
    assert issue['state'] == 'closed' and issue['closed_by']['login'] == OWNER     # a person's close stands
    gw = gateway(world.rest)
    assert gw.reopen_incident(number) is False
    issue.update(closed_by={'login': BOT}, state_reason='not_planned')
    assert gw.reopen_incident(number) is False                                     # only "completed" is ours


def test_403_twice_forbidden_exit3(world):
    world.run(entry('open'))
    world.rest.fail[('POST', r'/comments$')] = 403
    report = world.run(entry('comment'), advance=900)
    assert (report.reporting, report.exit_code, report.pending) == ('forbidden', 0, 1)
    posts = len(world.rest.repo_writes())
    report = world.run(advance=600)                                         # paused: not even an attempt
    assert (report.reporting, report.exit_code) == ('forbidden', 0) and len(world.rest.repo_writes()) == posts
    assert report.preflight == 'github forbidden'
    report = world.run(advance=1300)                                        # pause over, refused again
    assert (report.reporting, report.exit_code) == ('forbidden', 3)
    world.rest.fail.clear()
    report = world.run(advance=1900)
    assert (report.reporting, report.exit_code, report.pending) == ('on', 0, 0)
    assert world.state()['forbidden_strikes'] == 0
    world.rest.fail[('POST', r'/comments$')] = 429
    report = world.run(entry('comment', tag='changed-1', text='Schwerer.'), advance=900)
    assert (report.reporting, report.exit_code) == ('rate_limited', 0)
    report = world.run(advance=600)
    assert report.reporting == 'rate_limited' and world.state()['pause']['kind'] == 'rate_limited'


def test_401_token_invalid(tmp_path):
    world = World(tmp_path / 'mint')
    world.rest.fail[('POST', r'/access_tokens$')] = 401
    report = world.run(entry('open'))
    assert (report.reporting, report.preflight, report.exit_code, report.pending) == \
        ('token_invalid', 'token invalid', 3, 1)
    assert world.controls.authority == 'unknown' and world.rest.repo_writes() == []
    later = World(tmp_path / 'later')
    later.run(entry('open'))
    later.rest.fail[('POST', r'/comments$')] = 401
    report = later.run(entry('comment'), advance=900)
    assert (report.reporting, report.exit_code, report.pending) == ('token_invalid', 3, 1)


def test_label_allowlist_rejects_status_agent_p0(world):
    world.rest.seed(9, marked(), login=BOT)
    gw = gateway(world.rest)
    for label in ('status:ready', 'agent:claude', 'priority:p0', 'governance', 'checkup:silence', 'bug', 'Incident'):
        with pytest.raises(gh.LabelRefused):
            gw.add_labels(9, ['incident', label])
    assert world.rest.repo_writes() == []
    assert gw.add_labels(9, ['incident', 'incident']) == ['incident'] and gw.add_labels(9, ['incident']) == []
    world.run(entry('open', cls='SELFTEST', labels=['incident', 'source:tim-checkup', 'selftest', 'status:ready',
                                                     'agent:codex', 'priority:p0']))
    [number] = [n for n in world.incidents() if n != 9]
    assert world.rest.labels_of(number) == ['incident', 'source:tim-checkup', 'selftest']
    assert all(label in LABEL_ALLOWLIST for n in world.incidents() for label in world.rest.labels_of(n))


def test_body_frozen_after_status_ready(world):
    world.run(entry('open'))
    [number] = world.incidents()
    for labels in (['incident', 'status:ready'], ['incident', 'agent:codex']):
        world.rest.set_labels(number, labels)
        body = world.rest.issues[number]['body'] = world.rest.issues[number]['body'].replace(
            fingerprint_marker(gh.task_request('DATA_FLOW', EP, HOST).fingerprint), '')
        writes = len(world.rest.repo_writes())
        report = world.run(entry('status_line'), advance=25 * 3600)
        assert report.pending == 0 and 'body frozen' in world.done().values()
        gw = gateway(world.rest)
        assert gw.set_status_line(number, '- Stand: weiterhin aktiv') is False
        gw.update_issue(number, gh.task_request('DATA_FLOW', EP, HOST), 'marker missing')
        assert world.rest.issues[number]['body'] == body and len(world.rest.repo_writes()) == writes
    world.rest.set_labels(number, ['incident'])
    gateway(world.rest).update_issue(number, gh.task_request('DATA_FLOW', EP, HOST), 'marker missing')
    assert world.rest.issues[number]['body'].endswith(fingerprint_marker(gh.task_request('DATA_FLOW', EP, HOST).fingerprint))


# -- secrets -------------------------------------------------------------------------------------------------------

def test_app_jwt_and_token_never_logged(tmp_path, capsys):
    key = tmp_path / 'github-app-key'
    key.write_text(KEY, encoding='utf-8')
    rest, runner = IncidentRest(), Openssl()
    now = int(START)
    token = github_app.mint_installation_token(APP_ID, INSTALLATION, key, runner=runner, transport=rest, now=now)
    assert token == TOKEN
    [(argv, signing_input, timeout)] = runner.calls
    assert argv == ['openssl', 'dgst', '-sha256', '-sign', str(key), '-binary'] and timeout <= 30
    header, claims = (json.loads(b64url_decode(part)) for part in signing_input.decode().split('.'))
    assert header == {'alg': 'RS256', 'typ': 'JWT'}
    assert claims == {'iat': now - 60, 'exp': now + 540, 'iss': APP_ID}
    [(headers, payload)] = rest.token_requests
    jwt = headers['Authorization'].removeprefix('Bearer ')
    assert jwt == signing_input.decode() + '.' + base64.urlsafe_b64encode(SIGNATURE).rstrip(b'=').decode()
    assert payload == {'repositories': ['tim-ai-platform'], 'permissions': {'issues': 'write', 'metadata': 'read'}}
    assert rest.requests[0][1] == f'/app/installations/{INSTALLATION}/access_tokens'
    assert all(path != '/user' for _, path, _, _ in rest.requests)

    secrets = [jwt, TOKEN, *KEY.splitlines()[1:3]]
    failures = []
    for status in (401, 403, 404, 422, 429, 500):
        rest.fail[('POST', r'/access_tokens$')] = status
        with pytest.raises(github_app.AppTokenError) as caught:
            github_app.mint_installation_token(APP_ID, INSTALLATION, key, runner=runner, transport=rest, now=now)
        failures.append(caught.value)
    assert [error.kind for error in failures] == ['token_invalid', 'forbidden', 'token_invalid', 'token_invalid',
                                                  'rate_limited', 'network_down']
    rest.fail.clear()

    def leaky(method, url, headers, body, timeout):
        raise RuntimeError(f'cannot send {headers}')
    with pytest.raises(github_app.AppTokenError) as caught:
        github_app.mint_installation_token(APP_ID, INSTALLATION, key, runner=runner, transport=leaky, now=now)
    failures.append(caught.value)
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    rest.token_answer = dict(rest.token_answer, permissions={'issues': 'write', 'metadata': 'read', 'contents': 'write'})
    with pytest.raises(github_app.AppTokenError) as caught:
        github_app.mint_installation_token(APP_ID, INSTALLATION, key, runner=runner, transport=rest, now=now)
    assert caught.value.kind == 'token_invalid'
    failures.append(caught.value)
    with pytest.raises(github_app.AppTokenError) as caught:
        github_app.mint_installation_token(APP_ID, INSTALLATION, key, runner=Openssl(code=1, out=b''), transport=rest,
                                           now=now)
    assert caught.value.kind == 'key_missing' and 'openssl said' not in str(caught.value)
    failures.append(caught.value)
    calls = len(runner.calls)
    for missing in (tmp_path / 'nothing-here', None):
        with pytest.raises(github_app.AppTokenError) as caught:
            github_app.mint_installation_token(APP_ID, INSTALLATION, missing, runner=runner, transport=rest, now=now)
        assert caught.value.kind == 'key_missing'
    empty = tmp_path / 'empty-key'
    empty.write_text('\n', encoding='utf-8')
    with pytest.raises(github_app.AppTokenError) as caught:
        github_app.mint_installation_token(APP_ID, INSTALLATION, empty, runner=runner, transport=rest, now=now)
    assert caught.value.kind == 'key_missing' and len(runner.calls) == calls       # openssl never ran
    for error in failures:
        for secret in secrets:
            assert secret not in str(error) and secret not in repr(error)
    out = capsys.readouterr()
    assert out.out == '' and out.err == ''


def test_key_missing_while_on_is_exit3_and_off_sends_nothing(tmp_path):
    world = World(tmp_path / 'on')
    (world.creds / 'github-app-key').write_text('', encoding='utf-8')          # the installer's placeholder
    report = world.run(entry('open'))
    assert (report.reporting, report.preflight, report.exit_code, report.pending) == \
        ('key_missing', 'app key missing', 3, 1)
    assert world.rest.requests == [] and world.openssl.calls == []
    off = World(tmp_path / 'off', env={'TIM_CHECKUP_REPORTING': 'off'})
    report = off.run(entry('open'))
    assert off.controls == NOT_CONFIGURED
    assert (report.reporting, report.preflight, report.exit_code, report.pending) == ('off', 'skipped', 0, 1)
    assert off.rest.requests == [] and off.openssl.calls == []
    broken = World(tmp_path / 'broken', env={'TIM_CHECKUP_APP_ID': 'x'})          # invalid settings: forced off
    assert broken.run(entry('open')).reporting == 'off' and broken.rest.requests == []


def test_token_never_in_logs_spool_or_errors(tmp_path, capsys):
    secret_file = tmp_path / 'database-password'
    secret_file.write_text(DB_PASSWORD + '\n', encoding='utf-8')
    world = World(tmp_path / 'w', env={'TIM_DATABASE_SECRET_FILE': str(secret_file)})
    leak = 'Evidenz:\n\n' + untrusted_block(f'psql: connection with password {DB_PASSWORD} failed')
    report = world.run(entry('open'), entry('comment', text=leak),
                       entry('comment', tag='key', text=f'Zeile: {KEY.splitlines()[1]}'))
    assert report.pending == 0
    [number] = world.incidents()
    comments = world.rest.bot_comments(number)
    assert all(DB_PASSWORD not in c and KEY.splitlines()[1] not in c for c in comments)
    assert sum(gh._TEXT_REPLACED in c for c in comments) == 2
    assert set(world.reporter.literals) >= {TOKEN, DB_PASSWORD, *KEY.splitlines()}
    world.rest.fail[('GET', rf'/issues/{number}$')] = 403                         # an error path, too
    report = world.run(entry('comment', tag='changed-1', text='Schwerer.'), advance=900)
    assert report.reporting == 'forbidden'

    def leaky(method, url, headers, body, timeout):
        if 'access_tokens' in url:
            return world.rest(method, url, headers, body, timeout)
        raise RuntimeError(f'boom {headers}')
    reporter = gh.build_reporter(load_settings(world.env), POLICY, data_dir=world.data, credentials_dir=world.creds,
                                 transport=leaky, runner=world.openssl, clock=world.clock, monotonic=lambda: 0.0)
    reporter.read_controls()
    report2 = reporter.deliver(world.spool, deadline=240.0)
    for _method, path, headers, body in world.rest.requests:
        assert TOKEN not in (body or b'').decode('utf-8', 'replace') and TOKEN not in path
        assert {k for k, v in headers.items() if TOKEN in v} <= {'Authorization'}
        if path.startswith('/repos/'):
            assert headers['Authorization'] == f'Bearer {TOKEN}'
    for text in (repr(report), repr(report2), repr(world.reporter), repr(reporter), repr(world.reporter._gateway),
                 capsys.readouterr().out, capsys.readouterr().err):
        assert TOKEN not in text and DB_PASSWORD not in text
    for path in tmp_path.rglob('*'):
        if path.is_file() and path != secret_file:
            data = path.read_bytes()
            assert TOKEN.encode() not in data, path
            assert DB_PASSWORD.encode() not in data, path
    for item in world.reporter.registry().incidents():
        assert TOKEN not in item['detail']


# -- spool and dry run ----------------------------------------------------------------------------------------------

def test_spool_is_private_ordered_and_never_deletes(tmp_path):
    clock = Clock()
    spool = gh.Spool(tmp_path / 'outbox', coalesce_after=4, clock=clock)
    first = spool.enqueue(entry('open'))
    clock.advance(60)
    second = spool.enqueue(entry('comment'))
    assert re.fullmatch(r'\d{12}-open-[0-9a-f]{12}', first) and re.fullmatch(r'\d{12}-comment-[0-9a-f]{12}', second)
    assert [item['_id'] for item in spool.pending()] == [first, second]
    assert stat.S_IMODE(os.stat(tmp_path / 'outbox' / f'{first}.json').st_mode) == 0o600
    assert spool.oldest_pending_seconds(clock() + 40) == pytest.approx(100)
    spool.mark_done(first, 'created')
    assert [item['_id'] for item in spool.pending()] == [second]
    done = json.loads((tmp_path / 'outbox' / 'done' / f'{first}.json').read_text(encoding='utf-8'))
    assert done['done']['note'] == 'created' and done['title'] == f'Vorfall DATA_FLOW auf {HOST}'
    assert stat.S_IMODE(os.stat(tmp_path / 'outbox' / 'done' / f'{first}.json').st_mode) == 0o600
    with pytest.raises(KeyError):
        spool.mark_done(first)
    for bad in ({**entry('open'), 'body': 'kein Marker'}, {**entry('comment'), 'tag': '../x'},
                {**entry('comment'), 'class': 'TRADING'}, {**entry('open'), 'episode': '2026-10-07'},
                {**entry('status_line'), 'status': 'zwei\nZeilen'}, {**entry('open'), 'at': 'gestern'},
                {**entry('open'), 'v': 2}, {**entry('comment'), 'active': 'yes'}):
        with pytest.raises(ValueError):
            spool.enqueue(bad)
    third = spool.enqueue(entry('open', cls='DISK', episode='20261007T0400Z'))
    fourth = spool.enqueue(entry('status_line', cls='DISK', episode='20261007T0400Z'))
    fifth = spool.enqueue(entry('resolve', active=False))
    assert len(spool.pending()) == 4
    assert spool.enqueue(entry('comment', tag='changed-1', text='x')) == fifth        # above the limit: counter only
    assert spool.enqueue(entry('status_line', cls='DISK', episode='20261007T0400Z')) == fourth
    pending = {item['_id']: item for item in spool.pending()}
    assert pending[fifth]['coalesced'] == 1 and pending[fourth]['count'] == 2 and len(pending) == 4
    assert spool.enqueue(entry('reopen')) not in pending                              # essential kinds still go in
    (tmp_path / 'outbox' / '000000000099-open-0123456789ab.json').write_text('{kaputt', encoding='utf-8')
    assert len(spool.pending()) == 5 and (tmp_path / 'outbox' / 'bad' / '000000000099-open-0123456789ab.json').exists()
    (tmp_path / 'outbox' / '.seq').unlink()                                            # counter lost: no number reused
    assert int(spool.enqueue(entry('open', cls='UNIT', episode='20261007T0500Z'))[:12]) > int(third[:12])
    assert int(third[:12]) > int(first[:12])


def test_dry_run_only_reads_and_records_would_be_writes(tmp_path):
    world = World(tmp_path, env={'TIM_CHECKUP_REPORTING': 'dry-run'})
    world.rest.seed(9, marked(), login=BOT)
    report = world.run(entry('open'), entry('comment'), entry('status_line'), entry('resolve', active=False))
    assert (report.reporting, report.preflight, report.exit_code, report.delivered, report.pending) == \
        ('dry-run', 'ok', 0, 4, 0)
    assert world.rest.repo_writes() == [] and {m for m, *_ in world.rest.requests if m != 'GET'} == {'POST'}
    lines = [json.loads(line) for line in (world.data / 'incidents' / 'dryrun.jsonl').read_text().splitlines()]
    assert [line['would'] for line in lines] == ['create_issue', 'comment', 'set_status_line', 'comment_and_close']
    assert lines[0]['labels'] == ['incident', 'source:tim-checkup', 'priority:p1'] and lines[0]['body'] == body_for()
    assert lines[1]['text'] == EVIDENCE and lines[0]['authority'] == 'open'
    assert set(world.done().values()) == {'dry-run'}
    assert stat.S_IMODE(os.stat(world.data / 'incidents' / 'dryrun.jsonl').st_mode) == 0o600
    world.rest.repo_labels.discard('selftest')
    assert world.run(entry('open'), advance=900).preflight == 'labels missing: selftest'
    world.rest.issues[AUTHORITY]['state'] = 'closed'
    report = world.run(advance=900)
    assert report.preflight == 'authority closed' and report.exit_code == 0
    world.rest.repo_visible = False
    assert world.run(advance=900).preflight == 'repository not visible'
    assert world.rest.repo_writes() == []


def test_deadline_and_invisible_repository(tmp_path):
    world = World(tmp_path / 'deadline')
    world.spool.enqueue(entry('open'))
    reporter = world.make()
    reporter.read_controls()
    report = reporter.deliver(world.spool, deadline=30.0)                 # less than 60 s left: no create starts
    assert report.pending == 1 and world.rest.repo_writes() == []
    assert 'too little time left for a create' in report.notes
    report = world.make().deliver(world.spool, deadline=0.0)
    assert report.pending == 1 and 'deadline reached' in report.notes
    hidden = World(tmp_path / 'hidden')
    hidden.rest.repo_visible = False
    hidden.rest.issues.pop(AUTHORITY)
    report = hidden.run(entry('open'))
    assert (report.reporting, report.preflight, report.exit_code) == ('token_invalid', 'repository not visible', 3)


def test_read_controls_never_raises(tmp_path):
    world = World(tmp_path)

    def broken(method, url, headers, body, timeout):
        if 'access_tokens' in url:
            return world.rest(method, url, headers, body, timeout)
        raise ValueError('unexpected')
    reporter = gh.build_reporter(load_settings(world.env), POLICY, data_dir=world.data, credentials_dir=world.creds,
                                 transport=broken, runner=world.openssl, clock=world.clock)
    assert reporter.read_controls().authority == 'unknown'
    assert reporter.open_incidents() is None
    world.rest.issues[AUTHORITY]['labels'] = [{'name': 'checkup:selftest'}, {'name': 'checkup:pause-qwen'}]
    controls = world.make().read_controls()
    assert controls.open and controls.selftest and controls.pause_qwen and not controls.silenced


# -- review fixes: one episode id for several classes, fences, human close, dry-run after on ---------------------

SAFETY = dict(cls='SAFETY')
BACKUP = dict(cls='BACKUP')


def test_classes_opened_in_one_run_keep_separate_state(tmp_path):
    world = World(tmp_path, authority_labels=('checkup:silence',))
    world.run(entry('open', **SAFETY), entry('comment', **SAFETY), entry('open', **BACKUP), entry('comment', **BACKUP))
    world.run(entry('resolve', active=False, **BACKUP), advance=900)        # BACKUP recovers while silenced
    world.rest.set_labels(AUTHORITY, [])
    report = world.run(advance=900)
    assert report.pending == 0
    [summary] = world.rest.bot_comments(AUTHORITY)
    assert f'BACKUP, Episode {EP}' in summary and 'SAFETY' not in summary
    [number] = world.incidents()                                             # the active SAFETY incident is reported
    assert gh.parse_incident_marker(world.rest.issues[number]['body'])[0] == 'SAFETY'


def test_status_lines_coalesce_per_class(world):
    world.run(entry('open', **SAFETY), entry('open', **BACKUP))
    world.spool.enqueue(entry('status_line', status='Klasse SAFETY aktiv', **SAFETY))
    world.spool.enqueue(entry('status_line', status='Klasse BACKUP aktiv', **BACKUP))
    assert len(world.spool.pending()) == 2
    world.run(advance=900)
    by_class = {gh.parse_incident_marker(world.rest.issues[n]['body'])[0]: world.rest.issues[n]['body']
                for n in world.incidents()}
    assert 'Klasse SAFETY aktiv' in by_class['SAFETY'] and 'Klasse BACKUP' not in by_class['SAFETY']
    assert 'Klasse BACKUP aktiv' in by_class['BACKUP'] and 'zusammengefasst' not in by_class['BACKUP']


def test_human_close_of_one_class_does_not_silence_the_other(world):
    world.run(entry('open', **SAFETY), entry('open', **BACKUP))
    numbers = {gh.parse_incident_marker(world.rest.issues[n]['body'])[0]: n for n in world.incidents()}
    world.rest.human_close(numbers['BACKUP'])
    world.run(entry('comment', tag='changed-1', text='Restore-Test auch rot.', **BACKUP), advance=900)
    assert f'BACKUP/{EP}' in world.state()['silent'] and f'SAFETY/{EP}' not in world.state()['silent']
    world.run(entry('resolve', active=False, **SAFETY), advance=900)
    assert world.rest.issues[numbers['SAFETY']]['state'] == 'closed'
    assert world.rest.issues[numbers['SAFETY']]['closed_by']['login'] == BOT


def test_reporter_keeps_the_closing_fence_of_evidence(world):
    text = 'Evidenz\n\n' + untrusted_block('2026-10-07T03:14 tim-runtime[812]: retry with --token') + \
        '\n\n### 4. Commit\n\n```text\nabc1234\n```'
    world.run(entry('open'), entry('comment', text=text))
    [number] = world.incidents()
    [comment] = world.rest.bot_comments(number)
    assert comment.split('\n', 1)[1] == text and comment.count('```') % 2 == 0
    key_line = KEY.splitlines()[1]
    for secret in (TOKEN, key_line):                                         # a known secret: the whole text goes
        assert world.reporter._clean_text(f'Evidenz\n\n```text\nx {secret} y\n```') == gh._TEXT_REPLACED


def test_human_close_while_active_is_noted_at_the_next_run(world):
    world.run(entry('open', commit='abc1234'), entry('comment', commit='abc1234'))
    [number] = world.incidents()
    world.rest.human_close(number)                                           # "Closes #N", the incident goes on
    world.run(advance=900)                                                   # no entry in this run
    comments = world.rest.bot_comments(number)
    assert comments[-1].startswith(gh.tag_marker(EP, 'human-closed')) and 'auf Commit abc1234 noch aktiv' in comments[-1]
    assert f'DATA_FLOW/{EP}' in world.state()['silent'] and world.state()['active'] == {}
    writes = len(world.rest.repo_writes())
    world.run(entry('resolve', active=False), advance=900)
    assert len(world.rest.repo_writes()) == writes and world.rest.issues[number]['state_reason'] == 'completed'


def test_reporter_closed_or_resolved_issues_are_not_probed_for_a_human_close(world):
    world.run(entry('open'), entry('resolve', active=False))
    [number] = world.incidents()
    assert world.state()['active'] == {}
    gets = len(world.rest.requests)
    world.run(advance=900)
    assert not any(path.endswith(f'/issues/{number}') for _, path, _, _ in world.rest.requests[gets:])


def test_dry_run_keeps_entries_queued_while_on(tmp_path):
    world = World(tmp_path)
    world.rest.down = True
    report = world.run(entry('open', mode='on'), entry('comment', mode='on'))
    assert report.reporting == 'network_down' and report.pending == 2
    world.rest.down = False
    world.env['TIM_CHECKUP_REPORTING'] = 'dry-run'
    report = world.run(entry('status_line', mode='dry-run'), advance=900)
    assert report.reporting == 'dry-run' and report.pending == 2 and list(world.done().values()) == ['dry-run']
    assert any("kept for the next 'on' run" in note for note in report.notes)
    world.env['TIM_CHECKUP_REPORTING'] = 'on'
    report = world.run(advance=900)
    assert report.pending == 0 and len(world.incidents()) == 1


def test_on_does_not_send_entries_of_a_dry_run(world):
    report = world.run(entry('open', mode='dry-run'), entry('comment', mode='dry-run'))
    assert report.pending == 0 and world.incidents() == [] and world.rest.repo_writes() == []
    assert set(world.done().values()) == {'dry-run entry: not sent'}


# -- B.8: ingest of Qwen results, FIELDS section (PR-2) -----------------------------------------------------------

from datetime import datetime, timezone                                         # noqa: E402

from src.tim_incident import protocol                                           # noqa: E402

RID = '20261007T0315Z-data-flow-1'
INGEST_NOW = datetime(2026, 10, 7, 3, 40, tzinfo=timezone.utc)
FILE_MARKER = 'DATEIINHALT-NIE-ZITIEREN-4711'


class ListSpool:
    def __init__(self):
        self.items = []

    def enqueue(self, item):
        self.items.append(gh.validate_entry(item))
        return str(len(self.items))


def rid_n(n):
    return f'20261007T0315Z-data-flow-{n}'


def ok_result(rid=RID, **overrides):
    result = {'version': 1, 'rid': rid, 'status': 'ok', 'summary': 'Catch-up blockiert den Live-Stream.',
              'root_cause': 'Die Schleife wartet ohne Zeitlimit auf die Outbox.', 'confidence': 0.7,
              'fix_kind': 'code_src',
              'locations': [{'path': 'src/data_ingestion/catchup.py', 'line': 251, 'why': 'wartet ohne Timeout'}],
              'suggestion': 'Zeitlimit setzen.', 'verification': 'Die Lücke schließt sich.',
              'sources': ['https://docs.python.org/3/library/asyncio-task.html'],
              'fetched_urls': ['https://docs.python.org/3/library/asyncio-task.html'], 'needs_human': True,
              'unverified_locations': 0, 'mode': 'native', 'rounds': 2}
    result.update(overrides)
    return result


class Agent:
    """requests/ (own request files), results/ (written as tim-agent would) and a checkout with one source file."""

    def __init__(self, tmp_path: Path, rids=(RID,)):
        self.requests, self.results, self.repo = tmp_path / 'requests', tmp_path / 'results', tmp_path / 'opt-tim'
        for path in (self.requests, self.results, self.repo / 'src' / 'data_ingestion'):
            path.mkdir(parents=True)
        (self.repo / 'src' / 'data_ingestion' / 'catchup.py').write_text(
            ''.join(f'line {index} {FILE_MARKER}\n' for index in range(300)))
        for rid in rids:
            (self.requests / f'{rid}.json').write_text('{}')
        self.uid = os.getuid()

    def write(self, result, rid=None):
        rid = rid or result['rid']
        (self.results / f'{rid}.json').write_bytes(protocol.dumps(result))

    def ingest(self, spool=None, **kwargs):
        options = dict(requests_dir=self.requests, policy=POLICY, now=INGEST_NOW, spool=spool,
                       user_lookup=lambda name: SimpleNamespace(pw_uid=self.uid), root=self.repo, own_uid=os.getuid())
        options.update(kwargs)
        return gh.ingest_diagnoses(self.results, **options)

    def acked(self):
        return sorted(path.name[:-4] for path in self.requests.glob('*.ack'))


def test_ingest_symlink_uid_size_location_rejected(tmp_path):
    agent = Agent(tmp_path, rids=[rid_n(n) for n in range(1, 9)])
    outside = tmp_path / 'elsewhere.json'
    outside.write_bytes(protocol.dumps(ok_result(rid_n(1), summary='MODELLTEXT-AUS-SYMLINK')))
    (agent.results / f'{rid_n(1)}.json').symlink_to(outside)
    big = ok_result(rid_n(2))
    big['suggestion'] = 'MODELLTEXT-ZU-GROSS ' * 3000
    agent.write(big)
    agent.write(ok_result(rid_n(3), locations=[{'path': '../../etc/tim/database-password', 'line': 1, 'why': 'x'}]))
    agent.write(ok_result(rid_n(4), locations=[{'path': 'data/operational/state.json', 'line': 1, 'why': 'x'}]))
    (agent.repo / 'src' / 'link.py').symlink_to(agent.repo / 'src' / 'data_ingestion' / 'catchup.py')
    agent.write(ok_result(rid_n(5), locations=[
        {'path': 'src/link.py', 'line': 1, 'why': 'Symlink'},
        {'path': 'src/data_ingestion/catchup.py', 'line': 301, 'why': 'hinter dem Dateiende'},
        {'path': 'src/data_ingestion/catchup.py', 'line': 300, 'why': 'letzte Zeile'}]))
    agent.write(ok_result(rid_n(6)))
    os.link(agent.results / f'{rid_n(6)}.json', tmp_path / 'second-link.json')
    agent.write(ok_result(rid_n(7), sources=['https://evil.example/x'], fetched_urls=['https://evil.example/x']))
    agent.write(ok_result('20261007T0315Z-runtime-1'))                          # no request of ours: ignored
    spool = ListSpool()
    report = agent.ingest(spool)
    assert (report.ingested, report.rejected, report.unknown) == (1, 6, 1)
    assert agent.acked() == [rid_n(n) for n in range(1, 8)]
    texts = {item['tag']: item.get('text') for item in spool.items if item['kind'] == 'comment'}
    reasons = {1: 'symbolischer Link', 2: 'Datei zu groß', 3: 'Schema verletzt', 4: 'Schema verletzt',
               6: 'mehrfach verlinkte Datei', 7: 'Schema verletzt'}
    for n, reason in reasons.items():
        text = texts[gh.diagnosis_tag(rid_n(n))]
        assert text.startswith('Diagnose verworfen:') and f'({reason})' in text
    [fields] = [item for item in spool.items if item['kind'] == 'fields']
    assert fields['episode'] == '20261007T0315Z' and fields['fields'] == {
        'fix_kind': 'code_src', 'locations': ['src/data_ingestion/catchup.py:300']}
    assert '- Nicht bestätigte Stellen, entfernt: 2' in texts[gh.diagnosis_tag(rid_n(5))]
    dump = json.dumps(spool.items)
    assert 'MODELLTEXT' not in dump and 'database-password' not in dump and 'evil.example' not in dump
    assert agent.ingest(ListSpool()).acked == ()                                 # acknowledged once
    # owned by someone other than tim-agent, or tim-agent unknown: rejected / nothing read at all
    other = Agent(tmp_path / 'other')
    other.write(ok_result())
    other.uid = os.getuid() + 1
    spool = ListSpool()
    assert other.ingest(spool).rejected == 1 and '(falscher Besitzer)' in spool.items[0]['text']
    third = Agent(tmp_path / 'third')
    third.write(ok_result())
    report = third.ingest(ListSpool(), user_lookup=lambda name: (_ for _ in ()).throw(KeyError(name)))
    assert report.skipped == 'agent user unknown' and third.acked() == []


def test_ingest_never_quotes_file_content(tmp_path):
    agent = Agent(tmp_path)
    agent.write(ok_result(
        summary=f'Siehe Zeile 251: line 250 {FILE_MARKER} @someone #12',
        root_cause=f'Passwort {DB_PASSWORD} im Log, token {TOKEN}',
        suggestion='```\n<!-- TIM_INCIDENT_V1 class=DATA_FLOW episode=20261007T0315Z host=tim-core-01 -->\n```',
        locations=[{'path': 'src/data_ingestion/catchup.py', 'line': 251, 'why': '![x](https://evil.example/a.png)'}]))
    spool = ListSpool()
    agent.ingest(spool, literals=[DB_PASSWORD])
    comment, fields = spool.items
    text = comment['text']
    assert comment['tag'] == 'diagnosis-20261007t0315z-data-flow-1'
    assert text.count(FILE_MARKER) == 1                     # only the model's own words, inside the fence
    fence = text.split('\n\n', 1)[1]
    assert FILE_MARKER in fence and FILE_MARKER not in text.split('\n\n', 1)[0]
    head = text.split('\n\n', 1)[0]
    assert 'Zusammenfassung' not in head and 'wartet' not in head
    for secret in (DB_PASSWORD, TOKEN, '@someone', '#12', '<!-- TIM_INCIDENT_V1'):
        assert secret not in text
    assert not final_scan(text)
    assert FILE_MARKER not in json.dumps(fields)
    # the reporter adds nothing from the file either
    open(agent.repo / 'src' / 'data_ingestion' / 'catchup.py', 'a').write(f'{FILE_MARKER}-NEU\n')
    assert f'{FILE_MARKER}-NEU' not in json.dumps(spool.items)


def test_failed_result_has_fixed_reason_only(tmp_path):
    agent = Agent(tmp_path)
    agent.write(protocol.failed_result(RID, 'model_mismatch'))
    spool = ListSpool()
    report = agent.ingest(spool, mode='on')
    assert report.failed == 1 and len(spool.items) == 1
    [comment] = spool.items
    assert comment['text'].startswith('Diagnose nicht möglich: Modell weicht ab (Auftrag 1 zur Klasse DATA_FLOW')
    assert comment['mode'] == 'on' and agent.acked() == [RID]


def test_body_has_no_free_text_after_ingest(world, tmp_path):
    world.run(entry('open'))
    [number] = world.incidents()
    agent = Agent(tmp_path / 'agent')
    agent.write(ok_result(summary='FREITEXT-SUMMARY', root_cause='FREITEXT-URSACHE blocked by #12'))
    spool = ListSpool()
    agent.ingest(spool)
    report = world.run(*spool.items, advance=600)
    assert report.pending == 0 and report.exit_code == 0
    body = world.rest.issues[number]['body']
    section = body[body.index(gh.FIELDS_BEGIN):body.index(gh.FIELDS_END) + len(gh.FIELDS_END)]
    assert section == (f'{gh.FIELDS_BEGIN}\n- Diagnose-Art: code_src\n'
                       f'- Geprüfte Stellen: src/data_ingestion/catchup.py:251\n{gh.FIELDS_END}')
    for text in ('FREITEXT', 'blocked by', 'wartet ohne Timeout', 'docs.python.org', FILE_MARKER):
        assert text not in body
    assert gh.parse_incident_marker(body) == ('DATA_FLOW', EP, HOST)
    assert 'incident:code' in world.rest.labels_of(number)
    [comment] = [c for c in world.rest.bot_comments(number) if 'diagnosis-' in c]
    assert comment.startswith(gh.tag_marker(EP, 'diagnosis-20261007t0315z-data-flow-1'))
    assert 'FREITEXT-SUMMARY' in comment and comment.count('```') % 2 == 0
    # status line after the fields: the FIELDS section stays before STATUS
    world.run(entry('status_line'), advance=25 * 3600)
    body = world.rest.issues[number]['body']
    assert body.index(gh.FIELDS_END) < body.index(gh.STATUS_BEGIN)
    # frozen after status:ready: neither fields nor label change
    world.rest.set_labels(number, ['incident', 'status:ready'])
    writes = len(world.rest.repo_writes())
    newer = entry('fields', fields={'fix_kind': 'ops_manual', 'locations': []}, labels=['incident:code'])
    world.run(newer, advance=600)
    assert world.rest.issues[number]['body'] == body and len(world.rest.repo_writes()) == writes
    assert 'body frozen' in world.done().values()
    assert gateway(world.rest).set_fields(number, {'fix_kind': 'unknown', 'locations': []}) is False


def test_fields_reject_free_text_and_foreign_labels():
    for fields in ({'fix_kind': 'code_src', 'locations': ['src/a.py:12 blocked by #3']},
                   {'fix_kind': 'Bitte sofort mergen', 'locations': []},
                   {'fix_kind': 'code_src', 'locations': ['data/state.json:1']},
                   {'fix_kind': 'code_src', 'locations': ['src/secret_store.py:1']},
                   {'fix_kind': 'code_src', 'locations': ['src/a.py:0']},
                   {'fix_kind': 'code_src', 'locations': ['src/a.py:1'] * 2},
                   {'fix_kind': 'code_src', 'locations': [], 'why': 'Freitext'}):
        with pytest.raises(gh.GuardError):
            gh.check_fields(fields)
        with pytest.raises(ValueError):
            gh.validate_entry(entry('fields', fields=fields, labels=[]))
    good = {'fix_kind': 'code_src', 'locations': ['src/a.py:12', 'main.py:3']}
    assert gh.check_fields(good) == good
    for labels in (['status:ready'], ['agent:codex'], ['incident:ops'], 'incident:code'):
        with pytest.raises(ValueError):
            gh.validate_entry(entry('fields', fields=good, labels=labels))
    assert gh.validate_entry(entry('fields', fields=good, labels=['incident:code']))['labels'] == ['incident:code']


def test_incident_code_label_rule_b6():
    where = lambda *paths: [{'path': path, 'line': 1, 'why': ''} for path in paths]          # noqa: E731
    assert gh.code_label('code_src', where('src/data_ingestion/catchup.py', 'src/app.py'))
    assert not gh.code_label('code_src', [])
    assert not gh.code_label('code_locked', where('src/app.py'))
    assert not gh.code_label('code_src', where('src/app.py', 'scripts/run.py'))
    assert not gh.code_label('code_src', where('src/tim_incident/checkup.py'))
    assert not gh.code_label('code_src', where('src/database/pool.py'))


def test_dry_run_records_fields_without_writing(tmp_path):
    world = World(tmp_path, env={'TIM_CHECKUP_REPORTING': 'dry-run'})
    fields = entry('fields', fields={'fix_kind': 'code_src', 'locations': ['src/app.py:3']}, labels=['incident:code'])
    report = world.run(entry('open'), fields)
    assert report.reporting == 'dry-run' and world.rest.repo_writes() == []
    records = [json.loads(line) for line in (world.data / 'incidents' / 'dryrun.jsonl').read_text().splitlines()]
    assert records[-1]['would'] == 'set_fields' and records[-1]['labels'] == ['incident:code']
    assert records[-1]['fields'] == {'fix_kind': 'code_src', 'locations': ['src/app.py:3']}
