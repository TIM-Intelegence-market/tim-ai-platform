"""GARCH-4h volatility forecast for paper sizing (S15-4h, frozen parameters, paper only).

Uzi, 2026-11-02: "Dann für 4H morgen". S15-4h passed (docs/research_lab/studien/
S15_GARCH_VOLATILITAET_PRAEREGISTRIERUNG.md, section 9); section 6 says that using the forecast for
1 R or position sizes is a separate step, first on paper. This module is that step.

What it does: from the closed 4h candles before a moment (the latest of them must have closed less than 4 h before, else no
field) it forecasts the variance of the next 4h
log return (in percent^2) with GARCH(1,1) and the parameters of the last S15 fit (data up to
2024-12, report s15_run_2026-11-02T1815Z.json, ``last_fit``). Nothing is re-estimated, so no data
from 2025 on is used for fitting and no outcome is evaluated here. The recursion starts at the mean
r^2 of the first WARMUP periods and then runs over all given periods (as in s15.forecasts); with
beta about 0.93 the start value is forgotten after the warm-up (beta^84 < 0.01).

From the forecast it derives, for a plan with entry and stop (fields fixed when the plan is
recorded, never later):

- ``sigma_pct``: expected standard deviation of the next 4h return in percent.
- ``stop_sigma``: stop distance in percent of the entry divided by sigma_pct (how tight the stop is
  against normal 4h noise).
- ``garch_1r``: one sigma as a price distance at the entry (a reference 1 R, not used as a stop).
- ``weight``: SIGMA_REF / sigma_pct, clipped to [W_MIN, W_MAX] (volatility targeting: smaller size
  when it is wilder than usual). SIGMA_REF is the median GARCH-4h sigma per symbol in the
  validation years 2023-2024 with the same frozen parameters (computed on the Mac on 2026-11-03).
- ``risk_usd`` = RISK_USD * weight and ``size`` = risk_usd / |entry - stop| (units of the coin).

The plan journal multiplies a closed plan's net R with ``weight`` for the comparison
"Netto-R mit GARCH-Größe". It changes no plan, stop, target or count, and places no order.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

MODEL = "S15-4h garch/1"
SOURCE_REPORT = "docs/research_lab/reports/s15_run_2026-11-02T1815Z.json"
PERIOD_SECONDS = 4 * 3600
WARMUP = 84  # 14 days of 4h periods, like the 14-day rolling window of S15
RISK_USD = 1.0  # paper risk per 1 R before the weight
W_MIN, W_MAX = 0.5, 2.0

# S15-4h last_fit (expanding window up to 2024-12), percent log returns.
PARAMS: dict[str, tuple[float, float, float]] = {
    "BTCUSDT": (0.012575620705893402, 0.06284971156245814, 0.9370502874895258),
    "ETHUSDT": (0.027444075030508542, 0.0650233462024278, 0.9285225034151805),
    "SOLUSDT": (0.1036582962923517, 0.09761675357314013, 0.891654868324149),
}
# Median GARCH-4h sigma (percent) in validation 2023-2024 with the parameters above (n = 4386 each).
SIGMA_REF: dict[str, float] = {"BTCUSDT": 0.9787, "ETHUSDT": 1.1443, "SOLUSDT": 1.7967}


def symbol_key(symbol: Any) -> str:
    return "".join(ch for ch in str(symbol or "").upper() if ch.isalnum())


def _seconds(value: Any) -> float:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.timestamp() if isinstance(value, datetime) else float(value) / 1000.0


def closed_4h(candles: Sequence[Mapping[str, Any]], at: datetime) -> list[Mapping[str, Any]]:
    """The complete 4h candles that closed at or before ``at``, in time order."""
    out = []
    for c in sorted(candles, key=lambda c: _seconds(c["open_time"])):
        if c.get("closed", True) is False or c.get("close_time") is None or _seconds(c["close_time"]) > at.timestamp():
            continue
        if round(_seconds(c["close_time"]) - _seconds(c["open_time"])) not in {PERIOD_SECONDS, PERIOD_SECONDS - 1}:
            continue
        o, cl = float(c["open"]), float(c["close"])
        if o > 0 and cl > 0 and math.isfinite(o) and math.isfinite(cl):
            out.append(c)
    return out


def returns_4h(candles: Sequence[Mapping[str, Any]], at: datetime) -> list[float]:
    """Percent log returns (100 * ln(close / open), as in S15) of closed_4h()."""
    return [100.0 * math.log(float(c["close"]) / float(c["open"])) for c in closed_4h(candles, at)]


def forecast_variance(returns: Sequence[float], symbol: Any) -> float | None:
    """GARCH(1,1) variance of the next period, or None without parameters or enough periods."""
    params = PARAMS.get(symbol_key(symbol))
    if params is None or len(returns) < WARMUP:
        return None
    omega, alpha, beta = params
    h = statistics.fmean(r * r for r in returns[:WARMUP])
    for r in returns:
        h = omega + alpha * r * r + beta * h
    return h if h > 0 and math.isfinite(h) else None


def sizing(plan: Mapping[str, Any], candles_4h: Sequence[Mapping[str, Any]], at: datetime) -> dict[str, Any] | None:
    """The paper sizing fields for one plan, or None when no forecast is possible."""
    key = symbol_key(plan.get("symbol"))
    used = closed_4h(candles_4h, at)
    if not used or at.timestamp() - _seconds(used[-1]["close_time"]) >= PERIOD_SECONDS:
        return None  # the latest 4h candle is missing (failed refresh): no stale forecast
    rets = [100.0 * math.log(float(c["close"]) / float(c["open"])) for c in used]
    h = forecast_variance(rets, key)
    try:
        entry, stop = float(plan["entry"]), float(plan["stop"])
    except (KeyError, TypeError, ValueError):
        return None
    distance = abs(entry - stop)
    if h is None or entry <= 0 or distance <= 0 or not math.isfinite(distance):
        return None
    sigma = math.sqrt(h)
    weight = min(W_MAX, max(W_MIN, SIGMA_REF[key] / sigma))
    risk = RISK_USD * weight
    return {
        "model": MODEL,
        "periods": len(rets),
        "based_on": datetime.fromtimestamp(round(_seconds(used[-1]["close_time"])), tz=timezone.utc).isoformat(),
        "sigma_pct": round(sigma, 4),
        "sigma_ref_pct": SIGMA_REF[key],
        "stop_sigma": round(100.0 * distance / entry / sigma, 3),
        "garch_1r": round(sigma / 100.0 * entry, 2),
        "weight": round(weight, 3),
        "risk_usd": round(risk, 3),
        "size": round(risk / distance, 8),
    }


def weighted(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Net R of the closed entries that carry a weight: plain and with GARCH size, side by side."""
    rows = [e for e in entries if isinstance(e.get("vol_4h"), Mapping) and e.get("net_r") is not None
            and isinstance((e["vol_4h"]).get("weight"), (int, float))]
    return {
        "closed": len(rows),
        "sum_net_r": round(sum(float(e["net_r"]) for e in rows), 3),
        "sum_vol_net_r": round(sum(float(e["net_r"]) * float(e["vol_4h"]["weight"]) for e in rows), 3),
        "mean_weight": round(statistics.fmean(float(e["vol_4h"]["weight"]) for e in rows), 3) if rows else None,
    }
