"""src/tim_incident/redaction.py: regex chain, literal blackout, independent final scan, fencing (design A.5, section 15)."""
from __future__ import annotations

import base64
import re
import time

import pytest

from src.bugfixer.processing import redact_text as bugfixer_redact
from src.graph_mcp.redaction import redact_text as graph_redact
from src.tim_incident import redaction
from src.tim_incident.redaction import (
    BLOCK_REMOVED, EMAIL, IP, LITERAL_REMOVED, REDACTED, ZWSP,
    fence, final_scan, literal_variants, neutralize, redact, untrusted_block,
)

# Synthetic values only; none of them is or was a real credential.
GHP = 'ghp_' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8'
GHO = 'gho_' + 'Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2'
GHS = 'ghs_' + 'Q1w2E3r4T5y6U7i8O9p0A1s2D3f4G5h6J7k8'
GHU = 'ghu_' + 'M1n2B3v4C5x6Z7l8K9j0H1g2F3d4S5a6P7o8'
GHR = 'ghr_' + 'L1k2J3h4G5f6D7s8A9q0W1e2R3t4Y5u6I7o8'
PAT = 'github_pat_11ABCDEFG0aBcDeFgHiJkL_' + 'mNoPqRsTuVwXyZ0123456789aBcDeFgHiJkLmNoPqRsTuVwXyZ01234'
SQL_PASSWORD = 'Qm7Lx2Vb9Nc4Zt8Wk1Rp6Hs3Jd5Fg0Ya2Ue7Io4P'      # 40 characters like bootstrap.sh generates
HEX64 = '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08'
SHA1 = '0123456789abcdef0123456789abcdef01234567'
PEM = ('-----BEGIN RSA PRIVATE KEY-----\n'
       'MIIEpAIBAAKCAQEAu1SU1LfVLPHCozMxH2Mo4lgOEePzNm0tRgeLezV6ffAt0gun\n'
       'VTLw7onLRnrq0/IzW7yWR7QkrmBL7jTKEn5u+qKhbwKfBstIs+bMY2Zkp18gnTxK\n'
       '-----END RSA PRIVATE KEY-----')

JOURNAL = f'''2026-10-07T03:10:00+0000 tim-core-01 python[812]: Started tim-runtime.service - TIM runtime.
2026-10-07T03:10:01+0000 tim-core-01 python[812]: connect postgresql://tim:Xy9secretPw44@192.168.1.20:5432/tim failed
2026-10-07T03:10:02+0000 tim-core-01 python[812]: settings password=hunter2isweak user=tim
2026-10-07T03:10:03+0000 tim-core-01 python[812]: request headers Authorization: Bearer abcDEF123456ghiJKL789mno
2026-10-07T03:10:04+0000 tim-core-01 python[812]: plain Bearer zyxWVU987654tsrQPO321 seen
2026-10-07T03:10:05+0000 tim-core-01 python[812]: tokens {GHP} {GHO} {GHS} {GHU} {GHR}
2026-10-07T03:10:06+0000 tim-core-01 python[812]: fine grained {PAT}
2026-10-07T03:10:07+0000 tim-core-01 postgres[901]: statement: ALTER ROLE tim WITH LOGIN CREATEDB PASSWORD '{SQL_PASSWORD}';
2026-10-07T03:10:08+0000 tim-core-01 git[77]: fetch https://x-access-token:{GHS}@github.com/o/r.git
2026-10-07T03:10:08+0000 tim-core-01 sh[78]: x-access-token:v1Plain0Secret9Token
2026-10-07T03:10:09+0000 tim-core-01 sh[78]: PGPASSWORD=Pg9Sup3rS3cret psql -h 127.0.0.1 -U tim
2026-10-07T03:10:10+0000 tim-core-01 python[812]: key {PEM}
2026-10-07T03:10:11+0000 tim-core-01 python[812]: peer 203.0.113.77 and 2001:db8::8a2e:370:7334 local 127.0.0.1 and ::1
2026-10-07T03:10:12+0000 tim-core-01 python[812]: mail to uezeyir.aydin@example.com failed
2026-10-07T03:10:13+0000 tim-core-01 python[812]: File "/home/uzi/tim/src/data_ingestion/catchup.py", line 251
2026-10-07T03:10:14+0000 tim-core-01 python[812]: sk-proj-abcdefghijklmnopqrstuv and digest {HEX64}
2026-10-07T03:10:15+0000 tim-core-01 python[812]: deployed commit {SHA1} at 03:15:00
2026-10-07T03:10:16+0000 tim-core-01 python[812]: Binance public stream disconnected; retrying in 5s'''

