import hashlib
import json

import pytest

from src.bugfixer.evidence import export_bundle, load_bundle, make_bundle, validate_bundle, _encoded
from src.bugfixer.processing import Event
from src.bugfixer.store import IncidentStore

AT = '2026-09-09T00:00:00+00:00'


@pytest.fixture
def incident(tmp_path):
    store = IncidentStore(tmp_path / 'observer.db')
    with store.transaction():
        identity = store.record(Event(AT, 'collector', 'TimeoutError', 'network timeout password=fixture'))
    yield store, identity, tmp_path
    store.close()


def test_evidence_export_is_sanitized_deterministic_and_attached(incident):
    store, identity, root = incident
    first = export_bundle(store, identity, root / 'bundles')
    before = first.read_bytes()
    second = export_bundle(store, identity, root / 'bundles')
    assert first == second and first.read_bytes() == before
    assert b'fixture' not in before
    assert load_bundle(first).exception == 'TimeoutError'
    assert store.db.execute('SELECT count(*) FROM evidence_bundles').fetchone()[0] == 1
    assert first.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('tamper', ['hash', 'event', 'scope', 'path'])
def test_tampering_cannot_be_loaded(incident, tamper):
    store, identity, root = incident
    bundle = make_bundle(store, identity)
    if tamper == 'hash':
        bundle['sha256'] = '0' * 64
    elif tamper == 'event':
        bundle['body']['event']['message'] = 'other message'
    elif tamper == 'scope':
        bundle['body']['scope'] = 'production_verified'
    else:
        bundle['body']['execute_path'] = '/do/not/execute'
    with pytest.raises(ValueError):
        validate_bundle(bundle)


def test_rehashed_secret_still_rejected(incident):
    store, identity, root = incident
    bundle = make_bundle(store, identity)
    bundle['body']['event']['message'] = 'password=fixture'
    bundle['sha256'] = hashlib.sha256(_encoded(bundle['body'])).hexdigest()
    with pytest.raises(ValueError, match='unsanitized'):
        validate_bundle(bundle)


def test_symlink_and_oversize_input_rejected(incident):
    store, identity, root = incident
    target = export_bundle(store, identity, root / 'bundles')
    alias = root / 'alias'
    alias.symlink_to(target)
    with pytest.raises(OSError):
        load_bundle(alias)
    large = root / 'large.json'
    large.write_bytes(b' ' * (1024 * 1024 + 1))
    with pytest.raises(ValueError):
        load_bundle(large)


def test_existing_invalid_artifact_is_not_overwritten(incident):
    store, identity, root = incident
    path = export_bundle(store, identity, root / 'bundles')
    path.write_text('invalid existing evidence')
    with pytest.raises(ValueError):
        export_bundle(store, identity, root / 'bundles')
    assert path.read_text() == 'invalid existing evidence'


def test_cli_evidence_round_trip_and_cutoff(incident, capsys):
    from src.bugfixer.__main__ import main
    store, identity, root = incident
    base = ['--store', str(store.path)]
    assert main(base + ['export-evidence', identity, '--directory', str(root / 'exports')]) == 0
    document = json.loads(capsys.readouterr().out)
    bundle = root / 'exports' / document['bundle_name']
    assert main(base + ['replay-evidence', '--bundle', str(bundle), '--cutoff', AT]) == 0
    assert json.loads(capsys.readouterr().out)['production_bug_reproduced'] is False
    assert main(base + ['replay-evidence', '--bundle', str(bundle), '--cutoff', '2026-09-08T00:00:00Z']) == 2
