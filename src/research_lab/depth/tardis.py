"""Tardis.dev free sample days (1st of each month, no API key) for Binance USDⓈ-M BTCUSDT: download and check.

Paket P2 of the recorder plan: the same :class:`LocalBook` rebuilds the historical book from
``incremental_book_L2`` and every trade from ``trades`` is checked against the book just before it. No signal, no
feature and no study value is computed here.

Only first-of-month days are allowed (the free ones), and nothing from 2025-01-01 on (holdout, Protokoll 1.3).
CSV columns (Tardis docs): ``exchange,symbol,timestamp,local_timestamp,is_snapshot,side,price,amount`` for the book,
``exchange,symbol,timestamp,local_timestamp,id,side,price,amount`` for trades; ``side`` of a trade is the taker side.

    python -m src.research_lab.depth tardis-check --day 2020-06-01 --dir ~/TIM-research/tardis
"""
from __future__ import annotations

import csv
import gzip
import heapq
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from src.research_lab.depth.book import ASK, BID, LocalBook, to_units
from src.research_lab.depth.replay import TradeCheck

BASE = "https://datasets.tardis.dev/v1/binance-futures/{kind}/{y:04d}/{m:02d}/{d:02d}/BTCUSDT.csv.gz"
KINDS = ("incremental_book_L2", "trades")
HOLDOUT_START = date(2025, 1, 1)
CLEAN_FROM = date(2020, 6, 1)  # Tardis: collection issues before 2020-05-14
MAX_BYTES = 8 * 1024**3


def check_day(day: date) -> None:
    if day.day != 1:
        raise ValueError(f"{day}: only the free first day of a month is allowed")
    if day >= HOLDOUT_START:
        raise ValueError(f"{day}: holdout (from {HOLDOUT_START}) is locked")
    if day < CLEAN_FROM:
        raise ValueError(f"{day}: before {CLEAN_FROM} Tardis reports collection gaps")


def url_for(kind: str, day: date) -> str:
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r}")
    check_day(day)
    return BASE.format(kind=kind, y=day.year, m=day.month, d=day.day)


def download(kind: str, day: date, folder: Path, max_bytes: int = MAX_BYTES) -> Path:
    """Stream one file to ``folder``; refuses to grow beyond ``max_bytes``. Existing complete files are kept."""
    url = url_for(kind, day)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{kind}_{day.isoformat()}_BTCUSDT.csv.gz"
    if out.exists():
        return out
    tmp = out.with_suffix(".part")
    got = 0
    req = urllib.request.Request(url, headers={"User-Agent": "tim-research-depth/1"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as fh:
        while chunk := resp.read(1 << 20):
            got += len(chunk)
            if got > max_bytes:
                fh.close()
                tmp.unlink(missing_ok=True)
                raise ValueError(f"{url}: larger than {max_bytes} bytes, stopped")
            fh.write(chunk)
    tmp.replace(out)
    return out


def _rows(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", newline="") as fh:
        yield from csv.DictReader(fh)


@dataclass
class DayCheck:
    day: str
    book_rows: int = 0
    trades: int = 0
    snapshot_resets: int = 0
    crossed_rows: int = 0
    max_levels: int = 0
    seconds_with_book: int = 0
    seconds_crossed: int = 0
    seconds_spread_one_tick: int = 0
    trade_check: TradeCheck = field(default_factory=TradeCheck)
    elapsed_s: float = 0.0
    file_bytes: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = asdict(self)
        out["trade_check"]["share"] = self.trade_check.share
        return out


def check(book_csv: Path, trades_csv: Path, day: date) -> DayCheck:
    """Merge book and trade rows by local receive time and check each trade against the book before it."""
    check_day(day)
    started = time.monotonic()
    res = DayCheck(day=day.isoformat(), file_bytes={"book": book_csv.stat().st_size,
                                                     "trades": trades_csv.stat().st_size})
    book = LocalBook()
    in_snapshot = False
    valid = False
    last_sec: int | None = None
    tick = to_units("0.1")

    def tagged(path: Path, tag: int) -> Iterator[tuple[int, int, dict]]:
        for r in _rows(path):
            yield int(r["local_timestamp"]), tag, r

    # tag 0 = book before tag 1 = trade at the same microsecond: the trade sees the update received with it
    for ts, tag, r in heapq.merge(tagged(book_csv, 0), tagged(trades_csv, 1)):
        sec = ts // 1_000_000
        if last_sec is not None and sec > last_sec and valid:
            res.seconds_with_book += 1
            if book.crossed():
                res.seconds_crossed += 1
            else:
                b, a = book.best_bid(), book.best_ask()
                if b is not None and a is not None and a - b == tick:
                    res.seconds_spread_one_tick += 1
        last_sec = sec
        if tag == 0:
            res.book_rows += 1
            snap = r["is_snapshot"] == "true"
            if snap and not in_snapshot:
                book.clear()
                res.snapshot_resets += 1
            in_snapshot = snap
            book.set(BID if r["side"] == "bid" else ASK, r["price"], r["amount"])
            valid = len(book) > 0
            if not snap and book.crossed():
                res.crossed_rows += 1
            res.max_levels = max(res.max_levels, len(book))
        else:
            res.trades += 1
            res.trade_check.add(book, valid and not book.crossed(),
                                to_units(r["price"]), taker_buys=r["side"] == "buy")
    res.elapsed_s = round(time.monotonic() - started, 1)
    return res
