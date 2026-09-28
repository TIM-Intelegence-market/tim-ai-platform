from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.bugfixer.processing import Event, fingerprint, parse_line, redact_text
from src.bugfixer.replay import replay
from src.bugfixer.safety import Policy, SafetyViolation, require_isolated_database
from src.bugfixer.remediation import dry_run, load_registry
from src.bugfixer.store import IncidentStore
from src.bugfixer.__main__ import main

AT = '2026-09-09T00:00:00+00:00'
ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / 'schemas/bugfixer/remediations.v1.json'


@pytest.mark.parametrize('field', ['live_trading', 'execution', 'auto_remediate', 'mutate_queue',
    'mutate_outbox', 'reset_attempts', 'skip_events'])
def test_unsafe_action_fails_closed(field):
    with pytest.raises(SafetyViolation):
        replace(Policy(), **{field: True}).verify()


@pytest.mark.parametrize('field', ['strict_ordering', 'determinism', 'lookahead_safety'])
def test_safety_invariants_cannot_be_disabled(field):
    with pytest.raises(SafetyViolation):
        replace(Policy(), **{field: False}).verify()


@pytest.mark.parametrize('host', ['localhost', '127.0.0.1', '[::1]', 'LOCALHOST.'])
def test_same_database_rejected_despite_different_credentials_or_host_alias(host):
    with pytest.raises(SafetyViolation, match='runtime database'):
        require_isolated_database(f'postgresql://test:fixture@{host}/tim_test',
                                  'postgresql://runtime:different@localhost:5432/tim_test')


def test_explicit_separate_database_and_ambiguous_query():
    assert require_isolated_database('postgresql://test:fixture@localhost/tim_test',
                                     'postgresql://runtime:fixture@localhost/tim')[-1] == 'tim_test'
    with pytest.raises(SafetyViolation):
        require_isolated_database('postgresql://u:p@localhost/tim_test?host=production',
                                  'postgresql://u:p@localhost/tim')


def test_replay_is_deterministic_and_enforces_order_and_cutoff():
    first = Event(AT, 'collector', 'TimeoutError', 'network timeout')
    later = replace(first, timestamp='2026-09-09T01:00:00+00:00')
    assert replay([first], cutoff=AT) == replay([first], cutoff=AT)
    with pytest.raises(ValueError, match='cutoff'):
        replay([later], cutoff=AT)
    with pytest.raises(ValueError, match='out-of-order'):
        replay([later, first], cutoff=later.timestamp)
    assert replay([first], cutoff=AT)['production_bug_reproduced'] is False


@pytest.mark.parametrize('message', ['password=fixture', 'password="with spaces"',
    'Authorization: Bearer fixture', 'postgresql://user:fixture@localhost/tim', 'token=[REDACTED]'])
def test_redaction_and_persisted_fingerprint_are_idempotent(message):
    first = redact_text(message)
    assert redact_text(first) == first
    raw = Event(AT, 'collector', '', message)
    restored = Event(**raw.safe_dict())
    assert fingerprint(raw) == fingerprint(restored)


def test_registry_matches_only_proposals_and_rejects_unsafe_entries(tmp_path):
    entries = load_registry(REGISTRY)
    event = Event(AT, 'collector', 'TimeoutError', 'timeout')
    proposal = dry_run(event, entries)
    assert proposal['proposals'][0]['id'] == 'NETWORK_TIMEOUT_V1'
    assert proposal['executed'] is False
    bad = tmp_path / 'registry.json'
    entries[0]['autonomy'] = 'A3'
    bad.write_text(json.dumps({'schema_version': 1, 'entries': entries}))
    with pytest.raises(ValueError):
        load_registry(bad)


def test_cli_observe_inspect_replay_and_verify(tmp_path, capsys):
    path, source = tmp_path / 'observer.db', tmp_path / 'error.log'
    source.write_text(json.dumps({'timestamp': AT, 'component': 'collector',
                                 'exception_type': 'TimeoutError', 'message': 'timeout token=fixture'}) + '\n')
    base = ['--store', str(path)]
    assert main(base + ['observe', '--source', str(source)]) == 0
    capsys.readouterr()
    assert main(base + ['list']) == 0
    row = json.loads(capsys.readouterr().out)[0]
    assert 'fixture' not in str(row)
    for command in ('inspect', 'classify'):
        assert main(base + [command, row['id']]) == 0
        capsys.readouterr()
    assert main(base + ['reproduce', row['id'], '--cutoff', AT]) == 0
    replay_result = json.loads(capsys.readouterr().out)
    assert replay_result['events'][0]['fingerprint'] == row['id']
    assert main(base + ['remediation-dry-run', row['id'], '--registry', str(REGISTRY)]) == 0
    assert json.loads(capsys.readouterr().out)['executed'] is False
    assert main(base + ['verify']) == 0
    assert json.loads(capsys.readouterr().out)['observer_store_integrity'] == 'ok'


def test_resume_across_two_independent_processes(tmp_path):
    source, store = tmp_path / 'error.log', tmp_path / 'observer.db'
    source.write_text('network timeout\n')
    command = [sys.executable, '-m', 'src.bugfixer', '--store', str(store), 'observe', '--source', str(source)]
    first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert first.returncode == 0
    with source.open('a') as f:
        f.write('network timeout\n')
    second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert second.returncode == 0
    assert json.loads(second.stdout)['events_ingested'] == 1
    db = IncidentStore(store)
    try:
        assert db.status()['events_ingested'] == 2
        assert len(db.list()) == 1
    finally:
        db.close()


def test_abrupt_process_exit_rolls_back_uncommitted_event_and_cursor(tmp_path):
    path = tmp_path / 'crash.sqlite3'
    script = '''
import os, sys
from pathlib import Path
from src.bugfixer.store import IncidentStore
from src.bugfixer.processing import Event
s = IncidentStore(Path(sys.argv[1]))
with s.transaction():
    s.record(Event('2026-09-09T00:00:00+00:00', 'collector', '', 'timeout'))
    s.save_checkpoint('fixture', {'offset': 123})
    os._exit(73)
'''
    result = subprocess.run([sys.executable, '-c', script, str(path)], cwd=ROOT,
                            capture_output=True, timeout=15)
    assert result.returncode == 73
    store = IncidentStore(path)
    try:
        assert store.list() == []
        assert store.checkpoint('fixture') is None
        assert store.db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        store.close()


def test_historical_launchd_failure_is_classified_without_starting_service():
    event = Event(AT, 'launchd', '', 'EX_CONFIG 78 StandardErrorPath inaccessible')
    from src.bugfixer.processing import classify
    assert classify(event).category == 'CONFIGURATION'
    result = dry_run(event, load_registry(REGISTRY))
    assert result['proposals'][0]['id'] == 'LAUNCHD_LOG_PATH_V1'
    assert result['executed'] is False
