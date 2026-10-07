"""src/tim_incident/protocol.py: request/result schemas, path allowlist, safe file I/O, HOLD and PAUSE (design C.1,
C.2, C.5, B.8). No network, no systemd."""
from __future__ import annotations

import copy
import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest

from src.tim_incident import protocol
from src.tim_incident.policy import load_policy
from src.tim_incident.protocol import (
    ERROR_TEXTS, FAILURE_REASONS, FAILURE_TEXTS, FIX_KINDS, HOLD, PAUSE, ProtocolError, ack_name, atomic_write,
    build_request, check_path, clear_hold, dumps, failed_result, hold_active, line_count, list_rids, loads_strict,
    make_rid, parse_rid, path_allowed, pause_active, pending_rids, read_beneath, read_pause, read_request, read_result,
    request_name, result_name, safe_read, url_ok, validate_request, validate_result, verify_locations, write_ack,
    write_hold, write_pause, write_request, write_result,
)
from src.tim_incident.redaction import final_scan

UTC = timezone.utc
NOW = datetime(2026, 9, 30, 3, 20, tzinfo=UTC)
UID = os.getuid()
POLICY = load_policy()
DOMAINS = POLICY.agent.fetch_domains
SECRET = 'S3cr3tF1leC0ntentDoNotQuote'


def request(**changes) -> dict:
    data = {
        'version': 1, 'rid': '20260930T0312Z-data-flow-1', 'episode': '20260930T0312Z', 'class': 'DATA_FLOW',
        'created_at': '2026-09-30T03:15:00Z', 'selftest': False, 'evidence': 'candle_freshness RED\nmissing=7',
        'units': ['tim-runtime.service', 'tim-candle-finalizer.service'],
        'journal': {'tim-runtime.service': ['2026-09-30T03:10:00+0000 tim python[1]: catch-up incomplete']},
    }
    data.update(changes)
    return data


def result(**changes) -> dict:
    data = {
        'version': 1, 'rid': '20260930T0312Z-data-flow-1', 'status': 'ok', 'summary': 'Nachholen blieb hängen.',
        'root_cause': 'Der Catch-up wartet auf eine Sperre.', 'confidence': 0.6, 'fix_kind': 'code_src',
        'locations': [{'path': 'src/data_ingestion/catchup.py', 'line': 10, 'why': 'Sperre'}],
        'suggestion': 'Zeitlimit für die Sperre.', 'verification': 'Lücke schließt sich.',
        'sources': ['https://docs.python.org/3/library/asyncio.html'],
        'fetched_urls': ['https://docs.python.org/3/library/asyncio.html', 'https://pypi.org/project/asyncpg/'],
        'needs_human': True, 'unverified_locations': 0, 'mode': 'native', 'rounds': 2,
    }
    data.update(changes)
    return data


# --- names ---------------------------------------------------------------------------------------------------------------

def test_rid_roundtrip_and_sorting():
    rid = make_rid('20260930T0312Z', 'DATA_FLOW', 1)
    assert rid == '20260930T0312Z-data-flow-1'
    assert parse_rid(rid) == ('20260930T0312Z', 'DATA_FLOW', 1)
    assert parse_rid(make_rid('20260930T0312Z', 'HEALTH_STALE', 12)) == ('20260930T0312Z', 'HEALTH_STALE', 12)
    assert sorted([make_rid('20261001T0000Z', 'DISK', 1), rid]) == [rid, make_rid('20261001T0000Z', 'DISK', 1)]
    assert request_name(rid) == rid + '.json' and result_name(rid) == rid + '.json' and ack_name(rid) == rid + '.ack'


@pytest.mark.parametrize('rid', ['', '../x', '20260930T0312Z-data-flow-0', '20260930T0312Z-nope-1',
                                 '20260930T0312Z-data-flow-1.json', '20260930T0312Z-DATA-FLOW-1', 'x/y', None, 5,
                                 '20260930T0312Z-data-flow-1000', '20260930T0312Z-data_flow-1'])
def test_invalid_rids(rid):
    assert parse_rid(rid) is None
    with pytest.raises(ProtocolError):
        request_name(rid)


