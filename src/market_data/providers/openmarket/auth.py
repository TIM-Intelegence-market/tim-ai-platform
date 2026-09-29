"""OpenMarket API-key resolution on TIM's existing secret model.

Same rules as the database secret (config/secrets.py): exactly one explicitly
selected provider, no silent fallback, the value only ever lives inside a
non-printable ``SecretValue``. Supported providers:

- ``keychain``: macOS Keychain (service/account configurable).
- ``file``: a regular file owned by the runtime user with mode 0600 or stricter.
- ``env``: ``TIM_OPENMARKET_API_KEY`` (for hosts without a keychain).

Without ``TIM_OPENMARKET_SECRET_PROVIDER`` the provider is not configured and
every request fails closed with ``NO_SECRET``.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping

from config.secrets import SecretProviderError, SecretValue, _require_private_regular_file, _safe_identifier

from .errors import OpenMarketError, OpenMarketErrorKind

PROVIDER_ENV = "TIM_OPENMARKET_SECRET_PROVIDER"
KEY_ENV = "TIM_OPENMARKET_API_KEY"
FILE_ENV = "TIM_OPENMARKET_SECRET_FILE"
DEFAULT_SECRET_FILE = "~/Library/Application Support/TIM/openmarket-api-key"


class OpenMarketSecretResolver:
    PROVIDERS = frozenset({"keychain", "file", "env"})

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = os.environ if env is None else env

    @property
    def provider(self) -> str | None:
        value = self.env.get(PROVIDER_ENV, "").strip().lower()
        if not value:
            return None
        if value not in self.PROVIDERS:
            raise OpenMarketError(OpenMarketErrorKind.NOT_CONFIGURED, "OpenMarket secret provider is unsupported")
        return value

    def configured(self) -> bool:
        """True when a provider is selected and yields a well-formed value."""
        try:
            self.api_key()
        except OpenMarketError:
            return False
        return True

    def api_key(self) -> SecretValue:
        provider = self.provider
        if provider is None:
            raise OpenMarketError(OpenMarketErrorKind.NO_SECRET, f"{PROVIDER_ENV} is not set")
        try:
            if provider == "keychain":
                return self._keychain()
            if provider == "file":
                path = Path(self.env.get(FILE_ENV, DEFAULT_SECRET_FILE)).expanduser()
                _require_private_regular_file(path)
                return SecretValue(path.read_text(encoding="utf-8").strip())
            return SecretValue(self.env.get(KEY_ENV, "").strip())
        except SecretProviderError as exc:
            # SecretProviderError messages are fixed texts without the value.
            raise OpenMarketError(OpenMarketErrorKind.NO_SECRET, f"{provider} provider: {exc}") from None

    def _keychain(self) -> SecretValue:
        service = _safe_identifier(self.env.get("TIM_OPENMARKET_KEYCHAIN_SERVICE", "com.tim.openmarket"), label="Keychain service")
        account = _safe_identifier(self.env.get("TIM_OPENMARKET_KEYCHAIN_ACCOUNT", "tim"), label="Keychain account")
        try:
            completed = subprocess.run(
                ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
                check=False, capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise SecretProviderError("macOS Keychain OpenMarket secret is unavailable") from None
        if completed.returncode != 0:
            raise SecretProviderError("macOS Keychain OpenMarket secret is unavailable")
        return SecretValue(completed.stdout.strip())


def masked(secret: SecretValue) -> str:
    """``****last4``; only for operator confirmation, never needed for logs."""
    value = secret.reveal()
    return "****" + value[-4:] if len(value) >= 12 else "****"
