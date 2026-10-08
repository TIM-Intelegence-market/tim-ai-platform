"""GitHub App identity of the incident reporter (design B.1, E7, section 18).

Per run: a JWT (RS256, signed by the `openssl` CLI, no Python crypto dependency) buys one installation token that is
narrowed to the one repository and to issues:write + metadata:read. The token lives only in memory and only in the
Authorization header. Every error here carries a fixed text and a `kind`, never the key, the JWT or the token.

The key comes from systemd `LoadCredential=` as `$CREDENTIALS_DIRECTORY/github-app-key`. `GET /user` is never used:
installation tokens get 403 there.
"""
from __future__ import annotations

import base64
import json
import os
import re
import stat
import subprocess
from pathlib import Path

from src.task_governance.github_gateway import _NotSent

API = 'https://api.github.com'
KEY_NAME = 'github-app-key'
TOKEN_PERMISSIONS = {'issues': 'write', 'metadata': 'read'}
JWT_BACKDATE_SECONDS = 60       # clock drift towards GitHub
JWT_LIFETIME_SECONDS = 540      # GitHub allows at most 600
OPENSSL_TIMEOUT = 10.0
REQUEST_TIMEOUT = 20.0
MAX_KEY_BYTES = 16 * 1024
_TOKEN = re.compile(r'^[\x21-\x7e]{20,512}$')
_REPOSITORY_NAME = re.compile(r'^[A-Za-z0-9_.-]{1,100}$')

# kinds, mapped one to one onto DeliveryReport.reporting by the reporter
KEY_MISSING = 'key_missing'
TOKEN_INVALID = 'token_invalid'
FORBIDDEN = 'forbidden'
RATE_LIMITED = 'rate_limited'
NETWORK_DOWN = 'network_down'


class AppTokenError(Exception):
    """No installation token. `kind` says why; the message is a fixed text."""

    def __init__(self, kind: str, text: str):
        super().__init__(text)
        self.kind = kind


def key_path(credentials_dir) -> Path | None:
    """`$CREDENTIALS_DIRECTORY/github-app-key`, or None without a credentials directory."""
    if not credentials_dir:
        return None
    return Path(credentials_dir) / KEY_NAME


def _read_key(path) -> bytes:
    if path is None:
        raise AppTokenError(KEY_MISSING, 'app key missing')
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    except OSError:
        raise AppTokenError(KEY_MISSING, 'app key missing') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_KEY_BYTES:
            raise AppTokenError(KEY_MISSING, 'app key missing')
        data = os.read(fd, MAX_KEY_BYTES + 1)
    except OSError:
        raise AppTokenError(KEY_MISSING, 'app key missing') from None
    finally:
        os.close(fd)
    if not data.strip():
        raise AppTokenError(KEY_MISSING, 'app key missing')     # the installer's empty placeholder
    return data


def key_lines(path) -> list[str]:
    """The lines of the key file, for literal redaction only. [] when the file is missing or unreadable."""
    try:
        data = _read_key(path)
    except AppTokenError:
        return []
    return [line.strip() for line in data.decode('utf-8', 'replace').splitlines() if line.strip()]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _run_openssl(argv, *, input, timeout):
    """Default runner: no shell, output captured (nothing reaches the journal), minimal environment."""
    return subprocess.run(argv, input=input, capture_output=True, timeout=timeout, check=False,
                          env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})


