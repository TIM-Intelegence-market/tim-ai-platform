import copy
from dataclasses import replace
import fcntl
import hashlib
import json
import os

import pytest

from src.bugfixer.diagnosis import DiagnosisClient, MAX_GENERATION_TOKENS, _encode
from src.bugfixer.evidence import make_bundle
from src.bugfixer.processing import Event
from src.bugfixer.store import IncidentStore

AT = '2026-09-12T21:26:14+00:00'


def event(message='network timeout password=fixture-secret'):
    return Event(AT, 'collector', 'TimeoutError', message)


def proposal(category='NETWORK', **changes):
    value = {'schema_version': 1, 'category': category, 'risk': 'LOW', 'confidence': .95,
             'hypothesis': 'A transient connection interruption is possible; password=output-secret',
             'suggested_remediation_id': '', 'proposed_checks': ['inspect_sanitized_logs']}
    return {**value, **changes}


def fake(client, monkeypatch, response=None, *, failure=None):
    calls = []
    def request(path, payload, deadline):
        calls.append((path, payload, deadline))
        if failure:
            raise failure('password=exception-secret')
        if path == '/api/tags':
            return {'models': [{'name': client.model}]}
        return {'done': True, 'response': json.dumps(proposal() if response is None else response)}
    monkeypatch.setattr(client, '_request', request)
    return calls


def test_advice_is_sanitized_bounded_non_authoritative_and_cached(tmp_path, monkeypatch):
    client = DiagnosisClient(cache_dir=tmp_path / 'cache')
    calls = fake(client, monkeypatch)
    result = client.analyze(event())
    assert result['state'] == 'REVIEW_REQUIRED'
    assert result['executed'] is False and result['advisory_only'] is True
    assert result['live_data_ready'] is False and result['task_draft']['published'] is False
    assert result['cached'] is False
    assert len(calls) == 2
    assert 'fixture-secret' not in str(calls)
    assert 'output-secret' not in str(result)
    payload = calls[1][1]
    assert payload['stream'] is False and payload['options']['temperature'] == 0
    assert payload['options']['num_predict'] == MAX_GENERATION_TOKENS
    assert calls[0][2] == calls[1][2]
    repeated = client.analyze(replace(event(), timestamp='2026-09-13T00:00:00+00:00'))
    assert repeated == {**result, 'cached': True} and len(calls) == 2
    restarted = DiagnosisClient(cache_dir=tmp_path / 'cache')
    monkeypatch.setattr(restarted, '_request', lambda *args: pytest.fail('cached inference repeated'))
    assert restarted.analyze(event()) == repeated
    for path in (tmp_path / 'cache').glob('*.json'):
        assert 'secret' not in path.read_text()
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('url', ['https://127.0.0.1:11434', 'http://example.com', 'http://127.0.0.1.evil',
                                'http://192.168.1.1', 'http://0.0.0.0', 'http://[::ffff:8.8.8.8]',
                                'http://user:pass@127.0.0.1', 'http://127.0.0.1/api/generate',
                                'http://127.0.0.1?next=http://example.com', 'file:///tmp/ollama'])
def test_non_loopback_and_routing_endpoints_rejected(tmp_path, url):
    with pytest.raises(ValueError):
        DiagnosisClient(cache_dir=tmp_path, endpoint=url)


@pytest.mark.parametrize('changes', [{'extra': 'execute'}, {'confidence': True}, {'confidence': float('nan')},
                                    {'category': 'READY'}, {'schema_version': True},
                                    {'suggested_remediation_id': 'INVENTED_RECIPE'},
                                    {'proposed_checks': ['clear_outbox']},
                                    {'proposed_checks': ['inspect_sanitized_logs'] * 2},
                                    {'hypothesis': 'x' * 1001}, {'risk': ['LOW']}])
def test_invalid_model_outputs_fail_closed_once(tmp_path, monkeypatch, changes):
    client = DiagnosisClient(cache_dir=tmp_path)
    calls = fake(client, monkeypatch, proposal(**changes))
    result = client.analyze(event())
    assert result['state'] == 'SAFE_STOP' and result['proposal'] is None
    assert result['task_draft']['state'] == 'SAFE_STOP'
    assert client.analyze(event())['cached'] is True and len(calls) == 2


@pytest.mark.parametrize('changes', [{'risk': 'HIGH'}, {'confidence': .5}, {'category': 'CONFIGURATION'}])
def test_risk_or_classification_disagreement_cannot_grant_authority(tmp_path, monkeypatch, changes):
    client = DiagnosisClient(cache_dir=tmp_path)
    fake(client, monkeypatch, proposal(**changes))
    result = client.analyze(event())
    assert result['state'] == 'SAFE_STOP' and result['executed'] is False
    assert result['deterministic_category'] == 'NETWORK'


