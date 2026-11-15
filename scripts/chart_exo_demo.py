"""Chart-Dashboard mit ERFUNDENEN Testdaten (nur für Screenshots, ohne Börse und Datenbank).

Aufruf: python3 scripts/chart_exo_demo.py [port]   -> http://127.0.0.1:<port>/chart?symbol=BTCUSDT&tf=15m
Die Kurse sind ein Zufallslauf mit festem Startwert; nichts davon ist ein Marktstand.
"""
from __future__ import annotations

import math
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.dashboard import chart_live  # noqa: E402
from src.dashboard.app import DashboardState  # noqa: E402
from src.dashboard.footprint_data import BUBBLE_MIN_USD  # noqa: E402
from src.dashboard.server import DashboardServer  # noqa: E402

TICK, BUCKET, DAYS = 5.0, 300, 14


def make_store(symbol: str, seed: int = 7):
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    t0 = int(start.timestamp())
    n = (int(now.timestamp()) - t0) // BUCKET + 1
    price, trend = 96000.0, 0.0
    bars, days, bubbles = [], {}, {}
    for i in range(n):
        trend = 0.97 * trend + rng.gauss(0, 6)
        sigma = 40 + 25 * (1 + math.sin(i / 90.0))
        o = price
        c = o + trend + rng.gauss(0, sigma)
        hi = max(o, c) + abs(rng.gauss(0, sigma * 0.5))
        lo = min(o, c) - abs(rng.gauss(0, sigma * 0.5))
        price = c
        t = t0 + i * BUCKET
        bars.append((t, o, hi, lo, c))
        day = datetime.fromtimestamp(t, timezone.utc).date().isoformat()
        rows = days.setdefault(day, [])
        vol = 40 + rng.random() * 60 + (80 if abs(c - o) > 2 * sigma else 0)
        centre = (o + c) / 2 + rng.gauss(0, sigma * 0.15)
        levels = int((hi - lo) / TICK) + 1
        up = 0.5 + (0.25 if c >= o else -0.25) + rng.gauss(0, 0.05)
        weights = []
        for k in range(levels):
            p = lo + k * TICK
            weights.append(math.exp(-((p - centre) / max(sigma, 1.0)) ** 2 / 1.6) + 0.02)
        total = sum(weights)
        for k, w in enumerate(weights):
            p = round((lo + k * TICK) // TICK * TICK, 8)
            q = vol * w / total
            rows.append([t, p, round(q * (1 - up) * (0.7 + rng.random() * 0.6), 4), round(q * up * (0.7 + rng.random() * 0.6), 4)])
        if rng.random() < 0.35:  # large market order
            side = 1 if rng.random() < (0.65 if c >= o else 0.35) else -1
            qty = round(rng.lognormvariate(1.3, 0.8), 3)
            p = round(lo + rng.random() * (hi - lo), 1)
            if qty * p >= BUBBLE_MIN_USD:
                bubbles.setdefault(day, []).append([int((t + rng.random() * BUCKET) * 1000), p, qty, side])
    return bars, {"symbol": symbol, "tick": TICK, "bucket_seconds": BUCKET, "source": "TESTDATEN", "updated_at": now.isoformat(),
                  "days": days, "bubbles": {k: sorted(v) for k, v in bubbles.items()}, "bubble_min_usd": BUBBLE_MIN_USD,
                  "complete": {}}


def klines(bars, symbol: str, interval: str, limit: int):
    seconds = chart_live.INTERVAL_SECONDS[interval]
    out, bucket = [], None
    for t, o, hi, lo, c in bars:
        key = t // seconds * seconds
        if bucket is None or bucket["k"] != key:
            if bucket:
                out.append(bucket)
            bucket = {"k": key, "o": o, "h": hi, "l": lo, "c": c, "v": 0.0}
        bucket["h"], bucket["l"], bucket["c"] = max(bucket["h"], hi), min(bucket["l"], lo), c
        bucket["v"] += 40 + abs(c - o) * 0.3
    out.append(bucket)
    now = datetime.now(timezone.utc)
    rows = []
    for b in out[-limit:]:
        opened = datetime.fromtimestamp(b["k"], timezone.utc)
        end = opened + timedelta(seconds=seconds)
        rows.append(dict(symbol=symbol, timeframe=interval, open_time=opened.isoformat(), close_time=end.isoformat(), open=b["o"], high=b["h"],
                         low=b["l"], close=b["c"], volume=b["v"], provenance=chart_live.PROVENANCE, closed=end <= now))
    return rows


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8790
    bars, store = make_store("BTCUSDT")
    fetch = lambda symbol, interval, limit: klines(bars, symbol, interval, limit)  # noqa: E731
    chart_live.CACHE.fetch = fetch
    chart_live.PERP_CACHE.fetch = fetch
    state = DashboardState()
    state.footprint = store
    state.perp_flow = dict(store)
    rng = random.Random(3)
    now = datetime.now(timezone.utc)
    hour0 = int(now.timestamp()) // 3600 * 3600 - DAYS * 86400
    points, oi = [], 82000.0
    for k in range(DAYS * 24 + 1):
        oi = max(60000.0, oi + rng.gauss(0, 220))
        points.append([hour0 + k * 3600, round(oi, 1), round(oi * 96000, 0)])
    zs = [[t, round((v - 82000) / 2500, 3)] for t, v, _ in points]
    state.open_interest = {"symbol": "BTCUSDT", "venue": "binance", "points": points, "z": zs, "as_of": now.isoformat(), "source": "TESTDATEN"}
    server = DashboardServer(state, port=port)
    server.start()
    print(f"http://127.0.0.1:{port}/chart?symbol=BTCUSDT&tf=15m", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
