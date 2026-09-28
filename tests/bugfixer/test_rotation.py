from dataclasses import replace
import hashlib
import os
from pathlib import Path

import pytest

from src.bugfixer.rotation import RotationSeal
from src.bugfixer.store import IncidentStore
from src.bugfixer.worker import ErrorLogWorker, ObservationBlocked


def identity(path):
    info = path.stat()
    return info.st_dev, info.st_ino


@pytest.fixture
def rotated(tmp_path):
    store = IncidentStore(tmp_path / 'observer.db')
    source = tmp_path / 'errors.log'
    source.write_text('network timeout\nnetwork timeout\nnetwork timeout\n')
    worker = ErrorLogWorker(store, source, max_records=1)
    worker.poll()
    old = tmp_path / 'errors.log.1'
    source.rename(old)
    source.write_text('unknown new generation\n')
    seal = RotationSeal(0, identity(old), identity(source), old.stat().st_size,
                        hashlib.sha256(old.read_bytes()).hexdigest(), True, True)
    yield store, worker, old, source, seal
    store.close()


def test_bounded_tail_drain_then_successor_and_restart(rotated):
    store, worker, old, source, seal = rotated
    first = worker.reconcile_rotation(old, seal)
    assert first['complete'] is False and first['events_ingested'] == 1
    assert store.status()['events_ingested'] == 2
    # New instance uses the committed old-generation cursor.
    restarted = ErrorLogWorker(store, source, max_records=1)
    second = restarted.reconcile_rotation(old, seal)
    assert second['complete'] is True and second['generation'] == 1
    assert store.status()['events_ingested'] == 3
    assert restarted.poll()['events_ingested'] == 1
    assert store.status()['events_ingested'] == 4
    assert restarted.poll()['events_ingested'] == 0
    with pytest.raises(ObservationBlocked):
        restarted.reconcile_rotation(old, seal)


@pytest.mark.parametrize('change', ['digest', 'identity', 'generation', 'successor', 'size'])
def test_wrong_seal_never_advances(rotated, change):
    store, worker, old, source, seal = rotated
    before = store.checkpoint(worker.source_id)
    updates = {'digest': {'sha256': '0' * 64}, 'identity': {'old_identity': (0, 0)},
               'generation': {'generation': 1}, 'successor': {'successor_identity': (0, 1)},
               'size': {'size': seal.size - 1}}
    with pytest.raises(ObservationBlocked):
        worker.reconcile_rotation(old, replace(seal, **updates[change]))
    assert store.checkpoint(worker.source_id) == before
    assert store.status()['events_ingested'] == 1


def test_writer_must_be_closed_and_chain_attested(rotated):
    *_, seal = rotated
    for field in ('writer_closed', 'contiguous_successor'):
        with pytest.raises(ValueError):
            replace(seal, **{field: False})
    with pytest.raises(ValueError):
        replace(seal, successor_identity=seal.old_identity)


def test_sealed_partial_line_cannot_be_discarded(rotated):
    store, worker, old, source, seal = rotated
    with old.open('ab') as handle:
        handle.write(b'unfinished')
    seal = replace(seal, size=old.stat().st_size, sha256=hashlib.sha256(old.read_bytes()).hexdigest())
    with pytest.raises(ObservationBlocked):
        worker.reconcile_rotation(old, seal)
    assert store.status()['events_ingested'] == 1


def test_missing_or_compressed_old_identity_stays_blocked(rotated, tmp_path):
    import gzip
    store, worker, old, source, seal = rotated
    compressed = tmp_path / 'errors.log.1.gz'
    compressed.write_bytes(gzip.compress(old.read_bytes()))
    with pytest.raises(ObservationBlocked):
        worker.reconcile_rotation(compressed, seal)
    old.unlink()
    with pytest.raises(OSError):
        worker.reconcile_rotation(old, seal)
    assert store.status()['events_ingested'] == 1


