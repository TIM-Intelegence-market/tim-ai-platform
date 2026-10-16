from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Any


PASSWORD_ITERATIONS = 600_000
USERNAME_RE = re.compile(r"^[a-z][a-z0-9._-]{2,31}$")
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|cookie|password|secret|token)\s*[:=]\s*[^\s,;]+"
)


def validate_username(value: str) -> str:
    username = value.strip().lower()
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("Benutzername: 3–32 Zeichen, beginnend mit a–z; erlaubt sind a–z, 0–9, Punkt, _ und -.")
    return username


def validate_password(value: str) -> None:
    if len(value) < 14:
        raise ValueError("Das Passwort muss mindestens 14 Zeichen lang sein.")
    if len(value) > 256:
        raise ValueError("Das Passwort ist zu lang.")
    classes = sum(
        bool(re.search(pattern, value))
        for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]")
    )
    if classes < 3:
        raise ValueError("Das Passwort muss Zeichen aus mindestens drei Gruppen enthalten.")


def hash_password(value: str) -> str:
    validate_password(value)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(value: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", value.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact_text(value: str, limit: int = 12_000) -> str:
    return SECRET_RE.sub(r"\1=<REDACTED>", value)[:limit]


def redact_object(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(key): redact_object(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_object(item) for item in value]
    return value
