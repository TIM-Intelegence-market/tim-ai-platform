"""Estimated liquidation heatmap from open interest and candles (pure, no network).

The idea of the commercial heatmaps (Trading Different, CoinGlass, Hyblock) in a form
TIM can check: where open interest grew, positions were opened at about that period's
price. Those positions get liquidated if price moves 1/leverage against them. We do not
know the side or the leverage of the new positions, so this module assumes:

- half of the new open interest is long, half short (``LONG_SHARE``),
- a fixed mix of leverages (``LEVERAGE_MIX``),
- liquidation exactly at ``entry * (1 -/+ 1/leverage)`` (maintenance margin ignored, so
  the real liquidation sits slightly closer to the entry),
- falling open interest closes all open estimates in proportion,
- a level is gone (swept) once a later candle trades through it.

The result is an estimate for display and analysis context only: it never trades,
writes a plan or changes a score.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

SOURCE = "BINANCE_FUTURES_OPEN_INTEREST_HIST_ESTIMATE"
LEVERAGE_MIX = ((10, 0.30), (25, 0.30), (50, 0.25), (100, 0.15))
LONG_SHARE = 0.5
STEP_FRACTION = 0.0012  # price row about 0.12 % of the price (BTC 80k -> 100 $)
MIN_SHARE = 0.02  # cells below 2 % of the strongest active cell are dropped
MAX_CELLS = 400
CLUSTER_ROWS = 2  # rows on each side summed into a cluster


@dataclass(frozen=True)
class Candle:
    time: int  # open time, epoch seconds
    high: float
    low: float
    close: float

    @property
    def typical(self) -> float:
        return (self.high + self.low + self.close) / 3


def nice_step(price: float, fraction: float = STEP_FRACTION) -> float:
    """Round ``price * fraction`` to 1, 2 or 5 times a power of ten."""
    raw = max(price * fraction, 1e-9)
    power = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 5, 10):
        if raw <= factor * power * 1.5 or factor == 10:
            return float(factor * power)
    return float(10 * power)


def _row(price: float, step: float) -> float:
    return round(math.floor(price / step + 1e-9) * step, 10)


def build_heatmap(candles: Sequence[Candle], open_interest: Mapping[int, float], as_of: datetime,
                  symbol: str = "BTCUSDT", period_seconds: int = 1800,
                  leverage_mix: Sequence[tuple[int, float]] = LEVERAGE_MIX) -> dict[str, Any]:
    """Liquidation estimate per price row.

    ``candles`` are futures candles in time order (open time in epoch seconds).
    ``open_interest`` maps a snapshot time (epoch seconds) to open interest in coins.
    The change between the snapshots at ``t`` and ``t + period`` belongs to the candle
    opened at ``t`` and is placed at that candle's typical price.
    """
    candles = sorted(candles, key=lambda c: c.time)
    if len(candles) < 2:
        raise ValueError("liquidation heatmap: need at least two candles")
    weight_sum = sum(w for _, w in leverage_mix)
    if weight_sum <= 0:
        raise ValueError("liquidation heatmap: leverage weights must be positive")
    mix = [(lev, w / weight_sum) for lev, w in leverage_mix]
    last = candles[-1].close
    step = nice_step(last)
    active: dict[tuple[str, float], dict[str, Any]] = {}  # (side, row) -> {usd, start}
    swept: list[dict[str, Any]] = []
    used = 0
    for candle in candles:
        # 1. this candle's range sweeps every level it traded through
        for key in [k for k in active if (k[0] == "long" and k[1] + step > candle.low) or (k[0] == "short" and k[1] <= candle.high)]:
            cell = active.pop(key)
            swept.append({"side": key[0], "price": key[1], "usd": cell["usd"], "start": cell["start"], "end": candle.time})
        # 2. open interest change over this candle
        before, after = open_interest.get(candle.time), open_interest.get(candle.time + period_seconds)
        if before is None or after is None or before <= 0:
            continue
        used += 1
        change = after - before
        if change < 0:
            keep = max(0.0, 1.0 + change / before)
            for cell in active.values():
                cell["usd"] *= keep
            continue
        price = candle.typical
        notional = change * price
        for leverage, weight in mix:
            for side, share, level in (("long", LONG_SHARE, price * (1 - 1 / leverage)),
                                       ("short", 1 - LONG_SHARE, price * (1 + 1 / leverage))):
                key = (side, _row(level, step))
                cell = active.setdefault(key, {"usd": 0.0, "start": candle.time})
                cell["usd"] += notional * weight * share
    cells = [{"side": side, "price": row, "usd": cell["usd"], "start": cell["start"], "end": None}
             for (side, row), cell in active.items()]
    strongest = max((c["usd"] for c in cells), default=0.0)
    floor = strongest * MIN_SHARE
    cells = [c for c in cells if c["usd"] >= floor and c["usd"] > 0]
    cells += [c for c in swept if c["usd"] >= floor and c["usd"] > 0]
    cells.sort(key=lambda c: c["usd"], reverse=True)
    cells = cells[:MAX_CELLS]
    for cell in cells:
        cell["usd"] = round(cell["usd"], 2)
    above = _cluster([c for c in cells if c["end"] is None and c["side"] == "short" and c["price"] > last], step)
    below = _cluster([c for c in cells if c["end"] is None and c["side"] == "long" and c["price"] + step <= last], step)
    analysis = {"symbol": symbol, "last": last, "step": step, "cluster_above": above, "cluster_below": below,
                "active_usd_above": round(sum(c["usd"] for c in cells if c["end"] is None and c["side"] == "short"), 2),
                "active_usd_below": round(sum(c["usd"] for c in cells if c["end"] is None and c["side"] == "long"), 2)}
    return {
        "source": SOURCE,
        "mode": "OBSERVE",
        "estimate": True,
        "symbol": symbol,
        "as_of": as_of.astimezone(timezone.utc).isoformat(),
        "last": last,
        "step": step,
        "period_seconds": period_seconds,
        "first_candle": candles[0].time,
        "periods_with_oi": used,
        "assumptions": {"long_share": LONG_SHARE, "leverage_mix": [[lev, round(w, 4)] for lev, w in mix],
                        "maintenance_margin": "ignored", "swept": "level gone once a later candle trades through it"},
        "max_usd": round(max((c["usd"] for c in cells), default=0.0), 2),
        "cells": cells,
        "analysis": analysis,
        "input_hash": _hash(candles, open_interest),
    }


def _cluster(cells: Iterable[Mapping[str, Any]], step: float) -> dict[str, Any] | None:
    """Strongest row plus its neighbours (``CLUSTER_ROWS`` each side); None when empty."""
    by_row: dict[float, float] = {}
    for cell in cells:
        by_row[cell["price"]] = by_row.get(cell["price"], 0.0) + cell["usd"]
    if not by_row:
        return None
    best_row, best_usd = None, -1.0
    for row in by_row:
        total = sum(by_row.get(round(row + k * step, 10), 0.0) for k in range(-CLUSTER_ROWS, CLUSTER_ROWS + 1))
        if total > best_usd:
            best_row, best_usd = row, total
    return {"price": round(best_row + step / 2, 2), "usd": round(best_usd, 2),
            "low": round(best_row - CLUSTER_ROWS * step, 2), "high": round(best_row + (CLUSTER_ROWS + 1) * step, 2)}


def _hash(candles: Sequence[Candle], open_interest: Mapping[int, float]) -> str:
    payload = json.dumps({"c": [[c.time, c.high, c.low, c.close] for c in candles],
                          "oi": sorted(open_interest.items())}, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