JOURNAL_SECRETS = (
    'Xy9secretPw44', 'hunter2isweak', 'abcDEF123456ghiJKL789mno', 'zyxWVU987654tsrQPO321', GHP, GHO, GHS, GHU, GHR,
    PAT, SQL_PASSWORD, 'v1Plain0Secret9Token', 'Pg9Sup3rS3cret', 'MIIEpAIBAAKCAQEAu1SU1LfVLPHCozMxH2Mo4lgOEePzNm0tRgeLezV6ffAt0gun',
    'BEGIN RSA', '192.168.1.20', '203.0.113.77', '2001:db8::8a2e:370:7334', 'uezeyir.aydin@example.com', '/home/uzi',
    'sk-proj-abcdefghijklmnopqrstuv', HEX64,
)


def test_journal_fixture_redacted():
    out = redact(JOURNAL)
    for secret in JOURNAL_SECRETS:
        assert secret not in out, secret
    # The chain alone must leave nothing for final_scan, otherwise the whole journal block would be dropped.
    assert BLOCK_REMOVED not in out and LITERAL_REMOVED not in out
    assert 'Started tim-runtime.service - TIM runtime.' in out
    assert 'Binance public stream disconnected; retrying in 5s' in out
    assert 'catchup.py", line 251' in out and '/home/[USER]/tim/src' in out
    assert f'{IP}:5432' in out and f'peer {IP} and {IP} local 127.0.0.1 and ::1' in out
    assert f'mail to {EMAIL} failed' in out
    assert f'PASSWORD {REDACTED}' in out and f'PGPASSWORD={REDACTED}' in out
    assert f'commit {SHA1} at 03:15:00' in out          # a commit SHA-1 and a time of day are not secrets
    assert out.count('\n') == JOURNAL.count('\n') - 3   # only the PEM lines collapse
    assert not final_scan(out)


def test_redact_is_deterministic_and_idempotent():
    once = redact(JOURNAL)
    assert redact(JOURNAL) == once
    assert redact(once) == once


@pytest.mark.parametrize('line, secret', [
    ('db_password: "a b c" next', 'a b c'),
    ('{"password": "esc\\"aped tail", "u": 1}', 'aped tail'),
    ("{'api_key': 'k3y-Value-123'}", 'k3y-Value-123'),
    ('{"token":"tok-123-abc","n":1}', 'tok-123-abc'),
    ('my_secret_key=topsecret123', 'topsecret123'),
    ('client_secret = cs_live_99', 'cs_live_99'),
    ('passphrase=open-sesame-42', 'open-sesame-42'),
    ('X_ACCESS_KEY=AKfake0123', 'AKfake0123'),
    ('IDENTIFIED BY "orcl-Pass1"', 'orcl-Pass1'),
    ("PASSWORD 'unterminated-at-end-of-line", 'unterminated-at-end-of-line'),
    ('Cookie: session=0123abcdSESSIONvalue', '0123abcdSESSIONvalue'),
    ('proxy-authorization=Basic dXNlcjpwYXNzd29yZA==', 'dXNlcjpwYXNzd29yZA'),
    ('header Basic dXNlcjpwYXNzd29yZA==', 'dXNlcjpwYXNzd29yZA'),
    ('jwt eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiIxMjM0NSJ9.c2lnbmF0dXJlLXBhcnQ', 'eyJpc3MiOiIxMjM0NSJ9'),
    ('redis://:pa?ss123word@cache:6379/0', 'pa?ss123word'),
    ('postgres://tim:pa/ss9word@db/tim', 'pa/ss9word'),
    ('AKIAABCDEFGHIJKLMNOP is aws', 'AKIAABCDEFGHIJKLMNOP'),
    ('legacy v1.' + 'a' * 40 + ' token', 'v1.' + 'a' * 40),
    ('/Users/uzi/Library/TIM', '/Users/uzi'),
    ('psql --password hunter2xyz -h x', 'hunter2xyz'),
    ('url?password%3Dhunter2xyz&x=1', 'hunter2xyz'),
])
def test_additional_forms_redacted(line, secret):
    out = redact(line)
    assert secret not in out
    assert not final_scan(out)


