from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading

import pytest

from src.bugfixer.model import State, validate_transition
from src.bugfixer.processing import Event, fingerprint, parse_line, redact, classify
from src.bugfixer.store import IncidentStore
from src.bugfixer.worker import ErrorLogWorker, ObservationBlocked

AT = '2026-09-09T00:00:00+00:00'


def event(message='network timeout', **kwargs):
    return Event(AT, 'collector', 'TimeoutError', message, **kwargs)


@pytest.fixture
def store(tmp_path):
    instance = IncidentStore(tmp_path / 'observer.sqlite3')
    yield instance
    instance.close()


@pytest.mark.parametrize('target', [State.RESOLVED, State.FIX_TESTING, State.ROOT_CAUSE_FOUND])
def test_cannot_skip_evidence_lifecycle(target):
    with pytest.raises(ValueError):
        validate_transition(State.NEW, target, 'claim')


def test_lifecycle_requires_evidence():
    with pytest.raises(ValueError):
        validate_transition(State.NEW, State.NORMALIZED, '')
    assert validate_transition(State.CLASSIFIED, State.INVESTIGATING, 'review') == State.INVESTIGATING


@pytest.mark.parametrize('secret', ['password="fixture with spaces"', 'api_key=fixtureABC',
    'Authorization: Bearer fixtureABC', 'Cookie: session=fixtureABC',
    'postgresql://user:fixtureABC@localhost/tim',
    '-----BEGIN PRIVATE KEY-----\nfixtureABC\n-----END PRIVATE KEY-----'])
def test_secret_redaction(secret, store):
    sample = event('network timeout ' + secret)
    with store.transaction():
        store.record(sample)
    assert b'fixture' not in store.path.read_bytes()
    assert 'fixture' not in json.dumps(store.list())


def test_nested_json_and_direct_event_are_redacted():
    assert 'fixture' not in json.dumps(redact({'nested': [{'api-key': 'fixture'}]}))
    parsed = parse_line(json.dumps({'timestamp': AT, 'message': 'timeout',
                                    'stack': {'token': 'fixture'}}), AT)
    assert 'fixture' not in str(parsed)


def test_fingerprint_stable_but_preserves_semantic_codes():
    first = event('timeout at 2026-09-08T01:00:00Z request 123e4567-e89b-12d3-a456-426614174000')
    second = event('timeout at 2026-09-09T01:00:00Z request 123e4567-e89b-12d3-a456-426614174001')
    assert fingerprint(first) == fingerprint(second)
    assert fingerprint(event(code='401')) != fingerprint(event(code='403'))
    assert fingerprint(event('invalid price 0')) != fingerprint(event('invalid price -1'))


def test_unknown_escalates_and_critical_stops(store):
    with store.transaction():
        unknown = store.record(Event(AT, 'x', '', 'unexpected frobnication'))
        critical = store.record(event('out-of-order invariant'))
    assert store.inspect(unknown)['state'] == 'SAFE_STOP'
    assert store.task_for_incident(unknown).state == 'SAFE_STOP'
    assert store.inspect(critical)['state'] == 'SAFE_STOP'
    assert store.status()['auto_remediate'] is False


def test_storm_has_one_incident_and_bounded_history(store):
    with store.transaction():
        for _ in range(2500):
            identity = store.record(event())
    row = store.inspect(identity)
    assert row['occurrence_count'] == 2500
    assert row['suppressed_count'] == 2499
    assert len(store.list()) == 1
    assert store.db.execute('SELECT count(*) FROM history').fetchone()[0] == 2


def test_rollback_occurrences_and_cursor_together(store):
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.record(event())
            store.save_checkpoint('log', {'offset': 33})
            raise RuntimeError('simulated crash before commit')
    assert store.list() == [] and store.checkpoint('log') is None


