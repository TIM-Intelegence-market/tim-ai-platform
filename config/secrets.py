from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import quote, urlsplit, urlunsplit


class SecretProviderError(RuntimeError):
    """Raised when a required secret cannot be obtained without unsafe fallback."""


@dataclass(frozen=True, slots=True)
class DatabaseEndpoint:
    host: str = "127.0.0.1"
    port: int = 5432
    database: str = "tim"
    user: str = "tim"

    def validate(self) -> None:
        host = self.host.strip().lower()
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise SecretProviderError("TIM database host must be loopback")
        if not 1 <= self.port <= 65535:
            raise SecretProviderError("TIM database port is invalid")
        for label, value in (("database", self.database), ("user", self.user)):
            if not value or any(character in value for character in "\x00\r\n"):
                raise SecretProviderError(f"TIM database {label} is invalid")


class SecretValue:
    """A deliberately non-printable secret wrapper."""

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        if not value or any(character in value for character in "\x00\r\n"):
            raise SecretProviderError("secret provider returned an invalid value")
        self.__value = value

    def reveal(self) -> str:
        return self.__value

    def __repr__(self) -> str:
        return "SecretValue('@REDACTED@')"

    def __str__(self) -> str:
        return "@REDACTED@"


def _safe_identifier(value: str, *, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.:/@+-]{1,160}", value):
        raise SecretProviderError(f"invalid {label}")
    return value


def _parse_pgpass_line(line: str) -> list[str]:
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line.rstrip("\n"):
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


def _require_private_regular_file(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise SecretProviderError("configured local secret file is missing") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise SecretProviderError("configured local secret path must be a regular file")
    if metadata.st_uid != os.getuid():
        raise SecretProviderError("configured local secret file has the wrong owner")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise SecretProviderError("configured local secret file must use mode 0600 or stricter")
    if metadata.st_size > 4096:
        raise SecretProviderError("configured local secret file is unexpectedly large")


class DatabaseSecretResolver:
    """Resolve the TIM database secret from one explicitly selected provider."""

    PROVIDERS = frozenset({"keychain", "pgpass", "file", "url-env"})

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = os.environ if env is None else env

    @property
    def provider(self) -> str:
        value = self.env.get("TIM_DATABASE_SECRET_PROVIDER", "keychain").strip().lower()
        if value not in self.PROVIDERS:
            raise SecretProviderError("TIM database secret provider is unsupported")
        return value

    def _keychain(self, endpoint: DatabaseEndpoint) -> SecretValue:
        service = _safe_identifier(
            self.env.get("TIM_DATABASE_KEYCHAIN_SERVICE", "com.tim.database"),
            label="Keychain service",
        )
        account = _safe_identifier(
            self.env.get("TIM_DATABASE_KEYCHAIN_ACCOUNT", endpoint.user),
            label="Keychain account",
        )
        try:
            completed = subprocess.run(
                ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SecretProviderError("macOS Keychain database secret is unavailable") from exc
        if completed.returncode != 0:
            raise SecretProviderError("macOS Keychain database secret is unavailable")
        return SecretValue(completed.stdout.rstrip("\n"))

    def _pgpass(self, endpoint: DatabaseEndpoint) -> SecretValue:
        path = Path(self.env.get("TIM_DATABASE_PGPASS_FILE", "~/.pgpass")).expanduser()
        _require_private_regular_file(path)
        requested = (endpoint.host, str(endpoint.port), endpoint.database, endpoint.user)
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            if not raw_line or raw_line.lstrip().startswith("#"):
                continue
            fields = _parse_pgpass_line(raw_line)
            if len(fields) != 5:
                continue
            if all(pattern in {"*", actual} for pattern, actual in zip(fields[:4], requested, strict=True)):
                return SecretValue(fields[4])
        raise SecretProviderError("no matching TIM entry exists in the configured pgpass file")

    def _file(self) -> SecretValue:
        default = "~/Library/Application Support/TIM/database-password"
        path = Path(self.env.get("TIM_DATABASE_SECRET_FILE", default)).expanduser()
        _require_private_regular_file(path)
        return SecretValue(path.read_text(encoding="utf-8").rstrip("\n"))

    def _url_from_test_environment(self) -> str:
        allowed = self.env.get("TIM_ALLOW_DATABASE_URL_ENV_FOR_TESTS", "false").lower() == "true"
        isolated = self.env.get("TIM_RUNTIME_ENV", "").lower() == "test"
        if not allowed or not isolated:
            raise SecretProviderError("database URL environment provider is restricted to isolated tests")
        value = self.env.get("TIM_DURABLE_TEST_DATABASE_URL", "")
        parsed = urlsplit(value)
        if parsed.scheme not in {"postgres", "postgresql"} or not parsed.username or parsed.password is None:
            raise SecretProviderError("isolated test database URL is invalid")
        try:
            port = parsed.port or 5432
        except ValueError as exc:
            raise SecretProviderError("isolated test database URL is invalid") from exc
        DatabaseEndpoint(
            host=parsed.hostname or "",
            port=port,
            database=parsed.path.lstrip("/"),
            user=parsed.username,
        ).validate()
        return value

    def database_url(self, endpoint: DatabaseEndpoint) -> str:
        endpoint.validate()
        if self.provider == "url-env":
            return self._url_from_test_environment()
        if self.provider == "keychain":
            secret = self._keychain(endpoint)
        elif self.provider == "pgpass":
            secret = self._pgpass(endpoint)
        else:
            secret = self._file()
        host = f"[{endpoint.host}]" if ":" in endpoint.host else endpoint.host
        user = quote(endpoint.user, safe="")
        password = quote(secret.reveal(), safe="")
        database = quote(endpoint.database, safe="")
        return f"postgresql://{user}:{password}@{host}:{endpoint.port}/{database}?application_name=tim_observe_runtime"

    def status(self, endpoint: DatabaseEndpoint) -> dict[str, str]:
        self.database_url(endpoint)
        return {
            "provider": self.provider,
            "endpoint": f"{endpoint.host}:{endpoint.port}/{endpoint.database}",
            "status": "AVAILABLE",
        }


def redact_database_url(value: str) -> str:
    """Return a log-safe database URL without credentials or secret query values."""

    try:
        parsed = urlsplit(value)
    except ValueError:
        return "@REDACTED_DATABASE_URL@"
    if parsed.scheme not in {"postgres", "postgresql"}:
        return "@REDACTED_DATABASE_URL@"
    host = parsed.hostname or "UNKNOWN_HOST"
    if ":" in host:
        host = f"[{host}]"
    try:
        parsed_port = parsed.port
    except ValueError:
        return "@REDACTED_DATABASE_URL@"
    port = f":{parsed_port}" if parsed_port else ""
    database = parsed.path or "/UNKNOWN_DATABASE"
    return urlunsplit((parsed.scheme, f"@REDACTED_USER@@{host}{port}", database, "", ""))
