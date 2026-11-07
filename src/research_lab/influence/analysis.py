"""Descriptive measures per driver and for all drivers together (EINFLUSS_BAROMETER.md 5a point 2, 5c point 2).

Everything is computed on the weekly grid up to 2024-12-31 and describes the past. Weeks overlap in the
13-week states, so the number of independent cases is far smaller than the number of weeks; the report
says so and gives ``n_unabhaengig`` (weeks / 13) next to every state mean.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from src.research_lab.influence.states import TREND_WEEKS, WeekRow

LAGS = (1, 2, 3, 4)
ROLLING_WEEKS = 52
FORWARD_WEEKS = 4


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def corr(pairs: Sequence[tuple[float, float]]) -> float | None:
    if len(pairs) < 10:
        return None
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(sxx * syy)


def _shift(week: date, k: int) -> date:
    return week + timedelta(weeks=k)


def forward_return(btc: Mapping[date, float], week: date, n: int) -> float | None:
    """Compounded BTC return over ``n`` weeks starting with ``week`` (percent)."""
    total = 1.0
    for k in range(n):
        r = btc.get(_shift(week, k))
        if r is None:
            return None
        total *= 1 + r / 100
    return (total - 1) * 100


def describe(rows: Sequence[WeekRow], btc: Mapping[date, float]) -> dict:
    by_week = {r.week: r for r in rows}
    states: dict[str, dict] = {}
    for name in ("gestiegen", "gefallen"):
        values = [btc[r.week] for r in rows if r.state == name and r.week in btc]
        states[name] = {"btc_woche_mittel": mean(values), "wochen": len(values),
                        "n_unabhaengig": len(values) // TREND_WEEKS}
    concurrent = [(r.change_week, btc[r.week]) for r in rows if r.change_week is not None and r.week in btc]
    lead = {k: corr([(r.change_week, btc[_shift(r.week, k)]) for r in rows
                     if r.change_week is not None and _shift(r.week, k) in btc]) for k in LAGS}
    lag = {k: corr([(btc[r.week], by_week[_shift(r.week, k)].change_week) for r in rows
                    if r.week in btc and _shift(r.week, k) in by_week
                    and by_week[_shift(r.week, k)].change_week is not None]) for k in LAGS}
    vorlauf_13w = corr([(r.change_13w, f) for r in rows if r.change_13w is not None
                        and (f := forward_return(btc, r.week, FORWARD_WEEKS)) is not None])
    rolling = []
    for i in range(ROLLING_WEEKS, len(rows) + 1):
        window = rows[i - ROLLING_WEEKS:i]
        c = corr([(r.change_week, btc[r.week]) for r in window if r.change_week is not None and r.week in btc])
        if c is not None:
            rolling.append(c)
    full = corr(concurrent)
    years: dict[int, float | None] = {}
    for year in sorted({r.week.year for r in rows}):
        years[year] = corr([p for r in rows if r.week.year == year and r.change_week is not None and r.week in btc
                            for p in [(r.change_week, btc[r.week])]])
    best_lead = max((abs(v) for v in lead.values() if v is not None), default=0.0)
    best_lag = max((abs(v) for v in lag.values() if v is not None), default=0.0)
    return {
        "zustaende": states,
        "gleichlauf": full,
        "gleichlauf_n": len(concurrent),
        "vorlauf_wochen": lead,
        "nachlauf_wochen": lag,
        "vorlauf_13w_auf_4w": vorlauf_13w,
        "rollierend_52w": {"min": min(rolling, default=None), "max": max(rolling, default=None),
                           "anteil_gleiches_vorzeichen": (None if full is None or not rolling else
                                                          sum(1 for c in rolling if (c > 0) == (full > 0)) / len(rolling))},
        "je_jahr": years,
        "folgt_dem_kurs": best_lag > best_lead,
    }


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gauss-Jordan with partial pivoting; None if the system is singular."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def _r2(xs: Sequence[Sequence[float]], ys: Sequence[float]) -> tuple[float, list[float]] | None:
    """R² and coefficients (without intercept; inputs are centred)."""
    k = len(xs[0])
    a = [[sum(x[i] * x[j] for x in xs) for j in range(k)] for i in range(k)]
    b = [sum(x[i] * y for x, y in zip(xs, ys)) for i in range(k)]
    beta = _solve(a, b)
    if beta is None:
        return None
    sst = sum(y * y for y in ys)
    sse = sum((y - sum(bi * xi for bi, xi in zip(beta, x))) ** 2 for x, y in zip(xs, ys))
    return (0.0 if sst == 0 else 1 - sse / sst), beta


def joint(rows_by_driver: Mapping[str, Sequence[WeekRow]], btc: Mapping[date, float]) -> dict:
    """All drivers together: standardised coefficients on the weekly change, R², and the R² each driver adds.

    Only weeks where every driver and BTC are known enter, so a driver with a short history shortens the
    sample for all; the report states the number of weeks."""
    keys = list(rows_by_driver)
    weekly = {k: {r.week: r.change_week for r in rows if r.change_week is not None} for k, rows in rows_by_driver.items()}
    common = sorted(w for w in btc if all(w in weekly[k] for k in keys))
    if len(common) < 10 * max(1, len(keys)):
        return {"wochen": len(common), "ergebnis": None}
    cols = {}
    for k in keys:
        vals = [weekly[k][w] for w in common]
        mu = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals))
        cols[k] = [0.0 if sd == 0 else (v - mu) / sd for v in vals]
    ys = [btc[w] for w in common]
    my = sum(ys) / len(ys)
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / len(ys)) or 1.0
    ys = [(y - my) / sy for y in ys]
    full = _r2([[cols[k][i] for k in keys] for i in range(len(common))], ys)
    if full is None:
        return {"wochen": len(common), "ergebnis": None}
    r2, beta = full
    added = {}
    for j, k in enumerate(keys):
        rest = [x for x in keys if x != k]
        part = _r2([[cols[x][i] for x in rest] for i in range(len(common))], ys) if rest else (0.0, [])
        added[k] = None if part is None else r2 - part[0]
    return {"wochen": len(common), "von": common[0].isoformat(), "bis": common[-1].isoformat(),
            "ergebnis": {"r2": r2, "beta_std": dict(zip(keys, beta)), "r2_beitrag": added}}