def test_make_rid_rejects_bad_parts():
    for args in (('2026-09-30', 'DISK', 1), ('20260930T0312Z', 'NOPE', 1), ('20260930T0312Z', 'DISK', 0),
                 ('20260930T0312Z', 'DISK', True)):
        with pytest.raises(ValueError):
            make_rid(*args)


# --- strict JSON ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('data', [b'{"a": 1, "a": 2}', b'{"a": NaN}', b'{"a": Infinity}', b'[1]', b'{', b'\xff{}',
                                  b'"text"', b'{"a": ' + b'[' * 100000 + b']' * 100000 + b'}'])
def test_loads_strict_rejects(data):
    with pytest.raises(ProtocolError):
        loads_strict(data, 10 ** 7)


def test_loads_strict_size_first():
    with pytest.raises(ProtocolError) as caught:
        loads_strict(b'{"a": "' + b'x' * 100 + b'"}', 50)
    assert caught.value.code == 'too_large'


# --- requests ----------------------------------------------------------------------------------------------------------

def test_valid_request_roundtrip():
    checked = validate_request(request(), allowed_units=POLICY.agent.units_allowlist)
    assert checked == request()
    assert validate_request(dumps(checked)) == checked
    built = build_request(episode='20260930T0312Z', cls='DATA_FLOW', seq=1, created_at=datetime(2026, 9, 30, 3, 15),
                          evidence=checked['evidence'], units=checked['units'], journal=checked['journal'],
                          allowed_units=POLICY.agent.units_allowlist)
    assert built == checked


def test_build_request_keeps_last_200_journal_lines():
    lines = [f'line {n}' for n in range(500)]
    built = build_request(episode='20260930T0312Z', cls='DATA_FLOW', seq=1, created_at=NOW, evidence='e',
                          units=['tim-runtime.service'], journal={'tim-runtime.service': lines})
    assert built['journal']['tim-runtime.service'] == lines[-200:]


def test_selftest_request_with_expected_paths():
    data = request(rid='20260930T0312Z-selftest-1', **{'class': 'SELFTEST'}, selftest=True, units=[], journal={},
                   expected_paths=['src/data_ingestion/catchup.py', 'src/data_ingestion/durable.py'])
    assert validate_request(data)['expected_paths'] == ['src/data_ingestion/catchup.py', 'src/data_ingestion/durable.py']


@pytest.mark.parametrize('changes', [
    {'version': 2},
    {'version': True},
    {'rid': '20260930T0312Z-disk-1'},                    # class mismatch
    {'episode': '20260930T0313Z'},                       # episode mismatch
    {'class': 'NOPE'},
    {'created_at': '2026-09-30 03:15:00'},
    {'created_at': '2026-13-30T03:15:00Z'},
    {'selftest': True},                                  # only the SELFTEST class
    {'selftest': 'false'},
    {'evidence': ''},
    {'evidence': 'x' * (protocol.EVIDENCE_MAX_CHARS + 1)},
    {'evidence': 'nul\x00byte'},
    {'evidence': 'escape \x1b[31m'},
    {'evidence': 'lone \ud800 surrogate'},
    {'units': []},
    {'units': ['tim-runtime.service', 'tim-runtime.service']},
    {'units': ['tim-runtime']},
    {'units': ['tim-runtime.service; rm -rf /']},
    {'units': ['u%d.service' % n for n in range(9)]},
    {'journal': {'tim-backup.service': ['x']}},          # unit not in units
    {'journal': {'tim-runtime.service': ['x'] * 201}},
    {'journal': {'tim-runtime.service': 'x'}},
    {'journal': {'tim-runtime.service': ['x' * 2001]}},
    {'journal': {'tim-runtime.service': [1]}},
    {'journal': []},
    {'expected_paths': ['src/x.py']},                    # not a selftest
    {'extra': 1},
])
def test_invalid_requests_rejected(changes):
    with pytest.raises(ProtocolError):
        validate_request(request(**changes))


def test_request_missing_key_and_allowed_units():
    data = request()
    del data['journal']
    with pytest.raises(ProtocolError):
        validate_request(data)
    with pytest.raises(ProtocolError):
        validate_request(request(units=['ssh.service']), allowed_units=POLICY.agent.units_allowlist)


