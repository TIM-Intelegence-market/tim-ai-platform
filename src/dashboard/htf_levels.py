"""Higher-timeframe levels for the preparation: month, quarter and year value plus VWAPs.

Fills the part of a trader's morning prep that is usually typed in by hand
("Monthly VAL, Yearly VAL, Weekly VWAP ..."), read-only and paper only:

- value of the previous month, quarter and year (VAH, POC, VAL) and their
  high/low,
- anchored VWAPs: this week (Monday 00:00 UTC), this month (1st, 00:00 UTC)
  and the last twelve months (rolling, 365 days), each with one standard
  deviation band.

Everything comes from candles, not trades: profiles spread each candle's
volume evenly over its range (``chart_model.volume_profile``), the VWAP uses
the typical price (high + low + close) / 3 of each closed candle. Both are
estimates and can differ from TradingView. These levels are kept apart from
``session_map``'s ``levels`` on purpose: the plan journals read that list and
their rules must not change. Pure functions; the caller passes copies.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Sequence

from src.dashboard.chart_model import clean_candles, volume_profile

COMPLETE_SHARE = 0.9  # a period counts when 90 % of its candles are there
TF_SECONDS = {"30m": 1800, "1h": 3600, "1d": 86400, "1w": 604800}
ROLLING_DAYS = 365


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _start(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=timezone.utc)


def _closed(series: Mapping[str, Sequence[Mapping[str, Any]]], tf: str, now: datetime) -> list[dict[str, Any]]:
    return [c for c in clean_candles(series.get(tf) or [], tf) if c["close_time"] <= now and c.get("closed", True)]


def month_start(day: date) -> date:
    return day.replace(day=1)


def quarter_start(day: date) -> date:
    return date(day.year, (day.month - 1) // 3 * 3 + 1, 1)


def year_start(day: date) -> date:
    return date(day.year, 1, 1)


def previous_periods(today: date) -> list[dict[str, Any]]:
    """The last finished month, quarter and year as [start, end) dates with names."""
    month_end = month_start(today)
    month_begin = month_start(month_end - timedelta(days=1))
    quarter_end = quarter_start(today)
    quarter_begin = quarter_start(quarter_end - timedelta(days=1))
    year_end = year_start(today)
    year_begin = date(year_end.year - 1, 1, 1)
    return [
        {"key": "month", "tf": "1M", "start": month_begin, "end": month_end,
         "name": f"Vormonat {month_begin.month:02d}.{month_begin.year}"},
        {"key": "quarter", "tf": "1Q", "start": quarter_begin, "end": quarter_end,
         "name": f"Vorquartal Q{(quarter_begin.month - 1) // 3 + 1} {quarter_begin.year}"},
        {"key": "year", "tf": "1Y", "start": year_begin, "end": year_end, "name": f"Vorjahr {year_begin.year}"},
    ]


def period_profile(period: Mapping[str, Any], days: Sequence[Mapping[str, Any]], weeks: Sequence[Mapping[str, Any]],
                   months: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Value of one finished period from daily candles, or weekly candles when the days do not reach back.

    High and low come from the monthly candles when all months of the period
    are there (exact edges), otherwise from the candles used for the profile.
    """
    start, end = _start(period["start"]), _start(period["end"])
    expected_days = (period["end"] - period["start"]).days
    in_days = [c for c in days if start <= c["open_time"] < end]
    source, candles = None, []
    if len(in_days) >= COMPLETE_SHARE * expected_days:
        source, candles = "1d", in_days
    else:
        # Weeks start on Monday, so the first and last week can reach over the edge.
        in_weeks = [c for c in weeks if start - timedelta(days=6) < c["open_time"] < end]
        if len(in_weeks) >= COMPLETE_SHARE * expected_days / 7:
            source, candles = "1w", in_weeks
    if not candles:
        return None
    profile = volume_profile(candles)
    if not profile:
        return None
    in_months = [c for c in months if start <= c["open_time"] < end]
    expected_months = (period["end"].year - period["start"].year) * 12 + period["end"].month - period["start"].month
    edges = in_months if len(in_months) == expected_months else candles
    high, low = max(c["high"] for c in edges), min(c["low"] for c in edges)

    def inside(price: float) -> float:
        # Bin centres and edge weeks can poke past the period's range; a value level never lies outside it.
        return min(max(price, low), high)

    return {
        "key": period["key"], "tf": period["tf"], "name": period["name"],
        "start": start.isoformat(), "end": end.isoformat(), "high": high, "low": low,
        "poc": inside(profile["poc"]), "vah": inside(profile["vah"]), "val": inside(profile["val"]), "step": profile["step"],
        "source": source, "candles": len(candles),
        "estimate": "aus Tageskerzen geschätzt" if source == "1d" else "aus Wochenkerzen geschätzt, Ränder ungefähr",
    }


