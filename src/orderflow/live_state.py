"""Live-Orderflow-Lage: TIM folgt dem laufenden Trade-Strom und beschreibt die Welle (Paket 1, 08.11.2026).

Bisher landen Spot-Trades in PostgreSQL, Delta und Footprint entstehen daraus nur für den Chart; die
Plan-Entscheidung sieht davon nichts. Dieses Modul hält die letzten Minuten der Spot-aggTrades im
Speicher (``LiveOrderflowTracker.ingest``) und beschreibt daraus alle paar Sekunden den Zustand
(``snapshot``):

- Fenster 1m/5m/15m: Volumen, Delta, Käufer-/Verkäuferanteil, Tempo gegenüber den letzten 20 Minuten,
- Tages-CVD, Tages-Hoch/-Tief (UTC-Tag),
- die Welle: Richtung, Stärke 0-3, Phase (aufbauend / läuft / ebbt ab) und Exhaustion,
- Orderflow an den nahen Leveln (Vortages-VAH/VAL/POC, Tages-POC, Tages-Hoch/-Tief): Bid x Ask,
  Imbalance, Absorption (viel Volumen am Level, Preis kommt nicht durch),
- Perp-Delta der letzten 5 und 15 Minuten aus dem Perp-Store (5-Minuten-Körbe, grober als Spot).

Aggressorseite (Paket B, #372, 24.11.2026): ``buyer_is_maker`` ist nur als echtes ``True`` / ``False`` bekannt. Jeder andere
Wert (``None``, Text, Zahl) ist ``UNKNOWN``: er zählt ins Volumen und in ``unknown_volume``, aber nie ins Delta, den CVD oder
die Käufer-/Verkäuferanteile. ``buy_share`` hat als Nenner nur das Volumen mit bekannter Seite.

Point-in-Time (Paket A, #372, 24.11.2026): ``snapshot(now)`` sieht nur Trades mit Eventzeit <= ``now`` UND Verfügbarkeit
<= ``now``. Verfügbarkeit ist der Zeitpunkt, zu dem der Aufrufer den Trade bekam (``ingest(..., available_at=)``). Ohne diese Angabe
ist die Verfügbarkeit UNKNOWN (gemeinsamer Vertrag ``src/orderflow/pit_contract.py``, Mission 07): solche Trades werden nie
aus der Eventzeit erschlossen, sondern verworfen und als ``unavailable_dropped`` gezählt; die eigenen Tageswerte des Tages
heißen dann ``UNVOLLSTÄNDIG``. Perp-Körbe laufen über eine kanonische As-of-Historie (``PerpAsOf``, Runde 2 27.11.): ein Korb zählt bei ``now`` nur
geschlossen und in der Fassung, die TIM bis ``now`` gesehen hat (ein Nachtrag nach ``now`` bleibt draußen), unabhängig
von der Reihenfolge, in der die Fassungen eingelesen wurden; ein Korb mit mehrdeutiger Breite macht sein Fenster UNKNOWN. Fenster, Preis, Tageswerte (aus dem Stand je Trade), Level und Perp-Körbe enden bei ``now``; spätere Trades
zählen nur als ``future_trades``. Zu spät gelieferte Trades mit älterer Eventzeit werden nicht rückwirkend eingefügt, sondern
als ``late_dropped`` gezählt. Snapshots laufen zeitlich vorwärts; ein früheres ``now`` als ein schon gezeigtes ist ein Fehler.
Gleicher Strom, ob in Stücken oder auf einmal eingelesen, ergibt so denselben Snapshot (``snapshot_hash``).

Alle Schwellen stehen in ``THRESHOLDS`` und sind unkalibrierte Startwerte (Präreg OF2 entscheidet
später). Nichts hier handelt, schreibt einen Plan oder ändert einen Score: reine Beschreibung, als
Datei ``data/orderflow/orderflow_lage.json`` für Chart, Control Center und den Hermes-Leser.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from bisect import bisect_left
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.orderflow.pit_contract import as_time, bucket_size
from statistics import median
from typing import Any

from src.models.market_data import Trade

SCHEMA_VERSION = "orderflow-lage/3"  # 2: unknown aggressor side (Paket B); 3: point-in-time fields (Paket A)
SIDE_SCHEMA = "side-evidence/1"  # windows[*].side_evidence, additive (27.11.): the input of the known-side policy
BUY, SELL, UNKNOWN = 1, -1, 0  # aggressor side of a trade
DEFAULT_PATH = Path("data/orderflow/orderflow_lage.json")
WINDOWS = {"1m": 60, "5m": 300, "15m": 900}
KEEP_SECONDS = 1800  # 15m window plus 20 one-minute baseline buckets, with reserve
BASELINE_MINUTES = 20
BUCKET_NOT_AVAILABLE = "NOT_AVAILABLE"  # no store revision with a known time seen by the snapshot
BUCKET_INCONSISTENT = "INCONSISTENT"  # store revisions with the same write time state different widths
BUCKET_TOO_WIDE = "TOO_WIDE"  # a width above PERP_MAX_WIDTH: the 5/15-minute windows cannot be judged with it
BUCKET_HISTORY_GONE = "HISTORY_GONE"  # the snapshot asks for a moment older than the kept as-of history
PERP_MAX_WIDTH = 900  # widest bucket a 5/15-minute perp delta can be built from
PERP_ROW_HORIZON = WINDOWS["15m"] + PERP_MAX_WIDTH  # a revision seen at s only matters for buckets starting >= s - this
PERP_KEEP = 2 * 3600  # as-of history kept behind the newest store revision; older moments are HISTORY_GONE
LEVEL_RANGE_PCT = 0.6  # levels farther away than this share of the price are not reported
THRESHOLDS = {
    "direction_share": 0.15,  # |delta| / volume of the 5m window needed for a direction
    "tempo_strength": (1.0, 1.6, 2.5),  # tempo ratio bounds for strength 1, 2, 3
    "fade_ratio": 0.5,  # last minute below this share of the 3-minute peak = fading
    "stall_range_share": 0.3,  # 1m range below this share of the 5m range = price stalls
    "imbalance_ratio": 3.0,  # ask/bid (or bid/ask) at a level
    "absorption_volume_factor": 3.0,  # level volume vs. the median level volume in the 15m window
}


def aggressor_side(buyer_is_maker: object) -> int:
    """``SELL`` when the buyer was the maker, ``BUY`` when not, ``UNKNOWN`` for anything that is not a real bool."""
    if buyer_is_maker is True:
        return SELL
    if buyer_is_maker is False:
        return BUY
    return UNKNOWN


def _epoch(moment: datetime) -> float:
    return moment.astimezone(timezone.utc).timestamp()


def _day_start(moment: datetime) -> float:
    utc = moment.astimezone(timezone.utc)
    return _epoch(utc.replace(hour=0, minute=0, second=0, microsecond=0))


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def _decimal_text(value: Decimal) -> str:
    """A non-negative exact amount as a plain decimal string (no exponent, no sign), e.g. ``0.000007013695409686748``."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _exact(value: float) -> Decimal:
    """A trade quantity as the decimal it was written as (shortest repr of the float), so sums carry no binary noise."""
    return Decimal(repr(float(value)))


