"""BTC and USDT dominance history for the influence research (Uzi 07.11.2026).

A free daily history of the total crypto market cap does not exist (CoinGecko's chart is Pro only).
This module builds a substitute from the Coin Metrics Community API (no key): ``CapMrktEstUSD``
(price times estimated circulating supply) per asset and day, for about 830 assets from 2019-06-22.
Dominance = asset cap / sum of a cleaned basket of all assets with a value on that day. It is labelled
a substitute, not TradingView ``BTC.D``.

Cleaning the basket (otherwise caps are counted twice):
- chain variants ``<base>_<chain>`` are dropped when ``<base>`` itself is in the catalogue;
- wrapped, bridged or staked tokens of another asset are dropped (``WRAPPED``).

Checked on the Mac 07.11.2026 against published BTC.D values (CoinMarketCap/TradingView, from memory,
not re-checked): end of 2019 69.9 % (about 68), end of 2020 71.3 % (about 71), 08.11.2021 43.8 %
(about 41-42), end of 2022 39.9 % (about 40). ``CapMrktCurUSD`` (with escrowed XRP and fewer assets)
was several points off and is not used. Supply estimates may be revised later by Coin Metrics.

Research history ends 2024-12-31 (holdout 2025 stays closed); ``recent`` serves today's state only.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.research_lab.forward.macro_filters import MacroDataError, Series

BASE = "https://community-api.coinmetrics.io/v4/"
METRIC = "CapMrktEstUSD"
HISTORY_START = "2019-06-22"  # first day of CapMrktEstUSD in the community set
HISTORY_END = "2024-12-31"
HOLDOUT_START = date(2025, 1, 1)
BTC_SERIES = "CM_BTC_DOMINANCE"
USDT_SERIES = "CM_USDT_DOMINANCE"
COINS = {BTC_SERIES: "btc", USDT_SERIES: "usdt"}
# wrapped, bridged or staked forms of an asset that is already in the basket
WRAPPED = frozenset({"wbtc", "renbtc", "hbtc", "cbbtc", "btcb", "weth", "steth", "wsteth", "cbeth", "reth", "weeth",
                     "wbeth", "wnxm", "sdai_eth", "susde_eth"})
MAX_PAGES = 600
CHUNK = 60
MAX_RESPONSE_BYTES = 20_000_000

Fetch = Callable[[str], bytes]


def http_fetcher(*, timeout: float = 60.0, attempts: int = 5, pause: float = 0.7,
                 sleep: Callable[[float], None] = time.sleep) -> Fetch:
    """GET against the Coin Metrics Community API only; 429/5xx are retried with a growing wait."""

    def fetch(url: str) -> bytes:
        if not url.startswith(BASE):
            raise MacroDataError("only the Coin Metrics Community API is allowed here")
        for attempt in range(attempts):
            sleep(pause)  # community limit is 10 requests per 6 seconds
            try:
                with urllib.request.urlopen(url, timeout=timeout) as resp:  # fixed https host, checked above
                    body = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise MacroDataError("Coin Metrics answer too large")
                return body
            except urllib.error.HTTPError as exc:
                if (exc.code != 429 and exc.code < 500) or attempt == attempts - 1:
                    raise MacroDataError(f"Coin Metrics {urllib.parse.urlsplit(url).path}: HTTP {exc.code}") from None
                sleep(2.0 * 2 ** attempt)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt == attempts - 1:
                    raise MacroDataError(f"Coin Metrics not reachable ({type(exc).__name__})") from None
                sleep(2.0 * 2 ** attempt)
        raise MacroDataError("Coin Metrics not reachable")

    return fetch


def catalog_url() -> str:
    return BASE + "catalog-v2/asset-metrics?" + urllib.parse.urlencode({"metrics": METRIC, "page_size": 10000})


def series_url(assets: Sequence[str], start: str, end: str) -> str:
    query = {"assets": ",".join(assets), "metrics": METRIC, "frequency": "1d", "start_time": start, "end_time": end,
             "page_size": 10000, "paging_from": "start", "ignore_unsupported_errors": "true"}
    return BASE + "timeseries/asset-metrics?" + urllib.parse.urlencode(query)


def community_assets(raw: bytes) -> list[str]:
    """Assets with a daily community ``CapMrktCurUSD``."""
    out = []
    for item in json.loads(raw).get("data", []):
        for metric in item.get("metrics", []):
            if metric.get("metric") == METRIC and any(f.get("frequency") == "1d" and f.get("community")
                                                      for f in metric.get("frequencies", [])):
                out.append(str(item["asset"]))
    return sorted(set(out))


def basket(assets: Iterable[str]) -> list[str]:
    """Drop chain variants of an asset that is listed itself, and wrapped/staked duplicates."""
    names = set(assets)
    return sorted(a for a in names if a not in WRAPPED and not ("_" in a and a.split("_", 1)[0] in names))


def fetch_pages(fetch: Fetch, assets: Sequence[str], start: str, end: str) -> list[bytes]:
    """All pages of the time series, following ``next_page_url``; chunks of CHUNK assets keep URLs short."""
    pages: list[bytes] = []
    for i in range(0, len(assets), CHUNK):
        url: str | None = series_url(assets[i:i + CHUNK], start, end)
        while url:
            if len(pages) >= MAX_PAGES:
                raise MacroDataError("Coin Metrics: too many pages")
            body = fetch(url)
            pages.append(body)
            nxt = json.loads(body).get("next_page_url")
            url = str(nxt) if nxt else None
            if url and not url.startswith(BASE):
                raise MacroDataError("Coin Metrics: next page points elsewhere")
    return pages


def parse_caps(pages: Iterable[bytes]) -> dict[date, dict[str, float]]:
    """Market cap per day and asset; missing, zero or broken values are left out."""
    caps: dict[date, dict[str, float]] = {}
    for body in pages:
        for row in json.loads(body).get("data", []):
            try:
                value = float(row[METRIC])
                day = datetime.fromisoformat(str(row["time"])[:10]).date()
            except (KeyError, TypeError, ValueError):
                continue
            if value > 0:
                caps.setdefault(day, {})[str(row["asset"])] = value
    return caps


def raw_share(day_caps: Mapping[str, float], coin: str) -> float | None:
    total = sum(day_caps.values())
    return None if coin not in day_caps or not total else day_caps[coin] / total * 100


def share_series(caps: Mapping[date, Mapping[str, float]], coin: str, allowed: Iterable[str]) -> Series:
    """Share of ``coin`` in percent of the basket assets present on each day."""
    keep = set(allowed)
    out: Series = []
    for day in sorted(caps):
        value = raw_share({a: v for a, v in caps[day].items() if a in keep}, coin)
        if value is not None:
            out.append((day, value))
    return out


def build_series(caps: Mapping[date, Mapping[str, float]], allowed: Iterable[str], end: date | None = None) -> dict[str, Series]:
    names = list(allowed)
    data = {sid: share_series(caps, coin, names) for sid, coin in COINS.items()}
    if end is not None:
        data = {sid: [(d, v) for d, v in s if d <= end] for sid, s in data.items()}
    return data


def fetch_history(folder: Path, fetch: Fetch, start: str = HISTORY_START, end: str = HISTORY_END) -> dict[str, str]:
    """Store catalogue and all pages raw with SHA-256 under ``roh/dominanz`` (research history up to 2024)."""
    if date.fromisoformat(end) >= HOLDOUT_START:
        raise MacroDataError("dominance history must end before 2025-01-01 (holdout)")
    out = folder / "roh" / "dominanz"
    out.mkdir(parents=True, exist_ok=True)
    cat = fetch(catalog_url())
    assets = basket(community_assets(cat))
    pages = fetch_pages(fetch, assets, start, end)
    files = {"catalog.json": cat, **{f"seite_{i:03d}.json": body for i, body in enumerate(pages)}}
    for name, body in files.items():
        (out / name).write_bytes(body)
    meta = {"quelle": f"Coin Metrics Community API, {METRIC} 1d", "start": start, "ende": end, "korb": assets,
            "abruf_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "sha256": {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}}
    (out / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return meta["sha256"]


def load_history(folder: Path) -> tuple[dict[str, Series], dict[str, str]]:
    """Stored dominance series (checked against their hashes); empty when never fetched."""
    src = folder / "roh" / "dominanz"
    if not (src / "meta.json").exists():
        return {}, {}
    meta = json.loads((src / "meta.json").read_text())
    pages = []
    for name, digest in sorted(meta["sha256"].items()):
        body = (src / name).read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            raise MacroDataError(f"dominanz/{name}: stored answer changed since it was fetched")
        if name.startswith("seite_"):
            pages.append(body)
    data = build_series(parse_caps(pages), meta["korb"], end=HOLDOUT_START - timedelta(days=1))
    combined = hashlib.sha256("".join(v for _, v in sorted(meta["sha256"].items())).encode()).hexdigest()
    return data, {"coinmetrics_dominanz": combined}


def recent(fetch: Fetch, today: date, days: int = 120) -> dict[str, Series]:
    """Dominance of the last ``days`` days as published now (for today's state only, not for research)."""
    assets = basket(community_assets(fetch(catalog_url())))
    pages = fetch_pages(fetch, assets, (today - timedelta(days=days)).isoformat(), today.isoformat())
    return build_series(parse_caps(pages), assets)
