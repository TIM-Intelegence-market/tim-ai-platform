from src.bugfixer.processing import parse_line, fingerprint, classify

AT = '2026-09-09T16:00:00+00:00'

def record(ms='123', delay='2.1', capacity='50000'):
    return f'2026-09-09 17:52:18,{ms} WARNING src.data_ingestion.binance_ws Binance public stream disconnected (live resume blocked by incomplete catch-up: durable outbox capacity {capacity} reached; event rejected for catch-up); retrying in {delay}s'

def test_real_retry_storm_aggregates_without_erasing_capacity():
    first = parse_line(record(), AT)
    assert fingerprint(first) == fingerprint(parse_line(record('456', '3.9'), AT))
    assert fingerprint(first) != fingerprint(parse_line(record(capacity='60000'), AT))
    assert classify(first).category == 'TERMINAL_BLOCKED'
    assert first.timestamp == AT
    assert first.component == 'src.data_ingestion.binance_ws'

def test_generic_numeric_errors_stay_distinct_and_redacted():
    prefix = '2026-09-09 17:52:18,123 ERROR src.runtime '
    a = parse_line(prefix + 'failure 401 password=synthetic-secret', AT)
    b = parse_line(prefix + 'failure 403 password=synthetic-secret', AT)
    assert fingerprint(a) != fingerprint(b)
    assert 'synthetic-secret' not in a.message
    assert classify(a).category == 'UNKNOWN'

def test_structured_legacy_info_ignored_but_unknown_text_retained():
    assert parse_line('2026-09-09 17:52:18,123 INFO src.runtime healthy', AT) is None
    assert parse_line('unrecognized format', AT) is not None
