"""INFRA-09 draft: file archive for verified batch files with a hard byte budget (no database).

Interim store for the time before new disks exist. It keeps the original batch files
(``*.csv.gz`` + manifest) unchanged, so batch_id, content_sha256 and file_sha256 stay the
provenance. Rules:

* Every batch is checked like the importer checks it (manifest, file sha256, size, batch_id,
  gzip, content sha256, exact ID set) before anything is written.
* Before each write the budget is checked: ``used + incoming <= limit_bytes``. If it would be
  exceeded the ingest stops (``BUDGET_STOP``), writes nothing for that batch and tries no further
  batch. The file system free-space gate (15 %) applies as well.
* Nothing is ever deleted or overwritten. A different file under an existing name is a CONFLICT
  and halts the run. There is no delete function in this module; the only unlink removes a
  temporary file this process itself has just created with ``O_EXCL``.
* Every write is confined to the store (and, at init, the volume marker): directories are opened
  component by component with ``O_NOFOLLOW`` and every file is created relative to that pinned
  directory with ``O_CREAT | O_EXCL | O_NOFOLLOW``. A symbolic link anywhere on the way, a
  pre-planted temporary or target name, or a ledger path leaving ``batches/`` is refused.
* ``LEDGER.jsonl`` is append-only and records every stored file with its sha256.
* ``migrate_store`` copies everything to a new root, verifies it there, and leaves the source
  untouched.

Not activated anywhere; nothing here runs on a schedule.
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from src.archive_sync.common import (
    COLUMNS,
    FORMAT,
    KINDS,
    MIN_FREE_RATIO,
    ArchiveSyncError,
    disk_gate,
    hole_size,
    normalise_holes,
)

STORE_FORMAT = "tim-cold-store/1"
DEFAULT_LIMIT_BYTES = 100 * 1024**3
STORE_FILE = "STORE.json"
LEDGER_FILE = "LEDGER.jsonl"
LOCK_FILE = ".lock"
MIGRATION_FILE = "MIGRATION.json"
VOLUME_MARKER = ".tim-archive-volume"
PARENT_MIN_FREE_RATIO = 0.15
TMP_PREFIX = ".tmp-"
MountCheck = Callable[[str], bool]

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}")
_LEDGER_PATH = re.compile(r"batches/[A-Za-z0-9]+/[A-Za-z0-9][A-Za-z0-9._-]{0,200}")
_CHUNK = 1 << 20
_SYMBOL = re.compile(r"[A-Za-z0-9]{1,40}")
_VOLUME_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_HALT_ERRNOS = {errno.ENOSPC, errno.EROFS, errno.EDQUOT, errno.EIO}


# ---------------------------------------------------------------------- safe file system access
def _safe_name(name: str) -> str:
    """A plain file name: no separator, no '..', not hidden, not one of our temporary names."""
    if not isinstance(name, str) or not _NAME.fullmatch(name) or ".." in name:
        raise ArchiveSyncError(f"unsafe file name {name!r}")
    return name


def _safe_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
        raise ArchiveSyncError(f"unsafe symbol {symbol!r}")
    return symbol


def _io_errors(function):
    """Every file system error leaves as ArchiveSyncError (no raw traceback in the CLI).

    A full, read-only or failing file system halts the run; what is already stored stays valid.
    """
    import functools

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ArchiveSyncError:
            raise
        except OSError as error:
            name = errno.errorcode.get(error.errno or 0, "OSError")
            if error.errno in _HALT_ERRNOS:
                raise ArchiveSyncError(f"file system error {name}: halted, nothing half-written is kept as stored") from None
            raise ArchiveSyncError(f"file system error {name}: {error.strerror or error}") from None
        except (ValueError, KeyError, TypeError) as error:
            raise ArchiveSyncError(f"store metadata unreadable ({type(error).__name__}); refusing to continue") from None
    return wrapper


def _open_dir(path: str | Path, *, create: bool = False) -> int:
    """Open a directory without following a symbolic link in any component (fail closed)."""
    absolute = os.path.abspath(path)
    fd = os.open("/", os.O_RDONLY | _DIRECTORY | _CLOEXEC)
    try:
        for part in Path(absolute).parts[1:]:
            try:
                info = os.stat(part, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                if not create:
                    raise ArchiveSyncError(f"{absolute}: directory {part!r} does not exist") from None
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, 0o755, dir_fd=fd)
                info = os.stat(part, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise ArchiveSyncError(f"symbolic link in store path refused: {absolute} ({part})")
            if not stat.S_ISDIR(info.st_mode):
                raise ArchiveSyncError(f"{absolute}: {part!r} is not a directory")
            try:
                nxt = os.open(part, os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC, dir_fd=fd)
            except OSError as error:  # swapped for a link between stat and open
                raise ArchiveSyncError(f"symbolic link in store path refused: {absolute} ({error.strerror})") from None
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextlib.contextmanager
def _dir(path: str | Path, *, create: bool = False) -> Iterator[int]:
    fd = _open_dir(path, create=create)
    try:
        yield fd
    finally:
        os.close(fd)


def _no_symlinks(path: str | Path) -> None:
    """Refuse a path if it or any of its parent directories is a symbolic link."""
    with _dir(path):
        pass


def _open_regular(name: str, dir_fd: int, flags: int = os.O_RDONLY) -> int:
    """Open an existing regular file inside ``dir_fd`` without following a link."""
    try:
        # O_NONBLOCK: a planted FIFO must not hang the run; regular files ignore the flag.
        fd = os.open(name, flags | os.O_NONBLOCK | _NOFOLLOW | _CLOEXEC, dir_fd=dir_fd)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ArchiveSyncError(f"symbolic link refused: {name}") from None
        raise
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ArchiveSyncError(f"{name} is not a regular file")
    return fd


def _read_bytes(name: str, dir_fd: int) -> bytes:
    with os.fdopen(_open_regular(name, dir_fd), "rb") as handle:
        return handle.read()


def _lstat(name: str, dir_fd: int) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _sha_of(name: str, dir_fd: int) -> str:
    """sha256 of a stored regular file; a link or other special file never matches anything."""
    info = _lstat(name, dir_fd)
    if info is None or not stat.S_ISREG(info.st_mode):
        return "not-a-regular-file"
    digest = hashlib.sha256()
    with os.fdopen(_open_regular(name, dir_fd), "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _discard_own_temp(dir_fd: int, name: str) -> None:
    """Remove a temporary file this process created itself with O_EXCL; nothing else is ever removed."""
    if not name.startswith(TMP_PREFIX):
        raise ArchiveSyncError("refusing to remove anything but our own temporary file")
    with contextlib.suppress(FileNotFoundError):
        os.unlink(name, dir_fd=dir_fd)


def _fsync_fd(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError as error:  # some file systems cannot fsync a directory; real I/O errors still count
        if error.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EBADF):
            raise


def _write_new(dir_fd: int, name: str, chunks: Iterable[bytes], expected_sha256: str, *, mode: int = 0o444,
               max_bytes: int | None = None, internal: bool = False) -> int:
    """Create ``name`` in ``dir_fd`` with exactly this content. Never replaces or follows anything.

    The content goes to a fresh ``.tmp-<random>`` file (``O_EXCL``), is fsynced, read back and
    compared with ``expected_sha256``, set read-only and then hard-linked to ``name``; ``link``
    fails if ``name`` exists in any form. Returns the size in bytes.
    """
    if not (internal and name == VOLUME_MARKER):
        _safe_name(name)
    temp = f"{TMP_PREFIX}{uuid.uuid4().hex}"
    fd = os.open(temp, os.O_RDWR | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC, 0o600, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, "r+b") as handle:
            written = 0
            for chunk in chunks:
                written += len(chunk)
                if max_bytes is not None and written > max_bytes:  # a growing source never fills the disk
                    raise ArchiveSyncError(f"{name}: source is larger than declared ({max_bytes} bytes); refused")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
            handle.seek(0)
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(_CHUNK), b""):
                digest.update(chunk)
            size = handle.tell()
            os.fchmod(handle.fileno(), mode)
        if digest.hexdigest() != expected_sha256:
            raise ArchiveSyncError(f"{name}: sha256 changed while copying")
        try:
            os.link(temp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
        except FileExistsError:
            raise ArchiveSyncError(f"{name} already exists; refusing to overwrite") from None
    finally:
        _discard_own_temp(dir_fd, temp)
    _fsync_fd(dir_fd)
    if _sha_of(name, dir_fd) != expected_sha256:  # what is published under the name is what was checked
        raise ArchiveSyncError(f"{name}: published file differs from the checked copy; review by hand")
    return size


def _copy_verified(source: Path, target: Path, expected_sha256: str, *, data: bytes | None = None,
                   size: int | None = None) -> None:
    """Store ``source`` (or the exact ``data`` read from it) as the new file ``target``.

    ``size`` caps a streamed copy: more bytes than declared are refused before they reach the disk.
    """
    with _dir(target.parent) as target_fd:
        if data is not None:
            _write_new(target_fd, target.name, [data], expected_sha256)
            return
        with _dir(source.parent) as source_fd, os.fdopen(_open_regular(source.name, source_fd), "rb") as handle:
            _write_new(target_fd, target.name, iter(lambda: handle.read(_CHUNK), b""), expected_sha256,
                       max_bytes=size)


def _tree(root: Path) -> Iterator[tuple[str, os.stat_result]]:
    """Every entry below ``root`` (relative path, lstat), never following a link."""
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in [*dirs, *files]:
            path = os.path.join(folder, name)
            yield os.path.relpath(path, root), os.lstat(path)


# ---------------------------------------------------------------------- batch checks
def _parse_manifest(raw: bytes, name: str) -> dict[str, Any]:
    """The importer's manifest checks, on bytes read once (the same bytes are stored later)."""
    from src.archive_sync import importer

    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArchiveSyncError(f"{name}: unreadable manifest ({type(error).__name__})") from None
    if not isinstance(manifest, dict):
        raise ArchiveSyncError(f"{name}: manifest is not an object")
    for key, kind in importer._REQUIRED.items():
        value = manifest.get(key)
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            raise ArchiveSyncError(f"{name}: manifest field {key} missing or wrong type")
    if manifest.get("format") != FORMAT or manifest.get("kind") not in KINDS:
        raise ArchiveSyncError(f"{name}: unknown manifest format or kind")
    if list(manifest.get("columns") or []) != list(COLUMNS):
        raise ArchiveSyncError(f"{name}: column list differs from this importer")
    return manifest


