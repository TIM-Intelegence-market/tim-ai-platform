"""Point-in-time record contract and the registry of known sources.

A record states what a source published for one reference period in one
vintage, and from when TIM may use it (``available_at``). Replay at time T sees
a record only when ``available_at <= T``. A record without a reliable
``available_at`` is rejected at ingestion, never guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from src.quality.framework import QualityIssue, Severity

# Bump when normalization, availability rules or output layout change.
TRANSFORM_VERSION = "1.0.0"


class AvailabilityBasis(StrEnum):
    # The vintage date is a scheduled release date of the publisher; the time of day comes from the source spec.
    SCHEDULED_RELEASE = "SCHEDULED_RELEASE"
    # Time of day unknown: the record counts as known only after its vintage day ended (conservative).
    END_OF_VINTAGE_DAY = "END_OF_VINTAGE_DAY"


class ValueStatus(StrEnum):
    OK = "OK"
    MISSING = "MISSING"  # the source published "no value" for this period in this vintage


class Frequency(StrEnum):
    MONTHLY = "M"


class QualityState(StrEnum):
    READY = "READY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_READY = "NOT_READY"


class UnknownSource(KeyError):
    """Raised for a source that is not in the registry."""


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """Fixed facts about one external series; the parser checks every payload against them."""

    source: str
    source_identifier: str
    data_type: str
    event_type: str
    publisher: str  # primary publisher of the numbers
    distributor: str  # where TIM reads them
    frequency: Frequency
    units: str
    seasonal_adjustment: str
    release_id: int
    release_timezone: str
    release_time: time  # publisher's scheduled release time on a release date
    max_first_release_lag: timedelta  # period end -> first release; a later first vintage means earlier prints are missing
    positive_values: bool = True  # index levels; zero or negative is malformed

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.source_identifier)

    def period_end(self, period_start: date) -> date:
        """Exclusive end of the reference period."""
        if self.frequency is Frequency.MONTHLY:
            if period_start.day != 1:
                raise ValueError("monthly periods start on the first day of the month")
            return date(period_start.year + (period_start.month == 12), period_start.month % 12 + 1, 1)
        raise ValueError(f"unsupported frequency: {self.frequency}")

    def period_of(self, day: date) -> date:
        """Start of the reference period containing ``day``."""
        if self.frequency is Frequency.MONTHLY:
            return day.replace(day=1)
        raise ValueError(f"unsupported frequency: {self.frequency}")

    def previous_period(self, period_start: date) -> date:
        if self.frequency is Frequency.MONTHLY:
            return date(period_start.year - (period_start.month == 1), (period_start.month - 2) % 12 + 1, 1)
        raise ValueError(f"unsupported frequency: {self.frequency}")

    def available_at(self, vintage: date, basis: AvailabilityBasis) -> datetime:
        zone = ZoneInfo(self.release_timezone)
        if basis is AvailabilityBasis.SCHEDULED_RELEASE:
            local = datetime.combine(vintage, self.release_time, tzinfo=zone)
        else:
            local = datetime.combine(vintage + timedelta(days=1), time(0), tzinfo=zone)
        return local.astimezone(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_identifier": self.source_identifier,
            "data_type": self.data_type,
            "event_type": self.event_type,
            "publisher": self.publisher,
            "distributor": self.distributor,
            "frequency": self.frequency.value,
            "units": self.units,
            "seasonal_adjustment": self.seasonal_adjustment,
            "release_id": self.release_id,
            "release_timezone": self.release_timezone,
            "release_time": self.release_time.isoformat(),
            "max_first_release_lag_days": self.max_first_release_lag.days,
            "positive_values": self.positive_values,
        }


# US CPI-U, all items, seasonally adjusted. BLS publishes at 08:30 New York time;
# FRED/ALFRED mirrors it later the same morning and keeps every vintage.
CPI_US = SourceSpec(
    source="ALFRED",
    source_identifier="CPIAUCSL",
    data_type="MACRO_RELEASE",
    event_type="CPI_RELEASE",
    publisher="U.S. Bureau of Labor Statistics",
    distributor="Federal Reserve Bank of St. Louis (ALFRED)",
    frequency=Frequency.MONTHLY,
    units="Index 1982-1984=100",
    seasonal_adjustment="SA",
    release_id=10,
    release_timezone="America/New_York",
    release_time=time(8, 30),
    max_first_release_lag=timedelta(days=45),
)

SOURCES: dict[tuple[str, str], SourceSpec] = {CPI_US.key: CPI_US}


def source_spec(source: str, source_identifier: str) -> SourceSpec:
    try:
        return SOURCES[(source, source_identifier)]
    except KeyError:
        raise UnknownSource(f"{source}:{source_identifier} is not a registered source") from None


def require_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class VintageObservation:
    """One value of one reference period as published in one vintage."""

    source: str
    source_identifier: str
    data_type: str
    period_start: date
    period_end: date  # exclusive
    vintage: date  # ALFRED realtime_start
    vintage_end: date | None  # ALFRED realtime_end, None while current; never used for visibility (it is later knowledge)
    release_time: datetime | None  # set only for scheduled releases
    available_at: datetime
    availability_basis: AvailabilityBasis
    ingested_at: datetime
    value: Decimal | None
    value_status: ValueStatus
    raw_value: str
    payload_sha256: str
    transform_version: str = TRANSFORM_VERSION

    def __post_init__(self) -> None:
        for name in ("available_at", "ingested_at"):
            require_utc(getattr(self, name), name)
        if self.release_time is not None:
            require_utc(self.release_time, "release_time")
        if (self.value is None) != (self.value_status is ValueStatus.MISSING):
            raise ValueError("value and value_status disagree")
        if self.value is not None and not self.value.is_finite():
            raise ValueError("value must be finite")
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")

    @property
    def record_id(self) -> str:
        return f"{self.source}:{self.source_identifier}:{self.period_start.isoformat()}@{self.vintage.isoformat()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source": self.source,
            "source_identifier": self.source_identifier,
            "data_type": self.data_type,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "vintage": self.vintage.isoformat(),
            "vintage_end": self.vintage_end.isoformat() if self.vintage_end else None,
            "release_time": iso(self.release_time),
            "available_at": iso(self.available_at),
            "availability_basis": self.availability_basis.value,
            "ingested_at": iso(self.ingested_at),
            "value": decimal_str(self.value),
            "value_status": self.value_status.value,
            "raw_value": self.raw_value,
            "payload_sha256": self.payload_sha256,
            "transform_version": self.transform_version,
        }


@dataclass(frozen=True, slots=True)
class DatedIssue:
    """A quality issue and, when known, when the record it concerns became available.

    Replay at T reports only issues that are undated (payload-level) or dated at or
    before T, so the issue list cannot reveal later vintages."""

    issue: QualityIssue
    available_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.issue.code,
            "severity": self.issue.severity.value,
            "record_type": self.issue.record_type,
            "record_id": self.issue.record_id,
            "detail": self.issue.detail,
            "available_at": iso(self.available_at),
        }


@dataclass(frozen=True, slots=True)
class Unusable:
    """A period/vintage the source did publish but TIM cannot use (conflicting duplicates, malformed value,
    impossible timing). From its availability on, that period is UNKNOWN; replay never falls back to an older vintage."""

    period_start: date
    vintage: date
    available_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Normalized, quality-checked output of one source payload."""

    spec: SourceSpec
    state: QualityState
    records: tuple[VintageObservation, ...]
    unusable: tuple[Unusable, ...]
    issues: tuple[DatedIssue, ...]
    # Periods whose earliest archived vintage came later than the first release could have: earlier prints are unknown.
    periods_without_first_release: frozenset[date]
    # The archive tells nothing about vintages after this instant (request end or ingestion time).
    coverage_end: datetime
    ingested_at: datetime
    payload_hashes: dict[str, str]
    request: dict[str, Any]


def issue(code: str, severity: Severity, record_id: str, detail: str, available_at: datetime | None = None) -> DatedIssue:
    return DatedIssue(QualityIssue(code, severity, "VintageObservation", record_id, detail), available_at)


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(timezone.utc).isoformat()


def decimal_str(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def ms_to_utc(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def utc_to_ms(value: datetime) -> int:
    return (require_utc(value, "timestamp") - _EPOCH) // timedelta(milliseconds=1)


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


__all__ = [
    "CPI_US",
    "SOURCES",
    "TRANSFORM_VERSION",
    "AvailabilityBasis",
    "DatedIssue",
    "Frequency",
    "IngestResult",
    "QualityState",
    "SourceSpec",
    "UnknownSource",
    "Unusable",
    "ValueStatus",
    "VintageObservation",
    "decimal_str",
    "iso",
    "issue",
    "ms_to_utc",
    "require_utc",
    "source_spec",
    "utc_to_ms",
]
