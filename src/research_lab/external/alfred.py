"""ALFRED (FRED's vintage archive, St. Louis Fed) adapter: request layout and payload parsing.

One bundle is three JSON payloads:

- ``series``: series metadata (``fred/series``), checked against the source spec;
- ``observations``: every vintage (``fred/series/observations`` with the full
  real-time range 1776-07-04 .. 9999-12-31, ``units=lin``). Each row is a value
  valid from ``realtime_start`` to ``realtime_end`` (dates, closed interval);
- ``release_dates`` (optional): the publisher's release dates (``fred/release/dates``).

ALFRED vintage dates carry no time of day. A vintage that falls on a release date
becomes available at the publisher's scheduled release time; any other vintage only
after its vintage day ended. ``realtime_end`` is never used for visibility: when a
value stopped being current is known only later.

Parsing never repairs data. A row that cannot be dated makes the whole payload
NOT_READY; a dated row that cannot be used marks its period UNKNOWN from then on.
"""
from __future__ import annotations

import copy
import hashlib
import json
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

from src.quality.framework import Severity
from src.research_lab.external.records import (
    AvailabilityBasis,
    DatedIssue,
    IngestResult,
    QualityState,
    SourceSpec,
    Unusable,
    ValueStatus,
    VintageObservation,
    issue,
    require_utc,
    source_spec,
)

API_BASE = "https://api.stlouisfed.org/fred"
FIRST_REALTIME = "1776-07-04"
LAST_REALTIME = "9999-12-31"
PAGE_LIMIT = 100_000  # observations endpoint maximum
REQUIRED_PAYLOADS = ("series", "observations")
SECRET_KEYS = frozenset({"api_key", "apikey", "token", "password", "secret"})
# Event arithmetic runs in a fixed 28-digit context (events.DECIMAL_CONTEXT). Within these bounds every
# change and revision fits it exactly; a value outside them is malformed rather than a crash later.
MIN_ABS_VALUE = Decimal("1e-6")
MAX_ABS_VALUE = Decimal("1e9")
MAX_DIGITS = 20
NO_CALENDAR ="no release dates: every vintage counts as known only after its vintage day ended and no first print can be identified"

Fetcher = Callable[[str], bytes]
Clock = Callable[[], datetime]


def requests_for(spec: SourceSpec) -> dict[str, dict[str, str]]:
    """Request parameters without the API key; these are what provenance records."""
    full_range = {"realtime_start": FIRST_REALTIME, "realtime_end": LAST_REALTIME}
    return {
        "series": {"path": "series", "series_id": spec.source_identifier},
        "observations": {
            "path": "series/observations",
            "series_id": spec.source_identifier,
            **full_range,
            "units": "lin",
            "output_type": "1",
            "sort_order": "asc",
            "limit": str(PAGE_LIMIT),
        },
        "release_dates": {
            "path": "release/dates",
            "release_id": str(spec.release_id),
            **full_range,
            "include_release_dates_with_no_data": "false",
            "sort_order": "asc",
            "limit": "10000",
        },
    }


def url_for(request: dict[str, str], api_key: str) -> str:
    params = {key: value for key, value in request.items() if key != "path"}
    return f"{API_BASE}/{request['path']}?{urlencode({**params, 'file_type': 'json', 'api_key': api_key})}"


@dataclass(frozen=True, slots=True)
class RawBundle:
    source: str
    source_identifier: str
    payloads: dict[str, bytes]
    ingested_at: datetime
    requests: dict[str, dict[str, str]] = field(default_factory=dict)


def fetch_bundle(spec: SourceSpec, *, api_key: str, fetcher: Fetcher, clock: Clock) -> RawBundle:
    """Download one bundle. The key goes into the URL only, never into the bundle or its provenance."""
    if not api_key:
        raise ValueError("an ALFRED API key is required to download")
    requests = requests_for(spec)
    payloads = {name: fetcher(url_for(request, api_key)) for name, request in requests.items()}
    # Taken after the last download, so every payload was received at or before ingested_at.
    ingested_at = require_utc(clock(), "clock()")
    return RawBundle(spec.source, spec.source_identifier, payloads, ingested_at, requests)


def reject_credentials(requests: dict[str, dict[str, str]]) -> None:
    for request in requests.values():
        leaked = SECRET_KEYS & {key.lower() for key in request}
        if leaked:
            raise ValueError(f"request parameters must not contain credentials: {sorted(leaked)}")


