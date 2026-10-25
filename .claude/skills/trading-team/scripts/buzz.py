#!/usr/bin/env python3
"""Bot 2: Buzz-Tracker. Bewertet, wie viel Aufmerksamkeit die markierten Coins bekommen (0-10).

Quellen (öffentlich, ohne Schlüssel):
- CoinGecko-Trendliste (/search/trending): bis zu 6 Punkte, je höher der Rang, desto mehr.
- Krypto-Schlagzeilen aus öffentlichen RSS-Feeds der letzten 24 Stunden: bis zu 4 Punkte.

X (Twitter) ist bewusst nicht eingebaut: der Datenzugang ist kostenpflichtig, Scraping verstößt gegen
die Regeln von X. Schreibt pro neuem Scanner-Treffer eine Zeile nach buzz.csv.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    COINGECKO_BASE,
    append_rows,
    default_data_dir,
    http_get_bytes,
    http_get_json,
    iso,
    read_rows,
    signal_key,
    utc_now,
)

FIELDS = [
    "scored_at", "symbol", "candle_close_time", "buzz_score", "trending_rank",
    "trending_points", "headline_count", "headline_points", "reason",
]

NEWS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
]

# Häufige englische Wörter, die zugleich Ticker sind: nur über den Namen zählen.
KNOWN_NAMES = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "XRP": "Ripple", "BNB": "BNB Chain",
    "DOGE": "Dogecoin", "ADA": "Cardano", "AVAX": "Avalanche", "LINK": "Chainlink", "DOT": "Polkadot",
    "LTC": "Litecoin", "TRX": "Tron", "TON": "Toncoin", "SHIB": "Shiba Inu", "PEPE": "Pepe",
    "SUI": "Sui", "APT": "Aptos", "ARB": "Arbitrum", "OP": "Optimism", "NEAR": "Near Protocol",
}

AMBIGUOUS_TICKERS = {"ONE", "NEAR", "GAS", "SUN", "MASK", "BOND", "BEST", "HIGH", "OP", "S", "T", "W", "ID", "ACE"}


def trending_points(rank: int | None) -> int:
    if rank is None:
        return 0
    if rank < 3:
        return 6
    if rank < 7:
        return 5
    if rank < 11:
        return 4
    return 3


def headline_points(count: int) -> int:
    if count <= 0:
        return 0
    if count == 1:
        return 1
    if count == 2:
        return 2
    if count <= 4:
        return 3
    return 4


def parse_trending(payload: dict) -> dict[str, dict]:
    """Symbol (groß) -> {"rank": int, "name": str} aus der CoinGecko-Antwort."""
    out: dict[str, dict] = {}
    for idx, entry in enumerate(payload.get("coins", [])):
        item = entry.get("item", entry)
        sym = str(item.get("symbol", "")).upper()
        if not sym or sym in out:
            continue
        rank = item.get("score", idx)
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            rank = idx
        out[sym] = {"rank": rank, "name": str(item.get("name", ""))}
    return out


def parse_rss(xml_bytes: bytes) -> list[dict]:
    """Titel und Datum aus RSS 2.0 oder Atom. Fehlerhafte Feeds liefern eine leere Liste."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    items = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        title, published = "", None
        for child in node:
            ctag = child.tag.rsplit("}", 1)[-1]
            text = (child.text or "").strip()
            if ctag == "title":
                title = text
            elif ctag in ("pubDate", "published", "updated") and text and published is None:
                try:
                    published = parsedate_to_datetime(text)
                except (TypeError, ValueError):
                    try:
                        published = datetime.fromisoformat(text.replace("Z", "+00:00"))
                    except ValueError:
                        published = None
        if title:
            items.append({"title": title, "published": published})
    return items


def count_mentions(base: str, name: str | None, headlines: list[dict], now: datetime) -> int:
    since = now - timedelta(hours=24)
    patterns = []
    if len(base) >= 3 and base not in AMBIGUOUS_TICKERS:
        patterns.append(re.compile(rf"(?<![A-Za-z0-9$]){re.escape(base)}(?![A-Za-z0-9])|\${re.escape(base)}\b"))
    if name and len(name) >= 4:
        patterns.append(re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE))
    if not patterns:
        return 0
    n = 0
    for h in headlines:
        pub = h.get("published")
        if pub is not None and pub.tzinfo is not None and pub < since:
            continue
        if any(p.search(h["title"]) for p in patterns):
            n += 1
    return n


