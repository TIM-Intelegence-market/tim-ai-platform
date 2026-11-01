"""Funding rate and Coinbase premium for the TIM chart (display only, Uzi 31.10.2026).

Two lower bands next to CVD and open interest:

- ``funding``: Binance USD-M funding rate per settlement (``/fapi/v1/fundingRate``, about the
  last 500 settlements) plus the running rate of the next settlement (``/fapi/v1/premiumIndex``).
  BTC, ETH and SOL settle every 8 h, PAXG every 4 h; the chart shows the rate per settlement and
  ``rate_8h`` (scaled to 8 h) so symbols compare. Binance's base rate is 0.01 % per 8 h.
- ``premium``: Coinbase premium per hour, Coinbase ``<COIN>-USD`` close against Binance spot
  ``<COIN>USDT`` close converted to USD with Coinbase's ``USDT-USD`` close of the same hour.
  Without that correction the line would partly show the USDT price instead of US demand.
  An hour without all three closes is left out, never filled.

Public endpoints only, no key, no account. Nothing here feeds a score, a plan or an order.
Data is fetched in a background thread per symbol, so a chart request never waits for an exchange.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

FAPI = "https://fapi.binance.com"
SPOT = "https://api.binance.com"
COINBASE = "https://api.exchange.coinbase.com"
FUNDING_LIMIT = 500  # settlements: about 166 days at 8 h
PREMIUM_HOURS = 300  # Coinbase returns at most 300 candles per call
BASE_RATE_8H = 0.01  # % per 8 h, Binance's interest-rate part of the funding rate
HIGH_RATE_8H = 0.03  # % per 8 h: three times the base rate, drawn in a stronger colour (display only)
STALE_AFTER = timedelta(hours=3)
TTL = 300.0  # seconds between refreshes of one symbol
FAIL_PAUSE = 120.0
TIMEOUT_SECONDS = 10
MAX_BYTES = 4_000_000
COINBASE_PRODUCTS = {"BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD", "SOLUSDT": "SOL-USD", "PAXGUSDT": "PAXG-USD"}
FUNDING_SOURCE = "Binance USD-M Funding ({symbol}, öffentlich)"
PREMIUM_SOURCE = "Coinbase {product} vs. Binance {symbol} × Coinbase USDT-USD (1h, öffentlich)"

Fetch = Callable[[str], Any]


def fetch_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": "TIM-dashboard/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed public https endpoints above
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("answer too large")
    return json.loads(raw)


def _url(base: str, path: str, params: Mapping[str, str]) -> str:
    return f"{base}{path}?{urlencode(params)}"


def _interval_hours(times: Sequence[int]) -> float:
    """Settlement interval from the most common gap between settlements (Binance adds a few ms)."""
    gaps = [round((b - a) / 3600) for a, b in zip(times, times[1:]) if b > a]
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        return 8.0
    return float(max(set(gaps), key=gaps.count))


def funding(fetch: Fetch | None = None, symbol: str = "BTCUSDT", now: datetime | None = None) -> dict[str, Any]:
    """Funding rate history in % per settlement, its interval and the running rate."""
    fetch = fetch or fetch_json
    rows = fetch(_url(FAPI, "/fapi/v1/fundingRate", {"symbol": symbol, "limit": str(FUNDING_LIMIT)}))
    if not isinstance(rows, list):
        raise ValueError("funding: answer is not a list")
    points: list[tuple[int, float]] = []
    for row in rows:
        try:
            if row.get("symbol", symbol) != symbol:
                continue
            rate = float(row["fundingRate"]) * 100
            if not math.isfinite(rate):
                continue
            points.append((int(row["fundingTime"]) // 1000, rate))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    points = sorted(dict(points).items())
    if len(points) < 2:
        raise ValueError("funding: fewer than two settlements")
    hours = _interval_hours([t for t, _ in points])
    scale = 8.0 / hours
    current = next_time = None
    try:
        index = fetch(_url(FAPI, "/fapi/v1/premiumIndex", {"symbol": symbol}))
        current = round(float(index["lastFundingRate"]) * 100, 5)
        next_time = int(index["nextFundingTime"]) // 1000
    except Exception:  # noqa: BLE001 - the history is still worth showing without the running rate
        pass
    return {"symbol": symbol, "source": FUNDING_SOURCE.format(symbol=symbol), "as_of": (now or datetime.now(timezone.utc)).isoformat(),
            "interval_hours": hours, "points": [[t, round(r, 5)] for t, r in points],
            "current": current, "current_8h": None if current is None else round(current * scale, 5), "next_time": next_time,
            "base_8h": BASE_RATE_8H, "high_8h": HIGH_RATE_8H}


def _coinbase_closes(rows: Any) -> dict[int, float]:
    """Coinbase candles ``[time, low, high, open, close, volume]``, newest first."""
    out: dict[int, float] = {}
    if not isinstance(rows, list):
        raise ValueError("coinbase: answer is not a list")
    for row in rows:
        try:
            close = float(row[4])
            if close > 0 and math.isfinite(close):
                out[int(row[0])] = close
        except (IndexError, TypeError, ValueError):
            continue
    return out


def _binance_closes(rows: Any) -> dict[int, float]:
    out: dict[int, float] = {}
    if not isinstance(rows, list):
        raise ValueError("binance: answer is not a list")
    for row in rows:
        try:
            close = float(row[4])
            if close > 0 and math.isfinite(close):
                out[int(row[0]) // 1000] = close
        except (IndexError, TypeError, ValueError):
            continue
    return out


def coinbase_premium(fetch: Fetch | None = None, symbol: str = "BTCUSDT", now: datetime | None = None) -> dict[str, Any]:
    """Hourly Coinbase premium in % and in USD, USDT converted with Coinbase's USDT-USD close."""
    product = COINBASE_PRODUCTS.get(symbol)
    if product is None:
        raise ValueError(f"premium: no Coinbase product for {symbol}")
    fetch = fetch or fetch_json
    coinbase = _coinbase_closes(fetch(_url(COINBASE, f"/products/{product}/candles", {"granularity": "3600"})))
    usdt = _coinbase_closes(fetch(_url(COINBASE, "/products/USDT-USD/candles", {"granularity": "3600"})))
    binance = _binance_closes(fetch(_url(SPOT, "/api/v3/klines", {"symbol": symbol, "interval": "1h", "limit": str(PREMIUM_HOURS)})))
    points = []
    for hour in sorted(set(coinbase) & set(usdt) & set(binance)):
        binance_usd = binance[hour] * usdt[hour]
        points.append([hour, round((coinbase[hour] / binance_usd - 1) * 100, 4), round(coinbase[hour] - binance_usd, 2)])
    if len(points) < 2:
        raise ValueError("premium: fewer than two common hours")
    return {"symbol": symbol, "source": PREMIUM_SOURCE.format(product=product, symbol=symbol),
            "as_of": (now or datetime.now(timezone.utc)).isoformat(), "points": points,
            "last": points[-1][1], "last_usd": points[-1][2], "last_usdt_usd": usdt[points[-1][0]]}


