"""Read-only live download of ALFRED vintages for research, holdout-safe.

A research window fixes which observation periods and which vintages may be
requested. Its real-time range ends before the protocol holdout (2025-01-01), so
the request itself never asks for holdout vintages. The response is checked
against the window before anything is stored: an API answer that reaches past the
window (later vintages, later release dates, a wider real-time envelope) is
refused, never trimmed and never stored, so it cannot widen the window silently.

Accepted bundles go through ``RawPayloadStore`` first; parsing only ever reads a
stored bundle, so every research input has raw-payload provenance. A stored
bundle is reused by id without touching the network.

The API key comes from ``FredSecretResolver``. It is only placed in the request
URL; fetch errors report the endpoint path and HTTP status, never the URL.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from src.research_lab.data.store import HoldoutLocked
from src.research_lab.external.alfred import API_BASE, FIRST_REALTIME, PAGE_LIMIT, Clock, Fetcher, RawBundle, fetch_bundle, parse_bundle
from src.research_lab.external.fred_secret import FredSecretResolver
from src.research_lab.external.records import CPI_US, IngestResult, SourceSpec, source_spec
from src.research_lab.external.store import RawPayloadStore
from src.research_lab.protocol import HOLDOUT_START_MS

HOLDOUT_START = datetime.fromtimestamp(HOLDOUT_START_MS / 1000, tz=timezone.utc).date()
MAX_RESPONSE_BYTES = 50_000_000  # CPIAUCSL with every vintage is a few MB; anything far larger is not this API
USER_AGENT = "TIM-research-lab/1.1 (read-only)"


class LiveIngestError(RuntimeError):
    """A download or response check failed. Messages never contain the API key or the request URL."""


@dataclass(frozen=True, slots=True)
class ResearchWindow:
    """Which periods and vintages one research download may contain."""

    name: str
    observation_start: date  # first reference period requested (includes look-back for the first events)
    observation_end: date  # last reference period requested
    realtime_end: date  # last vintage date requested; must lie before the holdout

    def __post_init__(self) -> None:
        if self.observation_start > self.observation_end:
            raise ValueError("observation_start is after observation_end")
        if self.observation_end > self.realtime_end:
            raise ValueError("observation_end is after realtime_end")
        if self.realtime_end >= HOLDOUT_START:
            # Downloads have no holdout permission path: a window reaching the holdout is refused outright.
            raise HoldoutLocked(f"research window {self.name} reaches the protocol holdout ({HOLDOUT_START.isoformat()})")

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "observation_start": self.observation_start.isoformat(),
            "observation_end": self.observation_end.isoformat(),
            "realtime_end": self.realtime_end.isoformat(),
        }


# V1.1 verification: periods 2017-2024 plus one year of look-back, vintages up to the last pre-holdout day.
RESEARCH_2017_2024 = ResearchWindow("research-2017-2024", date(2016, 1, 1), date(2024, 12, 31), date(2024, 12, 31))


def research_requests(spec: SourceSpec, window: ResearchWindow) -> dict[str, dict[str, str]]:
    """Request parameters (without the key) for one research window."""
    realtime = {"realtime_start": FIRST_REALTIME, "realtime_end": window.realtime_end.isoformat()}
    return {
        "series": {"path": "series", "series_id": spec.source_identifier, **realtime},
        "observations": {
            "path": "series/observations",
            "series_id": spec.source_identifier,
            **realtime,
            "observation_start": window.observation_start.isoformat(),
            "observation_end": window.observation_end.isoformat(),
            "units": "lin",
            "output_type": "1",
            "sort_order": "asc",
            "limit": str(PAGE_LIMIT),
        },
        "release_dates": {
            "path": "release/dates",
            "release_id": str(spec.release_id),
            **realtime,
            "include_release_dates_with_no_data": "false",
            "sort_order": "asc",
            "limit": "10000",
        },
    }


def check_window(bundle: RawBundle, window: ResearchWindow) -> None:
    """Refuse a bundle whose requests or responses reach outside the window. Raises LiveIngestError."""
    if bundle.requests != research_requests(source_spec(bundle.source, bundle.source_identifier), window):
        raise LiveIngestError(f"bundle requests do not match research window {window.name}")
    end = window.realtime_end.isoformat()
    try:
        observations = json.loads(bundle.payloads["observations"])
        series = json.loads(bundle.payloads["series"])
        calendar = json.loads(bundle.payloads["release_dates"]) if "release_dates" in bundle.payloads else None
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise LiveIngestError(f"response is not usable JSON ({exc.__class__.__name__})") from None
    if not isinstance(observations, dict) or not isinstance(series, dict):
        raise LiveIngestError("response is not a JSON object")
    # The envelope must echo exactly what was asked; a wider answer would widen coverage silently.
    expected_envelope = {
        "realtime_start": FIRST_REALTIME,
        "realtime_end": end,
        "observation_start": window.observation_start.isoformat(),
        "observation_end": window.observation_end.isoformat(),
    }
    for key, value in expected_envelope.items():
        if observations.get(key) != value:
            raise LiveIngestError(f"observations {key} is {observations.get(key)!r}, requested {value!r}")
    rows = observations.get("observations")
    if not isinstance(rows, list):
        raise LiveIngestError("observations payload has no observation list")
    for row in rows:
        if not isinstance(row, dict):
            continue  # malformed rows are the parser's job (UNDATABLE_ROWS); only reach is checked here
        start, period, row_end = row.get("realtime_start"), row.get("date"), row.get("realtime_end")
        if isinstance(start, str) and start > end:
            raise LiveIngestError("observations contain a vintage after the research window")
        # The API clips realtime_end to the requested end; anything later (also 9999-12-31) is later knowledge.
        if isinstance(row_end, str) and row_end > end:
            raise LiveIngestError("observations contain a real-time end after the research window")
        if isinstance(period, str) and period > window.observation_end.isoformat():
            raise LiveIngestError("observations contain a period after the research window")
    if series.get("realtime_end") not in (None, end):
        raise LiveIngestError("series metadata describes a real-time range beyond the research window")
    for meta in series.get("seriess") or []:
        if not isinstance(meta, dict):
            continue  # malformed metadata is the parser's job
        for key in ("realtime_start", "realtime_end", "observation_end", "last_updated"):
            value = meta.get(key)
            if isinstance(value, str) and value[:10] > end:
                raise LiveIngestError(f"series metadata {key} lies after the research window")
    if calendar is not None:
        if not isinstance(calendar, dict) or not isinstance(calendar.get("release_dates"), list):
            raise LiveIngestError("release dates payload has no release_dates list")
        if calendar.get("realtime_end") not in (None, end):
            raise LiveIngestError("release dates describe a real-time range beyond the research window")
        for item in calendar["release_dates"]:
            day = item.get("date") if isinstance(item, dict) else None
            if isinstance(day, str) and day > end:
                raise LiveIngestError("release calendar contains a date after the research window")


def ingest_live(
    window: ResearchWindow,
    *,
    resolver: FredSecretResolver,
    store: RawPayloadStore,
    fetcher: Fetcher,
    clock: Clock,
    spec: SourceSpec = CPI_US,
) -> str:
    """Download one research bundle, check it against the window and store it. Returns the bundle id."""
    key = resolver.api_key()
    failure: str | None = None
    try:
        bundle = fetch_bundle(spec, api_key=key.reveal(), fetcher=fetcher, clock=clock, requests=research_requests(spec, window))
    except LiveIngestError as exc:
        failure = str(exc)  # already free of URL and key
    except Exception as exc:  # noqa: BLE001 - any fetch failure is reported without its (URL-bearing) text
        failure = f"download failed ({exc.__class__.__name__})"
    if failure is not None:
        # Raised outside the except block: no __context__ keeps the original exception (and its URL with the key).
        raise LiveIngestError(failure)
    # A response echoing the key must not reach the window check (its messages quote response values),
    # the store or any hash.
    secret = key.reveal()
    echoed = sorted(name for name, payload in bundle.payloads.items() if _echoes(payload, secret))
    if echoed:
        raise LiveIngestError(f"response echoes the API key ({', '.join(echoed)}); nothing stored")
    check_window(bundle, window)  # before storing: a refused response never reaches the disk
    return store.put(bundle)


def _echoes(payload: bytes, secret: str) -> bool:
    """The raw bytes or any decoded JSON string (key or value) contain the secret; JSON escapes
    such as ``\\u0061`` would hide it from the byte check but not from json.loads."""
    if secret.encode() in payload:
        return True
    try:
        pending = [json.loads(payload)]
    except (UnicodeDecodeError, ValueError, RecursionError):
        return False  # not JSON: the byte check above saw the payload as it is
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if secret in item:
                return True
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def load_research_ingest(store: RawPayloadStore, bundle_id: str, window: ResearchWindow) -> tuple[RawBundle, IngestResult]:
    """Parse a stored bundle (no network) after re-checking it against the window."""
    bundle = store.get(bundle_id)
    check_window(bundle, window)
    return bundle, parse_bundle(bundle)


def http_fetcher(
    *,
    timeout: float = 30.0,
    attempts: int = 4,
    backoff: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    opener: Callable[..., Any] | None = None,
) -> Fetcher:
    """HTTPS GET against the FRED API only, with retries for rate limits and server errors.

    - only ``https://api.stlouisfed.org/fred/`` URLs; redirects are refused (they would carry the key elsewhere);
    - 429 and 5xx are retried with exponential backoff (``backoff * 2**attempt`` seconds), other errors fail at once;
    - responses larger than MAX_RESPONSE_BYTES are refused;
    - every error names the endpoint path and status only."""
    open_url = opener or urllib.request.build_opener(_NoRedirect).open

    def fetch(url: str) -> bytes:
        if not url.startswith(API_BASE + "/"):
            raise LiveIngestError("refusing a URL outside the FRED API")
        path = urlsplit(url).path
        for attempt in range(attempts):
            status: int | None = None
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
                with open_url(request, timeout=timeout) as response:
                    body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise LiveIngestError(f"{path}: response larger than {MAX_RESPONSE_BYTES} bytes")
                return body
            except LiveIngestError:
                raise
            except urllib.error.HTTPError as exc:
                status = exc.code
                retryable = status == 429 or status >= 500
            except (urllib.error.URLError, TimeoutError, OSError):
                retryable = True
            except Exception:  # noqa: BLE001 - never surface an exception that may carry the URL
                retryable = False
            if not retryable or attempt == attempts - 1:
                reason = f"HTTP {status}" if status is not None else "network error"
                raise LiveIngestError(f"{path}: {reason} after {attempt + 1} attempt(s)") from None
            sleep(backoff * 2**attempt)
        raise LiveIngestError(f"{path}: no attempt made")  # attempts < 1

    return fetch


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        # No URL in the error: the request URL carries the key.
        raise urllib.error.HTTPError("", 310, "redirect refused", None, None)


__all__ = [
    "HOLDOUT_START",
    "RESEARCH_2017_2024",
    "LiveIngestError",
    "ResearchWindow",
    "check_window",
    "http_fetcher",
    "ingest_live",
    "load_research_ingest",
    "research_requests",
]
