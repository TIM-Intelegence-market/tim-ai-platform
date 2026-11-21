"""Rebuild a Binance USD-M order book from recorded rows (:mod:`.binance`) and summarise a recording.

Chain rule (Binance docs, "How to manage a local order book correctly", USD-M futures): after a snapshot with
``lastUpdateId`` drop every event with ``u < lastUpdateId``; the first applied event has
``U <= lastUpdateId <= u``; every later event has ``pu`` equal to the previous event's ``u``. A quantity of 0
removes the level. Any break (or a ``gap`` row) marks the book unsynced until the next snapshot; nothing is
guessed in between.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from src.research_lab.bitunix.recorder import read_segment


@dataclass
class Book:
    bids: dict[str, float] = field(default_factory=dict)
    asks: dict[str, float] = field(default_factory=dict)
    last_u: int | None = None
    synced: bool = False      # True once the first event after a snapshot fitted the chain
    _pending: bool = False    # snapshot loaded, waiting for the first fitting event

    def reset(self) -> None:
        self.bids.clear()
        self.asks.clear()
        self.last_u, self.synced, self._pending = None, False, False

    def load_snapshot(self, snap: dict) -> None:
        self.bids = {p: float(q) for p, q in snap.get("bids", []) if float(q) > 0}
        self.asks = {p: float(q) for p, q in snap.get("asks", []) if float(q) > 0}
        self.last_u, self.synced, self._pending = int(snap["lastUpdateId"]), False, True

    def apply(self, ev: dict) -> str:
        """``"applied"``, ``"old"`` (before the snapshot), ``"nobook"`` (waiting for a snapshot) or ``"break"``."""
        if self.last_u is None:
            return "nobook"
        u, first, prev = int(ev["u"]), int(ev["U"]), ev.get("pu")
        if self._pending:
            if u < self.last_u:
                return "old"
            if not first <= self.last_u <= u:
                self.reset()
                return "break"
            self._pending, self.synced = False, True
        elif prev is None or int(prev) != self.last_u:
            self.reset()
            return "break"
        for side, levels in ((self.bids, ev.get("b", [])), (self.asks, ev.get("a", []))):
            for p, q in levels:
                if float(q) == 0:
                    side.pop(p, None)
                else:
                    side[p] = float(q)
        self.last_u = u
        return "applied"

    def top(self, n: int = 10) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        bids = sorted(((float(p), q) for p, q in self.bids.items()), reverse=True)[:n]
        asks = sorted((float(p), q) for p, q in self.asks.items())[:n]
        return bids, asks

    @property
    def crossed(self) -> bool:
        if not self.bids or not self.asks:
            return False
        return max(float(p) for p in self.bids) >= min(float(p) for p in self.asks)


def replay(rows: Iterable[dict]) -> Iterator[tuple[int, Book]]:
    """Yield ``(event time ms, book)`` after every applied event; the same Book object is updated in place."""
    book = Book()
    for row in rows:
        kind = row.get("kind")
        if kind == "gap":
            book.reset()
        elif kind == "snapshot":
            if not book.synced:          # a synced book keeps running; later snapshots only help after a break
                book.load_snapshot(row["msg"])
        elif kind == "depth":
            if book.apply(row["msg"]) == "applied":
                yield int(row["msg"].get("E", row.get("recv_ms", 0))), book


def check(paths: Iterable[Path]) -> dict:
    """Summary of a recording: rows per kind, chain breaks, share of events on a synced book, crossed books (every 100th event), bytes."""
    out = {"files": 0, "bytes": 0, "complete": True, "rows": {}, "applied": 0, "old": 0, "nobook": 0, "breaks": 0,
           "crossed": 0, "first_ms": None, "last_ms": None, "levels_bid": 0, "levels_ask": 0}
    rows: list[dict] = []
    for path in sorted(paths):
        r, complete = read_segment(path)
        out["files"] += 1
        out["bytes"] += path.stat().st_size
        out["complete"] = out["complete"] and complete
        rows += r
    book = Book()
    for row in rows:
        kind = row.get("kind", "?")
        out["rows"][kind] = out["rows"].get(kind, 0) + 1
        t = row.get("recv_ms") or row.get("to_ms")
        if t is not None:
            out["first_ms"] = t if out["first_ms"] is None else min(out["first_ms"], t)
            out["last_ms"] = t if out["last_ms"] is None else max(out["last_ms"], t)
        if kind == "gap":
            book.reset()
        elif kind == "snapshot" and not book.synced:
            book.load_snapshot(row["msg"])
        elif kind == "depth":
            res = book.apply(row["msg"])
            out["breaks" if res == "break" else res] += 1
            if res == "applied" and out["applied"] % 100 == 0 and book.crossed:   # sampled: O(levels) per check
                out["crossed"] += 1
    out["levels_bid"], out["levels_ask"] = len(book.bids), len(book.asks)
    depth = out["rows"].get("depth", 0)
    out["synced_share"] = round(out["applied"] / depth, 4) if depth else 0.0
    hours = (out["last_ms"] - out["first_ms"]) / 3_600_000 if out["first_ms"] is not None and out["last_ms"] != out["first_ms"] else 0
    out["hours"] = round(hours, 3)
    out["bytes_per_day_estimate"] = int(out["bytes"] * 24 / hours) if hours else None
    return out
