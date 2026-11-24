"""Point-in-time Orderflow-Lage for the shadows (Paket E, #372, Uzi 24.11.2026 "GO E").

Orderflow-Schatten, Zweitmeinung and Chart-Urteil note the Live-Orderflow-Lage at a plan's creation and fill. Until
now they took whatever Lage was current when their step ran: after a pause or a restart a plan from 11:00 got the
Lage of 12:00, and the Chart-Urteil accepted a Lage up to ten minutes *after* the plan. This module is the one place
that answers "which Lage was known at moment t?":

- ``observe(lage, seen_at)`` keeps every Lage a consumer saw, per symbol, with ``seen_at`` as its availability. The
  real availability is at the latest ``seen_at`` (the consumer holds it then), so the check is conservative: it may
  say UNKNOWN where a Lage existed, never the other way round.
- ``lage_at(symbol, t)`` returns the newest kept Lage with ``as_of <= t``, ``last_trade_at <= t``, ``seen_at <= t``
  and ``t - as_of <= MAX_AGE`` (one-sided, no tolerance after t), not stale. Otherwise ``None`` with a reason
  (``UNKNOWN_*``). A missing historical Lage is never replaced by the current one.
- ``store_until(store, t)`` cuts a footprint store (spot or perp, rows ``[bucket_time, level, bid, ask]``) to the
  buckets that had ended by t, so value levels and naked POCs drawn for t see no later trade.

The history lives in memory: after a restart older moments are UNKNOWN. Plans recorded before ``PIT_VERSION`` keep
their values untouched and are counted apart (``legacy``) by the consumers.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

PIT_VERSION = "pit/1"
MAX_AGE = timedelta(minutes=3)  # the Lage refreshes every 10 s and consumers run every minute: 3 min is ample
KEEP = timedelta(hours=12)
OK = "OK"
UNKNOWN_NO_HISTORY = "UNKNOWN_NO_HISTORY"  # nothing kept from that time (restart, gap, start of the shadow)
UNKNOWN_TOO_OLD = "UNKNOWN_TOO_OLD"  # the newest Lage known at t is older than MAX_AGE
UNKNOWN_STALE = "UNKNOWN_STALE"  # the Lage known at t said itself that its trades were stale
UNKNOWN_NO_TIME = "UNKNOWN_NO_TIME"  # target time missing or unreadable

_LOCK = Lock()
_HISTORY: dict[str, deque[dict[str, Any]]] = {}


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    return moment if moment.tzinfo is not None else None


def _symbol(lage: Mapping[str, Any] | None, default: str = "BTCUSDT") -> str:
    return str((lage or {}).get("symbol") or default).upper()


def observe(lage: Mapping[str, Any] | None, seen_at: datetime, symbol: str | None = None) -> None:
    """Keep ``lage`` as available from ``seen_at`` on; the same ``as_of`` is kept once (first sighting wins)."""
    if not lage or _time(lage.get("as_of")) is None or seen_at.tzinfo is None:
        return
    key = (symbol or _symbol(lage)).upper()
    with _LOCK:
        kept = _HISTORY.setdefault(key, deque())
        if any(item["lage"].get("as_of") == lage.get("as_of") for item in kept):
            return
        kept.append({"seen_at": seen_at, "lage": dict(lage)})
        newest = max(item["seen_at"] for item in kept)
        while kept and kept[0]["seen_at"] < newest - KEEP:
            kept.popleft()


def reset(symbol: str | None = None) -> None:
    """Forget the history (tests, or one symbol)."""
    with _LOCK:
        if symbol is None:
            _HISTORY.clear()
        else:
            _HISTORY.pop(symbol.upper(), None)


def lage_at(symbol: str, target: Any, max_age: timedelta = MAX_AGE) -> tuple[dict[str, Any] | None, str]:
    """The Lage known at ``target`` and its status; ``(None, UNKNOWN_*)`` when there is none."""
    moment = _time(target)
    if moment is None:
        return None, UNKNOWN_NO_TIME
    with _LOCK:
        kept = list(_HISTORY.get(symbol.upper()) or ())
    known = []
    for item in kept:
        lage = item["lage"]
        as_of = _time(lage.get("as_of"))
        last = lage.get("last_trade_at")
        last_time = _time(last) if last else None
        if as_of is None or as_of > moment or item["seen_at"] > moment:
            continue
        if last and (last_time is None or last_time > moment):
            continue
        known.append((as_of, lage))
    if not known:
        return None, UNKNOWN_NO_HISTORY
    as_of, lage = max(known, key=lambda pair: pair[0])
    if moment - as_of > max_age:
        return None, UNKNOWN_TOO_OLD
    if lage.get("stale") or lage.get("price") is None:
        return None, UNKNOWN_STALE
    return dict(lage), OK


def live_after(lage: Mapping[str, Any] | None, moment: Any) -> bool:
    """True when the current ``lage`` was taken at or after ``moment`` (a live exit may use it then, never before)."""
    as_of, since = _time((lage or {}).get("as_of")), _time(moment)
    return as_of is not None and since is not None and as_of >= since


def store_until(store: Mapping[str, Any] | None, target: Any) -> dict[str, Any] | None:
    """A footprint store cut to the buckets that had ended by ``target``; days not finished by then lose ``complete``."""
    moment = _time(target)
    if not store or moment is None:
        return None
    bucket = int(store.get("bucket_seconds") or 300)
    limit = moment.timestamp()
    days = {}
    for key, rows in (store.get("days") or {}).items():
        kept = [row for row in rows if float(row[0]) + bucket <= limit]
        if kept:
            days[key] = kept
    complete = {}
    for key, value in (store.get("complete") or {}).items():
        try:
            day_end = datetime.fromisoformat(key).replace(tzinfo=timezone.utc) + timedelta(days=1)
        except ValueError:
            continue
        if key in days and day_end.timestamp() <= limit:
            complete[key] = value
    bubbles = {}
    for key, rows in (store.get("bubbles") or {}).items():
        kept = [row for row in rows if isinstance(row, (list, tuple)) and row and float(row[0]) <= limit * 1000]  # ms
        if kept:
            bubbles[key] = kept
    return {**store, "days": days, "complete": complete, "bubbles": bubbles, "cut_at": moment.isoformat()}
