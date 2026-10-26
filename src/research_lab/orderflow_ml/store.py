"""Own day store of minute bars for S8, separate from the S2 store.

Raw daily aggTrades archives are fetched (or served from a local directory of
already downloaded archives), verified against Binance's checksum sidecar and
reduced to ``bars/<symbol>-<day>.csv``. The raw archive is not kept unless asked.

This store never reads ``data/research_lab/aggtrades/px/`` (the S2 price files
stay unread, S2 section 8) and never touches the runtime database. Days from
2025-01-01 on are the holdout and are refused before any byte is fetched.
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
from src.research_lab.orderflow_ml.bars import BAR_HEADER, BAR_VERSION, MINUTE_MS, MINUTES_PER_DAY, MinuteBar, reduce_trades, ticks_from_rows
from src.research_lab.protocol import HOLDOUT_START_MS
from src.v2_readiness.backfill import BinanceArchiveRef, parse_official_checksum, verify_archive

Fetcher = Callable[[str], bytes]
DEFAULT_ROOT = Path("data/research_lab/orderflow_ml")
MANIFEST = "bars_manifest.json"
SYMBOL = "BTCUSDT"
HOLDOUT_DAY = date(2025, 1, 1)


def day_start_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


def days_between(first: date, last: date) -> list[date]:
    if last < first:
        raise ValueError("last day before first day")
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guard(day: date) -> None:
    if day >= HOLDOUT_DAY or day_start_ms(day) >= HOLDOUT_START_MS:
        raise HoldoutLocked(f"{day} lies in the holdout; S8 reads no holdout day")


class MinuteBarStore:
    def __init__(self, root: Path | str = DEFAULT_ROOT, fetcher: Fetcher = http_fetch, symbol: str = SYMBOL) -> None:
        self.root = Path(root)
        self.fetcher = fetcher
        self.symbol = symbol

    def bar_path(self, day: date) -> Path:
        return self.root / "bars" / f"{self.symbol}-{day.isoformat()}.csv"

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
        guard(day)
        ref = BinanceArchiveRef(day, self.symbol)
        digest = parse_official_checksum(self.fetcher(ref.checksum_url).decode("utf-8"), expected_filename=ref.filename)
        payload = self.fetcher(ref.url)
        if not verify_archive(payload, digest):
            raise ValueError(f"checksum mismatch for {ref.filename}")
        bars, quality = reduce_trades(ticks_from_rows(read_rows(payload)), day_start_ms(day))
        path = self.bar_path(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(BAR_HEADER)
            writer.writerows(bar.as_row() for bar in bars)
        if keep_raw:
            raw = self.root / "raw" / ref.filename
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(payload)
        return {"archive_sha256": digest, "url": ref.url, "bar_version": BAR_VERSION, "bars_sha256": sha256_file(path),
                "quality": quality.as_dict(), "raw_kept": keep_raw, "time_basis": "exchange_event_time"}

    def record(self, day: date, entry: dict) -> dict:
        manifest = self.manifest()
        manifest[day.isoformat()] = entry
        self._write_manifest(manifest)
        return entry

    def cached(self, day: date) -> dict | None:
        entry = self.manifest().get(day.isoformat())
        path = self.bar_path(day)
        if entry and entry.get("bar_version") == BAR_VERSION and path.exists() and sha256_file(path) == entry["bars_sha256"]:
            return entry
        return None

    def fetch(self, day: date, *, keep_raw: bool = False) -> dict:
        guard(day)
        return self.cached(day) or self.record(day, self.prepare(day, keep_raw=keep_raw))

    # -- read -----------------------------------------------------------------------------------
    def load(self, day: date) -> list[MinuteBar]:
        """The 1440 bars of a day, verified against the manifest."""
        guard(day)
        entry = self.manifest().get(day.isoformat())
        path = self.bar_path(day)
        if entry is None or not path.exists():
            raise FileNotFoundError(f"{day} has not been fetched")
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

    def dataset_hash(self, days: Iterable[date]) -> str:
        manifest = self.manifest()
        entries = sorted((d.isoformat(), manifest[d.isoformat()]["archive_sha256"], manifest[d.isoformat()]["bars_sha256"]) for d in days)
        return hashlib.sha256(json.dumps(entries).encode()).hexdigest()
