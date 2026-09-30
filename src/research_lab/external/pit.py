"""Point-in-time view: what an external series looked like at a given instant.

Rule: at time T a vintage is visible only when ``available_at <= T``. For each
reference period the newest visible vintage wins. Anything that cannot be
established fails closed (NOT_AVAILABLE, UNKNOWN, INSUFFICIENT_DATA), never an
older or later value.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from src.research_lab.external.records import (
    AvailabilityBasis,
    IngestResult,
    QualityState,
    SourceSpec,
    Unusable,
    ValueStatus,
    VintageObservation,
    decimal_str,
    iso,
    require_utc,
)


class Visibility(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"  # the visible vintage says "no value"
    UNKNOWN = "UNKNOWN"  # the visible vintage exists but is unusable
    NOT_AVAILABLE = "NOT_AVAILABLE"  # nothing published yet at T
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # the ingested archive does not cover T


class DataNotReady(ValueError):
    """Raised when a store is built from a payload that failed data quality."""


@dataclass(frozen=True, slots=True)
class PointValue:
    status: Visibility
    at: datetime
    period_start: date | None = None
    value: Decimal | None = None
    vintage: date | None = None
    available_at: datetime | None = None
    availability_basis: str | None = None
    revision_number: int | None = None  # 0 = earliest archived vintage of the period visible at T
    first_release_in_archive: bool | None = None
    stale: bool = False
    record_id: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "at": iso(self.at),
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "value": decimal_str(self.value),
            "vintage": self.vintage.isoformat() if self.vintage else None,
            "available_at": iso(self.available_at),
            "availability_basis": self.availability_basis,
            "revision_number": self.revision_number,
            "first_release_in_archive": self.first_release_in_archive,
            "stale": self.stale,
            "record_id": self.record_id,
            "reason": self.reason,
        }


Entry = VintageObservation | Unusable


class PointInTimeStore:
    """Immutable index over one ingested series."""

    def __init__(self, ingest: IngestResult) -> None:
        if ingest.state is not QualityState.READY:
            raise DataNotReady(f"{ingest.spec.source}:{ingest.spec.source_identifier} is {ingest.state.value}")
        self.ingest = ingest
        self.spec: SourceSpec = ingest.spec
        self.coverage_end = ingest.coverage_end
        by_period: dict[date, list[Entry]] = defaultdict(list)
        for entry in [*ingest.records, *ingest.unusable]:
            by_period[entry.period_start].append(entry)
        # Ties on available_at are ordered by vintage, so the order never depends on input order.
        self._entries = {period: sorted(items, key=lambda item: (item.available_at, item.vintage)) for period, items in by_period.items()}
        self._times = {period: [item.available_at for item in items] for period, items in self._entries.items()}
        self._periods = sorted(self._entries)
        # When each period first became visible, to find the newest period known at T.
        self._first_seen = sorted((items[0].available_at, period) for period, items in self._entries.items())

    def _check(self, at: datetime) -> tuple[datetime, PointValue | None]:
        at = require_utc(at, "at")
        if at > self.coverage_end:
            return at, PointValue(Visibility.INSUFFICIENT_DATA, at, reason="replay time is after the ingested archive coverage")
        return at, None

    def value(self, period_start: date, at: datetime) -> PointValue:
        at, refused = self._check(at)
        if refused:
            return PointValue(refused.status, at, period_start=period_start, reason=refused.reason)
        items = self._entries.get(period_start)
        count = bisect_right(self._times[period_start], at) if items else 0
        if not count:
            return PointValue(Visibility.NOT_AVAILABLE, at, period_start=period_start, reason="no vintage available at this time")
        entry = items[count - 1]  # type: ignore[index]
        common: dict[str, Any] = {
            "period_start": period_start,
            "vintage": entry.vintage,
            "available_at": entry.available_at,
            "revision_number": count - 1,
            "first_release_in_archive": period_start not in self.ingest.periods_without_first_release,
        }
        if isinstance(entry, Unusable):
            return PointValue(Visibility.UNKNOWN, at, reason=entry.reason, **common)
        status = Visibility.MISSING if entry.value_status is ValueStatus.MISSING else Visibility.AVAILABLE
        return PointValue(status, at, value=entry.value, availability_basis=entry.availability_basis.value, record_id=entry.record_id, **common)

    def latest(self, at: datetime) -> PointValue:
        """The newest reference period visible at T, as known at T."""
        at, refused = self._check(at)
        if refused:
            return refused
        visible = [period for seen, period in self._first_seen if seen <= at]
        if not visible:
            return PointValue(Visibility.NOT_AVAILABLE, at, reason="no period available at this time")
        period = max(visible)
        result = self.value(period, at)
        # Overdue: the next period should have been released by now.
        next_period_end = self.spec.period_end(self.spec.period_end(period))
        overdue_after = self.spec.available_at(next_period_end + self.spec.max_first_release_lag, AvailabilityBasis.END_OF_VINTAGE_DAY)
        return replace(result, stale=True) if at > overdue_after else result

    def visible_records(self, at: datetime) -> tuple[VintageObservation, ...]:
        """Records available at T, as they looked at T.

        A record's vintage_end is only known once the next vintage of its period is
        available; before that it is shown as still current (None)."""
        at = require_utc(at, "at")
        result = []
        for period in self._periods:
            items = self._entries[period]
            for index, entry in enumerate(items):
                if entry.available_at > at or not isinstance(entry, VintageObservation):
                    continue
                successor_known = index + 1 < len(items) and items[index + 1].available_at <= at
                result.append(entry if successor_known else replace(entry, vintage_end=None))
        return tuple(result)

    def visible_unusable(self, at: datetime) -> tuple[Unusable, ...]:
        at = require_utc(at, "at")
        return tuple(item for item in self.ingest.unusable if item.available_at <= at)

    def first_entry(self, period_start: date) -> Entry:
        """The period's earliest archived vintage."""
        return self._entries[period_start][0]

    def entry_in_vintage(self, period_start: date, available_at: datetime) -> Entry | None:
        """The period's entry as of one vintage instant (the newest one at or before it)."""
        items = self._entries.get(period_start)
        if not items:
            return None
        count = bisect_right(self._times[period_start], available_at)
        return items[count - 1] if count else None

    @property
    def periods(self) -> list[date]:
        return list(self._periods)


__all__ = ["DataNotReady", "PointInTimeStore", "PointValue", "Visibility"]