def test_ip_and_time_shapes():
    out = redact('at 10:00:00 mac aa:bb:cc:dd:ee:ff v1.2.3.4.5 bind 0.0.0.0 and :: ollama 127.0.0.2 lan 10.0.0.5. '
                 'v6 fe80::1%eth0 full 2001:0db8:85a3:0000:0000:8a2e:0370:7334 cpp std::vector')
    assert '10:00:00' in out and 'aa:bb:cc:dd:ee:ff' in out and 'v1.2.3.4.5' in out
    assert '0.0.0.0' in out and ' :: ' in out and '127.0.0.2' in out and 'std::vector' in out
    assert '10.0.0.5' not in out and 'fe80::1' not in out and '8a2e:0370' not in out
    assert out.count(IP) == 3


# --- literal blackout ----------------------------------------------------------------------------------------------

# Lower case and digits only, with no key in front: neither the chain nor final_scan would catch it.
LITERAL = 'k3vq9xw2m7pz/4tr8yb6nd1hs!'


def test_literal_variants_cover_url_and_base64_alignments():
    variants = literal_variants(LITERAL)
    assert variants[0] == LITERAL
    assert 'k3vq9xw2m7pz%2F4tr8yb6nd1hs%21' in variants and 'k3vq9xw2m7pz%2f4tr8yb6nd1hs%21' in variants
    for offset in range(3):
        for prefix in (b'', b'\x00', b'\xff\xfe', b'ab'):
            if len(prefix) % 3 != offset % 3:
                continue
            for encode in (base64.b64encode, base64.urlsafe_b64encode):
                encoded = encode(prefix + LITERAL.encode() + b'tail').decode()
                assert any(variant in encoded for variant in variants), (offset, prefix)
    assert all(len(variant) >= redaction.MIN_VARIANT for variant in variants)
    assert literal_variants('  ' + LITERAL + '\n') == variants
    assert literal_variants('short') == [] and literal_variants('') == []
    assert literal_variants(LITERAL.encode()) == variants


def test_literal_secret_plain_url_base64_removed():
    assert redact(f'value {LITERAL} here') == f'value {LITERAL} here'   # without literals nothing would catch it
    blocks = ['benign first block', f'plain {LITERAL} end', 'url k3vq9xw2m7pz%2F4tr8yb6nd1hs%21 end']
    for prefix in (b'', b'x', b'xy'):
        blocks.append('b64 ' + base64.b64encode(prefix + LITERAL.encode() + b'!!').decode())
        blocks.append('b64url ' + base64.urlsafe_b64encode(prefix + LITERAL.encode()).decode())
    wrapped = base64.b64encode(b'zz' + LITERAL.encode()).decode()
    blocks.append('wrapped\n' + wrapped[:17] + '\n' + wrapped[17:])
    blocks.append('benign last block')
    out = redact('\n\n'.join(blocks), literals=[LITERAL])
    assert out.split('\n\n') == ['benign first block'] + [LITERAL_REMOVED] * (len(blocks) - 2) + ['benign last block']
    # A single string is one secret, not a list of characters; bytes work too.
    assert redact(f'a {LITERAL}', literals=LITERAL) == LITERAL_REMOVED
    assert redact(f'a {LITERAL}', literals=[LITERAL.encode()]) == LITERAL_REMOVED
    assert redact('a b c', literals=[LITERAL]) == 'a b c'


