"""Redaction for every text the checkup sends to GitHub (design A.5). Fixed logic: no model, no network, no state.

`redact` works on blocks (paragraphs, split at blank lines):
1. A block that holds a known secret (`literals`) in any form from `literal_variants` is dropped whole.
2. The other blocks pass the regex chain, a copy that is at least as strict as `src.bugfixer.processing.redact_text`
   and `src.graph_mcp.redaction.redact_text` (parity test), and also covers the forms both leak.
3. `final_scan`, an independent second opinion with different patterns, drops any block it still finds suspicious.

Log text reaches a comment only through `untrusted_block`: redact, neutralize, fence. This module imports nothing
from the rest of the repository (design E8), so workers cannot weaken it by editing shared code.
"""
from __future__ import annotations

import base64
import ipaddress
import re
from urllib.parse import quote, quote_plus

REDACTED = '[REDACTED]'
IP = '[IP]'
EMAIL = '[EMAIL]'
USER = '[USER]'
BLOCK_REMOVED = '[BLOCK ENTFERNT: Geheimnisverdacht]'      # final_scan hit
LITERAL_REMOVED = '[BLOCK ENTFERNT: bekanntes Geheimnis]'   # known secret in some encoding
ZWSP = '\u200b'
MIN_LITERAL = 8         # shorter secrets cannot be told apart from ordinary words and are ignored
MIN_VARIANT = 8         # derived encodings shorter than this are dropped (they would match random text)

_KEYWORD = (r'(?:pass(?:word|wd|phrase)|pwd|secret|token|api[_-]?key|apikey|private[_-]?key|access[_-]?key'
            r'|credentials?|client[_-]?secret)')