def parse_bundle(bundle: RawBundle) -> IngestResult:
    spec = source_spec(bundle.source, bundle.source_identifier)
    ingested_at = require_utc(bundle.ingested_at, "ingested_at")
    reject_credentials(bundle.requests)
    request = copy.deepcopy(bundle.requests)  # the result must not change when the caller's dict does
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(bundle.payloads.items())}
    series_id = f"{spec.source}:{spec.source_identifier}"
    issues: list[DatedIssue] = []

    def not_ready(code: str, detail: str) -> IngestResult:
        issues.append(issue(code, Severity.ERROR, series_id, detail))
        return IngestResult(spec, QualityState.NOT_READY, (), (), _sorted(issues), frozenset(), ingested_at, ingested_at, hashes, request)

    missing = [name for name in REQUIRED_PAYLOADS if name not in bundle.payloads]
    if missing:
        return not_ready("MISSING_PAYLOAD", f"missing payload(s): {', '.join(missing)}")
    try:
        series = json.loads(bundle.payloads["series"])
        observations = json.loads(bundle.payloads["observations"])
    except (UnicodeDecodeError, ValueError) as exc:
        return not_ready("MALFORMED_PAYLOAD", f"payload is not valid JSON: {exc.__class__.__name__}")
    problem = _metadata_problem(spec, series, observations)
    if problem:
        return not_ready("INCONSISTENT_METADATA", problem)

    release_dates: set[date] = set()
    if "release_dates" not in bundle.payloads:
        issues.append(issue("RELEASE_CALENDAR_UNAVAILABLE", Severity.WARNING, series_id, NO_CALENDAR))
    else:
        try:
            release_dates = _release_dates(spec, json.loads(bundle.payloads["release_dates"]))
        except (UnicodeDecodeError, ValueError, TypeError, KeyError) as exc:
            return not_ready("MALFORMED_PAYLOAD", f"release dates unusable: {exc}")
        if not release_dates:
            issues.append(issue("RELEASE_CALENDAR_UNAVAILABLE", Severity.WARNING, series_id, NO_CALENDAR))

    request_start = _date(observations["realtime_start"])
    clipped_start = None if observations["realtime_start"] == FIRST_REALTIME else request_start
    coverage_end = ingested_at
    if observations["realtime_end"] != LAST_REALTIME:
        # The request end date is inclusive: coverage ends just before the next day starts.
        day_after = spec.available_at(_date(observations["realtime_end"]), AvailabilityBasis.END_OF_VINTAGE_DAY)
        coverage_end = min(ingested_at, day_after - timedelta(microseconds=1))

    entries: dict[tuple[date, date], list[VintageObservation | Unusable]] = defaultdict(list)
    bad_ends: list[tuple[date, date, str]] = []
    undatable = 0
    for index, row in enumerate(observations["observations"]):
        entry = _row(spec, index, row, release_dates, clipped_start, ingested_at, hashes["observations"], issues, bad_ends)
        if entry is None:
            undatable += 1
        else:
            entries[(entry.period_start, entry.vintage)].append(entry)
    if undatable:
        return not_ready("UNDATABLE_ROWS", f"{undatable} row(s) without a usable period or vintage date; availability cannot be established")
    request_end = _date(observations["realtime_end"])
    outside = sum(1 for _period, vintage in entries if not request_start <= vintage <= request_end)
    if outside:
        # The envelope's range sets coverage and clipping; rows contradicting it make both untrustworthy.
        return not_ready("INCONSISTENT_METADATA", f"{outside} vintage(s) outside the declared real-time range")

    records: list[VintageObservation] = []
    unusable: list[Unusable] = []
    for (period, vintage), items in sorted(entries.items()):
        record_id = f"{series_id}:{period.isoformat()}@{vintage.isoformat()}"
        bad = sorted((item for item in items if isinstance(item, Unusable)), key=lambda item: item.reason)
        good = sorted((item for item in items if isinstance(item, VintageObservation)), key=lambda item: item.raw_value)
        values = {(item.value_status, item.value) for item in good}
        ends = {item.vintage_end for item in items}
        if len(ends) > 1:
            # Rows disagree on the end date: the end is unknown (see _row), never picked by row order.
            bad_ends.append((period, vintage, "duplicate rows disagree on realtime_end"))
        end = next(iter(ends)) if len(ends) == 1 else None
        if bad:
            unusable.append(replace(bad[0], vintage_end=end))
        elif len(values) > 1:
            unusable.append(Unusable(period, vintage, items[0].available_at, "CONFLICTING_DUPLICATE", end))
            issues.append(issue("CONFLICTING_DUPLICATE", Severity.ERROR, record_id, f"{len(items)} rows with different values", items[0].available_at))
        else:
            # Same value in every row: the representative does not depend on row order.
            records.append(replace(good[0], vintage_end=end))
            if len(items) > 1:
                issues.append(issue("DUPLICATE_RECORD", Severity.WARNING, record_id, f"{len(items)} identical rows; kept one", items[0].available_at))

    records, unusable = _vintage_chain_checks(records, unusable, issues)
    _missing_successors(spec, records, unusable, request_end, release_dates, issues)
    _date_bad_ends(series_id, bad_ends, records, unusable, ingested_at, issues)
    without_first = _revision_history_gaps(spec, records, unusable, clipped_start, release_dates, issues)
    missing_periods = _missing_periods(spec, records, unusable, release_dates, coverage_end, issues)
    state = QualityState.READY if records or unusable else QualityState.INSUFFICIENT_DATA
    if state is QualityState.INSUFFICIENT_DATA:
        issues.append(issue("NO_OBSERVATIONS", Severity.ERROR, series_id, "payload holds no usable observation"))
    return IngestResult(
        spec,
        state,
        tuple(records),
        tuple(sorted(unusable, key=lambda item: (item.period_start, item.vintage))),
        _sorted(issues),
        frozenset(without_first),
        coverage_end,
        ingested_at,
        hashes,
        request,
        missing_periods,
    )


