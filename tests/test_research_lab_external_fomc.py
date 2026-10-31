"""BTC Research Engine V1.2: FOMC statements as point-in-time events.

Synthetic pages imitate the federalreserve.gov press releases (date line, "For release at",
title, statement text, "Last Update"); ranges, times and dates are the real ones of the
named statements, the remaining text is made up. No test needs the network.
"""
from __future__ import annotations

import ast
import io
import urllib.error
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.research_lab.data.store import HoldoutLocked
from src.research_lab.external.alfred import RawBundle
from src.research_lab.external.align import WindowStatus
from src.research_lab.external.fomc import (
    SOURCE,
    SOURCE_IDENTIFIER,
    Decision,
    FomcAvailability,
    FomcStore,
    StatementStatus,
    list_name,
    list_statement_links,
    parse_fomc_bundle,
    read_statement,
    release_instant,
    run_fomc_replay,
    statement_name,
)
from src.research_lab.external.fomc_live import (
    FIXTURE_2019_2020,
    FomcIngestError,
    PageMissing,
    StatementWindow,
    check_window,
    http_page_fetcher,
    ingest_fomc_live,
    list_url,
    load_fomc_ingest,
)
from src.research_lab.external.records import QualityState
from src.research_lab.external.replay import ReplayConfig
from src.research_lab.external.store import RawPayloadStore
from tests.test_research_lab_external import klines

UTC = timezone.utc
HOUR = 3_600_000
INGESTED = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")

DECIDED = "Consistent with its statutory mandate, the Committee decided to {verb} the target range for the federal funds rate to {range} percent."
DISSENT = "Voting against the action was James Bullard, who preferred at this meeting to lower the target range for the federal funds rate to {range} percent."

# Real dates, times and ranges of the 2019-2020 statements (text around them is synthetic).
STATEMENTS_2020 = {
    date(2020, 1, 29): ("2:00 p.m. EST", DECIDED.format(verb="maintain", range="1-1/2 to 1-3/4").replace("to 1-1/2", "at 1-1/2")),
    date(2020, 3, 3): ("10:00 a.m. EST", "The Federal Open Market Committee decided today to lower the target range for the federal funds rate by 1/2 percentage point, to 1 to 1‑1/4 percent."),
    date(2020, 3, 15): ("5:00 p.m. EDT", DECIDED.format(verb="lower", range="0 to 1/4")),
    date(2020, 3, 23): ("8:00 a.m. EDT", "The Committee will continue to maintain the federal funds rate in a target range of 0 to 1/4 percent."),
}


def long_date(day: date) -> str:
    return f"{MONTHS[day.month - 1]} {day.day:02d}, {day.year}"


def statement_page(day: date, release: str | None, *sentences: str, last_update: date | None = None, page_day: date | None = None) -> bytes:
    release_line = f'<p class="releaseTime">For release at {release}</p>' if release else ""
    body = "".join(f"<p>{sentence}</p>" for sentence in sentences)
    return f"""<!DOCTYPE html><html><head><title>Federal Reserve Board - Federal Reserve issues FOMC statement</title>
<script>var x = "For release at 9:99 p.m. EDT";</script></head><body>
<nav><a href="/newsevents/pressreleases.htm">Press Releases</a></nav>
<div id="article"><div class="heading col-xs-12"><p class="article__time">{long_date(page_day or day)}</p>
<h3 class="title"><em>Federal Reserve issues FOMC statement</em></h3>{release_line}</div>
<div class="col-xs-12 col-sm-8 col-md-8">{body}
<p>Implementation Note issued {long_date(day)}</p></div></div>
<div class="lastUpdate">Last Update:
 {long_date(last_update or day)}</div></body></html>""".encode()


def list_page(*days: date, extra: str = "") -> bytes:
    rows = "".join(
        f'<div class="row"><div class="col-xs-3"><time>{d.month}/{d.day}/{d.year}</time></div><div class="col-xs-9">'
        f'<p><a href="/newsevents/pressreleases/monetary{d:%Y%m%d}a.htm"><em>Federal Reserve issues FOMC statement</em></a></p>'
        f'<p><a href="/newsevents/pressreleases/monetary{d:%Y%m%d}b.htm"><em>Federal Reserve Board and Federal Open Market Committee release economic projections</em></a></p></div></div>'
        for d in days
    )
    return f"<html><body><div id='article'>{rows}</div>{extra}</body></html>".encode()