def test_literal_hit_removes_whole_block_only():
    text = f'line one\nline two {LITERAL}\nline three\n\n\nother paragraph'
    assert redact(text, [LITERAL]) == f'{LITERAL_REMOVED}\n\n\nother paragraph'


# --- final scan ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('fixture', [
    'deploy blob 9fK2mPx7Lw4Rt8Vn3Bc6Hs1Dg5Jy0EaQzX',      # bare high-entropy string, no key, no known prefix
    'short gho_abc1 prefix',                               # too short for the chain's token rule
    'Authorization failed for client',                     # the word itself, no header form
    'truncated -----BEGIN RSA PRIVATE KEY',                # no closing dashes, so not a PEM for the chain
    'md5 0123456789abcdef0123456789abcdef',                # 32 hex
    'wrapped key part abcDEF0123/ghiJKL4567+mnoPQR8901stuVWX',
])
def test_final_scan_independent(fixture):
    assert REDACTED not in redaction._chain(fixture)       # the chain lets it through ...
    assert final_scan(fixture)                             # ... the independent scan does not
    assert redact(f'{fixture}\nsecond line\n\nkept') == f'{BLOCK_REMOVED}\n\nkept'


def test_final_scan_flags_fingerprint_but_not_commit_sha():
    assert final_scan('<!-- TIM_TASK_FINGERPRINT:' + HEX64 + ' -->')
    assert not final_scan(f'Commit /opt/tim: {SHA1}')
    assert final_scan(SHA1.upper())


@pytest.mark.parametrize('text', [
    '''## Vorfall DATA_FLOW auf tim-core-01
cc @uezeyiraydin-cell
- Erkannt: 2026-10-07 03:15 UTC (Checkup); fehlschlagende Prüfungen: candle_freshness, gap_last_60m
- Unterbefunde: watchdog.collector_freshness, watchdog.data_age
- Commit /opt/tim: abc1234 (aus .git gelesen)
- Einordnung (feste Regel): ops
- Behebung: Datenfluss der Runtime prüfen (Kerzen, Lücken, Nachholen), siehe docs/TIM_CHECKUP.md.
<!-- TIM_INCIDENT_V1 class=DATA_FLOW episode=20261007T0315Z host=tim-core-01 -->''',
    'repos/TIM-Intelegence-market/tim-ai-platform/issues/123',
    'TIM_CHECKUP_REPORTER_LOGIN=tim-reporter2[bot] TIM_CHECKUP_APP_ID=123456',
    '/var/lib/postgresql/16/main/pg_wal/000000010000000000000001',
    '123E4567-E89B-12D3-A456-426614174000 and 123e4567-e89b-12d3-a456-426614174000',
    'TIM-CORE-01.20261007T0315Z src/tim_incident/checkup.py:251 2026-10-07T03:15:00+00:00',
    'test_resolve_threshold_doubles_per_reopen',
])
def test_final_scan_quiet_on_fixed_texts(text):
    assert not final_scan(text)


# --- parity with the existing chains (design E8) ----------------------------------------------------------------------