def _sorted(issues: list[DatedIssue]) -> tuple[DatedIssue, ...]:
    """Issue order must not depend on row order."""
    return tuple(sorted(issues, key=lambda item: (item.available_at is not None, item.available_at or datetime.min, item.issue.record_id, item.issue.code, item.issue.detail)))


def _metadata_problem(spec: SourceSpec, series: Any, observations: Any) -> str | None:
    if not isinstance(series, dict) or not isinstance(series.get("seriess"), list) or len(series["seriess"]) != 1:
        return "series payload must describe exactly one series"
    meta = series["seriess"][0]
    if not isinstance(meta, dict):
        return "series metadata is not an object"
    expected = {
        "id": spec.source_identifier,
        "frequency_short": spec.frequency.value,
        "units": spec.units,
        "seasonal_adjustment_short": spec.seasonal_adjustment,
    }
    for key, value in expected.items():
        if meta.get(key) != value:
            return f"series {key} is {meta.get(key)!r}, expected {value!r}"
    if not isinstance(observations, dict) or not isinstance(observations.get("observations"), list):
        return "observations payload has no observation list"
    if observations.get("units") != "lin":
        return f"observations are transformed (units={observations.get('units')!r}); only levels are accepted"
    if observations.get("output_type") != 1:
        # Other output types drop vintages (4 = initial release only) or change the row meaning.
        return f"observations output_type is {observations.get('output_type')!r}; only 1 (real-time periods) keeps every vintage"
    count = observations.get("count")
    if not isinstance(count, int) or count != len(observations["observations"]) or observations.get("offset", 0) != 0:
        return f"payload holds {len(observations['observations'])} of {count} observations (paging is not supported)"
    for key in ("realtime_start", "realtime_end"):
        try:
            _date(observations.get(key))
        except (TypeError, ValueError):
            return f"observations {key} is not a date"
    if observations["realtime_start"] > observations["realtime_end"]:  # ISO dates compare as strings
        return "observations realtime_start is after realtime_end"
    return None


def _release_dates(spec: SourceSpec, payload: Any) -> set[date]:
    if not isinstance(payload, dict) or not isinstance(payload.get("release_dates"), list):
        raise ValueError("release dates payload has no release_dates list")
    count = payload.get("count")
    if not isinstance(count, int) or count != len(payload["release_dates"]) or payload.get("offset", 0) != 0:
        # A truncated calendar would silently turn scheduled releases into end-of-day vintages.
        raise ValueError(f"release calendar holds {len(payload['release_dates'])} of {count} dates (paging is not supported)")
    result = set()
    for item in payload["release_dates"]:
        if int(item["release_id"]) != spec.release_id:
            raise ValueError(f"release id {item['release_id']} does not match {spec.release_id}")
        result.add(_date(item["date"]))
    return result