def statement_url(day: date) -> str:
    return f"https://www.federalreserve.gov/newsevents/pressreleases/monetary{day:%Y%m%d}a.htm"


def make_bundle(pages: dict[int, dict[date, bytes | int]], *, ingested_at: datetime = INGESTED, extra_list: str = "") -> RawBundle:
    """pages: year -> {release day -> page bytes, or an HTTP status for a failed retrieval}."""
    payloads: dict[str, bytes] = {}
    requests: dict[str, dict[str, str]] = {}
    for year, days in pages.items():
        payloads[list_name(year)] = list_page(*sorted(days), extra=extra_list)
        requests[list_name(year)] = {"url": list_url(year), "status": "200"}
        for day, page in days.items():
            url = statement_url(day)
            if isinstance(page, int):
                requests[statement_name(url)] = {"url": url, "status": f"HTTP {page}"}
            else:
                payloads[statement_name(url)] = page
                requests[statement_name(url)] = {"url": url, "status": "200"}
    return RawBundle(SOURCE, SOURCE_IDENTIFIER, payloads, ingested_at, requests)


def pages_2020(**overrides: bytes | int) -> dict[int, dict[date, bytes | int]]:
    days: dict[date, bytes | int] = {day: statement_page(day, release, text) for day, (release, text) in STATEMENTS_2020.items()}
    for key, value in overrides.items():
        days[date.fromisoformat(key)] = value
    return {2020: days}


def ingest(**overrides: bytes | int):
    return parse_fomc_bundle(make_bundle(pages_2020(**overrides)))


def event(result, day: date):
    return next(item for item in result.events if item.release_date == day)


# --- page reading ------------------------------------------------------------------------------


def test_release_line_and_ranges_in_the_variants_of_the_real_pages() -> None:
    page = read_statement(statement_page(date(2020, 3, 3), "10:00 a.m. EST", STATEMENTS_2020[date(2020, 3, 3)][1]))
    assert page.release_times == (("10:00 a.m.", "EST"),)
    assert page.page_date == date(2020, 3, 3)
    assert page.last_update == date(2020, 3, 3)
    # U+2011 inside "1-1/4" and "by 1/2 percentage point" before the range.
    assert page.ranges == ((Decimal("1"), Decimal("1.25")),)
    for text, expected in (
        (DECIDED.format(verb="raise", range="3/4 to 1"), (Decimal("0.75"), Decimal("1"))),
        (DECIDED.format(verb="raise", range="5-1/4 to 5-1/2"), (Decimal("5.25"), Decimal("5.5"))),
        (DECIDED.format(verb="lower", range="0 to 1/4"), (Decimal("0"), Decimal("0.25"))),
        ("The Committee decided to maintain the target range for the federal funds rate at 2 percent to 2-1/4 percent.", (Decimal("2"), Decimal("2.25"))),
        (STATEMENTS_2020[date(2020, 3, 23)][1], (Decimal("0"), Decimal("0.25"))),
    ):
        assert read_statement(statement_page(date(2020, 1, 29), "2:00 p.m. EST", text)).ranges == (expected,)


def test_script_text_is_not_read_as_a_release_line() -> None:
    page = read_statement(statement_page(date(2020, 1, 29), None, "No time here."))
    assert page.release_times == () and not page.release_line_unreadable


def test_dissent_ranges_are_not_the_decision() -> None:
    page = read_statement(statement_page(date(2019, 9, 18), "2:00 p.m. EDT", DECIDED.format(verb="lower", range="1-3/4 to 2"), DISSENT.format(range="1-1/2 to 1-3/4"),
                                         "Esther L. George and Eric S. Rosengren, who preferred to maintain the target range at 2 percent to 2-1/4 percent."))
    assert page.ranges == ((Decimal("1.75"), Decimal("2")),)


