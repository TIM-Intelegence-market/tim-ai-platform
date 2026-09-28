"""Offline regression coverage for classification and observer recursion guards."""
import json

import pytest

from src.bugfixer.processing import Event, canonical, classify, fingerprint, parse_line
from src.bugfixer.store import IncidentStore
from src.bugfixer.worker import ErrorLogWorker
from src.collection_reporting.errors import ErrorClass, classify_error


AT = '2026-09-10T00:00:00+00:00'
PREFIX = '2026-09-10 02:00:00,123 ERROR '


@pytest.mark.parametrize('component', [
    'bugfixer', 'bugfixer.worker', 'src.bugfixer', 'src.bugfixer.worker',
])
def test_python_logging_suppresses_exact_observer_namespaces(component):
    assert parse_line(PREFIX + component + ' storage failure', AT) is None


@pytest.mark.parametrize('component', [
    'collector', 'bugfixer_monitor', 'src.bugfixer_backup', 'other.bugfixer.worker',
])
def test_observer_mentions_and_similarly_named_components_remain_visible(component):
    event = parse_line(PREFIX + component + ' bugfixer.worker failed to inspect this error', AT)
    assert event.component == component
    assert event.message == 'bugfixer.worker failed to inspect this error'


@pytest.mark.parametrize('identity', [
    {'component': 'bugfixer'},
    {'component': 'src.bugfixer.worker'},
    {'logger': 'bugfixer.worker'},
    {'logger': 'src.bugfixer.worker'},
    {'component': 'storage', 'logger': 'src.bugfixer.store'},
    {'component': 'storage', 'origin': 'tim_bugfixer'},
])
def test_json_identity_recursion_guards_remain_compatible(identity):
    assert parse_line(json.dumps({**identity, 'message': 'write failed'}), AT) is None


def test_json_incidental_origin_and_message_mentions_do_not_hide_other_errors():
    event = parse_line(json.dumps({
        'component': 'collector', 'logger': 'src.bugfixer_backup',
        'origin': 'tim_bugfixer_backup', 'message': 'tim_bugfixer service unavailable',
    }), AT)
    assert event is not None and event.component == 'collector'


def test_worker_filters_self_errors_across_restart_without_hiding_redacted_external_error(tmp_path):
    log = tmp_path / 'errors.log'
    log.write_text('\n'.join([
        PREFIX + 'src.bugfixer.worker own failure token=fixture-private-token',
        PREFIX + 'bugfixer own failure',
        json.dumps({'origin': 'tim_bugfixer', 'message': 'own failure'}),
        PREFIX + 'collector bugfixer unavailable token=fixture-private-token',
    ]) + '\n')
    path = tmp_path / 'observer.sqlite3'
    store = IncidentStore(path)
    try:
        assert ErrorLogWorker(store, log).poll()['events_ingested'] == 1
        rows = store.list()
        assert len(rows) == 1
        assert 'fixture-private-token' not in json.dumps(rows)
    finally:
        store.close()
    reopened = IncidentStore(path)
    try:
        assert ErrorLogWorker(reopened, log).poll()['events_ingested'] == 0
        assert len(reopened.list()) == 1
    finally:
        reopened.close()
    assert b'fixture-private-token' not in path.read_bytes()


@pytest.mark.parametrize('exception,message,category', [
    ('', 'rate limit', ErrorClass.TRANSIENT),
    ('RetryableError', 'request rejected', ErrorClass.RETRYABLE),
    ('ValueError', 'invalid price', ErrorClass.DATA_QUALITY),
    ('ValueError', 'out-of-order trade', ErrorClass.TERMINAL_BLOCKED),
    ('', 'EX_CONFIG missing environment', ErrorClass.CONFIGURATION),
    ('', 'authentication failed', ErrorClass.CREDENTIAL),
    ('', 'database deadlock', ErrorClass.DATABASE),
    ('TimeoutError', 'request timed out', ErrorClass.NETWORK),
    ('', 'hash mismatch', ErrorClass.INVARIANT_VIOLATION),
    ('NameError', "name 'Any' is not defined", ErrorClass.SOFTWARE_BUG),
    ('OSError', '[Errno 48] Address already in use', ErrorClass.ENVIRONMENT),
    ('ValueError', 'unexpected frobnication', ErrorClass.UNKNOWN),
])
def test_every_required_incident_category_has_a_deterministic_result(exception, message, category):
    event = Event(AT, 'collector', exception, message)
    result = classify(event)
    assert result.category is category
    assert result == classify(event)
    assert result.confidence == (0 if category is ErrorClass.UNKNOWN else .9)