def _row(
    spec: SourceSpec,
    index: int,
    row: Any,
    release_dates: set[date],
    clipped_start: date | None,
    ingested_at: datetime,
    payload_sha256: str,
    issues: list[DatedIssue],
    bad_ends: list[tuple[date, date, str]],
) -> VintageObservation | Unusable | None:
    """Normalize one row; None means it cannot be dated at all."""
    row_id = f"{spec.source}:{spec.source_identifier}:row{index}"
    if not isinstance(row, dict):
        issues.append(issue("MALFORMED_RECORD", Severity.ERROR, row_id, "row is not an object"))
        return None
    if row.get("realtime_start") in (None, ""):
        issues.append(issue("MISSING_AVAILABLE_AT", Severity.ERROR, row_id, "row has no realtime_start"))
        return None
    try:
        vintage = _date(row["realtime_start"])
        raw_period = _date(row["date"])
    except (KeyError, TypeError, ValueError) as exc:
        issues.append(issue("MALFORMED_TIMESTAMP", Severity.ERROR, row_id, f"unusable date field: {exc.__class__.__name__}"))
        return None

    clipped = clipped_start is not None and vintage == clipped_start
    basis = AvailabilityBasis.SCHEDULED_RELEASE if vintage in release_dates and not clipped else AvailabilityBasis.END_OF_VINTAGE_DAY
    try:
        period = spec.period_of(raw_period)
        period_end = spec.period_end(period)
        available_at = spec.available_at(vintage, basis)
        # Every later step's period arithmetic must be representable too: the first-print check, the
        # previous period of a release event and the staleness deadline of PointInTimeStore.latest.
        _ = period_end + spec.max_first_release_lag
        spec.previous_period(period)
        spec.available_at(spec.period_end(period_end) + spec.max_first_release_lag, AvailabilityBasis.END_OF_VINTAGE_DAY)
    except (ValueError, OverflowError):
        # Dates at the calendar's edge (e.g. period 9999-12) have no representable end or availability.
        issues.append(issue("MALFORMED_TIMESTAMP", Severity.ERROR, row_id, "date outside the supported range"))
        return None
    # The row is datable from here on: every later defect is dated at this vintage's availability.
    record_id = f"{spec.source}:{spec.source_identifier}:{period.isoformat()}@{vintage.isoformat()}"

    # realtime_end says when this value stopped being current, which is only known once the next
    # vintage exists. A bad end is therefore not held against this row; it is treated as unknown and
    # the vintage chain check makes the next vintage of the period UNKNOWN from that vintage on.
    end_raw = row.get("realtime_end")
    try:
        vintage_end = None if end_raw == LAST_REALTIME else _date(end_raw)
    except ValueError:
        vintage_end = None
        bad_ends.append((period, vintage, "realtime_end is not a date"))
    if vintage_end is not None and vintage_end < vintage:
        vintage_end = None
        bad_ends.append((period, vintage, "realtime_end before realtime_start"))

    def unusable(code: str, detail: str) -> Unusable:
        issues.append(issue(code, Severity.ERROR, record_id, detail, available_at))
        return Unusable(period, vintage, available_at, code, vintage_end)

    if raw_period != period:
        return unusable("MALFORMED_TIMESTAMP", "observation date is not the start of a reference period")
    if vintage < period_end:
        return unusable("IMPOSSIBLE_TIMESTAMP_ORDER", "vintage dated before the reference period ended")
    if available_at > ingested_at:
        return unusable("FUTURE_DATA", "record claims availability after it was ingested")
    raw_value = row.get("value")
    if not isinstance(raw_value, str):
        return unusable("MALFORMED_VALUE", "value is not a string")
    if raw_value.strip() == ".":
        value, status = None, ValueStatus.MISSING
    else:
        try:
            value = Decimal(raw_value.strip())
        except InvalidOperation:
            return unusable("MALFORMED_VALUE", "value is not a number")
        if not value.is_finite():
            return unusable("MALFORMED_VALUE", "value is not finite")
        if spec.positive_values and value <= 0:
            return unusable("MALFORMED_VALUE", "value must be positive for this series")
        # copy_abs and comparisons are exact: no ambient context can overflow on extreme exponents.
        if (value and not MIN_ABS_VALUE <= value.copy_abs() <= MAX_ABS_VALUE) or len(value.as_tuple().digits) > MAX_DIGITS:
            return unusable("MALFORMED_VALUE", "value outside the supported range or precision")
        status = ValueStatus.OK
    if status is ValueStatus.MISSING:
        issues.append(issue("MISSING_VALUE", Severity.WARNING, record_id, "source published no value", available_at))
    if clipped:
        issues.append(issue("REVISION_HISTORY_UNAVAILABLE", Severity.WARNING, record_id, "vintage clipped to the request start; earlier vintages not requested", available_at))
    return VintageObservation(
        source=spec.source,
        source_identifier=spec.source_identifier,
        data_type=spec.data_type,
        period_start=period,
        period_end=period_end,
        vintage=vintage,
        vintage_end=vintage_end,
        release_time=available_at if basis is AvailabilityBasis.SCHEDULED_RELEASE else None,
        available_at=available_at,
        availability_basis=basis,
        ingested_at=ingested_at,
        value=value,
        value_status=status,
        raw_value=raw_value,
        payload_sha256=payload_sha256,
    )


