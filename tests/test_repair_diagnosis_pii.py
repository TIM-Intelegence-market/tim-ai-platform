"""PII and secret exclusion where diagnosis data leaves TIM (#315): request, manual export, stored diagnosis."""
import json

from src.repair_diagnosis.manual import export_request
from src.repair_diagnosis.package import build_request, parse_response
from src.repair_diagnosis.store import load_diagnosis, save_diagnosis

EMAIL = 'uezeyir.aydin' + '@example.com'
IP = '203.0.' + '113.77'
TOKEN = 'sk-' + 'proj-abcdefghijklmnopqrstuv'
AWS = 'AKIA' + 'ABCDEFGHIJKLMNOP'
LEAKS = (EMAIL, IP, TOKEN, AWS)


def _incident(**overrides):
    incident = {
        'incident_id': 'inc-1', 'category': 'network', 'component': 'collector', 'fingerprint': 'a' * 64,
        'normalized_error': f'TimeoutError: mail {EMAIL} peer {IP}',
        'stack': f'key {TOKEN} {AWS}',
        'reproduction': {'cmd': f'curl {IP}'},
        'code_paths': [EMAIL],
        'tests': [TOKEN],
    }
    incident.update(overrides)
    return incident


def _assert_clean(text):
    for leak in LEAKS:
        assert leak not in text


def test_request_has_no_leaks_and_placeholders():
    dumped = json.dumps(build_request(_incident()))
    _assert_clean(dumped)
    assert '[EMAIL]' in dumped
    assert '[IP]' in dumped
    assert '[REDACTED]' in dumped


def test_manual_export_has_no_leaks(tmp_path):
    path = export_request(build_request(_incident()), tmp_path / 'req.json')
    _assert_clean(path.read_text(encoding='utf-8'))


def test_parsed_response_has_no_leaks():
    request = build_request(_incident())
    result = parse_response({'incident_id': 'inc-1', 'hypothesis': f'contact {EMAIL} at {IP}',
                             'proposed_actions': [TOKEN], 'confidence': 0.5}, request)
    assert result['status'] == 'VALID'
    _assert_clean(json.dumps(result))


def test_stored_diagnosis_has_no_leaks(tmp_path):
    request = build_request(_incident())
    path = save_diagnosis(
        tmp_path / 'd', request,
        {'outcome': 'PROPOSAL', 'provider': 'fake', 'attempts': [{'provider': 'fake', 'status': 'VALID'}],
         'result': {'hypothesis': f'see {EMAIL} {IP} {TOKEN}', 'proposed_actions': [AWS], 'confidence': 0.5}},
        recorded_at='2026-09-09T00:00:00+00:00')
    raw = path.read_bytes()
    for leak in LEAKS:
        assert leak.encode() not in raw
    _assert_clean(json.dumps(load_diagnosis(path)))


def test_loopback_kept_in_request():
    request = build_request(_incident(normalized_error='TimeoutError: connect 127.0.0.1 refused'))
    assert '127.0.0.1' in request['normalized_error']
