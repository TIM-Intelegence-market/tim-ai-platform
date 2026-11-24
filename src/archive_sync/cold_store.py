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
  and halts the run. There is no delete function in this module.
* ``LEDGER.jsonl`` is append-only and records every stored file with its sha256.
* ``migrate_store`` copies everything to a new root, verifies it there, and leaves the source
  untouched.

Not activated anywhere; nothing here runs on a schedule.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.archive_sync.common import (
    MIN_FREE_RATIO,
    ArchiveSyncError,
    disk_gate,
    hole_size,
    normalise_holes,
    sha256_file,
)

STORE_FORMAT = "tim-cold-store/1"
DEFAULT_LIMIT_BYTES = 100 * 1024**3
STORE_FILE = "STORE.json"
LEDGER_FILE = "LEDGER.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _copy_verified(source: Path, target: Path, expected_sha256: str) -> None:
    """Copy to ``target.part``, fsync, compare sha256, then rename. Never replaces a file."""
    if target.exists():
        raise ArchiveSyncError(f"{target.name} already exists; refusing to overwrite")
    part = target.with_name(target.name + ".part")
    with source.open("rb") as src, part.open("wb") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)
        dst.flush()
        os.fsync(dst.fileno())
    if sha256_file(part) != expected_sha256:
        part.unlink(missing_ok=True)
        raise ArchiveSyncError(f"{target.name}: sha256 changed while copying")
    if target.exists():
        part.unlink(missing_ok=True)
        raise ArchiveSyncError(f"{target.name} appeared while copying; refusing to overwrite")
    os.link(part, target)  # fails if target exists: no silent overwrite even under a race
    part.unlink()
    _fsync_dir(target.parent)


