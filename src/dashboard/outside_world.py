"""Headlines and hourly stock prices around large BTC moves (Bauplan "Preisbewegungen erklären", P3; display only).

Uzi 16.11.2026: "Feed und Aktien ja". Two public sources without key or account, both only read:

- Headlines: a fixed allowlist of RSS feeds (``FEEDS``). Only title, link, time and feed name are kept;
  a title is data, never an instruction, and is shown escaped. Feeds keep about a day of items, so every
  refresh appends new items to ``HEADLINE_LOG`` (one JSON line each, deduplicated by id): a move from last
  week can still find the headlines of its hour.
- Stocks: hourly bars of the Nasdaq-100 (``^NDX``), the S&P 500 (``^GSPC``) and NVIDIA (``NVDA``) from the
  public Yahoo Finance chart endpoint (unofficial, may lag by a few minutes, US trading hours only). A bar
  counts from the end of its hour, never earlier (no look-ahead).

Both run in a background thread like ``market_context.ContextCache``; a failed read keeps the last value.
Tests (``TIM_RUNTIME_ENV=test``) never reach the network. Nothing here feeds a plan, a score or an order.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

FEEDS = (
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("CNBC Markets", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
)
STOCKS = (("^NDX", "Nasdaq-100"), ("^GSPC", "S&P 500"), ("NVDA", "NVIDIA"))
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=60m&range=30d"
STOCK_SOURCE = "Yahoo Finance Chart (öffentlich, inoffiziell, 1h, teils verzögert)"
HEADLINE_LOG = Path("data/news/headlines.jsonl")
TIMEOUT_SECONDS = 10
MAX_BYTES = 3_000_000
MAX_TITLE = 200
MAX_ITEMS_PER_FEED = 100
TTL = 600.0
FAIL_PAUSE = 300.0
LOG_READ_DAYS = 10

Fetch = Callable[[str], bytes]
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_TAGS = re.compile(r"<[^>]*>")


def fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (TIM-dashboard/1.0)", "Accept": "*/*"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed public https endpoints above
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("answer too large")
    return raw


# --- headlines ---------------------------------------------------------------------------------------------------


def _clean(text: Any, limit: int) -> str:
    text = _TAGS.sub(" ", str(text or ""))
    return " ".join(_CONTROL.sub(" ", text).split())[:limit]


def _when(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            moment = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None if moment.tzinfo is None else moment.astimezone(timezone.utc)


def _safe_link(link: str) -> str:
    link = _clean(link, 500)
    return link if urlparse(link).scheme == "https" else ""


def parse_feed(raw: bytes, feed: str) -> list[dict[str, Any]]:
    """Items of an RSS 2.0 or Atom feed: title, link, time (UTC), feed. Entities and DTDs are refused."""
    head = raw[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in raw.lower():
        raise ValueError(f"{feed}: DTD or entity in feed refused")
    root = ET.fromstring(raw)  # noqa: S314 - no DTD/entities (checked above), size capped in fetch_bytes
    items = []
    atom = "{http://www.w3.org/2005/Atom}"
    nodes = root.findall(".//item") or root.findall(f".//{atom}entry")
    for node in nodes[:MAX_ITEMS_PER_FEED]:
        element = node.find("title")
        element = element if element is not None else node.find(f"{atom}title")
        title = "".join(element.itertext()) if element is not None else ""
        link = node.findtext("link") or ""
        if not link:
            element = node.find(f"{atom}link")
            link = element.get("href", "") if element is not None else ""
        moment = _when(node.findtext("pubDate") or node.findtext(f"{atom}published") or node.findtext(f"{atom}updated"))
        title = _clean(title, MAX_TITLE)
        if not title or moment is None:
            continue
        key = hashlib.sha256(f"{feed}|{title}|{moment.isoformat()}".encode()).hexdigest()[:16]
        items.append({"id": key, "feed": feed, "title": title, "link": _safe_link(link), "time": moment.isoformat()})
    return items


def fetch_headlines(fetch: Fetch | None = None) -> list[dict[str, Any]]:
    """All feeds; one broken feed is skipped. Raises only when no feed answered."""
    fetch = fetch or fetch_bytes
    items, answered = [], 0
    for name, url in FEEDS:
        try:
            items.extend(parse_feed(fetch(url), name))
            answered += 1
        except Exception:  # noqa: BLE001 - other feeds still count
            continue
    if not answered:
        raise ValueError("headlines: no feed answered")
    return items


def append_log(items: Sequence[Mapping[str, Any]], path: Path = HEADLINE_LOG) -> int:
    """Append items not yet in the log; returns how many were new."""
    known = {row["id"] for row in read_log(path, days=None)}
    new = [dict(item) for item in items if item.get("id") not in known]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for item in sorted(new, key=lambda r: r["time"]):
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(new)


def read_log(path: Path = HEADLINE_LOG, days: int | None = LOG_READ_DAYS, now: datetime | None = None) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    since = None if days is None else (now or datetime.now(timezone.utc)) - timedelta(days=days)
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
            moment = datetime.fromisoformat(row["time"])
        except (ValueError, KeyError, TypeError):
            continue
        if isinstance(row.get("id"), str) and isinstance(row.get("title"), str) and (since is None or moment >= since):
            rows.append(row)
    return rows


def headlines_between(items: Sequence[Mapping[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Headlines published from ``start`` to ``end``, oldest first, one per title."""
    seen, found = set(), []
    for item in sorted(items, key=lambda r: r["time"]):
        moment = datetime.fromisoformat(item["time"])
        if start <= moment <= end and item["title"].lower() not in seen:
            seen.add(item["title"].lower())
            found.append(dict(item))
    return found


