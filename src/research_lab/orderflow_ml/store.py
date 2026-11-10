"""Own day store of minute bars for S8, separate from the S2 store.

Raw daily aggTrades archives are fetched (or served from a local directory of
already downloaded archives), verified against Binance's checksum sidecar and
reduced to ``bars/<symbol>-<day>.csv``. The raw archive is not kept unless asked.

This store never reads ``data/research_lab/aggtrades/px/`` (the S2 price files
stay unread, S2 section 8) and never touches the runtime database. Days from
2025-01-01 on are the holdout and are refused before any byte is fetched.

Exception (Uzi 10.11.2026, "die heutigen daten von diesem jahr ebenfalls nuzt bis 2020"): a store opened with
``release=OFX_RELEASE`` may fetch and read days from 2025-01-01 up to yesterday (UTC) for the OFX final test.
Every other caller (S8, OF2, export, sequence study) keeps the lock, and no store reads today or a future day.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from src.research_lab.data.aggtrades import read_rows
from src.research_lab.data.store import HoldoutLocked, http_fetch
from src.research_lab.orderflow_ml.bars import (BAR_HEADER, BAR_VERSION, MINUTE_MS, MINUTES_PER_DAY, PROFILE_HEADER, DayProfile, MinuteBar,
                                                reduce_trades_with_profile, ticks_from_rows)
from src.research_lab.protocol import HOLDOUT_START_MS
from src.v2_readiness.backfill import BinanceArchiveRef, parse_official_checksum, verify_archive

Fetcher = Callable[[str], bytes]
DEFAULT_ROOT = Path("data/research_lab/orderflow_ml")
MANIFEST = "bars_manifest.json"
SYMBOL = "BTCUSDT"
HOLDOUT_DAY = date(2025, 1, 1)
OFX_RELEASE = "OFX-Uzi-2026-11-10"  # release of holdout days for the OFX final test
# Paper journal of the orderflow engine (Uzi 10.11.2026, "go"): its own store may read days from PAPER_FIRST_DAY on
# (lead days for the levels, then the days after the journal start). Nothing before that day.
PAPER_RELEASE = "OF-Papier-Uzi-2026-11-10"
PAPER_FIRST_DAY = date(2026, 10, 1)
RELEASES = (OFX_RELEASE, PAPER_RELEASE)


def day_start_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


def days_between(first: date, last: date) -> list[date]:
    if last < first:
        raise ValueError("last day before first day")
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guard(day: date, release: str | None = None, *, today: date | None = None) -> None:
    if day >= HOLDOUT_DAY or day_start_ms(day) >= HOLDOUT_START_MS:
        if release not in RELEASES:
            raise HoldoutLocked(f"{day} lies in the holdout; S8 reads no holdout day")
        if release == PAPER_RELEASE and day < PAPER_FIRST_DAY:
            raise HoldoutLocked(f"{day} lies before the paper journal's window")
        if day >= (today or datetime.now(timezone.utc).date()):
            raise HoldoutLocked(f"{day} is not complete yet; only days up to yesterday (UTC) are released")


class MinuteBarStore:
    def __init__(self, root: Path | str = DEFAULT_ROOT, fetcher: Fetcher = http_fetch, symbol: str = SYMBOL,
                 release: str | None = None) -> None:
        if release is not None and release not in RELEASES:
            raise ValueError("unknown holdout release")
        self.release = release
        self.root = Path(root)
        self.fetcher = fetcher
        self.symbol = symbol

    def bar_path(self, day: date) -> Path:
        return self.root / "bars" / f"{self.symbol}-{day.isoformat()}.csv"

    def profile_path(self, day: date) -> Path:
        return self.root / "profile" / f"{self.symbol}-{day.isoformat()}.csv"

    def manifest(self) -> dict[str, dict]:
        path = self.root / MANIFEST
        return json.loads(path.read_text()) if path.exists() else {}

    def _write_manifest(self, manifest: dict[str, dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / (MANIFEST + ".tmp")
        tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        tmp.replace(self.root / MANIFEST)

    def present_days(self) -> list[date]:
        return sorted(date.fromisoformat(key) for key in self.manifest())

    # -- ingest ---------------------------------------------------------------------------------
    def prepare(self, day: date, *, keep_raw: bool = False) -> dict:
        """Fetch, verify and reduce one day; write its bar file; return the manifest entry (not recorded)."""
        guard(day, self.release)
        ref = BinanceArchiveRef(day, self.symbol)
        digest = parse_official_checksum(self.fetcher(ref.checksum_url).decode("utf-8"), expected_filename=ref.filename)
        payload = self.fetcher(ref.url)
        if not verify_archive(payload, digest):
            raise ValueError(f"checksum mismatch for {ref.filename}")
        bars, quality, profile = reduce_trades_with_profile(ticks_from_rows(read_rows(payload)), day_start_ms(day))
        path = self.bar_path(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(BAR_HEADER)
            writer.writerows(bar.as_row() for bar in bars)
        ppath = self.profile_path(day)
        ppath.parent.mkdir(parents=True, exist_ok=True)
        with ppath.open("w", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(PROFILE_HEADER)
            writer.writerows(profile.as_rows())
        if keep_raw:
            raw = self.root / "raw" / ref.filename
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(payload)
        return {"archive_sha256": digest, "url": ref.url, "bar_version": BAR_VERSION, "bars_sha256": sha256_file(path),
                "profile_sha256": sha256_file(ppath), "profile_width_e8": profile.width_e8,
                "quality": quality.as_dict(), "raw_kept": keep_raw, "time_basis": "exchange_event_time"}

    def record(self, day: date, entry: dict) -> dict:
        manifest = self.manifest()
        manifest[day.isoformat()] = entry
        self._write_manifest(manifest)
        return entry

    def cached(self, day: date) -> dict | None:
        entry = self.manifest().get(day.isoformat())
        path = self.bar_path(day)
        ppath = self.profile_path(day)
        if entry and entry.get("bar_version") == BAR_VERSION and path.exists() and sha256_file(path) == entry["bars_sha256"] \
                and ppath.exists() and sha256_file(ppath) == entry["profile_sha256"]:
            return entry
        return None

    def fetch(self, day: date, *, keep_raw: bool = False) -> dict:
        guard(day, self.release)
        return self.cached(day) or self.record(day, self.prepare(day, keep_raw=keep_raw))

    # -- read -----------------------------------------------------------------------------------
    def load(self, day: date) -> list[MinuteBar]:
        """The 1440 bars of a day, verified against the manifest."""
        guard(day, self.release)
        entry = self.manifest().get(day.isoformat())
        path = self.bar_path(day)
        if entry is None or not path.exists():
            raise FileNotFoundError(f"{day} has not been fetched")
        if entry.get("bar_version") != BAR_VERSION:
            raise ValueError(f"{day}: incompatible bar version")
        quality = entry.get("quality")
        if not isinstance(quality, dict) or any(
            type(quality.get(key)) is not int or quality[key] < 0
            for key in ("id_gaps", "time_regressions")
        ):
            raise ValueError(f"{day}: missing or invalid source quality evidence")
        if quality["id_gaps"] or quality["time_regressions"]:
            raise ValueError(f"{day}: source quality blocks export (id gaps or time regressions)")
        if sha256_file(path) != entry["bars_sha256"]:
            raise ValueError(f"{day}: bar file changed on disk since it was verified")
        with path.open(newline="") as handle:
            reader = csv.reader(handle)
            if next(reader) != BAR_HEADER:
                raise ValueError(f"{day}: unexpected bar layout")
            bars = [MinuteBar.from_row(row) for row in reader]
        start = day_start_ms(day)
        if len(bars) != MINUTES_PER_DAY or any(bar.window_start_ms != start + i * MINUTE_MS for i, bar in enumerate(bars)):
            raise ValueError(f"{day}: bar file is not one full day")
        return bars

    def load_profile(self, day: date) -> DayProfile:
        """Volume per minute and price bin of a day, verified against the manifest."""
        guard(day, self.release)
        entry = self.manifest().get(day.isoformat())
        path = self.profile_path(day)
        if entry is None or not path.exists() or entry.get("bar_version") != BAR_VERSION:
            raise FileNotFoundError(f"{day} has no profile of bar version {BAR_VERSION}")
        if sha256_file(path) != entry["profile_sha256"]:
            raise ValueError(f"{day}: profile file changed on disk since it was verified")
        with path.open(newline="") as handle:
            reader = csv.reader(handle)
            if next(reader) != PROFILE_HEADER:
                raise ValueError(f"{day}: unexpected profile layout")
            entries = tuple(tuple(int(v) for v in row) for row in reader)
        if list(entries) != sorted(entries) or any(not 0 <= e[0] < MINUTES_PER_DAY for e in entries):
            raise ValueError(f"{day}: profile rows out of order or outside the day")
        return DayProfile(day_start_ms(day), int(entry["profile_width_e8"]), entries)  # type: ignore[arg-type]

    def dataset_hash(self, days: Iterable[date]) -> str:
        manifest = self.manifest()
        # Quality and bar semantics determine whether these bytes can be used.
        # Bind their provenance too, rather than hashing only the two files.
        entries = sorted((d.isoformat(), manifest[d.isoformat()]) for d in days)
        return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
