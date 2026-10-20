import json

from src.bugfixer.legacy import LegacyTraceAssembler
from src.bugfixer.store import IncidentStore
from src.bugfixer.worker import ErrorLogWorker

_OBSERVED = '2026-09-09T16:00:00+00:00'


def _trace(path, error='sqlite3.OperationalError: database is locked'):
    return ['Traceback (most recent call last):', f'  File "{path}", line 120, in _consume',
            '    self.store.record(event)', error]


def _poll(tmp_path, lines):
    log = tmp_path / 'error.log'
    log.write_text('\n'.join(lines) + '\n')
    store = IncidentStore(tmp_path / 's.db')
    try:
        result = ErrorLogWorker(store, log).poll()
        return result, store.list()
    finally:
        store.close()


def test_own_traceback_is_dropped(tmp_path):
    result, rows = _poll(tmp_path, _trace('/opt/tim/src/bugfixer/worker.py'))
    assert result['events_ingested'] == 0
    assert rows == []


def test_foreign_traceback_after_own_one_is_kept(tmp_path):
    lines = _trace('/opt/tim/src/bugfixer/worker.py') + _trace(
        '/opt/tim/src/collector/run.py', 'TimeoutError: network timeout')
    result, rows = _poll(tmp_path, lines)
    assert result['events_ingested'] == 1
    assert len(rows) == 1
    assert json.loads(rows[0]['evidence'])['component'] == 'legacy'


def test_relative_and_windows_own_paths_are_dropped(tmp_path):
    for index, path in enumerate(('src/bugfixer/store.py', 'C:\\tim\\src\\bugfixer\\store.py')):
        directory = tmp_path / str(index)
        directory.mkdir()
        result, rows = _poll(directory, _trace(path))
        assert result['events_ingested'] == 0, path
        assert rows == [], path


def test_similar_foreign_paths_are_not_dropped(tmp_path):
    for index, path in enumerate(('/opt/tim/src/bugfixer_extra/x.py', '/opt/mysrc/bugfixer/x.py')):
        directory = tmp_path / str(index)
        directory.mkdir()
        result, rows = _poll(directory, _trace(path))
        assert result['events_ingested'] == 1, path
        assert len(rows) == 1, path


def test_incomplete_own_traceback_is_dropped(tmp_path):
    lines = ['Traceback (most recent call last):', '  File "/opt/tim/src/bugfixer/worker.py", line 120, in _consume',
             'plain failure']
    result, rows = _poll(tmp_path, lines)
    assert result['events_ingested'] == 1
    assert len(rows) == 1
    evidence = json.loads(rows[0]['evidence'])
    assert evidence['message'] == 'plain failure'
    assert evidence['component'] == 'legacy'


def test_assembler_feed_drops_own_traceback():
    assembler = LegacyTraceAssembler()
    results = [assembler.feed(line + '\n', _OBSERVED) for line in _trace('/opt/tim/src/bugfixer/worker.py')]
    assert results == [[], [], [], []]
    assert assembler.pending is None
