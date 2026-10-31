"""Read-only download of FOMC statement pages from federalreserve.gov, holdout-safe.

A statement window names the yearly press release lists to read (2016 as look-back
for the first 2017 statement, up to 2024). Its last year lies before the protocol
holdout, so no holdout list is ever requested; statement links a list shows for
another year (e.g. a "recent" box) are never followed. Every page goes through
``RawPayloadStore`` first, and parsing only reads stored bundles.

Only ``https://www.federalreserve.gov/`` is contacted. A redirect is followed only
to the same host over HTTPS and is recorded as ``final_url``; anything else is
refused. No credentials are needed or sent.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src.research_lab.data.store import HoldoutLocked
from src.research_lab.external.alfred import Clock, RawBundle
from src.research_lab.external.fomc import (
    HOLDOUT_START,
    HOST,
    SOURCE,
    SOURCE_IDENTIFIER,
    FomcIngest,
    bundle_years,
    list_name,
    list_statement_links,
    parse_fomc_bundle,
    statement_name,
)
from src.research_lab.external.records import iso, require_utc
from src.research_lab.external.store import RawPayloadStore, _bundle_id

MAX_PAGE_BYTES = 5_000_000  # a press release page or yearly list is well below 1 MB
USER_AGENT = "TIM-research-lab/1.2 (read-only)"
# federalreserve.gov has one FOMC list per year from 2020 on; before that the general yearly list.
FOMC_LIST_FROM = 2020

PageFetcher = Callable[[str], tuple[bytes, str]]  # url -> (body, final url after same-host redirects)


class FomcIngestError(RuntimeError):
    """A download or bundle check failed."""


class PageMissing(FomcIngestError):
    """The server answered a statement page with an HTTP error; recorded, not fatal for statements."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


@dataclass(frozen=True, slots=True)
class StatementWindow:
    """Which yearly lists one FOMC download reads."""

    name: str
    first_year: int
    last_year: int

    def __post_init__(self) -> None:
        if self.first_year > self.last_year:
            raise ValueError("first_year is after last_year")
        if self.last_year >= HOLDOUT_START.year:
            raise HoldoutLocked(f"statement window {self.name} reaches the protocol holdout ({HOLDOUT_START.isoformat()})")

    @property
    def years(self) -> tuple[int, ...]:
        return tuple(range(self.first_year, self.last_year + 1))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "first_year": self.first_year, "last_year": self.last_year}


# 2017-2024 plus 2016 as look-back, so the first 2017 statement has a known previous range.
RESEARCH_2017_2024 = StatementWindow("fomc-research-2017-2024", 2016, 2024)
# Real-data regression fixture: 2019-2020, with the three unscheduled March 2020 statements.
FIXTURE_2019_2020 = StatementWindow("fomc-fixture-2019-2020", 2019, 2020)
FIXTURE_DIR = Path("tests/fixtures/research_lab/fomc_statements_2019_2020")
PROVENANCE = "provenance.json"


def list_url(year: int) -> str:
    suffix = "-press-fomc.htm" if year >= FOMC_LIST_FROM else "-press.htm"
    return f"{HOST}/newsevents/pressreleases/{year}{suffix}"


def ingest_fomc_live(window: StatementWindow, *, store: RawPayloadStore, fetcher: PageFetcher, clock: Clock) -> str:
    """Download the window's lists and every statement they link for their year; store and return the bundle id."""
    payloads: dict[str, bytes] = {}
    requests: dict[str, dict[str, str]] = {}
    for year in window.years:
        url = list_url(year)
        body, final = fetcher(url)  # a failed list aborts: without it the year cannot be shown complete
        payloads[list_name(year)] = body
        requests[list_name(year)] = _request(url, final)
        for statement_url, day in list_statement_links(body):
            if day.year != year or day >= HOLDOUT_START:
                continue  # never fetched: another year's link, possibly a holdout statement
            name = statement_name(statement_url)
            try:
                page, page_final = fetcher(statement_url)
            except PageMissing as exc:
                requests[name] = {"url": statement_url, "status": str(exc)}
                continue
            payloads[name] = page
            requests[name] = _request(statement_url, page_final)
    bundle = RawBundle(SOURCE, SOURCE_IDENTIFIER, payloads, require_utc(clock(), "clock"), requests)
    check_window(bundle, window)
    return store.put(bundle)


def _request(url: str, final: str) -> dict[str, str]:
    return {"url": url, "status": "200", **({"final_url": final} if final != url else {})}


def check_window(bundle: RawBundle, window: StatementWindow) -> None:
    """Refuse a bundle that reads other lists than the window's or holds pages outside the host."""
    if bundle.source != SOURCE or bundle.source_identifier != SOURCE_IDENTIFIER:
        raise FomcIngestError("bundle is not an FOMC statement download")
    if bundle_years(bundle) != window.years:
        raise FomcIngestError(f"bundle lists {bundle_years(bundle)}, window {window.name} needs {window.years}")
    for name, request in bundle.requests.items():
        for key in ("url", "final_url"):
            value = request.get(key)
            if value is not None and not _on_host(value):
                raise FomcIngestError(f"request {name} {key} is not on {HOST}")
        if name.startswith("list-") and request.get("url") != list_url(int(name.removeprefix("list-"))):
            raise FomcIngestError(f"request {name} is not the yearly list URL")