# (pattern, replacement) in order. Earlier rules see the raw text; later ones may see earlier placeholders.
_CHAIN: tuple[tuple[re.Pattern[str], object], ...] = (
    # PEM of any kind, also cut off at the end of the block.
    (re.compile(r'-----BEGIN [^\n-]{0,64}-----.*?(?:-----END [^\n-]{0,64}-----|\Z)', re.S), REDACTED),
    # key=value and key: value, also inside longer names (db_password, X_TOKEN) and JSON ("token": "...").
    # Runs early and takes the rest of an unquoted value, like graph_mcp does (x-access-token:...@host goes whole).
    (re.compile(r'(?i)(' + _KEYWORD + r'[A-Za-z0-9_.-]{0,40}["\']?\s*(?:[:=]|%3[ADad])\s*)'
                r'(?:"(?:[^"\\\n]|\\.)*(?:"|$)|\'(?:[^\'\\\n]|\\.)*(?:\'|$)|\S+)', re.M), r'\1' + REDACTED),
    # URI userinfo; the scheme stays as it is and is not required (linear scan from '://').
    # The second form also catches passwords with '/' in them.
    (re.compile(r'://[^\s/@]*@'), '://' + REDACTED + '@'),
    (re.compile(r'://[^\s/@:]*:[^\s@]{0,256}@'), '://' + REDACTED + '@'),
    (re.compile(r'(?i)x-access-token:[^@\s]+'), 'x-access-token:' + REDACTED),
    # Credential headers: name and value go, so final_scan never sees the word Authorization afterwards.
    (re.compile(r'(?i)\b(?:proxy-authorization|authorization|set-cookie|cookie|x-api-key|x-auth-token|private-token'
                r'|x-github-token)["\']?\s*[:=][^\r\n]*'), REDACTED),
    (re.compile(r'(?i)\bbearer\s+[^\s,;]+'), 'Bearer ' + REDACTED),
    (re.compile(r'\bBasic\s+[A-Za-z0-9+/]{8,}={0,2}'), 'Basic ' + REDACTED),
    (re.compile(r'(?i)\btoken\s+(?=[A-Za-z0-9_./+=-]*\d)[A-Za-z0-9_./+=-]{16,}'), 'token ' + REDACTED),
    (re.compile(r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*'), REDACTED),
    (re.compile(r'\bgithub_pat_[A-Za-z0-9_]{16,}'), REDACTED),
    (re.compile(r'\bgh[pousr]_[A-Za-z0-9]{16,}'), REDACTED),
    (re.compile(r'\bv1\.[0-9a-f]{40}\b'), REDACTED),
    (re.compile(r'\bsk-[A-Za-z0-9._-]{16,}'), REDACTED),
    (re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b'), REDACTED),
    (re.compile(r'\bxox[abposr]-[A-Za-z0-9-]{10,}'), REDACTED),
    (re.compile(r'\bAIza[0-9A-Za-z_-]{35}'), REDACTED),
    # SQL forms, also an unterminated quote at the end of a truncated line.
    (re.compile(r'(?i)\b((?:ENCRYPTED\s+)?PASSWORD|IDENTIFIED\s+BY)\s+(?:\'(?:[^\'\n]|\'\')*\'?|"[^"\n]*"?)'),
     r'\1 ' + REDACTED),
    (re.compile(r'(?i)\bPGPASSWORD\s*=\s*\S+'), 'PGPASSWORD=' + REDACTED),
    # Command-line flags with the value after a space (--password hunter2, -token abc).
    (re.compile(r'(?i)(?<![A-Za-z0-9])(--?[A-Za-z0-9_-]{0,30}' + _KEYWORD + r'[A-Za-z0-9_-]{0,30})\s+(?!-)\S+'),
     r'\1 ' + REDACTED),
    (re.compile(r'\b[0-9A-Fa-f]{64,}\b'), REDACTED),
)
_IPV6 = re.compile(r'(?<![0-9A-Za-z:.])(?:[0-9A-Fa-f]{0,4}:){2,7}(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9A-Fa-f]{0,4})'
                   r'(?![0-9A-Za-z:])')
_IPV4 = re.compile(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)')
_EMAIL = re.compile(r'(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b')
_HOME = re.compile(r'/(home|Users)/(?!\[USER\])[^/\s:\'"]+')

# final_scan: deliberately different patterns from the chain above.
_SCAN = (
    re.compile(r'-----BEGIN'),
    re.compile(r'PRIVATE KEY-----'),
    re.compile(r'://[^\s/@:]{0,256}:[^\s/@]{0,256}@'),
    re.compile(r'(?i)\bauthori[sz]ation\b'),
    re.compile(r"(?i)\bpassword\s+'"),
    re.compile(r'\bgh[opsur]_'),
    re.compile(r'github_pat_'),
)
_RUN = re.compile(r'[A-Za-z0-9+/_-]{32,}')
_HEX_RUN = re.compile(r'(?<![A-Za-z0-9])[0-9A-Fa-f]{32,}(?![A-Za-z0-9])')
_SHA1 = re.compile(r'[0-9a-f]{40}')

_BLOCK_SPLIT = re.compile(r'(\n[ \t]*\n(?:[ \t]*\n)*)')
_WHITESPACE = re.compile(r'\s+')
_BIDI = re.compile('[\u202a-\u202e\u2066-\u2069]')
_MENTION = re.compile(r'@(?=[A-Za-z0-9_-])')
_ISSUE_REF = re.compile(r'#(?=\d)')
_TIM_TAG = re.compile(r'(?i)(tim)_')
_BACKTICKS = re.compile(r'`+')


def _text(value) -> str:
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'replace')
    if not isinstance(value, str):
        raise TypeError('redaction works on text only')
    return value.replace('\r\n', '\n').replace('\r', '\n')


def literal_variants(secret: str) -> list[str]:
    """Every form in which `secret` may show up in a log: exact, URL-encoded, Base64 (standard and URL-safe) in all three
    byte alignments. Base64 parts that depend on neighbouring bytes are cut off. Secrets under MIN_LITERAL give []."""
    if isinstance(secret, bytes):
        secret = secret.decode('utf-8', 'replace')
    secret = str(secret).strip()
    if len(secret) < MIN_LITERAL:
        return []
    raw = secret.encode('utf-8')
    found = [secret, quote(secret, safe=''), quote_plus(secret, safe='')]
    found.append(re.sub(r'%[0-9A-F]{2}', lambda m: m[0].lower(), found[1]))
    for offset in range(3):
        encoded = base64.b64encode(b'\0' * offset + raw).decode('ascii')
        start, end = -(-8 * offset // 6), 8 * (offset + len(raw)) // 6
        piece = encoded[start:end]
        found.extend((piece, piece.replace('+', '-').replace('/', '_')))
    unique = []
    for item in found:
        if len(item) >= MIN_VARIANT and item not in unique:
            unique.append(item)
    return unique


def _variants(literals) -> list[tuple[str, str]]:
    if isinstance(literals, (str, bytes)):
        literals = (literals,)
    pairs = []
    for secret in literals or ():
        for variant in literal_variants(secret):
            pairs.append((variant, _WHITESPACE.sub('', variant)))
    return pairs


def _holds_literal(block: str, variants) -> bool:
    if not variants:
        return False
    compact = _WHITESPACE.sub('', block)
    return any(exact in block or packed in compact for exact, packed in variants)


def _ipv6(match: re.Match[str]) -> str:
    text = match[0]
    if '::' not in text and text.count(':') != 7:
        return text                     # times like 03:15:00 and MAC addresses are not addresses here
    try:
        address = ipaddress.IPv6Address(text)
    except ValueError:
        return text
    return text if address.is_loopback or address.is_unspecified else IP


def _ipv4(match: re.Match[str]) -> str:
    try:
        address = ipaddress.IPv4Address(match[0])
    except ValueError:
        return match[0]
    return match[0] if address.is_loopback or address.is_unspecified else IP


def _chain(text: str) -> str:
    for pattern, replacement in _CHAIN:
        text = pattern.sub(replacement, text)
    text = _IPV6.sub(_ipv6, text)
    text = _IPV4.sub(_ipv4, text)
    text = _EMAIL.sub(EMAIL, text)
    return _HOME.sub(lambda m: f'/{m[1]}/{USER}', text)


def _mixed(value: str) -> bool:
    return (any(c.isupper() for c in value) and any(c.islower() for c in value)
            and any(c.isdigit() for c in value))


def _suspicious_run(run: str) -> bool:
    if not _mixed(run):
        return False
    if '/' not in run:
        return True
    # A path or URL is long because of its separators; a Base64 secret has long mixed parts between them.
    return any(len(part) >= 10 and _mixed(part) for part in run.split('/'))


def final_scan(text: str) -> bool:
    """True when `text` still looks like it holds a secret. Independent of the regex chain. Exempt: 40-character
    lowercase hex (commit SHA-1). A 64-hex fingerprint counts as suspicious, so markers are appended after scanning."""
    text = _text(text)
    if any(pattern.search(text) for pattern in _SCAN):
        return True
    if any(_suspicious_run(match[0]) for match in _RUN.finditer(text)):
        return True
    return any(not _SHA1.fullmatch(match[0]) for match in _HEX_RUN.finditer(text))


def redact(text: str, literals=()) -> str:
    """Redacted copy of `text`, see the module text. Blocks are paragraphs; blank-line separators are kept."""
    text = _text(text)
    variants = _variants(literals)
    pieces = _BLOCK_SPLIT.split(text)
    for index in range(0, len(pieces), 2):
        block = pieces[index]
        if not block.strip():
            continue
        if _holds_literal(block, variants):
            pieces[index] = LITERAL_REMOVED
            continue
        block = _chain(block)
        pieces[index] = BLOCK_REMOVED if final_scan(block) else block
    result = ''.join(pieces)
    return BLOCK_REMOVED if final_scan(result) else result


def neutralize(text: str) -> str:
    """Break what GitHub would act on: @mentions, #123 links, HTML comments (fake markers) and TIM_ tags. Bidi
    controls become U+FFFD. Idempotent."""
    text = _BIDI.sub('\ufffd', _text(text))
    text = _MENTION.sub('@' + ZWSP, text)
    text = _ISSUE_REF.sub('#' + ZWSP, text)
    text = text.replace('<!--', '<' + ZWSP + '!--').replace('-->', '--' + ZWSP + '>')
    return _TIM_TAG.sub(lambda m: m[1] + ZWSP + '_', text)


def fence(text: str) -> str:
    """`neutralize(text)` inside a code fence longer than any backtick run in it: no link, image or HTML renders."""
    body = neutralize(text)
    longest = max((len(run) for run in _BACKTICKS.findall(body)), default=0)
    ticks = '`' * max(3, longest + 1)
    return f'{ticks}text\n{body.rstrip(chr(10))}\n{ticks}'


def untrusted_block(text: str, literals=()) -> str:
    """The only way log or model text may enter a comment: redact, then fence."""
    return fence(redact(text, literals))
