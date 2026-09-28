from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
from typing import Iterable, Sequence


UTC = timezone.utc
ONE_MINUTE = timedelta(minutes=1)


class CoveragePolicyError(ValueError):
    """Raised when a coverage input could weaken or ambiguate the metric."""


def _utc_minute(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CoveragePolicyError(f"{field} must be timezone-aware")
    normalized = value.astimezone(UTC)
    if normalized.second or normalized.microsecond:
        raise CoveragePolicyError(f"{field} must be aligned to a UTC minute")
    return normalized


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class CoverageDefinition:
    metric_name: str
    metric_version: str
    market: str
    instrument: str
    data_type: str
    window_start_utc: datetime
    window_end_utc: datetime
    expected_interval: timedelta = ONE_MINUTE
    target: Decimal = Decimal("0.95")
    closed_only: bool = True

    def __post_init__(self) -> None:
        start = _utc_minute(self.window_start_utc, field="window_start_utc")
        end = _utc_minute(self.window_end_utc, field="window_end_utc")
        if end <= start:
            raise CoveragePolicyError("window_end_utc must be after window_start_utc")
        if self.expected_interval != ONE_MINUTE:
            raise CoveragePolicyError("the authoritative metric interval is fixed at one minute")
        if self.target != Decimal("0.95"):
            raise CoveragePolicyError("the authoritative coverage target is fixed at 0.95")
        if self.market != "BINANCE_SPOT":
            raise CoveragePolicyError("market must remain BINANCE_SPOT")
        if self.instrument != "BTCUSDT":
            raise CoveragePolicyError("instrument must remain BTCUSDT")
        object.__setattr__(self, "window_start_utc", start)
        object.__setattr__(self, "window_end_utc", end)

    @property
    def expected_observations(self) -> int:
        return int((self.window_end_utc - self.window_start_utc) / self.expected_interval)

    def expected_minutes(self) -> tuple[datetime, ...]:
        return tuple(
            self.window_start_utc + index * self.expected_interval
            for index in range(self.expected_observations)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_name": self.metric_name,
            "metric_version": self.metric_version,
            "market": self.market,
            "instrument": self.instrument,
            "data_type": self.data_type,
            "window_start_utc": _iso(self.window_start_utc),
            "window_end_utc": _iso(self.window_end_utc),
            "window_boundary": "START_INCLUSIVE_END_EXCLUSIVE",
            "expected_interval": "PT1M",
            "expected_observations": self.expected_observations,
            "target": float(self.target),
            "closed_only": self.closed_only,
            "excluded_intervals": [],
        }


@dataclass(frozen=True, slots=True)
class CoverageResult:
    definition: CoverageDefinition
    valid_observations: int
    duplicates_excluded: int
    synthetic_observations: int
    invalid_observations: int
    missing_minutes: tuple[datetime, ...]
    coverage: Decimal
    calculation_method: str

    @property
    def status(self) -> str:
        return "PASS" if self.coverage >= self.definition.target else "FAIL"

    def to_dict(self) -> dict[str, object]:
        payload = self.definition.to_dict()
        payload.update(
            {
                "valid_observations": self.valid_observations,
                "duplicates_excluded": self.duplicates_excluded,
                "synthetic_observations": self.synthetic_observations,
                "invalid_observations": self.invalid_observations,
                "missing_observations": len(self.missing_minutes),
                "coverage": float(self.coverage),
                "coverage_percent": format(self.coverage * 100, ".3f"),
                "calculation_method": self.calculation_method,
                "status": self.status,
            }
        )
        payload["result_hash"] = hashlib.sha256(_canonical(payload)).hexdigest()
        return payload


def _normalize_observed(
    definition: CoverageDefinition,
    observed: Iterable[datetime],
) -> tuple[Counter[datetime], int]:
    counts: Counter[datetime] = Counter()
    invalid = 0
    for item in observed:
        try:
            minute = _utc_minute(item, field="observed minute")
        except CoveragePolicyError:
            invalid += 1
            continue
        if not definition.window_start_utc <= minute < definition.window_end_utc:
            invalid += 1
            continue
        counts[minute] += 1
    return counts, invalid


def calculate_coverage(
    definition: CoverageDefinition,
    observed: Iterable[datetime],
    *,
    synthetic: Iterable[datetime] = (),
) -> CoverageResult:
    """Product calculation using a fixed expected-minute set.

    Synthetic, duplicate, misaligned and out-of-window observations never
    increase the numerator.
    """

    counts, invalid = _normalize_observed(definition, observed)
    synthetic_counts, synthetic_invalid = _normalize_observed(definition, synthetic)
    expected = set(definition.expected_minutes())
    synthetic_minutes = set(synthetic_counts)
    valid = set(counts) - synthetic_minutes
    missing = tuple(sorted(expected - valid))
    duplicates = sum(max(0, count - 1) for count in counts.values())
    numerator = len(valid)
    denominator = definition.expected_observations
    coverage = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_EVEN
    )
    return CoverageResult(
        definition=definition,
        valid_observations=numerator,
        duplicates_excluded=duplicates,
        synthetic_observations=len(synthetic_minutes),
        invalid_observations=invalid + synthetic_invalid,
        missing_minutes=missing,
        coverage=coverage,
        calculation_method="PRODUCT_EXPECTED_SET_V1",
    )