def score_coin(base: str, trending: dict[str, dict], headlines: list[dict], now: datetime,
               names: dict[str, str] | None = None) -> dict:
    t = trending.get(base.upper())
    rank = t["rank"] if t else None
    name = (t or {}).get("name") or (names or {}).get(base.upper())
    count = count_mentions(base.upper(), name, headlines, now)
    tp, hp = trending_points(rank), headline_points(count)
    score = min(10, tp + hp)
    trend_txt = f"CoinGecko-Trend Platz {rank + 1}" if rank is not None else "nicht in den CoinGecko-Trends"
    reason = f"{trend_txt}, {count} Schlagzeile(n) in 24h"
    return {
        "buzz_score": score, "trending_rank": "" if rank is None else rank + 1,
        "trending_points": tp, "headline_count": count, "headline_points": hp, "reason": reason,
    }


class LiveBuzzSources:
    def __init__(self, feeds: list[str] | None = None, log=print):
        self.feeds = feeds or NEWS_FEEDS
        self.log = log

    def trending(self) -> dict:
        return http_get_json(f"{COINGECKO_BASE}/search/trending")

    def headlines(self) -> list[dict]:
        out = []
        for url in self.feeds:
            try:
                out.extend(parse_rss(http_get_bytes(url)))
            except Exception as exc:
                self.log(f"  Feed nicht geladen: {url} ({exc})", file=sys.stderr)
        return out


class SnapshotBuzzSources:
    """Offline: {"trending": <CoinGecko-Antwort>, "headlines": [{"title": ..., "published": ISO}]}"""

    def __init__(self, data: dict):
        self.data = data

    @classmethod
    def from_file(cls, path: Path) -> "SnapshotBuzzSources":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def trending(self) -> dict:
        return self.data.get("trending", {"coins": []})

    def headlines(self) -> list[dict]:
        out = []
        for h in self.data.get("headlines", []):
            pub = h.get("published")
            out.append({"title": h["title"], "published": datetime.fromisoformat(pub) if pub else None})
        return out


def run(sources, data_dir: Path, now: datetime | None = None, log=print) -> list[dict]:
    now = now or utc_now()
    scanner_rows = read_rows(data_dir / "scanner.csv")
    buzz_path = data_dir / "buzz.csv"
    done = {signal_key(r["symbol"], r["candle_close_time"]) for r in read_rows(buzz_path)}
    todo = [r for r in scanner_rows if signal_key(r["symbol"], r["candle_close_time"]) not in done]
    if not todo:
        log("Buzz: nichts Neues zu bewerten")
        return []
    try:
        trending = parse_trending(sources.trending())
    except Exception as exc:
        log(f"  CoinGecko-Trends nicht geladen ({exc}); Trendpunkte = 0", file=sys.stderr)
        trending = {}
    headlines = sources.headlines()
    rows = []
    for r in todo:
        res = score_coin(r["base"], trending, headlines, now, KNOWN_NAMES)
        res.update({"scored_at": iso(now), "symbol": r["symbol"], "candle_close_time": r["candle_close_time"]})
        rows.append(res)
    append_rows(buzz_path, FIELDS, rows)
    log(f"Buzz: {len(rows)} Coin(s) bewertet ({len(headlines)} Schlagzeilen, {len(trending)} Trend-Coins) -> {buzz_path}")
    for row in rows:
        log(f"  {row['symbol']}: {row['buzz_score']}/10 - {row['reason']}")
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=default_data_dir())
    p.add_argument("--snapshot", type=Path, help="Offline-JSON statt CoinGecko/RSS")
    a = p.parse_args(argv)
    sources = SnapshotBuzzSources.from_file(a.snapshot) if a.snapshot else LiveBuzzSources()
    run(sources, a.data_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