def load_fomc_ingest(store: RawPayloadStore, bundle_id: str, window: StatementWindow) -> tuple[RawBundle, FomcIngest]:
    bundle = store.get(bundle_id)
    check_window(bundle, window)
    return bundle, parse_fomc_bundle(bundle)


def _on_host(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc == "www.federalreserve.gov" and not parts.username and not parts.password


def http_page_fetcher(
    *,
    timeout: float = 30.0,
    attempts: int = 4,
    backoff: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    opener: Callable[..., Any] | None = None,
) -> PageFetcher:
    """HTTPS GET on www.federalreserve.gov only; 429/5xx retried with backoff, 404/410 raise PageMissing."""
    open_url = opener or urllib.request.build_opener(_SameHostRedirect).open

    def fetch(url: str) -> tuple[bytes, str]:
        if not _on_host(url):
            raise FomcIngestError(f"refusing a URL outside {HOST}")
        for attempt in range(attempts):
            status: int | None = None
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
                with open_url(request, timeout=timeout) as response:
                    final = response.geturl()
                    body = response.read(MAX_PAGE_BYTES + 1)
                if not _on_host(final):
                    raise FomcIngestError(f"{urlsplit(url).path}: ended outside {HOST}")
                if len(body) > MAX_PAGE_BYTES:
                    raise FomcIngestError(f"{urlsplit(url).path}: response larger than {MAX_PAGE_BYTES} bytes")
                return body, final
            except FomcIngestError:
                raise
            except urllib.error.HTTPError as exc:
                status = exc.code
                if status in (404, 410):
                    raise PageMissing(status) from None
                retryable = status == 429 or status >= 500
            except (urllib.error.URLError, TimeoutError, OSError):
                retryable = True
            if not retryable or attempt == attempts - 1:
                reason = f"HTTP {status}" if status is not None else "network error"
                raise FomcIngestError(f"{urlsplit(url).path}: {reason} after {attempt + 1} attempt(s)") from None
            sleep(backoff * 2**attempt)
        raise FomcIngestError(f"{urlsplit(url).path}: no attempt made")

    return fetch


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if not _on_host(newurl):
            raise urllib.error.HTTPError(req.full_url, 310, "redirect off the host refused", headers, None)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# --- real-data fixture --------------------------------------------------------------------------


def write_fixture(bundle: RawBundle, bundle_id: str, target: Path = FIXTURE_DIR) -> Path:
    """Copy a stored fixture-window download byte for byte, with its provenance."""
    check_window(bundle, FIXTURE_2019_2020)
    target.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, payload in sorted(bundle.payloads.items()):
        (target / f"{name}.html").write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
    provenance = {
        "description": "Real federalreserve.gov pages (FOMC statements and yearly lists), unmodified (see src/research_lab/external/fomc_live.py)",
        "source": bundle.source,
        "source_identifier": bundle.source_identifier,
        "bundle_id": bundle_id,
        "retrieved_at": bundle.ingested_at.isoformat(),
        "window": FIXTURE_2019_2020.to_dict(),
        "requests": bundle.requests,
        "payload_sha256": hashes,
    }
    (target / PROVENANCE).write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    return target


def load_fixture(directory: Path = FIXTURE_DIR) -> tuple[RawBundle, dict[str, Any]]:
    """Read the fixture and prove every page is byte-identical to what was downloaded."""
    provenance = json.loads((directory / PROVENANCE).read_text())
    payloads = {}
    for name, sha in provenance["payload_sha256"].items():
        payload = (directory / f"{name}.html").read_bytes()
        if hashlib.sha256(payload).hexdigest() != sha:
            raise ValueError(f"fixture page {name} differs from the recorded download")
        payloads[name] = payload
    bundle = RawBundle(provenance["source"], provenance["source_identifier"], payloads, datetime.fromisoformat(provenance["retrieved_at"]), provenance["requests"])
    entry = {
        "source": bundle.source,
        "source_identifier": bundle.source_identifier,
        "ingested_at": iso(bundle.ingested_at),
        "payloads": dict(sorted(provenance["payload_sha256"].items())),
        "requests": bundle.requests,
    }
    if _bundle_id(entry) != provenance["bundle_id"]:
        raise ValueError("fixture does not match the bundle id of the recorded download")
    check_window(bundle, FIXTURE_2019_2020)
    return bundle, provenance


__all__ = [
    "FIXTURE_2019_2020",
    "FIXTURE_DIR",
    "RESEARCH_2017_2024",
    "FomcIngestError",
    "PageFetcher",
    "PageMissing",
    "StatementWindow",
    "check_window",
    "http_page_fetcher",
    "ingest_fomc_live",
    "list_url",
    "load_fixture",
    "load_fomc_ingest",
    "write_fixture",
]
