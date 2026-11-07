"""Weekly driver states and BTC weekly returns, point in time (EINFLUSS_BAROMETER.md section 3).

The grid is one week per Monday 00:00 UTC. A driver value counts as known at a moment ``t`` when its
observation date plus the driver's ``lag_days`` is on or before ``t``; the 13-week state at ``t`` compares
the value known at ``t`` with the value known at ``t - 13 weeks``. BTC weekly returns use daily closes
strictly before 2025-01-01 (holdout), so the last week on the grid ends by 2024-12-30.
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from src.research_lab.forward.macro_filters import Series, net_liquidity_series
from src.research_lab.influence.catalog import LIQUIDITY_KEY, Driver

FIRST_WEEK = date(2017, 9, 4)  # first Monday with a full BTC history on the Binance spot archive
HOLDOUT_START = date(2025, 1, 1)
TREND_WEEKS = 13


class HoldoutError(ValueError):
    """BTC data from the holdout period reached the influence research."""


def weeks(first: date = FIRST_WEEK, end: date = HOLDOUT_START) -> list[date]:
    """Mondays whose week (Monday to Sunday) ends before ``end``."""
    if first.weekday() != 0:
        raise ValueError("the grid starts on a Monday")
    out, day = [], first
    while day + timedelta(days=7) <= end:
        out.append(day)
        day += timedelta(days=7)
    return out


def driver_series(driver: Driver, data: Mapping[str, Series]) -> Series:
    if driver.key == LIQUIDITY_KEY:
        walcl, tga, rrp = (data.get(s, []) for s in driver.series)
        return net_liquidity_series(walcl, tga, rrp)
    return sorted(data.get(driver.series[0], []))


def known_at(series: Series, moment: date, driver: Driver) -> tuple[date, float] | None:
    """Latest observation published by ``moment`` (date + lag), or None if missing or older than max_age_days."""
    dates = [d for d, _ in series]
    i = bisect_right(dates, moment - timedelta(days=driver.lag_days)) - 1
    if i < 0 or (moment - dates[i]).days > driver.max_age_days + driver.lag_days:
        return None
    return series[i]


def change(kind: str, before: float, now: float) -> float | None:
    """Change in the driver's unit: bp for rates in percent, percent for prices, plain difference otherwise."""
    if kind == "bp":
        return (now - before) * 100
    if kind == "pct":
        return None if before == 0 else (now / before - 1) * 100
    return now - before


@dataclass(frozen=True, slots=True)
class WeekRow:
    week: date
    state: str | None  # "gestiegen", "gefallen", "gleich" or None (not known)
    change_13w: float | None  # known at the week start, over the 13 weeks before it
    change_week: float | None  # from this week start to the next week start (concurrent with BTC)


def driver_weeks(driver: Driver, data: Mapping[str, Series], grid: Sequence[date]) -> list[WeekRow]:
    series = driver_series(driver, data)
    out = []
    for week in grid:
        now = known_at(series, week, driver)
        before = known_at(series, week - timedelta(weeks=TREND_WEEKS), driver)
        nxt = known_at(series, week + timedelta(weeks=1), driver)
        c13 = None if now is None or before is None else change(driver.change, before[1], now[1])
        cw = None if now is None or nxt is None else change(driver.change, now[1], nxt[1])
        state = None
        if c13 is not None:
            state = "gestiegen" if c13 > 0 else "gefallen" if c13 < 0 else "gleich"
        out.append(WeekRow(week, state, c13, cw))
    return out


def btc_weekly_returns(daily_closes: Mapping[date, float], grid: Sequence[date]) -> dict[date, float]:
    """Return in percent from the last close before the week to the last close of the week (Sunday)."""
    if any(day >= HOLDOUT_START for day in daily_closes):
        raise HoldoutError("BTC closes from 2025-01-01 onwards must not be loaded")
    out = {}
    for week in grid:
        start, end = daily_closes.get(week - timedelta(days=1)), daily_closes.get(week + timedelta(days=6))
        if start and end:
            out[week] = (end / start - 1) * 100
    return out
