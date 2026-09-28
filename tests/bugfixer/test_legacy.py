import json

import pytest

from src.bugfixer.store import IncidentStore
from src.bugfixer.worker import ErrorLogWorker, ObservationBlocked


def test_traceback_survives_database_close_and_reopen_without_secret(tmp_path):
    path, source = tmp_path / 'observer.db', tmp_path / 'error.log'
    source.write_text('Traceback (most recent call last):\n  File "worker.py", line 12, in run\n'
                      '    password = "fixtureSecret"\nTimeoutError: network timeout\n')
    store = IncidentStore(path)
    worker = ErrorLogWorker(store, source, max_records=3)
    assert worker.poll()['events_ingested'] == 0
    pending = store.checkpoint(worker.source_id)['pending_trace']
    assert 'fixtureSecret' not in json.dumps(pending)
    assert b'fixtureSecret' not in path.read_bytes()
    store.close()
    store = IncidentStore(path)
    try:
        assert ErrorLogWorker(store, source).poll()['events_ingested'] == 1
        rows = store.list()
        assert len(rows) == 1 and rows[0]['category'] == 'NETWORK'
        evidence = json.loads(rows[0]['evidence'])
        assert evidence['exception'] == 'TimeoutError'
        assert 'worker.py' in evidence['stack']
        assert 'fixtureSecret' not in evidence['stack']
        assert ErrorLogWorker(store, source).poll()['events_ingested'] == 0
    finally:
        store.close()


def test_incomplete_trace_is_preserved_until_terminal_line(tmp_path):
    path, source = tmp_path / 'observer.db', tmp_path / 'error.log'
    source.write_text('Traceback (most recent call last):\n  File "worker.py", line 12\n')
    store = IncidentStore(path)
    try:
        worker = ErrorLogWorker(store, source)
        worker.poll()
        worker.poll()
        assert store.status()['events_ingested'] == 0
        with source.open('a') as output:
            output.write('ValueError: invalid price\n')
        assert worker.poll()['events_ingested'] == 1
        assert store.list()[0]['category'] == 'DATA_QUALITY'
    finally:
        store.close()


def test_new_record_boundary_escalates_incomplete_trace(tmp_path):
    path, source = tmp_path / 'observer.db', tmp_path / 'error.log'
    source.write_text('Traceback (most recent call last):\n  File "worker.py", line 12\n'
                      '{"component":"collector","message":"network timeout"}\n')
    store = IncidentStore(path)
    try:
        assert ErrorLogWorker(store, source).poll()['events_ingested'] == 2
        assert {row['state'] for row in store.list()} == {'SAFE_STOP', 'CLASSIFIED'}
    finally:
        store.close()


def test_trace_budget_failure_preserves_prior_checkpoint(tmp_path):
    path, source = tmp_path / 'observer.db', tmp_path / 'error.log'
    source.write_text('Traceback (most recent call last):\n' + '  frame\n' * 130)
    store = IncidentStore(path)
    try:
        worker = ErrorLogWorker(store, source)
        with pytest.raises(ObservationBlocked):
            worker.poll()
        assert store.checkpoint(worker.source_id) is None
        assert store.list() == []
    finally:
        store.close()
