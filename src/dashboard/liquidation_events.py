"""Real liquidations for the chart, read from the S12 collector's raw record (display only).

The S12 collector (``src/research_lab/liquidations``) writes every public liquidation message of
Binance USD-M (``forceOrder``) and Bybit linear (``allLiquidation``) unchanged as one JSON line per
record under ``<root>/raw/<venue>/<day>.jsonl`` on the Mac. This module turns the lines of the
shown window into chart items: time, price, side of the liquidated position, size in USD, venue.
It writes nothing, changes no record and never touches the study's evaluation (``gate.py``,
``snapshots.py``); the heatmap (``liquidation_data.py``) stays the model it is.

Reading is incremental: per day file the parsed events and the byte offset are cached, so a chart
request parses only the lines appended since the last request. A line still being written (no
newline yet) waits for the next request.

Issue #162 (Master-Analyse 09.11.2026): "echte Liquidationen statt Modell" as its own layer.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from src.research_lab.liquidations import events as liq_events
from src.research_lab.liquidations.store import data_root, raw_path

VENUES = (liq_events.BINANCE, liq_events.BYBIT)
VENUE_NAMES = {liq_events.BINANCE: "Binance", liq_events.BYBIT: "Bybit"}
SYMBOL = "BTCUSDT"  # the collector records BTC only (S12)
MAX_ITEMS = 300  # largest liquidations of the window carried to the browser
MIN_USD = 5_000.0  # smaller ones are counted, not drawn
SOURCE = "Binance forceOrder + Bybit allLiquidation (öffentlich, S12-Sammler, nur Anzeige)"

_cache: dict[Path, tuple[int, list[liq_events.LiquidationEvent]]] = {}


def default_root() -> Path:
    return data_root()


def _parse_lines(venue: str, text: str) -> list[liq_events.LiquidationEvent]:
    parse = liq_events.PARSERS[venue]
    found: list[liq_events.LiquidationEvent] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("kind") != "message" or not isinstance(record.get("payload"), str):
            continue
        try:
            message = json.loads(record["payload"])
        except ValueError:
            continue
        if not isinstance(message, Mapping):
            continue
        try:
            found.extend(e for e in parse(message) if e.counts and e.symbol == SYMBOL)
        except liq_events.EventFormatError:
            continue
    return found


def events_of(path: Path, venue: str) -> list[liq_events.LiquidationEvent]:
    """Events of one day file; only the bytes appended since the last call are parsed."""
    try:
        size = path.stat().st_size
    except OSError:
        _cache.pop(path, None)
        return []
    offset, found = _cache.get(path, (0, []))
    if size < offset:  # file replaced or truncated: start over
        offset, found = 0, []
    if size > offset:
        with path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read(size - offset)
        complete = chunk.rfind(b"\n") + 1  # a partial last line waits for the next request
        if complete:
            found = found + _parse_lines(venue, chunk[:complete].decode("utf-8", "replace"))
            offset += complete
        _cache[path] = (offset, found)
    return found


def _days(start: datetime, end: datetime) -> list[date]:
    first, last = start.date() - timedelta(days=1), end.date()  # the day file is named by receive time (UTC)
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


def window_events(root: Path, start: datetime, end: datetime) -> dict[str, list[liq_events.LiquidationEvent]]:
    """Events per venue with ``start <= time < end``, duplicates removed."""
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    result = {}
    for venue in VENUES:
        found = []
        for day in _days(start, end):
            path = raw_path(root, venue, day)
            if path.exists():
                found.extend(e for e in events_of(path, venue) if start_ms <= e.time_ms < end_ms)
        result[venue] = liq_events.dedupe(found)
    return result


def chart_items(root: Path | None, symbol: str, first_time: int, now: datetime | None = None) -> dict[str, Any]:
    """Chart part ``liquidations``: the largest real liquidations between the first candle and now.

    ``items``: ``time`` (epoch seconds, ms precision), ``price``, ``side`` ("long" = long position
    liquidated, a forced sell), ``usd``, ``quantity``, ``venue``. ``counts`` has every event per venue
    in the window, ``usd`` per venue the summed size. ``note`` says what is missing.
    """
    empty = {"items": [], "counts": {}, "usd": {}, "min_usd": None, "max_usd": None, "source": SOURCE, "note": None}
    if symbol != SYMBOL:
        return empty
    root = root or default_root()
    now = now or datetime.now(timezone.utc)
    if not any((root / "raw" / venue).is_dir() for venue in VENUES):
        return {**empty, "note": "Liquidationen: kein Mitschnitt des S12-Sammlers gefunden, Ebene leer."}
    start = datetime.fromtimestamp(first_time, tz=timezone.utc)
    per_venue = window_events(root, start, now)
    missing = [VENUE_NAMES[v] for v in VENUES if not (root / "raw" / v).is_dir()]
    rows = []
    for venue, found in per_venue.items():
        for event in found:
            usd = float(event.notional)
            rows.append((usd, event.time_ms / 1000.0, float(event.price), event.side, float(event.quantity), venue))
    rows.sort(reverse=True)
    drawn = [r for r in rows if r[0] >= MIN_USD][:MAX_ITEMS]
    drawn.sort(key=lambda r: r[1])
    items = [{"time": round(t, 3), "price": price, "side": side, "usd": round(usd, 0), "quantity": quantity, "venue": venue}
             for usd, t, price, side, quantity, venue in drawn]
    note = None
    if missing:
        note = f"Liquidationen: nur {', '.join(VENUE_NAMES[v] for v in VENUES if VENUE_NAMES[v] not in missing)} im Mitschnitt, {', '.join(missing)} fehlt."
    elif not rows:
        note = "Liquidationen: keine Ereignisse im gezeigten Fenster."
    return {"items": items, "counts": {v: len(found) for v, found in per_venue.items()},
            "usd": {v: round(sum(float(e.notional) for e in found), 0) for v, found in per_venue.items()},
            "min_usd": items[0]["usd"] if items else None, "max_usd": max((i["usd"] for i in items), default=None),
            "source": SOURCE, "note": note}
