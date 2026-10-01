"""FRED/ALFRED API-key resolution on TIM's existing secret model.

Same rules as the database and OpenMarket secrets (config/secrets.py,
src/market_data/providers/openmarket/auth.py): exactly one explicitly selected
provider, no silent fallback, the value only lives inside a non-printable
``SecretValue`` and no error message ever contains it. Providers:

- ``keychain``: macOS Keychain (service/account configurable);
- ``file``: a regular file owned by the runtime user with mode 0600 or stricter
  (written by ``scripts/fred_store_key.py``);
- ``env``: ``TIM_FRED_API_KEY`` (hosts without a keychain).

Without ``TIM_FRED_SECRET_PROVIDER`` nothing is configured and every download
fails closed.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Mapping

from config.secrets import SecretProviderError, SecretValue, _require_private_regular_file, _safe_identifier

PROVIDER_ENV = "TIM_FRED_SECRET_PROVIDER"
KEY_ENV = "TIM_FRED_API_KEY"
FILE_ENV = "TIM_FRED_SECRET_FILE"
DEFAULT_SECRET_FILE = "~/Library/Application Support/TIM/fred-api-key"
# FRED documents the key as a "32 character alpha-numeric lowercase string".
KEY_SHAPE = re.compile(r"[a-z0-9]{32}")


class FredSecretError(RuntimeError):
    """The FRED key is not configured or malformed. Messages never contain the key."""


def describe_shape(raw: str) -> str:
    """Explain a malformed key by counts only, never by content."""
    return (
        f"length={len(raw)} uppercase={sum(c.isupper() for c in raw)} "
        f"whitespace={sum(c.isspace() for c in raw)} other={sum(not (c.isalnum() and c.isascii()) and not c.isspace() for c in raw)}"
    )


class FredSecretResolver:
    PROVIDERS = frozenset({"keychain", "file", "env"})

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = os.environ if env is None else env

    @property
    def provider(self) -> str | None:
        value = self.env.get(PROVIDER_ENV, "").strip().lower()
        if not value:
            return None
        if value not in self.PROVIDERS:
            raise FredSecretError(f"{PROVIDER_ENV} names an unsupported provider")
        return value

    def configured(self) -> bool:
        try:
            self.api_key()
        except FredSecretError:
            return False
        return True

    def api_key(self) -> SecretValue:
        provider = self.provider
        if provider is None:
            raise FredSecretError(f"{PROVIDER_ENV} is not set; store a key with scripts/fred_store_key.py")
        failure: str | None = None
        raw = ""
        try:
            if provider == "keychain":
                raw = self._keychain()
            elif provider == "file":
                path = Path(self.env.get(FILE_ENV, DEFAULT_SECRET_FILE)).expanduser()
                _require_private_regular_file(path)
                raw = path.read_text(encoding="utf-8", errors="replace").strip()
            else:
                raw = self.env.get(KEY_ENV, "").strip()
        except SecretProviderError as exc:
            # SecretProviderError messages are fixed texts without the value.
            failure = f"{provider} provider: {exc}"
        except OSError as exc:
            failure = f"{provider} provider: {exc.__class__.__name__}"
        if failure is not None:
            # Raised outside the except block: no exception chain keeps a provider error that may hold the value.
            raise FredSecretError(failure)
        if not KEY_SHAPE.fullmatch(raw):
            raise FredSecretError(f"FRED key has an invalid shape ({provider}: {describe_shape(raw)})")
        return SecretValue(raw)

    def _keychain(self) -> str:
        service = _safe_identifier(self.env.get("TIM_FRED_KEYCHAIN_SERVICE", "com.tim.fred"), label="Keychain service")
        account = _safe_identifier(self.env.get("TIM_FRED_KEYCHAIN_ACCOUNT", "tim"), label="Keychain account")
        completed = None
        try:
            completed = subprocess.run(
                ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
                check=False, capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass  # TimeoutExpired.output may hold the value: never chain it
        if completed is None or completed.returncode != 0:
            raise SecretProviderError("macOS Keychain FRED secret is unavailable")
        return completed.stdout.strip()


__all__ = ["DEFAULT_SECRET_FILE", "FILE_ENV", "KEY_ENV", "KEY_SHAPE", "PROVIDER_ENV", "FredSecretError", "FredSecretResolver"]
