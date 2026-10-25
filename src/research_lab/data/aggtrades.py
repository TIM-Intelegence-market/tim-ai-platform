"""Daily Binance spot aggTrades archives for study S2, reduced to per-minute aggregates.

A BTCUSDT aggTrades day is 100–300 MB zipped and the study needs five years
of them, so the raw archives are not the dataset the lab keeps. Each day is
verified against Binance's checksum sidecar, reduced to two small files, and
the raw archive may then be deleted:

- ``agg/<day>.csv``: the seven rule fields per minute (``MinuteAggregate``),
  the only input of the count run.
- ``px/<day>.csv``: first, last, high and low trade price per minute, kept for
  the later outcome run after the study is released. The count run never
  opens this directory.

``manifest.json`` records the archive SHA-256 from the sidecar together with the
SHA-256 of both reduced files, so a later run can prove it used the same data.
Days from 2025-01-01 on are the holdout and are refused outright.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

from src.research_lab.data.store import HoldoutLocked, http_fetch
from src.research_lab.protocol import HOLDOUT_START_MS
from src.research_lab.studies.s2_orderflow import MINUTE_MS, MINUTES_PER_DAY, SYMBOL, MinuteAggregate, aggregate_rows, archive_ms
from src.v2_readiness.backfill import BinanceArchiveRef, parse_official_checksum, verify_archive

Fetcher = Callable[[str], bytes]
DEFAULT_ROOT = Path("data/research_lab/aggtrades")
MANIFEST = "manifest.json"
AGG_HEADER = ["window_start_ms", "trade_count", "buy_count", "sell_count", "buy_sats", "sell_sats", "largest_sats"]
PX_HEADER = ["window_start_ms", "first_price", "last_price", "high_price", "low_price", "first_agg_trade_id", "last_agg_trade_id"]
HOLDOUT_DAY = date(2025, 1, 1)


@dataclass(frozen=True, slots=True)
class DirectoryFetcher:
    """Serves archive and checksum files from a local directory by file name (offline runs, tests).

    Picklable, so it works in worker processes under both fork and spawn.
    """

    root: Path

    def __call__(self, url: str) -> bytes:
        return (Path(self.root) / url.rsplit("/", 1)[1]).read_bytes()


def prepare_day(store: "AggTradeDayStore", day: date, keep_raw: bool, verify: bool) -> tuple[date, dict]:
    """Worker entry for parallel fetching; importable from every process."""
    return day, store.prepare(day, keep_raw=keep_raw, verify=verify)


def day_start_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


def days_between(first: date, last: date) -> list[date]:
    """Inclusive list of days."""
    if last < first:
        raise ValueError("last day before first day")
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


@dataclass(frozen=True, slots=True)
class MinutePrices:
    window_start_ms: int
    first_price: str
    last_price: str
    high_price: str
    low_price: str
    first_agg_trade_id: int
    last_agg_trade_id: int


def read_rows(archive: bytes) -> Iterator[list[str]]:
    """Stream the rows of the single CSV inside a Binance archive, skipping a header row."""
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        names = [name for name in bundle.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("archive must contain exactly one CSV file")
        with bundle.open(names[0]) as handle:
            reader = csv.reader(io.TextIOWrapper(handle, encoding="utf-8", newline=""))
            for row in reader:
                if not row:
                    continue
                if not row[0].strip().lstrip("-").isdigit():
                    continue  # header row (spot archives carry one since 2025)
                yield row


def reduce_prices(rows: Iterable[Sequence[str]], start_ms: int) -> list[MinutePrices | None]:
    """Per-minute first/last/high/low price strings; None for minutes without trades."""
    out: list[MinutePrices | None] = [None] * MINUTES_PER_DAY
    for row in rows:
        minute = (archive_ms(row[5]) - start_ms) // MINUTE_MS
        if not 0 <= minute < MINUTES_PER_DAY:
            raise ValueError("trade outside the archive day")
        price = row[1].strip()
        trade_id = int(row[0])
        current = out[minute]
        if current is None:
            out[minute] = MinutePrices(start_ms + minute * MINUTE_MS, price, price, price, price, trade_id, trade_id)
            continue
        if trade_id <= current.last_agg_trade_id:
            raise ValueError("aggTrades must be in ascending id order")
        out[minute] = MinutePrices(current.window_start_ms, current.first_price, price,
                                   max(current.high_price, price, key=_as_decimal), min(current.low_price, price, key=_as_decimal),
                                   current.first_agg_trade_id, trade_id)
    return out


def _as_decimal(text: str) -> Decimal:
    return Decimal(text)


def reduce_day(archive: bytes, day: date) -> tuple[list[MinuteAggregate], list[MinutePrices | None], int]:
    """Verified archive bytes -> (aggregates, prices, row count), pure Python reference. Two passes keep memory flat."""
    start = day_start_ms(day)
    rows = 0

    def counted() -> Iterator[list[str]]:
        nonlocal rows
        for row in read_rows(archive):
            rows += 1
            yield row

    aggregates = aggregate_rows(counted(), start)
    prices = reduce_prices(read_rows(archive), start)
    return aggregates, prices, rows


def fast_available() -> bool:
    try:
        import numpy  # noqa: F401
        import pandas  # noqa: F401
    except ImportError:
        return False
    return True


def reduce_day_fast(archive: bytes, day: date) -> tuple[list[MinuteAggregate], list[MinutePrices | None], int]:
    """Same result as ``reduce_day`` with pandas/numpy, about a hundred times faster on a real day.

    Quantities are parsed as float64 and rounded to 1e-8 integers; for values
    with at most eight decimals below 4.5e7 BTC that rounding is exact, so the
    aggregates match the Decimal reference bit for bit (checked in the tests and
    by ``fetch(..., verify=True)``). Prices stay strings, picked from the row that
    holds the extreme, so no price is ever reformatted.
    """
    import numpy as np
    import pandas as pd

    start = day_start_ms(day)
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        names = [name for name in bundle.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("archive must contain exactly one CSV file")
        with bundle.open(names[0]) as handle:
            frame = pd.read_csv(handle, header=None, usecols=[0, 1, 2, 5, 6], names=["id", "price", "qty", "time", "maker"],
                                dtype={"id": str, "price": str, "qty": str, "time": str, "maker": str}, skip_blank_lines=True)
    if len(frame) and not frame["id"].iloc[0].strip().lstrip("-").isdigit():
        frame = frame.iloc[1:]
    rows = len(frame)
    if rows == 0:
        empty = [MinuteAggregate(start + i * MINUTE_MS, 0, 0, 0, 0, 0, 0) for i in range(MINUTES_PER_DAY)]
        return empty, [None] * MINUTES_PER_DAY, 0
    ids = frame["id"].astype(np.int64).to_numpy()
    if np.any(np.diff(ids) <= 0):
        raise ValueError("aggTrades must be in ascending id order")
    stamps = frame["time"].astype(np.int64).to_numpy()
    stamps = np.where(stamps >= 10**14, stamps // 1000, stamps)
    minute = (stamps - start) // MINUTE_MS
    if minute.min() < 0 or minute.max() >= MINUTES_PER_DAY:
        raise ValueError("trade outside the archive day")
    qty = frame["qty"].astype(np.float64).to_numpy()
    sats = np.rint(qty * 1e8).astype(np.int64)
    if np.any(sats <= 0) or np.any(np.abs(qty * 1e8 - sats) > 1e-3):
        raise ValueError("quantity is zero or has more than eight decimals")
    maker = frame["maker"].str.strip().str.lower().map({"true": True, "1": True, "false": False, "0": False})
    if maker.isna().any():
        raise ValueError("unknown is_buyer_maker flag")
    maker = maker.to_numpy(dtype=bool)
    buy = ~maker
    trade_count = np.bincount(minute, minlength=MINUTES_PER_DAY)
    buy_count = np.bincount(minute[buy], minlength=MINUTES_PER_DAY)
    buy_sats = np.rint(np.bincount(minute[buy], weights=sats[buy], minlength=MINUTES_PER_DAY)).astype(np.int64)
    sell_sats = np.rint(np.bincount(minute[maker], weights=sats[maker], minlength=MINUTES_PER_DAY)).astype(np.int64)
    largest = np.zeros(MINUTES_PER_DAY, dtype=np.int64)
    np.maximum.at(largest, minute, sats)
    aggregates = [MinuteAggregate(start + i * MINUTE_MS, int(trade_count[i]), int(buy_count[i]), int(trade_count[i] - buy_count[i]),
                                  int(buy_sats[i]), int(sell_sats[i]), int(largest[i])) for i in range(MINUTES_PER_DAY)]
    price_text = frame["price"].str.strip().to_numpy()
    price_num = frame["price"].astype(np.float64).to_numpy()
    order = np.lexsort((price_num, minute))  # by minute, then price: group first = low, group last = high
    sorted_minutes = minute[order]
    first_of_group = np.r_[True, sorted_minutes[1:] != sorted_minutes[:-1]]
    last_of_group = np.r_[sorted_minutes[1:] != sorted_minutes[:-1], True]
    low_idx = order[first_of_group]
    high_idx = order[last_of_group]
    present = sorted_minutes[first_of_group]
    first_idx = np.r_[True, minute[1:] != minute[:-1]]  # ids ascend, so row order is time order within a minute
    last_idx = np.r_[minute[1:] != minute[:-1], True]
    first_rows = np.flatnonzero(first_idx)
    last_rows = np.flatnonzero(last_idx)
    prices: list[MinutePrices | None] = [None] * MINUTES_PER_DAY
    for m, lo, hi, fr, lr in zip(present.tolist(), low_idx.tolist(), high_idx.tolist(), first_rows.tolist(), last_rows.tolist(), strict=True):
        prices[m] = MinutePrices(start + m * MINUTE_MS, str(price_text[fr]), str(price_text[lr]), str(price_text[hi]), str(price_text[lo]), int(ids[fr]), int(ids[lr]))
    return aggregates, prices, rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AggTradeDayStore:
    def __init__(self, root: Path | str = DEFAULT_ROOT, fetcher: Fetcher = http_fetch, symbol: str = SYMBOL) -> None:
        self.root = Path(root)
        self.fetcher = fetcher
        self.symbol = symbol

    # -- layout -------------------------------------------------------------------------------
    def raw_path(self, day: date) -> Path:
        return self.root / "raw" / BinanceArchiveRef(day, self.symbol).filename

    def agg_path(self, day: date) -> Path:
        return self.root / "agg" / f"{self.symbol}-{day.isoformat()}.csv"

    def px_path(self, day: date) -> Path:
        return self.root / "px" / f"{self.symbol}-{day.isoformat()}.csv"

    def manifest(self) -> dict[str, dict]:
        path = self.root / MANIFEST
        return json.loads(path.read_text()) if path.exists() else {}

    def _write_manifest(self, manifest: dict[str, dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def guard(day: date) -> None:
        if day >= HOLDOUT_DAY or day_start_ms(day) >= HOLDOUT_START_MS:
            raise HoldoutLocked(f"{day} lies in the holdout; S2 reads no holdout day")

    # -- ingest -------------------------------------------------------------------------------
    def cached(self, day: date) -> dict | None:
        """The manifest entry of an already reduced day whose aggregate file is intact, else None."""
        entry = self.manifest().get(day.isoformat())
        if entry and self.agg_path(day).exists() and _sha256(self.agg_path(day)) == entry["agg_sha256"]:
            return entry
        return None

    def prepare(self, day: date, *, keep_raw: bool = False, fast: bool | None = None, verify: bool = False) -> dict:
        """Download, verify and reduce one day; write agg/px files; return the manifest entry WITHOUT recording it.

        Safe to run for different days in parallel processes: every file it
        writes is specific to the day. Only ``record`` touches the manifest.
        """
        self.guard(day)
        ref = BinanceArchiveRef(day, self.symbol)
        checksum = self.fetcher(ref.checksum_url).decode("utf-8")
        payload = self.fetcher(ref.url)
        digest = parse_official_checksum(checksum, expected_filename=ref.filename)
        if not verify_archive(payload, digest):
            raise ValueError(f"checksum mismatch for {ref.filename}")
        use_fast = fast_available() if fast is None else fast
        aggregates, prices, rows = (reduce_day_fast if use_fast else reduce_day)(payload, day)
        if verify:
            reference = reduce_day(payload, day) if use_fast else reduce_day_fast(payload, day)
            if reference != (aggregates, prices, rows):
                raise ValueError(f"{day}: fast and reference reduction differ; day refused")
        self._write_agg(day, aggregates)
        self._write_px(day, prices)
        if keep_raw:
            self.raw_path(day).parent.mkdir(parents=True, exist_ok=True)
            self.raw_path(day).write_bytes(payload)
        return {"archive_sha256": digest, "url": ref.url, "rows": rows, "agg_sha256": _sha256(self.agg_path(day)),
                "px_sha256": _sha256(self.px_path(day)), "raw_kept": keep_raw, "reduction": "fast" if use_fast else "reference", "verified_both": verify}

    def record(self, day: date, entry: dict) -> dict:
        """Write one day's entry into the manifest (single writer: the parent process)."""
        manifest = self.manifest()
        manifest[day.isoformat()] = entry
        self._write_manifest(manifest)
        return entry

    def fetch(self, day: date, *, keep_raw: bool = False, fast: bool | None = None, verify: bool = False) -> dict:
        """Download, verify, reduce and record one day. Returns its manifest entry.

        ``fast`` picks the pandas path (default: when available); ``verify``
        runs both paths and refuses the day if they differ.
        """
        self.guard(day)
        cached = self.cached(day)
        if cached is not None:
            return cached
        return self.record(day, self.prepare(day, keep_raw=keep_raw, fast=fast, verify=verify))

    def _write_agg(self, day: date, aggregates: Sequence[MinuteAggregate]) -> None:
        path = self.agg_path(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(AGG_HEADER)
            for item in aggregates:
                writer.writerow(item.as_row())

    def _write_px(self, day: date, prices: Sequence[MinutePrices | None]) -> None:
        path = self.px_path(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(PX_HEADER)
            for item in prices:
                if item is not None:
                    writer.writerow([item.window_start_ms, item.first_price, item.last_price, item.high_price, item.low_price, item.first_agg_trade_id, item.last_agg_trade_id])

    # -- count-run input -----------------------------------------------------------------------
    def present_days(self) -> list[date]:
        return sorted(date.fromisoformat(key) for key in self.manifest())

    def load_aggregates(self, day: date) -> list[MinuteAggregate]:
        """The seven rule fields of one day, verified against the manifest. Never touches ``px/``."""
        self.guard(day)
        entry = self.manifest().get(day.isoformat())
        path = self.agg_path(day)
        if entry is None or not path.exists():
            raise FileNotFoundError(f"{day} has not been fetched")
        if _sha256(path) != entry["agg_sha256"]:
            raise ValueError(f"{day}: aggregates changed on disk since they were verified")
        with path.open(newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            if header != AGG_HEADER:
                raise ValueError(f"{day}: unexpected aggregate layout")
            items = [MinuteAggregate.from_row(row) for row in reader]
        if len(items) != MINUTES_PER_DAY or items[0].window_start_ms != day_start_ms(day):
            raise ValueError(f"{day}: aggregate file is not one full day")
        return items

    def dataset_hash(self, days: Iterable[date]) -> str:
        """Stable hash over archive and aggregate digests of the days used."""
        manifest = self.manifest()
        entries = sorted((day.isoformat(), manifest[day.isoformat()]["archive_sha256"], manifest[day.isoformat()]["agg_sha256"]) for day in days)
        return hashlib.sha256(json.dumps(entries).encode()).hexdigest()