@pytest.mark.parametrize('exception,message,category', [
    ('NameError', "name 'network' is not defined", ErrorClass.SOFTWARE_BUG),
    ('builtins.NameError', "name 'List' is not defined", ErrorClass.SOFTWARE_BUG),
    ('UnboundLocalError', "cannot access local variable 'value' where it is not associated with a value", ErrorClass.SOFTWARE_BUG),
    ('UnboundLocalError', "local variable 'value' referenced before assignment", ErrorClass.SOFTWARE_BUG),
    ('OSError', '[Errno 98] Address already in use', ErrorClass.ENVIRONMENT),
    ('OSError', '[Errno 24] Too many open files', ErrorClass.ENVIRONMENT),
    ('OSError', "[Errno 28] No space left on device: '/tmp/fixture'", ErrorClass.ENVIRONMENT),
    ('OSError', '[Errno 30] Read-only file system', ErrorClass.ENVIRONMENT),
])
def test_specific_runtime_signatures_share_fail_closed_policy(exception, message, category):
    # These fixtures exercise signatures without occupying ports or filling disks.
    for event in (Event(AT, 'collector', exception, message),
                  Event(AT, 'legacy', '', exception + ': ' + message)):
        assert classify(event).category is category
    policy = classify_error(exception + ': ' + message)
    assert policy.category is category
    assert policy.retry is False and policy.max_attempts == 0
    assert policy.safe_stop is True


def test_real_exception_objects_use_the_same_conservative_policy():
    assert classify_error(NameError("name 'Any' is not defined")).category is ErrorClass.SOFTWARE_BUG
    assert classify_error(OSError(98, 'Address already in use')).category is ErrorClass.ENVIRONMENT


@pytest.mark.parametrize('exception,message', [
    ('NameError', 'unexpected lookup failure'),
    ('OSError', '[Errno 22] Address already in use'),
    ('OSError', '[Errno 28] unspecified resource failure'),
    ('PermissionError', 'Paper policy is disabled'),
    ('TypeError', 'bad input'),
    ('ValueError', 'bad input'),
    ('ModuleNotFoundError', "No module named 'optional_module'"),
    ('', 'software bug suspected in environment'),
    ('', "example NameError: name 'Any' is not defined"),
])
def test_ambiguous_runtime_failures_still_require_review(exception, message):
    result = classify(Event(AT, 'collector', exception, message))
    assert result.category is ErrorClass.UNKNOWN and result.confidence == 0
    policy = classify_error((exception + ': ' if exception else '') + message)
    assert policy.category is ErrorClass.UNKNOWN and policy.retry is False


def test_runtime_signatures_preserve_critical_integrity_precedence():
    event = Event(AT, 'collector', 'NameError', "name 'value' is not defined", stack='hash mismatch')
    assert classify(event).category is ErrorClass.INVARIANT_VIOLATION


def test_similar_software_faults_keep_distinct_fingerprints_and_redact_fake_secrets():
    first = Event(AT, 'collector', 'NameError', "name 'Any' is not defined", stack='token=fixture-private-token')
    second = Event(AT, 'collector', 'NameError', "name 'List' is not defined", stack='token=fixture-private-token')
    assert classify(first).category is classify(second).category is ErrorClass.SOFTWARE_BUG
    assert fingerprint(first) != fingerprint(second)
    assert 'fixture-private-token' not in canonical(first)
