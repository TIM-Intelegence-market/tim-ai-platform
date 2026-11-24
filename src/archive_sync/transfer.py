"""Resumable, hash-verified transfer of batch files (pattern of the offsite upload script).

Each file goes to ``<name>.part``, is checked by sha256 on the receiving side and only then
renamed. Files whose remote sha256 already matches are skipped, so a dropped connection is
resumed by simply running the transfer again. Data files go before their manifest: the
importer only sees a batch once its manifest has arrived.
"""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from src.archive_sync.common import MIN_FREE_RATIO, ArchiveSyncError, sha256_file

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
_SAFE_REMOTE_DIR = re.compile(r"^[A-Za-z0-9_./-]{1,300}$")
_SAFE_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,250}$")
_SAFE_KEY = re.compile(r"^[A-Za-z0-9_./~-]{1,500}$")


def _checked_name(name: str) -> str:
    if not _SAFE_NAME.match(name) or ".." in name:
        raise ArchiveSyncError(f"unsafe file name: {name!r}")
    return name


class Target(Protocol):
    def sha256(self, name: str) -> str | None: ...

    def upload(self, local: Path, name: str) -> None: ...

    def disk(self) -> tuple[int, int]: ...


@dataclass
class LocalDirTarget:
    """Target directory on the same machine (also used by the tests)."""

    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def sha256(self, name: str) -> str | None:
        path = self.root / _checked_name(name)
        return sha256_file(path) if path.is_file() else None

    def upload(self, local: Path, name: str) -> None:
        part = self.root / (_checked_name(name) + ".part")
        shutil.copyfile(local, part)
        if sha256_file(part) != sha256_file(local):
            part.unlink(missing_ok=True)
            raise ArchiveSyncError(f"{name}: sha256 changed in transit")
        part.replace(self.root / name)

    def disk(self) -> tuple[int, int]:
        usage = shutil.disk_usage(self.root)
        return int(usage.total), int(usage.free)


Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def _default_runner(argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=3600, check=False)


@dataclass
class SshTarget:
    """Remote directory over ssh/scp. Host, port and key come from the caller, never from code."""

    host: str
    remote_dir: str
    key: str | None = None
    port: int | None = None
    runner: Runner = field(default=_default_runner)

    def __post_init__(self) -> None:
        if not _SAFE_REMOTE_DIR.match(self.remote_dir) or ".." in self.remote_dir.split("/"):
            raise ArchiveSyncError("unsafe remote directory")
        if not _SAFE_HOST.match(self.host or ""):
            raise ArchiveSyncError("unsafe host")
        if self.key is not None and (not _SAFE_KEY.match(self.key) or self.key.startswith("-")):
            raise ArchiveSyncError("unsafe key path")

    def _opts(self, port_flag: str) -> list[str]:
        opts = ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes"]
        if self.key:
            opts += ["-i", self.key]
        if self.port:
            opts += [port_flag, str(int(self.port))]
        return opts

    def _ssh(self, command: str) -> "subprocess.CompletedProcess[str]":
        return self.runner(["ssh", *self._opts("-p"), "--", self.host, command])

    def _path(self, name: str) -> str:
        return f"{self.remote_dir.rstrip('/')}/{_checked_name(name)}"

    def sha256(self, name: str) -> str | None:
        quoted = shlex.quote(self._path(name))
        done = self._ssh(f"if [ -f {quoted} ]; then sha256sum -- {quoted}; fi")
        if done.returncode != 0:
            raise ArchiveSyncError(f"remote sha256 failed for {name}")
        text = (done.stdout or "").strip()
        return text.split()[0] if text else None

    def upload(self, local: Path, name: str) -> None:
        part = self._path(name) + ".part"
        made = self._ssh(f"mkdir -p -- {shlex.quote(self.remote_dir)}")
        if made.returncode != 0:
            raise ArchiveSyncError("remote directory could not be created")
        copied = self.runner(["scp", *self._opts("-P"), "-q", "--", str(local), f"{self.host}:{part}"])
        if copied.returncode != 0:
            raise ArchiveSyncError(f"copy of {name} failed")
        expected = sha256_file(local)
        quoted = shlex.quote(part)
        check = self._ssh(f"sha256sum -- {quoted}")
        if check.returncode != 0 or (check.stdout or "").split()[:1] != [expected]:
            self._ssh(f"rm -f -- {quoted}")
            raise ArchiveSyncError(f"{name}: sha256 changed in transit")
        moved = self._ssh(f"mv -f -- {quoted} {shlex.quote(self._path(name))}")
        if moved.returncode != 0:
            raise ArchiveSyncError(f"rename of {name} failed")

    def disk(self) -> tuple[int, int]:
        done = self._ssh(f"mkdir -p -- {shlex.quote(self.remote_dir)} && df -Pk -- {shlex.quote(self.remote_dir)}")
        lines = (done.stdout or "").strip().splitlines()
        if done.returncode != 0 or len(lines) < 2:
            raise ArchiveSyncError("remote free space unknown; refusing to send")
        fields = lines[-1].split()
        return int(fields[1]) * 1024, int(fields[3]) * 1024


def transfer_directory(
    local_dir: str | Path,
    target: Target,
    *,
    symbol: str,
    attempts: int = 3,
    pause_seconds: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    min_free_ratio: float = MIN_FREE_RATIO,
) -> dict[str, Any]:
    local = Path(local_dir)
    files: list[Path] = []
    for manifest in sorted(local.glob(f"{symbol}-*.manifest.json")):
        data = manifest.with_name(manifest.name.replace(".manifest.json", ".csv.gz"))
        if not data.is_file():
            raise ArchiveSyncError(f"{manifest.name}: data file missing locally")
        files += [data, manifest]
    pending = []
    skipped = 0
    for path in files:
        if target.sha256(path.name) == sha256_file(path):
            skipped += 1
        else:
            pending.append(path)
    needed = sum(path.stat().st_size for path in pending)
    total, free = target.disk()
    if total <= 0 or (free - needed) / total < min_free_ratio:
        raise ArchiveSyncError("free-space gate on the receiving side failed; nothing sent")
    sent = []
    for path in pending:
        for attempt in range(1, attempts + 1):
            try:
                target.upload(path, path.name)
                break
            except (ArchiveSyncError, OSError, subprocess.SubprocessError):
                if attempt == attempts:
                    raise
                sleep(pause_seconds * attempt)
        sent.append(path.name)
    return {"mode": "TRANSFER", "symbol": symbol, "sent": sent, "skipped_already_present": skipped}
