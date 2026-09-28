from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import time

from src.bugfixer.store import IncidentStore
from src.bugfixer.worker import ErrorLogWorker

ROOT = Path(__file__).resolve().parents[2]


def test_metrics_distinguish_raw_lines_events_and_checkpoint_age(tmp_path):
    source = tmp_path / 'events.log'
    source.write_text('\n'.join([
        '{"timestamp":"2026-09-09T00:00:00+00:00","message":"network timeout"}',
        '{"level":"INFO","message":"normal"}',
        'Traceback (most recent call last):',
        '  File "worker.py", line 1']) + '\n')
    store = IncidentStore(tmp_path / 'observer.db')
    try:
        worker = ErrorLogWorker(store, source)
        worker.poll()
        cp = store.checkpoint(worker.source_id)
        status = store.status(now=datetime.fromisoformat(cp['timestamp']) + timedelta(seconds=7))
        assert status['records_read_total'] == 4
        assert status['records_ignored_total'] == 1
        assert status['events_ingested'] == status['events_normalized'] == 1
        assert status['pending_tracebacks'] == 1
        assert status['checkpoint_age_seconds'] == 7
        assert status['ingestion_lag_seconds'] == (
            datetime.fromisoformat(cp['timestamp']) - datetime.fromisoformat('2026-09-09T00:00:00+00:00')).total_seconds()
    finally:
        store.close()


def test_empty_store_metrics_are_unknown_instead_of_fresh(tmp_path):
    store = IncidentStore(tmp_path / 'observer.db')
    try:
        status = store.status()
        assert status['checkpoint_age_seconds'] is None
        assert status['ingestion_lag_seconds'] is None
        assert status['worker_running'] is False
    finally:
        store.close()


def test_follow_worker_reports_liveness_and_stops_cleanly(tmp_path):
    source = tmp_path / 'errors.log'
    source.write_text('network timeout\n')
    path = tmp_path / 'observer.db'
    store = IncidentStore(path)
    process = subprocess.Popen([sys.executable, '-m', 'src.bugfixer', '--store', str(path),
        'observe', '--source', str(source), '--follow'], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and store.status()['events_ingested'] < 1:
            assert process.poll() is None
            time.sleep(.05)
        assert store.status()['worker_running'] is True
        assert store.status()['events_ingested'] == 1
        process.terminate()
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0
        assert json.loads(stdout)['stopped'] is True
        assert store.status()['worker_running'] is False
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        store.close()