def test_mid_read_mutation_rolls_back_tail(rotated, monkeypatch):
    store, worker, old, source, seal = rotated
    original = store.record
    def mutate(event):
        result = original(event)
        with old.open('ab') as handle:
            handle.write(b'extra error\n')
        return result
    monkeypatch.setattr(store, 'record', mutate)
    with pytest.raises(ObservationBlocked):
        worker.reconcile_rotation(old, seal)
    assert store.status()['events_ingested'] == 1


def test_successor_rotation_during_tail_rolls_back(rotated, monkeypatch, tmp_path):
    store, worker, old, source, seal = rotated
    original = store.record
    def rotate(event):
        result = original(event)
        source.rename(tmp_path / 'errors.log.2')
        source.write_text('yet another generation\n')
        return result
    monkeypatch.setattr(store, 'record', rotate)
    with pytest.raises(ObservationBlocked):
        worker.reconcile_rotation(old, seal)
    assert store.status()['events_ingested'] == 1


def test_checkpoint_write_failure_rolls_back_rotation(rotated, monkeypatch):
    store, worker, old, source, seal = rotated
    before = store.checkpoint(worker.source_id)
    def fail(*args):
        raise RuntimeError('simulated checkpoint fault')
    monkeypatch.setattr(store, 'save_checkpoint', fail)
    with pytest.raises(RuntimeError):
        worker.reconcile_rotation(old, seal)
    assert store.checkpoint(worker.source_id) == before
    assert store.status()['events_ingested'] == 1


def test_byte_budget_and_symlinks_fail_closed(rotated, tmp_path):
    store, worker, old, source, seal = rotated
    with pytest.raises(ObservationBlocked):
        worker.reconcile_rotation(old, seal, max_sealed_bytes=1)
    alias = tmp_path / 'alias'
    alias.symlink_to(old)
    with pytest.raises(OSError):
        worker.reconcile_rotation(alias, seal)
    assert store.status()['events_ingested'] == 1


def test_cli_reconciliation(rotated, tmp_path, capsys):
    import json
    from dataclasses import asdict
    from src.bugfixer.__main__ import main
    store, worker, old, source, seal = rotated
    document = tmp_path / 'seal.json'
    document.write_text(json.dumps({'schema_version': 1, **asdict(seal)}))
    assert main(['--store', str(store.path), 'reconcile-rotation', '--source', str(source),
                 '--rotated-source', str(old), '--seal', str(document)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['complete'] is True and result['events_ingested'] == 2
    assert worker.poll()['events_ingested'] == 1


def test_pending_trace_survives_sealed_generation_transition(tmp_path):
    source, old = tmp_path / 'error.log', tmp_path / 'error.log.1'
    store = IncidentStore(tmp_path / 'observer.db')
    try:
        source.write_text('Traceback (most recent call last):\n  File "worker.py", line 1\n')
        worker = ErrorLogWorker(store, source)
        worker.poll()
        source.rename(old)
        source.write_text('TimeoutError: network timeout\n')
        seal = RotationSeal(0, identity(old), identity(source), old.stat().st_size,
                            hashlib.sha256(old.read_bytes()).hexdigest(), True, True)
        assert worker.reconcile_rotation(old, seal)['complete'] is True
        assert worker.poll()['events_ingested'] == 1
        assert store.list()[0]['category'] == 'NETWORK'
    finally:
        store.close()


def test_pending_reconciliation_cannot_change_declared_successor(rotated, tmp_path):
    store, worker, old, source, seal = rotated
    assert worker.reconcile_rotation(old, seal)['complete'] is False
    before = store.checkpoint(worker.source_id)
    source.rename(tmp_path / 'skipped-generation.log')
    source.write_text('another generation\n')
    changed = replace(seal, successor_identity=identity(source))
    with pytest.raises(ObservationBlocked, match='seal cannot change'):
        worker.reconcile_rotation(old, changed)
    assert store.checkpoint(worker.source_id) == before
    assert store.status()['events_ingested'] == 2
