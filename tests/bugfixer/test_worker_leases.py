import os
import threading
import pytest

from src.bugfixer.store import IncidentStore
from src.bugfixer.worker import ErrorLogWorker, ObservationBlocked


@pytest.mark.parametrize('hardlink', [False, True])
def test_same_source_cannot_have_workers_with_different_stores(tmp_path, hardlink):
    source = tmp_path / 'runtime.log'
    source.write_text('network timeout\n')
    second = tmp_path / 'alias.log' if hardlink else source
    if hardlink:
        os.link(source, second)
    first_store = IncidentStore(tmp_path / 'first.db')
    second_store = IncidentStore(tmp_path / 'second.db')
    try:
        first = ErrorLogWorker(first_store, source)
        other = ErrorLogWorker(second_store, second)
        with first._lease():
            assert first_store.worker_running() is True
            with pytest.raises(ObservationBlocked, match='already running'):
                other.poll()
        assert other.poll()['events_ingested'] == 1
        assert first_store.worker_running() is False
    finally:
        first_store.close()
        second_store.close()


@pytest.mark.parametrize('interval', [float('nan'), float('inf'), True, 0, 61])
def test_follow_rejects_hotloop_and_unbounded_wait(tmp_path, interval):
    source = tmp_path / 'runtime.log'
    source.write_text('network timeout\n')
    store = IncidentStore(tmp_path / 'observer.db')
    try:
        with pytest.raises(ValueError):
            ErrorLogWorker(store, source).run(threading.Event(), interval=interval)
    finally:
        store.close()
