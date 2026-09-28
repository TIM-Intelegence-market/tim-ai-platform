from __future__ import annotations

import fcntl
import gzip
import json
import os
import re
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


SENSITIVE_KEY = re.compile(
    r"(?:pass(?:word)?|secret|token|credential|authorization|cookie|api[_-]?key)", re.IGNORECASE
)
URI_PASSWORD = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s:/@]+:)([^\s@]+)(@)", re.IGNORECASE)
BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


def _redact(value: Any, *, key: str = "") -> Any:
    if SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return BEARER.sub("Bearer [REDACTED]", URI_PASSWORD.sub(r"\1[REDACTED]\3", value))
    return value


@dataclass(frozen=True, slots=True)
class RotationPolicy:
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 7
    retention_days: int = 14
    compress: bool = True

    def __post_init__(self) -> None:
        if self.max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if self.backup_count < 1:
            raise ValueError("backup_count must be positive")
        if self.retention_days < 1:
            raise ValueError("retention_days must be positive")


class LogRotator:
    """Cross-process cooperative rotation using atomic rename and fsync."""

    def __init__(
        self,
        path: Path,
        policy: RotationPolicy | None = None,
        *,
        preserve_inode: bool = False,
    ) -> None:
        self.path = path
        self.policy = policy or RotationPolicy()
        self.preserve_inode = preserve_inode
        self.lock_path = path.with_name(f".{path.name}.rotation.lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _backup(self, index: int) -> Path:
        suffix = f".{index}.gz" if self.policy.compress else f".{index}"
        return self.path.with_name(self.path.name + suffix)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _prune_expired_locked(self) -> list[str]:
        threshold = datetime.now(timezone.utc) - timedelta(days=self.policy.retention_days)
        removed: list[str] = []
        for candidate in self.path.parent.glob(f"{self.path.name}.*"):
            if candidate == self.lock_path or not re.search(r"\.\d+(?:\.gz)?$", candidate.name):
                continue
            modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=timezone.utc)
            if modified < threshold:
                candidate.unlink()
                removed.append(str(candidate))
        return removed

    def _rotate_locked(self) -> Path | None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            self._prune_expired_locked()
            return None
        oldest = self._backup(self.policy.backup_count)
        oldest.unlink(missing_ok=True)
        for index in range(self.policy.backup_count - 1, 0, -1):
            source = self._backup(index)
            if source.exists():
                os.replace(source, self._backup(index + 1))

        if self.preserve_inode:
            compressed = self._backup(1)
            temporary = compressed.with_name(f".{compressed.name}.{os.getpid()}.tmp")
            try:
                if self.policy.compress:
                    with self.path.open("rb") as source, gzip.open(temporary, "wb", compresslevel=6) as target:
                        shutil.copyfileobj(source, target)
                else:
                    with self.path.open("rb") as source, temporary.open("wb") as target:
                        shutil.copyfileobj(source, target)
                with temporary.open("rb") as handle:
                    os.fsync(handle.fileno())
                os.replace(temporary, compressed)
                with self.path.open("r+b") as active:
                    active.truncate(0)
                    active.flush()
                    os.fsync(active.fileno())
            finally:
                temporary.unlink(missing_ok=True)
        elif self.policy.compress:
            uncompressed = self.path.with_name(self.path.name + ".1")
            compressed = self._backup(1)
            temporary = compressed.with_name(f".{compressed.name}.{os.getpid()}.tmp")
            os.replace(self.path, uncompressed)
            try:
                with uncompressed.open("rb") as source, gzip.open(temporary, "wb", compresslevel=6) as target:
                    shutil.copyfileobj(source, target)
                with temporary.open("rb") as handle:
                    os.fsync(handle.fileno())
                os.replace(temporary, compressed)
                uncompressed.unlink()
            finally:
                temporary.unlink(missing_ok=True)
        else:
            compressed = self._backup(1)
            os.replace(self.path, compressed)
        self._prune_expired_locked()
        self._fsync_directory(self.path.parent)
        return compressed

    def rotate_if_needed(self, *, projected_bytes: int = 0, force: bool = False) -> dict[str, Any]:
        with self.locked():
            size = self.path.stat().st_size if self.path.exists() else 0
            should_rotate = force or (size > 0 and size + max(0, projected_bytes) > self.policy.max_bytes)
            rotated = self._rotate_locked() if should_rotate else None
            removed = self._prune_expired_locked()
        return {
            "path": str(self.path),
            "rotated": str(rotated) if rotated else None,
            "size_before": size,
            "max_bytes": self.policy.max_bytes,
            "retention_days": self.policy.retention_days,
            "backup_count": self.policy.backup_count,
            "compressed": self.policy.compress,
            "expired_removed": removed,
        }


class StructuredLog:
    """Durable JSONL writer with redaction and cooperative lossless rotation."""

    def __init__(self, path: Path, rotation: RotationPolicy | None = None) -> None:
        self.path = path
        self.rotator = LogRotator(path, rotation)
        self._rate_limit_lock = threading.Lock()
        self._last_emitted: dict[str, float] = {}
        self._suppressed: dict[str, int] = {}
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        event: str,
        severity: str = "INFO",
        *,
        rate_limit_seconds: float = 0.0,
        rate_limit_key: str | None = None,
        **fields: Any,
    ) -> bool:
        """Append an event and optionally suppress identical hot-loop messages."""
        suppressed = 0
        if rate_limit_seconds > 0:
            key = rate_limit_key or f"{severity}:{event}"
            now = time.monotonic()
            with self._rate_limit_lock:
                previous = self._last_emitted.get(key)
                if previous is not None and now - previous < rate_limit_seconds:
                    self._suppressed[key] = self._suppressed.get(key, 0) + 1
                    return False
                self._last_emitted[key] = now
                suppressed = self._suppressed.pop(key, 0)
        if suppressed:
            fields["suppressed_since_last"] = suppressed
        row = _redact(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "severity": severity,
                **fields,
            }
        )
        encoded = (json.dumps(row, sort_keys=True, default=str) + "\n").encode("utf-8")
        with self.rotator.locked():
            size = self.path.stat().st_size if self.path.exists() else 0
            if size > 0 and size + len(encoded) > self.rotator.policy.max_bytes:
                self.rotator._rotate_locked()
            descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                os.write(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return True
