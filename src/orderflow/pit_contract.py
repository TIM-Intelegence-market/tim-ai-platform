"""Shared point-in-time data contract for TIM (Mission 07, #372): one rule for A (live Lage) and E (shadows).

A value may be used as evidence for a decision at moment ``t`` only when all of these hold:

1. **Identity**: it belongs to the expected source and symbol (when the caller names them).
2. **Event**: its event time, or the end of its interval (a bucket ``[start, start + width)``), is ``<= t``.
3. **Availability**: the moment it was actually available to TIM, for *this exact revision* of the value, is known
   and ``<= t``. Availability is never inferred from event time: a value without a recorded availability is
   ``UNKNOWN_AVAILABILITY``, not "available since its event".

Anything else is not evidence at ``t``: it is left out of the inputs and every judgement derived from them, with a
reason. A missing value is UNKNOWN, never 0 and never neutral.

Two building blocks:

* :func:`check` for one observation (a Lage, a gamma snapshot, a trade batch).
* :class:`RevisionLog` for stores of buckets that are rewritten in place (footprint, perp flow): it keeps, per
  bucket key, each distinct value with the moment it was first seen, so ``rows_at(t)`` returns for every bucket the
  revision that was known at ``t`` (an earlier revision if the bucket was revised later, nothing if it only appeared
  later, e.g. a backfill after a gap). Seen times are taken by the caller when it holds the store, so they are an
  upper bound of the real availability: the rule may say UNKNOWN where a value existed, never the reverse. After a
  restart the log is empty and everything before is UNKNOWN.

Pure standard library, no I/O. The persistent variant (receipt times written by the recorder) is E2.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any

CONTRACT_VERSION = "pit-contract/1"
OK = "OK"
UNKNOWN_NO_TIME = "UNKNOWN_NO_TIME"                # target or a needed time is missing or has no time zone
UNKNOWN_AVAILABILITY = "UNKNOWN_AVAILABILITY"      # no recorded availability for this value / revision
FUTURE_EVENT = "FUTURE_EVENT"                      # event or interval end after t
NOT_YET_AVAILABLE = "NOT_YET_AVAILABLE"            # available only after t
WRONG_SOURCE = "WRONG_SOURCE"                      # source or symbol differs from the expected one


def as_time(value: Any) -> datetime | None:
    """A time with a zone from a datetime, ISO text or epoch seconds (int/float); else None. Naive is never guessed."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc) if math.isfinite(value) else None
    if isinstance(value, str) and value:
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return moment if moment.tzinfo is not None else None
    return None


@dataclass(frozen=True)
class Observation:
    source: str
    symbol: str
    event_end: datetime | None        # event time, or end of the interval the value describes
    available_at: datetime | None     # when this exact revision was available to TIM; None = unknown
    revision: Any = None


def check(obs: Observation, target: Any, *, source: str | None = None, symbol: str | None = None) -> str:
    """``OK`` when ``obs`` is evidence at ``target``, else the reason (one of the ``UNKNOWN_*`` / ``*`` constants)."""
    moment = as_time(target)
    if moment is None:
        return UNKNOWN_NO_TIME
    if (source is not None and obs.source != source) or (symbol is not None and obs.symbol.upper() != symbol.upper()):
        return WRONG_SOURCE
    if obs.event_end is None or obs.event_end.tzinfo is None:
        return UNKNOWN_NO_TIME
    if obs.event_end > moment:
        return FUTURE_EVENT
    if obs.available_at is None or obs.available_at.tzinfo is None:
        return UNKNOWN_AVAILABILITY
    if obs.available_at > moment:
        return NOT_YET_AVAILABLE
    return OK


_ABSENT = object()
BUCKET_OK, BUCKET_MISSING, BUCKET_INVALID = "OK", "MISSING", "INVALID"


def bucket_size(store: Mapping[str, Any] | None, field: str = "bucket_seconds") -> tuple[int | None, str]:
    """The bucket width a store states about itself, as ``(seconds, status)``.

    The width decides which buckets are closed at ``t``, so it is evidence like any value: only a positive whole number
    written in the store counts. A missing key or ``None`` is ``MISSING``; a bool, text, NaN, infinity, zero, a
    negative or a fraction is ``INVALID``. In both cases the size is ``None``: no default stands in for it."""
    raw = store.get(field, _ABSENT) if isinstance(store, Mapping) else _ABSENT
    if raw is _ABSENT or raw is None:
        return None, BUCKET_MISSING
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw <= 0 \
            or not float(raw).is_integer():
        return None, BUCKET_INVALID
    return int(raw), BUCKET_OK


