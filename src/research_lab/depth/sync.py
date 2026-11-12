"""Binance USDⓈ-M diff-depth synchronisation ("How to manage a local order book correctly", read 12.11.2026).

1. Buffer stream events. 2. Load a REST snapshot (``lastUpdateId`` = L). 3. Drop events with ``u`` < L.
4. The first applied event needs ``U`` <= L <= ``u``. 5. Every later event needs ``pu`` == previous ``u``,
otherwise the book is invalid until the next snapshot. Quantities are absolute; 0 removes a level.

The same class runs live in the recorder and offline in the replay, so both build identical books.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.research_lab.depth.book import ASK, BID, LocalBook

MAX_BUFFER = 20_000  # ~30 min at 100 ms; beyond that the buffer is useless for a snapshot anyway


@dataclass
class SyncCounts:
    applied: int = 0
    dropped: int = 0
    gaps: int = 0
    stale_snapshots: int = 0
    snapshots: int = 0


@dataclass
class DepthSync:
    book: LocalBook = field(default_factory=LocalBook)
    valid: bool = False
    last_u: int | None = None
    counts: SyncCounts = field(default_factory=SyncCounts)
    _buffer: list[dict] = field(default_factory=list)
    _snapshot_id: int | None = None  # set while waiting for the first event that bridges the snapshot

    @property
    def needs_snapshot(self) -> bool:
        return not self.valid and self._snapshot_id is None

    def invalidate(self) -> None:
        """Connection lost or gap: book unusable until the next snapshot; buffered events from before are useless."""
        self.valid = False
        self.last_u = None
        self._snapshot_id = None
        self._buffer.clear()

    def on_snapshot(self, snap: dict) -> None:
        last_id = int(snap["lastUpdateId"])
        self.counts.snapshots += 1
        self.book.load(snap.get("bids", []), snap.get("asks", []))
        self.valid = False
        self.last_u = None
        self._snapshot_id = last_id
        pending, self._buffer = self._buffer, []
        for ev in pending:
            self.on_event(ev)

    def on_event(self, ev: dict) -> str:
        """Feed one ``depthUpdate`` payload. Returns applied / buffered / dropped / gap / stale."""
        if self.valid:
            if int(ev["pu"]) != self.last_u:
                self.counts.gaps += 1
                self.invalidate()
                self._buffer.append(ev)
                return "gap"
            self._apply(ev)
            return "applied"
        if self._snapshot_id is None:
            self._buffer.append(ev)
            if len(self._buffer) > MAX_BUFFER:
                del self._buffer[: len(self._buffer) - MAX_BUFFER]
            return "buffered"
        return self._bridge(ev)

    def _bridge(self, ev: dict) -> str:
        last_id = self._snapshot_id
        assert last_id is not None
        if int(ev["u"]) < last_id:
            self.counts.dropped += 1
            return "dropped"
        if int(ev["U"]) > last_id:
            # Snapshot older than the stream: the events in between are lost. Ask for a newer snapshot.
            self.counts.stale_snapshots += 1
            self._snapshot_id = None
            self._buffer.append(ev)
            return "stale"
        self._snapshot_id = None
        self.valid = True
        self._apply(ev)
        return "applied"

    def _apply(self, ev: dict) -> None:
        for p, q in ev.get("b", []):
            self.book.set(BID, p, q)
        for p, q in ev.get("a", []):
            self.book.set(ASK, p, q)
        self.last_u = int(ev["u"])
        self.counts.applied += 1
        if self.book.crossed():
            # A crossed book means our state is wrong; never compute features from it.
            self.counts.gaps += 1
            self.invalidate()
