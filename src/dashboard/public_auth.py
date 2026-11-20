"""Login for the private pages of the public view (live account, paper journal).

The chart stays open. ``/journal``, ``/journal/trade``, ``/live`` and ``/api/plan-journal`` need HTTP Basic
login (the tunnel is HTTPS). The login lives only in a file outside the repo, with a salted PBKDF2 hash,
never a plain password. Fails closed: no file, a broken file or an empty hash means nobody gets in (503).

Create or replace the login on the Mac: ``python -m src.dashboard.public_auth init`` (writes the file with
mode 0600 and prints the generated password once; nothing is stored in the repo or in logs).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Callable

AUTH_FILE_ENV = "TIM_PUBLIC_AUTH_FILE"
AUTH_FILE = Path.home() / "Library/Application Support/TIM/public-auth.json"
PROTECTED = frozenset({"/journal", "/journal/trade", "/live", "/api/plan-journal"})
ITERATIONS = 600_000
MAX_AUTH_FILE_BYTES = 4096
MAX_HEADER = 512
REALM = "TIM private pages"
FAIL_LIMIT, FAIL_WINDOW = 5, 300  # failed logins per client in this many seconds, then a pause
GLOBAL_FAIL_LIMIT = 20  # the same, over all clients together


def auth_file() -> Path:
    return Path(os.environ.get(AUTH_FILE_ENV) or AUTH_FILE)


def hash_password(password: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> dict:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return {"user": "", "salt": salt.hex(), "hash": digest.hex(), "iterations": iterations}


def load_credentials(path: Path | None = None) -> dict | None:
    """User, salt, hash and iterations; ``None`` when the file is missing, too big or incomplete."""
    path = path or auth_file()
    try:
        if path.stat().st_size > MAX_AUTH_FILE_BYTES:
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        user, salt, digest, rounds = str(raw["user"]), bytes.fromhex(raw["salt"]), bytes.fromhex(raw["hash"]), int(raw["iterations"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not user or not salt or not digest or rounds < 100_000:
        return None
    return {"user": user, "salt": salt, "hash": digest, "iterations": rounds}


def check_login(authorization: str | None, credentials: dict | None) -> bool:
    if not credentials or not authorization or len(authorization) > MAX_HEADER:
        return False
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        user, _, password = base64.b64decode(token.strip(), validate=True).decode().partition(":")
    except (binascii.Error, ValueError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), credentials["salt"], credentials["iterations"])
    user_ok = hmac.compare_digest(user.encode(), credentials["user"].encode())
    return hmac.compare_digest(digest, credentials["hash"]) and user_ok


class FailureLimiter:
    """Pauses password guessing. Each attempt is counted before the slow check, under one lock (no burst gets past it).

    Per client, and also over all clients together: the client name comes from tunnel headers a guesser may
    forge, so the global limit is the one that cannot be dodged. It can pause the owner too; that is the safe side."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock, self.lock = clock, threading.Lock()
        self.fails: dict[str, list[float]] = {}
        self.all_fails: list[float] = []

    def reserve(self, key: str) -> bool:
        """Count one attempt; False when the client or the whole view is over its limit."""
        now = self.clock()
        with self.lock:
            self.all_fails = [t for t in self.all_fails if now - t < FAIL_WINDOW]
            recent = [t for t in self.fails.get(key, []) if now - t < FAIL_WINDOW]
            if len(recent) >= FAIL_LIMIT or len(self.all_fails) >= GLOBAL_FAIL_LIMIT:
                self.fails[key] = recent
                return False
            if len(self.fails) > 10_000:
                self.fails.clear()
            self.fails[key] = recent + [now]
            self.all_fails.append(now)
            return True

    def release(self, key: str) -> None:
        """A correct login does not count."""
        with self.lock:
            if self.fails.get(key):
                self.fails[key].pop()
            if self.all_fails:
                self.all_fails.pop()


def init_login(path: Path | None = None, user: str = "uzi") -> str:
    """Write a new login file (0600) and return the generated password."""
    path = path or auth_file()
    password = secrets.token_urlsafe(18)
    record = {**hash_password(password), "user": user}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle)
    os.replace(tmp, path)
    return password


if __name__ == "__main__":
    if sys.argv[1:] == ["init"]:
        target = auth_file()
        print(f"login file: {target}\nuser: uzi\npassword (shown once): {init_login(target)}")
    else:
        print("usage: python -m src.dashboard.public_auth init")
        sys.exit(2)