def build_jwt(app_id: int, path, *, runner=None, now: int) -> str:
    """RS256 JWT for the App: iat = now - 60, exp = now + 540, iss = app id. Signed by
    `openssl dgst -sha256 -sign <key> -binary` with the signing input on stdin."""
    if not isinstance(app_id, int) or isinstance(app_id, bool) or app_id <= 0:
        raise AppTokenError(TOKEN_INVALID, 'app id invalid')
    _read_key(path)                                         # missing or empty: key_missing before openssl runs
    header = _b64url(json.dumps({'alg': 'RS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    claims = {'iat': int(now) - JWT_BACKDATE_SECONDS, 'exp': int(now) + JWT_LIFETIME_SECONDS, 'iss': app_id}
    payload = _b64url(json.dumps(claims, separators=(',', ':')).encode())
    signing_input = f'{header}.{payload}'.encode('ascii')
    argv = ['openssl', 'dgst', '-sha256', '-sign', str(path), '-binary']
    try:
        result = (runner or _run_openssl)(argv, input=signing_input, timeout=OPENSSL_TIMEOUT)
        code, signature = result.returncode, result.stdout
    except Exception:                                       # openssl missing, timeout: never echo its stderr
        raise AppTokenError(KEY_MISSING, 'signing with openssl failed') from None
    if code != 0 or not isinstance(signature, bytes) or not signature:
        raise AppTokenError(KEY_MISSING, 'signing with openssl failed')
    return f'{header}.{payload}.{_b64url(signature)}'


def mint_installation_token(app_id: int, installation_id: int, key_path, *, runner=None, transport, now: int,
                            repository_name: str = 'tim-ai-platform', api: str = API,
                            timeout: float = REQUEST_TIMEOUT) -> str:
    """One installation token (1 h) narrowed to `repository_name` with issues:write and metadata:read."""
    if not isinstance(installation_id, int) or isinstance(installation_id, bool) or installation_id <= 0:
        raise AppTokenError(TOKEN_INVALID, 'installation id invalid')
    if not _REPOSITORY_NAME.match(repository_name or ''):
        raise AppTokenError(TOKEN_INVALID, 'repository name invalid')
    jwt = build_jwt(app_id, key_path, runner=runner, now=now)
    headers = {'Accept': 'application/vnd.github+json', 'Authorization': f'Bearer {jwt}',
               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'tim-checkup', 'Content-Type': 'application/json'}
    body = json.dumps({'repositories': [repository_name], 'permissions': dict(TOKEN_PERMISSIONS)}).encode('utf-8')
    url = f'{api.rstrip("/")}/app/installations/{installation_id}/access_tokens'
    failure = None
    try:
        status, raw = transport('POST', url, headers, body, timeout)
    except _NotSent:
        failure = AppTokenError(NETWORK_DOWN, 'github not reachable')
    except Exception:                                       # a transport message may hold the headers: never shown
        failure = AppTokenError(NETWORK_DOWN, 'token request failed')
    del jwt, headers
    if failure is not None:
        raise failure                                       # outside the except block: no context with headers
    if status != 201:
        raise _status_error(status)
    try:
        answer = json.loads(raw.decode('utf-8'))
    except (ValueError, AttributeError):
        raise AppTokenError(TOKEN_INVALID, 'token answer unreadable') from None
    token = answer.get('token') if isinstance(answer, dict) else None
    if not isinstance(token, str) or not _TOKEN.match(token):
        raise AppTokenError(TOKEN_INVALID, 'token answer unusable')
    granted = answer.get('permissions')
    if granted is not None and granted != TOKEN_PERMISSIONS:
        raise AppTokenError(TOKEN_INVALID, 'token has other permissions than requested')
    repositories = answer.get('repositories')
    if repositories is not None:
        names = [item.get('name') for item in repositories if isinstance(item, dict)] if isinstance(repositories, list) else None
        if names != [repository_name]:
            raise AppTokenError(TOKEN_INVALID, 'token is not limited to the repository')
    return token


def _status_error(status) -> AppTokenError:
    if status == 401:
        return AppTokenError(TOKEN_INVALID, 'app jwt rejected (HTTP 401)')
    if status == 403:
        return AppTokenError(FORBIDDEN, 'token request forbidden (HTTP 403)')
    if status == 429:
        return AppTokenError(RATE_LIMITED, 'token request rate limited (HTTP 429)')
    if status in (404, 422):
        return AppTokenError(TOKEN_INVALID, f'installation or repository refused (HTTP {int(status)})')
    if isinstance(status, int) and status >= 500:
        return AppTokenError(NETWORK_DOWN, f'github unavailable (HTTP {int(status)})')
    return AppTokenError(TOKEN_INVALID, 'token request refused')
