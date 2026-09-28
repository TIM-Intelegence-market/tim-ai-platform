from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from src.bugfixer.readiness import REQUIRED, ISOLATED_GATES, SOURCE_FILES, evaluate_readiness, source_digest

NOW = datetime(2026, 9, 12, 21, 30, tzinfo=timezone.utc)


@pytest.fixture
def evidence(tmp_path):
    repo = tmp_path / 'repo'
    for name in SOURCE_FILES:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# isolated source fixture\n')
    folder = tmp_path / 'proof'
    folder.mkdir()
    digest = source_digest(repo)
    manifest = {'schema_version': 1, 'code_sha256': digest, 'runtime_id': '100:1', 'artifacts': {}}
    for gate, checks in REQUIRED.items():
        report = {'schema_version': 1, 'gate': gate, 'code_sha256': digest, 'runtime_id': '100:1',
                  'scope': 'ISOLATED_VERIFICATION' if gate in ISOLATED_GATES else 'LIVE_RUNTIME',
                  'status': 'PASS', 'observed_at': NOW.isoformat(), 'checks': checks}
        raw = json.dumps(report).encode()
        (folder / (gate + '.json')).write_bytes(raw)
        manifest['artifacts'][gate] = {'path': gate + '.json', 'sha256': hashlib.sha256(raw).hexdigest()}
    path = folder / 'manifest.json'
    path.write_text(json.dumps(manifest))
    return repo, path


def evaluate(evidence, **kwargs):
    repo, manifest = evidence
    return evaluate_readiness(manifest, repo_root=repo, now=NOW, runtime_id='100:1', **kwargs)


def mutate(evidence, gate, change):
    _, manifest_path = evidence
    path = manifest_path.parent / (gate + '.json')
    report = json.loads(path.read_text())
    change(report)
    raw = json.dumps(report).encode()
    path.write_bytes(raw)
    manifest = json.loads(manifest_path.read_text())
    manifest['artifacts'][gate]['sha256'] = hashlib.sha256(raw).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


def test_complete_current_bound_evidence_passes_without_trading_permission(evidence):
    result = evaluate(evidence)
    assert result['LIVE_DATA_READINESS'] == 'PASS'
    assert result['live_data_release_allowed'] is True
    assert result['live_trading'] is result['execution'] is False


@pytest.mark.parametrize('gate', REQUIRED)
def test_every_gate_required_and_pass_label_alone_insufficient(evidence, gate):
    mutate(evidence, gate, lambda report: report.update(checks={}))
    result = evaluate(evidence)
    assert result['LIVE_DATA_READINESS'] == 'SAFE_STOP'
    assert result['checks'][gate] is False


@pytest.mark.parametrize('change', [
    lambda r: r.update(observed_at=(NOW - timedelta(seconds=61)).isoformat()),
    lambda r: r.update(observed_at=(NOW + timedelta(seconds=1)).isoformat()),
    lambda r: r.update(observed_at='2026-09-12T21:30:00'),
    lambda r: r.update(runtime_id='100:2'),
    lambda r: r.update(scope='ISOLATED_VERIFICATION'),
    lambda r: r.update(code_sha256='a' * 64),
    lambda r: r['checks'].update(pending=1),
    lambda r: r['checks'].update(pending=False),
    lambda r: r['checks'].update(catchup_complete='true'),
])
def test_queue_requires_fresh_live_identity_and_strict_measurements(evidence, change):
    mutate(evidence, 'queue', change)
    assert evaluate(evidence)['live_data_release_allowed'] is False


def test_report_tamper_and_source_change_invalidate_old_acceptance(evidence):
    repo, manifest = evidence
    (manifest.parent / 'queue.json').write_text('{}')
    assert evaluate(evidence)['live_data_release_allowed'] is False
    (repo / 'main.py').write_text('# changed after tests\n')
    assert 'manifest_missing_invalid_or_source_changed' in evaluate(evidence)['blockers']


@pytest.mark.parametrize('value', ['../outside.json', '/tmp/outside.json'])
def test_manifest_cannot_reference_external_files(evidence, value):
    _, path = evidence
    manifest = json.loads(path.read_text())
    manifest['artifacts']['safety']['path'] = value
    path.write_text(json.dumps(manifest))
    assert evaluate(evidence)['live_data_release_allowed'] is False


def test_missing_proof_and_unverified_runtime_stop(evidence):
    repo, manifest = evidence
    assert evaluate_readiness(None, repo_root=repo)['LIVE_DATA_READINESS'] == 'SAFE_STOP'
    assert evaluate_readiness(manifest, repo_root=repo, now=NOW)['blockers'] == ['runtime_identity_unverified']


def test_bounded_collection_refuses_before_database_snapshot(evidence, monkeypatch, capsys):
    import asyncio
    from types import SimpleNamespace
    from scripts import verified_live_collection as cli
    monkeypatch.setattr(cli, 'runtime', lambda: {'pid': 100, 'runs': 1})
    monkeypatch.setattr(cli, 'ROOT', evidence[0])
    def forbidden(*args, **kwargs):
        raise AssertionError('unsafe/expensive path reached before readiness proof')
    monkeypatch.setattr(cli, 'snapshot', forbidden)
    result = asyncio.run(cli.run(SimpleNamespace(readiness_manifest=None)))
    assert result['LIVE_DATA_READINESS'] == 'SAFE_STOP'
    assert 'SAFE_STOP' in capsys.readouterr().out