def _stale(snapshot: Mapping[str, Any], now: datetime) -> bool:
    return now - datetime.fromisoformat(str(snapshot["as_of"])) > STALE_AFTER


def funding_chart(snapshot: Mapping[str, Any] | None, first_time: int, now: datetime | None = None) -> dict[str, Any] | None:
    """The part of the funding history the chart shows: from one settlement before the first candle on."""
    if not snapshot or not snapshot.get("points"):
        return None
    now = now or datetime.now(timezone.utc)
    hours = float(snapshot.get("interval_hours") or 8.0)
    start = first_time - int(hours * 3600)
    scale = 8.0 / hours
    points = [[t, r, round(r * scale, 5)] for t, r in snapshot["points"] if t >= start]
    if not points:
        return None
    return {"points": points, "interval_hours": hours, "current": snapshot.get("current"), "current_8h": snapshot.get("current_8h"),
            "next_time": snapshot.get("next_time"), "base_8h": snapshot.get("base_8h", BASE_RATE_8H),
            "high_8h": snapshot.get("high_8h", HIGH_RATE_8H), "as_of": snapshot["as_of"], "stale": _stale(snapshot, now),
            "source": snapshot.get("source")}


def premium_chart(snapshot: Mapping[str, Any] | None, first_time: int, now: datetime | None = None) -> dict[str, Any] | None:
    """The part of the Coinbase premium the chart shows: from one hour before the first candle on."""
    if not snapshot or not snapshot.get("points"):
        return None
    now = now or datetime.now(timezone.utc)
    points = [p for p in snapshot["points"] if p[0] >= first_time - 3600]
    if not points:
        return None
    return {"points": points, "last": snapshot.get("last"), "last_usd": snapshot.get("last_usd"), "as_of": snapshot["as_of"],
            "stale": _stale(snapshot, now), "source": snapshot.get("source")}