# --- stocks ------------------------------------------------------------------------------------------------------


def parse_chart(payload: Any, symbol: str) -> list[list[float]]:
    """Hourly bars ``[start epoch, open, close]`` of one Yahoo chart answer; empty bars are dropped."""
    result = ((payload or {}).get("chart") or {}).get("result") or []
    if not result:
        raise ValueError(f"{symbol}: no chart result")
    block = result[0]
    times = block.get("timestamp") or []
    quote_ = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    opens, closes = quote_.get("open") or [], quote_.get("close") or []
    bars = []
    for t, o, c in zip(times, opens, closes):
        if o is None or c is None or not (math.isfinite(o) and math.isfinite(c)) or o <= 0 or c <= 0:
            continue
        bars.append([int(t), float(o), float(c)])
    if len(bars) < 2:
        raise ValueError(f"{symbol}: fewer than two bars")
    return sorted(bars)


def fetch_stocks(fetch: Fetch | None = None, now: datetime | None = None) -> dict[str, Any]:
    fetch = fetch or fetch_bytes
    series = {}
    for symbol, name in STOCKS:
        try:
            series[symbol] = {"name": name, "bars": parse_chart(json.loads(fetch(YAHOO.format(symbol=quote(symbol)))), symbol)}
        except Exception:  # noqa: BLE001 - the other symbols still count
            continue
    if not series:
        raise ValueError("stocks: no symbol answered")
    return {"source": STOCK_SOURCE, "as_of": (now or datetime.now(timezone.utc)).isoformat(), "series": series}


def stock_move(bars: Sequence[Sequence[float]], start: datetime, end: datetime) -> dict[str, Any] | None:
    """Return of the bars inside ``[start, end]``: a bar counts only when it has ended by ``end``.

    None when no bar ended inside the window (market closed).
    """
    s, e = int(start.timestamp()), int(end.timestamp())
    inside = [b for b in bars if b[0] + 3600 > s and b[0] + 3600 <= e]
    if not inside:
        return None
    first, last = inside[0], inside[-1]
    return {"from": datetime.fromtimestamp(first[0], timezone.utc).isoformat(),
            "to": datetime.fromtimestamp(last[0] + 3600, timezone.utc).isoformat(),
            "change_pct": round((last[2] / first[1] - 1.0) * 100, 2), "bars": len(inside)}


# --- cache -------------------------------------------------------------------------------------------------------


class Cache:
    """Headlines and stocks, refreshed in a background thread every ``ttl`` seconds; the last success is kept."""

    def __init__(self, headlines: Callable[[], list[dict[str, Any]]] | None = None, stocks: Callable[[], dict[str, Any]] | None = None,
                 log_path: Path | None = None, ttl: float = TTL, fail_pause: float = FAIL_PAUSE) -> None:
        self._headlines = headlines or fetch_headlines
        self._stocks = stocks or fetch_stocks
        self._log_path = log_path
        self._ttl, self._fail_pause = ttl, fail_pause
        self._lock = threading.Lock()
        self._values: dict[str, Any] = {"headlines": None, "stocks": None}
        self._at, self._failed, self._running = -math.inf, True, False

    def refresh(self) -> None:
        values, failed = {}, False
        for key, build in (("headlines", self._headlines), ("stocks", self._stocks)):
            try:
                values[key] = build()
            except Exception:  # noqa: BLE001 - keep the last value
                failed = True
        if values.get("headlines"):
            try:
                append_log(values["headlines"], self._log_path or HEADLINE_LOG)
            except OSError:
                pass
        with self._lock:
            self._values.update(values)
            self._at, self._failed, self._running = time.monotonic(), failed, False

    def snapshot(self, background: bool = True) -> dict[str, Any]:
        with self._lock:
            pause = self._fail_pause if self._failed else self._ttl
            start = time.monotonic() - self._at >= pause and not self._running
            if start:
                self._running = True
        if start:
            if background:
                threading.Thread(target=self.refresh, name="tim-outside-world", daemon=True).start()
            else:
                self.refresh()
        with self._lock:
            return dict(self._values)


CACHE = Cache()


def sources() -> dict[str, Any]:
    """Headlines (log plus the last read) and stocks for move_context; nothing in tests."""
    if os.environ.get("TIM_RUNTIME_ENV") == "test":
        return {}
    snap = CACHE.snapshot()
    items = {row["id"]: row for row in read_log()}
    for row in snap.get("headlines") or []:
        items.setdefault(row["id"], row)
    return {"headlines": list(items.values()) if items else None, "stocks": snap.get("stocks")}