def _bucket_state(rows: Sequence[Any]) -> tuple[float, float] | None:
    """(bid, ask) of one bucket in one store revision, summed over its level rows; ``None`` when a row is unusable."""
    bids, asks = [], []
    for row in rows:
        try:
            values = [row[2], row[3]]
        except (TypeError, IndexError, KeyError):
            return None
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values):
            return None
        bids.append(float(values[0]))
        asks.append(float(values[1]))
    return math.fsum(bids), math.fsum(asks)     # correctly rounded: independent of the row order


class PerpAsOf:
    """Bitemporal history of perp store revisions: canonical, so the noting order never matters (Codex #377, 27.11.).

    Every store revision has a write time ``u`` (``updated_at``) and the moment ``s`` TIM first held it (``seen``).
    Kept per revision: the width it states and, per bucket start, its ``(bid, ask)`` summed over the level rows.
    Entries are keyed by content with the earliest ``seen``: noting the same revision twice, or the revisions in
    another order, gives the same history. The answer at ``t`` uses only revisions with ``seen <= t``:

    - width at ``t``: the one of the newest write time seen by ``t``; revisions with that write time and different
      widths are ``INCONSISTENT``; none seen is ``NOT_AVAILABLE``; above ``PERP_MAX_WIDTH`` it is ``TOO_WIDE``.
    - a bucket (start ``b``) is AMBIGUOUS when the revisions seen by ``t`` that contain it state more than one width,
      a missing/unusable/too wide width, an unusable row, or, at their newest write time, different values. The same
      start under another width is another bucket and which one a row means cannot be decided: it is never counted
      and never closed early (a value update may not move a bucket end forward).
    - otherwise its width ``w`` is that single width; it is closed iff ``b + w <= t``; its value is the one of the
      newest write time seen by ``t``.
    - a window (5 or 15 minutes) sums closed buckets with ``b >= t - window - w``; an ambiguous bucket that could fall
      into it makes the window UNKNOWN (``None``), never a partial sum.

    Bounded without changing any answer at ``t >= F`` (``F`` = newest ``seen`` - ``PERP_KEEP``): rows starting more than
    ``PERP_ROW_HORIZON`` before their revision's ``seen`` are not kept (never in a window at ``t >= seen``); entries
    seen by ``F`` are folded into what every later answer needs (the newest write time, the set of widths and values
    seen); buckets starting before ``F - PERP_ROW_HORIZON`` are dropped. Each cut depends only on the set of revisions,
    not on the order. A moment before ``F`` is ``HISTORY_GONE`` (snapshots move forward, so live this never happens).
    """

    def __init__(self) -> None:
        self._widths: dict[tuple[float, int | None, str], float] = {}           # (u, width, status) -> first seen
        # bucket start -> {(u, width, status, (bid, ask) or None): first seen}
        self._buckets: dict[float, dict[tuple[float, int | None, str, tuple[float, float] | None], float]] = {}
        # bucket start -> (widths, values) of every entry folded at the floor
        self._folded: dict[float, tuple[frozenset, frozenset]] = {}
        self._newest: float | None = None

    def observe(self, store: Mapping[str, Any], updated: datetime, seen_at: datetime) -> None:
        u, seen = updated.timestamp(), seen_at.timestamp()
        width, status = bucket_size(store)
        key = (u, width, status)
        self._widths[key] = min(seen, self._widths.get(key, seen))
        grouped: dict[float, list[Any]] = {}
        for rows in (store.get("days") or {}).values():
            for row in rows or ():
                try:
                    start = float(row[0])
                except (TypeError, ValueError, IndexError, KeyError):
                    continue
                if math.isfinite(start) and start >= seen - PERP_ROW_HORIZON:
                    grouped.setdefault(start, []).append(row)
        for start, rows in grouped.items():
            entries = self._buckets.setdefault(start, {})
            entry = (u, width, status, _bucket_state(rows))
            entries[entry] = min(seen, entries.get(entry, seen))
        self._newest = seen if self._newest is None else max(self._newest, seen)
        self._fold(self._newest - PERP_KEEP)

    def _fold(self, floor: float) -> None:
        old = [k for k, s in self._widths.items() if s <= floor]
        if old:
            top = max(u for u, _w, _st in old)
            self._widths = {k: s for k, s in self._widths.items() if s > floor or k[0] == top}
        for start in list(self._buckets):
            if start < floor - PERP_ROW_HORIZON:
                del self._buckets[start]
                self._folded.pop(start, None)
                continue
            entries = self._buckets[start]
            old_entries = [e for e, s in entries.items() if s <= floor]
            if not old_entries:
                continue
            widths, values = self._folded.get(start, (frozenset(), frozenset()))
            self._folded[start] = (widths | {(w, st) for _u, w, st, _v in old_entries},
                                   values | {v for *_x, v in old_entries})
            top = max(e[0] for e in old_entries)
            self._buckets[start] = {e: s for e, s in entries.items() if s > floor or e[0] == top}
        for start in [k for k in self._folded if k not in self._buckets]:
            del self._folded[start]

    def _floor(self) -> float | None:
        return None if self._newest is None else self._newest - PERP_KEEP

    def width_at(self, t: float) -> tuple[int | None, str]:
        floor = self._floor()
        if floor is not None and t < floor:
            return None, BUCKET_HISTORY_GONE
        known = [k for k, s in self._widths.items() if s <= t]
        if not known:
            return None, BUCKET_NOT_AVAILABLE
        newest = max(u for u, _w, _st in known)
        stated = {(w, st) for u, w, st in known if u == newest}
        if len(stated) > 1:
            return None, BUCKET_INCONSISTENT
        width, status = stated.pop()
        if width is not None and width > PERP_MAX_WIDTH:
            return None, BUCKET_TOO_WIDE
        return width, status

    def at(self, now: datetime) -> dict[str, Any]:
        t = now.timestamp()
        bucket, bucket_status = self.width_at(t)
        if bucket is None:
            return {"status": "Bucket-Größe unbekannt", "bucket_seconds": None, "bucket_seconds_status": bucket_status}
        counts = {"open": 0, "ambiguous": 0, "revised": 0, "other_width": 0}
        unknown_windows: set[str] = set()
        sums = {"5m": 0.0, "15m": 0.0}
        volume15 = 0.0
        seen_any = False
        for start, entries in sorted(self._buckets.items()):
            known = [e for e, s in entries.items() if s <= t]
            if not known:
                continue
            folded_widths, folded_values = self._folded.get(start, (frozenset(), frozenset()))
            widths = set(folded_widths) | {(w, st) for _u, w, st, _v in known}
            newest = max(u for u, *_ in known)
            values = {v for u, _w, _st, v in known if u == newest}
            usable = {w for w, _st in widths if w is not None and w <= PERP_MAX_WIDTH}
            if len(widths) > 1 or len(usable) != 1 or len(values) > 1 or None in values:
                counts["ambiguous"] += 1
                reach = min(max([w for w, _st in widths if w is not None] + [bucket]), PERP_MAX_WIDTH)
                for name in ("5m", "15m"):
                    if t - WINDOWS[name] - reach <= start < t:
                        unknown_windows.add(name)
                continue
            width = usable.pop()
            if start + width > t:
                counts["open"] += 1
                continue
            bid, ask = next(iter(values))
            counts["revised"] += int(len(set(folded_values) | {e[3] for e in known}) > 1)
            if start < t - WINDOWS["15m"] - width:
                continue
            counts["other_width"] += int(width != bucket)
            seen_any = True
            sums["15m"] += ask - bid
            volume15 += ask + bid
            if start >= t - WINDOWS["5m"] - width:
                sums["5m"] += ask - bid
        meta = {"buckets_open": counts["open"], "buckets_ambiguous": counts["ambiguous"],
                "buckets_revised": counts["revised"], "buckets_other_width": counts["other_width"],
                "window_status": {name: "UNKNOWN" if name in unknown_windows else "OK" for name in ("5m", "15m")}}
        if not seen_any and not unknown_windows:
            return {"status": "keine Daten in den letzten 15 Minuten", "bucket_seconds": bucket, **meta}
        return {"bucket_seconds": bucket,
                "delta_5m": None if "5m" in unknown_windows else _round(sums["5m"]),
                "delta_15m": None if "15m" in unknown_windows else _round(sums["15m"]),
                "volume_15m": None if "15m" in unknown_windows else _round(volume15), **meta}