def test_recurrence_reopens_resolved_incident(store, tmp_path):
    from src.bugfixer.tasks import TaskState
    from tests.bugfixer.repair_fixture import evidence
    with store.transaction():
        identity = store.record(event())
        task = store.task_for_incident(identity)
        store.plan_task(task.id, git_sha='a'*40)
        for state in (TaskState.PLANNED, TaskState.READY, TaskState.IN_PROGRESS, TaskState.VERIFYING):
            task = store.transition_task(task.id,state,reason='synthetic lifecycle',next_action='verify synthetic evidence')
        store.transition_task(task.id,TaskState.FIXED,reason='synthetic verified fixture',next_action='monitor recurrence',evidence=evidence(tmp_path,task))
        assert store.inspect(identity)['state'] == State.RESOLVED
        store.record(event())
    assert store.inspect(identity)['state'] == State.INVESTIGATING


def test_plain_text_cannot_resolve_incident(store):
    with store.transaction():
        identity = store.record(event())
        for target in (State.INVESTIGATING, State.REPRODUCED, State.ROOT_CAUSE_FOUND, State.FIX_PROPOSED, State.FIX_TESTING):
            store.transition(identity,target,'synthetic setup')
        with pytest.raises(ValueError,match='verified FIXED'):
            store.transition(identity,State.RESOLVED,'test evidence')


def test_existing_application_database_is_rejected_without_mutation(tmp_path):
    path = tmp_path / 'foreign.db'
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE original (value TEXT)')
    connection.close()
    before = path.read_bytes()
    with pytest.raises(ValueError, match='not a bugfixer'):
        IncidentStore(path)
    assert before == path.read_bytes()


def test_worker_restart_partial_line_and_backpressure(store, tmp_path):
    log = tmp_path / 'errors.log'
    log.write_bytes(b'network timeout\nnetwork timeout\npart')
    assert ErrorLogWorker(store, log, max_records=1).poll()['events_ingested'] == 1
    assert ErrorLogWorker(store, log).poll()['events_ingested'] == 1
    assert ErrorLogWorker(store, log).poll()['events_ingested'] == 0
    with log.open('ab') as handle:
        handle.write(b'ial error\n')
    assert ErrorLogWorker(store, log).poll()['events_ingested'] == 1
    assert store.status()['events_ingested'] == 3


def test_rotation_preserves_committed_state_and_requires_reconciliation(store, tmp_path):
    log = tmp_path / 'errors.log'
    log.write_text('network timeout\n')
    worker = ErrorLogWorker(store, log)
    worker.poll()
    log.rename(tmp_path / 'errors.log.1')
    log.write_text('new error\n')
    with pytest.raises(ObservationBlocked, match='rotation'):
        worker.poll()
    assert store.status()['events_ingested'] == 1


@pytest.mark.parametrize('replacement', ['x\n', 'other timeout\nlonger data\n'])
def test_truncation_and_rewrite_never_silently_advance(store, tmp_path, replacement):
    log = tmp_path / 'errors.log'
    log.write_text('network timeout\n')
    worker = ErrorLogWorker(store, log)
    worker.poll()
    before = store.checkpoint(worker.source_id)
    log.write_text(replacement)
    with pytest.raises(ObservationBlocked):
        worker.poll()
    assert store.checkpoint(worker.source_id) == before


def test_recursion_info_and_multiline_private_key_guard(store, tmp_path):
    log = tmp_path / 'errors.log'
    log.write_text('\n'.join([json.dumps({'component': 'bugfixer.worker', 'message': 'own error'}),
        json.dumps({'severity': 'INFO', 'message': 'normal'}), '-----BEGIN PRIVATE KEY-----',
        'fixtureKEYBODY', '-----END PRIVATE KEY-----', 'network timeout']) + '\n')
    worker = ErrorLogWorker(store, log, max_records=1)
    for _ in range(6):
        worker.poll()
    assert store.status()['events_ingested'] == 1
    assert b'fixtureKEYBODY' not in store.path.read_bytes()


def test_oversize_rolls_back_entire_poll(store, tmp_path):
    log = tmp_path / 'errors.log'
    log.write_text('network timeout\n' + 'x' * 150 + '\n')
    worker = ErrorLogWorker(store, log, max_line_bytes=128)
    with pytest.raises(ObservationBlocked):
        worker.poll()
    assert not store.list() and store.checkpoint(worker.source_id) is None


def test_stop_before_run_performs_no_reads(store, tmp_path):
    stop = threading.Event()
    stop.set()
    ErrorLogWorker(store, tmp_path / 'absent.log').run(stop)
    assert not store.list()