def test_two_decision_ranges_are_range_unknown() -> None:
    page = statement_page(date(2020, 1, 29), "2:00 p.m. EST", DECIDED.format(verb="maintain", range="1-1/2 to 1-3/4"), "The Committee also set the federal funds rate to 2 to 2-1/4 percent.")
    result = ingest(**{"2020-01-29": page})
    assert result.state is QualityState.READY
    assert event(result, date(2020, 1, 29)).status is StatementStatus.RANGE_UNKNOWN
    assert event(result, date(2020, 1, 29)).target_low is None


def test_list_takes_only_statement_links_and_both_url_schemes() -> None:
    payload = b"""<a href="/newsevents/press/monetary/20170315a.htm">Federal Reserve issues FOMC statement</a>
    <a href="https://www.federalreserve.gov/newsevents/pressreleases/monetary20170503a.htm"><em>Federal Reserve issues  FOMC statement</em></a>
    <a href="/newsevents/pressreleases/monetary20170503a1.htm">Federal Reserve issues FOMC statement</a>
    <a href="https://evil.example/newsevents/pressreleases/monetary20170614a.htm">Federal Reserve issues FOMC statement</a>
    <a href="/newsevents/pressreleases/monetary20170614b.htm">Minutes of the Federal Open Market Committee</a>"""
    assert list_statement_links(payload) == [
        ("https://www.federalreserve.gov/newsevents/press/monetary/20170315a.htm", date(2017, 3, 15)),
        ("https://www.federalreserve.gov/newsevents/pressreleases/monetary20170503a.htm", date(2017, 5, 3)),
    ]


# --- time zone and daylight saving -------------------------------------------------------------


def test_release_time_is_new_york_time_with_the_dst_label_of_that_day() -> None:
    assert release_instant(date(2020, 3, 3), "10:00 a.m.", "EST") == datetime(2020, 3, 3, 15, 0, tzinfo=UTC)
    assert release_instant(date(2020, 3, 15), "5:00 p.m.", "EDT") == datetime(2020, 3, 15, 21, 0, tzinfo=UTC)
    assert release_instant(date(2020, 3, 3), "10:00 a.m.", "EDT") is None  # EDT starts 2020-03-08
    assert release_instant(date(2020, 3, 8), "2:30 a.m.", "EDT") is None  # skipped by spring-forward
    assert release_instant(date(2020, 3, 3), "13:00 p.m.", "EST") is None


def test_wrong_zone_label_is_event_time_inconsistent_and_fails_closed() -> None:
    result = ingest(**{"2020-03-03": statement_page(date(2020, 3, 3), "10:00 a.m. EDT", STATEMENTS_2020[date(2020, 3, 3)][1])})
    item = event(result, date(2020, 3, 3))
    assert item.status is StatementStatus.EVENT_TIME_INCONSISTENT
    assert item.event_time is None
    assert item.availability_basis is FomcAvailability.END_OF_RELEASE_DAY
    assert item.available_at == datetime(2020, 3, 4, 5, 0, tzinfo=UTC)  # midnight New York (EST)
    assert item.decision is Decision.NOT_DETERMINED


def test_repeated_or_unreadable_release_line_is_inconsistent() -> None:
    twice = statement_page(date(2020, 3, 3), "10:00 a.m. EST", "For release at 11:00 a.m. EST", STATEMENTS_2020[date(2020, 3, 3)][1])
    garbled = statement_page(date(2020, 3, 3), "10 a.m. Eastern", STATEMENTS_2020[date(2020, 3, 3)][1])
    for page in (twice, garbled):
        assert event(ingest(**{"2020-03-03": page}), date(2020, 3, 3)).status is StatementStatus.EVENT_TIME_INCONSISTENT