def _check_batch(manifest_path: Path, manifest: dict[str, Any] | None = None,
                 symbol: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """Same checks as the importer before staging, plus the exact ID set from the file itself."""
    from src.archive_sync import importer

    if manifest is None:
        try:
            manifest = importer.load_manifest(manifest_path)
        except ArchiveSyncError as error:
            return None, str(error)
    if symbol is not None and manifest["symbol"] != symbol:
        return manifest, "manifest symbol differs from the requested symbol"
    try:
        _safe_name(manifest["file"])
    except ArchiveSyncError:
        return manifest, "data file name is not a plain batch file name"
    if symbol is not None and not manifest["file"].startswith(f"{symbol}-"):
        return manifest, "data file name does not belong to this symbol"
    if manifest_path.name != manifest["file"][: -len(".csv.gz")] + ".manifest.json":
        return manifest, "data file name does not match the manifest name"
    payload, problem = importer._verify_file(manifest_path, manifest)
    if problem or payload is None:
        return manifest, problem or "unreadable data file"
    if hashlib.sha256(payload).hexdigest() != manifest["content_sha256"]:
        return manifest, "content sha256 differs from manifest"
    lo, hi = int(manifest["lo"]), int(manifest["hi"])
    holes = normalise_holes(manifest["holes"], lo, hi)
    expected = hi - lo + 1 - hole_size(holes)
    try:
        lines = payload.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError:
        return manifest, "data file is not valid UTF-8"
    if len(lines) != expected or int(manifest["row_count"]) != expected:
        return manifest, f"row count {len(lines)} differs from span minus holes {expected}"
    previous = lo - 1
    hole_iter = iter(holes)
    hole = next(hole_iter, None)
    for line in lines:
        fields = line.split(",")
        if len(fields) < 2 or fields[0] != manifest["symbol"]:
            return manifest, "row with wrong symbol or shape"
        text = fields[1]
        if not (text.isascii() and text.isdigit()) or (len(text) > 1 and text[0] == "0"):
            return manifest, "row with non-canonical trade id"
        trade_id = int(text)
        if trade_id <= previous or trade_id > hi:
            return manifest, "trade ids not strictly increasing inside the batch range"
        while hole is not None and trade_id > hole[1]:
            hole = next(hole_iter, None)
        if hole is not None and hole[0] <= trade_id <= hole[1]:
            return manifest, f"trade id {trade_id} lies in a declared hole"
        previous = trade_id
    return manifest, None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ColdStore:
    """Append-only store under ``root``. ``limit_bytes`` is the hard budget for stored files.

    A store created with ``volume_mount`` is bound to that mounted file system: before every write
    the mount must be present, carry the volume marker written at init, and contain the store.
    Otherwise the write is refused (fail closed), so an absent mount never fills the parent disk.
    """

    @_io_errors
    def __init__(self, root: str | Path, *, usage: Callable[[str], Any] = shutil.disk_usage,
                 is_mount: MountCheck = os.path.ismount) -> None:
        self.root = Path(os.path.abspath(root))
        self._usage = usage
        self._is_mount = is_mount
        with _dir(self.root) as root_fd:
            if _lstat(STORE_FILE, root_fd) is None:
                raise ArchiveSyncError(f"{self.root} is not an initialised cold store (volume not mounted?)")
            self.info = json.loads(_read_bytes(STORE_FILE, root_fd).decode("utf-8"))
        if self.info.get("format") != STORE_FORMAT:
            raise ArchiveSyncError("unknown cold store format")
        self.limit_bytes = int(self.info["limit_bytes"])
        self.volume: dict[str, Any] | None = self.info.get("volume")
        self.check_volume()

    def check_volume(self) -> dict[str, Any]:
        """Fail-closed identity check of the bound volume; called before every write."""
        if self.volume is None:
            return {"bound": False}
        mount = Path(self.volume["mount"])
        if not self._is_mount(str(mount)):
            raise ArchiveSyncError(f"archive volume {mount} is not mounted; nothing written")
        try:
            with _dir(mount) as mount_fd:
                found = _read_bytes(VOLUME_MARKER, mount_fd).decode("utf-8").strip()
        except (OSError, ArchiveSyncError, UnicodeDecodeError):
            found = ""
        if not _VOLUME_ID.fullmatch(str(self.volume.get("volume_id", ""))) or found != self.volume["volume_id"]:
            raise ArchiveSyncError(f"wrong volume mounted at {mount}; nothing written")
        try:
            self.root.relative_to(mount)
        except ValueError:
            raise ArchiveSyncError("store root lies outside its volume") from None
        try:
            same_device = os.stat(self.root, follow_symlinks=False).st_dev == os.stat(mount, follow_symlinks=False).st_dev
        except OSError:
            same_device = False
        if not same_device:
            raise ArchiveSyncError("store root is not on the bound volume; nothing written")
        image = self.volume.get("image")
        if image:
            try:
                info = os.stat(image)
            except OSError:
                raise ArchiveSyncError("volume image file not reachable; nothing written") from None
            if info.st_blocks * 512 < info.st_size:
                raise ArchiveSyncError("volume image is no longer fully allocated (sparse); nothing written")
        parent = self.volume.get("parent")
        if parent:
            gate = disk_gate(parent, 0, min_free_ratio=PARENT_MIN_FREE_RATIO, usage=self._usage)
            if not gate.passed:
                raise ArchiveSyncError(f"parent file system {parent} below {PARENT_MIN_FREE_RATIO:.0%} free; nothing written")
        return {"bound": True, "mount": str(mount), "volume_id": self.volume["volume_id"]}

    @contextlib.contextmanager
    def _locked(self):
        """Exclusive writer lock; a second writer fails at once instead of interleaving."""
        with _dir(self.root) as root_fd:
            try:
                fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT | _NOFOLLOW | _CLOEXEC, 0o600, dir_fd=root_fd)
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise ArchiveSyncError("symbolic link refused: store lock; nothing written") from None
                raise
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ArchiveSyncError("store lock is not a regular file; nothing written")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ArchiveSyncError("another writer holds the store lock; nothing written") from None
            yield
        finally:
            os.close(fd)

    @classmethod
    @_io_errors
    def init(cls, root: str | Path, *, limit_bytes: int = DEFAULT_LIMIT_BYTES, volume_mount: str | Path | None = None,
             parent: str | Path | None = None, image: str | Path | None = None,
             is_mount: MountCheck = os.path.ismount, **kwargs: Any) -> "ColdStore":
        root = Path(os.path.abspath(root))
        if limit_bytes <= 0:
            raise ArchiveSyncError("limit must be positive")
        if os.path.lexists(root):
            with _dir(root) as root_fd:
                if _lstat(STORE_FILE, root_fd) is not None:
                    existing = json.loads(_read_bytes(STORE_FILE, root_fd).decode("utf-8"))
                    if int(existing.get("limit_bytes", -1)) != int(limit_bytes):
                        raise ArchiveSyncError("store exists with another limit; change it explicitly, not by init")
                    bound = existing.get("volume") or {}
                    wanted = str(os.path.abspath(volume_mount)) if volume_mount is not None else None
                    if bound.get("mount") != wanted:
                        raise ArchiveSyncError("store exists with another volume binding; refusing")
                    return cls(root, is_mount=is_mount, **kwargs)
                if os.listdir(root_fd):  # checked before anything is written, the marker included
                    raise ArchiveSyncError(f"{root} is not empty; a cold store needs its own directory")
        volume = None
        if volume_mount is not None:
            mount = Path(os.path.abspath(volume_mount))
            if not is_mount(str(mount)):
                raise ArchiveSyncError(f"{mount} is not a mounted file system; refusing to create a store")
            try:
                root.relative_to(mount)
            except ValueError:
                raise ArchiveSyncError("store root must lie inside the volume") from None
            if root == mount:
                raise ArchiveSyncError("store root must be a sub-directory of the volume")
            if str(mount) == os.path.abspath(os.sep):
                raise ArchiveSyncError("the root file system cannot be an archive volume")
            usage = kwargs.get("usage", shutil.disk_usage)
            if int(limit_bytes) > usage(str(mount)).total * (1 - MIN_FREE_RATIO):
                raise ArchiveSyncError("limit exceeds what the volume can hold with its 15% reserve")
            with _dir(mount) as mount_fd:
                if _lstat(VOLUME_MARKER, mount_fd) is not None:
                    volume_id = _read_bytes(VOLUME_MARKER, mount_fd).decode("utf-8").strip()
                    if not _VOLUME_ID.fullmatch(volume_id):
                        raise ArchiveSyncError("volume marker is empty or malformed; check the volume by hand")
                else:
                    volume_id = str(uuid.uuid4())
                    # Written whole and published by link: never empty, never replaces or follows a marker.
                    text = (volume_id + "\n").encode()
                    _write_new(mount_fd, VOLUME_MARKER, [text], hashlib.sha256(text).hexdigest(), internal=True)
            volume = {"mount": str(mount), "volume_id": volume_id,
                      "parent": str(os.path.abspath(parent)) if parent else None,
                      "image": str(os.path.abspath(image)) if image else None}
        with _dir(root.parent) as parent_fd:  # only the store directory itself is created
            with contextlib.suppress(FileExistsError):
                os.mkdir(root.name, 0o755, dir_fd=parent_fd)
        with _dir(root) as root_fd:
            if os.listdir(root_fd):
                raise ArchiveSyncError(f"{root} is not empty; a cold store needs its own directory")
            os.mkdir("batches", 0o755, dir_fd=root_fd)
            payload = {"format": STORE_FORMAT, "limit_bytes": int(limit_bytes), "created_at": _now(), "volume": volume}
            text = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
            _write_new(root_fd, STORE_FILE, [text], hashlib.sha256(text).hexdigest())
            for name, mode in ((LEDGER_FILE, 0o644), (LOCK_FILE, 0o600)):
                os.close(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC, mode, dir_fd=root_fd))
            _fsync_fd(root_fd)
        return cls(root, is_mount=is_mount, **kwargs)

    # ------------------------------------------------------------------ ledger
    def ledger(self) -> list[dict[str, Any]]:
        """Ledger entries. A torn last line (crash during append, no newline) is ignored; the next
        ingest re-records that file. Any other unreadable line, or a path outside ``batches/``,
        stops everything."""
        with _dir(self.root) as root_fd:
            text = _read_bytes(LEDGER_FILE, root_fd).decode("utf-8")
        lines = text.split("\n")
        lines.pop()  # text after the last newline: empty or a torn entry
        entries = []
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                entry = None
            if not isinstance(entry, dict):
                following = lines[number] if number < len(lines) else ""
                if '"event":"torn_tail_discarded"' in following:
                    continue  # the torn rest of a crashed append, closed and logged by the next append
                raise ArchiveSyncError(f"ledger line {number} is unreadable; refusing to continue")
            if "event" in entry:
                continue
            if not isinstance(entry.get("path"), str) or not _LEDGER_PATH.fullmatch(entry["path"]) \
                    or ".." in entry["path"]:
                raise ArchiveSyncError(f"ledger line {number} names a path outside batches/; refusing to continue")
            entries.append(entry)
        return entries

    def _append(self, entry: dict[str, Any]) -> None:
        self.check_volume()
        with _dir(self.root) as root_fd:
            fd = _open_regular(LEDGER_FILE, root_fd, os.O_RDWR | os.O_APPEND)
        with os.fdopen(fd, "r+b") as handle:
            if os.fstat(handle.fileno()).st_nlink != 1:
                raise ArchiveSyncError("ledger has extra hard links; refusing to write")
            data = handle.read()
            torn_tail = b""
            lines = b""
            if data and not data.endswith(b"\n"):
                # A torn tail is a half-written entry of a write that never completed; its file is
                # re-recorded by this ingest. Nothing is cut: the line is closed and the event logged.
                torn_tail = data[data.rfind(b"\n") + 1:]
                lines += b"\n"
            if torn_tail:
                lines += json.dumps({"event": "torn_tail_discarded", "at": _now(), "bytes": len(torn_tail),
                                     "sha256": hashlib.sha256(torn_tail).hexdigest()},
                                    sort_keys=True, separators=(",", ":")).encode() + b"\n"
            lines += json.dumps(entry, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            handle.write(lines)
            handle.flush()
            os.fsync(handle.fileno())

    @_io_errors
    def used_bytes(self) -> int:
        """The larger of what the ledger records and what is really on disk below batches/
        (left-over temporary files included)."""
        recorded = sum(int(e["bytes"]) for e in self.ledger())
        on_disk = sum(info.st_size for _, info in _tree(self.root / "batches") if stat.S_ISREG(info.st_mode))
        return max(recorded, on_disk)

    def _symbol_dir(self, symbol: str) -> Path:
        _safe_symbol(symbol)
        with _dir(self.root / "batches") as batches_fd:
            try:
                os.mkdir(symbol, 0o755, dir_fd=batches_fd)
                _fsync_fd(batches_fd)
            except FileExistsError:
                pass
        path = self.root / "batches" / symbol
        _no_symlinks(path)
        return path

    # ------------------------------------------------------------------ ingest
    @_io_errors
    def ingest_directory(self, inbox: str | Path, *, symbol: str, min_free_ratio: float = MIN_FREE_RATIO) -> dict[str, Any]:
        _safe_symbol(symbol)
        with self._locked():
            return self._ingest(Path(inbox), symbol=symbol, min_free_ratio=min_free_ratio)

    def _ingest(self, inbox: Path, *, symbol: str, min_free_ratio: float) -> dict[str, Any]:
        _safe_symbol(symbol)
        self.check_volume()
        results: list[dict[str, Any]] = []
        halted: str | None = None
        for manifest_path in sorted(inbox.glob(f"{symbol}-*.manifest.json")):
            name = manifest_path.name
            if halted:
                results.append({"manifest": name, "status": "NOT_TRIED"})
                continue
            manifest, raw, problem = self._read_batch(inbox, manifest_path, symbol)
            if problem or manifest is None or raw is None:
                results.append({"manifest": name, "status": "FILE_INVALID", "reason": problem})
                halted = "FILE_INVALID"
                continue
            data_name = manifest["file"]
            target_dir = self._symbol_dir(symbol)
            # (stored name, expected sha256, size, bytes to write or None for a streamed copy)
            files = [(data_name, manifest["file_sha256"], int(manifest["file_bytes"]), None),
                     (name, hashlib.sha256(raw).hexdigest(), len(raw), raw)]
            with _dir(target_dir) as target_fd:
                present = {n: _lstat(n, target_fd) is not None for n, *_ in files}
                conflict = any(present[n] and _sha_of(n, target_fd) != sha for n, sha, *_ in files)
            if conflict:
                results.append({"manifest": name, "status": "CONFLICT",
                                "reason": "a different file with this name is already stored"})
                halted = "CONFLICT"
                continue
            entries = self.ledger()
            recorded = {e["path"] for e in entries}
            rel = {n: f"batches/{symbol}/{n}" for n, *_ in files}
            elsewhere = {e["path"] for e in entries if e.get("batch_id") == manifest["batch_id"]} - set(rel.values())
            if elsewhere:
                results.append({"manifest": name, "status": "CONFLICT",
                                "reason": "this batch is already stored under another name"})
                halted = "CONFLICT"
                continue
            missing = [n for n, *_ in files if not present[n]]
            unrecorded = [n for n, *_ in files if present[n] and rel[n] not in recorded]
            if not missing and not unrecorded:
                results.append({"manifest": name, "status": "ALREADY", "batch_id": manifest["batch_id"]})
                continue
            incoming = sum(size for n, _, size, _ in files if n in missing)
            used = self.used_bytes()
            if used + incoming > self.limit_bytes:
                results.append({"manifest": name, "status": "BUDGET_STOP", "used_bytes": used,
                                "incoming_bytes": incoming, "limit_bytes": self.limit_bytes})
                halted = "BUDGET_STOP"
                continue
            gate = disk_gate(self.root, incoming, min_free_ratio=min_free_ratio, usage=self._usage)
            if not gate.passed:
                results.append({"manifest": name, "status": "DISK_STOP", "disk": gate.as_dict()})
                halted = "DISK_STOP"
                continue
            for stored_name, sha, size, data in files:  # data first, manifest last
                if stored_name not in missing and stored_name not in unrecorded:
                    continue
                if stored_name in missing:
                    self.check_volume()
                    _copy_verified(inbox / stored_name, target_dir / stored_name, sha, data=data, size=size)
                self._append({
                    "stored_at": _now(), "symbol": symbol, "path": rel[stored_name],
                    "bytes": size, "sha256": sha, "batch_id": manifest["batch_id"],
                    "content_sha256": manifest["content_sha256"], "kind": manifest["kind"],
                    "lo": int(manifest["lo"]), "hi": int(manifest["hi"]),
                    "role": "data" if stored_name == data_name else "manifest",
                })
            status = "STORED" if len(missing) == len(files) else "RESUMED"
            results.append({"manifest": name, "status": status, "batch_id": manifest["batch_id"], "bytes": incoming})
        summary: dict[str, int] = {}
        for result in results:
            summary[result["status"]] = summary.get(result["status"], 0) + 1
        return {"mode": "COLD_INGEST", "symbol": symbol, "summary": summary, "halted": halted,
                "used_bytes": self.used_bytes(), "limit_bytes": self.limit_bytes, "results": results}

    @staticmethod
    def _read_batch(inbox: Path, manifest_path: Path, symbol: str) -> tuple[dict[str, Any] | None, bytes | None, str | None]:
        """Read the manifest once (no links), check the batch, and return the exact bytes to store."""
        name = manifest_path.name
        try:
            _safe_name(name)
            with _dir(inbox) as inbox_fd:
                info = _lstat(name, inbox_fd)
                if info is not None and stat.S_ISLNK(info.st_mode):
                    return None, None, "symbolic link refused"
                raw = _read_bytes(name, inbox_fd)
                manifest = _parse_manifest(raw, name)
                data = manifest.get("file")
                if isinstance(data, str) and _NAME.fullmatch(data):
                    info = _lstat(data, inbox_fd)
                    if info is not None and stat.S_ISLNK(info.st_mode):
                        return manifest, raw, "symbolic link refused"
        except ArchiveSyncError as error:
            return None, None, str(error)
        except OSError as error:  # vanished or unreadable between listing and reading
            return None, None, f"inbox file unreadable ({errno.errorcode.get(error.errno or 0, 'OSError')})"
        try:
            manifest, problem = _check_batch(manifest_path, manifest, symbol)
        except OSError as error:
            return manifest, raw, f"data file unreadable ({errno.errorcode.get(error.errno or 0, 'OSError')})"
        return manifest, raw, problem

    @staticmethod
    def _stored_sha(path: Path) -> str:
        try:
            with _dir(path.parent) as folder_fd:
                return _sha_of(path.name, folder_fd)
        except ArchiveSyncError:
            return "unreachable"

    # ------------------------------------------------------------------ verify
    @_io_errors
    def verify(self) -> dict[str, Any]:
        """Re-hash every ledger entry and look for anything below batches/ the ledger does not know.

        Takes the writer lock, so a running ingest is never reported as a half-written file."""
        with self._locked():
            return self._verify()

    def _verify(self) -> dict[str, Any]:
        entries = self.ledger()
        problems: list[str] = []
        known = set()
        for entry in entries:
            rel = entry["path"]
            known.add(rel)
            path = self.root / rel
            try:
                info = os.lstat(path)
            except FileNotFoundError:
                problems.append(f"missing: {rel}")
                continue
            if stat.S_ISLNK(info.st_mode):
                problems.append(f"symbolic link: {rel}")
            elif not stat.S_ISREG(info.st_mode):
                problems.append(f"not a regular file: {rel}")
            elif info.st_size != int(entry["bytes"]) or self._stored_sha(path) != entry["sha256"]:
                problems.append(f"changed: {rel}")
            elif info.st_mode & 0o222:
                problems.append(f"writable (should be read-only): {rel}")
            elif info.st_nlink != 1:
                problems.append(f"extra hard link: {rel}")
        for rel, info in _tree(self.root / "batches"):
            full = f"batches/{rel}"
            if stat.S_ISDIR(info.st_mode):
                continue
            if stat.S_ISLNK(info.st_mode):
                if full not in known:
                    problems.append(f"symbolic link: {full}")
            elif os.path.basename(rel).startswith(TMP_PREFIX):
                problems.append(f"left-over temporary file (interrupted write, review by hand): {full}")
            elif full not in known:
                problems.append(f"not in ledger: {full}")
        volume = self.check_volume()
        return {"mode": "COLD_VERIFY", "status": "FAIL" if problems else "OK", "files": len(entries), "volume": volume,
                "used_bytes": self.used_bytes(), "limit_bytes": self.limit_bytes, "problems": problems}


@_io_errors
def migrate_store(source: str | Path, target: str | Path, *, volume_mount: str | Path | None = None,
                  parent: str | Path | None = None, is_mount: MountCheck = os.path.ismount,
                  source_is_mount: MountCheck = os.path.ismount) -> dict[str, Any]:
    """Copy a cold store to a new root (e.g. new disks), verify it there, keep the source as it is."""
    old = ColdStore(source, is_mount=source_is_mount)
    with old._locked():
        return _migrate(old, Path(target), volume_mount=volume_mount, parent=parent, is_mount=is_mount)


def _migrate(old: "ColdStore", target: Path, *, volume_mount: str | Path | None, parent: str | Path | None,
             is_mount: MountCheck) -> dict[str, Any]:
    before = old._verify()
    if before["status"] != "OK":
        raise ArchiveSyncError("source store does not verify; fix that before migrating")
    target = Path(os.path.abspath(target))
    for inner, outer in ((target, old.root), (old.root, target)):
        try:
            inner.relative_to(outer)
        except ValueError:
            continue
        raise ArchiveSyncError("migration target and source must not contain each other")
    if os.path.lexists(target):
        with _dir(target) as target_fd:
            if os.listdir(target_fd):
                raise ArchiveSyncError(f"{target} is not empty; migrate only into an empty directory")
    new = ColdStore.init(target, limit_bytes=old.limit_bytes, volume_mount=volume_mount, parent=parent, is_mount=is_mount)
    copied = 0
    for entry in old.ledger():
        symbol = entry["path"].split("/")[1]
        new._symbol_dir(symbol)
        new.check_volume()
        gate = disk_gate(new.root, int(entry["bytes"]), min_free_ratio=MIN_FREE_RATIO, usage=new._usage)
        if not gate.passed:
            raise ArchiveSyncError(f"migration target below {MIN_FREE_RATIO:.0%} free; stopped, source untouched")
        _copy_verified(old.root / entry["path"], new.root / entry["path"], entry["sha256"], size=int(entry["bytes"]))
        new._append({**entry, "migrated_at": _now(), "migrated_from": str(old.root)})
        copied += 1
    after = new.verify()
    receipt = {"mode": "COLD_MIGRATE", "status": after["status"], "copied_files": copied,
               "source_files": before["files"], "target_files": after["files"],
               "same_bytes": before["used_bytes"] == after["used_bytes"], "finished_at": _now()}
    text = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    with _dir(new.root) as root_fd:
        _write_new(root_fd, MIGRATION_FILE, [text], hashlib.sha256(text).hexdigest())
    return receipt