def _revision_history_gaps(
    spec: SourceSpec,
    records: list[VintageObservation],
    unusable: list[Unusable],
    clipped_start: date | None,
    release_dates: set[date],
    issues: list[DatedIssue],
) -> set[date]:
    """Periods whose first print is not in the archive.

    The lag bound can only disprove a first print. With a release calendar the first
    print must also be positively identified: the earliest archived vintage has to be
    the first scheduled release after the period ended, otherwise an earlier release
    is missing (or the calendar does not show it) and the first print counts as unknown.
    Without calendar dates no first print can be identified at all."""
    first: dict[date, VintageObservation | Unusable] = {}
    for item in [*records, *unusable]:
        if item.period_start not in first or item.vintage < first[item.period_start].vintage:
            first[item.period_start] = item
    calendar = sorted(release_dates)
    gaps = set()
    for period, item in sorted(first.items()):
        period_end = spec.period_end(period)
        latest_first_release = period_end + spec.max_first_release_lag
        record_id = f"{spec.source}:{spec.source_identifier}:{period.isoformat()}@{item.vintage.isoformat()}"
        detail = None
        if item.vintage > latest_first_release:
            detail = "earliest archived vintage is later than the first release could have been"
        elif calendar:
            position = bisect_left(calendar, period_end)
            expected = calendar[position] if position < len(calendar) else None
            if position == 0:
                # No release before the period ended: the calendar may start too late to show the first print.
                detail = "release calendar does not reach back to the end of the reference period"
            elif expected is not None and expected - calendar[position - 1] > spec.max_release_interval:
                # A gap wider than one release interval may hide the release that first printed the period.
                detail = "release calendar has a gap around the first release"
            elif item.vintage != expected:
                detail = "earliest archived vintage is not the first scheduled release after the period ended"
        if detail is not None or not calendar or (clipped_start is not None and item.vintage == clipped_start):
            gaps.add(period)
        if detail is not None:
            issues.append(issue("REVISION_HISTORY_UNAVAILABLE", Severity.WARNING, record_id, detail, item.available_at))
    return gaps


def _vintage_chain_checks(
    records: list[VintageObservation],
    unusable: list[Unusable],
    issues: list[DatedIssue],
) -> tuple[list[VintageObservation], list[Unusable]]:
    """Overlapping real-time periods assert two values at once: the later vintage becomes UNKNOWN.

    The conflict is only knowable once the later vintage exists, so marking it from
    that vintage's own availability on uses no later knowledge. Unusable entries take
    part as earlier vintages: a bad value still claims its validity period."""
    by_period: dict[date, list[VintageObservation | Unusable]] = defaultdict(list)
    for item in [*records, *unusable]:
        by_period[item.period_start].append(item)
    kept: list[VintageObservation] = []
    for _period, items in sorted(by_period.items()):
        items.sort(key=lambda item: item.vintage)
        for position, current in enumerate(items):
            if not isinstance(current, VintageObservation):
                continue
            if position == 0:
                kept.append(current)
                continue
            # Every earlier vintage, not only the adjacent one, must have ended before this one starts.
            if any(earlier.vintage_end is None or earlier.vintage_end >= current.vintage for earlier in items[:position]):
                issues.append(issue("INCONSISTENT_VINTAGE_CHAIN", Severity.ERROR, current.record_id, "an earlier vintage is still valid when this one starts", current.available_at))
                unusable.append(Unusable(current.period_start, current.vintage, current.available_at, "INCONSISTENT_VINTAGE_CHAIN", current.vintage_end))
            else:
                kept.append(current)
    return sorted(kept, key=lambda item: (item.period_start, item.vintage)), unusable


