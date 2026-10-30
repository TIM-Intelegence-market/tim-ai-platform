"""Estimated liquidation heatmap for the Control Center, from Binance's public futures data.

The runtime (main.py) calls ``refresh`` every few minutes for each chart coin. It reads two
public Binance futures endpoints (no key, no account): the open interest history and the
candles of the same period, computes the estimate with ``src.liquidation_map`` and stores it
in ``DashboardState.liquidation``. Consumers:

- ``/api/liquidation`` (full estimate plus age and freshness),
- the interactive chart: model key ``liquidation`` (heat cells, layer "liq") and two levels
  (strongest cluster above and below the price).

An estimate for display and analysis context only: nothing here trades, writes a plan or
changes a score. A failed read keeps the last estimate, which then turns stale.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.liquidation_map.heatmap import Candle, build_heatmap

BINANCE_FUTURES = "https://fapi.binance.com"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
PERIOD = "30m"
PERIOD_SECONDS = 1800
LIMIT = 500  # about ten days of 30m periods (Binance keeps 30 days of open interest history)
REFRESH_SECONDS = 300
STALE_AFTER = timedelta(minutes=20)
TIMEOUT_SECONDS = 15
MAX_BYTES = 4_000_000
LEVEL_COLOR = {"above": "#ff6b3d", "below": "#3fb6ff"}

Fetch = Callable[[str, Mapping[str, str]], Any]


def _fetch_json(path: str, params: Mapping[str, str]) -> Any:
    url = f"{BINANCE_FUTURES}{path}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "TIM-ControlCenter/1 (read-only)"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https host
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("binance response too large")
    return json.loads(body)


def parse_open_interest(rows: Any) -> dict[int, float]:
    """``/futures/data/openInterestHist`` rows -> {epoch seconds: open interest in coins}."""
    if not isinstance(rows, list):
        raise ValueError("open interest: answer is not a list")
    result = {}
    for row in rows:
        try:
            result[int(row["timestamp"]) // 1000] = float(row["sumOpenInterest"])
        except (KeyError, TypeError, ValueError):
            continue
    return result


def parse_candles(rows: Any) -> list[Candle]:
    """``/fapi/v1/klines`` rows -> candles (open time in epoch seconds)."""
    if not isinstance(rows, list):
        raise ValueError("klines: answer is not a list")
    result = []
    for row in rows:
        try:
            result.append(Candle(time=int(row[0]) // 1000, high=float(row[2]), low=float(row[3]), close=float(row[4])))
        except (IndexError, TypeError, ValueError):
            continue
    return result


def fetch_heatmap(symbol: str = "BTCUSDT", fetch: Fetch | None = None, now: datetime | None = None) -> dict[str, Any]:
    fetch = fetch or _fetch_json
    oi = parse_open_interest(fetch("/futures/data/openInterestHist", {"symbol": symbol, "period": PERIOD, "limit": str(LIMIT)}))
    candles = parse_candles(fetch("/fapi/v1/klines", {"symbol": symbol, "interval": PERIOD, "limit": str(LIMIT)}))
    if len(oi) < 2:
        raise ValueError("open interest: fewer than two snapshots")
    return build_heatmap(candles, oi, now or datetime.now(timezone.utc), symbol=symbol, period_seconds=PERIOD_SECONDS)


def refresh(state: Any, symbol: str, fetch: Fetch | None = None, now: datetime | None = None) -> dict[str, Any] | None:
    """Store a new estimate for ``symbol`` in ``state.liquidation``; None for symbols without futures data."""
    if symbol not in SYMBOLS:
        return None
    heatmap = fetch_heatmap(symbol, fetch=fetch, now=now)
    with state.lock:
        state.liquidation = {**state.liquidation, symbol: heatmap}
    return heatmap


def with_age(heatmap: Mapping[str, Any] | None, now: datetime | None = None) -> dict[str, Any] | None:
    if not heatmap:
        return None
    now = now or datetime.now(timezone.utc)
    age = now - datetime.fromisoformat(str(heatmap["as_of"]))
    return {**heatmap, "age_seconds": int(age.total_seconds()), "stale": age > STALE_AFTER}


def chart_layer(heatmap: Mapping[str, Any] | None, first_time: int, now: datetime | None = None) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    """Heat cells for the chart (model key ``liquidation``), cluster levels (group "liq") and notes.

    Cells that ended before the first candle on screen are dropped; a stale estimate draws nothing.
    """
    current = with_age(heatmap, now)
    if current is None:
        return None, [], []
    if current["stale"]:
        return None, [], [f"Liquidations-Heatmap: Binance-Stand ist {current['age_seconds'] // 60} min alt, ausgeblendet."]
    cells = [dict(c) for c in current["cells"] if c["end"] is None or c["end"] > first_time]
    layer = {"step": current["step"], "max_usd": current["max_usd"], "as_of": current["as_of"], "cells": cells,
             "source": current["source"]}
    drawings = []
    as_of = datetime.fromisoformat(str(current["as_of"]))
    start = (as_of - timedelta(days=1)).isoformat()
    for where, name, note in (("above", "Liq-Cluster oben", "stärkste geschätzte Short-Liquidationen über dem Preis"),
                              ("below", "Liq-Cluster unten", "stärkste geschätzte Long-Liquidationen unter dem Preis")):
        cluster = current["analysis"].get(f"cluster_{where}")
        if not cluster:
            continue
        drawings.append({"group": "liq", "tf": "Liq", "name": name, "label": name,
                         "price": float(cluster["price"]), "start": start, "note": note,
                         "color": LEVEL_COLOR[where], "style": "dashed"})
    return layer, drawings, []
