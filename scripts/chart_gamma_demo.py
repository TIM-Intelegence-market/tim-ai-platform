"""Chart-Dashboard mit ERFUNDENEN Testdaten und Gamma-Zonen (nur für Screenshots, ohne Börse und Datenbank).

Aufruf: python3 scripts/chart_gamma_demo.py [port]  -> http://127.0.0.1:<port>/chart?symbol=BTCUSDT&tf=30m
Baut auf scripts/chart_exo_demo.py auf; die Gamma-Level liegen um den letzten Testkurs, nichts davon ist ein Marktstand.
"""
from __future__ import annotations

import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import chart_exo_demo as demo  # noqa: E402
from src.dashboard import chart_live  # noqa: E402
from src.dashboard.app import DashboardState  # noqa: E402
from src.dashboard.server import DashboardServer  # noqa: E402


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    bars, store = demo.make_store("BTCUSDT")
    fetch = lambda symbol, interval, limit: demo.klines(bars, symbol, interval, limit)  # noqa: E731
    chart_live.CACHE.fetch = fetch
    chart_live.PERP_CACHE.fetch = fetch
    state = DashboardState()
    state.footprint = store
    state.perp_flow = dict(store)
    now = datetime.now(timezone.utc)
    last = bars[-1][4]
    rng = random.Random(3)
    points, oi = [], 82000.0
    hour0 = int(now.timestamp()) // 3600 * 3600 - demo.DAYS * 86400
    for k in range(demo.DAYS * 24 + 1):
        oi = max(60000.0, oi + rng.gauss(0, 220))
        points.append([hour0 + k * 3600, round(oi, 1), round(oi * 96000, 0)])
    state.open_interest = {"symbol": "BTCUSDT", "venue": "binance", "points": points,
                           "z": [[t, round((v - 82000) / 2500, 3)] for t, v, _ in points], "as_of": now.isoformat(), "source": "TESTDATEN"}
    levels = [("flip", "Gamma Flip", last + 180), ("call_wall", "Call Wall", last + 620), ("put_wall", "Put Wall", last - 540),
              ("max_pain", "Max Pain", last - 150), ("oi_call", "OI-Wand Call", last + 1100), ("oi_put", "OI-Wand Put", last - 1000)]
    since = (now - timedelta(hours=20)).isoformat()
    state.gamma = {"BTCUSDT": {
        "as_of": now.isoformat(), "source": "TESTDATEN", "convention": "TESTDATEN", "spot": last,
        "all_expiries": {"regime": "negative", "gamma_flip": last + 180},
        "levels": [{"key": k, "name": n, "price": round(p), "note": f"{n} (Testdaten)"} for k, n, p in levels],
        "level_since": {k: {"since": since} for k, _, _ in levels}}}
    zone_levels = {"flip": levels[0][2], "put_wall": levels[2][2]}
    zones = []
    for key, name, side, qty in (("flip", "Gamma Flip", "ask", 410.0), ("put_wall", "Put Wall", "bid", 520.0)):
        level = zone_levels[key]
        zones.append({"key": key, "name": name, "level": round(level), "low": round(level - 40), "high": round(level + 40), "side": side,
                      "wall_qty": qty, "wall_usd": qty * level, "wall_ratio": 7.2, "wall_since_ms": int((now - timedelta(hours=3)).timestamp() * 1000)})
    state.gamma_zones = {"BTCUSDT": {"ruleset": "TESTDATEN", "as_of": now.isoformat(), "status": "OK", "note": None, "walls": [], "zones": zones, "mid": last}}
    server = DashboardServer(state, port=port)
    server.start()
    print(f"http://127.0.0.1:{port}/chart?symbol=BTCUSDT&tf=30m", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