def _missing_periods(
    spec: SourceSpec,
    records: list[VintageObservation],
    unusable: list[Unusable],
    release_dates: set[date],
    coverage_end: datetime,
    issues: list[DatedIssue],
) -> tuple[tuple[date, datetime], ...]:
    """Periods a calendar release should have published but the archive lacks entirely.

    A release date d publishes the period whose first scheduled release after its end is d
    (the month before d's month for CPI). Everything is judged as known at the release: the
    period is missing when none of its vintages was available by then, and only once an older
    period was already available (the archive had started). Later vintages cannot erase it;
    it ends when the period's first vintage becomes visible."""
    first_available: dict[date, datetime] = {}
    for item in [*records, *unusable]:
        if item.period_start not in first_available or item.available_at < first_available[item.period_start]:
            first_available[item.period_start] = item.available_at
    if not first_available or not release_dates:
        return ()
    calendar = sorted(release_dates)
    missing = []
    for release in calendar:
        try:
            period = spec.previous_period(spec.period_of(release))
            period_end = spec.period_end(period)
            due = spec.available_at(release, AvailabilityBasis.SCHEDULED_RELEASE)
        except (ValueError, OverflowError):
            continue
        if due > coverage_end or first_available.get(period, datetime.max.replace(tzinfo=due.tzinfo)) <= due:
            continue
        if not any(older < period and seen <= due for older, seen in first_available.items()):
            continue  # the archive had not started yet
        if calendar[bisect_left(calendar, period_end)] != release:
            continue  # this release published another period
        record_id = f"{spec.source}:{spec.source_identifier}:{period.isoformat()}@{release.isoformat()}"
        issues.append(issue("MISSING_PERIOD", Severity.ERROR, record_id, "the release calendar shows this period's release but the archive has no vintage of it", due))
        missing.append((period, due))
    return tuple(missing)


def _missing_successors(
    spec: SourceSpec,
    records: list[VintageObservation],
    unusable: list[Unusable],
    request_end: date,
    release_dates: set[date],
    issues: list[DatedIssue],
) -> None:
    """A vintage that ended without a successor starting the next day leaves its period unknown.

    The missing vintage would have started the day after realtime_end; from the instant it
    would have become available (same rule as a real vintage) the period is UNKNOWN, so the
    expired value is not carried forward and earlier replays are unchanged. A row ending on
    the request's last day is clipped by the request, not ended."""
    starts: dict[date, set[date]] = defaultdict(set)
    for item in [*records, *unusable]:
        starts[item.period_start].add(item.vintage)
    for item in sorted([*records, *unusable], key=lambda item: (item.period_start, item.vintage)):
        end = item.vintage_end
        if end is None or end >= request_end:
            continue
        successor = end + timedelta(days=1)
        if any(start <= successor for start in starts[item.period_start] if start > item.vintage):
            continue  # the next vintage starts on time (or overlaps, which the chain check handles)
        basis = AvailabilityBasis.SCHEDULED_RELEASE if successor in release_dates else AvailabilityBasis.END_OF_VINTAGE_DAY
        try:
            available_at = spec.available_at(successor, basis)
        except OverflowError:
            continue  # the successor could never become available in any representable replay
        record_id = f"{spec.source}:{spec.source_identifier}:{item.period_start.isoformat()}@{successor.isoformat()}"
        issues.append(issue("MISSING_VINTAGE", Severity.ERROR, record_id, f"vintage {item.vintage.isoformat()} ended {end.isoformat()} and no vintage starts the next day", available_at))
        unusable.append(Unusable(item.period_start, successor, available_at, "MISSING_VINTAGE"))
        starts[item.period_start].add(successor)


def _date_bad_ends(
    series_id: str,
    bad_ends: list[tuple[date, date, str]],
    records: list[VintageObservation],
    unusable: list[Unusable],
    ingested_at: datetime,
    issues: list[DatedIssue],
) -> None:
    """Report an unusable realtime_end when it becomes knowable: with the period's next vintage, else at ingestion."""
    for period, vintage, detail in sorted(set(bad_ends)):
        later = [item.available_at for item in [*records, *unusable] if item.period_start == period and item.vintage > vintage]
        record_id = f"{series_id}:{period.isoformat()}@{vintage.isoformat()}"
        issues.append(issue("MALFORMED_TIMESTAMP", Severity.ERROR, record_id, detail, min(later) if later else ingested_at))


def _date(value: Any) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError(f"not a YYYY-MM-DD date: {value!r}")
    return date.fromisoformat(value)


__all__ = ["API_BASE", "FIRST_REALTIME", "LAST_REALTIME", "RawBundle", "fetch_bundle", "parse_bundle", "requests_for", "url_for"]