def test_missing_release_line_is_event_time_unknown_visible_at_end_of_day() -> None:
    result = ingest(**{"2020-03-15": statement_page(date(2020, 3, 15), None, STATEMENTS_2020[date(2020, 3, 15)][1])})
    item = event(result, date(2020, 3, 15))
    assert item.status is StatementStatus.EVENT_TIME_UNKNOWN
    end_of_day = datetime(2020, 3, 16, 4, 0, tzinfo=UTC)  # midnight New York (EDT)
    assert item.available_at == end_of_day
    store = FomcStore(result)
    assert item not in store.visible(end_of_day - timedelta(seconds=1))
    assert item in store.visible(end_of_day)


# --- point in time -----------------------------------------------------------------------------


def test_statement_is_invisible_one_second_before_its_release_and_visible_at_it() -> None:
    result = ingest()
    item = event(result, date(2020, 3, 15))
    assert item.status is StatementStatus.OK
    assert item.event_time == item.available_at == datetime(2020, 3, 15, 21, 0, tzinfo=UTC)
    store = FomcStore(result)
    assert item not in store.visible(item.event_time - timedelta(seconds=1))
    assert item in store.visible(item.event_time)
    assert store.current_range(item.event_time - timedelta(seconds=1))["target_low"] == "1"
    assert store.current_range(item.event_time)["target_low"] == "0"


def test_unscheduled_sunday_and_morning_statements_and_a_statement_without_change() -> None:
    result = ingest()
    assert [e.release_date for e in result.events] == sorted(STATEMENTS_2020)
    march3, march15, march23 = (event(result, date(2020, 3, d)) for d in (3, 15, 23))
    assert march3.event_time == datetime(2020, 3, 3, 15, 0, tzinfo=UTC)
    assert (march3.decision, march3.change_bp) == (Decision.LOWER, -50)
    assert march15.release_date.weekday() == 6  # Sunday
    assert (march15.previous_low, march15.previous_high, march15.target_low, march15.target_high) == (Decimal("1"), Decimal("1.25"), Decimal("0"), Decimal("0.25"))
    assert (march15.decision, march15.change_bp) == (Decision.LOWER, -100)
    assert march23.event_time == datetime(2020, 3, 23, 12, 0, tzinfo=UTC)
    assert (march23.decision, march23.change_bp) == (Decision.MAINTAIN, 0)
    first = event(result, date(2020, 1, 29))
    assert (first.previous_low, first.decision) == (None, Decision.NOT_DETERMINED)  # nothing before it in this bundle


def test_a_statement_that_is_not_ok_makes_the_next_previous_range_unknown() -> None:
    result = ingest(**{"2020-03-15": statement_page(date(2020, 3, 15), None, STATEMENTS_2020[date(2020, 3, 15)][1])})
    march23 = event(result, date(2020, 3, 23))
    assert march23.status is StatementStatus.OK
    assert (march23.previous_low, march23.decision, march23.change_bp) == (None, Decision.NOT_DETERMINED, None)


def test_failed_retrieval_is_missing_statement_and_still_counted() -> None:
    result = ingest(**{"2020-03-15": 404})
    item = event(result, date(2020, 3, 15))
    assert item.status is StatementStatus.MISSING_STATEMENT
    assert item.payload_sha256 is None and item.event_time is None
    assert any(i.issue.code == "MISSING_STATEMENT" for i in result.issues)


def test_page_date_that_differs_from_the_listed_date_is_source_conflict() -> None:
    page = statement_page(date(2020, 3, 15), "5:00 p.m. EDT", STATEMENTS_2020[date(2020, 3, 15)][1], page_day=date(2020, 3, 16))
    assert event(ingest(**{"2020-03-15": page}), date(2020, 3, 15)).status is StatementStatus.SOURCE_CONFLICT


def test_later_last_update_is_document_updated_and_leaves_an_earlier_replay_unchanged() -> None:
    updated = statement_page(date(2020, 3, 23), "8:00 a.m. EDT", STATEMENTS_2020[date(2020, 3, 23)][1], last_update=date(2021, 2, 1))
    result = ingest(**{"2020-03-23": updated})
    assert event(result, date(2020, 3, 23)).status is StatementStatus.DOCUMENT_UPDATED
    before = ReplayConfig(replay_at=datetime(2020, 3, 20, tzinfo=UTC))
    candles = klines(datetime(2020, 1, 1, tzinfo=UTC), 24 * 80)
    assert run_fomc_replay(result, candles, before)["content_hash"] == run_fomc_replay(ingest(), candles, before)["content_hash"]
    after = ReplayConfig(replay_at=datetime(2020, 4, 1, tzinfo=UTC))
    assert run_fomc_replay(result, candles, after)["content_hash"] != run_fomc_replay(ingest(), candles, after)["content_hash"]


def test_statement_known_only_after_download_is_rejected() -> None:
    result = parse_fomc_bundle(make_bundle(pages_2020(), ingested_at=datetime(2020, 3, 15, 20, 0, tzinfo=UTC)))
    assert date(2020, 3, 15) not in {e.release_date for e in result.events}
    assert any(i.issue.code == "AVAILABLE_AFTER_INGESTION" for i in result.issues)
    assert result.coverage_end == datetime(2020, 3, 15, 20, 0, tzinfo=UTC)


# --- payload-level fail-closed -----------------------------------------------------------------


def test_page_that_is_not_a_statement_makes_the_bundle_not_ready() -> None:
    result = ingest(**{"2020-03-15": b"<html><body><p>Page not found</p></body></html>"})
    assert result.state is QualityState.NOT_READY and result.events == ()
    with pytest.raises(ValueError):
        FomcStore(result)


def test_unlisted_or_unrequested_payloads_make_the_bundle_not_ready() -> None:
    raw = make_bundle(pages_2020())
    raw.payloads["statement-monetary20200401a"] = statement_page(date(2020, 4, 1), "2:00 p.m. EDT", "x")
    assert parse_fomc_bundle(raw).state is QualityState.NOT_READY
    raw = make_bundle(pages_2020())
    del raw.requests[statement_name(statement_url(date(2020, 3, 3)))]
    assert parse_fomc_bundle(raw).state is QualityState.NOT_READY
    raw = make_bundle(pages_2020())
    raw.payloads[list_name(2020)] = b"<html><body>empty</body></html>"
    assert parse_fomc_bundle(raw).state is QualityState.NOT_READY


def test_not_ready_replay_reads_no_inputs() -> None:
    result = ingest(**{"2020-03-15": b"<html></html>"})
    out = run_fomc_replay(result, [], ReplayConfig(replay_at=datetime(2020, 6, 1, tzinfo=UTC)))
    assert out["state"] == "NOT_READY" and out["events"] == []


# --- holdout -----------------------------------------------------------------------------------


def test_holdout_is_locked_in_window_bundle_store_and_replay() -> None:
    with pytest.raises(HoldoutLocked):
        StatementWindow("too-far", 2016, 2025)
    assert parse_fomc_bundle(make_bundle({2025: {date(2025, 1, 29): statement_page(date(2025, 1, 29), "2:00 p.m. EST", "x")}})).state is QualityState.NOT_READY
    store = FomcStore(ingest())
    with pytest.raises(HoldoutLocked):
        store.visible(datetime(2025, 1, 1, tzinfo=UTC))
    with pytest.raises(HoldoutLocked):
        store.current_range(datetime(2025, 1, 1, tzinfo=UTC))
    with pytest.raises(HoldoutLocked):
        run_fomc_replay(ingest(), [], ReplayConfig(replay_at=datetime(2025, 1, 1, tzinfo=UTC)))


def test_links_to_other_years_are_neither_fetched_nor_used(tmp_path: Path) -> None:
    recent = '<aside><a href="/newsevents/pressreleases/monetary20250129a.htm">Federal Reserve issues FOMC statement</a></aside>'
    fetched: list[str] = []
    lists = {list_url(2019): list_page(date(2019, 12, 11), extra=recent), list_url(2020): list_page(date(2020, 1, 29), extra=recent)}

    def fetcher(url: str) -> tuple[bytes, str]:
        fetched.append(url)
        if url in lists:
            return lists[url], url
        day = datetime.strptime(url[-13:-5], "%Y%m%d").date()
        return statement_page(day, "2:00 p.m. EST", DECIDED.format(verb="maintain", range="1-1/2 to 1-3/4")), url

    store = RawPayloadStore(tmp_path)
    bundle_id = ingest_fomc_live(FIXTURE_2019_2020, store=store, fetcher=fetcher, clock=lambda: INGESTED)
    assert not any("2025" in url for url in fetched)
    _, result = load_fomc_ingest(store, bundle_id, FIXTURE_2019_2020)
    assert result.state is QualityState.READY
    assert [e.release_date for e in result.events] == [date(2019, 12, 11), date(2020, 1, 29)]
    assert {i.issue.code for i in result.issues} >= {"LIST_LINK_OUTSIDE_YEAR"}


# --- determinism and replay --------------------------------------------------------------------


def test_replay_is_deterministic_and_independent_of_page_order() -> None:
    raw = make_bundle(pages_2020())
    reversed_raw = RawBundle(raw.source, raw.source_identifier, dict(reversed(list(raw.payloads.items()))), raw.ingested_at, dict(reversed(list(raw.requests.items()))))
    config = ReplayConfig(replay_at=datetime(2020, 4, 1, tzinfo=UTC))
    candles = klines(datetime(2020, 1, 1, tzinfo=UTC), 24 * 100)
    first = run_fomc_replay(parse_fomc_bundle(raw), candles, config)
    again = run_fomc_replay(parse_fomc_bundle(raw), candles, config)
    other = run_fomc_replay(parse_fomc_bundle(reversed_raw), candles, config)
    assert first == again
    assert (first["dataset_id"], first["content_hash"], first["output_hash"]) == (other["dataset_id"], other["content_hash"], other["output_hash"])
    later = make_bundle(pages_2020(), ingested_at=INGESTED + timedelta(days=1))
    relabeled = run_fomc_replay(parse_fomc_bundle(later), candles, config)
    assert (relabeled["dataset_id"], relabeled["content_hash"]) == (first["dataset_id"], first["content_hash"])
    assert relabeled["output_hash"] != first["output_hash"]  # provenance differs truthfully


def test_btc_windows_for_a_sunday_statement_and_excluded_candles() -> None:
    candles = klines(datetime(2020, 3, 10, tzinfo=UTC), 24 * 20)
    release = datetime(2020, 3, 15, 21, 0, tzinfo=UTC)
    broken = int((release + timedelta(hours=2)).timestamp() * 1000)
    candles = [k if k.open_time != broken else type(k)(k.open_time, k.open, k.high, k.low, k.close, k.volume, k.close_time - 1, k.taker_buy_volume) for k in candles]
    config = ReplayConfig(replay_at=datetime(2020, 3, 30, tzinfo=UTC), interval="1h", invalid_candles="exclude")
    out = run_fomc_replay(ingest(), candles, config)
    row = next(item for item in out["events"] if item["event"]["release_date"] == "2020-03-15")
    assert row["btc"]["status"] == "ALIGNED"
    assert row["btc"]["anchor"]["open_time"] == "2020-03-15T20:00:00+00:00"
    assert row["btc"]["windows"]["1h"]["status"] == WindowStatus.COMPLETE
    assert row["btc"]["windows"]["4h"]["status"] == WindowStatus.INSUFFICIENT_DATA  # excluded candle inside
    assert row["btc"]["windows"]["5m"]["status"] == WindowStatus.RESOLUTION_TOO_COARSE
    assert out["inputs"]["btc_excluded"] == [{"open_time_ms": broken, "reason": "WRONG_SPAN"}]


def test_statement_that_is_not_ok_gets_no_btc_windows() -> None:
    result = ingest(**{"2020-03-15": statement_page(date(2020, 3, 15), "5:00 p.m. EST", STATEMENTS_2020[date(2020, 3, 15)][1])})
    out = run_fomc_replay(result, klines(datetime(2020, 3, 10, tzinfo=UTC), 24 * 20), ReplayConfig(replay_at=datetime(2020, 3, 30, tzinfo=UTC)))
    row = next(item for item in out["events"] if item["event"]["release_date"] == "2020-03-15")
    assert row["btc"] == {"event_id": row["event"]["event_id"], "interval": "1h", "status": "EVENT_NOT_OK", "event_status": "EVENT_TIME_INCONSISTENT", "anchor": None, "windows": {}}


def test_replay_after_coverage_end_is_insufficient_data() -> None:
    result = parse_fomc_bundle(make_bundle(pages_2020(), ingested_at=datetime(2020, 3, 20, tzinfo=UTC)))
    out = run_fomc_replay(result, klines(datetime(2020, 3, 1, tzinfo=UTC), 24 * 40), ReplayConfig(replay_at=datetime(2020, 4, 1, tzinfo=UTC)))
    assert out["state"] == "INSUFFICIENT_DATA"
    assert "2020-03-23" not in {row["event"]["release_date"] for row in out["events"]}


# --- download path -----------------------------------------------------------------------------


class _Response(io.BytesIO):
    def __init__(self, body: bytes, url: str) -> None:
        super().__init__(body)
        self._url = url

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def test_fetcher_only_contacts_the_fed_host_and_records_same_host_redirects() -> None:
    fetch = http_page_fetcher(opener=lambda request, timeout: _Response(b"ok", "https://www.federalreserve.gov/newsevents/pressreleases/monetary20170315a.htm"))
    assert fetch("https://www.federalreserve.gov/newsevents/press/monetary/20170315a.htm") == (b"ok", "https://www.federalreserve.gov/newsevents/pressreleases/monetary20170315a.htm")
    with pytest.raises(FomcIngestError):
        fetch("http://www.federalreserve.gov/x.htm")
    with pytest.raises(FomcIngestError):
        fetch("https://www.federalreserve.gov.evil.example/x.htm")
    off_host = http_page_fetcher(opener=lambda request, timeout: _Response(b"ok", "https://evil.example/x.htm"))
    with pytest.raises(FomcIngestError):
        off_host("https://www.federalreserve.gov/x.htm")


def test_fetcher_reports_missing_pages_and_retries_server_errors() -> None:
    calls: list[int] = []

    def opener(request, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(request.full_url, 404 if len(calls) == 1 else 503, "x", None, None)

    fetch = http_page_fetcher(opener=opener, sleep=lambda _: None, attempts=3)
    with pytest.raises(PageMissing):
        fetch("https://www.federalreserve.gov/a.htm")
    with pytest.raises(FomcIngestError, match="HTTP 503 after 3 attempt"):
        fetch("https://www.federalreserve.gov/b.htm")


def test_window_check_refuses_other_lists_and_hosts() -> None:
    raw = make_bundle({2019: {date(2019, 12, 11): statement_page(date(2019, 12, 11), "2:00 p.m. EST", "x")}})
    with pytest.raises(FomcIngestError):
        check_window(raw, FIXTURE_2019_2020)  # 2020 list missing
    raw = make_bundle(pages_2020() | {2019: {date(2019, 12, 11): statement_page(date(2019, 12, 11), "2:00 p.m. EST", "x")}})
    check_window(raw, FIXTURE_2019_2020)
    raw.requests[statement_name(statement_url(date(2020, 3, 3)))]["final_url"] = "https://evil.example/x"
    with pytest.raises(FomcIngestError):
        check_window(raw, FIXTURE_2019_2020)


# --- isolation ---------------------------------------------------------------------------------


def test_nothing_outside_the_research_lab_imports_the_fomc_modules() -> None:
    offenders = []
    for path in Path("src").rglob("*.py"):
        if path.is_relative_to(Path("src/research_lab")):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            if any("research_lab.external.fomc" in name for name in names):
                offenders.append(str(path))
    assert offenders == []


def test_fomc_modules_import_only_research_lab_and_standard_library() -> None:
    for name in ("fomc.py", "fomc_live.py"):
        tree = ast.parse(Path("src/research_lab/external", name).read_text(encoding="utf-8"))
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {a.name for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names}
        assert all(module is None or module.startswith(("src.research_lab", "src.quality", "src.research_ops.audit")) or "." not in module or module.split(".")[0] in {"urllib", "html", "datetime", "collections", "dataclasses", "decimal", "enum", "typing", "zoneinfo", "pathlib"} for module in modules), modules


# --- real-data verification helpers --------------------------------------------------------------


def test_fred_cross_check_finds_same_day_next_day_and_mismatch() -> None:
    from src.research_lab.external.fomc_verify import fred_cross_check, fred_values

    result = ingest()
    upper = fred_values(b'{"observations": [{"date": "2020-01-29", "value": "1.75"}, {"date": "2020-03-03", "value": "1.75"}, {"date": "2020-03-04", "value": "1.25"},'
                        b' {"date": "2020-03-16", "value": "0.25"}, {"date": "2020-03-23", "value": "0.50"}, {"date": "2020-03-24", "value": "."}]}')
    lower = {day: value - Decimal("0.25") for day, value in upper.items()}
    checks = {item["event_id"][5:15]: item["result"] for item in fred_cross_check(result.events, upper, lower)}
    assert checks == {"2020-01-29": "MATCH_SAME_DAY", "2020-03-03": "MATCH_NEXT_DAY", "2020-03-15": "MATCH_NEXT_DAY", "2020-03-23": "MISMATCH"}


def test_summary_report_and_replay_checks_on_a_synthetic_download() -> None:
    from src.research_lab.external.fomc_verify import render_markdown, replay_checks, summary

    raw = make_bundle(pages_2020(**{"2020-03-15": 404}))
    result = parse_fomc_bundle(raw)
    facts = summary(raw, result)
    assert facts["statements_per_year"] == {"2020": 4}
    assert facts["status_counts"] == {"MISSING_STATEMENT": 1, "OK": 3}
    assert facts["not_2pm_releases"] == ["FOMC:2020-03-03:monetary20200303a", "FOMC:2020-03-23:monetary20200323a"]
    checks = replay_checks(raw, result, klines(datetime(2019, 12, 1, tzinfo=UTC), 24 * 200))
    assert checks["all_checks_pass"], checks
    text = render_markdown({"bundle_id": "x", "ingested_at": "t", "summary": facts, "fred_cross_check": None, "replay": checks})
    assert "MISSING_STATEMENT" in text and "no_lookahead: PASS" in text


def test_range_that_does_not_increase_is_range_unknown() -> None:
    page = statement_page(date(2020, 3, 15), "5:00 p.m. EDT", DECIDED.format(verb="lower", range="1/4 to 0"))
    item = event(ingest(**{"2020-03-15": page}), date(2020, 3, 15))
    assert item.status is StatementStatus.RANGE_UNKNOWN and item.event_time is None


def test_release_line_split_over_two_lines_is_read() -> None:
    page = statement_page(date(2020, 3, 15), "<br>5:00 p.m.\n EDT", STATEMENTS_2020[date(2020, 3, 15)][1])
    assert read_statement(page).release_times == (("5:00 p.m.", "EDT"),)


def test_ignored_links_of_other_years_do_not_reveal_their_dates() -> None:
    recent = '<a href="/newsevents/pressreleases/monetary20250129a.htm">Federal Reserve issues FOMC statement</a>'
    result = parse_fomc_bundle(make_bundle(pages_2020(), extra_list=recent))
    found = [i for i in result.issues if i.issue.code == "LIST_LINK_OUTSIDE_YEAR"]
    assert len(found) == 1 and "2025" not in found[0].issue.detail + found[0].issue.record_id


def test_page_bytes_that_change_without_changing_facts_keep_the_dataset_identity() -> None:
    changed = pages_2020()
    changed[2020] = {day: page.replace(b"<nav>", b"<nav><!-- build 42 -->") for day, page in changed[2020].items()}
    config = ReplayConfig(replay_at=datetime(2020, 4, 1, tzinfo=UTC))
    candles = klines(datetime(2020, 1, 1, tzinfo=UTC), 24 * 100)
    first, second = (run_fomc_replay(parse_fomc_bundle(make_bundle(pages)), candles, config) for pages in (pages_2020(), changed))
    assert (first["dataset_id"], first["content_hash"]) == (second["dataset_id"], second["content_hash"])
    assert first["output_hash"] != second["output_hash"]
