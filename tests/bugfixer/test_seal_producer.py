"""#14: producer-side seal generator for rename rotation."""
import json
import os

import pytest

from src.bugfixer.__main__ import main
from src.bugfixer.rotation import RotationSeal
from src.bugfixer.seal import create_seal, seal_to_dict, write_seal
from src.bugfixer.store import IncidentStore
from src.bugfixer.worker import ErrorLogWorker


@pytest.fixture
def rotated_log(tmp_path):
    store = IncidentStore(tmp_path / 'observer.db')
    source = tmp_path / 'errors.log'
    source.write_text('network timeout\nnetwork timeout\n')
    worker = ErrorLogWorker(store, source)
    worker.poll()
    old = tmp_path / 'errors.log.1'
    source.rename(old)
    source.write_text('database locked\n')
    yield store, worker, old, source
    store.close()


def test_generated_seal_lets_the_observer_finish_the_rotation(rotated_log):
    store, worker, old, source = rotated_log
    with open(old, 'a') as late:                 # last records the writer flushed before closing
        late.write('network timeout\n')
    seal = create_seal(old, source, 0, writer_closed=True, contiguous_successor=True)
    result = worker.reconcile_rotation(old, seal)
    assert result['complete'] is True and result['generation'] == 1
    assert worker.poll()['events_ingested'] == 1           # successor is read from its start
    assert store.status()['events_ingested'] == 4


@pytest.mark.parametrize('flags', [(False, True), (True, False), (False, False)])
def test_seal_needs_both_attestations(rotated_log, flags):
    _, _, old, source = rotated_log
    with pytest.raises(ValueError, match='attest'):
        create_seal(old, source, 0, writer_closed=flags[0], contiguous_successor=flags[1])


def test_copytruncate_and_links_are_refused(rotated_log, tmp_path):
    _, _, old, source = rotated_log
    with pytest.raises(ValueError, match='copytruncate'):
        create_seal(source, source, 0, writer_closed=True, contiguous_successor=True)
    link = tmp_path / 'link.log'
    link.symlink_to(old)
    with pytest.raises(ValueError, match='regular'):
        create_seal(link, source, 0, writer_closed=True, contiguous_successor=True)


def test_segment_ending_inside_a_record_is_not_sealed(rotated_log):
    _, _, old, source = rotated_log
    with open(old, 'a') as late:
        late.write('half a line')
    with pytest.raises(ValueError, match='inside a record'):
        create_seal(old, source, 0, writer_closed=True, contiguous_successor=True)


def test_seal_file_round_trips_and_is_never_overwritten(rotated_log, tmp_path):
    _, _, old, source = rotated_log
    seal = create_seal(old, source, 3, writer_closed=True, contiguous_successor=True)
    target = write_seal(seal, tmp_path / 'seal.json')
    assert RotationSeal.from_dict(json.loads(target.read_text())) == seal
    assert oct(os.stat(target).st_mode & 0o777) == '0o600'
    with pytest.raises(FileExistsError):
        write_seal(seal, target)
    assert seal_to_dict(seal)['schema_version'] == 1


def test_cli_seals_without_a_store_and_reconcile_accepts_it(rotated_log, tmp_path, capsys):
    store, worker, old, source = rotated_log
    out = tmp_path / 'seal.json'
    missing_store = tmp_path / 'not-created.db'
    assert main(['--store', str(missing_store), 'seal-rotation', '--rotated-source', str(old),
                 '--successor', str(source), '--generation', '0', '--out', str(out),
                 '--attest-writer-closed', '--attest-contiguous-successor']) == 0
    assert not missing_store.exists()
    assert json.loads(capsys.readouterr().out)['sealed'] is True
    store.close()
    assert main(['--store', str(tmp_path / 'observer.db'), 'reconcile-rotation', '--source', str(source),
                 '--rotated-source', str(old), '--seal', str(out)]) == 0
    assert json.loads(capsys.readouterr().out)['complete'] is True


def test_cli_without_attestation_is_blocked(rotated_log, tmp_path, capsys):
    _, _, old, source = rotated_log
    out = tmp_path / 'seal.json'
    assert main(['--store', str(tmp_path / 'x.db'), 'seal-rotation', '--rotated-source', str(old),
                 '--successor', str(source), '--generation', '0', '--out', str(out)]) == 2
    assert not out.exists()
    assert json.loads(capsys.readouterr().out)['status'] == 'BLOCKED'