PARITY_CORPUS = [
    ('postgresql://tim:S3cretPassw0rd@db.internal:5432/tim', ['S3cretPassw0rd']),
    ('DATABASE_URL=postgresql://tim:pw0rd123@localhost/tim', ['pw0rd123']),
    ('redis://:pa?ss123word@cache:6379', ['pa?ss123word']),
    ('Authorization: Bearer abcDEF123456ghiJKL789', ['abcDEF123456ghiJKL789']),
    ('authorization=Basic dXNlcjpwYXNzd29yZA==', ['dXNlcjpwYXNzd29yZA']),
    ('Proxy-Authorization: Basic Zm9vOmJhcg==', ['Zm9vOmJhcg']),
    ('Authorization: token ' + GHS, [GHS]),
    ('Cookie: session=0123abcdSESSIONvalue', ['0123abcdSESSIONvalue']),
    ('Set-Cookie: sid=XYZsecretCookie99; Path=/', ['XYZsecretCookie99']),
    ('sent Bearer abcdefghijklmnop1234 upstream', ['abcdefghijklmnop1234']),
    ('password=hunter2xyz', ['hunter2xyz']),
    ('password: hunter2xyz', ['hunter2xyz']),
    ('passwd = hunter2xyz', ['hunter2xyz']),
    ("passphrase='my pass phrase'", ['my pass phrase']),
    ('"secret": "s3cr3t-value"', ['s3cr3t-value']),
    ('token=tok_123456789', ['tok_123456789']),
    ('access_token=abc.def.ghi123', ['abc.def.ghi123']),
    ('refresh_token: r3fr3sh-token-value', ['r3fr3sh-token-value']),
    ('api_key=AKfake123456', ['AKfake123456']),
    ('api-key: k3y-value-77', ['k3y-value-77']),
    ('apikey=xyz123456', ['xyz123456']),
    ('credential=cr3d-value', ['cr3d-value']),
    ('private_key=pk_value_123', ['pk_value_123']),
    ('password=abc123&user=bob123456', ['abc123', 'bob123456']),
    ('mytoken=embedded-0042', ['embedded-0042']),
    ('my_secret_key=topsecret123', ['topsecret123']),
    ('{"password": "p@ss w0rd!", "user": "tim"}', ['p@ss w0rd!']),
    (f'using {GHP} now', [GHP]),
    (f'using {PAT} now', [PAT]),
    (f'oauth {GHO}', [GHO]),                                    # design: leaks through both chains
    (f'server {GHS}', [GHS]),                                   # design: leaks through both chains
    (f'user {GHU} refresh {GHR}', [GHU, GHR]),
    ('openai sk-proj-abcdefghijklmnopqrstuv', ['sk-proj-abcdefghijklmnopqrstuv']),
    (f'digest {HEX64}', [HEX64]),
    (f"ALTER ROLE tim WITH LOGIN PASSWORD '{SQL_PASSWORD}';", [SQL_PASSWORD]),   # design: leaks through both
    (f'https://x-access-token:{GHS}@github.com/o/r.git', [GHS]),
    ('x-access-token:plainSecret0042', ['plainSecret0042']),
    ('PGPASSWORD=Zx81Qw9pp PGHOST=localhost psql', ['Zx81Qw9pp']),
    (PEM, ['MIIEpAIBAAKCAQEAu1SU1LfVLPHCozMxH2Mo4lgOEePzNm0tRgeLezV6ffAt0gun']),
    ('-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ\n-----END OPENSSH PRIVATE KEY-----',
     ['b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ']),
    ('token: eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiIxMjMifQ.c2lnbmF0dXJl', ['eyJpc3MiOiIxMjMifQ']),
]
_CHAINS = {
    'bugfixer': bugfixer_redact,
    'graph': graph_redact,
    'bugfixer+graph': lambda text: graph_redact(bugfixer_redact(text)),
}
# Key names may survive in our output (password=[REDACTED]) while an older chain drops them; values never may.
_KEY_WORD = re.compile(r'(?i)pass|secret|token|bearer|basic|authori[sz]ation|cookie|credential|api.?key|private.?key')
_WORD = re.compile(r'[A-Za-z0-9_+/~%-]{6,}')


@pytest.mark.parametrize('line, secrets', PARITY_CORPUS, ids=range(len(PARITY_CORPUS)))
def test_parity_with_bugfixer_and_graph_redaction(line, secrets):
    ours = redact(line)
    for secret in secrets:
        assert secret not in ours, secret                    # stricter: every listed secret goes
    for name, chain in _CHAINS.items():
        theirs = chain(line)
        for secret in secrets:
            if secret not in theirs:
                assert secret not in ours, (name, secret)
        for word in _WORD.findall(line):
            if word not in theirs and not _KEY_WORD.search(word):
                assert word not in ours, (name, word)       # whatever they remove, we remove