def audit_calculate_coverage(
    definition: CoverageDefinition,
    observed: Iterable[datetime],
    *,
    synthetic: Iterable[datetime] = (),
) -> CoverageResult:
    """Independent calculation using a sorted merge against the UTC grid."""

    counts, invalid = _normalize_observed(definition, observed)
    synthetic_counts, synthetic_invalid = _normalize_observed(definition, synthetic)
    synthetic_minutes = set(synthetic_counts)
    actual = sorted(set(counts) - synthetic_minutes)
    missing: list[datetime] = []
    position = 0
    cursor = definition.window_start_utc
    while cursor < definition.window_end_utc:
        while position < len(actual) and actual[position] < cursor:
            position += 1
        if position >= len(actual) or actual[position] != cursor:
            missing.append(cursor)
        else:
            position += 1
        cursor += definition.expected_interval
    denominator = definition.expected_observations
    numerator = denominator - len(missing)
    coverage = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_EVEN
    )
    return CoverageResult(
        definition=definition,
        valid_observations=numerator,
        duplicates_excluded=sum(max(0, count - 1) for count in counts.values()),
        synthetic_observations=len(synthetic_minutes),
        invalid_observations=invalid + synthetic_invalid,
        missing_minutes=tuple(missing),
        coverage=coverage,
        calculation_method="AUDIT_SORTED_MERGE_V1",
    )


