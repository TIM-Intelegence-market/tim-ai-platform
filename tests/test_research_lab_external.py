"""External point-in-time data for the research lab (src/research_lab/external).

All payloads below are SYNTHETIC test fixtures in the ALFRED JSON layout. The
values are made up (300.0, 301.0, ...) and are not real CPI numbers. No test
needs the network.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace as dataclass_replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.research_lab.data.parse import Kline
from src.research_lab.data.store import HoldoutLocked, _issue_permission
from src.research_lab.external.alfred import RawBundle, fetch_bundle, parse_bundle, requests_for
from src.research_lab.external.align import BtcSeries, WindowStatus, align_event, align_series
from src.research_lab.external.events import EventStatus, Expectation, Measure, release_events, with_expectation
from src.research_lab.external.pit import DataNotReady, PointInTimeStore, Visibility
from src.research_lab.external.records import CPI_US, AvailabilityBasis, QualityState, UnknownSource, ValueStatus
from src.research_lab.external.replay import ReplayConfig, run_replay
from src.research_lab.external.store import RawPayloadStore

UTC = timezone.utc
INGESTED = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
HOUR = 3_600_000
FIVE_MIN = 300_000

# 08:30 New York: EST (UTC-5) on 2024-02-13, EDT (UTC-4) from 2024-03-10.
FEB_RELEASE = datetime(2024, 2, 13, 13, 30, tzinfo=UTC)
MAR_RELEASE = datetime(2024, 3, 12, 12, 30, tzinfo=UTC)
APR_RELEASE = datetime(2024, 4, 10, 12, 30, tzinfo=UTC)
MAY_CORRECTION = datetime(2024, 5, 16, 4, 0, tzinfo=UTC)  # unscheduled vintage 2024-05-15: end of that New York day


def row(period: str, start: str, end: str, value: str) -> dict:
    return {"realtime_start": start, "realtime_end": end, "date": period, "value": value}


def base_rows() -> list[dict]:
    return [
        row("2024-01-01", "2024-02-13", "2024-03-11", "300.0"),
        row("2024-01-01", "2024-03-12", "9999-12-31", "300.2"),
        row("2024-02-01", "2024-03-12", "9999-12-31", "301.0"),
        row("2024-03-01", "2024-04-10", "2024-05-14", "302.0"),
        row("2024-03-01", "2024-05-15", "9999-12-31", "302.5"),
    ]


def series_payload(**changes: str) -> bytes:
    meta = {"id": "CPIAUCSL", "frequency_short": "M", "units": "Index 1982-1984=100", "seasonal_adjustment_short": "SA", **changes}
    return json.dumps({"seriess": [meta]}).encode()


def observations_payload(
    rows: list[dict], *, start: str = "1776-07-04", end: str = "9999-12-31", units: str = "lin", count: int | None = None, output_type: int = 1
) -> bytes:
    body = {
        "realtime_start": start,
        "realtime_end": end,
        "units": units,
        "output_type": output_type,
        "offset": 0,
        "count": len(rows) if count is None else count,
        "observations": rows,
    }
    return json.dumps(body).encode()


def release_payload(dates: tuple[str, ...] = ("2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10"), release_id: int = 10, count: int | None = None) -> bytes:
    items = [{"release_id": release_id, "date": d} for d in dates]
    return json.dumps({"offset": 0, "count": len(items) if count is None else count, "release_dates": items}).encode()


def bundle(rows: list[dict] | None = None, *, calendar: bool = True, ingested_at: datetime = INGESTED, **observation_kwargs) -> RawBundle:
    payloads = {"series": series_payload(), "observations": observations_payload(base_rows() if rows is None else rows, **observation_kwargs)}
    if calendar:
        payloads["release_dates"] = release_payload()
    return RawBundle("ALFRED", "CPIAUCSL", payloads, ingested_at, requests_for(CPI_US))


def ingest(rows: list[dict] | None = None, **kwargs):
    return parse_bundle(bundle(rows, **kwargs))


def store(rows: list[dict] | None = None, **kwargs) -> PointInTimeStore:
    return PointInTimeStore(ingest(rows, **kwargs))


def codes(result) -> list[str]:
    return [item.issue.code for item in result.issues]


def klines(start: datetime, count: int, step: int = HOUR, skip: set[int] = frozenset()) -> list[Kline]:
    first = int(start.timestamp() * 1000)
    out = []
    for i in range(count):
        if i in skip:
            continue
        price = 40_000.0 + i
        out.append(Kline(first + i * step, price, price + 5, price - 5, price + 1, 10.0 + i, first + (i + 1) * step - 1, 4.0))
    return out


# --- ingestion, source identity and provenance ---------------------------------


def test_scheduled_vintages_become_available_at_release_time_new_york() -> None:
    result = ingest()
    assert result.state is QualityState.READY
    jan_first = next(r for r in result.records if r.period_start == date(2024, 1, 1) and r.vintage == date(2024, 2, 13))
    assert jan_first.available_at == FEB_RELEASE
    assert jan_first.release_time == FEB_RELEASE
    assert jan_first.availability_basis is AvailabilityBasis.SCHEDULED_RELEASE
    mar_first = next(r for r in result.records if r.period_start == date(2024, 3, 1) and r.vintage == date(2024, 4, 10))
    assert mar_first.available_at == APR_RELEASE  # daylight saving time applied
    correction = next(r for r in result.records if r.vintage == date(2024, 5, 15))
    assert correction.availability_basis is AvailabilityBasis.END_OF_VINTAGE_DAY
    assert correction.available_at == MAY_CORRECTION
    assert correction.release_time is None


def test_unknown_source_is_rejected() -> None:
    with pytest.raises(UnknownSource):
        parse_bundle(RawBundle("ALFRED", "NOT_A_SERIES", bundle().payloads, INGESTED))


@pytest.mark.parametrize("change", [{"id": "CPILFESL"}, {"units": "Percent"}, {"frequency_short": "Q"}, {"seasonal_adjustment_short": "NSA"}])
def test_inconsistent_series_metadata_is_not_ready(change) -> None:
    raw = bundle()
    raw.payloads["series"] = series_payload(**change)
    result = parse_bundle(raw)
    assert result.state is QualityState.NOT_READY
    assert codes(result) == ["INCONSISTENT_METADATA"]
    assert result.records == ()


def test_provenance_is_preserved_on_every_record_and_in_the_replay() -> None:
    raw = bundle()
    result = parse_bundle(raw)
    observation_sha = hashlib.sha256(raw.payloads["observations"]).hexdigest()
    for record in result.records:
        assert record.source == "ALFRED" and record.source_identifier == "CPIAUCSL" and record.data_type == "MACRO_RELEASE"
        assert record.payload_sha256 == observation_sha
        assert record.ingested_at == INGESTED
        assert record.raw_value
    output = run_replay(result, klines(datetime(2024, 2, 13, tzinfo=UTC), 24), ReplayConfig(datetime(2024, 2, 14, tzinfo=UTC)))
    assert output["provenance"]["payload_sha256"]["observations"] == observation_sha
    assert output["source"]["publisher"] == "U.S. Bureau of Labor Statistics"
    assert output["inputs"]["external_record_ids"] == ["ALFRED:CPIAUCSL:2024-01-01@2024-02-13"]


def test_fetch_keeps_the_api_key_out_of_the_bundle() -> None:
    seen: list[str] = []
    payloads = {"series": series_payload(), "series/observations": observations_payload(base_rows()), "release/dates": release_payload()}

    def fetcher(url: str) -> bytes:
        seen.append(url)
        path = url.split("/fred/", 1)[1].split("?", 1)[0]
        return payloads[path]

    raw = fetch_bundle(CPI_US, api_key="k" * 32, fetcher=fetcher, clock=lambda: INGESTED)
    assert all("api_key=" + "k" * 32 in url for url in seen)
    assert "k" * 32 not in json.dumps(raw.requests)
    assert parse_bundle(raw).state is QualityState.READY
    with pytest.raises(ValueError):
        fetch_bundle(CPI_US, api_key="", fetcher=fetcher, clock=lambda: INGESTED)


def test_raw_store_round_trip_detects_tampering_and_refuses_credentials(tmp_path) -> None:
    payload_store = RawPayloadStore(tmp_path)
    raw = bundle()
    bundle_id = payload_store.put(raw)
    loaded = payload_store.get(bundle_id)
    assert loaded.payloads == raw.payloads and loaded.ingested_at == INGESTED
    assert parse_bundle(loaded).records == parse_bundle(raw).records
    sha = hashlib.sha256(raw.payloads["observations"]).hexdigest()
    (tmp_path / "payloads" / sha[:2] / f"{sha}.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="changed on disk"):
        payload_store.get(bundle_id)
    leaky = RawBundle("ALFRED", "CPIAUCSL", raw.payloads, INGESTED, {"series": {"api_key": "secret"}})
    with pytest.raises(ValueError, match="credentials"):
        payload_store.put(leaky)


# --- point in time ---------------------------------------------------------------


def test_record_is_invisible_before_available_at_and_visible_from_it() -> None:
    pit = store()
    jan = date(2024, 1, 1)
    before = pit.value(jan, FEB_RELEASE - timedelta(microseconds=1))
    assert before.status is Visibility.NOT_AVAILABLE and before.value is None
    at = pit.value(jan, FEB_RELEASE)
    assert at.status is Visibility.AVAILABLE and at.value == Decimal("300.0")
    assert pit.value(jan, FEB_RELEASE + timedelta(days=1)).value == Decimal("300.0")


def test_revision_is_visible_only_from_its_own_vintage() -> None:
    pit = store()
    jan = date(2024, 1, 1)
    assert pit.value(jan, MAR_RELEASE - timedelta(seconds=1)).value == Decimal("300.0")
    revised = pit.value(jan, MAR_RELEASE)
    assert revised.value == Decimal("300.2") and revised.revision_number == 1 and revised.vintage == date(2024, 3, 12)
    mar = date(2024, 3, 1)
    assert pit.value(mar, MAY_CORRECTION - timedelta(seconds=1)).value == Decimal("302.0")
    assert pit.value(mar, MAY_CORRECTION).value == Decimal("302.5")


def test_latest_is_the_newest_period_known_at_t() -> None:
    pit = store()
    assert pit.latest(FEB_RELEASE - timedelta(seconds=1)).status is Visibility.NOT_AVAILABLE
    assert pit.latest(MAR_RELEASE).period_start == date(2024, 2, 1)
    assert pit.latest(APR_RELEASE).period_start == date(2024, 3, 1)


def test_naive_or_uncovered_replay_times_fail_closed() -> None:
    pit = store()
    with pytest.raises(ValueError):
        pit.value(date(2024, 1, 1), datetime(2024, 3, 1))
    beyond = pit.latest(INGESTED + timedelta(seconds=1))
    assert beyond.status is Visibility.INSUFFICIENT_DATA and beyond.value is None


def test_partial_realtime_range_limits_coverage() -> None:
    result = ingest([row("2024-01-01", "2024-02-13", "2024-03-01", "300.0")], end="2024-03-01")
    pit = PointInTimeStore(result)
    assert pit.value(date(2024, 1, 1), datetime(2024, 3, 1, 12, tzinfo=UTC)).status is Visibility.AVAILABLE
    assert pit.value(date(2024, 1, 1), datetime(2024, 3, 5, tzinfo=UTC)).status is Visibility.INSUFFICIENT_DATA


def test_stale_when_the_next_release_is_overdue() -> None:
    pit = store()
    assert pit.latest(datetime(2024, 5, 20, tzinfo=UTC)).stale is False
    late = pit.latest(datetime(2024, 6, 20, tzinfo=UTC))  # April data due by mid-June
    assert late.stale is True and late.value == Decimal("302.5")


# --- data quality ------------------------------------------------------------------


def test_missing_available_at_makes_the_payload_not_ready() -> None:
    rows = base_rows() + [{"realtime_end": "9999-12-31", "date": "2024-04-01", "value": "303.0"}]
    result = ingest(rows)
    assert result.state is QualityState.NOT_READY
    assert "MISSING_AVAILABLE_AT" in codes(result) and "UNDATABLE_ROWS" in codes(result)
    with pytest.raises(DataNotReady):
        PointInTimeStore(result)


@pytest.mark.parametrize("bad", ["2024-13-40", "2024/03/12", "", "2024-03-12T08:30:00"])
def test_malformed_timestamps_are_rejected(bad: str) -> None:
    rows = base_rows() + [row("2024-04-01", bad or "x", "9999-12-31", "303.0")]
    result = ingest(rows)
    assert result.state is QualityState.NOT_READY
    assert "MALFORMED_TIMESTAMP" in codes(result)


def test_impossible_timestamp_ordering_fails_closed() -> None:
    rows = base_rows() + [
        row("2024-05-01", "2024-05-20", "9999-12-31", "304.0"),  # published before May ended
        row("2024-01-01", "2024-02-13", "2024-02-01", "300.0"),  # end before start: duplicates January's first vintage
    ]
    result = ingest(rows)
    assert result.state is QualityState.READY
    assert codes(result).count("IMPOSSIBLE_TIMESTAMP_ORDER") == 1
    pit = PointInTimeStore(result)
    later = datetime(2024, 6, 1, tzinfo=UTC)
    assert pit.value(date(2024, 5, 1), later).status is Visibility.UNKNOWN
    assert all(r.period_start != date(2024, 5, 1) for r in result.records)
    # The bad end only becomes knowable with January's next vintage: that vintage is UNKNOWN, the first one is not.
    assert pit.value(date(2024, 1, 1), FEB_RELEASE).value == Decimal("300.0")
    assert pit.value(date(2024, 1, 1), MAR_RELEASE).status is Visibility.UNKNOWN


def test_future_vintage_is_rejected() -> None:
    rows = base_rows() + [row("2026-08-01", "2026-10-15", "9999-12-31", "350.0")]
    result = ingest(rows)
    assert "FUTURE_DATA" in codes(result)
    assert all(r.available_at <= INGESTED for r in result.records)


def test_identical_duplicates_are_kept_once() -> None:
    rows = base_rows() + [row("2024-02-01", "2024-03-12", "9999-12-31", "301.0")]
    result = ingest(rows)
    assert "DUPLICATE_RECORD" in codes(result)
    assert sum(1 for r in result.records if r.period_start == date(2024, 2, 1)) == 1


def test_conflicting_duplicates_are_unknown_not_an_older_value() -> None:
    rows = base_rows() + [row("2024-01-01", "2024-03-12", "9999-12-31", "299.9")]
    pit = store(rows)
    assert "CONFLICTING_DUPLICATE" in codes(pit.ingest)
    jan = pit.value(date(2024, 1, 1), MAR_RELEASE)
    assert jan.status is Visibility.UNKNOWN and jan.value is None
    assert pit.value(date(2024, 1, 1), MAR_RELEASE - timedelta(seconds=1)).value == Decimal("300.0")


def test_missing_and_malformed_values() -> None:
    rows = base_rows() + [row("2024-04-01", "2024-05-15", "9999-12-31", "."), row("2024-05-01", "2024-06-12", "9999-12-31", "abc")]
    result = ingest(rows)
    assert "MISSING_VALUE" in codes(result) and "MALFORMED_VALUE" in codes(result)
    pit = PointInTimeStore(result)
    april = pit.value(date(2024, 4, 1), datetime(2024, 6, 1, tzinfo=UTC))
    assert april.status is Visibility.MISSING and april.value is None
    assert next(r for r in result.records if r.period_start == date(2024, 4, 1)).value_status is ValueStatus.MISSING
    assert pit.value(date(2024, 5, 1), datetime(2024, 6, 20, tzinfo=UTC)).status is Visibility.UNKNOWN


@pytest.mark.parametrize(
    "payload",
    [b"not json", observations_payload(base_rows(), units="pch"), observations_payload(base_rows(), count=99)],
)
def test_payload_level_failures_are_not_ready_and_replay_outputs_nothing(payload: bytes) -> None:
    raw = bundle()
    raw.payloads["observations"] = payload
    result = parse_bundle(raw)
    assert result.state is QualityState.NOT_READY
    output = run_replay(result, klines(datetime(2024, 2, 13, tzinfo=UTC), 24), ReplayConfig(datetime(2024, 2, 14, tzinfo=UTC)))
    assert output["state"] == "NOT_READY" and output["series_rows"] == [] and output["events"] == []
    assert output["quality_issues"]


def test_empty_observations_are_insufficient_data() -> None:
    result = ingest([])
    assert result.state is QualityState.INSUFFICIENT_DATA
    with pytest.raises(DataNotReady):
        PointInTimeStore(result)


def test_revision_history_unavailable_is_flagged_not_hidden() -> None:
    rows = [row("2023-01-01", "2024-02-13", "9999-12-31", "290.0")] + base_rows()  # first archived a year late
    result = ingest(rows)
    assert date(2023, 1, 1) in result.periods_without_first_release
    assert "REVISION_HISTORY_UNAVAILABLE" in codes(result)
    pit = PointInTimeStore(result)
    assert pit.value(date(2023, 1, 1), datetime(2023, 3, 1, tzinfo=UTC)).status is Visibility.NOT_AVAILABLE
    assert pit.value(date(2023, 1, 1), FEB_RELEASE).first_release_in_archive is False


def test_clipped_request_start_is_not_treated_as_a_release() -> None:
    rows = [row("2024-01-01", "2024-03-01", "2024-03-11", "300.0")] + base_rows()[1:]
    result = ingest(rows, start="2024-03-01")
    clipped = next(r for r in result.records if r.vintage == date(2024, 3, 1))
    assert clipped.availability_basis is AvailabilityBasis.END_OF_VINTAGE_DAY
    assert date(2024, 1, 1) in result.periods_without_first_release


def test_without_release_calendar_every_vintage_waits_for_end_of_day() -> None:
    result = ingest(calendar=False)
    assert "RELEASE_CALENDAR_UNAVAILABLE" in codes(result)
    assert {r.availability_basis for r in result.records} == {AvailabilityBasis.END_OF_VINTAGE_DAY}
    assert PointInTimeStore(result).value(date(2024, 1, 1), FEB_RELEASE).status is Visibility.NOT_AVAILABLE


def test_release_calendar_for_another_release_is_not_ready() -> None:
    raw = bundle()
    raw.payloads["release_dates"] = release_payload(release_id=50)
    assert parse_bundle(raw).state is QualityState.NOT_READY


# --- events ----------------------------------------------------------------------


def test_release_events_expose_actual_previous_and_revision() -> None:
    events = release_events(store(), until=INGESTED)
    assert [e.reference_period for e in events] == [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]  # the May correction is no release
    feb = events[1]
    assert feb.status is EventStatus.OK and feb.event_time == MAR_RELEASE
    assert (feb.actual, feb.previous, feb.previous_revised, feb.revision) == (Decimal("301.0"), Decimal("300.0"), Decimal("300.2"), Decimal("0.2"))
    assert feb.derived_change_pct == Decimal("0.2665")
    assert feb.expected is None and feb.surprise is None and feb.surprise_status == "UNAVAILABLE_NO_EXPECTATION"
    assert events[0].previous is None and events[0].revision is None


def test_events_after_until_are_not_returned() -> None:
    assert [e.reference_period for e in release_events(store(), until=MAR_RELEASE - timedelta(seconds=1))] == [date(2024, 1, 1)]


def test_expectation_must_be_sourced_and_known_before_the_release() -> None:
    feb = release_events(store(), until=INGESTED)[1]
    with pytest.raises(ValueError, match="lookahead"):
        with_expectation(feb, Expectation(Decimal("0.3"), Measure.CHANGE_PCT, "SURVEY", "cpi_mom", MAR_RELEASE + timedelta(seconds=1)))
    with pytest.raises(ValueError):
        Expectation(Decimal("0.3"), Measure.CHANGE_PCT, "", "cpi_mom", MAR_RELEASE)
    event = with_expectation(feb, Expectation(Decimal("0.3"), Measure.CHANGE_PCT, "SURVEY", "cpi_mom", MAR_RELEASE - timedelta(days=1)))
    assert event.surprise == Decimal("-0.0335") and event.surprise_status == "OK"
    assert event.expected_source == "SURVEY:cpi_mom"


def test_events_without_scheduled_time_are_not_aligned() -> None:
    pit = store(calendar=False)
    event = release_events(pit, until=INGESTED)[0]
    assert event.status is EventStatus.RELEASE_TIME_UNKNOWN and event.event_time is None
    btc = BtcSeries.build(klines(datetime(2024, 2, 13, tzinfo=UTC), 48), "1h", replay_at=INGESTED)
    assert align_event(event, btc, replay_at=INGESTED)["status"] == WindowStatus.EVENT_TIME_UNKNOWN


# --- BTC alignment -----------------------------------------------------------------


def test_series_alignment_has_no_lookahead() -> None:
    btc = BtcSeries.build(klines(datetime(2024, 2, 13, 10, tzinfo=UTC), 6), "1h", replay_at=INGESTED)
    rows = align_series(store(), btc)
    by_open = {r["open_time"]: r for r in rows}
    before = by_open["2024-02-13T12:00:00+00:00"]  # closes 13:00, release is 13:30
    assert before["decision_time"] == "2024-02-13T13:00:00+00:00" and before["external"]["status"] == "NOT_AVAILABLE"
    containing = by_open["2024-02-13T13:00:00+00:00"]  # closes 14:00, after the release
    assert containing["decision_time"] == "2024-02-13T14:00:00+00:00" and containing["external"]["value"] == "300.0"
    for r in rows:
        if r["external"]["available_at"]:
            assert r["external"]["available_at"] <= r["decision_time"]
    assert {r["split"] for r in rows} == {"validation"}


def test_event_windows_on_hourly_candles() -> None:
    event = release_events(store(), until=INGESTED)[0]
    btc = BtcSeries.build(klines(datetime(2024, 2, 13, tzinfo=UTC), 24 * 9), "1h", replay_at=INGESTED)
    aligned = align_event(event, btc, replay_at=INGESTED)
    assert aligned["anchor"]["open_time"] == "2024-02-13T12:00:00+00:00"  # 13:00-14:00 contains the release
    assert aligned["anchor"]["btc_close_before"] == repr(40_000.0 + 12 + 1)
    assert aligned["release_inside_candle"] == "2024-02-13T13:00:00+00:00"
    windows = aligned["windows"]
    assert windows["5m"]["status"] == windows["15m"]["status"] == windows["1h"]["status"] == WindowStatus.RESOLUTION_TOO_COARSE
    assert (windows["4h"]["status"], windows["4h"]["expected_candles"]) == (WindowStatus.COMPLETE, 3)
    assert windows["24h"]["expected_candles"] == 23 and windows["7d"]["expected_candles"] == 167
    assert windows["7d"]["status"] == WindowStatus.COMPLETE
    assert "return" not in json.dumps(aligned)


def test_event_windows_on_five_minute_candles() -> None:
    event = release_events(store(), until=INGESTED)[0]
    btc = BtcSeries.build(klines(datetime(2024, 2, 13, 12, tzinfo=UTC), 12 * 8, step=FIVE_MIN), "5m", replay_at=INGESTED)
    windows = align_event(event, btc, replay_at=INGESTED, horizons=("5m", "15m", "1h", "4h", "24h"))["windows"]
    assert (windows["5m"]["status"], windows["5m"]["expected_candles"]) == (WindowStatus.COMPLETE, 1)
    assert windows["15m"]["expected_candles"] == 3 and windows["1h"]["expected_candles"] == 12
    assert windows["24h"]["status"] == WindowStatus.INSUFFICIENT_DATA  # candles end after 8 hours


def test_gap_in_btc_candles_is_insufficient_data() -> None:
    event = release_events(store(), until=INGESTED)[0]
    btc = BtcSeries.build(klines(datetime(2024, 2, 13, tzinfo=UTC), 48, skip={15}), "1h", replay_at=INGESTED)
    windows = align_event(event, btc, replay_at=INGESTED, horizons=("4h",))["windows"]
    assert windows["4h"]["status"] == WindowStatus.INSUFFICIENT_DATA and windows["4h"]["present_candles"] == 2


def test_windows_after_replay_time_are_not_available() -> None:
    replay_at = FEB_RELEASE + timedelta(hours=5)
    event = release_events(store(), until=replay_at)[0]
    btc = BtcSeries.build(klines(datetime(2024, 2, 13, tzinfo=UTC), 24 * 9), "1h", replay_at=replay_at)
    windows = align_event(event, btc, replay_at=replay_at)["windows"]
    assert windows["4h"]["status"] == WindowStatus.COMPLETE
    assert windows["24h"]["status"] == WindowStatus.NOT_AVAILABLE_AT_REPLAY_TIME
    assert all(k.open_time + HOUR <= int(replay_at.timestamp() * 1000) for k in btc.klines)


def test_holdout_candles_need_the_protocol_permission() -> None:
    holdout = klines(datetime(2024, 12, 31, 22, tzinfo=UTC), 4)
    with pytest.raises(HoldoutLocked):
        BtcSeries.build(holdout, "1h", replay_at=INGESTED)
    permission = _issue_permission("test", (), 0)
    assert len(BtcSeries.build(holdout, "1h", replay_at=INGESTED, permission=permission).klines) == 4


@pytest.mark.parametrize(
    "candles",
    [
        klines(datetime(2024, 2, 13, tzinfo=UTC), 3) + klines(datetime(2024, 2, 13, 2, tzinfo=UTC), 1),  # duplicate
        list(reversed(klines(datetime(2024, 2, 13, tzinfo=UTC), 3))),
        [Kline(1_707_782_400_001, 1, 1, 1, 1, 1, 1_707_786_000_000, 0)],  # off grid
    ],
)
def test_invalid_btc_input_is_rejected(candles) -> None:
    with pytest.raises(ValueError):
        BtcSeries.build(candles, "1h", replay_at=INGESTED)


def test_invalid_replay_config_is_rejected() -> None:
    with pytest.raises(ValueError):
        ReplayConfig(datetime(2024, 3, 1))
    with pytest.raises(ValueError):
        ReplayConfig(INGESTED, horizons=("2h",))
    with pytest.raises(ValueError):
        BtcSeries.build([], "7m", replay_at=INGESTED)


# --- replay ------------------------------------------------------------------------


def replay(result, at: datetime) -> dict:
    return run_replay(result, klines(datetime(2024, 2, 12, tzinfo=UTC), 24 * 70), ReplayConfig(at))


def test_replay_is_deterministic_and_order_independent() -> None:
    at = datetime(2024, 4, 20, tzinfo=UTC)
    first, second = replay(ingest(), at), replay(ingest(), at)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    shuffled = ingest(list(reversed(base_rows())))
    assert replay(shuffled, at)["content_hash"] == first["content_hash"]
    assert len(first["output_hash"]) == 64 and first["mode"] == "RESEARCH"


def test_historical_replay_is_unaffected_by_a_later_revision() -> None:
    at = datetime(2024, 4, 20, tzinfo=UTC)
    before_correction = copy.deepcopy(base_rows()[:4])
    before_correction[3]["realtime_end"] = "9999-12-31"  # March had not been revised yet
    early = parse_bundle(bundle(before_correction, ingested_at=datetime(2024, 4, 30, tzinfo=UTC)))
    late = ingest()
    old, new = replay(early, at), replay(late, at)
    assert old["content_hash"] == new["content_hash"]
    assert old["events"] == new["events"] and old["series_rows"] == new["series_rows"]
    assert old["provenance"] != new["provenance"]
    assert "302.5" not in json.dumps({k: v for k, v in new.items() if k != "provenance"})
    after = replay(late, datetime(2024, 5, 20, tzinfo=UTC))
    assert after["latest"]["value"] == "302.5"


def test_replay_does_not_reveal_later_quality_issues() -> None:
    rows = base_rows() + [row("2024-01-01", "2024-03-12", "9999-12-31", "299.9")]  # conflict dated 2024-03-12
    result = ingest(rows)
    assert replay(result, datetime(2024, 3, 1, tzinfo=UTC))["quality_issues"] == []
    assert any(i["code"] == "CONFLICTING_DUPLICATE" for i in replay(result, datetime(2024, 3, 20, tzinfo=UTC))["quality_issues"])


def test_replay_in_the_holdout_needs_the_protocol_permission() -> None:
    with pytest.raises(HoldoutLocked):
        run_replay(ingest(), [], ReplayConfig(datetime(2025, 1, 1, tzinfo=UTC)))
    permission = _issue_permission("test", (), 0)
    output = run_replay(ingest(), [], ReplayConfig(datetime(2025, 2, 1, tzinfo=UTC)), permission=permission)
    assert output["latest"]["value"] == "302.5"


# --- regressions from the independent review ---------------------------------------


def test_malformed_end_date_does_not_change_an_earlier_replay() -> None:
    rows = base_rows()
    rows[3] = row("2024-03-01", "2024-04-10", "BAD", "302.0")  # its successor arrives 2024-05-15
    result = ingest(rows)
    assert result.state is QualityState.READY and "MALFORMED_TIMESTAMP" in codes(result)
    before_successor = datetime(2024, 4, 20, tzinfo=UTC)
    assert replay(result, before_successor)["content_hash"] == replay(ingest(), before_successor)["content_hash"]
    pit = PointInTimeStore(result)
    assert pit.value(date(2024, 3, 1), before_successor).value == Decimal("302.0")
    assert pit.value(date(2024, 3, 1), MAY_CORRECTION).status is Visibility.UNKNOWN
    future_row = ingest(base_rows() + [row("2024-04-01", "2024-05-15", "BAD", "303.0")])
    assert replay(future_row, before_successor)["content_hash"] == replay(ingest(), before_successor)["content_hash"]


def test_duplicates_disagreeing_on_end_date_do_not_depend_on_row_order() -> None:
    rows = base_rows() + [row("2024-01-01", "2024-02-13", "9999-12-31", "300.0")]  # same value, other end date
    at = datetime(2024, 4, 20, tzinfo=UTC)
    forward, backward = ingest(rows), ingest(list(reversed(rows)))
    assert replay(forward, at)["content_hash"] == replay(backward, at)["content_hash"]
    pit = PointInTimeStore(forward)
    assert pit.value(date(2024, 1, 1), FEB_RELEASE).value == Decimal("300.0")
    assert pit.value(date(2024, 1, 1), MAR_RELEASE).status is Visibility.UNKNOWN


def test_overlap_with_any_earlier_vintage_fails_closed() -> None:
    rows = [
        row("2024-01-01", "2024-02-13", "2024-12-31", "300.0"),
        row("2024-01-01", "2024-03-12", "2024-04-09", "301.0"),
        row("2024-01-01", "2024-04-10", "9999-12-31", "302.0"),
    ]
    pit = store(rows)
    assert pit.value(date(2024, 1, 1), APR_RELEASE).status is Visibility.UNKNOWN


def test_misaligned_period_date_is_dated_not_payload_wide() -> None:
    rows = base_rows() + [row("2024-04-02", "2024-05-15", "9999-12-31", "303.0")]
    result = ingest(rows)
    assert result.state is QualityState.READY
    at = datetime(2024, 4, 20, tzinfo=UTC)
    assert replay(result, at)["content_hash"] == replay(ingest(), at)["content_hash"]
    assert PointInTimeStore(result).value(date(2024, 4, 1), datetime(2024, 6, 1, tzinfo=UTC)).status is Visibility.UNKNOWN


def test_holdout_release_anchor_needs_the_permission() -> None:
    permission = _issue_permission("test", (), 0)
    btc = BtcSeries.build(klines(datetime(2025, 1, 15, tzinfo=UTC), 48), "1h", replay_at=datetime(2025, 2, 1, tzinfo=UTC), permission=permission)
    rows = [row("2024-12-01", "2025-01-15", "9999-12-31", "310.0")]
    raw = bundle(rows, calendar=False)
    raw.payloads["release_dates"] = release_payload(("2024-12-11", "2025-01-15"))
    event = release_events(PointInTimeStore(parse_bundle(raw)), until=INGESTED)[0]
    locked = align_event(event, btc, replay_at=datetime(2025, 2, 1, tzinfo=UTC))
    assert locked["status"] == WindowStatus.HOLDOUT_LOCKED and locked["anchor"] is None
    opened = align_event(event, btc, replay_at=datetime(2025, 2, 1, tzinfo=UTC), permission=permission)
    assert opened["anchor"]["btc_close_before"] is not None


def test_raw_store_refuses_an_edited_manifest_entry(tmp_path) -> None:
    payload_store = RawPayloadStore(tmp_path)
    bundle_id = payload_store.put(bundle())
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["bundles"][bundle_id]["ingested_at"] = "2020-01-01T00:00:00+00:00"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest entry"):
        payload_store.get(bundle_id)


def test_defective_future_candles_do_not_change_an_earlier_replay() -> None:
    at = datetime(2024, 2, 20, tzinfo=UTC)
    good = klines(datetime(2024, 2, 12, tzinfo=UTC), 24 * 8)
    broken_future = Kline(int(datetime(2024, 3, 1, tzinfo=UTC).timestamp() * 1000), 1, 1, 1, 1, 1, 0, 0)
    assert run_replay(ingest(), good + [broken_future], ReplayConfig(at))["content_hash"] == run_replay(ingest(), good, ReplayConfig(at))["content_hash"]


def test_align_event_enforces_its_own_replay_time() -> None:
    event = release_events(store(), until=INGESTED)[1]  # released 2024-03-12
    btc = BtcSeries.build(klines(datetime(2024, 3, 11, tzinfo=UTC), 72), "1h", replay_at=INGESTED)
    early = align_event(event, btc, replay_at=datetime(2024, 2, 20, tzinfo=UTC))
    assert early["status"] == WindowStatus.NOT_AVAILABLE_AT_REPLAY_TIME and early["anchor"] is None
    short = BtcSeries.build(klines(datetime(2024, 3, 11, tzinfo=UTC), 72), "1h", replay_at=datetime(2024, 3, 12, tzinfo=UTC))
    with pytest.raises(ValueError):
        align_event(event, short, replay_at=INGESTED)


def test_credentials_are_refused_before_they_can_reach_any_output() -> None:
    raw = bundle()
    leaky = RawBundle(raw.source, raw.source_identifier, raw.payloads, INGESTED, {"series": {"path": "series", "api_key": "secret"}})
    with pytest.raises(ValueError, match="credentials"):
        parse_bundle(leaky)


def test_row_order_and_number_spelling_do_not_change_the_result() -> None:
    rows = base_rows() + [row("2024-02-01", "2024-03-12", "9999-12-31", "301.00"), row("2024-04-01", "2024-05-15", "9999-12-31", ".")]
    at = datetime(2024, 5, 20, tzinfo=UTC)
    forward, backward = ingest(rows), ingest(list(reversed(rows)))
    assert forward.issues == backward.issues
    assert replay(forward, at)["content_hash"] == replay(backward, at)["content_hash"]


def test_event_arithmetic_ignores_the_ambient_decimal_context() -> None:
    import decimal

    with decimal.localcontext(decimal.Context(prec=3, rounding=decimal.ROUND_DOWN)):
        feb = release_events(store(), until=INGESTED)[1]
    assert feb.derived_change_pct == Decimal("0.2665") and feb.revision == Decimal("0.2")


def test_returned_provenance_is_detached_from_the_input() -> None:
    raw = bundle()
    output = replay(parse_bundle(raw), datetime(2024, 4, 20, tzinfo=UTC))
    raw.requests["series"]["series_id"] = "changed"
    assert output["provenance"]["request"]["series"]["series_id"] == "CPIAUCSL"
    body = {key: value for key, value in output.items() if key != "output_hash"}
    from src.research_ops.audit import digest

    assert digest(body) == output["output_hash"]


def test_expectation_needs_a_known_release_time() -> None:
    unscheduled = release_events(store(calendar=False), until=INGESTED)[1]
    with pytest.raises(ValueError, match="release time unknown"):
        with_expectation(unscheduled, Expectation(Decimal("0.3"), Measure.CHANGE_PCT, "SURVEY", "cpi_mom", MAR_RELEASE - timedelta(days=1)))
    scheduled = release_events(store(), until=INGESTED)[1]
    with pytest.raises(ValueError, match="lookahead"):
        with_expectation(scheduled, Expectation(Decimal("0.3"), Measure.CHANGE_PCT, "SURVEY", "cpi_mom", MAR_RELEASE))


def test_unusable_entries_are_part_of_the_dataset_identity() -> None:
    at = datetime(2024, 5, 20, tzinfo=UTC)
    clean = replay(ingest(), at)
    poisoned = replay(ingest(base_rows() + [row("2024-04-01", "2024-05-15", "9999-12-31", "abc")]), at)
    assert clean["dataset_id"] != poisoned["dataset_id"]
    assert poisoned["inputs"]["external_unusable"][0]["reason"] == "MALFORMED_VALUE"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.payloads.__setitem__("series", b'{"seriess":[null]}'),
        lambda raw: raw.payloads.__setitem__("observations", observations_payload(base_rows(), output_type=4)),
    ],
)
def test_malformed_metadata_and_other_output_types_are_not_ready(mutate) -> None:
    raw = bundle()
    mutate(raw)
    result = parse_bundle(raw)
    assert result.state is QualityState.NOT_READY and codes(result) == ["INCONSISTENT_METADATA"]


def test_truncated_release_calendar_is_not_ready() -> None:
    raw = bundle()
    raw.payloads["release_dates"] = release_payload(count=99)
    assert parse_bundle(raw).state is QualityState.NOT_READY


def test_overlapping_vintages_fail_closed() -> None:
    rows = [row("2024-01-01", "2024-02-13", "2024-04-01", "300.0"), row("2024-01-01", "2024-03-12", "9999-12-31", "301.0")]
    result = ingest(rows)
    assert "INCONSISTENT_VINTAGE_CHAIN" in codes(result)
    pit = PointInTimeStore(result)
    assert pit.value(date(2024, 1, 1), FEB_RELEASE).value == Decimal("300.0")
    assert pit.value(date(2024, 1, 1), MAR_RELEASE).status is Visibility.UNKNOWN


def test_non_positive_values_and_invalid_candles_are_rejected() -> None:
    result = ingest(base_rows() + [row("2024-04-01", "2024-05-15", "9999-12-31", "0"), row("2024-05-01", "2024-06-12", "9999-12-31", "-1")])
    assert codes(result).count("MALFORMED_VALUE") == 2
    candle = klines(datetime(2024, 2, 13, tzinfo=UTC), 1)[0]
    for bad in (dataclass_replace(candle, close=float("nan")), dataclass_replace(candle, volume=-2.0)):
        with pytest.raises(ValueError):
            BtcSeries.build([bad], "1h", replay_at=INGESTED)


def test_coverage_ends_with_the_last_requested_day() -> None:
    result = ingest([row("2024-01-01", "2024-02-13", "9999-12-31", "300.0")], end="2024-03-01")
    pit = PointInTimeStore(result)
    last_instant = datetime(2024, 3, 2, 5, 0, tzinfo=UTC) - timedelta(microseconds=1)  # end of 2024-03-01 in New York
    assert pit.latest(last_instant).status is Visibility.AVAILABLE
    assert pit.latest(datetime(2024, 3, 2, 5, 0, tzinfo=UTC)).status is Visibility.INSUFFICIENT_DATA


def test_visible_records_do_not_reveal_when_a_value_was_later_replaced() -> None:
    pit = store()
    (jan,) = pit.visible_records(FEB_RELEASE)
    assert jan.vintage_end is None
    later = {r.record_id: r for r in pit.visible_records(MAR_RELEASE)}
    assert later["ALFRED:CPIAUCSL:2024-01-01@2024-02-13"].vintage_end == date(2024, 3, 11)


def test_replay_before_any_release_is_insufficient_data() -> None:
    output = replay(ingest(), datetime(2024, 2, 13, 13, tzinfo=UTC))
    assert output["state"] == "INSUFFICIENT_DATA" and output["events"] == []
    assert output["latest"]["status"] == "NOT_AVAILABLE"


# --- regressions from the pre-merge review (PR #128) ------------------------------


def test_missing_first_print_is_not_a_release_and_takes_no_expectation() -> None:
    # January's earliest archived vintage is the April release: the real January release came earlier.
    event = release_events(store([row("2024-01-01", "2024-04-10", "9999-12-31", "310.0")]), until=INGESTED)[0]
    assert event.first_release_in_archive is False
    assert event.status is EventStatus.FIRST_RELEASE_UNAVAILABLE and event.event_time is None
    with pytest.raises(ValueError, match="first release"):
        with_expectation(event, Expectation(Decimal("300"), Measure.LEVEL, "SURVEY", "cpi_level", APR_RELEASE - timedelta(days=1)))
    btc = BtcSeries.build(klines(datetime(2024, 4, 9, tzinfo=UTC), 72), "1h", replay_at=INGESTED)
    assert align_event(event, btc, replay_at=INGESTED)["status"] == WindowStatus.EVENT_TIME_UNKNOWN


def test_coverage_that_cuts_the_replay_changes_the_dataset_identity() -> None:
    rows = copy.deepcopy(base_rows()[:4])
    rows[3]["realtime_end"] = "9999-12-31"
    at = datetime(2024, 4, 10, 14, tzinfo=UTC)
    cut = replay(parse_bundle(bundle(rows, ingested_at=datetime(2024, 4, 10, 13, tzinfo=UTC))), at)
    covered = replay(parse_bundle(bundle(rows, ingested_at=datetime(2024, 4, 30, tzinfo=UTC))), at)
    assert cut["inputs"]["external_records_hash"] == covered["inputs"]["external_records_hash"]
    assert (cut["state"], covered["state"]) == ("INSUFFICIENT_DATA", "READY")
    assert cut["dataset_id"] != covered["dataset_id"]
    # Re-ingesting the same archive later keeps the identity when both cover the replay time.
    assert covered["dataset_id"] == replay(parse_bundle(bundle(rows, ingested_at=INGESTED)), at)["dataset_id"]


def test_missing_first_prints_are_part_of_the_dataset_identity() -> None:
    at = datetime(2024, 4, 20, tzinfo=UTC)
    rows = [row("2024-01-01", "2024-03-01", "2024-03-11", "300.0")] + base_rows()[1:]
    full, clipped = replay(ingest(rows), at), replay(ingest(rows, start="2024-03-01"), at)
    assert full["inputs"] == clipped["inputs"]
    assert full["dataset_id"] != clipped["dataset_id"]


def test_different_unusable_payloads_do_not_share_a_dataset_id() -> None:
    at = datetime(2024, 4, 20, tzinfo=UTC)
    broken_json, missing = bundle(), bundle()
    broken_json.payloads["series"] = b"{"
    del missing.payloads["observations"]
    first, second = replay(parse_bundle(broken_json), at), replay(parse_bundle(missing), at)
    assert first["state"] == second["state"] == "NOT_READY"
    assert first["dataset_id"] != second["dataset_id"]
    assert first["dataset_id"] == replay(parse_bundle(copy.deepcopy(broken_json)), at)["dataset_id"]


def test_first_print_must_be_the_first_scheduled_release_not_just_inside_the_lag() -> None:
    # January's February 13 print is missing; its March 12 revision lies inside the 45-day bound.
    result = ingest([row("2024-01-01", "2024-03-12", "9999-12-31", "300.2")])
    assert date(2024, 1, 1) in result.periods_without_first_release
    event = release_events(PointInTimeStore(result), until=INGESTED)[0]
    assert event.status is EventStatus.FIRST_RELEASE_UNAVAILABLE and event.event_time is None
    with pytest.raises(ValueError, match="first release"):
        with_expectation(event, Expectation(Decimal("300"), Measure.LEVEL, "SURVEY", "cpi_level", MAR_RELEASE - timedelta(days=1)))
    # The complete fixture still identifies every first print.
    assert ingest().periods_without_first_release == frozenset()
    assert [e.status for e in release_events(store(), until=INGESTED)] == [EventStatus.OK] * 3


def test_unusable_value_still_counts_for_overlapping_vintages() -> None:
    overlapping = [row("2024-01-01", "2024-02-13", "2024-12-31", "bad"), row("2024-01-01", "2024-03-12", "9999-12-31", "301.0")]
    assert store(overlapping).value(date(2024, 1, 1), MAR_RELEASE).status is Visibility.UNKNOWN
    chained = [row("2024-01-01", "2024-02-13", "2024-03-11", "bad"), row("2024-01-01", "2024-03-12", "9999-12-31", "301.0")]
    assert store(chained).value(date(2024, 1, 1), MAR_RELEASE).value == Decimal("301.0")


@pytest.mark.parametrize("empty_calendar", [False, True])
def test_without_calendar_dates_no_first_print_is_certified(empty_calendar: bool) -> None:
    raw = bundle([row("2024-01-01", "2024-03-12", "9999-12-31", "300.2")], calendar=empty_calendar)
    if empty_calendar:
        raw.payloads["release_dates"] = release_payload(())
    result = parse_bundle(raw)
    assert result.state is QualityState.READY and "RELEASE_CALENDAR_UNAVAILABLE" in codes(result)
    assert result.periods_without_first_release == frozenset({date(2024, 1, 1)})
    event = release_events(PointInTimeStore(result), until=INGESTED)[0]
    assert event.first_release_in_archive is False and event.event_time is None


@pytest.mark.parametrize(
    "edge_row",
    [row("9999-12-01", "9999-12-30", "9999-12-31", "300.0"), row("2024-01-01", "9999-12-31", "9999-12-31", "300.0")],
)
def test_dates_at_the_calendar_edge_make_the_payload_not_ready_instead_of_crashing(edge_row: dict) -> None:
    result = ingest(base_rows() + [edge_row])
    assert result.state is QualityState.NOT_READY
    assert "MALFORMED_TIMESTAMP" in codes(result) and "UNDATABLE_ROWS" in codes(result)


def test_calendar_starting_after_the_period_ended_certifies_no_first_print() -> None:
    # The calendar lacks the February 13 release, so matching its first entry proves nothing.
    raw = bundle([row("2024-01-01", "2024-03-12", "9999-12-31", "300.2")])
    raw.payloads["release_dates"] = release_payload(("2024-03-12", "2024-04-10"))
    result = parse_bundle(raw)
    assert date(2024, 1, 1) in result.periods_without_first_release
    event = release_events(PointInTimeStore(result), until=INGESTED)[0]
    assert event.status is EventStatus.FIRST_RELEASE_UNAVAILABLE and event.event_time is None
    with pytest.raises(ValueError, match="first release"):
        with_expectation(event, Expectation(Decimal("300"), Measure.LEVEL, "SURVEY", "cpi_level", MAR_RELEASE - timedelta(days=1)))


def test_calendar_gap_around_the_first_release_certifies_no_first_print() -> None:
    # The February 13 release is missing inside the calendar: January 11 -> March 12 spans two releases.
    raw = bundle([row("2024-01-01", "2024-03-12", "9999-12-31", "300.2")])
    raw.payloads["release_dates"] = release_payload(("2024-01-11", "2024-03-12", "2024-04-10"))
    result = parse_bundle(raw)
    assert date(2024, 1, 1) in result.periods_without_first_release
    event = release_events(PointInTimeStore(result), until=INGESTED)[0]
    assert event.status is EventStatus.FIRST_RELEASE_UNAVAILABLE and event.event_time is None
    with pytest.raises(ValueError, match="first release"):
        with_expectation(event, Expectation(Decimal("300"), Measure.LEVEL, "SURVEY", "cpi_level", datetime(2024, 3, 1, tzinfo=UTC)))


@pytest.mark.parametrize(
    "envelope",
    [{"start": "2024-04-01"}, {"end": "2024-02-01"}, {"start": "2024-05-01", "end": "2024-04-01"}],
)
def test_rows_outside_the_declared_real_time_range_are_not_ready(envelope: dict) -> None:
    result = ingest(**envelope)
    assert result.state is QualityState.NOT_READY and codes(result) == ["INCONSISTENT_METADATA"]
    output = replay(result, datetime(2024, 4, 20, tzinfo=UTC))
    assert output["state"] == "NOT_READY" and output["events"] == []


def test_period_at_the_start_of_the_calendar_makes_the_payload_not_ready_instead_of_crashing() -> None:
    result = ingest(base_rows() + [row("0001-01-01", "2024-02-13", "9999-12-31", "300.0")])
    assert result.state is QualityState.NOT_READY and "UNDATABLE_ROWS" in codes(result)
    assert replay(result, datetime(2024, 4, 20, tzinfo=UTC))["state"] == "NOT_READY"


@pytest.mark.parametrize("extreme",["1e100", "1e999999999", "1e-9", "300.00000000000000000001"])
def test_values_outside_the_supported_range_are_unusable_not_a_crash(extreme: str) -> None:
    rows = base_rows()
    rows[2] = row("2024-02-01", "2024-03-12", "9999-12-31", extreme)  # February, first printed with the March release
    result = ingest(rows)
    assert result.state is QualityState.READY and "MALFORMED_VALUE" in codes(result)
    output = replay(result, datetime(2024, 4, 20, tzinfo=UTC))
    feb = next(item["event"] for item in output["events"] if item["event"]["reference_period"] == "2024-02-01")
    assert feb["status"] == "ACTUAL_UNKNOWN" and feb["derived_change_pct"] is None
    assert PointInTimeStore(result).value(date(2024, 2, 1), APR_RELEASE).status is Visibility.UNKNOWN
    # January, before February's bad print, is untouched.
    assert PointInTimeStore(result).value(date(2024, 1, 1), MAR_RELEASE).value == Decimal("300.2")


def test_quality_findings_are_part_of_the_dataset_identity() -> None:
    at = datetime(2024, 4, 20, tzinfo=UTC)
    clean = replay(ingest(), at)
    duplicated = replay(ingest(base_rows() + [base_rows()[0]]), at)
    assert clean["inputs"] == duplicated["inputs"]
    assert clean["dataset_id"] != duplicated["dataset_id"]