def test_request_size_limit():
    big = request(evidence='y' * 10000, journal={'tim-runtime.service': ['z' * 1900] * 200})
    with pytest.raises(ProtocolError) as caught:
        validate_request(big, max_bytes=POLICY.limits.request_bytes)
    assert caught.value.code == 'too_large'
    with pytest.raises(ProtocolError):
        validate_request(dumps(big), max_bytes=POLICY.limits.request_bytes)


def test_selftest_expected_paths_rules():
    base = dict(rid='20260930T0312Z-selftest-1', selftest=True, units=[], journal={})
    base['class'] = 'SELFTEST'
    for paths in (['../etc/passwd'], ['data/x.json'], [], ['src/a.py', 'src/a.py'], ['.venv/lib/x.py'],
                  ['requirements.txt']):
        with pytest.raises(ProtocolError):
            validate_request(request(**base, expected_paths=paths))


# --- results -----------------------------------------------------------------------------------------------------------

def test_valid_result_roundtrip():
    checked = validate_result(result(), expected_rid='20260930T0312Z-data-flow-1', fetch_domains=DOMAINS)
    assert checked == result()
    assert validate_result(dumps(checked), fetch_domains=DOMAINS) == checked
    assert validate_result(result(confidence=1))['confidence'] == 1.0
    assert validate_result(result(locations=[], sources=[], fetched_urls=[], root_cause=''))['locations'] == []


def test_failed_result():
    for reason in FAILURE_REASONS:
        assert failed_result('20260930T0312Z-data-flow-1', reason)['reason'] == reason
        assert not final_scan(FAILURE_TEXTS[reason])
    with pytest.raises(ValueError):
        failed_result('20260930T0312Z-data-flow-1', 'free text from the model')
    with pytest.raises(ProtocolError):
        validate_result({'version': 1, 'rid': '20260930T0312Z-data-flow-1', 'status': 'failed', 'reason': 'x'})
    with pytest.raises(ProtocolError):
        validate_result({'version': 1, 'rid': '20260930T0312Z-data-flow-1', 'status': 'failed',
                         'reason': 'timeout', 'summary': 'extra'})


@pytest.mark.parametrize('changes', [
    {'status': 'done'},
    {'rid': '../x'},
    {'summary': ''},
    {'summary': 'x' * 301},
    {'root_cause': 'x' * 801},
    {'suggestion': 'x' * 1201},
    {'verification': 'x' * 601},
    {'summary': 5},
    {'confidence': 1.5},
    {'confidence': -0.1},
    {'confidence': True},
    {'confidence': float('nan')},
    {'confidence': '0.5'},
    {'fix_kind': 'restart'},
    {'locations': [{'path': 'src/a.py', 'line': 1, 'why': 'x'}] * 6},
    {'locations': [{'path': '../../etc/tim/database-password', 'line': 1, 'why': ''}]},
    {'locations': [{'path': 'data/operational/server_health.json', 'line': 1, 'why': ''}]},
    {'locations': [{'path': '.venv/lib/python3.13/site-packages/x.py', 'line': 1, 'why': ''}]},
    {'locations': [{'path': 'src/a.py', 'line': 0, 'why': ''}]},
    {'locations': [{'path': 'src/a.py', 'line': True, 'why': ''}]},
    {'locations': [{'path': 'src/a.py', 'line': 1, 'why': 'x' * 201}]},
    {'locations': [{'path': 'src/a.py', 'line': 1}]},
    {'locations': [{'path': 'src/a.py', 'line': 1, 'why': '', 'quote': 'x'}]},
    {'sources': ['https://evil.example/x'], 'fetched_urls': ['https://evil.example/x']},
    {'sources': ['https://pypi.org/project/x/']},                          # not fetched
    {'fetched_urls': ['http://pypi.org/project/x/']},
    {'fetched_urls': ['https://pypi.org/project/x/?q=leak']},
    {'fetched_urls': ['https://user:pw@pypi.org/']},
    {'fetched_urls': ['https://pypi.org:8443/']},
    {'fetched_urls': ['https://pypi.org/x'] * 2},
    {'needs_human': 'yes'},
    {'unverified_locations': -1},
    {'mode': 'cloud'},
    {'rounds': 21},
    {'labels': ['status:ready']},
    {'body': 'free text'},
])
def test_invalid_results_rejected(changes):
    with pytest.raises(ProtocolError):
        validate_result(result(**changes), fetch_domains=DOMAINS)


