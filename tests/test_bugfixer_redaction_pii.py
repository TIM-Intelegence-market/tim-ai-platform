"""PII redaction in bugfixer evidence (#314): IP and e-mail addresses, parity with src/tim_incident/redaction.py."""
import json

from src.bugfixer.processing import Event, fingerprint, parse_line, redact_text
from src.repair_diagnosis.package import build_request

EMAIL = 'uezeyir.aydin' + '@example.com'
IP = '203.0.' + '113.77'
OBSERVED = '2026-09-09T00:00:00+00:00'


def test_ipv4_and_ipv6_redacted_loopback_and_times_kept():
    text = 'peer ' + IP + ' and 2001:db8::8a2e:370:7334 local 127.0.0.1 and ::1 at 03:15:00'
    assert redact_text(text) == 'peer [IP] and [IP] local 127.0.0.1 and ::1 at 03:15:00'


def test_email_redacted():
    assert redact_text('contact ' + EMAIL + ' now') == 'contact [EMAIL] now'


def test_uri_credentials_and_host_ip_redacted():
    result = redact_text('postgresql://tim:pw' + '@192.168.1.20:5432/db')
    assert 'pw' not in result
    assert '192.168.1.20' not in result


def test_invalid_ip_and_mac_unchanged():
    assert redact_text('value 999.1.1.1 end') == 'value 999.1.1.1 end'
    assert redact_text('mac aa:bb:cc:dd:ee:ff end') == 'mac aa:bb:cc:dd:ee:ff end'


def test_idempotent():
    text = ('peer ' + IP + ' v6 2001:db8::1 mail ' + EMAIL + ' postgresql://tim:pw' + '@192.168.1.20:5432/db'
            + ' local 127.0.0.1 ::1 03:15:00')
    once = redact_text(text)
    assert redact_text(once) == once


def test_parse_line_stores_no_email():
    line = json.dumps({'timestamp': OBSERVED, 'level': 'ERROR', 'component': 'collector',
                       'message': 'mail to ' + EMAIL + ' failed'})
    event = parse_line(line, OBSERVED)
    assert event is not None
    assert EMAIL not in event.message
    assert '[EMAIL]' in event.message


def test_fingerprint_ignores_ipv4_difference():
    first = Event(OBSERVED, 'collector', 'TimeoutError', 'connect to ' + IP + ' timed out')
    second = Event(OBSERVED, 'collector', 'TimeoutError', 'connect to 198.51.' + '100.9 timed out')
    assert fingerprint(first) == fingerprint(second)


def test_build_request_has_no_email_or_ip():
    request = build_request({
        'incident_id': 'inc-1', 'category': 'network', 'component': 'collector', 'fingerprint': 'a' * 64,
        'normalized_error': 'TimeoutError: mail ' + EMAIL, 'stack': 'peer ' + IP,
    })
    dumped = json.dumps(request)
    assert EMAIL not in dumped
    assert IP not in dumped