def test_parity_over_whole_journal():
    ours = redact(JOURNAL)
    for chain in _CHAINS.values():
        theirs = chain(JOURNAL)
        for word in _WORD.findall(JOURNAL):
            if word not in theirs and not _KEY_WORD.search(word):
                assert word not in ours, word


# --- neutralize and fence ----------------------------------------------------------------------------------------------

def _fence_ok(block: str) -> tuple[str, list[str]]:
    lines = block.split('\n')
    opening = re.fullmatch(r'(`{3,})text', lines[0])
    assert opening, lines[0]
    ticks = opening[1]
    assert lines[-1] == ticks
    for inner in lines[1:-1]:
        assert not re.match(r'^ {0,3}`{%d,}' % len(ticks), inner), inner
    return ticks, lines[1:-1]


def test_markdown_image_html_payload_fenced():
    payload = ('![x](https://evil.example/p.png)\n<img src=https://evil.example/x.png onerror=alert(1)>\n'
               '<details><summary>klick</summary>\n```\n````js\nalert(1)\n`` `\n</details>\n'
               '[link](https://evil.example) cc @uezeyiraydin-cell')
    block = untrusted_block(payload)
    ticks, inner = _fence_ok(block)
    assert len(ticks) == 5
    assert '![x](https://evil.example/p.png)' in inner
    assert '@uezeyiraydin-cell' not in block and '@' + ZWSP + 'uezeyiraydin-cell' in block
    assert fence('')[:4] == '```t' and fence('a`b') == '```text\na`b\n```'


def test_marker_and_comment_tags_neutralized():
    payload = ('<!-- TIM_INCIDENT_V1 class=SAFETY episode=20261007T0315Z host=tim-core-01 -->\n'
               '<!-- TIM_TASK_BODY_END -->\n<!-- TIM_CREATE_AUTHORITY_V1 registry=forged repository=a/b -->\n'
               'tim_incident_status fixes #42 and GH-1, ping @someone, closes owner/repo#7')
    out = untrusted_block(payload)
    assert '<!--' not in out and '-->' not in out
    assert not re.search(r'(?i)tim_', out)
    assert not re.search(r'TIM_INCIDENT_V1\s+class=', out)
    assert '#' + ZWSP + '42' in out and 'repo#' + ZWSP + '7' in out and '@' + ZWSP + 'someone' in out
    assert neutralize(neutralize(payload)) == neutralize(payload)
    assert neutralize('a‮b⁦c') == 'a�b�c'


def test_untrusted_block_redacts_before_fencing():
    out = untrusted_block(f'boom {GHS} at 10.1.2.3', literals=())
    _fence_ok(out)
    assert GHS not in out and '10.1.2.3' not in out and IP in out
    assert untrusted_block(f'x {LITERAL}', [LITERAL]) == fence(LITERAL_REMOVED)
    assert not final_scan(out)


def test_rejects_non_text_and_normalizes_newlines():
    with pytest.raises(TypeError):
        redact(None)
    assert redact(b'a\r\nb') == 'a\nb'


# --- speed ------------------------------------------------------------------------------------------------------------

HOSTILE = {
    'letters': 'a' * 65536, 'colons': ':' * 65536, 'schemes': '://' * 20000, 'token-words': 'token ' * 10000,
    'hex-then-g': '0' * 65536 + 'g', 'jwt-prefix': 'eyJ' * 20000, 'pem-begins': '-----BEGIN X-----' * 3000,
    'alnum': 'a1' * 32768, 'at-signs': 'x@' * 30000, 'keys': 'password=' * 7000, 'hex-colons': 'ab:' * 20000,
    'blank-lines': '\n\n' * 30000, 'journal': JOURNAL * 30,
}


@pytest.mark.parametrize('payload', HOSTILE.values(), ids=HOSTILE.keys())
def test_redaction_stays_fast_on_hostile_input(payload):
    started = time.perf_counter()
    out = untrusted_block(payload, literals=[LITERAL, SQL_PASSWORD])
    assert time.perf_counter() - started < 3.0
    assert isinstance(out, str)