class LiveOrderflowTracker:
    """Rolling store of the last ``keep_seconds`` of trades for one spot symbol."""

    def __init__(self, symbol: str, tick: float, keep_seconds: int = KEEP_SECONDS) -> None:
        if tick <= 0 or keep_seconds <= WINDOWS["15m"]:
            raise ValueError("tick must be > 0 and keep_seconds longer than the 15m window")
        self.symbol = symbol
        self.tick = float(tick)
        self.keep_seconds = int(keep_seconds)
        self._trades: deque[tuple[float, float, float, int]] = deque()  # (time, price, qty, aggressor side)
        # Parallel to _trades: (available epoch, day key, day cvd, day unknown volume, day high, day low) after the trade.
        self._states: deque[tuple[float, float, float, float, float, float]] = deque()
        self.late_dropped = 0  # trades older than the newest one, delivered late: never inserted back in time
        self.held_back = 0  # trades made visible later than their own availability, waiting for an earlier one
        self.held_back_max_seconds = 0.0  # longest such wait (head-of-line delay of the prefix rule)
        self._last_available: float | None = None  # availability is kept monotone: a trade is visible after all earlier
        self._carry: tuple[float, float, float, float, float, float] | None = None  # state after the last pruned trade
        self._last_snapshot: float | None = None
        self.unavailable_dropped = 0  # trades handed in without available_at: availability UNKNOWN, never evidence
        self._incomplete_days: set[float] = set()  # UTC days whose own values miss such trades
        self._perp_history = PerpAsOf()  # canonical as-of history of the perp store revisions (reference: docs/ORDERFLOW_REFERENZ_AB.md)
        self.last_trade_id: int | None = None
        self.last_trade_time: datetime | None = None
        self.day_key: float | None = None
        self.day_cvd = 0.0
        self.day_high: float | None = None
        self.day_low: float | None = None
        self.day_unknown_volume = 0.0
        self.unknown_trades = 0  # since start, trades without a known aggressor side
        self.last_price: float | None = None
        self.ingested = 0

    def ingest(self, trades: Iterable[Trade], available_at: datetime | None = None) -> int:
        """Add new trades; a trade with an id not above the last seen one is skipped (replay-safe).

        ``available_at`` is when the caller received these trades (live: the clock after the read); a trade is visible to
        a snapshot only from ``max(event time, available_at, availability of every earlier trade)`` on. Visibility is
        a prefix of the stream, so windows and the cumulative day values always describe the same set of trades
        (Codex #377: a later trade available earlier never carries the day values of an earlier, still unseen one).
        """
        added = 0
        if available_at is not None and available_at.tzinfo is None:
            raise ValueError("available_at needs a time zone (a naive time would be read as local time)")
        if available_at is None:
            # Availability UNKNOWN (pit contract): never inferred from the event time. Not added, ids not advanced.
            for trade in trades:
                if trade.symbol == self.symbol:
                    self.unavailable_dropped += 1
                    self._incomplete_days.add(_day_start(trade.event_time))
            return 0
        available = _epoch(available_at)
        for trade in trades:
            if trade.symbol != self.symbol:
                continue
            if trade.trade_id is not None and self.last_trade_id is not None and trade.trade_id <= self.last_trade_id:
                continue
            moment = _epoch(trade.event_time)
            if self._trades and moment < self._trades[-1][0]:
                self.late_dropped += 1  # out of order: the durable store has it in order; never inserted back in time
                continue
            side = aggressor_side(trade.buyer_is_maker)
            day = _day_start(trade.event_time)
            if self.day_key != day:
                self.day_key, self.day_cvd, self.day_high, self.day_low = day, 0.0, None, None
                self.day_unknown_volume = 0.0
            if side == UNKNOWN:
                self.day_unknown_volume += trade.quantity
                self.unknown_trades += 1
            else:
                self.day_cvd += trade.quantity * side
            self.day_high = trade.price if self.day_high is None else max(self.day_high, trade.price)
            self.day_low = trade.price if self.day_low is None else min(self.day_low, trade.price)
            self._trades.append((moment, float(trade.price), float(trade.quantity), side))
            own = max(moment, available)
            seen = own if self._last_available is None else max(own, self._last_available)
            if seen > own:
                self.held_back += 1
                self.held_back_max_seconds = max(self.held_back_max_seconds, seen - own)
            self._last_available = seen
            self._states.append((seen, day, self.day_cvd,
                                 self.day_unknown_volume, float(self.day_high), float(self.day_low)))
            if trade.trade_id is not None:
                self.last_trade_id = trade.trade_id
            self.last_trade_time = trade.event_time
            self.last_price = float(trade.price)
            added += 1
        self.ingested += added
        return added

    def _prune(self, now: float) -> None:
        """Drop trades older than ``keep_seconds`` that were visible at ``now``; their day values live on in ``_carry``."""
        limit = now - self.keep_seconds
        while self._trades and self._trades[0][0] < limit and self._states[0][0] <= now:
            self._trades.popleft()
            self._carry = self._states.popleft()

    def _visible(self, now: float) -> list[int]:
        """Indexes of the trades a snapshot at ``now`` may see: event time and availability both <= now."""
        return [i for i, (trade, state) in enumerate(zip(self._trades, self._states)) if trade[0] <= now and state[0] <= now]

    def _since(self, start: float, end: float | None = None) -> Sequence[tuple[float, float, float, int]]:
        trades = list(self._trades)
        if end is not None:
            trades = [trades[i] for i in self._visible(end)]
        times = [t[0] for t in trades]
        index = bisect_left(times, start)
        return trades[index:]

    @staticmethod
    def _window(trades: Sequence[tuple[float, float, float, int]]) -> dict[str, Any]:
        """One window of trades. ``volume``, ``delta``, ``unknown_volume`` and ``buy_share`` are policy values and are
        not rounded (Codex P2 #376, 27.11.: rounding to 4 places turned 0.00056 known + 0.00004 unknown into "100 %
        known"). The quantities are summed exactly as the decimals they were written as (``_exact``); rounding is only
        for display (``describe`` and the per-minute display list)."""
        buy = sum((_exact(q) for _, _, q, side in trades if side == BUY), Decimal(0))
        sell = sum((_exact(q) for _, _, q, side in trades if side == SELL), Decimal(0))
        unknown = sum((_exact(q) for _, _, q, side in trades if side == UNKNOWN), Decimal(0))
        known = buy + sell
        volume = known + unknown
        prices = [p for _, p, _, _ in trades]
        return {"trades": len(trades), "volume": float(volume), "delta": float(buy - sell),
                "buy_share": float(buy / known) if known else None,
                "unknown_volume": float(unknown), "unknown_trades": sum(1 for *_, side in trades if side == UNKNOWN),
                # The only input of the known-side policy (orderflow_shadow.known_side): exact decimal strings, so no
                # binary rounding sits between producer and consumer (Codex #376, 27.11., 20 x unknown vs total).
                "side_evidence": {"schema": SIDE_SCHEMA, "known": _decimal_text(known), "unknown": _decimal_text(unknown)},
                "high": max(prices) if prices else None, "low": min(prices) if prices else None,
                "range": _round(max(prices) - min(prices), 2) if prices else 0.0}

    def _minutes(self, now: float, count: int) -> list[dict[str, Any]]:
        """Per-minute windows, oldest first, the last one ending at ``now``."""
        trades = self._since(now - 60 * count, now)
        buckets: list[list[tuple[float, float, float, int]]] = [[] for _ in range(count)]
        for item in trades:
            index = int((item[0] - (now - 60 * count)) // 60)
            if 0 <= index < count:
                buckets[index].append(item)
        return [self._window(bucket) for bucket in buckets]

    def _perp(self, store: Mapping[str, Any] | None, now: datetime) -> dict[str, Any] | None:
        """Perp delta of the last 5/15 minutes as TIM could know it at ``now`` (see :class:`PerpAsOf`).

        The store is noted at ``seen = max(now, updated_at)``: live that is the moment TIM holds it, in a replay a
        store written after ``now`` is never seen before it was written (availability is never backdated). A store
        without a readable ``updated_at`` is not noted (its time is unknown). The answer depends only on the revisions
        seen by ``now``, never on the order they were noted or on anything seen later.
        """
        if not store or not store.get("days"):
            return None
        updated = as_time(store.get("updated_at"))
        if updated is not None:
            self._perp_history.observe(store, updated, max(now, updated))
        meta = {"updated_at": store.get("updated_at"), "store_time_known": updated is not None, "closed_buckets_only": True}
        block = self._perp_history.at(now)
        if "delta_5m" in block:
            meta["symbol"] = store.get("symbol")
        return {**meta, **block}

    def snapshot(self, now: datetime, levels: Sequence[Mapping[str, Any]] = (),
                 perp_store: Mapping[str, Any] | None = None,
                 day_profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Describe the orderflow at ``now``.

        ``levels`` are ``{"name", "price"}``; ``perp_store`` is the perp footprint store; ``day_profile`` is the
        running day's volume profile from the spot store (``footprint_data.volume_profiles``), which carries the whole
        UTC day while the tracker itself only holds the last ``keep_seconds`` (the tracker's own day values start at
        the runtime start, 1b fix 08.11.2026).
        """
        moment = _epoch(now)
        if self._last_snapshot is not None and moment < self._last_snapshot:
            raise ValueError("snapshot time went backwards; replay must move forward")
        self._last_snapshot = moment
        self._prune(moment)
        visible = self._visible(moment)
        last = visible[-1] if visible else None
        future = len(self._trades) - len(visible)
        windows = {name: self._window(self._since(moment - seconds, moment)) for name, seconds in WINDOWS.items()}
        minutes = self._minutes(moment, BASELINE_MINUTES + 3)
        baseline = [m["volume"] for m in minutes[:BASELINE_MINUTES] if m["volume"] > 0]
        last_three = minutes[-3:]
        tempo = (last_three[-1]["volume"] / median(baseline)) if baseline and last_three else None
        price = self._trades[last][1] if last is not None else None
        last_time = datetime.fromtimestamp(self._trades[last][0], timezone.utc) if last is not None else None
        wave = _wave(windows, last_three, tempo)
        day = _day_values(self, day_profile, self._states[last] if last is not None else self._carry, moment)
        own_levels = list(levels)
        if day["high"] is not None:
            own_levels += [{"name": "Tages-Hoch", "price": day["high"]}, {"name": "Tages-Tief", "price": day["low"]}]
        level_rows = _levels(self._since(moment - WINDOWS["15m"], moment), own_levels, price, self.tick) if price else []
        perp = self._perp(perp_store, now)
        stale = last_time is None or moment - _epoch(last_time) > 120
        state = {
            "schema": SCHEMA_VERSION, "symbol": self.symbol, "as_of": now.astimezone(timezone.utc).isoformat(),
            "price": price, "last_trade_at": last_time.isoformat() if last_time else None,
            "stale": stale, "future_trades": future, "late_dropped": self.late_dropped,
            "unavailable_dropped": self.unavailable_dropped,
            "held_back": {"trades": self.held_back, "max_seconds": _round(self.held_back_max_seconds, 3)}, "windows": windows, "tempo": _round(tempo, 2) if tempo is not None else None,
            "day": day,
            "wave": wave, "levels": level_rows, "perp": perp, "thresholds": THRESHOLDS,
        }
        state["text"] = describe(state)
        state["snapshot_hash"] = snapshot_hash(state)
        return state


def snapshot_hash(state: Mapping[str, Any]) -> str:
    """SHA-256 over the snapshot without its own hash and the bookkeeping counters that depend on how it was fed."""
    body = {k: v for k, v in state.items() if k not in ("snapshot_hash", "future_trades", "late_dropped", "unavailable_dropped")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _day_values(tracker: LiveOrderflowTracker, profile: Mapping[str, Any] | None,
                at: tuple[float, float, float, float, float, float] | None, now: float) -> dict[str, Any]:
    """Whole-day CVD/high/low at ``now``: the running day profile when there is one, else the tracker's own state after
    the last visible trade, kept after its trade is pruned (never values of later trades). With no visible trade of
    this UTC day the own values are UNKNOWN (None), not 0."""
    if at is None or at[1] != _day_start(datetime.fromtimestamp(now, timezone.utc)):
        own = {"cvd": None, "high": None, "low": None, "unknown_volume": None, "source": "seit Start der Runtime",
               "status": "UNKNOWN"}
    else:
        own = {"cvd": _round(at[2]), "high": at[4], "low": at[5], "unknown_volume": _round(at[3]),
               "source": "seit Start der Runtime", "status": "UNVOLLSTÄNDIG" if at[1] in tracker._incomplete_days else "OK"}
    if not profile or not profile.get("rows"):
        return own
    prices = [float(r["price"]) for r in profile["rows"] if r.get("volume")]
    if not prices:
        return own
    step = float(profile.get("step") or 0.0)
    high, low = max(prices) + step, min(prices)
    if own["high"] is not None:
        high, low = max(high, own["high"]), min(low, own["low"])
    return {"cvd": _round(float(profile.get("delta") or 0.0)), "high": high, "low": low,
            "unknown_volume": own["unknown_volume"], "status": "OK",
            "source": "Tagesprofil des Spot-Stores (bis 2 min alt) plus Trades seit Start"}


def _wave(windows: Mapping[str, Mapping[str, Any]], last_three: Sequence[Mapping[str, Any]], tempo: float | None) -> dict[str, Any]:
    five = windows["5m"]
    direction = "keine"
    if five["volume"] and abs(five["delta"]) / five["volume"] >= THRESHOLDS["direction_share"]:
        direction = "auf" if five["delta"] > 0 else "ab"
    strength = 0
    if tempo is not None and direction != "keine":
        strength = sum(1 for bound in THRESHOLDS["tempo_strength"] if tempo >= bound)
    sign = 1 if direction == "auf" else -1
    deltas = [m["delta"] * sign for m in last_three]  # positive = with the wave
    volumes = [m["volume"] for m in last_three]
    phase = "keine"
    exhaustion = False
    if direction != "keine" and len(last_three) == 3 and volumes[-1] > 0:
        peak = max(volumes)
        stalled = bool(five["range"]) and windows["1m"]["range"] < THRESHOLDS["stall_range_share"] * five["range"]
        if deltas[0] < deltas[1] < deltas[2] and volumes[2] >= volumes[1]:
            phase = "aufbauend"
        elif volumes[-1] < THRESHOLDS["fade_ratio"] * peak or deltas[-1] <= 0:
            phase = "ebbt ab"
            exhaustion = stalled or deltas[-1] <= 0
        else:
            phase = "läuft"
    return {"direction": direction, "strength": strength, "phase": phase, "exhaustion": exhaustion,
            "delta_per_minute": [_round(m["delta"]) for m in last_three]}


def _levels(trades: Sequence[tuple[float, float, float, int]], levels: Sequence[Mapping[str, Any]],
            price: float, tick: float) -> list[dict[str, Any]]:
    by_level: dict[float, list[float]] = {}  # [bid (seller aggressive), ask (buyer aggressive), unknown side]
    for _, p, q, side in trades:
        row = by_level.setdefault(round(p // tick * tick, 8), [0.0, 0.0, 0.0])
        row[{SELL: 0, BUY: 1, UNKNOWN: 2}[side]] += q
    volumes = [sum(row) for row in by_level.values()]
    typical = median(volumes) if volumes else 0.0
    out = []
    for level in levels:
        try:
            target = float(level["price"])
        except (KeyError, TypeError, ValueError):
            continue
        distance_pct = (target - price) / price * 100
        if abs(distance_pct) > LEVEL_RANGE_PCT:
            continue
        tolerance = 2 * tick
        bid = ask = unknown = 0.0
        for key, (b, a, u) in by_level.items():
            if abs(key - target) <= tolerance:
                bid += b
                ask += a
                unknown += u
        volume = bid + ask + unknown
        touched = any(abs(p - target) <= tolerance for _, p, _, _ in trades)
        side_now = "über" if price > target else "unter"
        broke = any((p - target) * (price - target) < -tolerance for _, p, _, _ in trades)  # traded on the far side
        ratio = (ask / bid) if bid else (float("inf") if ask else 0.0)
        imbalance = None
        if bid and ratio >= THRESHOLDS["imbalance_ratio"]:
            imbalance = "Käufer"
        elif ask and (1 / ratio if ratio else 0) >= THRESHOLDS["imbalance_ratio"]:
            imbalance = "Verkäufer"
        absorption = touched and not broke and typical > 0 and volume >= THRESHOLDS["absorption_volume_factor"] * typical
        out.append({"name": str(level.get("name", "Level")), "price": target, "distance_pct": _round(distance_pct, 3),
                    "side": side_now, "tested_15m": touched, "broke_through": broke, "bid": _round(bid), "ask": _round(ask), "unknown": _round(unknown),
                    "delta": _round(ask - bid), "imbalance": imbalance, "absorption": bool(absorption)})
    out.sort(key=lambda row: abs(row["distance_pct"]))
    return out


def describe(state: Mapping[str, Any]) -> str:
    """Short German summary for the Control Center and the Hermes reader; every number comes from ``state``."""
    if state.get("stale") or state.get("price") is None:
        return "Orderflow-Lage: keine frischen Trades (Datenstrom prüfen)."
    wave = state["wave"]
    five = state["windows"]["5m"]
    parts = [f"Preis {state['price']:.0f}."]
    if wave["direction"] == "keine":
        parts.append(f"Keine klare Welle: Delta 5m {five['delta']:+.2f} bei {five['volume']:.1f} Volumen.")
    else:
        word = {"auf": "Käuferwelle", "ab": "Verkäuferwelle"}[wave["direction"]]
        parts.append(f"{word} Stärke {wave['strength']}/3, Phase {wave['phase']}; Delta 5m {five['delta']:+.2f}.")
        if wave["exhaustion"]:
            parts.append("Exhaustion: Tempo fällt, Preis stockt.")
    if state.get("tempo") is not None:
        parts.append(f"Tempo {state['tempo']:.1f}x der letzten 20 Minuten.")
    if state["day"].get("cvd") is not None:
        parts.append(f"Tages-CVD {state['day']['cvd']:+.1f}.")
    if five.get("unknown_volume"):
        parts.append(f"Ohne bekannte Seite 5m: {five['unknown_volume']:.2f} Volumen (nicht im Delta).")
    for level in state.get("levels", [])[:2]:
        flags = [f for f, on in (("Absorption", level["absorption"]), (f"Imbalance {level['imbalance']}", level["imbalance"])) if on]
        tag = f" ({', '.join(flags)})" if flags else ""
        parts.append(f"{level['name']} {level['price']:.0f} {level['distance_pct']:+.2f} %{tag}.")
    perp = state.get("perp") or {}
    if perp.get("delta_5m") is not None or perp.get("delta_15m") is not None:
        five, fifteen = (f"{perp[k]:+.1f}" if perp.get(k) is not None else "unbekannt" for k in ("delta_5m", "delta_15m"))
        parts.append(f"Perp-Delta 5m {five}, 15m {fifteen}.")
    return " ".join(parts)


def levels_from_profiles(profiles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Prior-day VAH/VAL/POC and the running day's POC from ``footprint_data.volume_profiles``."""
    finished = [p for p in profiles if not p.get("running")]
    running = [p for p in profiles if p.get("running")]
    out: list[dict[str, Any]] = []
    if finished:
        prev = finished[-1]
        out += [{"name": "Vortag VAH", "price": prev["vah"]}, {"name": "Vortag VAL", "price": prev["val"]},
                {"name": "Vortag POC", "price": prev.get("poc_mid", prev["poc"])}]
    if running:
        out.append({"name": "Tages-POC", "price": running[-1].get("poc_mid", running[-1]["poc"])})
    return [row for row in out if row["price"] is not None]


def save(state: Mapping[str, Any], path: Path | str = DEFAULT_PATH) -> Path:
    """Write the state atomically (temp file + replace) so readers never see a half file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, target)
    return target


def load(path: Path | str = DEFAULT_PATH) -> dict[str, Any] | None:
    target = Path(path)
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except ValueError:
        return None
