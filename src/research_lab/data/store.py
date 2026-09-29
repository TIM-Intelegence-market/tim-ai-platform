"""Local file store for verified archive files.

Files live under a directory of their own (default data/research_lab, ignored
by git). The store refuses holdout months unless the caller holds a holdout
permission, so holdout data cannot be loaded by accident before R6.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from src.research_lab.data.archive import ArchiveRef, Dataset, checked_digest
from src.research_lab.data.parse import FundingRate, Kline, parse_funding, parse_klines, read_single_csv
from src.research_lab.protocol import HOLDOUT_START_MS

Fetcher = Callable[[str], bytes]
DEFAULT_ROOT = Path("data/research_lab")
MANIFEST = "manifest.json"


class HoldoutLocked(PermissionError):
    """Raised when holdout data is requested without a holdout permission."""


_ISSUER = object()


@dataclass(frozen=True, slots=True)
class HoldoutPermission:
    """Issued only by stats.register.claim_holdout after the lock file exists.

    Carries the frozen candidate list and register size so the holdout run can
    check it evaluates exactly what was frozen. This guards against accidents,
    not against deliberate misuse of Python internals."""

    reason: str
    candidates: tuple[str, ...]
    m: int
    token: object = field(repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if self.token is not _ISSUER:
            raise PermissionError("holdout permissions are issued only by claim_holdout")


def _issue_permission(reason: str, candidates: tuple[str, ...], m: int) -> HoldoutPermission:
    return HoldoutPermission(reason, candidates, m, _ISSUER)


def http_fetch(url: str, timeout: float = 60.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed https host
        return response.read()


class ArchiveStore:
    def __init__(self, root: Path | str = DEFAULT_ROOT, fetcher: Fetcher = http_fetch) -> None:
        self.root = Path(root)
        self.fetcher = fetcher

    def _guard(self, ref: ArchiveRef, permission: HoldoutPermission | None) -> None:
        if ref.touches_holdout and permission is None:
            raise HoldoutLocked(f"{ref.filename} lies in the holdout period; loading needs the R6 permission")

    def _manifest(self) -> dict[str, dict[str, str]]:
        path = self.root / MANIFEST
        return json.loads(path.read_text()) if path.exists() else {}

    def _write_manifest(self, manifest: dict[str, dict[str, str]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    def fetch(self, ref: ArchiveRef, permission: HoldoutPermission | None = None) -> Path:
        """Download, verify against the official checksum, and store one archive."""
        self._guard(ref, permission)
        target = self.root / ref.local_path
        manifest = self._manifest()
        known = manifest.get(ref.local_path)
        if known and target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == known["sha256"]:
            return target
        checksum = self.fetcher(ref.checksum_url).decode("utf-8")
        payload = self.fetcher(ref.url)
        digest = checked_digest(ref, checksum, payload)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        manifest[ref.local_path] = {"sha256": digest, "url": ref.url}
        self._write_manifest(manifest)
        return target

    def _verified_csv(self, ref: ArchiveRef, permission: HoldoutPermission | None) -> str:
        self._guard(ref, permission)
        target = self.root / ref.local_path
        known = self._manifest().get(ref.local_path)
        if known is None or not target.exists():
            raise FileNotFoundError(f"{ref.filename} has not been fetched")
        payload = target.read_bytes()
        if hashlib.sha256(payload).hexdigest() != known["sha256"]:
            raise ValueError(f"{ref.filename} changed on disk since it was verified")
        return read_single_csv(payload)

    def load_klines(self, refs: Iterable[ArchiveRef], permission: HoldoutPermission | None = None) -> list[Kline]:
        result: list[Kline] = []
        for ref in refs:
            if ref.dataset is not Dataset.KLINES:
                raise ValueError("expected kline archives")
            result.extend(k for k in parse_klines(self._verified_csv(ref, permission)) if ref.start_ms <= k.open_time < ref.end_ms)
        if permission is None:
            result = [k for k in result if k.open_time < HOLDOUT_START_MS]
        return sorted(result, key=lambda k: k.open_time)

    def load_funding(self, refs: Iterable[ArchiveRef], permission: HoldoutPermission | None = None) -> list[FundingRate]:
        result: list[FundingRate] = []
        for ref in refs:
            if ref.dataset is not Dataset.FUNDING:
                raise ValueError("expected funding archives")
            result.extend(f for f in parse_funding(self._verified_csv(ref, permission)) if ref.start_ms <= f.time < ref.end_ms)
        if permission is None:
            result = [f for f in result if f.time < HOLDOUT_START_MS]
        return sorted(result, key=lambda f: f.time)

    def dataset_hash(self, refs: Iterable[ArchiveRef]) -> str:
        """Stable hash over the verified files of a dataset version (Band 8)."""
        manifest = self._manifest()
        entries = sorted((ref.local_path, manifest[ref.local_path]["sha256"]) for ref in refs)
        return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def months(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """Inclusive list of (year, month) from start to end."""
    year, month = start
    result = []
    while (year, month) <= end:
        result.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result
