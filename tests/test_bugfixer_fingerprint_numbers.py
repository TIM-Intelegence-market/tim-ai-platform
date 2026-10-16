import json

from src.bugfixer.processing import Event, canonical, fingerprint, parse_line
from src.bugfixer.store import IncidentStore

AT = '2026-09-09T16:00:00+00:00'


def _event(message, stack=''):
    return Event(AT, 'svc', '', message, '', stack)


def _fp(message, stack=''):
    return fingerprint(_event(message, stack))


def _noisy_lines():
    return [f'network timeout after {i}ms on request {j}' for i in range(15) for j in range(10)]


def test_varying_durations_and_request_counters_share_one_fingerprint():
    lines = _noisy_lines()
    assert len(lines) == 150
    prints = {fingerprint(parse_line(line, AT)) for line in lines}
    assert len(prints) == 1


def test_fractional_and_whole_second_delays_match():
    assert _fp('retrying in 2.5 seconds') == _fp('retrying in 9 seconds')


def test_key_value_counter_values_match():
    assert _fp('request_id=77') == _fp('request_id=78')


def test_hex_addresses_match():
    assert _fp('object at 0x7f3a2b') == _fp('object at 0x11aa22')


def test_different_status_codes_differ():
    assert _fp('failure 401') != _fp('failure 403')


def test_different_capacities_differ():
    assert _fp('capacity 50000') != _fp('capacity 60000')


def test_different_stack_line_numbers_differ():
    assert _fp('boom', 'File "a.py", line 10') != _fp('boom', 'File "a.py", line 11')


def test_canonical_reports_fingerprint_version_2():
    assert json.loads(canonical(_event('boom')))['fingerprint_version'] == 2


def test_store_collapses_noisy_lines_into_one_versioned_incident(tmp_path):
    store = IncidentStore(tmp_path / 's.db')
    try:
        with store.transaction():
            for line in _noisy_lines():
                store.record(parse_line(line, AT))
        incidents = store.list()
        assert len(incidents) == 1
        assert incidents[0]['fingerprint_version'] == 2
        assert incidents[0]['occurrence_count'] == 150
    finally:
        store.close()