def rolling_coverage(
    definition: CoverageDefinition,
    observed: Iterable[datetime],
    durations: Sequence[timedelta],
) -> dict[str, dict[str, object]]:
    observed_values = tuple(observed)
    results: dict[str, dict[str, object]] = {}
    for duration in durations:
        start = max(definition.window_start_utc, definition.window_end_utc - duration)
        minutes = int(duration.total_seconds() // 60)
        label = f"PT{minutes}M"
        child = CoverageDefinition(
            metric_name=f"{definition.metric_name}_rolling_{minutes}m",
            metric_version=definition.metric_version,
            market=definition.market,
            instrument=definition.instrument,
            data_type=definition.data_type,
            window_start_utc=start,
            window_end_utc=definition.window_end_utc,
            target=definition.target,
            closed_only=definition.closed_only,
        )
        scoped_values = tuple(
            item
            for item in observed_values
            if item.tzinfo is not None
            and child.window_start_utc <= item.astimezone(UTC) < child.window_end_utc
        )
        results[label] = calculate_coverage(child, scoped_values).to_dict()
    return results


def _gap_id(
    definition: CoverageDefinition,
    start: datetime,
    end: datetime,
) -> str:
    identity = {
        "source": "BINANCE_SPOT_PUBLIC",
        "market": definition.market,
        "instrument": definition.instrument,
        "data_type": definition.data_type,
        "start_utc": _iso(start),
        "end_utc": _iso(end),
    }
    return "gap-" + hashlib.sha256(_canonical(identity)).hexdigest()[:24]


def _overlaps(
    start: datetime,
    end: datetime,
    intervals: Sequence[tuple[datetime, datetime]],
) -> bool:
    return any(start < other_end and other_start < end for other_start, other_end in intervals)


def build_gap_records(
    definition: CoverageDefinition,
    missing_minutes: Iterable[datetime],
    *,
    raw_minutes: Iterable[datetime] = (),
    confirmed_downtime: Sequence[tuple[datetime, datetime]] = (),
    probable_downtime: Sequence[tuple[datetime, datetime]] = (),
    evidence_refs: Sequence[str] = (),
) -> list[dict[str, object]]:
    """Collapse missing minutes into deterministic, typed gap records."""

    missing = sorted({_utc_minute(item, field="missing minute") for item in missing_minutes})
    raw = {_utc_minute(item, field="raw minute") for item in raw_minutes}
    downtime = tuple(
        (
            value_start.astimezone(UTC),
            value_end.astimezone(UTC),
        )
        for value_start, value_end in confirmed_downtime
    )
    probable = tuple(
        (
            value_start.astimezone(UTC),
            value_end.astimezone(UTC),
        )
        for value_start, value_end in probable_downtime
    )
    ranges: list[tuple[datetime, datetime]] = []
    for minute in missing:
        if not ranges or minute != ranges[-1][1]:
            ranges.append((minute, minute + ONE_MINUTE))
        else:
            ranges[-1] = (ranges[-1][0], minute + ONE_MINUTE)

    records: list[dict[str, object]] = []
    for start, end in ranges:
        expected = int((end - start) / ONE_MINUTE)
        raw_present = sum(
            1 for index in range(expected) if start + index * ONE_MINUTE in raw
        )
        if _overlaps(start, end, downtime):
            root_class = "PROCESS_DOWNTIME"
            root_status = "CONFIRMED"
        elif raw_present:
            root_class = "PARTIAL_WRITE"
            root_status = "PROBABLE"
        elif _overlaps(start, end, probable):
            root_class = "PROCESS_DOWNTIME"
            root_status = "PROBABLE"
        else:
            root_class = "UNKNOWN"
            root_status = "UNKNOWN"
        records.append(
            {
                "gap_id": _gap_id(definition, start, end),
                "source": "BINANCE_SPOT_PUBLIC",
                "market": definition.market,
                "instrument": definition.instrument,
                "data_type": definition.data_type,
                "start_utc": _iso(start),
                "end_utc": _iso(end),
                "duration_seconds": int((end - start).total_seconds()),
                "expected_observations": expected,
                "observed_observations": 0,
                "missing_observations": expected,
                # Missing public market observations invalidate coverage and
                # replay, but do not by themselves prove corruption or a
                # safety breach. Escalation to P0 requires separate evidence.
                "severity": "P1",
                "root_cause_class": root_class,
                "root_cause_status": root_status,
                "repairability": "TECHNICALLY_REPAIRABLE_GOVERNANCE_RESTRICTED",
                "repair_source": None,
                "repair_status": "NOT_ATTEMPTED",
                "raw_minutes_present": raw_present,
                "secondary_root_causes": (
                    ["IN_MEMORY_UNFLUSHED_BUCKET_OR_SCHEMA_REJECTION"]
                    if raw_present and root_class == "PROCESS_DOWNTIME"
                    else []
                ),
                "evidence_refs": list(evidence_refs),
                "notes": "No synthetic, interpolated, forward-filled, cross-market or OHLCV-substitute data may close this gap.",
            }
        )
    return records
