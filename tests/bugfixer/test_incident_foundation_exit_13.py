"""Exit gate of #13 (Incident Foundation), end to end through the public store API.

A sanitized normalized failure deterministically produces one persisted incident, recurrences aggregate,
the class is deterministic or UNKNOWN, and every incident is linked to a durable task, also after a restart.
"""
import json

import pytest

from src.bugfixer.processing import Event, fingerprint
from src.bugfixer.store import IncidentStore
from src.bugfixer.tasks import TaskState
from src.collection_reporting.errors import ErrorClass

AT = '2026-10-25T10:00:00+00:00'
LATER = '2026-10-25T10:05:00+00:00'


def ev(message, exception='TimeoutError', at=AT, component='collector'):
    return Event(at, component, exception, message)


def test_one_failure_is_one_persisted_incident_with_one_task_across_restart(tmp_path):
    path = tmp_path / 'observer.sqlite3'
    store = IncidentStore(path, code_version='a'*40)
    with store.transaction():
        first = store.record(ev('network timeout talking to exchange api_key=fixtureSECRET'))
    task_id = store.task_for_incident(first).id
    store.close()

    store = IncidentStore(path, code_version='a'*40)      # restart
    try:
        with store.transaction():
            again = store.record(ev('network timeout talking to exchange api_key=fixtureSECRET', at=LATER))
        assert again == first == fingerprint(ev('network timeout talking to exchange api_key=fixtureSECRET'))
        incident = store.inspect(first)
        assert incident['occurrence_count'] == 2 and incident['suppressed_duplicate_count'] == 1
        assert incident['first_seen'] == AT and incident['last_seen'] == LATER
        assert store.task_for_incident(first).id == task_id     # recurrence before resolution: same task
        assert len(store.list()) == 1
        assert b'fixtureSECRET' not in path.read_bytes()
    finally:
        store.close()


def test_different_failures_stay_separate_incidents_with_separate_tasks(tmp_path):
    store = IncidentStore(tmp_path / 'observer.sqlite3')
    try:
        with store.transaction():
            a = store.record(ev('network timeout talking to exchange'))
            b = store.record(ev('division by zero in resampler', exception='ZeroDivisionError', component='resampler'))
        assert a != b
        assert store.task_for_incident(a).id != store.task_for_incident(b).id
    finally:
        store.close()


def test_unknown_is_never_guessed_and_its_task_is_stopped(tmp_path):
    store = IncidentStore(tmp_path / 'observer.sqlite3')
    try:
        with store.transaction():
            identity = store.record(ev('the frobnicator emitted a quux', exception='WeirdThing', component='x'))
        incident = store.inspect(identity)
        assert incident['category'] == ErrorClass.UNKNOWN
        assert incident['state'] == 'SAFE_STOP'
        assert store.task_for_incident(identity).state is TaskState.SAFE_STOP
    finally:
        store.close()


def test_classification_is_deterministic_across_stores(tmp_path):
    samples = [ev('network timeout talking to exchange'),
               ev('division by zero in resampler', exception='ZeroDivisionError'),
               ev('the frobnicator emitted a quux', exception='WeirdThing')]
    seen = []
    for name in ('a', 'b'):
        store = IncidentStore(tmp_path / f'{name}.sqlite3')
        try:
            with store.transaction():
                ids = [store.record(sample) for sample in samples]
            seen.append([(i, store.inspect(i)['category'], store.inspect(i)['matched_rule']) for i in ids])
        finally:
            store.close()
    assert seen[0] == seen[1]
    assert all(category in set(ErrorClass) for _, category, _ in seen[0])


def test_every_required_incident_class_exists():
    required = {'TRANSIENT', 'RETRYABLE', 'DATA_QUALITY', 'TERMINAL_BLOCKED', 'CONFIGURATION', 'CREDENTIAL',
                'DATABASE', 'NETWORK', 'INVARIANT_VIOLATION', 'SOFTWARE_BUG', 'ENVIRONMENT', 'UNKNOWN'}
    assert {c.value for c in ErrorClass} == required


def test_recording_outside_a_transaction_is_refused(tmp_path):
    store = IncidentStore(tmp_path / 'observer.sqlite3')
    try:
        with pytest.raises(RuntimeError):
            store.record(ev('network timeout'))
        assert store.list() == []
    finally:
        store.close()


def test_evidence_kept_with_the_incident_is_the_sanitized_event(tmp_path):
    store = IncidentStore(tmp_path / 'observer.sqlite3')
    try:
        with store.transaction():
            identity = store.record(ev('db error postgresql://u:fixturePW@host/tim'))
        evidence = json.loads(store.inspect(identity)['evidence'])
        assert 'fixturePW' not in json.dumps(evidence)
        assert evidence['component'] == 'collector'
    finally:
        store.close()
