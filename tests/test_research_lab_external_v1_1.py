"""BTC Research Engine V1.1: live ingest, holdout-safe research window, real-data fixture, expectation bounds.

Synthetic payloads reuse the helpers of tests/test_research_lab_external.py (made-up values).
The real-data tests read tests/fixtures/research_lab/alfred_cpiaucsl_fixture_2019_2020, an
unmodified ALFRED download (see its provenance.json). No test needs the network.
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.research_lab.data.parse import Kline
from src.research_lab.data.store import HoldoutLocked
from src.research_lab.external.alfred import parse_bundle
from src.research_lab.external.align import BtcSeries, align_event
from src.research_lab.external.events import Expectation, Measure, release_events, with_expectation
from src.research_lab.external.fixture_window import FIXTURE_2019_2020, FIXTURE_DIR, load_fixture
from src.research_lab.external.fred_secret import FILE_ENV, KEY_ENV, PROVIDER_ENV, FredSecretError, FredSecretResolver
from src.research_lab.external.live import (
    RESEARCH_2017_2024,
    LiveIngestError,
    ResearchWindow,
    _NoRedirect,
    http_fetcher,
    ingest_live,
    load_research_ingest,
    research_requests,
)
from src.research_lab.external.pit import PointInTimeStore, Visibility
from src.research_lab.external.realcheck import as_of, leakage, reordered
from src.research_lab.external.records import CPI_US, QualityState, iso
from src.research_lab.external.replay import ReplayConfig, run_replay
from src.research_lab.external.store import RawPayloadStore
from src.research_lab.external.verify import raw_summary
from tests.test_research_lab_external import (
    INGESTED,
    MAR_RELEASE,
    base_rows,
    bundle,
    codes,
    klines,
    release_payload,
    row,
    store,
)

UTC = timezone.utc
FEB_RELEASE_V1 = datetime(2024, 2, 13, 13, 30, tzinfo=UTC)  # synthetic V1 fixture: January first print


def with_envelope(raw, **envelope: str):
    observations = json.loads(raw.payloads["observations"])
    observations.update(envelope)
    raw.payloads["observations"] = json.dumps(observations).encode()
    return raw


# --- declared observation range (defect found while preparing the real-data fixture) ---------


def test_periods_outside_the_requested_observation_range_are_not_missing() -> None:
    raw = bundle()
    raw.payloads["release_dates"] = release_payload(("2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10", "2024-05-15"))
    result = parse_bundle(with_envelope(raw, observation_start="2024-01-01", observation_end="2024-03-31"))
    assert result.state is QualityState.READY
    # 2024-05-15 releases April, which was never requested: no gap in the archive.
    assert "MISSING_PERIOD" not in codes(result)
    assert result.missing_periods == ()


def test_periods_inside_the_requested_range_are_still_missing() -> None:
    raw = bundle()
    raw.payloads["release_dates"] = release_payload(("2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10", "2024-05-15"))
    result = parse_bundle(with_envelope(raw, observation_start="2024-01-01", observation_end="2024-04-30"))
    assert [period for period, _due in result.missing_periods] == [date(2024, 4, 1)]


@pytest.mark.parametrize(
    "envelope",
    [
        {"observation_start": "2024-02-01", "observation_end": "2024-03-31"},  # January row outside
        {"observation_start": "2024-01-01", "observation_end": "2024-02-29"},  # March rows outside
        {"observation_start": "2024-13-01", "observation_end": "2024-03-31"},
        {"observation_start": "2024-03-31", "observation_end": "2024-01-01"},
    ],
)
def test_rows_contradicting_the_observation_range_are_not_ready(envelope) -> None:
    result = parse_bundle(with_envelope(bundle(), **envelope))
    assert result.state is QualityState.NOT_READY and codes(result) == ["INCONSISTENT_METADATA"]


# --- series metadata in real-time versions (defect found with the real ALFRED response) -----


def meta(start: str, end: str, **changes: str) -> dict:
    base = {"id": "CPIAUCSL", "frequency_short": "M", "units": "Index 1982-1984=100", "seasonal_adjustment_short": "SA"}
    return {**base, "realtime_start": start, "realtime_end": end, **changes}


def with_series(raw, *versions: dict):
    raw.payloads["series"] = json.dumps({"realtime_start": "1776-07-04", "realtime_end": "9999-12-31", "seriess": list(versions)}).encode()
    return raw


def test_metadata_versions_before_the_archived_vintages_do_not_matter() -> None:
    # As in the real response: units were "Index 1967=100" until 1988, long before any row here.
    raw = with_series(bundle(), meta("1972-07-21", "1988-02-25", units="Index 1967=100"), meta("1988-02-26", "2019-09-11"), meta("2019-09-12", "9999-12-31", title="renamed"))
    assert parse_bundle(raw).state is QualityState.READY


def test_metadata_version_contradicting_archived_vintages_makes_them_unknown() -> None:
    # Scoped in time (see test_later_metadata_contradiction_does_not_change_an_earlier_replay): every
    # vintage published under the NSA version is UNKNOWN, earlier ones are untouched.
    raw = with_series(bundle(), meta("1988-02-26", "2024-03-01"), meta("2024-03-02", "9999-12-31", seasonal_adjustment_short="NSA"))
    result = parse_bundle(raw)
    assert result.state is QualityState.READY
    assert {issue.issue.record_id for issue in result.issues if issue.issue.code == "INCONSISTENT_METADATA"} == {
        "ALFRED:CPIAUCSL:2024-01-01@2024-03-12",
        "ALFRED:CPIAUCSL:2024-02-01@2024-03-12",
        "ALFRED:CPIAUCSL:2024-03-01@2024-04-10",
        "ALFRED:CPIAUCSL:2024-03-01@2024-05-15",
    }
    assert {record.vintage for record in result.records} == {date(2024, 2, 13)}


def test_older_metadata_version_overlapping_archived_vintages_must_match_too() -> None:
    # Vintages start 2024-02-13; the older version is still in force then and has other units.
    raw = with_series(bundle(), meta("1988-02-26", "2024-03-11", units="Index 1967=100"), meta("2024-03-12", "9999-12-31"))
    result = parse_bundle(raw)
    pit = PointInTimeStore(result)
    assert pit.value(date(2024, 1, 1), FEB_RELEASE_V1).status is Visibility.UNKNOWN  # first print under the old units
    assert pit.value(date(2024, 1, 1), MAR_RELEASE).value == Decimal("300.2")  # revision under the matching version


@pytest.mark.parametrize(
    "versions",
    [
        (meta("1988-02-26", "2024-01-31"), meta("2024-03-01", "9999-12-31")),  # gap in the metadata's real time
        (meta("1988-02-26", "2024-03-01"), meta("2024-02-01", "9999-12-31")),  # overlap
        (meta("2024-03-01", "9999-12-31"),),  # vintages from 2024-02-13 have no metadata
        (meta("1988-02-26", "bad"),),
        ({"id": "CPIAUCSL", "frequency_short": "M"}, meta("2019-09-12", "9999-12-31")),  # version without real time
    ],
)
def test_metadata_versions_must_cover_the_archived_vintages_without_gaps(versions) -> None:
    result = parse_bundle(with_series(bundle(), *versions))
    assert result.state is QualityState.NOT_READY and codes(result) == ["INCONSISTENT_METADATA"]


# --- revision-only release dates (defect found with the real ALFRED calendar) ---------------
# Real pattern: each February the FRED CPI calendar holds the BLS seasonal-revision date (only older
# periods are revised) a few days before the January release (e.g. 2024-02-09 and 2024-02-13).

SEASONAL_REVISION = "2024-02-09"


def seasonal_rows() -> list[dict]:
    return [
        row("2023-12-01", "2024-01-11", "2024-02-08", "300.0"),
        row("2023-12-01", "2024-02-09", "9999-12-31", "299.8"),  # seasonal revision only
        row("2024-01-01", "2024-02-13", "9999-12-31", "301.0"),  # the January first print
    ]


def seasonal_bundle(dates=("2023-12-12", "2024-01-11", SEASONAL_REVISION, "2024-02-13")):
    raw = bundle(seasonal_rows())
    raw.payloads["release_dates"] = release_payload(dates)
    return raw


def test_revision_only_date_is_not_the_first_release_of_the_period() -> None:
    result = parse_bundle(seasonal_bundle())
    assert date(2024, 1, 1) not in result.periods_without_first_release
    assert "MISSING_PERIOD" not in codes(result)
    events = release_events(PointInTimeStore(result), until=INGESTED)
    january = next(e for e in events if e.reference_period == date(2024, 1, 1))
    assert january.status.value == "OK" and january.event_time == datetime(2024, 2, 13, 13, 30, tzinfo=UTC)


def test_revision_only_vintages_have_no_release_time() -> None:
    # BLS states a date but no time for revised seasonal factors: visible only after that New York day.
    result = parse_bundle(seasonal_bundle())
    revised = next(r for r in result.records if r.vintage == date(2024, 2, 9))
    assert revised.availability_basis.value == "END_OF_VINTAGE_DAY" and revised.release_time is None
    assert revised.available_at == datetime(2024, 2, 10, 5, 0, tzinfo=UTC)
    pit = PointInTimeStore(result)
    assert pit.value(date(2023, 12, 1), datetime(2024, 2, 9, 20, 0, tzinfo=UTC)).value == Decimal("300.0")
    assert pit.value(date(2023, 12, 1), datetime(2024, 2, 10, 5, 0, tzinfo=UTC)).value == Decimal("299.8")


def test_a_revision_is_no_first_print_when_the_first_print_is_missing() -> None:
    # December's first print (2024-01-11) is missing from the archive: its 2024-02-09 vintage is the
    # seasonal revision, which has no stated time, not a release at 08:30.
    raw = bundle(seasonal_rows()[1:])
    raw.payloads["release_dates"] = release_payload(("2023-12-12", "2024-01-11", SEASONAL_REVISION, "2024-02-13"))
    result = parse_bundle(raw)
    revised = next(r for r in result.records if r.vintage == date(2024, 2, 9))
    assert revised.availability_basis.value == "END_OF_VINTAGE_DAY" and revised.release_time is None
    assert revised.available_at == datetime(2024, 2, 10, 5, 0, tzinfo=UTC)
    assert date(2023, 12, 1) in result.periods_without_first_release
    assert PointInTimeStore(result).value(date(2023, 12, 1), datetime(2024, 2, 9, 14, 0, tzinfo=UTC)).value is None


@pytest.mark.parametrize(
    "unusable",
    [
        row("2024-02-01", SEASONAL_REVISION, "9999-12-31", "302.0"),  # vintage before February ended
        row("2024-01-02", SEASONAL_REVISION, "9999-12-31", "302.0"),  # not the start of a period
        row("2024-01-01", SEASONAL_REVISION, "2024-02-12", "garbage"),  # value is not a number
    ],
    ids=["impossible", "malformed-period", "malformed-value"],
)
def test_an_unusable_row_is_no_first_print(unusable: dict) -> None:
    # Rows _row rejects must not make the seasonal revision date look like a release that first
    # printed a period.
    raw = bundle([*seasonal_rows(), unusable])
    raw.payloads["release_dates"] = release_payload(("2023-12-12", "2024-01-11", SEASONAL_REVISION, "2024-02-13"))
    result = parse_bundle(raw)
    revised = next(r for r in result.records if r.vintage == date(2024, 2, 9))
    assert revised.availability_basis.value == "END_OF_VINTAGE_DAY"
    assert PointInTimeStore(result).value(date(2023, 12, 1), datetime(2024, 2, 9, 14, 0, tzinfo=UTC)).value == Decimal("300.0")


def test_a_replay_past_the_coverage_end_shows_nothing_dated_after_it() -> None:
    # Archive downloaded 2024-02-11 holding only December's 2024-02-09 vintage: whether that date was a
    # revision cannot be told yet, so coverage ends before it. No event or record may show it early.
    raw = with_envelope(bundle([row("2023-12-01", SEASONAL_REVISION, "2024-02-11", "299.8")]), realtime_end="2024-02-11")
    raw.payloads["release_dates"] = release_payload(("2023-12-12", "2024-01-11", SEASONAL_REVISION))
    ingest_result = parse_bundle(raw)
    assert ingest_result.coverage_end < datetime(2024, 2, 9, 13, 30, tzinfo=UTC)
    result = run_replay(ingest_result, klines(datetime(2024, 2, 8, tzinfo=UTC), 24), ReplayConfig(datetime(2024, 2, 9, 14, 0, tzinfo=UTC)))
    assert result["state"] == "INSUFFICIENT_DATA"
    assert result["events"] == [] and result["inputs"]["external_record_ids"] == []
    assert all(item["available_at"] is None or item["available_at"] <= iso(ingest_result.coverage_end) for item in result["quality_issues"])
    # The public point-in-time queries keep the same cut.
    pit, at = PointInTimeStore(ingest_result), datetime(2024, 2, 9, 14, 0, tzinfo=UTC)
    assert pit.visible_records(at) == () and pit.visible_unusable(at) == () and release_events(pit, until=at) == ()
    assert pit.entry_in_vintage(date(2023, 12, 1), at) is None


def test_revisions_without_a_release_right_after_do_not_hide_a_missing_period() -> None:
    # Revisions on 2024-02-09 but no January and no release within a week: a normal release whose
    # period is missing, exactly as V1 judged it (due at the release, 08:30 New York).
    rows = seasonal_rows()[:2]
    raw = bundle(rows)
    raw.payloads["release_dates"] = release_payload(("2023-12-12", "2024-01-11", SEASONAL_REVISION, "2024-03-12"))
    result = parse_bundle(raw)
    assert result.missing_periods == (
        (date(2024, 1, 1), datetime(2024, 2, 9, 13, 30, tzinfo=UTC)),
        (date(2024, 2, 1), datetime(2024, 3, 12, 12, 30, tzinfo=UTC)),
    )
    revised = next(r for r in result.records if r.vintage == date(2024, 2, 9))
    assert revised.availability_basis.value == "SCHEDULED_RELEASE"


def early_archive(cut: str):
    """The archive as a download with realtime_end=cut returns it (FRED lists only dates with data)."""
    dates = tuple(d for d in ("2023-12-12", "2024-01-11", SEASONAL_REVISION, "2024-02-13") if d <= cut)
    raw = with_envelope(seasonal_bundle(dates=dates), realtime_end=cut)
    body = json.loads(raw.payloads["observations"])
    body["observations"] = [dict(r, realtime_end=min(r["realtime_end"], cut)) for r in body["observations"] if r["realtime_start"] <= cut]
    body["count"] = len(body["observations"])
    raw.payloads["observations"] = json.dumps(body).encode()
    return parse_bundle(raw)


def test_archive_ending_inside_the_lead_cannot_answer_after_the_revision_date() -> None:
    # Downloaded 2024-02-11: whether 2024-02-09 was a revision date or a release missing its period is
    # not knowable yet. The answer must not depend on the download date: the archive ends before 2024-02-09.
    full, early = parse_bundle(seasonal_bundle()), early_archive("2024-02-11")
    assert early.missing_periods == () and full.missing_periods == ()
    assert early.coverage_end == datetime(2024, 2, 9, 13, 30, tzinfo=UTC) - timedelta(microseconds=1)
    candles = klines(datetime(2024, 2, 1, tzinfo=UTC), 24 * 12)
    before = ReplayConfig(datetime(2024, 2, 9, 12, 0, tzinfo=UTC))
    assert run_replay(full, candles, before)["content_hash"] == run_replay(early, candles, before)["content_hash"]
    after = ReplayConfig(datetime(2024, 2, 11, 20, 0, tzinfo=UTC))
    early_after, full_after = run_replay(early, candles, after), run_replay(full, candles, after)
    assert early_after["state"] == "INSUFFICIENT_DATA" and early_after["latest"]["status"] == "INSUFFICIENT_DATA"
    assert full_after["latest"]["value"] == "299.8"


def test_archive_ending_after_the_lead_answers_like_the_full_archive() -> None:
    later = early_archive("2024-02-16")  # the 2024-02-13 release is in it
    assert later.coverage_end > datetime(2024, 2, 13, tzinfo=UTC) and later.missing_periods == ()


def test_a_release_date_without_any_archived_row_still_counts_as_missing() -> None:
    rows = seasonal_rows()[:2]  # the January release is absent from the archive
    raw = bundle(rows)
    raw.payloads["release_dates"] = release_payload(("2023-12-12", "2024-01-11", SEASONAL_REVISION, "2024-02-13"))
    result = parse_bundle(raw)
    assert [period for period, _ in result.missing_periods] == [date(2024, 1, 1)]


# --- expectation bounds (overflow deferred from V1) ---------------------------------------


def feb_event():
    return release_events(store(), until=INGESTED)[1]


def expectation(value) -> Expectation:
    return Expectation(value, Measure.CHANGE_PCT, "SURVEY", "cpi_mom", MAR_RELEASE - timedelta(days=1))


@pytest.mark.parametrize("raw", ["1e1000000", "-1e1000000", "1e-1000000", "1e10", "0.0000000000001", "123456789012345678901"])
def test_extreme_expectations_are_refused_before_any_arithmetic(raw: str) -> None:
    with pytest.raises(ValueError):
        expectation(Decimal(raw))


def test_non_decimal_expectations_are_refused() -> None:
    for value in (0.3, 3, True, "0.3"):
        with pytest.raises(ValueError):
            expectation(value)


@pytest.mark.parametrize("raw", ["0.3", "-0.1", "0", "0.25", "3.4", "312.5", "1e9", "-1e9", "0.000000000001"])
def test_realistic_and_boundary_expectations_still_attach(raw: str) -> None:
    event = with_expectation(feb_event(), expectation(Decimal(raw)))
    assert event.surprise == event.derived_change_pct - Decimal(raw)
    assert event.surprise_status == "OK"


def test_existing_surprise_value_is_unchanged() -> None:
    assert with_expectation(feb_event(), expectation(Decimal("0.3"))).surprise == Decimal("-0.0335")


def test_inexact_surprise_is_refused_not_rounded() -> None:
    # Inside the series bounds (20 digits, >= 1e-6) but 25 decimal places: actual - 999999999 needs 34 digits.
    tiny = "0.0000012345678901234567890"
    rows = base_rows()
    rows[2] = row("2024-02-01", "2024-03-12", "9999-12-31", tiny)
    event = release_events(PointInTimeStore(parse_bundle(bundle(rows))), until=INGESTED)[1]
    assert event.actual == Decimal(tiny)
    level = Expectation(Decimal("999999999"), Measure.LEVEL, "SURVEY", "cpi_level", MAR_RELEASE - timedelta(days=1))
    with pytest.raises(ValueError, match="not exactly representable"):
        with_expectation(event, level)


# --- real ALFRED data (tests/fixtures/research_lab/alfred_cpiaucsl_fixture_2019_2020) --------
# Real values from the fixture: Nov 2019 first print 257.936 (2019-12-11), seasonal revision to
# 257.824 on 2020-02-11 (revision-only date, no stated time: visible from 2020-02-12 00:00 New York);
# Dec 2019 258.501 (2020-01-14) -> 258.444; Jan 2020 first print 258.820 (2020-02-13).

NOV_2019, DEC_2019, JAN_2020 = date(2019, 11, 1), date(2019, 12, 1), date(2020, 1, 1)
NOV_FIRST_PRINT = datetime(2019, 12, 11, 13, 30, tzinfo=UTC)  # 08:30 EST
REVISION_VISIBLE = datetime(2020, 2, 12, 5, 0, tzinfo=UTC)  # end of 2020-02-11 in New York
JAN_RELEASE = datetime(2020, 2, 13, 13, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def real():
    raw, provenance = load_fixture()
    return raw, provenance, parse_bundle(raw)


def test_fixture_is_byte_identical_to_the_recorded_download(real, tmp_path) -> None:
    raw, provenance, ingest = real
    assert provenance["source"] == "ALFRED" and provenance["source_identifier"] == "CPIAUCSL"
    assert provenance["requests"] == research_requests(CPI_US, FIXTURE_2019_2020)
    assert all("api_key" not in request for request in provenance["requests"].values())
    assert ingest.state is QualityState.READY and ingest.issues == ()
    copy_dir = tmp_path / "fixture"
    copy_dir.mkdir()
    for path in FIXTURE_DIR.iterdir():
        (copy_dir / path.name).write_bytes(path.read_bytes())
    observations = copy_dir / "observations.json"
    observations.write_bytes(observations.read_bytes().replace(b"257.936", b"257.937"))
    with pytest.raises(ValueError, match="differs from the recorded download"):
        load_fixture(copy_dir)


def test_fixture_holds_no_holdout_data(real) -> None:
    raw, _provenance, _ingest = real
    for name, payload in raw.payloads.items():
        body = json.loads(payload)
        dates = [item["date"] for item in body.get("release_dates", [])]
        dates += [row[key] for row in body.get("observations", []) for key in ("date", "realtime_start", "realtime_end")]
        dates += [meta["realtime_end"] for meta in body.get("seriess", [])]
        assert dates and max(dates) < "2025-01-01", name


def test_real_first_print_is_invisible_before_and_visible_from_the_release(real) -> None:
    pit = PointInTimeStore(real[2])
    assert pit.value(NOV_2019, NOV_FIRST_PRINT - timedelta(microseconds=1)).status is Visibility.NOT_AVAILABLE
    first = pit.value(NOV_2019, NOV_FIRST_PRINT)
    assert first.status is Visibility.AVAILABLE and first.value == Decimal("257.936") and first.revision_number == 0


def test_real_revision_is_visible_only_from_its_own_vintage(real) -> None:
    pit = PointInTimeStore(real[2])
    assert pit.value(NOV_2019, REVISION_VISIBLE - timedelta(microseconds=1)).value == Decimal("257.936")
    assert pit.value(DEC_2019, REVISION_VISIBLE - timedelta(microseconds=1)).value == Decimal("258.501")
    revised = pit.value(NOV_2019, REVISION_VISIBLE)
    assert revised.value == Decimal("257.824") and revised.revision_number == 1
    assert pit.value(DEC_2019, REVISION_VISIBLE).value == Decimal("258.444")


def test_real_release_events(real) -> None:
    events = {event.reference_period: event for event in release_events(PointInTimeStore(real[2]), until=datetime(2020, 12, 31, tzinfo=UTC))}
    assert set(events) == {NOV_2019, DEC_2019, JAN_2020}  # the seasonal revision date is no release event
    january = events[JAN_2020]
    assert january.status.value == "OK" and january.event_time == JAN_RELEASE
    assert january.actual == Decimal("258.820")
    # Dec 2019 as known just before the January release already includes the 2020-02-11 revision.
    assert (january.previous, january.previous_revised, january.revision) == (Decimal("258.444"), Decimal("258.444"), Decimal("0.000"))
    december = events[DEC_2019]
    assert (december.actual, december.previous, december.event_time) == (Decimal("258.501"), Decimal("257.936"), datetime(2020, 1, 14, 13, 30, tzinfo=UTC))


def test_real_replay_before_the_revision_is_unchanged_by_it(real) -> None:
    raw, _provenance, ingest = real
    candles = klines(datetime(2020, 1, 20, tzinfo=UTC), 24 * 14)
    at = datetime(2020, 2, 1, tzinfo=UTC)
    full = run_replay(ingest, candles, ReplayConfig(at))
    archive_then = run_replay(parse_bundle(as_of(raw, date(2020, 1, 31))), candles, ReplayConfig(at))
    assert full["content_hash"] == archive_then["content_hash"] and full["dataset_id"] == archive_then["dataset_id"]
    assert "257.824" not in json.dumps({key: value for key, value in full.items() if key != "provenance"})
    assert leakage(full, at) == []


def test_real_replay_repeats_byte_for_byte_and_ignores_row_order(real) -> None:
    raw, _provenance, ingest = real
    candles = klines(datetime(2020, 2, 10, tzinfo=UTC), 24 * 10)
    config = ReplayConfig(datetime(2020, 2, 20, tzinfo=UTC))
    first, second = run_replay(ingest, candles, config), run_replay(parse_bundle(raw), candles, config)
    assert (first["dataset_id"], first["content_hash"], first["output_hash"]) == (second["dataset_id"], second["content_hash"], second["output_hash"])
    shuffled = run_replay(parse_bundle(reordered(raw)), candles, config)
    assert (shuffled["dataset_id"], shuffled["content_hash"]) == (first["dataset_id"], first["content_hash"])
    assert first["latest"]["value"] == "258.820" and leakage(first, config.replay_at) == []


# --- defective real BTC candles (found in the Binance spot 1h archive 2017-2024) -------------
# Real archive: 15 candles with an irregular span (one closing before it opens, 2020-12-21) and 43 off
# the hourly grid (e.g. opening 2018-02-11T03:28:14.789Z). Shapes reproduced synthetically here.

def defective_candles():
    good = klines(datetime(2024, 2, 13, tzinfo=UTC), 24)
    short = Kline(good[14].open_time, 1.0, 1.0, 1.0, 1.0, 0.0, good[14].open_time + 793_524, 0.0)  # truncated span
    backwards = Kline(good[15].open_time, 1.0, 1.0, 1.0, 1.0, 0.0, good[15].open_time - 759_479, 0.0)  # closes before it opens
    off_grid = Kline(good[16].open_time + 1_694_789, 2.0, 2.0, 2.0, 2.0, 1.0, good[17].open_time - 1, 0.0)
    return good[:14] + [short, backwards, off_grid] + good[17:], (good[14].open_time, good[15].open_time, good[16].open_time + 1_694_789)


def test_defective_candles_still_abort_by_default() -> None:
    candles, _ = defective_candles()
    with pytest.raises(ValueError):
        BtcSeries.build(candles, "1h", replay_at=INGESTED)


def test_research_replay_can_exclude_defective_candles_explicitly() -> None:
    candles, bad = defective_candles()
    btc = BtcSeries.build(candles, "1h", replay_at=INGESTED, invalid_candles="exclude")
    assert [item["open_time_ms"] for item in btc.excluded] == list(bad)
    assert {item["reason"] for item in btc.excluded} == {"WRONG_SPAN", "OFF_GRID"}
    assert len(btc.klines) == 21 and all(k.open_time not in bad for k in btc.klines)
    event = release_events(store(), until=INGESTED)[0]  # released 2024-02-13 13:30 UTC
    windows = align_event(event, btc, replay_at=INGESTED, horizons=("4h",))["windows"]
    # The 4h window after the 13:30 release spans the 14:00, 15:00 and 16:00 candles: all three are excluded.
    assert windows["4h"]["status"] == "INSUFFICIENT_DATA" and windows["4h"]["present_candles"] == 0
    assert align_event(event, btc, replay_at=INGESTED, horizons=("24h",))["windows"]["24h"]["status"] == "INSUFFICIENT_DATA"


def test_excluded_candles_are_part_of_the_dataset_identity() -> None:
    candles, _bad = defective_candles()
    at = datetime(2024, 2, 20, tzinfo=UTC)
    config = ReplayConfig(at, invalid_candles="exclude")
    with_defects = run_replay(parse_bundle(bundle()), candles, config)
    without = run_replay(parse_bundle(bundle()), [c for c in candles if c.open_time % 3_600_000 == 0 and c.close_time == c.open_time + 3_599_999], config)
    assert with_defects["inputs"]["btc_excluded"] and with_defects["dataset_id"] != without["dataset_id"]
    assert with_defects["config"]["invalid_candles"] == "exclude"
    default = run_replay(parse_bundle(bundle()), [c for c in candles if c.open_time % 3_600_000 == 0 and c.close_time == c.open_time + 3_599_999], ReplayConfig(at))
    assert "invalid_candles" not in default["config"] and "btc_excluded" not in default["inputs"]


@pytest.mark.parametrize("defect", ["WRONG_SPAN", "OFF_GRID"])
@pytest.mark.parametrize("edge", [0, 2])
def test_excluded_edge_candles_count_as_missing(edge: int, defect: str) -> None:
    good = klines(datetime(2024, 2, 13, tzinfo=UTC), 3)
    candles = list(good)
    if defect == "WRONG_SPAN":
        candles[edge] = Kline(good[edge].open_time, 1.0, 1.0, 1.0, 1.0, 0.0, good[edge].open_time + 1_000, 0.0)
    else:  # opens 28 minutes into its slot, as in the real Binance archive; the slot itself stays empty
        shifted = good[edge].open_time + 1_694_789
        candles[edge] = Kline(shifted, 2.0, 2.0, 2.0, 2.0, 1.0, shifted + 3_599_999, 0.0)
    btc = BtcSeries.build(candles, "1h", replay_at=INGESTED, invalid_candles="exclude")
    assert btc.gaps() == {"expected": 3, "present": 2, "missing": 1}


def test_unknown_candle_policy_is_refused() -> None:
    with pytest.raises(ValueError):
        ReplayConfig(INGESTED, invalid_candles="repair")


# --- secret resolution ----------------------------------------------------------------------

KEY = "0123456789abcdef0123456789abcdef"  # made-up key in FRED's documented shape


def test_resolver_needs_an_explicit_provider() -> None:
    with pytest.raises(FredSecretError, match="not set"):
        FredSecretResolver({}).api_key()
    with pytest.raises(FredSecretError, match="unsupported"):
        FredSecretResolver({PROVIDER_ENV: "clipboard"}).api_key()
    assert FredSecretResolver({}).configured() is False


def test_resolver_env_provider_and_value_is_never_printed() -> None:
    secret = FredSecretResolver({PROVIDER_ENV: "env", KEY_ENV: KEY}).api_key()
    assert secret.reveal() == KEY and KEY not in repr(secret) and KEY not in str(secret)


@pytest.mark.parametrize("bad", ["", "short", KEY.upper(), KEY + "0", KEY[:-1] + " ", "ä" * 32])
def test_malformed_keys_are_explained_by_counts_only(bad: str) -> None:
    with pytest.raises(FredSecretError) as raised:
        FredSecretResolver({PROVIDER_ENV: "env", KEY_ENV: bad}).api_key()
    if bad.strip():
        assert bad.strip() not in str(raised.value)


def test_resolver_file_provider_requires_a_private_file(tmp_path) -> None:
    path = tmp_path / "fred-api-key"
    path.write_text(KEY + "\n")
    path.chmod(0o644)
    with pytest.raises(FredSecretError, match="0600"):
        FredSecretResolver({PROVIDER_ENV: "file", FILE_ENV: str(path)}).api_key()
    path.chmod(0o600)
    assert FredSecretResolver({PROVIDER_ENV: "file", FILE_ENV: str(path)}).api_key().reveal() == KEY


def test_store_key_script_writes_a_private_file_and_prints_only_the_last_four(tmp_path, capsys) -> None:
    from scripts.fred_store_key import main

    target = tmp_path / "TIM" / "fred-api-key"
    assert main(["--file", str(target)], prompt=lambda _text: KEY) == 0
    assert target.read_text() == KEY and oct(target.stat().st_mode & 0o777) == "0o600"
    printed = capsys.readouterr().out
    assert KEY not in printed and "****cdef" in printed
    assert main(["--file", str(target)], prompt=lambda _text: "not-a-key") == 2
    assert target.read_text() == KEY  # unchanged


# --- research window, live ingest, fetcher --------------------------------------------------


def research_payloads(window: ResearchWindow = RESEARCH_2017_2024, *, rows=None, calendar=None, **envelope) -> dict[str, bytes]:
    end = window.realtime_end.isoformat()
    rows = rows if rows is not None else [
        row("2016-01-01", "2016-02-19", "2017-02-14", "237.0"),
        row("2016-01-01", "2017-02-15", end, "237.1"),
    ]
    observations = {
        "realtime_start": "1776-07-04", "realtime_end": end, "observation_start": window.observation_start.isoformat(),
        "observation_end": window.observation_end.isoformat(), "units": "lin", "output_type": 1, "offset": 0,
        "count": len(rows), "limit": 100000, "observations": rows, **envelope,
    }
    dates = calendar if calendar is not None else ["2016-02-19", "2017-02-15"]
    return {
        "series": json.dumps({"realtime_start": "1776-07-04", "realtime_end": end, "seriess": [
            {"id": "CPIAUCSL", "frequency_short": "M", "units": "Index 1982-1984=100", "seasonal_adjustment_short": "SA",
             "realtime_start": "1776-07-04", "realtime_end": end}]}).encode(),
        "series/observations": json.dumps(observations).encode(),
        "release/dates": json.dumps({"realtime_start": "1776-07-04", "realtime_end": end, "offset": 0, "count": len(dates),
                                     "release_dates": [{"release_id": 10, "date": d} for d in dates]}).encode(),
    }


class FakeApi:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return self.payloads[url.split("/fred/", 1)[1].split("?", 1)[0]]


def live(tmp_path, payloads: dict[str, bytes]):
    api = FakeApi(payloads)
    store = RawPayloadStore(tmp_path / "raw")
    resolver = FredSecretResolver({PROVIDER_ENV: "env", KEY_ENV: KEY})
    return api, store, lambda window=RESEARCH_2017_2024: ingest_live(window, resolver=resolver, store=store, fetcher=api, clock=lambda: INGESTED)


def stored_files(store: RawPayloadStore) -> list:
    return sorted(path for path in store.root.rglob("*") if path.is_file()) if store.root.exists() else []


def test_research_window_requests_end_before_the_holdout() -> None:
    requests = research_requests(CPI_US, RESEARCH_2017_2024)
    assert {request["realtime_end"] for request in requests.values()} == {"2024-12-31"}
    assert requests["observations"]["observation_end"] == "2024-12-31"
    assert all("api_key" not in request for request in requests.values())


@pytest.mark.parametrize("end", [date(2025, 1, 1), date(2026, 9, 30), date(9999, 12, 31)])
def test_windows_reaching_the_holdout_cannot_be_built(end: date) -> None:
    with pytest.raises(HoldoutLocked):
        ResearchWindow("x", date(2016, 1, 1), date(2024, 12, 31), end)


def test_live_ingest_stores_raw_payloads_without_the_key(tmp_path) -> None:
    api, store, run = live(tmp_path, research_payloads())
    bundle_id = run()
    assert len(api.urls) == 3 and all(f"api_key={KEY}" in url for url in api.urls)
    for path in stored_files(store):
        assert KEY not in path.read_text(errors="replace")
    raw, ingest = load_research_ingest(store, bundle_id, RESEARCH_2017_2024)
    assert ingest.state is QualityState.READY
    assert raw.requests == research_requests(CPI_US, RESEARCH_2017_2024)


def test_stored_bundles_are_reused_without_network(tmp_path) -> None:
    api, store, run = live(tmp_path, research_payloads())
    bundle_id = run()
    calls = len(api.urls)
    first = load_research_ingest(store, bundle_id, RESEARCH_2017_2024)[1]
    second = load_research_ingest(store, bundle_id, RESEARCH_2017_2024)[1]
    assert len(api.urls) == calls and first == second


@pytest.mark.parametrize(
    "mutation",
    [
        {"rows": [row("2016-01-01", "2025-01-15", "9999-12-31", "237.0")]},  # holdout vintage
        {"rows": [row("2025-01-01", "2024-12-31", "9999-12-31", "237.0")]},  # period after the window
        {"realtime_end": "9999-12-31"},  # API ignored the requested real-time end
        {"observation_end": "2025-12-31"},
        {"calendar": ["2016-02-19", "2025-01-15"]},  # holdout release date
    ],
)
def test_responses_reaching_past_the_window_are_refused_and_never_stored(tmp_path, mutation) -> None:
    _api, store, run = live(tmp_path, research_payloads(**mutation))
    with pytest.raises(LiveIngestError):
        run()
    assert stored_files(store) == []


def test_bundle_from_another_window_is_refused_on_load(tmp_path) -> None:
    _api, store, run = live(tmp_path, research_payloads(FIXTURE_2019_2020, rows=[row("2019-11-01", "2019-12-11", "2020-12-31", "257.9")], calendar=["2019-12-11"]))
    bundle_id = run(FIXTURE_2019_2020)
    with pytest.raises(LiveIngestError):
        load_research_ingest(store, bundle_id, RESEARCH_2017_2024)


@pytest.mark.parametrize("payload", [b"<html>rate limited</html>", b"", b'{"error_code": 400, "error_message": "Bad Request"}'])
def test_malformed_live_responses_are_refused_and_never_stored(tmp_path, payload: bytes) -> None:
    payloads = research_payloads()
    payloads["series/observations"] = payload
    _api, store, run = live(tmp_path, payloads)
    with pytest.raises(LiveIngestError):
        run()
    assert stored_files(store) == []


def test_partial_page_is_not_ready_after_storage(tmp_path) -> None:
    # A truncated page is inside the window, so it is stored as received; the parser refuses it.
    _api, store, run = live(tmp_path, research_payloads(count=99))
    bundle_id = run()
    assert load_research_ingest(store, bundle_id, RESEARCH_2017_2024)[1].state is QualityState.NOT_READY


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, limit: int = -1) -> bytes:
        return self.body if limit < 0 else self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def opener_from(outcomes: list):
    calls = []

    def open_url(request, timeout):
        calls.append(request.full_url)
        outcome = outcomes[min(len(calls), len(outcomes)) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(outcome)

    return open_url, calls


URL = f"https://api.stlouisfed.org/fred/series?series_id=CPIAUCSL&file_type=json&api_key={KEY}"


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, code, f"error with {URL}", {}, None)


def test_fetcher_retries_rate_limits_and_server_errors_with_backoff() -> None:
    sleeps: list[float] = []
    open_url, calls = opener_from([http_error(429), http_error(503), b"{}"])
    assert http_fetcher(opener=open_url, sleep=sleeps.append)(URL) == b"{}"
    assert len(calls) == 3 and sleeps == [2.0, 4.0]


@pytest.mark.parametrize("failure", [http_error(400), http_error(403), http_error(310)])
def test_fetcher_does_not_retry_client_errors_and_never_shows_the_key(failure) -> None:
    sleeps: list[float] = []
    open_url, calls = opener_from([failure])
    with pytest.raises(LiveIngestError) as raised:
        http_fetcher(opener=open_url, sleep=sleeps.append)(URL)
    assert len(calls) == 1 and sleeps == []
    assert KEY not in str(raised.value) and "api_key" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__


def test_fetcher_gives_up_after_the_last_attempt() -> None:
    open_url, calls = opener_from([urllib.error.URLError(f"down {URL}")])
    with pytest.raises(LiveIngestError, match="network error after 4") as raised:
        http_fetcher(opener=open_url, sleep=lambda _s: None)(URL)
    assert len(calls) == 4 and KEY not in str(raised.value)


def test_fetcher_refuses_other_hosts_and_oversized_responses(monkeypatch) -> None:
    with pytest.raises(LiveIngestError, match="outside the FRED API"):
        http_fetcher(opener=opener_from([b"{}"])[0])(f"https://evil.example/fred/series?api_key={KEY}")
    monkeypatch.setattr("src.research_lab.external.live.MAX_RESPONSE_BYTES", 10)
    with pytest.raises(LiveIngestError, match="larger than"):
        http_fetcher(opener=opener_from([b"x" * 11])[0])(URL)


def test_redirects_are_refused_by_the_real_opener() -> None:
    handler = _NoRedirect()
    with pytest.raises(urllib.error.HTTPError) as raised:
        handler.redirect_request(urllib.request.Request(URL), None, 302, "Found", {}, "https://elsewhere.example/")
    assert KEY not in str(raised.value) and raised.value.filename == ""


def test_credentials_in_request_parameters_are_refused_before_any_download() -> None:
    from src.research_lab.external.alfred import fetch_bundle

    calls: list[str] = []
    leaky = research_requests(CPI_US, RESEARCH_2017_2024)
    leaky["series"]["api_key"] = KEY
    with pytest.raises(ValueError, match="credentials"):
        fetch_bundle(CPI_US, api_key=KEY, fetcher=lambda url: calls.append(url) or b"{}", clock=lambda: INGESTED, requests=leaky)
    assert calls == []


def test_download_errors_never_carry_the_key(tmp_path) -> None:
    def failing(url: str) -> bytes:
        raise RuntimeError(f"boom {url}")

    store = RawPayloadStore(tmp_path / "raw")
    resolver = FredSecretResolver({PROVIDER_ENV: "env", KEY_ENV: KEY})
    with pytest.raises(LiveIngestError) as raised:
        ingest_live(RESEARCH_2017_2024, resolver=resolver, store=store, fetcher=failing, clock=lambda: INGESTED)
    assert KEY not in str(raised.value) and raised.value.__cause__ is None
    assert stored_files(store) == []


def test_corrupted_stored_payload_is_refused(tmp_path) -> None:
    _api, store, run = live(tmp_path, research_payloads())
    bundle_id = run()
    payload = next(path for path in stored_files(store) if "payloads" in path.parts)
    payload.write_bytes(payload.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed on disk"):
        load_research_ingest(store, bundle_id, RESEARCH_2017_2024)


# --- regressions from the independent review of V1.1 -----------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        {"rows": [row("2016-01-01", "2016-02-19", "2025-02-12", "237.0")]},  # row end in the holdout
    ],
)
def test_row_end_dates_past_the_window_are_refused(tmp_path, mutation) -> None:
    _api, store, run = live(tmp_path, research_payloads(**mutation))
    with pytest.raises(LiveIngestError):
        run()
    assert stored_files(store) == []


@pytest.mark.parametrize("field", ["realtime_end", "observation_end", "last_updated"])
def test_metadata_dates_past_the_window_are_refused(tmp_path, field: str) -> None:
    payloads = research_payloads()
    series = json.loads(payloads["series"])
    series["seriess"][-1][field] = "2025-03-01" if field != "last_updated" else "2025-03-01 07:41:02-06"
    payloads["series"] = json.dumps(series).encode()
    _api, store, run = live(tmp_path, payloads)
    with pytest.raises(LiveIngestError):
        run()
    assert stored_files(store) == []


def test_later_metadata_contradiction_does_not_change_an_earlier_replay() -> None:
    # Vintages from 2024-02-13; a metadata version from 2024-03-12 on says NSA. Before that date the
    # archive must answer exactly as one without the later version and vintages.
    later = with_series(bundle(), meta("1988-02-26", "2024-03-11"), meta("2024-03-12", "9999-12-31", seasonal_adjustment_short="NSA"))
    result = parse_bundle(later)
    assert result.state is QualityState.READY and "INCONSISTENT_METADATA" in codes(result)
    pit = PointInTimeStore(result)
    assert pit.value(date(2024, 1, 1), MAR_RELEASE - timedelta(seconds=1)).value == Decimal("300.0")
    assert pit.value(date(2024, 1, 1), MAR_RELEASE).status is Visibility.UNKNOWN
    early_rows = [r for r in base_rows() if r["realtime_start"] < "2024-03-12"]
    early_rows = [dict(r, realtime_end="2024-03-01") for r in early_rows]
    early = with_series(bundle(early_rows, end="2024-03-01"), meta("1988-02-26", "2024-03-01"))
    at = datetime(2024, 2, 20, tzinfo=UTC)
    candles = klines(datetime(2024, 2, 12, tzinfo=UTC), 24 * 7)
    assert run_replay(result, candles, ReplayConfig(at))["content_hash"] == run_replay(parse_bundle(early), candles, ReplayConfig(at))["content_hash"]


@pytest.mark.parametrize("bad", [[], {}, 7, None])
def test_malformed_period_dates_are_not_ready_not_a_crash(bad) -> None:
    rows = base_rows()
    rows[0] = dict(rows[0], date=bad)
    result = parse_bundle(bundle(rows))
    assert result.state is QualityState.NOT_READY and "UNDATABLE_ROWS" in codes(result)


def test_fetch_errors_keep_no_exception_context_with_the_key(tmp_path) -> None:
    def failing(url: str) -> bytes:
        raise RuntimeError(f"request failed {url}")

    store = RawPayloadStore(tmp_path / "raw")
    resolver = FredSecretResolver({PROVIDER_ENV: "env", KEY_ENV: KEY})
    with pytest.raises(LiveIngestError) as raised:
        ingest_live(RESEARCH_2017_2024, resolver=resolver, store=store, fetcher=failing, clock=lambda: INGESTED)
    chain, error = [], raised.value
    while error is not None:
        chain.append(error)
        error = error.__cause__ or error.__context__
    assert len(chain) == 1 and KEY not in repr(chain)


@pytest.mark.parametrize("failure", [http_error(400), http_error(503), urllib.error.URLError(f"down {URL}")])
def test_fetcher_errors_keep_no_exception_context(failure) -> None:
    open_url, _calls = opener_from([failure])
    with pytest.raises(LiveIngestError) as raised:
        http_fetcher(opener=open_url, sleep=lambda _s: None, attempts=1)(URL)
    assert raised.value.__context__ is None and raised.value.__cause__ is None


def test_fixture_bundle_identity_is_recomputed(tmp_path) -> None:
    copy_dir = tmp_path / "fixture"
    copy_dir.mkdir()
    for path in FIXTURE_DIR.iterdir():
        (copy_dir / path.name).write_bytes(path.read_bytes())
    series = copy_dir / "series.json"
    series.write_bytes(series.read_bytes() + b" ")
    provenance = json.loads((copy_dir / "provenance.json").read_text())
    provenance["payload_sha256"]["series"] = hashlib.sha256(series.read_bytes()).hexdigest()
    (copy_dir / "provenance.json").write_text(json.dumps(provenance))
    with pytest.raises(ValueError, match="bundle id"):
        load_fixture(copy_dir)


def test_report_describes_the_metadata_in_force_for_the_data(real) -> None:
    summary = raw_summary(real[0])
    assert summary["series"]["units"] == "Index 1982-1984=100"
    assert summary["series"]["realtime_end"] == "2020-12-31"
    assert len(summary["series_versions"]) == 6 and summary["series_versions"][0]["units"] == "Index 1967=100"


# --- regressions from the second independent review of V1.1 ----------------------------------


def test_metadata_scoping_does_not_depend_on_duplicate_row_order() -> None:
    rows = base_rows()[1:] + [row("2024-01-01", "2024-02-13", "2024-02-14", "300.0"), row("2024-01-01", "2024-02-13", "2024-12-31", "300.0")]
    versions = (meta("1988-02-26", "2024-02-12"), meta("2024-02-13", "9999-12-31", seasonal_adjustment_short="NSA"))
    forward = parse_bundle(with_series(bundle(rows), *versions))
    backward = parse_bundle(with_series(bundle(list(reversed(rows))), *versions))
    assert forward.unusable == backward.unusable and forward.issues == backward.issues
    at = datetime(2024, 2, 20, tzinfo=UTC)
    candles = klines(datetime(2024, 2, 12, tzinfo=UTC), 24 * 7)
    assert run_replay(forward, candles, ReplayConfig(at))["content_hash"] == run_replay(backward, candles, ReplayConfig(at))["content_hash"]


def test_keychain_failure_keeps_no_exception_chain(monkeypatch) -> None:
    import subprocess

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("security", 5, output=KEY)

    monkeypatch.setattr("src.research_lab.external.fred_secret.subprocess.run", timeout)
    with pytest.raises(FredSecretError) as raised:
        FredSecretResolver({PROVIDER_ENV: "keychain"}).api_key()
    assert raised.value.__context__ is None and raised.value.__cause__ is None and KEY not in str(raised.value)


@pytest.mark.parametrize("escaped", [False, True])
@pytest.mark.parametrize("where", ["series", "series/observations", "release/dates"])
def test_responses_echoing_the_key_are_refused_and_never_stored(tmp_path, where: str, escaped: bool) -> None:
    payloads = research_payloads()
    body = json.loads(payloads[where])
    body["notes"] = "echo @@KEY@@"
    if where == "series/observations":
        body["observation_end"] = "@@KEY@@"  # would otherwise surface in the envelope error message
    # JSON escapes hide the key from a byte search; json.loads restores it.
    echoed = "".join(f"\\u{ord(char):04x}" for char in KEY) if escaped else KEY
    payloads[where] = json.dumps(body).replace("@@KEY@@", echoed).encode()
    _api, store, run = live(tmp_path, payloads)
    with pytest.raises(LiveIngestError) as raised:
        run()
    assert KEY not in str(raised.value) and raised.value.__context__ is None
    assert stored_files(store) == []


@pytest.mark.parametrize(
    "body",
    [
        ('{"notes": "' + KEY + '",').encode("utf-16"),  # json.loads decodes UTF-16; the byte search does not
        b'{"notes": "truncated",',
    ],
    ids=["utf16-echo", "truncated"],
)
def test_malformed_responses_leave_no_exception_context(tmp_path, body: bytes) -> None:
    payloads = research_payloads()
    payloads["series"] = body
    _api, store, run = live(tmp_path, payloads)
    with pytest.raises(LiveIngestError) as raised:
        run()
    # A JSONDecodeError context would hold the decoded response (.doc), key included.
    assert KEY not in str(raised.value) and raised.value.__context__ is None
    assert stored_files(store) == []


ESCAPED_KEY = "".join(f"\\u{ord(char):04x}" for char in KEY).encode()


@pytest.mark.parametrize(
    "where, members",
    [
        # json.loads keeps the last of two equal members; the first one would still reach the store.
        ("series", b'"notes": "' + ESCAPED_KEY + b'", "notes": "safe", '),
        # A lone surrogate (ED A0 80) fails strict UTF-8, but json.loads(bytes) decodes it (surrogatepass).
        ("series/observations", b'"notes": "' + ESCAPED_KEY + b'", "other": "\xed\xa0\x80", '),
    ],
    ids=["duplicate-member", "lone-surrogate"],
)
def test_hidden_key_echoes_are_refused(tmp_path, where: str, members: bytes) -> None:
    payloads = research_payloads()
    payloads[where] = payloads[where].replace(b"{", b"{" + members, 1)
    _api, store, run = live(tmp_path, payloads)
    with pytest.raises(LiveIngestError) as raised:
        run()
    assert KEY not in str(raised.value) and raised.value.__context__ is None
    assert stored_files(store) == []


def test_repeated_json_members_are_refused(tmp_path) -> None:
    # json.loads would keep the second date; the stored response would still hold the holdout date.
    repeated = b'"realtime_start": "2025-02-12", "realtime_start": "2016-02-19"'
    payloads = research_payloads()
    assert payloads["series/observations"].count(b'"realtime_start": "2016-02-19"') == 1
    payloads["series/observations"] = payloads["series/observations"].replace(b'"realtime_start": "2016-02-19"', repeated)
    _api, store, run = live(tmp_path, payloads)
    with pytest.raises(LiveIngestError):
        run()
    assert stored_files(store) == []
    raw = bundle()
    raw.payloads["observations"] = raw.payloads["observations"].replace(b'"realtime_start": "2024-02-13"', b'"realtime_start": "2024-01-11", "realtime_start": "2024-02-13"', 1)
    result = parse_bundle(raw)
    assert result.state is QualityState.NOT_READY and codes(result) == ["MALFORMED_PAYLOAD"]


def test_a_fetcher_error_quoting_the_url_does_not_leak_the_key(tmp_path) -> None:
    def fetcher(url: str) -> bytes:
        raise LiveIngestError(f"failed {url}")

    resolver = FredSecretResolver({PROVIDER_ENV: "env", KEY_ENV: KEY})
    with pytest.raises(LiveIngestError) as raised:
        ingest_live(RESEARCH_2017_2024, resolver=resolver, store=RawPayloadStore(tmp_path / "raw"), fetcher=fetcher, clock=lambda: INGESTED)
    assert KEY not in str(raised.value) and raised.value.__context__ is None


@pytest.mark.parametrize("stdout", [KEY.encode() + b"\n", KEY.encode() + b"\xff"], ids=["valid", "not-utf8"])
def test_keychain_output_is_decoded_without_exposing_the_key(monkeypatch, stdout: bytes) -> None:
    import subprocess

    def run(args, *, text=False, **_kwargs):
        # Like subprocess.run: text=True decodes inside run, so a decode error carries the bytes.
        return subprocess.CompletedProcess(args, 0, stdout.decode("utf-8") if text else stdout, "" if text else b"")

    monkeypatch.setattr("src.research_lab.external.fred_secret.subprocess.run", run)
    resolver = FredSecretResolver({PROVIDER_ENV: "keychain"})
    if stdout.endswith(b"\n"):
        assert resolver.api_key().reveal() == KEY
        return
    with pytest.raises(FredSecretError) as raised:
        resolver.api_key()
    assert KEY not in str(raised.value) and KEY not in repr(raised.value) and raised.value.__context__ is None


def test_store_key_script_refuses_destinations_inside_a_repository(tmp_path, monkeypatch) -> None:
    from scripts.fred_store_key import main

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    target = repo / "sub" / "fred-api-key.txt"
    assert main(["--file", str(target)], prompt=lambda _text: KEY) == 2
    assert not target.exists()
    monkeypatch.chdir(repo)
    assert main(["--file", "fred-api-key.txt"], prompt=lambda _text: KEY) == 2
    assert not (repo / "fred-api-key.txt").exists()


def test_store_key_script_refuses_a_symlink_into_or_out_of_a_repository(tmp_path) -> None:
    from scripts.fred_store_key import main

    repo, outside = tmp_path / "repo", tmp_path / "outside"
    (repo / ".git").mkdir(parents=True)
    outside.mkdir()
    link = repo / "fred-api-key"
    link.symlink_to(outside / "fred-api-key")  # resolves outside, but os.replace would replace the link in the repo
    assert main(["--file", str(link)], prompt=lambda _text: KEY) == 2
    assert link.is_symlink() and not (outside / "fred-api-key").exists()
    plain_link = outside / "link"
    plain_link.symlink_to(outside / "target")
    assert main(["--file", str(plain_link)], prompt=lambda _text: KEY) == 2  # no symlink destinations at all


def test_real_data_checks_require_an_answer_with_btc_data(monkeypatch) -> None:
    from src.research_lab.external import realcheck

    raw, _provenance = load_fixture()
    monkeypatch.setattr(realcheck, "load_btc", lambda _root, fetch: [])
    monkeypatch.setattr(realcheck, "FINAL_REPLAY_AT", datetime(2020, 12, 31, tzinfo=UTC))
    monkeypatch.setattr(realcheck, "AS_OF_CUTS", ())
    result = realcheck.replay_checks(raw, parse_bundle(raw), btc_root=FIXTURE_DIR, fetch_btc=False)
    assert result["btc_candles"] == 0 and result["all_checks_pass"] is False


def test_refused_expectation_leaves_the_event_unchanged() -> None:
    event = feb_event()
    with pytest.raises(ValueError):
        with_expectation(event, expectation(Decimal("1e1000000")))
    assert event.expected is None and event.surprise is None and event.surprise_status == "UNAVAILABLE_NO_EXPECTATION"