def vwap(candles: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Volume-weighted average of the typical price and its volume-weighted standard deviation."""
    total = sum(c["volume"] for c in candles)
    if total <= 0:
        return None
    typical = [((c["high"] + c["low"] + c["close"]) / 3, c["volume"]) for c in candles]
    value = sum(price * volume for price, volume in typical) / total
    variance = sum(volume * (price - value) ** 2 for price, volume in typical) / total
    sigma = math.sqrt(max(variance, 0.0))
    return {"value": round(value, 8), "sigma": round(sigma, 8),
            "upper": round(value + sigma, 8), "lower": round(value - sigma, 8)}


def vwap_curve(candles: Sequence[Mapping[str, Any]]) -> list[tuple[datetime, float]]:
    """Running VWAP after each candle: (open time, value) for drawing it as a line."""
    weighted = volume = 0.0
    curve = []
    for candle in candles:
        weighted += (candle["high"] + candle["low"] + candle["close"]) / 3 * candle["volume"]
        volume += candle["volume"]
        if volume > 0:
            curve.append((candle["open_time"], round(weighted / volume, 8)))
    return curve


def anchored_vwap(key: str, tf: str, name: str, anchor: datetime, sources: Sequence[tuple[str, Sequence[Mapping[str, Any]]]],
                  now: datetime) -> dict[str, Any] | None:
    """VWAP from ``anchor`` until the last closed candle, from the finest source that reaches back to the anchor."""
    for source, candles in sources:
        step = TF_SECONDS[source]
        rows = [c for c in candles if c["open_time"] >= anchor and c["close_time"] <= now]
        expected = int((now - anchor).total_seconds() // step)
        if not rows or rows[0]["open_time"] > anchor + timedelta(seconds=step) or len(rows) < COMPLETE_SHARE * expected:
            continue
        result = vwap(rows)
        if result is None:
            continue
        return {"key": key, "tf": tf, "name": name, "anchor": anchor.isoformat(), "source": source,
                "candles": len(rows), "through": rows[-1]["close_time"].isoformat(), **result}
    return None


def _level(levels: list[dict[str, Any]], label: str, price: float | None, source: str, last: float | None) -> None:
    if price is None:
        return
    item: dict[str, Any] = {"label": label, "price": price, "source": source}
    if last:
        item["distance_pct"] = round((price - last) / last * 100, 3)
        item["side"] = "über" if price > last else "unter" if price < last else "am Kurs"
    levels.append(item)


def build_htf_levels(series: Mapping[str, Sequence[Mapping[str, Any]]], now: datetime | None = None,
                     last: float | None = None) -> dict[str, Any]:
    """Month/quarter/year value and the anchored VWAPs, JSON-ready."""
    now = _utc(now or datetime.now(timezone.utc))
    days = _closed(series, "1d", now)
    weeks = _closed(series, "1w", now)
    months = _closed(series, "1M", now)
    hours = _closed(series, "1h", now)
    model: dict[str, Any] = {"profiles": [], "vwaps": [], "levels": [], "notes": []}

    for period in previous_periods(now.date()):
        profile = period_profile(period, days, weeks, months)
        if profile:
            model["profiles"].append(profile)
        else:
            model["notes"].append(f"{period['name']}: zu wenige Tages- oder Wochenkerzen für ein Profil.")

    today = now.date()
    week_anchor = _start(today - timedelta(days=today.weekday()))
    month_anchor = _start(month_start(today))
    rolling_anchor = _start(today - timedelta(days=ROLLING_DAYS))
    specs = (
        ("week", "1W", f"VWAP Woche ab {week_anchor:%d.%m.}", week_anchor, (("1h", hours), ("1d", days))),
        ("month", "1M", f"VWAP Monat ab {month_anchor:%d.%m.}", month_anchor, (("1h", hours), ("1d", days))),
        ("rolling", "12M", "VWAP 12 Monate", rolling_anchor, (("1d", days),)),
    )
    for key, tf, name, anchor, sources in specs:
        if anchor >= now:
            continue
        item = anchored_vwap(key, tf, name, anchor, sources, now)
        if item:
            model["vwaps"].append(item)
        elif anchor + timedelta(hours=1) <= now:
            model["notes"].append(f"{name}: zu wenige geschlossene Kerzen seit dem Anker.")

    levels: list[dict[str, Any]] = []
    for profile in model["profiles"]:
        source = f"Profil {profile['name']} ({profile['estimate']})"
        for key, label in (("vah", "VAH"), ("poc", "POC"), ("val", "VAL")):
            _level(levels, f"{profile['tf']} {label}", profile[key], source, last)
        _level(levels, f"{profile['tf']} Hoch", profile["high"], profile["name"], last)
        _level(levels, f"{profile['tf']} Tief", profile["low"], profile["name"], last)
    for item in model["vwaps"]:
        _level(levels, f"{item['tf']} VWAP", item["value"], f"{item['name']} ({item['source']}-Kerzen)", last)
    model["levels"] = sorted(levels, key=lambda level: -level["price"])
    return model
