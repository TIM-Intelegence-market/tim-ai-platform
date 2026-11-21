"""Rebuild the book from recorded raw rows and check it against the recorder's live checksums.

Acceptance (S8 Depth-Datenvertrag, Abschnitt 5): every ``second`` row written live must be reproduced exactly from
the raw rows of the same run. The same pass checks each aggTrade against the book just before it (a buy by a taker
cannot print below the best ask minus one tolerance, a sell not above the best bid plus one).
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.research_lab.bitunix.recorder import read_segment
from src.research_lab.depth.book import LocalBook, to_units
from src.research_lab.depth.sync import DepthSync

_SEGMENT = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(\d+)\.jsonl\.gz$")
TICK_UNITS = to_units("0.1")  # BTCUSDT perpetual tick


@dataclass
class TradeCheck:
    """Trades compared with the book state right before them (book valid only)."""

    tolerance_units: int = TICK_UNITS
    checked: int = 0
    inside: int = 0
    skipped_invalid: int = 0
    worst_units: int = 0

    def add(self, book: LocalBook, valid: bool, price_units: int, taker_buys: bool) -> None:
        if not valid:
            self.skipped_invalid += 1
            return
        self.checked += 1
        if taker_buys:
            ref = book.best_ask()
            miss = 0 if ref is None else max(0, ref - price_units)
        else:
            ref = book.best_bid()
            miss = 0 if ref is None else max(0, price_units - ref)
        if miss <= self.tolerance_units:
            self.inside += 1
        self.worst_units = max(self.worst_units, miss)

    @property
    def share(self) -> float | None:
        return self.inside / self.checked if self.checked else None


@dataclass
class ReplayResult:
    runs: int = 0
    rows: int = 0
    seconds: int = 0
    valid_seconds: int = 0
    matches: int = 0
    mismatches: int = 0
    first_mismatch_sec: int | None = None
    incomplete_segments: int = 0
    gaps: int = 0
    trades: TradeCheck = field(default_factory=TradeCheck)

    def as_dict(self) -> dict:
        out = asdict(self)
        out["trades"]["share"] = self.trades.share
        out["valid_share"] = self.valid_seconds / self.seconds if self.seconds else None
        out["ok"] = self.mismatches == 0 and self.seconds > 0
        return out


def runs(root: Path, symbol: str = "BTCUSDT") -> dict[int, list[Path]]:
    """Segment files grouped by run id, each list in day order."""
    out: dict[int, list[Path]] = defaultdict(list)
    for f in (root / symbol).glob("*.jsonl.gz"):
        m = _SEGMENT.match(f.name)
        if m:
            out[int(m.group(2))].append(f)
    return {k: sorted(v) for k, v in sorted(out.items())}


def replay_rows(rows: Iterable[dict], result: ReplayResult) -> Iterator[tuple[int, DepthSync]]:
    """Feed one run's rows in file order; yields (exchange second, sync) at every live checkpoint.

    The recorder writes a ``second`` row right before the first depth event of a later second, so the replayed book
    at that row is the book the recorder checksummed.
    """
    sync = DepthSync()
    for row in rows:
        result.rows += 1
        kind = row.get("kind")
        if kind == "session" and row.get("stream") == "depth":
            sync.invalidate()
        elif kind == "gap":
            result.gaps += 1
            if row.get("stream") == "depth":
                sync.invalidate()
        elif kind == "snapshot":
            sync.on_snapshot(row["msg"])
        elif kind == "depth":
            sync.on_event(row["msg"])
        elif kind == "aggTrade":
            t = row["msg"]
            # m = buyer is maker -> the taker sold
            result.trades.add(sync.book, sync.valid, to_units(t["p"]), taker_buys=not bool(t["m"]))
        elif kind == "second":
            s = int(row["sec"])
            mine = (sync.valid, sync.book.checksum() if sync.valid else None)
            result.seconds += 1
            result.valid_seconds += int(bool(row["valid"]))
            if mine == (bool(row["valid"]), row.get("sum")):
                result.matches += 1
            else:
                result.mismatches += 1
                if result.first_mismatch_sec is None:
                    result.first_mismatch_sec = s
            yield s, sync


def replay(root: Path) -> ReplayResult:
    result = ReplayResult()
    for files in runs(root).values():
        result.runs += 1
        rows: list[dict] = []
        for f in files:
            part, complete = read_segment(f)
            rows.extend(part)
            result.incomplete_segments += int(not complete)
        for _ in replay_rows(rows, result):
            pass
    return result
