"""Standing walls in the recorded Binance USD-M order book (:mod:`.binance`, :mod:`.book`), read while it grows.

Uzi 21.11.2026: mark the gamma levels on the chart where the order book really shows large resting orders. A
wall is a price bucket whose resting quantity is far above the usual bucket on its side. Resting orders can be
pulled at any time, so only a wall that stayed for ``STAND_SECONDS`` counts as standing.

Frozen before any look at outcomes (``RULESET``): bucket width, reach, enter/stay factor and standing time.

Limits, said plainly: the book is the recorder's (snapshot of 1000 levels per side plus every later change), so a
far order that never changed since the last restart of the recorder is not in it. Binance perpetual only.

:class:`Tail` follows the newest gzip segments of one symbol without re-reading them (the recorder flushes with a
sync flush every few seconds, so a streaming decompressor can pick up where it stopped) and drives a
:class:`Tracker` in event time: one scan per ``SCAN_SECONDS`` of recorded time, also while catching up.
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path
from statistics import median
from typing import Any

from src.research_lab.orderbook.book import Book

RULESET = "orderbuch-mauern/1.0"
BUCKET_USD = {"BTCUSDT": 50.0}  # price bucket per symbol; only recorded symbols are listed
REACH_PCT = 0.05                # buckets within 5 % of the mid price are looked at
ENTER_FACTOR = 5.0              # a bucket becomes a wall at this multiple of the median bucket of its side ...
STAY_FACTOR = 2.5               # ... and stays one while it holds this multiple (orders are refilled and eaten)
MIN_BUCKETS = 20                # fewer filled buckets on a side: no median worth the name, no walls
STAND_SECONDS = 1800            # a wall must stay this long before it counts as standing
SCAN_SECONDS = 60               # one scan per minute of recorded time
SHOWN = 5                       # standing walls reported per side
CHUNK = 1 << 20                 # compressed bytes read per step
LOOKBACK_SECONDS = 7200         # at the first read, rows older than this are skipped unparsed (the day's file is large);
                                # the book then starts at the first snapshot inside the window
MAX_STEP_BYTES = 4 << 20        # compressed bytes per call of Tail.advance: catch-up comes in small steps, so the
                                # runtime that hosts the reader is never busy for long


def buckets(book: Book, width: float) -> tuple[dict[float, float], dict[float, float], float | None]:
    """Quantity per price bucket (lower edge) for bids and asks within reach, and the mid price."""
    if not book.bids or not book.asks:
        return {}, {}, None
    best_bid = max(float(p) for p in book.bids)
    best_ask = min(float(p) for p in book.asks)
    if best_bid >= best_ask:
        return {}, {}, None
    mid = (best_bid + best_ask) / 2
    low, high = mid * (1 - REACH_PCT), mid * (1 + REACH_PCT)
    out: list[dict[float, float]] = []
    for levels in (book.bids, book.asks):
        side: dict[float, float] = {}
        for price, qty in levels.items():
            p = float(price)
            if low <= p <= high:
                edge = (p // width) * width
                side[edge] = side.get(edge, 0.0) + qty
        out.append(side)
    return out[0], out[1], mid


class Tracker:
    """Walls over time. ``scan`` is called with the book at one moment; ``standing`` lists walls old enough."""

    def __init__(self, width: float) -> None:
        self.width = width
        self.walls: dict[tuple[str, float], dict[str, Any]] = {}
        self.last_scan_ms: int | None = None
        self.mid: float | None = None

    def reset(self) -> None:
        self.walls.clear()
        self.last_scan_ms = None
        self.mid = None

    def scan(self, t_ms: int, book: Book) -> None:
        bids, asks, mid = buckets(book, self.width)
        if mid is None:
            return
        if self.last_scan_ms is not None and t_ms - self.last_scan_ms > 3 * SCAN_SECONDS * 1000:
            self.walls.clear()  # a hole in the recording: nothing is known about the time between
        self.last_scan_ms, self.mid = t_ms, mid
        seen: set[tuple[str, float]] = set()
        for side, levels in (("bid", bids), ("ask", asks)):
            if len(levels) < MIN_BUCKETS:
                continue
            usual = median(levels.values())
            if usual <= 0:
                continue
            for edge, qty in levels.items():
                key = (side, edge)
                ratio = qty / usual
                known = self.walls.get(key)
                if ratio >= ENTER_FACTOR or (known is not None and ratio >= STAY_FACTOR):
                    seen.add(key)
                    if known is None:
                        self.walls[key] = {"side": side, "low": edge, "high": edge + self.width, "since_ms": t_ms,
                                           "qty": qty, "ratio": ratio}
                    else:
                        known["qty"], known["ratio"] = qty, ratio
        for key in [k for k in self.walls if k not in seen]:
            del self.walls[key]

    def standing(self) -> list[dict[str, Any]]:
        if self.last_scan_ms is None:
            return []
        out = []
        for side in ("bid", "ask"):
            rows = [w for w in self.walls.values()
                    if w["side"] == side and self.last_scan_ms - w["since_ms"] >= STAND_SECONDS * 1000]
            rows.sort(key=lambda w: w["qty"], reverse=True)
            out += [{**w, "qty": round(w["qty"], 3), "ratio": round(w["ratio"], 2),
                     "notional_usd": round(w["qty"] * (w["low"] + w["high"]) / 2)} for w in rows[:SHOWN]]
        return out


def _recv_ms(line: bytes) -> int:
    """``recv_ms`` of a recorder row read from its first bytes, without parsing the row; a huge number when absent
    (gap rows carry none and must always be read)."""
    at = line.find(b'"recv_ms":', 0, 80)
    if at < 0:
        return 1 << 62
    end = at + 10
    while end < len(line) and line[end:end + 1].isdigit():
        end += 1
    return int(line[at + 10:end] or (1 << 62))


def segments(root: Path, symbol: str) -> list[Path]:
    """Segments of one symbol, oldest first (name: ``<day>.<run_start_ms>.jsonl.gz``)."""
    folder = Path(root) / symbol
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.jsonl.gz"), key=lambda p: (p.name.split(".")[0], int(p.name.split(".")[1]) if p.name.split(".")[1].isdigit() else 0))


class Tail:
    """Follows the newest segment of ``symbol`` under ``root`` and keeps book and wall tracker up to date."""

    def __init__(self, root: Path, symbol: str, skip_before_ms: int | None = None) -> None:
        """``skip_before_ms``: rows received before this moment are passed over without parsing (None: read all)."""
        self.skip_before_ms = skip_before_ms
        if symbol not in BUCKET_USD:
            raise ValueError(f"no bucket width for {symbol}")
        self.root, self.symbol = Path(root), symbol
        self.book = Book()
        self.tracker = Tracker(BUCKET_USD[symbol])
        self.path: Path | None = None
        self.offset = 0
        self._inflate: Any = None
        self._rest = b""
        self.last_event_ms: int | None = None
        self.caught_up = False

    def _open(self, path: Path) -> None:
        same_run = self.path is not None and self.path.name.split(".")[1] == path.name.split(".")[1]
        if not same_run:        # another run starts with a gap row; do not carry a book across it
            self.book.reset()
        self.path, self.offset, self._rest = path, 0, b""
        self._inflate = zlib.decompressobj(16 + zlib.MAX_WBITS)

    def _row(self, row: dict) -> None:
        kind = row.get("kind")
        if kind == "gap":
            self.book.reset()
        elif kind == "snapshot":
            if not self.book.synced:
                self.book.load_snapshot(row["msg"])
        elif kind == "depth":
            if self.book.apply(row["msg"]) != "applied":
                return
            t = int(row["msg"].get("E", row.get("recv_ms", 0)))
            self.last_event_ms = t
            last = self.tracker.last_scan_ms
            if last is None or t - last >= SCAN_SECONDS * 1000:
                self.tracker.scan(t, self.book)

    def _feed(self, data: bytes) -> None:
        while data:
            try:
                text = self._inflate.decompress(data)
            except zlib.error:
                # damaged member: give this file up, the next one starts clean
                self._rest, self.offset = b"", self.path.stat().st_size if self.path else 0
                self.book.reset()
                return
            lines = (self._rest + text).split(b"\n")
            self._rest = lines.pop()
            for line in lines:
                if self.skip_before_ms is not None and _recv_ms(line) < self.skip_before_ms:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    self._row(row)
            if not self._inflate.eof:
                return
            data = self._inflate.unused_data    # next gzip member in the same file
            self._inflate = zlib.decompressobj(16 + zlib.MAX_WBITS)

    def advance(self, max_bytes: int = MAX_STEP_BYTES) -> bool:
        """Read what the recorder wrote since the last call (at most ``max_bytes``). True when caught up."""
        files = segments(self.root, self.symbol)
        if not files:
            self.caught_up = False
            return False
        if self.path is None:
            self._open(files[-1])   # start with the newest segment; older days are not needed for today's walls
        budget = max_bytes
        while True:
            assert self.path is not None
            try:
                size = self.path.stat().st_size
            except OSError:
                self.path = None
                self.caught_up = False
                return False
            if size < self.offset:  # file replaced: start it again
                self._open(self.path)
            with self.path.open("rb") as fh:
                fh.seek(self.offset)
                while budget > 0:
                    data = fh.read(min(CHUNK, budget))
                    if not data:
                        break
                    self.offset += len(data)
                    budget -= len(data)
                    self._feed(data)
            if budget <= 0:
                self.caught_up = False
                return False
            files = segments(self.root, self.symbol)
            newer = files[files.index(self.path) + 1:] if self.path in files else files[-1:]
            if not newer:
                self.caught_up = True
                return True
            self._open(newer[0])

    def view(self) -> dict[str, Any]:
        return {"ruleset": RULESET, "symbol": self.symbol, "source": "Binance USD-M Perp, eigenes Orderbuch-Archiv",
                "caught_up": self.caught_up, "synced": self.book.synced, "last_event_ms": self.last_event_ms,
                "mid": self.tracker.mid, "bucket_usd": self.tracker.width, "stand_seconds": STAND_SECONDS,
                "walls": self.tracker.standing(), "candidates": len(self.tracker.walls)}
