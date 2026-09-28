"""Sanitize untrusted logs before canonicalization or persistence."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re

from src.bugfixer.model import ErrorClass
from src.collection_reporting.errors import classify_runtime_signature

REDACTED = '[REDACTED]'
_KEY = re.compile(r'pass(?:word|phrase)?|secret|token|credential|authorization|cookie|api.?key|private.?key', re.I)
_PEM = re.compile(r'-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)', re.S)
_URI = re.compile(r'([a-z][a-z0-9+.-]*://)[^\s/@]*@', re.I)
_HEADER = re.compile(r'\b(authorization|proxy-authorization|cookie|set-cookie)\s*[:=][^\r\n]*', re.I)
_BEARER = re.compile(r'\bBearer\s+[^\s,;]+', re.I)
_PAIR = re.compile(r'''\b(password|passwd|passphrase|secret|token|access_token|refresh_token|api[_-]?key|credential|private[_-]?key)\b["']?\s*[:=]\s*(?:\[REDACTED\]|"[^"\n]*"|'[^'\n]*'|[^\s,;&}\]]+)''', re.I)
_UUID = re.compile(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', re.I)
_TIMESTAMP = re.compile(r'\b\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)?\b')


_LEGACY_RECORD = re.compile(
    r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} '
    r'(DEBUG|INFO|WARNING|ERROR|CRITICAL) ([A-Za-z_][A-Za-z0-9_.]*) (.+)$')
_OUTBOX_RETRY = re.compile(
    r'^(Binance public stream disconnected \(live resume blocked by incomplete catch-up: '
    r'durable outbox capacity [0-9]+ reached; event rejected for catch-up\)); '
    r'retrying in [0-9]+(?:\.[0-9]+)?s$')


def _is_bugfixer_component(component: str) -> bool:
    return any(component == root or component.startswith(root + '.')
               for root in ('bugfixer', 'src.bugfixer'))


def redact_text(text: str) -> str:
    text = _PEM.sub(REDACTED, text)
    text = _URI.sub(r'\1[REDACTED]@', text)
    text = _HEADER.sub(lambda m: m[1] + ': ' + REDACTED, text)
    text = _BEARER.sub('Bearer ' + REDACTED, text)
    return _PAIR.sub(lambda m: m[1] + '=' + REDACTED, text)


def redact(value):
    if isinstance(value, dict):
        return {redact_text(str(k)): REDACTED if _KEY.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('timestamp must be timezone-aware ISO-8601') from None


@dataclass(frozen=True)
class Event:
    timestamp: str
    component: str
    exception: str
    message: str
    code: str = ''
    stack: str = ''

    def __post_init__(self):
        if self.timestamp != timestamp(self.timestamp):
            raise ValueError('event timestamp must be canonical UTC')
        for value in (self.component, self.exception, self.message, self.code, self.stack):
            if not isinstance(value, str) or len(value) > 65536:
                raise ValueError('invalid event field')
        if not self.message.strip():
            raise ValueError('empty event message')

    def safe_dict(self):
        # Also sanitize events supplied directly by API clients.
        return redact(vars(self))


def parse_line(line: str, observed_at: str) -> Event | None:
    observed_at = timestamp(observed_at)
    safe = redact_text(line)
    try:
        row = json.loads(safe)
    except (ValueError, RecursionError):
        row = None
    # Redact valid JSON before text redaction can change quoting/structure.
    try:
        raw = json.loads(line)
        row = redact(raw)
    except (ValueError, RecursionError):
        pass
    if not isinstance(row, dict):
        # Fail closed for multiline private-key content; worker also guards blocks.
        if not safe.strip():
            return None
        record = _LEGACY_RECORD.fullmatch(safe.strip())
        if record:
            if record[1] in {'DEBUG', 'INFO'} or _is_bugfixer_component(record[2]):
                return None
            # Local log time has no offset: retain observation time, never infer UTC.
            message = record[3]
            retry = _OUTBOX_RETRY.fullmatch(message)
            if retry:
                message = retry[1] + '; retrying in <delay>s'
            return Event(observed_at, record[2], '', message)
        return Event(observed_at, 'legacy', '', safe.strip())
    component = str(row.get('component', row.get('logger', 'unknown')))
    if (any(_is_bugfixer_component(str(row.get(key, ''))) for key in ('component', 'logger'))
            or row.get('origin') == 'tim_bugfixer'):
        return None
    level = str(row.get('severity', row.get('level', 'ERROR'))).upper()
    if level not in {'WARN', 'WARNING', 'ERROR', 'CRITICAL', 'FATAL'}:
        return None
    return Event(timestamp(row.get('timestamp', observed_at)), component,
                 str(row.get('exception_type', row.get('exception', ''))),
                 str(row.get('message', row.get('event', 'unstructured error'))),
                 str(row.get('error_code', '')), str(row.get('stack', '')))


def canonical(event: Event) -> str:
    fields = event.safe_dict()
    fields.pop('timestamp')
    for key in ('message', 'stack'):
        fields[key] = re.sub(r'\s+', ' ', _UUID.sub('<uuid>', _TIMESTAMP.sub('<timestamp>', fields[key]))).strip()
    return json.dumps({'fingerprint_version': 1, **fields}, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def fingerprint(event: Event) -> str:
    return hashlib.sha256(canonical(event).encode()).hexdigest()


@dataclass(frozen=True)
class Classification:
    category: ErrorClass
    confidence: float
    matched_rule: str
    reason: str


_SAFETY_RULES = (
    ('outbox_capacity_v1', ErrorClass.TERMINAL_BLOCKED, ('live resume blocked by incomplete catch-up: durable outbox capacity',)),
    ('ordering_v1', ErrorClass.TERMINAL_BLOCKED, ('out-of-order', 'terminal_blocked')),
    ('integrity_v1', ErrorClass.INVARIANT_VIOLATION, ('invariant', 'hash mismatch', 'duplicate side effect')),
)
_RULES = (
    ('credential_v1', ErrorClass.CREDENTIAL, ('authentication', 'credential', 'keychain', 'unauthorized')),
    ('configuration_v1', ErrorClass.CONFIGURATION, ('ex_config', 'configuration', 'missing environment', 'standarderrorpath')),
    ('database_v1', ErrorClass.DATABASE, ('deadlock', 'postgres', 'asyncpg', 'database', 'connection pool')),
    ('network_v1', ErrorClass.NETWORK, ('timeout', 'network', 'websocket', 'connection refused', 'dns')),
    ('quality_v1', ErrorClass.DATA_QUALITY, ('invalid price', 'invalid volume', 'future timestamp', 'candle gap', 'data quality')),
    ('transient_v1', ErrorClass.TRANSIENT, ('rate limit', 'temporarily unavailable')),
    ('retryable_v1', ErrorClass.RETRYABLE, ('retryableerror',)),
)


def classify(event: Event) -> Classification:
    if event.message == 'Incomplete Python traceback' and not event.exception:
        return Classification(ErrorClass.UNKNOWN, 0.0, 'incomplete_trace_v1',
                              'Incomplete traceback requires review')
    text = canonical(event).lower()
    for rule, category, terms in _SAFETY_RULES:
        if any(term in text for term in terms):
            return Classification(category, .9, rule, 'Matched deterministic rule: ' + rule)
    safe = event.safe_dict()
    category = classify_runtime_signature(safe['exception'], safe['message'])
    if category is not None:
        rule = category.value.lower() + '_runtime_signature_v1'
        return Classification(category, .9, rule, 'Matched deterministic rule: ' + rule)
    for rule, category, terms in _RULES:
        if any(term in text for term in terms):
            return Classification(category, .9, rule, 'Matched deterministic rule: ' + rule)
    return Classification(ErrorClass.UNKNOWN, 0.0, 'unknown_v1', 'No sufficiently specific known rule; review required')
