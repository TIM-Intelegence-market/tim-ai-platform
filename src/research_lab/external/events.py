"""Release events derived from vintages, with room for expectations and surprise.

A release event is a vintage that published a new reference period. ``actual``
is that period's first value in the archive, ``previous`` the prior period as
known just before the release and ``previous_revised`` the same period as
published in this release.

Expectations are never derived or invented. Without a sourced expectation that
was known before the release, ``expected`` and ``surprise`` stay empty and say
why. Nothing here states a direction, cause or trading meaning.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum
from typing import Any

from src.research_lab.external.pit import PointInTimeStore
from src.research_lab.external.records import (
    AvailabilityBasis,
    Unusable,
    ValueStatus,
    VintageObservation,
    decimal_str,
    iso,
    require_utc,
)

CHANGE_QUANTUM = Decimal("0.0001")
# Fixed arithmetic context: results must not depend on the caller's ambient decimal settings.
DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
_JUST_BEFORE = timedelta(microseconds=1)


class EventStatus(StrEnum):
    OK = "OK"
    RELEASE_TIME_UNKNOWN = "RELEASE_TIME_UNKNOWN"  # vintage is not a scheduled release date: no exact event time
    ACTUAL_UNKNOWN = "ACTUAL_UNKNOWN"  # the new period's value is missing or unusable


class Measure(StrEnum):
    LEVEL = "LEVEL"  # compared with ``actual``
    CHANGE_PCT = "CHANGE_PCT"  # compared with ``derived_change_pct``


@dataclass(frozen=True, slots=True)
class Expectation:
    """A sourced expectation (e.g. a survey consensus) and when it was known."""

    value: Decimal
    measure: Measure
    source: str
    source_identifier: str
    available_at: datetime

    def __post_init__(self) -> None:
        require_utc(self.available_at, "available_at")
        if not self.source or not self.source_identifier:
            raise ValueError("an expectation needs a source and a source identifier")
        if not self.value.is_finite():
            raise ValueError("expectation value must be finite")


@dataclass(frozen=True, slots=True)
class ReleaseEvent:
    event_id: str
    event_type: str
    source: str
    source_identifier: str
    status: EventStatus
    event_time: datetime | None  # scheduled release instant; None when unknown
    available_at: datetime
    availability_basis: str
    vintage: date
    reference_period: date
    new_periods: int  # >1 when the vintage published several new periods at once (archive start, delayed releases)
    first_release_in_archive: bool
    actual: Decimal | None
    previous: Decimal | None
    previous_revised: Decimal | None
    revision: Decimal | None
    derived_change_pct: Decimal | None  # actual vs previous_revised, both from this vintage
    expected: Decimal | None = None
    expected_measure: str | None = None
    expected_source: str | None = None
    expected_available_at: datetime | None = None
    surprise: Decimal | None = None
    surprise_status: str = "UNAVAILABLE_NO_EXPECTATION"
    surprise_normalized: Decimal | None = None  # needs a surprise history; not computed here
    record_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "source_identifier": self.source_identifier,
            "status": self.status.value,
            "event_time": iso(self.event_time),
            "available_at": iso(self.available_at),
            "availability_basis": self.availability_basis,
            "vintage": self.vintage.isoformat(),
            "reference_period": self.reference_period.isoformat(),
            "new_periods": self.new_periods,
            "first_release_in_archive": self.first_release_in_archive,
            "actual": decimal_str(self.actual),
            "previous": decimal_str(self.previous),
            "previous_revised": decimal_str(self.previous_revised),
            "revision": decimal_str(self.revision),
            "derived_change_pct": decimal_str(self.derived_change_pct),
            "expected": decimal_str(self.expected),
            "expected_measure": self.expected_measure,
            "expected_source": self.expected_source,
            "expected_available_at": iso(self.expected_available_at),
            "surprise": decimal_str(self.surprise),
            "surprise_status": self.surprise_status,
            "surprise_normalized": decimal_str(self.surprise_normalized),
            "record_ids": list(self.record_ids),
        }


def release_events(store: PointInTimeStore, *, until: datetime) -> tuple[ReleaseEvent, ...]:
    """Every release event available at or before ``until``."""
    until = require_utc(until, "until")
    spec = store.spec
    first_seen: dict[tuple[datetime, date], list[date]] = {}
    for period in store.periods:
        first = store.first_entry(period)
        first_seen.setdefault((first.available_at, first.vintage), []).append(period)
    events = []
    for (available_at, vintage), periods in sorted(first_seen.items()):
        if available_at > until:
            break
        reference = max(periods)
        entry = store.first_entry(reference)
        previous_period = spec.previous_period(reference)
        before = _value(store.entry_in_vintage(previous_period, available_at - _JUST_BEFORE))
        revised = _value(store.entry_in_vintage(previous_period, available_at))
        actual = _value(entry)
        basis = entry.availability_basis if isinstance(entry, VintageObservation) else _basis_of(store, vintage, available_at)
        if actual is None:
            status = EventStatus.ACTUAL_UNKNOWN
        elif basis is not AvailabilityBasis.SCHEDULED_RELEASE:
            status = EventStatus.RELEASE_TIME_UNKNOWN
        else:
            status = EventStatus.OK
        change = None
        with localcontext(DECIMAL_CONTEXT):
            if actual is not None and revised:
                change = ((actual / revised - 1) * 100).quantize(CHANGE_QUANTUM)
            revision = None if before is None or revised is None else revised - before
        record_ids = tuple(
            item.record_id
            for item in (entry, store.entry_in_vintage(previous_period, available_at))
            if isinstance(item, VintageObservation)
        )
        events.append(
            ReleaseEvent(
                event_id=f"{spec.event_type}:{spec.source}:{spec.source_identifier}:{reference.isoformat()}@{vintage.isoformat()}",
                event_type=spec.event_type,
                source=spec.source,
                source_identifier=spec.source_identifier,
                status=status,
                event_time=available_at if basis is AvailabilityBasis.SCHEDULED_RELEASE else None,
                available_at=available_at,
                availability_basis=basis.value,
                vintage=vintage,
                reference_period=reference,
                new_periods=len(periods),
                first_release_in_archive=reference not in store.ingest.periods_without_first_release,
                actual=actual,
                previous=before,
                previous_revised=revised,
                revision=revision,
                derived_change_pct=change,
                record_ids=record_ids,
            )
        )
    return tuple(events)


def with_expectation(event: ReleaseEvent, expectation: Expectation) -> ReleaseEvent:
    """Attach a sourced expectation. It must have been known strictly before the release instant.

    Without a known release time (``event_time``) there is no instant to check
    against, so the expectation is refused rather than compared with the later,
    conservative ``available_at``."""
    if event.event_time is None:
        raise ValueError("release time unknown; an expectation cannot be shown to precede the release")
    if expectation.available_at >= event.event_time:
        raise ValueError("expectation was not available before the release; using it would be lookahead")
    target = event.actual if expectation.measure is Measure.LEVEL else event.derived_change_pct
    with localcontext(DECIMAL_CONTEXT):
        surprise = None if target is None else target - expectation.value
    return replace(
        event,
        expected=expectation.value,
        expected_measure=expectation.measure.value,
        expected_source=f"{expectation.source}:{expectation.source_identifier}",
        expected_available_at=expectation.available_at,
        surprise=surprise,
        surprise_status="OK" if surprise is not None else "UNAVAILABLE_NO_ACTUAL",
    )


def _value(entry: VintageObservation | Unusable | None) -> Decimal | None:
    if isinstance(entry, VintageObservation) and entry.value_status is ValueStatus.OK:
        return entry.value
    return None


def _basis_of(store: PointInTimeStore, vintage: date, available_at: datetime) -> AvailabilityBasis:
    scheduled = store.spec.available_at(vintage, AvailabilityBasis.SCHEDULED_RELEASE)
    return AvailabilityBasis.SCHEDULED_RELEASE if available_at == scheduled else AvailabilityBasis.END_OF_VINTAGE_DAY


__all__ = ["EventStatus", "Expectation", "Measure", "ReleaseEvent", "release_events", "with_expectation"]