def _key(day: str, row: Any) -> tuple[str, float, float] | None:
    try:
        return day, float(row[0]), float(row[1])
    except (TypeError, ValueError, IndexError):
        return None


class RevisionLog:
    """Per bucket key, every distinct value with the moment it was first seen (see module doc).

    Rows are ``[bucket_start_epoch, level, *values]`` grouped by day, the layout of the footprint and perp stores.
    """

    def __init__(self, keep_seconds: float = 12 * 3600) -> None:
        self.keep_seconds = float(keep_seconds)
        self._log: dict[tuple[str, float, float], list[tuple[float, tuple[float, ...]]]] = {}
        self._lock = Lock()
        self.first_seen: float | None = None

    def observe(self, days: Mapping[str, Iterable[Any]] | None, seen_at: datetime) -> int:
        """Note the store as held at ``seen_at``; returns how many new revisions were kept."""
        if not days or seen_at.tzinfo is None:
            return 0
        seen = seen_at.timestamp()
        added = 0
        with self._lock:
            self.first_seen = seen if self.first_seen is None else min(self.first_seen, seen)
            for day, rows in days.items():
                for row in rows or ():
                    key = _key(str(day), row)
                    if key is None:
                        continue
                    try:
                        values = tuple(float(v) for v in row[2:])
                    except (TypeError, ValueError):
                        continue
                    history = self._log.setdefault(key, [])
                    if not history or history[-1][1] != values:
                        if history and seen < history[-1][0]:
                            continue          # never insert a revision back in time
                        history.append((seen, values))
                        added += 1
            limit = seen - self.keep_seconds
            for key in [k for k, h in self._log.items() if k[1] < limit and h[-1][0] < limit]:
                del self._log[key]
        return added

    def rows_at(self, target: Any, bucket_seconds: float) -> tuple[dict[str, list[list[float]]], dict[str, int]]:
        """Rows known at ``target``: closed buckets (start + width <= t) in the revision first seen at or before t.

        Returns ``(days, counts)``; counts say how many buckets were left out and why (``open``, ``unknown``: no
        revision seen by t, e.g. a later backfill or anything from before the first observation) and how many were
        taken in an earlier revision because they changed after t (``revised_later``). Without a usable
        ``bucket_seconds`` (see :func:`bucket_size`) nothing can be called closed: no rows, every bucket ``unknown``.
        """
        moment = as_time(target)
        counts = {"kept": 0, "open": 0, "unknown": 0, "revised_later": 0}
        if moment is None:
            return {}, counts
        if bucket_size({"bucket_seconds": bucket_seconds})[0] is None:
            with self._lock:
                counts["unknown"] = len(self._log)
            return {}, counts
        limit = moment.timestamp()
        days: dict[str, list[list[float]]] = {}
        with self._lock:
            items = [(k, list(h)) for k, h in self._log.items()]
        for (day, start, level), history in sorted(items):
            if start + bucket_seconds > limit:
                counts["open"] += 1
                continue
            known = [values for seen, values in history if seen <= limit]
            if not known:
                counts["unknown"] += 1
                continue
            if len(known) < len(history):
                counts["revised_later"] += 1
            counts["kept"] += 1
            days.setdefault(day, []).append([start, level, *known[-1]])
        return days, counts

    def revisions_at(self, target: Any) -> tuple[list[tuple[str, float, float, float, tuple[float, ...], bool]], int]:
        """Per bucket the revision known at ``target``, with the moment it was first seen; no closed-bucket rule.

        Returns ``(rows, unknown)``: rows are ``(day, start, level, seen, values, revised_later)``; ``unknown`` counts
        the buckets with no revision seen by ``target``. For callers whose bucket width depends on the revision
        (``live_state``, Codex #377 27.11.): the width a bucket is judged by is the one of the store revision it was
        first seen in."""
        moment = as_time(target)
        if moment is None:
            return [], 0
        limit = moment.timestamp()
        with self._lock:
            items = [(k, list(h)) for k, h in self._log.items()]
        rows: list[tuple[str, float, float, float, tuple[float, ...], bool]] = []
        unknown = 0
        for (day, start, level), history in sorted(items):
            known = [(seen, values) for seen, values in history if seen <= limit]
            if not known:
                unknown += 1
                continue
            seen, values = known[-1]
            rows.append((day, start, level, seen, values, len(known) < len(history)))
        return rows, unknown

    def reset(self) -> None:
        with self._lock:
            self._log.clear()
            self.first_seen = None