@pytest.mark.parametrize('message, category', [
    ('mysterious failure', 'UNKNOWN'),
    ('live resume blocked by incomplete catch-up: durable outbox capacity 50000 reached', 'TERMINAL_BLOCKED'),
    ('hash mismatch', 'INVARIANT_VIOLATION')])
def test_critical_and_unknown_incidents_stop_even_with_low_risk_advice(tmp_path, monkeypatch, message, category):
    client = DiagnosisClient(cache_dir=tmp_path)
    fake(client, monkeypatch, proposal(category))
    result = client.analyze(event(message))
    assert result['state'] == 'SAFE_STOP' and result['live_data_ready'] is False


@pytest.mark.parametrize('failure', [TimeoutError, OSError, ValueError])
def test_model_failure_recorded_without_payloads_or_retries(tmp_path, monkeypatch, failure):
    client = DiagnosisClient(cache_dir=tmp_path)
    calls = fake(client, monkeypatch, failure=failure)
    result = client.analyze(event())
    assert result['reason'] == 'model_unavailable_or_invalid'
    assert result['state'] == 'SAFE_STOP' and 'exception-secret' not in str(result)
    assert client.analyze(event())['cached'] is True and len(calls) == 1


def test_missing_model_never_downloads_or_generates(tmp_path, monkeypatch):
    client = DiagnosisClient(cache_dir=tmp_path)
    calls = []
    def missing(path, payload, deadline):
        calls.append(path)
        return {'models': []}
    monkeypatch.setattr(client, '_request', missing)
    assert client.analyze(event())['reason'] == 'model_unavailable'
    assert calls == ['/api/tags']


def test_evidence_bundle_bound_to_incident(tmp_path, monkeypatch):
    client = DiagnosisClient(cache_dir=tmp_path / 'cache')
    calls = fake(client, monkeypatch)
    store = IncidentStore(tmp_path / 'observer.db')
    try:
        with store.transaction():
            identity = store.record(event())
        bundle = make_bundle(store, identity)
    finally:
        store.close()
    assert client.analyze(event('different'), bundle)['state'] == 'SAFE_STOP'
    assert not calls
    assert client.analyze(event(), bundle)['state'] == 'REVIEW_REQUIRED'
    tampered = copy.deepcopy(bundle)
    tampered['sha256'] = '0' * 64
    assert client.analyze(event(), tampered)['state'] == 'SAFE_STOP'
    assert len(calls) == 2


def test_oversized_evidence_is_not_sent(tmp_path, monkeypatch):
    client = DiagnosisClient(cache_dir=tmp_path)
    calls = fake(client, monkeypatch)
    assert client.analyze(event('x' * 13000))['state'] == 'SAFE_STOP'
    assert not calls


def test_cache_tampering_and_symlinks_preserved_and_rejected(tmp_path, monkeypatch):
    client = DiagnosisClient(cache_dir=tmp_path / 'cache')
    calls = fake(client, monkeypatch)
    result = client.analyze(event())
    target = tmp_path / 'cache' / (result['cache_key'] + '.json')
    original = target.read_bytes()
    envelope = json.loads(original)
    envelope['body']['executed'] = True
    envelope['sha256'] = hashlib.sha256(_encode(envelope['body'])).hexdigest()
    target.write_text(json.dumps(envelope))
    assert client.analyze(event())['reason'] == 'cache_rejected'
    assert json.loads(target.read_text())['body']['executed'] is True
    target.unlink()
    other = tmp_path / 'evidence.json'
    other.write_bytes(original)
    target.symlink_to(other)
    assert client.analyze(event())['reason'] == 'cache_rejected'
    assert target.is_symlink() and other.read_bytes() == original
    assert len(calls) == 2


def test_concurrent_request_never_runs_second_inference(tmp_path, monkeypatch):
    client = DiagnosisClient(cache_dir=tmp_path)
    result = client.analyze(event('x' * 13000))
    # Use a valid event to establish the deterministic key without a generation.
    calls = fake(client, monkeypatch)
    result = client.analyze(event())
    lock = os.open(tmp_path / (result['cache_key'] + '.lock'), os.O_RDWR)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert client.analyze(event())['reason'] == 'diagnosis_in_progress'
        assert len(calls) == 2
    finally:
        os.close(lock)


def test_interrupted_generation_leaves_durable_stop(tmp_path, monkeypatch):
    client = DiagnosisClient(cache_dir=tmp_path)
    monkeypatch.setattr(client, '_request', lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        client.analyze(event())
    monkeypatch.setattr(client, '_request', lambda *args: pytest.fail('interrupted inference retried'))
    result = client.analyze(event())
    assert result['state'] == 'SAFE_STOP' and result['reason'] == 'diagnosis_not_completed'
    assert result['cached'] is True
