"""Session preparation map ("Vorbereitungs-Karte") from TIM's own candles.

Builds the trader's preparation in the order the Broncx bootcamp teaches it
(HTF bias -> auction context -> locations), read-only and paper only:

- HTF structure on 4h, 1D and 1W, aggregated from TIM's 1h candles,
- previous day and previous week value (VAH, VAL, POC) and the developing
  value of today and this week,
- naked POCs (daily POCs no later candle has traded through),
- Asia, London and New York session high/low,
- initial balance (first 90 minutes of the UTC day) and its width,
- poor highs/lows of the previous day (two or more 30-minute periods at
  the extreme),
- where price is against the previous day's value, with a mechanical
  acceptance rule (two 30-minute closes beyond the edge).

TIM keeps candles, not trades, in the dashboard, so every profile is an
estimate: each candle's volume is spread evenly over its high-low range
(``chart_model.volume_profile``). Pure functions; the caller passes copies.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.dashboard.chart_model import _fmt, clean_candles, swing_points, volume_profile

SCHEMA = "tim_session_map/1"
HTF = (("4h", 4 * 3600), ("1D", 86400), ("1W", 7 * 86400))
IB_MINUTES = 90
ACCEPT_CLOSES = 2  # 30m closes beyond a value edge that count as acceptance
POOR_PERIODS = 2  # 30m periods at the extreme that make a high/low "poor"
COMPLETE_SHARE = 0.9  # a day/week profile counts as complete with 90 % of its candles
# Session windows in local exchange time (start, end, zone).
SESSIONS = (
    ("Asia", (9, 0), (15, 0), "Asia/Tokyo"),
    ("London", (8, 0), (16, 30), "Europe/London"),
    ("New York", (9, 30), (16, 0), "America/New_York"),
)
LOCATION_TEXT = {
    "ABOVE_ACCEPTED": ("über Vortages-Value, angenommen",
                       "AMT-Regel 3: angenommen außerhalb der Balance, neuer Value wird gesucht. "
                       "Broncx-Intraday-Modell Long: Rücklauf zum Vortages-VAH als Ort, Stop unter dem Swing."),
    "ABOVE_NOT_ACCEPTED": ("über Vortages-VAH, noch nicht angenommen",
                           "Noch keine zwei 30m-Schlüsse darüber: Gefahr einer Failed Auction zurück in den Value (AMT-Regel 1)."),
    "IN_VALUE": ("im Vortages-Value",
                 "AMT-Regel 2: in der Balance werden die Kanten eher abgelehnt, Chop in der Mitte. "
                 "Kanten faden oder warten, bis eine kippt."),
    "BELOW_NOT_ACCEPTED": ("unter Vortages-VAL, noch nicht angenommen",
                           "Noch keine zwei 30m-Schlüsse darunter: Gefahr einer Failed Auction zurück in den Value (AMT-Regel 1)."),
    "BELOW_ACCEPTED": ("unter Vortages-Value, angenommen",
                       "AMT-Regel 3: angenommen außerhalb der Balance, neuer Value wird gesucht. "
                       "Broncx-Intraday-Modell Short: Rücklauf zum Vortages-VAL als Ort, Stop über dem Swing."),
    "UNKNOWN": ("unbekannt", "Kein vollständiges Vortagesprofil vorhanden."),
}
STRUCTURE_TEXT = {"UP": "aufwärts (höhere Hochs und Tiefs)", "DOWN": "abwärts (tiefere Hochs und Tiefs)",
                  "RANGE": "seitwärts", "UNKNOWN": "zu wenig Daten"}


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _bucket(moment: datetime, label: str) -> datetime:
    moment = _utc(moment)
    if label == "4h":
        return moment.replace(hour=moment.hour - moment.hour % 4, minute=0, second=0, microsecond=0)
    day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if label == "1D":
        return day
    return day - timedelta(days=day.weekday())  # 1W: Monday 00:00 UTC


def aggregate(candles: Sequence[Mapping[str, Any]], label: str, seconds: int, now: datetime) -> list[dict[str, Any]]:
    """Higher-timeframe candles from 1h candles; ``complete`` is False for the running one."""
    groups: dict[datetime, list[Mapping[str, Any]]] = {}
    for candle in candles:
        groups.setdefault(_bucket(candle["open_time"], label), []).append(candle)
    result = []
    for opened in sorted(groups):
        items = groups[opened]
        end = opened + timedelta(seconds=seconds)
        result.append({
            "timeframe": label, "open_time": opened, "close_time": end,
            "open": items[0]["open"], "close": items[-1]["close"],
            "high": max(c["high"] for c in items), "low": min(c["low"] for c in items),
            "volume": sum(c["volume"] for c in items), "hours": len(items),
            "complete": end <= now and len(items) >= COMPLETE_SHARE * seconds / 3600,
        })
    return result


def structure(candles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Swing structure of complete candles: the last two swing highs and lows."""
    done = [c for c in candles if c.get("complete", True)]
    swings = swing_points(done)
    highs = [s["price"] for s in swings if s["kind"] == "HIGH"][-2:]
    lows = [s["price"] for s in swings if s["kind"] == "LOW"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        state = "UNKNOWN"
    elif highs[1] > highs[0] and lows[1] > lows[0]:
        state = "UP"
    elif highs[1] < highs[0] and lows[1] < lows[0]:
        state = "DOWN"
    else:
        state = "RANGE"
    return {"state": state, "text": STRUCTURE_TEXT[state], "candles": len(done),
            "swing_highs": highs, "swing_lows": lows, "last_close": done[-1]["close"] if done else None}


def htf_bias(states: Mapping[str, str]) -> dict[str, Any]:
    """1D and 4h decide; 1W only confirms. LTF never overrides this (Broncx)."""
    daily, four = states.get("1D", "UNKNOWN"), states.get("4h", "UNKNOWN")
    if daily == four == "UP":
        bias = "LONG"
    elif daily == four == "DOWN":
        bias = "SHORT"
    elif "UNKNOWN" in (daily, four):
        bias = "UNKNOWN"
    else:
        bias = "NEUTRAL"
    weekly = states.get("1W", "UNKNOWN")
    confirmed = (bias == "LONG" and weekly == "UP") or (bias == "SHORT" and weekly == "DOWN")
    text = {"LONG": "Long-Bias: 1D und 4h aufwärts", "SHORT": "Short-Bias: 1D und 4h abwärts",
            "NEUTRAL": "kein klarer Bias: 1D und 4h uneins, Level zu Level oder warten",
            "UNKNOWN": "Bias unbekannt: zu wenig 1D/4h-Kerzen"}[bias]
    if confirmed:
        text += ", Woche bestätigt"
    return {"bias": bias, "weekly_confirms": confirmed, "text": text}


def _profile(candles: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    profile = volume_profile(candles)
    if not profile:
        return None
    return {key: profile[key] for key in ("poc", "vah", "val", "step")}


def _periods(candles: Sequence[Mapping[str, Any]], key, expected: int) -> list[dict[str, Any]]:
    groups: dict[Any, list[Mapping[str, Any]]] = {}
    for candle in candles:
        groups.setdefault(key(candle["open_time"]), []).append(candle)
    result = []
    for period in sorted(groups):
        items = groups[period]
        profile = _profile(items)
        result.append({
            "period": period, "candles": items, "count": len(items),
            "complete": len(items) >= COMPLETE_SHARE * expected,
            "high": max(c["high"] for c in items), "low": min(c["low"] for c in items),
            "profile": profile,
        })
    return result


def _thirty(candles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """30-minute periods (TPO blocks) from 15m candles."""
    groups: dict[datetime, list[Mapping[str, Any]]] = {}
    for candle in candles:
        opened = _utc(candle["open_time"])
        groups.setdefault(opened.replace(minute=opened.minute - opened.minute % 30, second=0, microsecond=0), []).append(candle)
    return [{"open_time": k, "high": max(c["high"] for c in v), "low": min(c["low"] for c in v), "close": v[-1]["close"],
             "close_time": k + timedelta(minutes=30), "complete": len(v) == 2} for k, v in sorted(groups.items())]


def poor_extremes(day: Mapping[str, Any]) -> dict[str, Any]:
    """A high/low is poor when two or more 30m periods traded within one profile step of it."""
    blocks = _thirty(day["candles"])
    step = (day.get("profile") or {}).get("step") or max(day["high"] * 0.0005, 1e-9)
    at_high = sum(b["high"] >= day["high"] - step for b in blocks)
    at_low = sum(b["low"] <= day["low"] + step for b in blocks)
    return {"poor_high": at_high >= POOR_PERIODS, "poor_low": at_low >= POOR_PERIODS, "high_periods": at_high, "low_periods": at_low}


def naked_pocs(days: Sequence[Mapping[str, Any]], later: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Complete daily POCs that no candle after that day traded through."""
    result = []
    for day in days:
        poc = (day.get("profile") or {}).get("poc")
        if poc is None or not day["complete"]:
            continue
        end = datetime.combine(day["period"], time(0), tzinfo=timezone.utc) + timedelta(days=1)
        touched = any(c["open_time"] >= end and c["low"] <= poc <= c["high"] for c in later)
        if not touched:
            result.append({"day": day["period"].isoformat(), "price": poc})
    return result


def _session_windows(day: date) -> list[dict[str, Any]]:
    windows = []
    for name, start, end, zone_name in SESSIONS:
        zone = ZoneInfo(zone_name)
        begin = datetime(day.year, day.month, day.day, *start, tzinfo=zone).astimezone(timezone.utc)
        finish = datetime(day.year, day.month, day.day, *end, tzinfo=zone).astimezone(timezone.utc)
        windows.append({"name": name, "start": begin, "end": finish})
    return windows


def sessions(candles: Sequence[Mapping[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Latest occurrence of each session that has started: high, low, running or done."""
    result = []
    for offset in (0, 1):
        for window in _session_windows(_utc(now).date() - timedelta(days=offset)):
            if window["start"] > now or any(item["name"] == window["name"] for item in result):
                continue
            inside = [c for c in candles if window["start"] <= c["open_time"] < window["end"]]
            if not inside:
                continue
            result.append({"name": window["name"], "start": window["start"].isoformat(), "end": window["end"].isoformat(),
                           "high": max(c["high"] for c in inside), "low": min(c["low"] for c in inside),
                           "running": window["start"] <= now < window["end"]})
    order = [name for name, *_ in SESSIONS]
    return sorted(result, key=lambda item: order.index(item["name"]))


def initial_balance(today: Sequence[Mapping[str, Any]], previous_ranges: Sequence[float], now: datetime) -> dict[str, Any] | None:
    if not today:
        return None
    start = _utc(today[0]["open_time"]).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=IB_MINUTES)
    inside = [c for c in today if c["open_time"] < end]
    if not inside:
        return None
    high, low = max(c["high"] for c in inside), min(c["low"] for c in inside)
    ranges = sorted(r for r in previous_ranges if r > 0)
    median = ranges[len(ranges) // 2] if ranges else None
    ratio = (high - low) / median if median else None
    if ratio is None:
        width = "unbekannt"
    elif ratio < 0.25:
        width = "eng: Trendtag eher möglich"
    elif ratio > 0.5:
        width = "breit: Range-Tag eher wahrscheinlich"
    else:
        width = "mittel"
    return {"high": high, "low": low, "complete": now >= end, "ratio_to_median_day": round(ratio, 3) if ratio is not None else None, "width": width}


def location(price: float, value: Mapping[str, Any] | None, blocks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Price against the previous day's value, with the two-close acceptance rule."""
    if not value:
        key = "UNKNOWN"
    else:
        closes = [b["close"] for b in blocks if b["complete"]][-ACCEPT_CLOSES:]
        if price > value["vah"]:
            accepted = len(closes) == ACCEPT_CLOSES and all(c > value["vah"] for c in closes)
            key = "ABOVE_ACCEPTED" if accepted else "ABOVE_NOT_ACCEPTED"
        elif price < value["val"]:
            accepted = len(closes) == ACCEPT_CLOSES and all(c < value["val"] for c in closes)
            key = "BELOW_ACCEPTED" if accepted else "BELOW_NOT_ACCEPTED"
        else:
            key = "IN_VALUE"
    label, hint = LOCATION_TEXT[key]
    return {"state": key, "label": label, "hint": hint}


def _level(levels: list[dict[str, Any]], label: str, price: float | None, source: str, last: float) -> None:
    if price is None:
        return
    levels.append({"label": label, "price": price, "source": source,
                   "distance_pct": round((price - last) / last * 100, 3), "side": "über" if price > last else "unter" if price < last else "am Kurs"})


def build_session_map(series: Mapping[str, Sequence[Mapping[str, Any]]], now: datetime | None = None) -> dict[str, Any]:
    """Everything the preparation page shows, as JSON-ready data."""
    now = now or datetime.now(timezone.utc)
    hours = clean_candles(series.get("1h") or [], "1h")
    quarter = clean_candles(series.get("15m") or [], "15m")
    model: dict[str, Any] = {"schema": SCHEMA, "generated_at": now.isoformat(), "read_only": True,
                             "provenance": "PUBLIC_MARKET_DATA (Binance Spot, TIM-Runtime); Profile aus Kerzen geschätzt",
                             "notes": [], "htf": {}, "bias": None, "levels": [], "sessions": [], "initial_balance": None}
    if not quarter or not hours:
        model["notes"].append("Zu wenige 15m- oder 1h-Kerzen für die Vorbereitung.")
        return model
    last = quarter[-1]["close"]
    model["last"] = last
    model["last_time"] = quarter[-1]["close_time"].isoformat()

    states = {}
    for label, seconds in HTF:
        info = structure(aggregate(hours, label, seconds, now))
        model["htf"][label] = info
        states[label] = info["state"]
    model["bias"] = htf_bias(states)

    days = _periods(quarter, lambda moment: _utc(moment).date(), 96)
    today_date = _utc(now).date()
    previous = [d for d in days if d["period"] < today_date and d["complete"]]
    today = next((d for d in days if d["period"] == today_date), None)
    prev_day = previous[-1] if previous else None
    weeks = _periods(hours, lambda moment: _bucket(moment, "1W"), 168)
    this_week = _bucket(now, "1W")
    prev_week = next((w for w in reversed(weeks) if w["period"] < this_week and w["complete"]), None)
    current_week = next((w for w in weeks if w["period"] == this_week), None)

    model["previous_day"] = None
    if prev_day:
        model["previous_day"] = {"day": prev_day["period"].isoformat(), "high": prev_day["high"], "low": prev_day["low"],
                                 **(prev_day["profile"] or {}), **poor_extremes(prev_day)}
    else:
        model["notes"].append("Kein vollständiger Vortag in den 15m-Kerzen: Vortages-Value fehlt.")
    model["previous_week"] = ({"week": prev_week["period"].date().isoformat(), "high": prev_week["high"], "low": prev_week["low"], **(prev_week["profile"] or {})}
                              if prev_week else None)
    if not prev_week:
        model["notes"].append("Keine vollständige Vorwoche in den 1h-Kerzen: Wochen-Value fehlt.")

    blocks = _thirty(quarter)
    model["location"] = location(last, model["previous_day"] if prev_day and prev_day["profile"] else None, blocks)
    model["sessions"] = sessions(quarter, now)
    model["initial_balance"] = initial_balance(today["candles"] if today else [], [d["high"] - d["low"] for d in previous], now)
    nakeds = naked_pocs(previous, quarter)
    model["naked_pocs"] = nakeds

    levels: list[dict[str, Any]] = []
    if model["previous_day"]:
        pd = model["previous_day"]
        _level(levels, "Vortag VAH", pd.get("vah"), "Profil Vortag", last)
        _level(levels, "Vortag POC", pd.get("poc"), "Profil Vortag", last)
        _level(levels, "Vortag VAL", pd.get("val"), "Profil Vortag", last)
        _level(levels, "Vortag Hoch" + (" (poor)" if pd["poor_high"] else ""), pd["high"], "Vortag", last)
        _level(levels, "Vortag Tief" + (" (poor)" if pd["poor_low"] else ""), pd["low"], "Vortag", last)
    if model["previous_week"]:
        pw = model["previous_week"]
        for key, name in (("vah", "VAH"), ("poc", "POC"), ("val", "VAL")):
            _level(levels, f"Vorwoche {name}", pw.get(key), "Profil Vorwoche", last)
    if today and today["profile"]:
        _level(levels, "heute POC (laufend)", today["profile"]["poc"], "Profil heute", last)
    if current_week and current_week["profile"]:
        _level(levels, "Woche POC (laufend)", current_week["profile"]["poc"], "Profil Woche", last)
    for item in nakeds:
        if not prev_day or item["day"] != prev_day["period"].isoformat():
            _level(levels, f"naked POC {item['day'][8:10]}.{item['day'][5:7]}.", item["price"], "unberührter Tages-POC", last)
        elif model["previous_day"]:
            for level in levels:
                if level["label"] == "Vortag POC":
                    level["label"] = "Vortag POC (naked)"
    for session in model["sessions"]:
        _level(levels, f"{session['name']} Hoch", session["high"], "Session", last)
        _level(levels, f"{session['name']} Tief", session["low"], "Session", last)
    ib = model["initial_balance"]
    if ib:
        _level(levels, "IB Hoch", ib["high"], "Initial Balance", last)
        _level(levels, "IB Tief", ib["low"], "Initial Balance", last)
    model["levels"] = sorted(levels, key=lambda item: -item["price"])
    return model


def summary_line(model: Mapping[str, Any]) -> str:
    """One line for the Setup-Pfad and the trader journal."""
    bias = (model.get("bias") or {}).get("text") or "Bias unbekannt"
    where = (model.get("location") or {}).get("label") or "Lage unbekannt"
    last = model.get("last")
    above = [lvl for lvl in model.get("levels") or [] if lvl["side"] == "über"]
    below = [lvl for lvl in model.get("levels") or [] if lvl["side"] == "unter"]
    near = []
    if above:
        near.append(f"darüber {above[-1]['label']} {_fmt(above[-1]['price'])}")
    if below:
        near.append(f"darunter {below[0]['label']} {_fmt(below[0]['price'])}")
    price = f"Kurs {_fmt(last)} · " if last else ""
    return f"{price}{bias} · {where}" + (" · " + " · ".join(near) if near else "")
