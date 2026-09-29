"""Exchange sessions and full-day holidays for hypothesis S2 (protocol section 6).

Rule-based calendars for NYSE and the London Stock Exchange, 2017 to 2026,
plus the one-off closures of that period. Early closes are not modelled.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")


def easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _us_observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


@lru_cache(maxsize=None)
def nyse_holidays(year: int) -> frozenset[date]:
    days = {
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Presidents Day
        easter(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _us_observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _us_observed(date(year, 12, 25)),
    }
    new_year = date(year, 1, 1)
    if new_year.weekday() != 5:  # NYSE does not close on the Friday before a Saturday New Year
        days.add(_us_observed(new_year))
    if year >= 2022:
        days.add(_us_observed(date(year, 6, 19)))  # Juneteenth
    days |= {d for d in (date(2018, 12, 5), date(2025, 1, 9)) if d.year == year}  # national days of mourning
    return frozenset(days)


def _uk_substitute(day: date, taken: set[date]) -> date:
    while day.weekday() >= 5 or day in taken:
        day += timedelta(days=1)
    return day


@lru_cache(maxsize=None)
def lse_holidays(year: int) -> frozenset[date]:
    taken: set[date] = set()
    for fixed in (date(year, 1, 1), date(year, 12, 25), date(year, 12, 26)):
        taken.add(_uk_substitute(fixed, taken))
    taken |= {easter(year) - timedelta(days=2), easter(year) + timedelta(days=1)}
    early_may = date(2020, 5, 8) if year == 2020 else _nth_weekday(year, 5, 0, 1)
    spring = date(2022, 6, 2) if year == 2022 else _last_weekday(year, 5, 0)
    taken |= {early_may, spring, _last_weekday(year, 8, 0)}
    extra = {2022: {date(2022, 6, 3), date(2022, 9, 19)}, 2023: {date(2023, 5, 8)}}
    taken |= extra.get(year, set())
    return frozenset(taken)


SESSIONS = {
    "london": (LONDON, time(8, 0), time(16, 30), lse_holidays),
    "newyork": (NEW_YORK, time(9, 30), time(16, 0), nyse_holidays),
}


def session_bounds(name: str, day: date) -> tuple[int, int] | None:
    """UTC milliseconds [open, close) of a session on a local trading day, or None when closed."""
    zone, opens, closes, holidays = SESSIONS[name]
    if day.weekday() >= 5 or day in holidays(day.year):
        return None

    def ms(local: time) -> int:
        return int(datetime.combine(day, local, tzinfo=zone).astimezone(timezone.utc).timestamp() * 1000)

    return ms(opens), ms(closes)