Builder = Callable[[str], dict[str, Any]]


class ContextCache:
    """Funding and premium per symbol, refreshed in a background thread every TTL seconds.

    ``snapshot(symbol)`` returns the last values ({"funding": ..., "premium": ...}, each None
    before its first success) and starts a refresh when they are stale. A failure keeps the last
    value; the chart hides a value older than STALE_AFTER.
    """

    def __init__(self, builders: Mapping[str, Builder] | None = None, ttl: float = TTL, fail_pause: float = FAIL_PAUSE) -> None:
        self._builders = dict(builders or {"funding": lambda s: funding(symbol=s), "premium": lambda s: coinbase_premium(symbol=s)})
        self._ttl, self._fail_pause = ttl, fail_pause
        self._lock = threading.Lock()
        self._values: dict[tuple[str, str], dict[str, Any]] = {}
        self._at: dict[str, float] = {}
        self._failed: dict[str, bool] = {}
        self._running: set[str] = set()

    def _stale(self, symbol: str) -> bool:
        pause = self._fail_pause if self._failed.get(symbol, True) else self._ttl
        return time.monotonic() - self._at.get(symbol, -math.inf) >= pause

    def refresh(self, symbol: str) -> None:
        results: dict[str, dict[str, Any]] = {}
        for key, build in self._builders.items():
            try:
                results[key] = build(symbol)
            except Exception:  # noqa: BLE001 - keep the last value, the chart marks it stale later
                continue
        with self._lock:
            for key, value in results.items():
                self._values[(key, symbol)] = value
            self._at[symbol] = time.monotonic()
            self._failed[symbol] = len(results) < len(self._builders)
            self._running.discard(symbol)

    def snapshot(self, symbol: str, background: bool = True) -> dict[str, Any]:
        with self._lock:
            start = self._stale(symbol) and symbol not in self._running
            if start:
                self._running.add(symbol)
        if start:
            if background:
                threading.Thread(target=self.refresh, args=(symbol,), name=f"tim-context-{symbol}", daemon=True).start()
            else:
                self.refresh(symbol)
        with self._lock:
            return {key: self._values.get((key, symbol)) for key in self._builders}


CACHE = ContextCache()


def chart_context(symbol: Any) -> dict[str, Any] | None:
    """Funding and premium for one chart request; only TIM's chart symbols, never a free query value.

    Tests (TIM_RUNTIME_ENV=test) get None, so no request leaves the test run.
    """
    from src.dashboard.chart_live import DEFAULT_SYMBOL, SYMBOLS

    if os.environ.get("TIM_RUNTIME_ENV") == "test":
        return None
    return CACHE.snapshot(symbol if symbol in SYMBOLS else DEFAULT_SYMBOL)