def _check_batch(manifest_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Same checks as the importer before staging, plus the exact ID set from the file itself."""
    from src.archive_sync import importer

    try:
        manifest = importer.load_manifest(manifest_path)
    except ArchiveSyncError as error:
        return None, str(error)
    payload, problem = importer._verify_file(manifest_path, manifest)
    if problem or payload is None:
        return manifest, problem or "unreadable data file"
    if hashlib.sha256(payload).hexdigest() != manifest["content_sha256"]:
        return manifest, "content sha256 differs from manifest"
    lo, hi = int(manifest["lo"]), int(manifest["hi"])
    holes = normalise_holes(manifest["holes"], lo, hi)
    expected = hi - lo + 1 - hole_size(holes)
    lines = payload.decode("utf-8", errors="strict").splitlines()
    if len(lines) != expected or int(manifest["row_count"]) != expected:
        return manifest, f"row count {len(lines)} differs from span minus holes {expected}"
    previous = lo - 1
    hole_iter = iter(holes)
    hole = next(hole_iter, None)
    for line in lines:
        fields = line.split(",")
        if len(fields) < 2 or fields[0] != manifest["symbol"]:
            return manifest, "row with wrong symbol or shape"
        try:
            trade_id = int(fields[1])
        except ValueError:
            return manifest, "row with non-numeric trade id"
        if trade_id <= previous or trade_id > hi:
            return manifest, "trade ids not strictly increasing inside the batch range"
        while hole is not None and trade_id > hole[1]:
            hole = next(hole_iter, None)
        if hole is not None and hole[0] <= trade_id <= hole[1]:
            return manifest, f"trade id {trade_id} lies in a declared hole"
        previous = trade_id
    return manifest, None


class ColdStore:
    """Append-only store under ``root``. ``limit_bytes`` is the hard budget for stored files."""

    def __init__(self, root: str | Path, *, usage: Callable[[str], Any] = shutil.disk_usage) -> None:
        self.root = Path(root)
        self._usage = usage
        info = self.root / STORE_FILE
        if not info.is_file():
            raise ArchiveSyncError(f"{self.root} is not an initialised cold store")
        self.info = json.loads(info.read_text(encoding="utf-8"))
        if self.info.get("format") != STORE_FORMAT:
            raise ArchiveSyncError("unknown cold store format")
        self.limit_bytes = int(self.info["limit_bytes"])

    @classmethod
    def init(cls, root: str | Path, *, limit_bytes: int = DEFAULT_LIMIT_BYTES, **kwargs: Any) -> "ColdStore":
        root = Path(root)
        if limit_bytes <= 0:
            raise ArchiveSyncError("limit must be positive")
        info = root / STORE_FILE
        if info.exists():
            existing = json.loads(info.read_text(encoding="utf-8"))
            if int(existing.get("limit_bytes", -1)) != int(limit_bytes):
                raise ArchiveSyncError("store exists with another limit; change it explicitly, not by init")
            return cls(root, **kwargs)
        root.mkdir(parents=True, exist_ok=True)
        if any(p.name not in (STORE_FILE,) for p in root.iterdir()):
            raise ArchiveSyncError(f"{root} is not empty; a cold store needs its own directory")
        (root / "batches").mkdir()
        payload = {"format": STORE_FORMAT, "limit_bytes": int(limit_bytes), "created_at": _now()}
        tmp = root / (STORE_FILE + ".part")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(info)
        (root / LEDGER_FILE).touch()
        _fsync_dir(root)
        return cls(root, **kwargs)

    # ------------------------------------------------------------------ ledger
    def ledger(self) -> list[dict[str, Any]]:
        lines = (self.root / LEDGER_FILE).read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def _append(self, entry: dict[str, Any]) -> None:
        with (self.root / LEDGER_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def used_bytes(self) -> int:
        """The larger of what the ledger records and what is really on disk below batches/."""
        recorded = sum(int(e["bytes"]) for e in self.ledger())
        on_disk = sum(p.stat().st_size for p in (self.root / "batches").rglob("*") if p.is_file())
        return max(recorded, on_disk)

    def _dir(self, symbol: str) -> Path:
        if not symbol.isalnum():
            raise ArchiveSyncError(f"unsafe symbol {symbol!r}")
        path = self.root / "batches" / symbol
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------ ingest
    def ingest_directory(self, inbox: str | Path, *, symbol: str, min_free_ratio: float = MIN_FREE_RATIO) -> dict[str, Any]:
        inbox = Path(inbox)
        results: list[dict[str, Any]] = []
        halted: str | None = None
        for manifest_path in sorted(inbox.glob(f"{symbol}-*.manifest.json")):
            name = manifest_path.name
            if halted:
                results.append({"manifest": name, "status": "NOT_TRIED"})
                continue
            manifest, problem = _check_batch(manifest_path)
            if problem or manifest is None:
                results.append({"manifest": name, "status": "FILE_INVALID", "reason": problem})
                halted = "FILE_INVALID"
                continue
            data_path = manifest_path.parent / manifest["file"]
            target_dir = self._dir(symbol)
            files = [(data_path, target_dir / data_path.name), (manifest_path, target_dir / name)]
            shas = {src: sha256_file(src) for src, _ in files}
            if any(dst.exists() and sha256_file(dst) != shas[src] for src, dst in files):
                results.append({"manifest": name, "status": "CONFLICT",
                                "reason": "a different file with this name is already stored"})
                halted = "CONFLICT"
                continue
            missing = [(src, dst) for src, dst in files if not dst.exists()]
            recorded = {e["path"] for e in self.ledger()}
            unrecorded = [(src, dst) for src, dst in files
                          if dst.exists() and str(dst.relative_to(self.root)) not in recorded]
            if not missing and not unrecorded:
                results.append({"manifest": name, "status": "ALREADY", "batch_id": manifest["batch_id"]})
                continue
            incoming = sum(src.stat().st_size for src, _ in missing)
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
            for src, dst in files:  # data first, manifest last
                if dst.exists() and (src, dst) not in unrecorded:
                    continue
                if not dst.exists():
                    _copy_verified(src, dst, shas[src])
                self._append({
                    "stored_at": _now(), "symbol": symbol, "path": str(dst.relative_to(self.root)),
                    "bytes": dst.stat().st_size, "sha256": shas[src], "batch_id": manifest["batch_id"],
                    "content_sha256": manifest["content_sha256"], "kind": manifest["kind"],
                    "lo": int(manifest["lo"]), "hi": int(manifest["hi"]),
                    "role": "data" if src == data_path else "manifest",
                })
            status = "STORED" if len(missing) == len(files) else "RESUMED"
            results.append({"manifest": name, "status": status, "batch_id": manifest["batch_id"], "bytes": incoming})
        summary: dict[str, int] = {}
        for result in results:
            summary[result["status"]] = summary.get(result["status"], 0) + 1
        return {"mode": "COLD_INGEST", "symbol": symbol, "summary": summary, "halted": halted,
                "used_bytes": self.used_bytes(), "limit_bytes": self.limit_bytes, "results": results}

    # ------------------------------------------------------------------ verify
    def verify(self) -> dict[str, Any]:
        """Re-hash every ledger entry and look for files the ledger does not know."""
        entries = self.ledger()
        problems: list[str] = []
        known = set()
        for entry in entries:
            path = self.root / entry["path"]
            known.add(path)
            if not path.is_file():
                problems.append(f"missing: {entry['path']}")
            elif path.stat().st_size != int(entry["bytes"]) or sha256_file(path) != entry["sha256"]:
                problems.append(f"changed: {entry['path']}")
        unknown = [str(p.relative_to(self.root)) for p in (self.root / "batches").rglob("*")
                   if p.is_file() and p not in known]
        problems += [f"not in ledger: {name}" for name in unknown]
        return {"mode": "COLD_VERIFY", "status": "FAIL" if problems else "OK", "files": len(entries),
                "used_bytes": self.used_bytes(), "limit_bytes": self.limit_bytes, "problems": problems}


def migrate_store(source: str | Path, target: str | Path) -> dict[str, Any]:
    """Copy a cold store to a new root (e.g. new disks), verify it there, keep the source as it is."""
    old = ColdStore(source)
    before = old.verify()
    if before["status"] != "OK":
        raise ArchiveSyncError("source store does not verify; fix that before migrating")
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        raise ArchiveSyncError(f"{target} is not empty; migrate only into an empty directory")
    new = ColdStore.init(target, limit_bytes=old.limit_bytes)
    copied = 0
    for entry in old.ledger():
        src = old.root / entry["path"]
        dst = new.root / entry["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        _copy_verified(src, dst, entry["sha256"])
        new._append({**entry, "migrated_at": _now(), "migrated_from": str(old.root)})
        copied += 1
    after = new.verify()
    receipt = {"mode": "COLD_MIGRATE", "status": after["status"], "copied_files": copied,
               "source_files": before["files"], "target_files": after["files"],
               "same_bytes": before["used_bytes"] == after["used_bytes"], "finished_at": _now()}
    (new.root / "MIGRATION.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt
