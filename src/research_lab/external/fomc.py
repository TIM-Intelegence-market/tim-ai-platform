"""FOMC statements as point-in-time events (docs/research_lab/EXTERNAL_DATA.md, section FOMC).

The event is the publication of an FOMC statement, not the meeting and not the
decision: the decision is public only from the time in the statement's own
"For release at" line. The source is the Federal Reserve's press release page
of each statement; the yearly press release lists say which statements exist.

Flow: stored raw pages (``RawBundle``) -> ``parse_fomc_bundle`` (page parsing,
quality states) -> ``FomcStore`` (what was known when, holdout-locked) ->
``run_fomc_replay`` (deterministic research dataset with BTC windows).

Nothing is guessed. A release time comes only from the page, checked against the
New York daylight-saving rule of that day; without it the event is visible from
the end of its release day and gets no BTC windows. A statement that is not
``OK`` stays visible and counted, but has no event time, no decision and no
windows. Nothing here forecasts, scores or trades.
"""
from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

from src.quality.framework import QualityIssue, Severity
from src.research_lab.data.parse import Kline
from src.research_lab.data.store import HoldoutLocked, HoldoutPermission
from src.research_lab.external.align import BtcSeries, align_event
from src.research_lab.external.alfred import RawBundle
from src.research_lab.external.records import DatedIssue, QualityState, decimal_str, iso, require_utc, utc_to_ms
from src.research_lab.external.replay import MODE, ReplayConfig, _finish
from src.research_lab.protocol import HOLDOUT_START_MS, PROTOCOL_VERSION
from src.research_ops.audit import digest

SOURCE = "FEDERAL_RESERVE"
SOURCE_IDENTIFIER = "FOMC_STATEMENTS"
EVENT_TYPE = "FOMC_STATEMENT"
# Bump when page parsing, quality states, availability rules or output layout change.
PARSER_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"
HOST = "https://www.federalreserve.gov"
NEW_YORK = ZoneInfo("America/New_York")
STATEMENT_TITLE = "Federal Reserve issues FOMC statement"
HOLDOUT_START = datetime.fromtimestamp(HOLDOUT_START_MS / 1000, tz=timezone.utc).date()
RECORD_TYPE = "PolicyStatementEvent"

SOURCE_INFO = {
    "source": SOURCE,
    "source_identifier": SOURCE_IDENTIFIER,
    "event_type": EVENT_TYPE,
    "publisher": "Board of Governors of the Federal Reserve System (FOMC)",
    "distributor": "www.federalreserve.gov press releases",
    "release_timezone": "America/New_York",
    "parser_version": PARSER_VERSION,
}

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
_DATE = rf"({'|'.join(_MONTHS)}) (\d{{1,2}}), (\d{{4}})"
DATE_RE = re.compile(rf"\b{_DATE}\b")
RELEASE_RE = re.compile(r"For release at\s+(\d{1,2}):(\d{2})\s+([ap])\.m\.\s+(EST|EDT)\b")
LAST_UPDATE_RE = re.compile(rf"Last Update:\s*{_DATE}")
_NUMBER = r"\d+-\d+/\d+|\d+/\d+|\d+"
# "3/4 to 1 percent", "1 to 1-1/4 percent", "2 percent to 2-1/4 percent", "0 to 1/4 percent".
RANGE_RE = re.compile(rf"(?<![\d/-])({_NUMBER})(?: percent)? to ({_NUMBER}) percent\b")
# Statement links in the yearly lists: current scheme and the pre-2018 scheme (both seen on federalreserve.gov).
STATEMENT_PATH_RE = re.compile(r"^(?:https://www\.federalreserve\.gov)?(/newsevents/(?:pressreleases/monetary|press/monetary/)(\d{8})a\.htm)$")
# Sentences that state what a dissenting member preferred are not the decision.
_DISSENT = ("preferred", "dissent", "voting against")
# Hyphens and spaces the pages use inside numbers ("1-1/4" is written with U+2011 on some pages).
_TRANSLATE = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", " ": " ", " ": " "})


class StatementStatus(StrEnum):
    OK = "OK"
    EVENT_TIME_UNKNOWN = "EVENT_TIME_UNKNOWN"  # no "For release at" line
    EVENT_TIME_INCONSISTENT = "EVENT_TIME_INCONSISTENT"  # unreadable, several times, or zone label wrong for that day
    RANGE_UNKNOWN = "RANGE_UNKNOWN"  # no target range or more than one in the decision sentences
    SOURCE_CONFLICT = "SOURCE_CONFLICT"  # page date differs from the date in the list link
    DOCUMENT_UPDATED = "DOCUMENT_UPDATED"  # "Last Update" after the release day, or missing
    MISSING_STATEMENT = "MISSING_STATEMENT"  # listed, but the page could not be retrieved


class StatementKind(StrEnum):
    SCHEDULED_MEETING = "SCHEDULED_MEETING"
    UNSCHEDULED_MEETING = "UNSCHEDULED_MEETING"
    # V1.2 loads no meeting calendar (the current one reaches into the holdout), so the kind stays unknown.
    UNKNOWN_KIND = "UNKNOWN_KIND"


class Decision(StrEnum):
    RAISE = "RAISE"
    LOWER = "LOWER"
    MAINTAIN = "MAINTAIN"
    NOT_DETERMINED = "NOT_DETERMINED"  # this or the previous statement has no usable range


class FomcAvailability(StrEnum):
    STATED_RELEASE_TIME = "STATED_RELEASE_TIME"
    # No usable release time: known only after the release day ended in New York (conservative).
    END_OF_RELEASE_DAY = "END_OF_RELEASE_DAY"


@dataclass(frozen=True, slots=True)
class StatementPage:
    """What one statement page says, before any judgement."""

    is_statement: bool
    page_date: date | None  # date line next to the release line
    release_times: tuple[tuple[str, str], ...]  # every "For release at" as (local time text, zone label)
    release_line_unreadable: bool  # "For release at" present but not in the known form
    last_update: date | None
    ranges: tuple[tuple[Decimal, Decimal], ...]  # distinct target ranges in the decision sentences


@dataclass(frozen=True, slots=True)
class PolicyStatementEvent:
    event_id: str
    release_date: date
    kind: StatementKind
    status: StatementStatus
    release_time_local: str | None  # as written, e.g. "2:00 p.m."
    release_zone_label: str | None  # as written, "EST" or "EDT"
    event_time: datetime | None  # set only when status is OK
    available_at: datetime
    availability_basis: FomcAvailability
    target_low: Decimal | None
    target_high: Decimal | None
    previous_low: Decimal | None
    previous_high: Decimal | None
    decision: Decision
    change_bp: int | None
    url: str
    final_url: str | None
    last_update: date | None
    payload_sha256: str | None
    ingested_at: datetime
    parser_version: str = PARSER_VERSION

    def __post_init__(self) -> None:
        require_utc(self.available_at, "available_at")
        require_utc(self.ingested_at, "ingested_at")
        if self.event_time is not None:
            require_utc(self.event_time, "event_time")
            if self.status is not StatementStatus.OK:
                raise ValueError("only an OK statement has an event time")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": EVENT_TYPE,
            "release_date": self.release_date.isoformat(),
            "kind": self.kind.value,
            "status": self.status.value,
            "release_time_local": self.release_time_local,
            "release_zone_label": self.release_zone_label,
            "event_time": iso(self.event_time),
            "available_at": iso(self.available_at),
            "availability_basis": self.availability_basis.value,
            "target_low": decimal_str(self.target_low),
            "target_high": decimal_str(self.target_high),
            "previous_low": decimal_str(self.previous_low),
            "previous_high": decimal_str(self.previous_high),
            "decision": self.decision.value,
            "change_bp": self.change_bp,
            "url": self.url,
            "final_url": self.final_url,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "payload_sha256": self.payload_sha256,
            "ingested_at": iso(self.ingested_at),
            "parser_version": self.parser_version,
        }


@dataclass(frozen=True, slots=True)
class FomcIngest:
    state: QualityState
    events: tuple[PolicyStatementEvent, ...]  # ordered by available_at, then event_id
    issues: tuple[DatedIssue, ...]
    years: tuple[int, ...]
    coverage_end: datetime  # nothing is known about statements after this instant
    ingested_at: datetime
    payload_hashes: dict[str, str]
    request: dict[str, Any]


# --- page reading -------------------------------------------------------------------------------


class _Page(HTMLParser):
    """Visible text (one line per block element) and links of an HTML page."""

    _SKIP = {"script", "style", "noscript", "head", "template"}
    _BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th", "table", "section", "article", "header", "footer", "nav"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[tuple[str, list[str]]] = []
        self._skip = 0
        self._link: tuple[str, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
        if tag in self._BLOCK:
            self.parts.append("\n")
        if tag == "a":
            self._link = (dict(attrs).get("href") or "", [])
            self.links.append(self._link)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        if tag in self._BLOCK:
            self.parts.append("\n")
        if tag == "a":
            self._link = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.parts.append(data)
        if self._link is not None:
            self._link[1].append(data)


def _read(payload: bytes) -> _Page:
    page = _Page()
    page.feed(payload.decode("utf-8"))  # federalreserve.gov serves UTF-8; anything else fails loudly
    page.close()
    return page


def normalize(text: str) -> str:
    lines = (" ".join(line.translate(_TRANSLATE).split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def page_text(payload: bytes) -> str:
    return normalize("".join(_read(payload).parts))


def list_statement_links(payload: bytes) -> list[tuple[str, date]]:
    """Statement links of one yearly list: (absolute URL, date in the link), in page order, without duplicates."""
    found: list[tuple[str, date]] = []
    for href, parts in _read(payload).links:
        if normalize("".join(parts)) != STATEMENT_TITLE:
            continue
        match = STATEMENT_PATH_RE.match(href.strip())
        if match is None:
            continue
        url = HOST + match.group(1)
        if url not in {item[0] for item in found}:
            found.append((url, _ymd(match.group(2))))
    return found


def read_statement(payload: bytes) -> StatementPage:
    text = page_text(payload)
    times = tuple(dict.fromkeys((f"{int(m.group(1))}:{m.group(2)} {m.group(3)}.m.", m.group(4)) for m in RELEASE_RE.finditer(text)))
    unreadable = text.count("For release at") > len(RELEASE_RE.findall(text))
    first = text.find("For release at")
    page_date = None
    if first >= 0:
        # The date line is the last date printed before the release line (header of the press release).
        dates = list(DATE_RE.finditer(text, 0, first))
        page_date = _long_date(dates[-1]) if dates else None
    updates = LAST_UPDATE_RE.findall(text)
    last_update = max(_long_date_parts(*item) for item in updates) if updates else None
    start = text.find(STATEMENT_TITLE)
    body_start = max(start, first)
    body_end = text.rfind("Last Update:")
    body = text[body_start : body_end if body_end > body_start else len(text)] if start >= 0 else ""
    return StatementPage(
        is_statement=start >= 0,
        page_date=page_date,
        release_times=times,
        release_line_unreadable=unreadable,
        last_update=last_update,
        ranges=_decision_ranges(body),
    )


def _decision_ranges(body: str) -> tuple[tuple[Decimal, Decimal], ...]:
    found: list[tuple[Decimal, Decimal]] = []
    for sentence in re.split(r"(?<=[.;])\s+(?=[A-Z])", body.replace("\n", " ")):
        lowered = sentence.lower()
        if "target range" not in lowered and "federal funds rate" not in lowered:
            continue
        if any(word in lowered for word in _DISSENT):
            continue
        for match in RANGE_RE.finditer(sentence):
            pair = (_rate(match.group(1)), _rate(match.group(2)))
            if pair not in found:
                found.append(pair)
    return tuple(found)


def _rate(text: str) -> Decimal:
    whole, _, fraction = text.rpartition("-") if "-" in text else ("", "", text)
    if "/" in fraction:
        numerator, denominator = fraction.split("/")
        if denominator not in {"2", "4", "8"}:
            raise ValueError(f"unexpected fraction {text!r}")
        value = Decimal(int(numerator) * 1000 // int(denominator)) / 1000
    else:
        value = Decimal(int(fraction))
    return value + (Decimal(int(whole)) if whole else 0)


def _ymd(text: str) -> date:
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def _long_date(match: re.Match[str]) -> date:
    return _long_date_parts(match.group(1), match.group(2), match.group(3))


def _long_date_parts(month: str, day: str, year: str) -> date:
    return date(int(year), _MONTHS.index(month) + 1, int(day))


def release_instant(day: date, local_time: str, zone_label: str) -> datetime | None:
    """The stated time on that day in New York, or None when the zone label contradicts the DST rule
    (e.g. "EDT" on a winter day) or the local time does not exist that day."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2}) ([ap])\.m\.", local_time)
    if match is None:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (1 <= hour <= 12 and minute < 60):
        return None
    hour = hour % 12 + (12 if match.group(3) == "p" else 0)
    local = datetime.combine(day, time(hour, minute), tzinfo=NEW_YORK)
    if local.astimezone(timezone.utc).astimezone(NEW_YORK).replace(tzinfo=None) != local.replace(tzinfo=None):
        return None  # skipped by the spring-forward change
    if local.tzname() != zone_label:
        return None
    return local.astimezone(timezone.utc)


def end_of_day(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time(0), tzinfo=NEW_YORK).astimezone(timezone.utc)


# --- bundle parsing -----------------------------------------------------------------------------


def list_name(year: int) -> str:
    return f"list-{year}"


def statement_name(url: str) -> str:
    return "statement-" + url.rsplit("/", 1)[1].removesuffix(".htm")


def _issue(code: str, severity: Severity, record_id: str, detail: str, available_at: datetime | None = None) -> DatedIssue:
    return DatedIssue(QualityIssue(code, severity, RECORD_TYPE, record_id, detail), available_at)


def bundle_years(bundle: RawBundle) -> tuple[int, ...]:
    years = []
    for name in bundle.requests:
        if name.startswith("list-"):
            years.append(int(name.removeprefix("list-")))
    return tuple(sorted(years))


def parse_fomc_bundle(bundle: RawBundle) -> FomcIngest:
    """Normalize one stored download into point-in-time statement events. Never reads the network."""
    ingested_at = require_utc(bundle.ingested_at, "ingested_at")
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(bundle.payloads.items())}
    issues: list[DatedIssue] = []
    years = bundle_years(bundle)

    def failed(reason: str) -> FomcIngest:
        issues.append(_issue("NOT_READY", Severity.ERROR, "bundle", reason))
        return FomcIngest(QualityState.NOT_READY, (), _sorted(issues), years, ingested_at, ingested_at, hashes, copy.deepcopy(bundle.requests))

    if bundle.source != SOURCE or bundle.source_identifier != SOURCE_IDENTIFIER:
        return failed(f"bundle source {bundle.source}:{bundle.source_identifier} is not {SOURCE}:{SOURCE_IDENTIFIER}")
    if not years:
        return failed("bundle has no yearly press release list")
    if years[-1] >= HOLDOUT_START.year:
        return failed("bundle lists a year in the protocol holdout")
    coverage_end = min(ingested_at, end_of_day(date(years[-1], 12, 31)))

    listed: dict[str, date] = {}
    for year in years:
        payload = bundle.payloads.get(list_name(year))
        if payload is None:
            return failed(f"press release list {year} is missing")
        try:
            links = list_statement_links(payload)
        except (UnicodeDecodeError, ValueError):
            return failed(f"press release list {year} is not readable")
        in_year = [(url, day) for url, day in links if day.year == year]
        if len(in_year) < len(links):
            # Lists may link recent statements elsewhere on the page; they are neither fetched nor used. Only
            # their number is kept: their dates may lie in the holdout.
            issues.append(_issue("LIST_LINK_OUTSIDE_YEAR", Severity.WARNING, list_name(year), f"{len(links) - len(in_year)} statement link(s) of other years ignored"))
        if not in_year:
            return failed(f"press release list {year} contains no FOMC statement")
        for url, day in in_year:
            listed[url] = day

    expected_names = {list_name(year) for year in years} | {statement_name(url) for url in listed}
    unexpected = sorted(set(bundle.requests) - expected_names)
    if unexpected:
        return failed(f"bundle has requests that no list asks for: {unexpected[:5]}")
    unexpected = sorted(set(bundle.payloads) - expected_names)
    if unexpected:
        return failed(f"bundle has payloads that no list asks for: {unexpected[:5]}")

    drafts: list[dict[str, Any]] = []
    for url, day in sorted(listed.items(), key=lambda item: (item[1], item[0])):
        name = statement_name(url)
        request = bundle.requests.get(name)
        if request is None or request.get("url") != url:
            return failed(f"statement {url} was not requested as listed")
        draft: dict[str, Any] = {"url": url, "day": day, "final_url": request.get("final_url"), "payload_sha256": hashes.get(name)}
        payload = bundle.payloads.get(name)
        if payload is None:
            if request.get("status") in (None, "200"):
                return failed(f"statement {url} has neither a payload nor a failed retrieval")
            draft.update(status=StatementStatus.MISSING_STATEMENT, detail=f"retrieval failed: {request.get('status')}")
            drafts.append(draft)
            continue
        try:
            page = read_statement(payload)
        except (UnicodeDecodeError, ValueError) as exc:
            return failed(f"statement {url} is not readable ({exc.__class__.__name__})")
        if not page.is_statement:
            return failed(f"page {url} is not recognisable as an FOMC statement")
        draft.update(_judge(page, day))
        drafts.append(draft)

    events: list[PolicyStatementEvent] = []
    for draft in drafts:
        status: StatementStatus = draft["status"]
        event_time = draft.get("event_time") if status is StatementStatus.OK else None
        available_at = event_time or end_of_day(draft["day"])
        event_id = f"FOMC:{draft['day'].isoformat()}:{statement_name(draft['url']).removeprefix('statement-')}"
        if available_at > ingested_at:
            issues.append(_issue("AVAILABLE_AFTER_INGESTION", Severity.ERROR, event_id, "statement would be known only after it was downloaded; rejected"))
            continue
        if draft.get("detail"):
            issues.append(_issue(status.value, Severity.WARNING, event_id, draft["detail"], available_at))
        low, high = draft.get("range") or (None, None)
        events.append(
            PolicyStatementEvent(
                event_id=event_id,
                release_date=draft["day"],
                kind=StatementKind.UNKNOWN_KIND,
                status=status,
                release_time_local=draft.get("local"),
                release_zone_label=draft.get("zone"),
                event_time=event_time,
                available_at=available_at,
                availability_basis=FomcAvailability.STATED_RELEASE_TIME if event_time else FomcAvailability.END_OF_RELEASE_DAY,
                target_low=low,
                target_high=high,
                previous_low=None,
                previous_high=None,
                decision=Decision.NOT_DETERMINED,
                change_bp=None,
                url=draft["url"],
                final_url=draft["final_url"],
                last_update=draft.get("last_update"),
                payload_sha256=draft["payload_sha256"],
                ingested_at=ingested_at,
            )
        )
    events.sort(key=lambda event: (event.available_at, event.event_id))
    if len({event.event_id for event in events}) != len(events):
        return failed("duplicate statement event id")
    return FomcIngest(QualityState.READY, _link_previous(events), _sorted(issues), years, coverage_end, ingested_at, hashes, copy.deepcopy(bundle.requests))


def _judge(page: StatementPage, listed_day: date) -> dict[str, Any]:
    """Status of one readable statement page; the first failing check in this order wins."""
    result: dict[str, Any] = {"last_update": page.last_update}
    if page.release_times:
        result["local"], result["zone"] = page.release_times[0]
    if len(page.ranges) == 1:
        result["range"] = page.ranges[0]
    if page.release_line_unreadable or len(page.release_times) > 1:
        return {**result, "status": StatementStatus.EVENT_TIME_INCONSISTENT, "detail": f"release line unreadable or repeated: {list(page.release_times)}"}
    if not page.release_times:
        return {**result, "status": StatementStatus.EVENT_TIME_UNKNOWN, "detail": "no 'For release at' line"}
    if page.page_date != listed_day:
        return {**result, "status": StatementStatus.SOURCE_CONFLICT, "detail": f"page date {page.page_date} differs from listed date {listed_day}"}
    instant = release_instant(listed_day, result["local"], result["zone"])
    if instant is None:
        return {**result, "status": StatementStatus.EVENT_TIME_INCONSISTENT, "detail": f"{result['local']} {result['zone']} is not a valid New York time on {listed_day}"}
    if page.last_update is None or page.last_update != listed_day:
        return {**result, "status": StatementStatus.DOCUMENT_UPDATED, "detail": f"Last Update {page.last_update} differs from release day {listed_day}"}
    if len(page.ranges) != 1:
        return {**result, "status": StatementStatus.RANGE_UNKNOWN, "detail": f"{len(page.ranges)} target ranges in the decision sentences"}
    low, high = page.ranges[0]
    if not low < high:
        return {**result, "status": StatementStatus.RANGE_UNKNOWN, "detail": f"range {low} to {high} is not increasing"}
    return {**result, "status": StatementStatus.OK, "event_time": instant}


def _link_previous(events: list[PolicyStatementEvent]) -> tuple[PolicyStatementEvent, ...]:
    """Previous range = range of the immediately preceding statement, only when both are OK; a statement
    in between that is not OK makes the previous range unknown, never skipped over."""
    linked = []
    before: PolicyStatementEvent | None = None
    for event in events:
        ok = event.status is StatementStatus.OK and before is not None and before.status is StatementStatus.OK
        if ok and event.target_low is not None and event.target_high is not None and before.target_low is not None and before.target_high is not None:
            low, high, previous_low, previous_high = event.target_low, event.target_high, before.target_low, before.target_high
            decision, change = Decision.NOT_DETERMINED, None
            if (low, high) == (previous_low, previous_high):
                decision, change = Decision.MAINTAIN, 0
            elif high - low == previous_high - previous_low:
                # A parallel shift of the range; a changed width is no single decision and stays NOT_DETERMINED.
                change = int((low - previous_low) * 100)
                decision = Decision.RAISE if change > 0 else Decision.LOWER
            event = replace(event, previous_low=previous_low, previous_high=previous_high, decision=decision, change_bp=change)
        linked.append(event)
        before = event
    return tuple(linked)


def _sorted(issues: list[DatedIssue]) -> tuple[DatedIssue, ...]:
    return tuple(sorted(issues, key=lambda item: (iso(item.available_at) or "", item.issue.code, item.issue.record_id)))


# --- point in time ------------------------------------------------------------------------------


class FomcStore:
    """What was known about FOMC statements at a time T. The holdout is locked here, not only in replay."""

    def __init__(self, ingest: FomcIngest) -> None:
        if ingest.state is not QualityState.READY:
            raise ValueError(f"ingest is {ingest.state.value}; nothing can be read from it")
        self.ingest = ingest

    def known_at(self, at: datetime, *, permission: HoldoutPermission | None = None) -> datetime:
        at = require_utc(at, "at")
        if permission is None and utc_to_ms(at) >= HOLDOUT_START_MS:
            raise HoldoutLocked("FOMC data at a holdout time needs the holdout permission")
        return min(at, self.ingest.coverage_end)

    def visible(self, at: datetime, *, permission: HoldoutPermission | None = None) -> tuple[PolicyStatementEvent, ...]:
        known = self.known_at(at, permission=permission)
        return tuple(event for event in self.ingest.events if event.available_at <= known)

    def current_range(self, at: datetime, *, permission: HoldoutPermission | None = None) -> dict[str, Any]:
        """The target range as of T: from the latest visible statement, UNKNOWN when that statement is not OK."""
        known = self.known_at(at, permission=permission)
        if require_utc(at, "at") > known:
            return {"status": "INSUFFICIENT_DATA", "event_id": None, "target_low": None, "target_high": None}
        visible = self.visible(at, permission=permission)
        if not visible:
            return {"status": "NOT_AVAILABLE", "event_id": None, "target_low": None, "target_high": None}
        last = visible[-1]
        ok = last.status is StatementStatus.OK
        return {
            "status": "OK" if ok else "UNKNOWN",
            "event_id": last.event_id,
            "target_low": decimal_str(last.target_low) if ok else None,
            "target_high": decimal_str(last.target_high) if ok else None,
        }


# --- replay -------------------------------------------------------------------------------------


def run_fomc_replay(
    ingest: FomcIngest,
    klines: Sequence[Kline],
    config: ReplayConfig,
    *,
    permission: HoldoutPermission | None = None,
) -> dict[str, Any]:
    """Deterministic FOMC dataset at replay time T: no clock, no network, no randomness."""
    at = require_utc(config.replay_at, "replay_at")
    if permission is None and utc_to_ms(at) >= HOLDOUT_START_MS:
        raise HoldoutLocked("replay time lies in the protocol holdout; replay needs the holdout permission")
    known = min(at, ingest.coverage_end)
    issues = [item.to_dict() for item in ingest.issues if item.available_at is None or item.available_at <= known]
    header: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "transform_version": PARSER_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "mode": MODE,
        "config": config.to_dict(),
        "source": dict(SOURCE_INFO),
    }
    provenance = {
        "payload_sha256": dict(sorted(ingest.payload_hashes.items())),
        "request": copy.deepcopy(ingest.request),
        "ingested_at": iso(ingest.ingested_at),
        "coverage_end": iso(ingest.coverage_end),
    }
    if ingest.state is not QualityState.READY:
        content = {**header, "state": ingest.state.value, "quality_issues": issues, "events": []}
        return _finish(content, provenance, {"state": ingest.state.value, "quality_issues": issues, "payload_sha256": provenance["payload_sha256"]})

    store = FomcStore(ingest)
    btc = BtcSeries.build(klines, config.interval, replay_at=at, permission=permission, invalid_candles=config.invalid_candles)
    events = store.visible(at, permission=permission)
    rows = []
    for event in events:
        if event.status is StatementStatus.OK:
            # align_event reads event_id, status, event_time and available_at, which a statement event has as well.
            alignment = align_event(event, btc, replay_at=at, horizons=config.horizons, permission=permission)  # type: ignore[arg-type]
        else:
            # Fail closed: an uncertain statement gets no windows, but stays listed so studies can avoid it.
            alignment = {"event_id": event.event_id, "interval": btc.interval, "status": "EVENT_NOT_OK", "event_status": event.status.value, "anchor": None, "windows": {}}
        rows.append({"event": _content_event(event.to_dict()), "btc": alignment})
    state = QualityState.READY if at <= ingest.coverage_end and btc.klines else QualityState.INSUFFICIENT_DATA
    content = {
        **header,
        "state": state.value,
        "inputs": {
            "fomc_event_ids": [event.event_id for event in events],
            "fomc_events_hash": digest_events(events),
            "btc_candles": len(btc.klines),
            "btc_hash": _btc_hash(btc),
            "btc_completeness": btc.gaps(),
            **({"btc_excluded": list(btc.excluded)} if config.invalid_candles == "exclude" else {}),
        },
        "quality_issues": issues,
        "current_range": store.current_range(at, permission=permission),
        "events": rows,
    }
    identity = {
        "state": state.value,
        "quality_issues": issues,
        "coverage_end": iso(ingest.coverage_end) if ingest.coverage_end < at else None,
    }
    return _finish(content, provenance, identity)


def digest_events(events: Sequence[PolicyStatementEvent]) -> str:
    return digest([_content_event(event.to_dict()) for event in events])


def _content_event(event: dict[str, Any]) -> dict[str, Any]:
    # Download time, redirect target and page hash are provenance, not research content: a page whose
    # bytes change without changing any parsed fact (e.g. site markup) keeps the dataset identity.
    return {key: value for key, value in event.items() if key not in {"ingested_at", "final_url", "payload_sha256"}}


def _btc_hash(btc: BtcSeries) -> str:
    return digest([[k.open_time, repr(k.open), repr(k.high), repr(k.low), repr(k.close), repr(k.volume), k.close_time, repr(k.taker_buy_volume)] for k in btc.klines])


__all__ = [
    "EVENT_TYPE",
    "HOST",
    "PARSER_VERSION",
    "SOURCE",
    "SOURCE_IDENTIFIER",
    "STATEMENT_TITLE",
    "Decision",
    "FomcAvailability",
    "FomcIngest",
    "FomcStore",
    "PolicyStatementEvent",
    "StatementKind",
    "StatementPage",
    "StatementStatus",
    "list_name",
    "list_statement_links",
    "page_text",
    "parse_fomc_bundle",
    "read_statement",
    "release_instant",
    "run_fomc_replay",
    "statement_name",
]