def test_result_rid_and_size_checks():
    with pytest.raises(ProtocolError):
        validate_result(result(), expected_rid='20260930T0312Z-data-flow-2')
    with pytest.raises(ProtocolError) as caught:
        validate_result(dumps(result()) + b' ' * 40000)
    assert caught.value.code == 'too_large'
    assert set(FIX_KINDS) == {'code_src', 'code_locked', 'ops_manual', 'external_network', 'transient', 'unknown'}


def test_url_ok():
    assert url_ok('https://docs.python.org/3/library/asyncio.html', DOMAINS)
    assert url_ok('https://github.com', DOMAINS)
    assert not url_ok('https://docs.python.org.evil.example/', DOMAINS)
    assert not url_ok('https://evil.example/', DOMAINS)
    assert url_ok('https://evil.example/')                       # without domains only the form counts
    for bad in ('https://pypi.org/a b', 'https://pypi.org/#x', 'https://PYPI.org/', 'https://1.2.3.4./', 'ftp://pypi.org/',
                'https://pypi..org/', 'https://pypi.org/' + 'a' * 201, 7):
        assert not url_ok(bad, DOMAINS), bad


# --- path allowlist --------------------------------------------------------------------------------------------------------

@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / 'opt-tim'
    files = {
        'src/data_ingestion/catchup.py': ''.join(f'line {n}\n' for n in range(1, 31)),
        'scripts/tim_server_health.py': 'x\n',
        'main.py': 'print()\n',
        'requirements.txt': 'aiohttp\n',
        'ops/systemd/tim.env.example': '# TIM_X=\n',
        'ops/systemd/tim.env': 'SECRET=1\n',
        '.venv/lib/python3.13/site-packages/aiohttp/client.py': 'class ClientError: ...\n',
        'data/operational/server_health.json': SECRET,
        'config/secrets.py': SECRET,
        'docs/runbook.md': '# x\n',
        'tests/test_x.py': 'x\n',
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    outside = tmp_path / 'outside.txt'
    outside.write_text(SECRET, encoding='utf-8')
    os.symlink(outside, root / 'src' / 'link.py')
    os.symlink(root / 'data', root / 'src' / 'datalink')
    (root / 'docs' / 'sub').mkdir()
    os.symlink(tmp_path, root / 'docs' / 'up')
    os.mkfifo(root / 'src' / 'fifo.py')
    return root


@pytest.mark.parametrize('path', ['src/data_ingestion/catchup.py', 'scripts/tim_server_health.py', 'main.py',
                                  'ops/systemd/tim.env.example', 'docs/runbook.md', 'tests/test_x.py'])
def test_allowed_paths(repo, path):
    assert check_path(path, repo) is None
    assert path_allowed(path, repo, location=True)
    assert read_beneath(repo, path)


def test_tool_only_paths(repo):
    for path in ('requirements.txt', '.venv/lib/python3.13/site-packages/aiohttp/client.py'):
        assert path_allowed(path, repo)
        assert check_path(path, repo, location=True) == 'prefix'


@pytest.mark.parametrize('path, code', [
    ('../../etc/tim/database-password', 'syntax'),
    ('src/../data/x.json', 'syntax'),
    ('/etc/passwd', 'syntax'),
    ('-rf', 'syntax'),
    ('src/-x.py', 'syntax'),
    ('src//x.py', 'syntax'),
    ('src/./x.py', 'syntax'),
    ('src/', 'syntax'),
    ('src/a b.py', 'syntax'),
    ('src/a\nb.py', 'syntax'),
    ('src/ä.py', 'syntax'),
    ('x' * 201, 'syntax'),
    ('', 'syntax'),
    (None, 'syntax'),
    ('data/operational/server_health.json', 'prefix'),
    ('artifacts/x.json', 'prefix'),
    ('.git/config', 'prefix'),
    ('src/.git/config', 'blocked'),
    ('src/data/x.py', 'blocked'),
    ('config/secrets.py', 'blocked'),
    ('scripts/provision_tim_daemon_secret.py', 'blocked'),
    ('src/github_token.py', 'blocked'),
    ('docs/Password.md', 'blocked'),
    ('docs/credential_reproduction.md', 'blocked'),
    ('ops/tls/server.pem', 'blocked'),
    ('ops/tls/server.KEY', 'blocked'),
    ('ops/systemd/tim.env', 'blocked'),
    ('ops/.env', 'blocked'),
    ('ops/.env.local', 'blocked'),
    ('ops/.envrc', 'blocked'),
    ('ops/.env.example/x.py', 'blocked'),
    ('ops/key.pem.example', 'blocked'),
    ('ops/tls/server.key.bak', 'blocked'),
    ('README.md', 'prefix'),
    ('setup.py', 'prefix'),
    ('requirements/../x.txt', 'syntax'),
])
def test_path_rules(path, code):
    assert check_path(path, None) == code
    assert not path_allowed(path, None)


def test_path_file_checks(repo):
    assert check_path('src/link.py', repo) == 'symlink'
    assert check_path('src/datalink/operational/server_health.json', repo) == 'symlink'
    assert check_path('docs/up/outside.txt', repo) == 'symlink'
    assert check_path('src/fifo.py', repo) == 'not_regular'
    assert check_path('docs/sub', repo) == 'not_regular'
    assert check_path('src/missing.py', repo) == 'missing'
    assert check_path('src/data_ingestion/catchup.py/x', repo) == 'not_regular'


def test_symlinked_root_is_followed_but_nothing_below(tmp_path, repo):
    alias = tmp_path / 'alias'
    os.symlink(repo, alias)
    assert check_path('src/data_ingestion/catchup.py', alias) is None


def test_read_beneath_refuses_symlinks_and_never_quotes(repo):
    for path in ('src/link.py', 'src/datalink/operational/server_health.json', 'docs/up/outside.txt'):
        with pytest.raises(ProtocolError) as caught:
            read_beneath(repo, path)
        assert caught.value.code in ('symlink', 'not_regular')
        assert SECRET not in str(caught.value) and path not in str(caught.value)
    with pytest.raises(ProtocolError) as caught:
        read_beneath(repo, 'config/secrets.py')
    assert caught.value.code == 'bad_name'
    with pytest.raises(ProtocolError):
        read_beneath(repo, 'src/fifo.py')                # O_NONBLOCK: no hang on a FIFO
    with pytest.raises(ProtocolError) as caught:
        read_beneath(repo, 'src/data_ingestion/catchup.py', max_bytes=10)
    assert caught.value.code == 'too_large'
    with pytest.raises(ProtocolError) as caught:
        read_beneath(repo, 'src/data_ingestion/catchup.py', expected_uid=UID + 1)
    assert caught.value.code == 'wrong_owner'


def test_verify_locations(repo):
    kept, removed = verify_locations([
        {'path': 'src/data_ingestion/catchup.py', 'line': 30, 'why': 'ok'},
        {'path': 'src/data_ingestion/catchup.py', 'line': 31, 'why': 'past the end'},
        {'path': 'src/link.py', 'line': 1, 'why': 'symlink'},
        {'path': 'requirements.txt', 'line': 1, 'why': 'not a location prefix'},
        {'path': 'src/missing.py', 'line': 1, 'why': 'missing'},
        {'path': 'src/data_ingestion/catchup.py', 'line': True, 'why': 'bool'},
    ], repo)
    assert kept == [{'path': 'src/data_ingestion/catchup.py', 'line': 30, 'why': 'ok'}] and removed == 5
    assert line_count(b'') == 0 and line_count(b'a') == 1 and line_count(b'a\nb\n') == 2


# --- safe_read -----------------------------------------------------------------------------------------------------------------

def test_safe_read_checks_before_reading(tmp_path):
    good = tmp_path / 'good.json'
    good.write_bytes(b'{}')
    assert safe_read(good, UID, 100) == b'{}'
    cases = {}
    link = tmp_path / 'link.json'
    os.symlink(good, link)
    cases['symlink'] = link
    big = tmp_path / 'big.json'
    big.write_bytes(SECRET.encode() * 100)
    cases['too_large'] = big
    fifo = tmp_path / 'fifo.json'
    os.mkfifo(fifo)
    cases['not_regular'] = fifo
    hard = tmp_path / 'hard.json'
    os.link(good, hard)
    cases['linked'] = hard
    cases['unreadable'] = tmp_path / 'missing.json'
    cases['not_regular_dir'] = tmp_path
    for code, path in cases.items():
        with pytest.raises(ProtocolError) as caught:
            safe_read(path, UID, 100)
        assert caught.value.code == code.replace('_dir', ''), code
        assert SECRET not in str(caught.value) and str(path) not in str(caught.value)
        assert str(caught.value) in ERROR_TEXTS.values()


def test_safe_read_owner(tmp_path):
    path = tmp_path / 'r.json'
    path.write_bytes(b'{}')
    with pytest.raises(ProtocolError) as caught:
        safe_read(path, UID + 4242, 100)
    assert caught.value.code == 'wrong_owner'
    if UID == 0:
        os.chown(path, 4242, -1)
        assert safe_read(path, 4242, 100) == b'{}'
        with pytest.raises(ProtocolError):
            safe_read(path, 0, 100)


# --- atomic_write ---------------------------------------------------------------------------------------------------------------

def test_atomic_write(tmp_path):
    written = atomic_write(tmp_path, 'a.json', b'one', 0o640)
    assert written == tmp_path / 'a.json' and written.read_bytes() == b'one'
    assert stat.S_IMODE(os.stat(written).st_mode) == 0o640
    atomic_write(tmp_path, 'a.json', b'two', 0o600)
    assert written.read_bytes() == b'two' and stat.S_IMODE(os.stat(written).st_mode) == 0o600
    assert sorted(os.listdir(tmp_path)) == ['a.json']          # no temp file left


def test_atomic_write_replaces_symlink_not_target(tmp_path):
    target = tmp_path / 'target'
    target.write_bytes(b'keep')
    os.symlink(target, tmp_path / 'a.json')
    atomic_write(tmp_path, 'a.json', b'new')
    assert target.read_bytes() == b'keep'
    assert not (tmp_path / 'a.json').is_symlink() and (tmp_path / 'a.json').read_bytes() == b'new'


@pytest.mark.parametrize('name', ['../x', 'a/b', '.hidden', '', 'x' * 101, None])
def test_atomic_write_rejects_names(tmp_path, name):
    with pytest.raises(ProtocolError) as caught:
        atomic_write(tmp_path, name, b'x')
    assert caught.value.code == 'bad_name'


def test_atomic_write_refuses_symlinked_directory(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    os.symlink(real, tmp_path / 'linkdir')
    with pytest.raises(ProtocolError) as caught:
        atomic_write(tmp_path / 'linkdir', 'a.json', b'x')
    assert caught.value.code == 'write_failed' and not os.listdir(real)
    with pytest.raises(ProtocolError):
        atomic_write(tmp_path / 'missing', 'a.json', b'x')


# --- requests/ and results/ queues -------------------------------------------------------------------------------------------

def test_queue_roundtrip(tmp_path):
    requests_dir, results_dir = tmp_path / 'requests', tmp_path / 'results'
    requests_dir.mkdir()
    results_dir.mkdir()
    first = request()
    second = request(rid='20261001T0000Z-data-flow-1', episode='20261001T0000Z')
    write_request(requests_dir, second)
    write_request(requests_dir, first)
    (requests_dir / 'junk.json').write_text('{}')
    (requests_dir / '.20260930T0312Z-data-flow-2.json.abc.tmp').write_text('{}')
    assert list_rids(requests_dir) == [first['rid'], second['rid']]
    assert pending_rids(requests_dir, results_dir) == [first['rid'], second['rid']]
    assert read_request(requests_dir, first['rid'], expected_uid=UID,
                        allowed_units=POLICY.agent.units_allowlist) == first
    write_result(results_dir, result(), fetch_domains=DOMAINS)
    assert pending_rids(requests_dir, results_dir) == [second['rid']]
    assert read_result(results_dir, first['rid'], expected_uid=UID, fetch_domains=DOMAINS) == result()
    write_ack(requests_dir, second['rid'], NOW)
    assert pending_rids(requests_dir, results_dir) == []
    assert json.loads((requests_dir / ack_name(second['rid'])).read_text())['acked_at'] == '2026-09-30T03:20:00Z'


def test_read_request_rejects_renamed_file(tmp_path):
    write_request(tmp_path, request())
    os.rename(tmp_path / request_name(request()['rid']), tmp_path / '20260930T0312Z-data-flow-7.json')
    with pytest.raises(ProtocolError):
        read_request(tmp_path, '20260930T0312Z-data-flow-7', expected_uid=UID)


def test_write_result_validates_first(tmp_path):
    with pytest.raises(ProtocolError):
        write_result(tmp_path, result(summary=''))
    with pytest.raises(ProtocolError):
        write_result(tmp_path, result(sources=['https://evil.example/'], fetched_urls=['https://evil.example/']),
                     fetch_domains=DOMAINS)
    assert not os.listdir(tmp_path)


def test_read_result_symlink_into_foreign_file(tmp_path):
    foreign = tmp_path / 'foreign.json'
    foreign.write_text(json.dumps(result()))
    os.symlink(foreign, tmp_path / result_name(result()['rid']))
    with pytest.raises(ProtocolError) as caught:
        read_result(tmp_path, result()['rid'], expected_uid=UID)
    assert caught.value.code == 'symlink'


# --- HOLD and PAUSE ------------------------------------------------------------------------------------------------------------

def test_hold(tmp_path):
    assert not hold_active(tmp_path)
    write_hold(tmp_path, NOW)
    assert hold_active(tmp_path)
    assert clear_hold(tmp_path) and not hold_active(tmp_path) and not clear_hold(tmp_path)
    os.symlink(tmp_path / 'nowhere', tmp_path / HOLD)          # even a dangling link holds (fail-closed)
    assert hold_active(tmp_path)


def test_pause(tmp_path):
    assert not pause_active(tmp_path, NOW, expected_uid=UID) and read_pause(tmp_path, expected_uid=UID) is None
    write_pause(tmp_path, NOW + timedelta(hours=24), 'breaker')
    assert read_pause(tmp_path, expected_uid=UID) == {'version': 1, 'reason': 'breaker',
                                                      'until': '2026-10-01T03:20:00Z'}
    assert pause_active(tmp_path, NOW, expected_uid=UID)
    assert not pause_active(tmp_path, NOW + timedelta(hours=25), expected_uid=UID)
    with pytest.raises(ValueError):
        write_pause(tmp_path, NOW, 'because')


@pytest.mark.parametrize('content', [b'', b'{', b'{"version":1,"reason":"breaker"}',
                                     b'{"version":1,"reason":"x","until":"2026-10-01T03:20:00Z"}',
                                     b'{"version":1,"reason":"label","until":"tomorrow"}', b'x' * 2000])
def test_unreadable_pause_counts_as_active(tmp_path, content):
    (tmp_path / PAUSE).write_bytes(content)
    assert pause_active(tmp_path, NOW, expected_uid=UID)


def test_pause_of_wrong_owner_counts_as_active(tmp_path):
    write_pause(tmp_path, NOW - timedelta(hours=1), 'label')
    assert not pause_active(tmp_path, NOW, expected_uid=UID)
    assert pause_active(tmp_path, NOW, expected_uid=UID + 1)


# --- error texts ---------------------------------------------------------------------------------------------------------------

def test_error_texts_are_fixed():
    assert str(ProtocolError('too_large')) == ERROR_TEXTS['too_large']
    assert ProtocolError('anything else').code == 'schema'
    for text in list(ERROR_TEXTS.values()) + list(FAILURE_TEXTS.values()):
        assert not final_scan(text) and '{' not in text


def test_validation_returns_copies():
    data = request()
    checked = validate_request(data)
    checked['journal']['tim-runtime.service'].append('mutated')
    assert data == request()
    original = result()
    copy_ = validate_result(copy.deepcopy(original))
    copy_['locations'][0]['why'] = 'mutated'
    assert original == result()
