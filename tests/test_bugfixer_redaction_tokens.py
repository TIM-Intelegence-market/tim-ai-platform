import json

import pytest

from src.bugfixer.processing import REDACTED, parse_line, redact, redact_text
from src.repair_diagnosis.package import build_request

# Fake tokens are assembled at runtime so no literal token shape lives in the source.
SK = 'sk-' + 'proj-abcdefghijklmnopqrstuv'
TOKENS = [
    SK,
    'AKIA' + 'ABCDEFGHIJKLMNOP',
    'gh' + 'p_' + 'A1b2C3d4E5f6G7h8I9j0K1',
    'xox' + 'b-1234567890-abcdef',
    'eyJ' + 'hbGciOiJIUzI1.eyJzdWIiOiIx.c2ln',
    'github_' + 'pat_11ABCDEFG0aBcDeFgHiJ',
]


@pytest.mark.parametrize('token', TOKENS)
def test_redact_text_removes_keyword_free_token(token):
    output = redact_text('value ' + token + ' seen')
    assert token not in output
    assert REDACTED in output
    assert redact_text(output) == output


@pytest.mark.parametrize('text', ['sk-short', 'AKIA123'])
def test_short_lookalikes_stay_unchanged(text):
    assert redact_text(text) == text


@pytest.mark.parametrize('token', TOKENS)
def test_redact_dict_value(token):
    assert token not in redact({'msg': token})['msg']


@pytest.mark.parametrize('token', TOKENS)
def test_parse_line_message_has_no_token(token):
    event = parse_line('value ' + token + ' seen', '2026-09-09T16:00:00+00:00')
    assert token not in event.message


def test_build_request_has_no_token():
    request = build_request({'incident_id': 'inc-1', 'category': 'network', 'component': 'collector',
                             'fingerprint': 'a' * 64, 'normalized_error': 'upstream rejected ' + SK})
    assert SK not in json.dumps(request)
