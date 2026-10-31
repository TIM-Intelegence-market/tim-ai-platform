"""Data for the interactive TIM chart (/chart): candles and labelled drawings.

Read-only display data, never research data and never orders:

- candles of BTC, ETH, SOL or gold (PAXG) in every Binance interval (public klines, cached
  briefly); the newest, still open candle is shown but flagged ``closed=False``
  and never enters a level,
- drawings: every level as a labelled segment from the moment it formed to the
  newest candle ("1D VAH", "1W POC", "nPOC 1D 24.10."), BOS/MSS as segments
  from the swing to the break, and two automatic trend lines through the last
  confirmed swing highs and lows.

Levels for BTC come from the runtime series (the same data the plan journals
use); ETH, SOL and gold are display only and fetched on demand. The multi-coin
runtime stays off: nothing here writes to a journal, the database or a plan.
"""

from __future__ import annotations

import json
import math
import threading
import time
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import urlopen

from src.dashboard.chart_model import _nice_step, analytical_series, clean_candles, structure_events, swing_points

# PAXGUSDT = tokenised gold (1 PAXG = 1 troy ounce), the gold market Binance offers with the
# same public klines (Uzi 27.10.2026: gold into the analysis). It trades 24/7, real gold does not.
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "PAXGUSDT")
SYMBOL_NAMES = {"BTCUSDT": "Bitcoin", "ETHUSDT": "Ethereum", "SOLUSDT": "Solana", "PAXGUSDT": "Gold (PAXG)"}
SYMBOL_TABS = {"PAXGUSDT": "GOLD"}
GOLD_NOTE = ("Gold über PAXG (tokenisiertes Gold, 1 PAXG = 1 Feinunze): handelt rund um die Uhr, echtes Gold nicht; "
             "Wochenend-Kerzen und dünnere Liquidität können Level gegenüber XAUUSD verschieben.")
DEFAULT_SYMBOL = "BTCUSDT"
# Every interval Binance Spot offers, as on TradingView.
VIEW_TIMEFRAMES = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1w", "1M")
DEFAULT_VIEW = "30m"
LEVEL_TIMEFRAMES = ("30m", "1h", "4h", "1d", "1w", "1M")  # what the level logic (session map) reads
VIEW_LIMIT = 1000  # candles per view (Binance maximum per request)
LEVEL_LIMIT = 500  # same depth as the runtime chart history
INTERVAL_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
                    "6h": 21600, "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800, "1M": 2678400}
INTRADAY_ONLY = ("session", "ib", "running")  # not drawn on 1d and above
MAX_STRUCTURE = 6  # newest BOS/MSS segments
STRUCTURE_PIVOT = 3  # candles on each side of a structure swing (journals keep their own width)
TREND_PIVOT = 5  # wider pivots for trend lines than for BOS: only clear swings
PROVENANCE = "BINANCE_PUBLIC_KLINES_CHART_DISPLAY"
FAIL_PAUSE = 30.0  # seconds without exchange requests after a failure (one slow page, not seven)

# Colour per group; the page legend uses the same names.
GROUP_STYLE = {
    "day": ("#4c8dff", "solid"),
    "week": ("#b07cff", "solid"),
    "month": ("#ff9f43", "solid"),
    "naked": ("#f5c542", "dashed"),
    "running": ("#5ec8d8", "dotted"),
    "session": ("#8a94a6", "dotted"),
    "ib": ("#8a94a6", "dashed"),
    "structure": ("#35d39a", "solid"),
    "trend": ("#e879c6", "solid"),
    "quarter": ("#f08c4a", "solid"),
    "year": ("#ff5c9a", "solid"),
    "vwap": ("#3fd0c9", "solid"),
    "vwap_bands": ("#3fd0c9", "dotted"),
    "fib": ("#c9a227", "dotted"),
    "gamma": ("#ffb020", "solid"),  # each gamma level brings its own colour (gamma_data.LEVEL_STYLE)
    "liq": ("#ff6b3d", "dashed"),  # cluster levels bring their own colour (liquidation_data.LEVEL_COLOR)
}
GROUP_NAMES = {
    "day": "Tag (1D)", "week": "Woche (1W)", "month": "Monat (1M)", "quarter": "Quartal (1Q)", "year": "Jahr (1Y)",
    "vwap": "VWAP (Woche, Monat, Quartal, Jahr)",
    "vwap_bands": "VWAP-Bänder Woche (±1σ, ±2σ)", "naked": "naked POC",
    "running": "laufende POCs", "session": "Sessions", "ib": "Initial Balance",
    "structure": "BOS / MSS", "trend": "Trendlinien", "fib": "Fibonacci (letzter Swing)", "tpo": "TPO (Tagesprofil)",
    "vp": "Volume Profile (Tag, echte Trades)", "fp": "Footprint (Bid × Ask)", "bubbles": "Volume Bubbles (große Market Orders)",
    "plans_short": "TIM-Pläne SHORT 15m", "plans_mid": "TIM-Pläne MID 1h", "plans_long": "TIM-Pläne LONG 1D",
    "plans_old": "TIM-Pläne Testversionen 30m",
    "gamma": "Options-Gamma (Deribit)",
    "liq": "Liquidations-Heatmap (Schätzung)",
    "cvd": "CVD Spot vs. Perp", "oi": "Open Interest + Z-Score (7,5 T)",
}
# Footprint, volume profile, delta and bubbles from spot or perp trades (Beirat 29.10.2026, F5); levels stay on spot.
MARKETS = {"spot": "Spot", "perp": "Perp"}
DEFAULT_MARKET = "spot"
TPO_DAYS = 6  # finished days drawn as TPO profiles, plus the running day
TPO_BINS = 40  # price rows per day profile
TPO_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuv"  # 48 half-hour periods from 00:00 UTC
# The earlier 30m test versions start hidden: their many closed trades crowd the candles (Uzi 27.10.2026).
DEFAULT_GROUPS = ("day", "week", "month", "naked", "vwap", "vwap_bands", "structure", "trend", "tpo", "vp", "fp", "bubbles",
                  "plans_short", "plans_mid", "plans_long", "gamma", "liq", "cvd", "oi")
# TIM's paper plans on the chart (Uzi 27.10.2026: "man kann nicht richtig sehen wo die Entrys von TIM waren").
# Journal key -> (layer, short label); the earlier 30m test versions share one layer.
PLAN_JOURNALS = {"short": ("plans_short", "SHORT"), "mid": ("plans_mid", "MID"), "long": ("plans_long", "LONG"),
                 "tim": ("plans_old", "TIM 30m"), "struct": ("plans_old", "Struktur 30m"), "level": ("plans_old", "Level 30m")}
PLAN_LIMIT = 40  # newest plans drawn per chart
PLAN_SHOWN = {"OPEN", "FILLED", "CLOSED"}
# Fibonacci retracement of the newest swing leg, drawn like TradingView's Fib tool (Uzi 30.10.2026):
# 0 = end of the leg, 1 = its start, zones between the levels, 1.618 beyond the start.
# 0.886 and 0.941 come from the GoatHub EDUCATION lesson (02.10.2026): zones where price often reacts.
# Display only, never a signal or a score.
FIB_RATIOS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 0.886, 0.941, 1.0, 1.618)
# A swing counts once price moved this many average candle ranges (ATR) against it (TradingView Auto Fib: 3).
FIB_ATR_MULT = 3.0
FIB_ATR_BARS = 100  # closed candles behind the average range
FIB_MAX_STEPS = 6  # older legs looked at when the newest moves are pullbacks

Fetch = Callable[[str, str, int], list[dict[str, Any]]]


def tab_label(symbol: str) -> str:
    """Short name on the coin tabs: BTC, ETH, SOL, GOLD."""
    return SYMBOL_TABS.get(symbol, symbol.removesuffix("USDT"))


def fetch_klines(symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
    """Public Binance Spot klines, including the open candle (``closed`` False)."""
    if symbol not in SYMBOLS or interval not in INTERVAL_SECONDS:
        raise ValueError("Unsupported symbol or interval")
    query = urlencode({"symbol": symbol, "interval": interval, "limit": max(1, min(int(limit), VIEW_LIMIT))})
    with urlopen("https://api.binance.com/api/v3/klines?" + query, timeout=10) as response:
        rows = json.load(response)
    if not isinstance(rows, list):
        raise ValueError("Invalid exchange candle response")
    now = datetime.now(timezone.utc)
    result = []
    for row in rows:
        opened = datetime.fromtimestamp(row[0] / 1000, timezone.utc)
        end = datetime.fromtimestamp((row[6] + 1) / 1000, timezone.utc)
        result.append(dict(symbol=symbol, timeframe=interval, open_time=opened.isoformat(), close_time=end.isoformat(),
                           open=float(row[1]), high=float(row[2]), low=float(row[3]), close=float(row[4]),
                           volume=float(row[5]), provenance=PROVENANCE, closed=end <= now))
    return result


class KlineCache:
    """Small in-memory cache so a page full of clicks does not hammer the exchange."""

    def __init__(self, fetch: Fetch | None = None) -> None:
        self.fetch = fetch or fetch_klines
        self.lock = threading.Lock()
        self.rows: dict[tuple[str, str, int], tuple[float, list[dict[str, Any]]]] = {}
        self.failed_at: float | None = None  # last failed fetch: the exchange gets a pause, the page no wait

    @staticmethod
    def ttl(interval: str) -> float:
        seconds = INTERVAL_SECONDS[interval]
        return 10.0 if seconds <= 300 else 30.0 if seconds <= 3600 else 120.0

    def get(self, symbol: str, interval: str, limit: int) -> tuple[list[dict[str, Any]], str | None]:
        """Rows and an error note; on a failed fetch the last good rows are kept."""
        key = (symbol, interval, limit)
        with self.lock:
            cached = self.rows.get(key)
        if cached and time.monotonic() - cached[0] < self.ttl(interval):
            return [dict(r) for r in cached[1]], None
        if self.failed_at is not None and time.monotonic() - self.failed_at < FAIL_PAUSE:
            error = "Börse nicht erreichbar, neuer Versuch in Kürze."
        else:
            try:
                rows = self.fetch(symbol, interval, limit)
            except Exception as exc:  # noqa: BLE001 - network trouble must not break the page
                self.failed_at = time.monotonic()
                error = f"Börse nicht erreichbar ({type(exc).__name__})."
            else:
                self.failed_at = None
                with self.lock:
                    self.rows[key] = (time.monotonic(), rows)
                return [dict(r) for r in rows], None
        if cached:
            return [dict(r) for r in cached[1]], f"{error} Zeige Stand von vor {int(time.monotonic() - cached[0])} s."
        return [], error


CACHE = KlineCache()


def _epoch(value: Any) -> int:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def _day_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _extreme_time(candles: Sequence[Mapping[str, Any]], start: datetime, end: datetime, price: float, key: str) -> datetime:
    """Open time of the first candle in [start, end) that printed ``price`` as high/low."""
    for candle in candles:
        if start <= candle["open_time"] < end and abs(candle[key] - price) <= max(price * 1e-9, 1e-9):
            return candle["open_time"]
    return start


def _short_day(day: date) -> str:
    return f"{day.day:02d}.{day.month:02d}."


def level_drawings(series: Mapping[str, Sequence[Mapping[str, Any]]], now: datetime,
                   trades: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every reference level with timeframe, name and the moment it formed.

    Uses the session map (same rules as /prep and the level plans) and adds
    where each level starts: profile levels at the start of their day/week,
    highs and lows at the candle that printed them. With ``trades`` (TIM's
    aggTrades store, ``DashboardState.footprint``) the value levels and naked
    POCs of the days it covers come from the real trades (``trade_levels``).
    """
    from src.dashboard.session_map import build_session_map

    prep = build_session_map(series, now)
    base_tf = "30m" if series.get("30m") else "15m"
    base = [c for c in clean_candles(series.get(base_tf) or [], base_tf) if c["close_time"] <= now]
    hours = [c for c in clean_candles(series.get("1h") or [], "1h") if c["close_time"] <= now]
    out: list[dict[str, Any]] = []

    def add(group: str, tf: str, name: str, price: float | None, start: datetime, note: str = "") -> None:
        if price is None:
            return
        out.append({"group": group, "tf": tf, "name": name, "label": f"{tf} {name}".strip(), "price": float(price),
                    "start": start.isoformat(), "note": note})

    pd = prep.get("previous_day")
    if pd:
        day = date.fromisoformat(pd["day"])
        start, end = _day_start(day), _day_start(day) + timedelta(days=1)
        note = f"Vortag {_short_day(day)}"
        for key, name in (("vah", "VAH"), ("poc", "POC"), ("val", "VAL")):
            add("day", "1D", name, pd.get(key), start, note)
        add("day", "1D", "High" + (" (poor)" if pd.get("poor_high") else ""), pd.get("high"), _extreme_time(base, start, end, pd["high"], "high"), note)
        add("day", "1D", "Low" + (" (poor)" if pd.get("poor_low") else ""), pd.get("low"), _extreme_time(base, start, end, pd["low"], "low"), note)
    pw = prep.get("previous_week")
    if pw:
        start = _day_start(date.fromisoformat(pw["week"]))
        end = start + timedelta(days=7)
        note = f"Vorwoche ab {_short_day(start.date())}"
        for key, name in (("vah", "VAH"), ("poc", "POC"), ("val", "VAL")):
            add("week", "1W", name, pw.get(key), start, note)
        add("week", "1W", "High", pw.get("high"), _extreme_time(hours, start, end, pw["high"], "high"), note)
        add("week", "1W", "Low", pw.get("low"), _extreme_time(hours, start, end, pw["low"], "low"), note)
    months = [c for c in clean_candles(series.get("1M") or [], "1M") if c["close_time"] <= now]
    if months:
        month = months[-1]
        days = [c for c in clean_candles(series.get("1d") or [], "1d")]
        note = f"Vormonat {month['open_time'].strftime('%m.%Y')}"
        for key, name in (("high", "High"), ("low", "Low")):
            moment = _extreme_time(days, month["open_time"], month["close_time"], month[key], key) if days else month["open_time"]
            add("month", "1M", name, month[key], moment, note)
    for profile in (prep.get("htf_levels") or {}).get("profiles") or []:
        group = {"1M": "month", "1Q": "quarter", "1Y": "year"}[profile["tf"]]
        start = datetime.fromisoformat(profile["start"])
        for key, name in (("vah", "VAH"), ("poc", "POC"), ("val", "VAL")):
            add(group, profile["tf"], name, profile.get(key), start, f"{profile['name']}, {profile['estimate']}")
        if group != "month":  # the month's high/low is drawn above from the monthly candle
            add(group, profile["tf"], "High", profile.get("high"), start, profile["name"])
            add(group, profile["tf"], "Low", profile.get("low"), start, profile["name"])
    prev_day = pd["day"] if pd else None
    for item in prep.get("naked_pocs") or []:
        if item["day"] == prev_day:
            continue  # the previous day's POC is already drawn as "1D POC"
        day = date.fromisoformat(item["day"])
        add("naked", "1D", f"nPOC {_short_day(day)}", item["price"], _day_start(day), "unberührter Tages-POC")
    today = _day_start(now.astimezone(timezone.utc).date())
    week = today - timedelta(days=today.weekday())
    for level in prep.get("levels") or []:
        if "heute POC (laufend)" in level["label"]:
            add("running", "1D", "POC lfd.", level["price"], today, "laufendes Tagesprofil")
        if "Woche POC (laufend)" in level["label"]:
            add("running", "1W", "POC lfd.", level["price"], week, "laufendes Wochenprofil")
    for session in prep.get("sessions") or []:
        begin = datetime.fromisoformat(session["start"])
        add("session", "", f"{session['name']} High", session["high"], begin, "Session" + (" (läuft)" if session.get("running") else ""))
        add("session", "", f"{session['name']} Low", session["low"], begin, "Session" + (" (läuft)" if session.get("running") else ""))
    ib = prep.get("initial_balance")
    if ib:
        add("ib", "", "IB High", ib["high"], today, "Initial Balance (90 min ab 00:00 UTC)")
        add("ib", "", "IB Low", ib["low"], today, "Initial Balance (90 min ab 00:00 UTC)")
    if trades and trades.get("days"):
        out = trade_levels(out, trades, series, now)
    return out


TRADE_NOTE = "echte Trades"


def _week_rows(store: Mapping[str, Any], monday: date, last: date) -> list[list[float]] | None:
    """Stored rows of the days ``monday`` .. ``last``, or None when a day is missing or was not read in full."""
    days, complete = store.get("days") or {}, store.get("complete") or {}
    rows: list[list[float]] = []
    day = monday
    while day <= last:
        key = day.isoformat()
        if key not in days:
            return None
        if key not in complete and day != last:
            return None
        rows.extend(days[key])
        day += timedelta(days=1)
    return rows


def trade_levels(drawings: Sequence[Mapping[str, Any]], store: Mapping[str, Any], series: Mapping[str, Sequence[Mapping[str, Any]]],
                 now: datetime) -> list[dict[str, Any]]:
    """Value levels and naked POCs from TIM's own trades instead of the candle estimate (Beirat 29.10.2026).

    For every day the store covers: previous day VAH/POC/VAL, previous week value (when all
    seven days are stored), the running day/week POC, and naked POCs of both kinds, as Broncx
    marks them: vPOC (most volume, real trades) and tPOC (most 30m periods). A POC is naked
    while no later trade (vPOC) or closed candle (tPOC) has printed inside its row. Days older
    than the store keep the candle estimate, marked as such. The plan journals do not read
    this (they call ``build_session_map`` directly), so their rules stay unchanged.
    """
    from src.dashboard.footprint_data import profile_from_rows, volume_profiles

    tick = float(store["tick"])
    profiles = {p["day"]: p for p in volume_profiles(store, now)}
    if not profiles:
        return [dict(d) for d in drawings]
    first_day = min(profiles)
    today = now.astimezone(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    monday = today - timedelta(days=today.weekday())
    replaced: set[tuple[str, str]] = set()
    added: list[dict[str, Any]] = []

    def add(group: str, tf: str, name: str, price: float, start: datetime, note: str) -> None:
        added.append({"group": group, "tf": tf, "name": name, "label": f"{tf} {name}".strip(), "price": float(price),
                      "start": start.isoformat(), "note": note, "source": "trades"})

    previous = profiles.get(yesterday)
    if previous and previous["complete"]:
        day = date.fromisoformat(yesterday)
        note = f"Vortag {_short_day(day)}, {TRADE_NOTE}"
        for key, name in (("vah", "VAH"), ("poc_mid", "POC"), ("val", "VAL")):
            add("day", "1D", name, previous[key], _day_start(day), note)
        replaced |= {("day", "VAH"), ("day", "POC"), ("day", "VAL")}
    week_rows = _week_rows(store, monday - timedelta(days=7), monday - timedelta(days=1))
    week = profile_from_rows(week_rows, tick) if week_rows else None
    if week:
        start = _day_start(monday - timedelta(days=7))
        note = f"Vorwoche ab {_short_day(start.date())}, {TRADE_NOTE}"
        for key, name in (("vah", "VAH"), ("poc_mid", "POC"), ("val", "VAL")):
            add("week", "1W", name, week[key], start, note)
        replaced |= {("week", "VAH"), ("week", "POC"), ("week", "VAL")}
    running = profiles.get(today.isoformat())
    if running:
        add("running", "1D", "POC lfd.", running["poc_mid"], _day_start(today), f"laufendes Tagesprofil, {TRADE_NOTE}")
        replaced.add(("running_day", ""))
        this_week_rows = _week_rows(store, monday, today)
        this_week = profile_from_rows(this_week_rows, tick) if this_week_rows else None
        if this_week:
            add("running", "1W", "POC lfd.", this_week["poc_mid"], _day_start(monday), f"laufendes Wochenprofil, {TRADE_NOTE}")
            replaced.add(("running_week", ""))

    # Naked vPOCs: no later trade inside the POC row (stored levels are multiples of the tick).
    levels_by_day = {key: {round(float(r[1]), 8) for r in rows} for key, rows in store["days"].items()}
    for key, profile in sorted(profiles.items()):
        if not profile["complete"] or key in (today.isoformat(), yesterday):
            continue
        later: set[float] = set().union(*(v for k, v in levels_by_day.items() if k > key))
        inside = {round(profile["poc"] + i * tick, 8) for i in range(max(1, round(profile["step"] / tick)))}
        if not inside & later:
            day = date.fromisoformat(key)
            add("naked", "1D", f"nPOC {_short_day(day)}", profile["poc_mid"], _day_start(day), f"unberührter Volumen-POC (vPOC), {TRADE_NOTE}")
    # Naked tPOCs: no later closed candle inside the TPO POC row.
    base_tf = "30m" if series.get("30m") else "15m"
    candles = [c for c in clean_candles(series.get(base_tf) or [], base_tf) if c["close_time"] <= now]
    for profile in tpo_profiles(series, now, days=14):
        if profile["running"] or profile["day"] == yesterday or profile["periods"] < 44:
            continue
        end = datetime.fromisoformat(profile["end"])
        low, high = profile["poc"], profile["poc"] + profile["step"]
        if not any(c["open_time"] >= end and c["low"] < high and c["high"] >= low for c in candles):
            day = date.fromisoformat(profile["day"])
            add("naked", "1D", f"tPOC {_short_day(day)}", low + profile["step"] / 2, _day_start(day), "unberührter TPO-POC (Zeit, 30m-Perioden)")

    result = []
    for item in drawings:
        group, name = item["group"], item["name"]
        if (group, name) in replaced:
            continue
        if group == "running" and ((item["tf"] == "1D" and ("running_day", "") in replaced) or (item["tf"] == "1W" and ("running_week", "") in replaced)):
            continue
        if group == "naked":
            if item["start"][:10] >= first_day:
                continue  # covered by the trades: vPOC/tPOC above decide
            item = {**item, "note": "unberührter Tages-POC (Schätzung aus Kerzen)"}
        result.append(dict(item))
    return result + added


def structure_swings(candles: Sequence[Mapping[str, Any]], width: int = STRUCTURE_PIVOT) -> list[dict[str, Any]]:
    """Swing highs/lows for the chart's market structure.

    Like ``chart_model.swing_points`` but equal highs (double tops) and equal
    lows count: the last of two equal extremes is the swing (``>=`` to the
    left, ``>`` to the right). The plan journals keep their own swing rule.
    """
    result = []
    for index in range(width, len(candles) - width):
        candle = candles[index]
        left, right = candles[index - width:index], candles[index + 1:index + width + 1]
        if all(candle["high"] >= c["high"] for c in left) and all(candle["high"] > c["high"] for c in right):
            result.append({"index": index, "price": candle["high"], "kind": "HIGH"})
        if all(candle["low"] <= c["low"] for c in left) and all(candle["low"] < c["low"] for c in right):
            result.append({"index": index, "price": candle["low"], "kind": "LOW"})
    return result


def market_structure(candles: Sequence[Mapping[str, Any]], timeframe: str, width: int = STRUCTURE_PIVOT) -> dict[str, Any]:
    """BOS and MSS of the swing structure, causal, decided by the close (wicks never break).

    - No trend yet: the first close beyond the latest confirmed swing high or low is a BOS
      and sets the trend.
    - Uptrend: BOS up = close above the highest swing high confirmed since the last break
      and above the broken level (the top of the leg; a wick through it is a sweep, not a
      break). At every break up, the lowest low between the broken swing and the break
      becomes the protected low (origin of the impulse, "Strong Low"); every new, higher
      swing high lifts it to the last confirmed swing low before that high (the higher low
      that launched the move).
      MSS down = close below the protected low. Internal swing lows of a pullback do not
      flip the trend. Downtrend mirrored.
    A swing is known at the close of the ``width``-th candle after it (confirmation); that
    close and later ones can break it.
    Mechanical price structure for the display, not an orderflow signal and not a plan.

    Returns ``events`` (oldest first) and the state after the last closed candle:
    ``trend``, ``protected`` (the level whose close-break would be the next MSS) and
    ``target`` (the swing whose close-break would be the next BOS), each with its candle index.
    """
    by_confirm: dict[int, list[dict[str, Any]]] = {}
    for s in structure_swings(candles, width):
        by_confirm.setdefault(s["index"] + width, []).append(s)  # known at the close of the width-th candle after it
    trend: str | None = None
    last_break, last_level = -1, None
    latest: dict[str, dict[str, Any]] = {}  # before a trend: newest confirmed swing per side
    seen: dict[str, list[dict[str, Any]]] = {"HIGH": [], "LOW": []}  # all confirmed swings, oldest first
    pending: dict[str, dict[str, Any] | None] = {"HIGH": None, "LOW": None}  # next BOS level per side
    protected: dict[str, Any] | None = None  # {"index", "price"} on the opposite side of the trend
    events: list[dict[str, Any]] = []

    def emit(kind: str, direction: str, index: int, price: float, i: int) -> None:
        events.append({"kind": kind, "direction": direction, "timeframe": timeframe, "level": price,
                       "swing_time": candles[index]["open_time"].isoformat(),
                       "break_time": candles[i]["open_time"].isoformat(), "break_index": i, "swing_index": index})

    def origin(direction: str, start: int, end: int) -> dict[str, Any]:
        """Extreme between the broken level and the break: lowest low after a break up, highest high after a break down."""
        span = range(start, end + 1)
        if direction == "UP":
            index = min(span, key=lambda j: (candles[j]["low"], -j))
            return {"index": index, "price": candles[index]["low"]}
        index = max(span, key=lambda j: (candles[j]["high"], j))
        return {"index": index, "price": candles[index]["high"]}

    for i, candle in enumerate(candles):
        for s in by_confirm.get(i, []):
            latest[s["kind"]] = s
            seen[s["kind"]].append(s)
            # Next BOS level: the most extreme swing after the last break and beyond the broken level
            # (a higher high in an uptrend, a lower low in a downtrend); internal swings of a pullback do not count.
            beyond = last_level is None or (s["price"] > last_level if s["kind"] == "HIGH" else s["price"] < last_level)
            current = pending[s["kind"]]
            extreme = current is None or (s["price"] > current["price"] if s["kind"] == "HIGH" else s["price"] < current["price"])
            if s["index"] >= last_break and beyond and extreme:
                if trend is not None and s["kind"] == ("HIGH" if trend == "UP" else "LOW"):
                    # A new extreme of the trend leg (also a wick-only higher high / lower low): the protected
                    # level moves up (down) to the last confirmed swing low (high) before it, the higher low
                    # (lower high) that launched the move. It only ever tightens.
                    before = [x for x in seen["LOW" if trend == "UP" else "HIGH"] if x["index"] < s["index"]]
                    if before:
                        candidate = {"index": before[-1]["index"], "price": before[-1]["price"]}
                        if protected is None or (candidate["price"] > protected["price"] if trend == "UP" else candidate["price"] < protected["price"]):
                            protected = candidate
                pending[s["kind"]] = s
        close = candle["close"]
        if trend is None:
            for side, direction in (("HIGH", "UP"), ("LOW", "DOWN")):
                s = latest.get(side)
                if s and (close > s["price"] if direction == "UP" else close < s["price"]):
                    emit("BOS", direction, s["index"], s["price"], i)
                    trend, last_break, last_level, protected = direction, i, s["price"], origin(direction, s["index"], i)
                    pending = {"HIGH": None, "LOW": None}
                    break
            continue
        side = "HIGH" if trend == "UP" else "LOW"
        target = pending[side]
        if target and (close > target["price"] if trend == "UP" else close < target["price"]):
            emit("BOS", trend, target["index"], target["price"], i)
            last_break, last_level, protected = i, target["price"], origin(trend, target["index"], i)
            pending = {"HIGH": None, "LOW": None}
            continue
        if protected and (close < protected["price"] if trend == "UP" else close > protected["price"]):
            direction = "DOWN" if trend == "UP" else "UP"
            emit("MSS", direction, protected["index"], protected["price"], i)
            trend, last_break, last_level, protected = direction, i, protected["price"], origin(direction, protected["index"], i)
            pending = {"HIGH": None, "LOW": None}
    target = pending["HIGH" if trend == "UP" else "LOW"] if trend else None
    return {"events": events, "trend": trend, "protected": protected, "target": target}


def structure_drawings(candles: Sequence[Mapping[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    """Newest BOS/MSS as segments from the broken level to the break, plus the open structure levels.

    The open levels run to the newest candle: "Strong Low"/"Strong High" (a close beyond = MSS)
    and "BOS-Ziel" (a close beyond = next BOS in the trend direction).
    """
    closed = [c for c in candles if c.get("closed", True)]
    structure = market_structure(closed, timeframe)
    result = []
    for event in structure["events"][-MAX_STRUCTURE:]:
        arrow = "↑" if event["direction"] == "UP" else "↓"
        what = "Bruch des Swings" if event["kind"] == "BOS" else "Bruch des " + ("Strong Low" if event["direction"] == "DOWN" else "Strong High")
        result.append({"group": "structure", "tf": timeframe, "name": f"{event['kind']} {arrow}", "label": f"{timeframe} {event['kind']} {arrow}",
                       "price": event["level"], "start": event["swing_time"], "end": event["break_time"],
                       "direction": event["direction"], "note": f"{what}, per Schlusskurs (Docht zählt nicht)"})
    trend = structure["trend"]
    if trend:
        level = structure["protected"]
        name = "Strong Low" if trend == "UP" else "Strong High"
        if level:
            result.append({"group": "structure", "tf": timeframe, "name": name, "label": f"{timeframe} {name}", "open": True,
                           "price": level["price"], "start": closed[level["index"]]["open_time"].isoformat(),
                           "direction": "DOWN" if trend == "UP" else "UP",
                           "note": f"Trend {'auf' if trend == 'UP' else 'ab'}wärts; Schlusskurs {'darunter' if trend == 'UP' else 'darüber'} = MSS"})
        target = structure["target"]
        if target:
            arrow = "↑" if trend == "UP" else "↓"
            result.append({"group": "structure", "tf": timeframe, "name": f"BOS-Ziel {arrow}", "label": f"{timeframe} BOS-Ziel {arrow}", "open": True,
                           "price": target["price"], "start": closed[target["index"]]["open_time"].isoformat(), "direction": trend,
                           "note": f"Schlusskurs {'darüber' if trend == 'UP' else 'darunter'} = BOS"})
    return result


def trend_drawings(candles: Sequence[Mapping[str, Any]], timeframe: str, width: int = TREND_PIVOT) -> list[dict[str, Any]]:
    """Trend lines through the last two confirmed swing highs and the last two swing lows.

    Straight in candle steps (as the chart's time axis), drawn to the newest
    candle or to the first close through the line ("gebrochen"). A picture of
    the structure, not a signal.
    """
    closed = [c for c in candles if c.get("closed", True)]
    if len(closed) < 2 * width + 3:
        return []
    swings = swing_points(closed, width)
    last = len(closed) - 1
    result = []
    for kind, name in (("HIGH", "Trend Hochs"), ("LOW", "Trend Tiefs")):
        points = [s for s in swings if s["kind"] == kind][-2:]
        if len(points) < 2:
            continue
        first, second = points
        slope = (second["price"] - first["price"]) / (second["index"] - first["index"])
        end, broken = last, False
        for index in range(second["index"] + 1, last + 1):  # the line ends where a close goes through it
            value = second["price"] + slope * (index - second["index"])
            if (closed[index]["close"] > value) if kind == "HIGH" else (closed[index]["close"] < value):
                end, broken = index, True
                break
        end_price = second["price"] + slope * (end - second["index"])
        if end_price <= 0:
            continue
        arrow = "↑" if slope > 0 else "↓" if slope < 0 else "→"
        suffix = " gebrochen" if broken else ""
        result.append({"group": "trend", "tf": timeframe, "name": f"{name} {arrow}{suffix}", "label": f"{timeframe} {name} {arrow}{suffix}",
                       "price": end_price, "start": closed[first["index"]]["open_time"].isoformat(), "broken": broken,
                       "end": closed[end]["open_time"].isoformat(), "start_price": first["price"],
                       "anchor_time": closed[second["index"]]["open_time"].isoformat(), "anchor_price": second["price"],
                       "note": f"durch die letzten zwei Swing-{'Hochs' if kind == 'HIGH' else 'Tiefs'} ({width} Kerzen je Seite)"})
    return result


BAND_KEYS = ("week",)  # VWAPs drawn with ±1σ/±2σ bands (Broncx: weekly VWAP ±2σ)
BANDS = ((2, "+2σ"), (1, "+1σ"), (-1, "−1σ"), (-2, "−2σ"))


def vwap_drawings(vwaps: Sequence[Mapping[str, Any]], candles: Sequence[Mapping[str, Any]], timeframe: str,
                  now: datetime) -> list[dict[str, Any]]:
    """Anchored VWAPs: a running line over the shown candles when the anchor is in view, else the current value.

    The line is recomputed from the shown candles (typical price, including the
    running candle); the current value comes from the session map's VWAP. The
    weekly VWAP brings its ±1σ and ±2σ bands (group "vwap_bands"), running with
    the line or, when the anchor is not in view, as the current band values.
    """
    from src.dashboard.htf_levels import vwap_band_curve

    out = []
    first = candles[0]["open_time"] if candles else None
    for item in vwaps:
        anchor = datetime.fromisoformat(item["anchor"])
        base = {"group": "vwap", "tf": item["tf"], "name": "VWAP", "label": f"{item['tf']} VWAP", "price": float(item["value"]),
                "note": f"{item['name']}, aus {item['source']}-Kerzen"}
        bands = item["key"] in BAND_KEYS and item.get("sigma") is not None
        if first is not None and anchor >= first and INTERVAL_SECONDS[timeframe] <= 86400:
            curve = vwap_band_curve([c for c in candles if c["open_time"] >= anchor])
            if len(curve) >= 2:
                note = f"{item['name']}, Linie aus den gezeigten Kerzen"
                out.append({**base, "price": curve[-1][1], "start": curve[0][0].isoformat(), "note": note,
                            "curve": [[_epoch(moment), value] for moment, value, _ in curve]})
                if bands:
                    for factor, name in BANDS:
                        out.append({**base, "group": "vwap_bands", "name": f"VWAP {name}", "label": f"{item['tf']} VWAP {name}",
                                    "price": curve[-1][1] + factor * curve[-1][2], "start": curve[0][0].isoformat(), "note": f"{note}, Band {name}",
                                    "curve": [[_epoch(moment), value + factor * sigma] for moment, value, sigma in curve]})
                continue
        out.append({**base, "start": now.isoformat()})
        if bands:
            for factor, name in BANDS:
                out.append({**base, "group": "vwap_bands", "name": f"VWAP {name}", "label": f"{item['tf']} VWAP {name}",
                            "price": float(item["value"]) + factor * float(item["sigma"]), "start": now.isoformat(),
                            "note": f"{base['note']}, Band {name}"})
    return out


def zigzag_pivots(candles: Sequence[Mapping[str, Any]], threshold: float) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Swing highs/lows that matter: a wick extreme becomes a pivot once price moved ``threshold`` against it.

    Walks the candles in time order (causal, wicks). Returns the confirmed pivots (oldest first,
    alternating HIGH/LOW) and the running extreme of the leg since the last pivot (not confirmed yet).
    """
    if not candles:
        return [], None
    pivots: list[dict[str, Any]] = []
    high = {"index": 0, "price": candles[0]["high"], "kind": "HIGH"}
    low = {"index": 0, "price": candles[0]["low"], "kind": "LOW"}
    direction: str | None = None  # "UP" = hunting the next high, "DOWN" = hunting the next low
    for i, c in enumerate(candles):
        if direction in (None, "UP") and c["high"] > high["price"]:
            high = {"index": i, "price": c["high"], "kind": "HIGH"}
        if direction in (None, "DOWN") and c["low"] < low["price"]:
            low = {"index": i, "price": c["low"], "kind": "LOW"}
        if direction is None:
            if high["price"] - low["price"] >= threshold:
                # the older extreme starts the first leg
                first, direction = (low, "UP") if low["index"] < high["index"] else (high, "DOWN")
                pivots.append(first)
            continue
        # Within one candle the order of high and low is unknown: the reversal needs a later candle.
        if direction == "UP" and high["index"] < i and high["price"] - c["low"] >= threshold:
            pivots.append(high)
            direction = "DOWN"
            low = min(({"index": j, "price": candles[j]["low"], "kind": "LOW"} for j in range(high["index"] + 1, i + 1)),
                      key=lambda x: (x["price"], -x["index"]))
        elif direction == "DOWN" and low["index"] < i and c["high"] - low["price"] >= threshold:
            pivots.append(low)
            direction = "UP"
            high = max(({"index": j, "price": candles[j]["high"], "kind": "HIGH"} for j in range(low["index"] + 1, i + 1)),
                       key=lambda x: (x["price"], x["index"]))
    running = None if direction is None else (high if direction == "UP" else low)
    return pivots, running


def average_range(candles: Sequence[Mapping[str, Any]], bars: int = FIB_ATR_BARS) -> float:
    """Mean true range of the newest ``bars`` candles (0 without candles)."""
    tail = list(candles[-(bars + 1):])
    ranges = [max(c["high"], p["close"]) - min(c["low"], p["close"]) for p, c in zip(tail, tail[1:])]
    if not ranges and tail:
        ranges = [tail[0]["high"] - tail[0]["low"]]
    return sum(ranges) / len(ranges) if ranges else 0.0


def fib_retracement(candles: Sequence[Mapping[str, Any]], timeframe: str,
                    mult: float = FIB_ATR_MULT) -> dict[str, Any] | None:
    """Fibonacci retracement of the newest swing leg, like a Fib drawn by hand in TradingView.

    Swings come from a zigzag on the closed candles' wicks: a high or low counts once price moved
    ``mult`` x the average candle range against it, so small wiggles never start a new leg.
    The leg is the newest move that every later candle stayed inside: while price only pulls back
    (bounce, lower high, drift) the fib stays on the impulse; once a candle trades beyond the leg,
    the running move from the last pivot to its extreme so far is the new leg.
    Level 0 sits at the end of the leg, 1 at its start, as in TradingView. The open candle never
    moves an anchor. A picture of zones, not a signal.
    """
    closed = [c for c in candles if c.get("closed", True)]
    if len(closed) < 3:
        return None
    threshold = mult * average_range(closed)
    if threshold <= 0:
        return None
    pivots, running = zigzag_pivots(closed, threshold)
    if not pivots or running is None:
        return None
    points = pivots + [running]
    legs = list(zip(points, points[1:]))
    if not legs:
        return None
    # Start with the running leg and step back while an older leg still holds everything after it
    # (a later high/low beyond its range would be a break): the moves after it are only pullbacks.
    chosen = len(legs) - 1
    for k in range(len(legs) - 2, max(-1, len(legs) - 1 - FIB_MAX_STEPS), -1):
        a, b = legs[k]
        low, high = min(a["price"], b["price"]), max(a["price"], b["price"])
        later = closed[b["index"] + 1:]
        if later and (min(c["low"] for c in later) < low or max(c["high"] for c in later) > high):
            break
        chosen = k
    start, end = legs[chosen]
    span = end["price"] - start["price"]
    if span == 0 or end["index"] <= start["index"]:
        return None
    up = span > 0
    levels = [{"ratio": ratio, "price": end["price"] - span * ratio} for ratio in FIB_RATIOS]
    side, anchors = ("Long", "Swing-Tief → Hoch") if up else ("Short", "Swing-Hoch → Tief")
    finished = chosen != len(legs) - 1
    return {"group": "fib", "tf": timeframe, "direction": "UP" if up else "DOWN",
            "start": _epoch(closed[start["index"]]["open_time"]), "start_price": start["price"],
            "end": _epoch(closed[end["index"]]["open_time"]), "end_price": end["price"],
            "finished": finished, "levels": levels, "threshold": round(threshold, 8),
            "note": f"{side}-Fib {anchors} (Docht), Zone, kein Signal"}


def place_drawings(drawings: Sequence[Mapping[str, Any]], times: Sequence[int]) -> list[dict[str, Any]]:
    """Snap every drawing onto the shown candle times (the chart's time axis).

    Start = the candle containing the start moment, clamped to the first shown
    candle; end = the newest candle unless the drawing has its own end. A level
    that starts at the newest candle keeps one candle of length so it stays visible.
    """
    if len(times) < 2:
        return []
    placed = []
    for item in drawings:
        start = _epoch(item["start"])
        index = max(0, bisect_right(times, start) - 1)
        end_index = len(times) - 1
        if item.get("end"):
            end_index = max(0, bisect_right(times, _epoch(item["end"])) - 1)
        if index >= end_index:
            if item.get("end"):
                continue  # a finished segment that lies before the shown window
            index = end_index - 1
        color, style = GROUP_STYLE[item["group"]]
        color, style = item.get("color", color), item.get("style", style)
        if item["group"] == "structure":
            color = "#35d39a" if item.get("direction") == "UP" else "#ff5c6c"
            if item["name"].startswith("MSS") or item.get("open"):
                color = "#ffb020" if not item["name"].startswith("BOS") else color
            if item.get("open"):
                style = "dashed"
        clipped = start < times[0]
        finished = (item["group"] == "structure" and not item.get("open")) or bool(item.get("broken"))  # history, not a live level
        result = {**item, "color": color, "style": style, "t1": times[index], "t2": times[end_index], "clipped": clipped, "finished": finished,
                  "bars": end_index - index}
        if item.get("curve"):
            # A running line (VWAP): keep only points on shown candles, one per candle.
            shown = set(times)
            curve = [[t, v] for t, v in item["curve"] if t in shown]
            if len(curve) < 2:
                continue
            result.update({"curve": curve, "t1": curve[0][0], "t2": curve[-1][0], "p1": curve[0][1], "p2": curve[-1][1],
                           "bars": len(curve) - 1})
        elif item["group"] == "trend":
            # Straight in candle steps: recompute the start value at the snapped start index.
            anchor = max(0, bisect_right(times, _epoch(item["anchor_time"])) - 1)
            first = max(0, bisect_right(times, start) - 1)
            if anchor <= first:
                continue
            slope = (item["anchor_price"] - item["start_price"]) / (anchor - first)
            result["p1"] = item["start_price"] + slope * (index - first)
            result["p2"] = item["anchor_price"] + slope * (end_index - anchor)
        else:
            result["p1"] = result["p2"] = item["price"]
        if item["group"] == "structure" and not item.get("open"):
            result["tm"] = times[(index + end_index) // 2]  # label in the middle of the segment, as on TradingView
        placed.append(result)
    return placed


def tpo_profiles(series: Mapping[str, Sequence[Mapping[str, Any]]], now: datetime, days: int = TPO_DAYS) -> list[dict[str, Any]]:
    """Market Profile per UTC day from 30m periods (TPO letters A, B, C ... from 00:00).

    Each day: price rows with the count of periods that traded there and their
    letters, POC (most periods), value area (70 % of the TPOs around the POC),
    single prints (rows with one period, outside the first and last period).
    Rows are a picture of time at price, not volume. The running day is marked.
    """
    base_tf = "30m" if series.get("30m") else "15m"
    candles = [c for c in clean_candles(series.get(base_tf) or [], base_tf) if c["close_time"] <= now]
    by_day: dict[date, list[dict[str, Any]]] = {}
    for candle in candles:
        by_day.setdefault(candle["open_time"].astimezone(timezone.utc).date(), []).append(candle)
    today = now.astimezone(timezone.utc).date()
    result = []
    for day in sorted(by_day)[-(days + 1):]:
        rows = by_day[day]
        periods: dict[int, dict[str, float]] = {}
        for c in rows:
            t = c["open_time"].astimezone(timezone.utc)
            slot = t.hour * 2 + t.minute // 30
            p = periods.setdefault(slot, {"high": c["high"], "low": c["low"]})
            p["high"], p["low"] = max(p["high"], c["high"]), min(p["low"], c["low"])
        if len(periods) < 2:
            continue
        high, low = max(p["high"] for p in periods.values()), min(p["low"] for p in periods.values())
        step = _nice_step(max(high - low, high * 0.0005), TPO_BINS)
        first = math.floor(low / step) * step
        letters: dict[int, str] = {}
        for slot in sorted(periods):
            p = periods[slot]
            for index in range(int((p["low"] - first) // step), int((p["high"] - first) // step) + 1):
                letters[index] = letters.get(index, "") + TPO_LETTERS[slot]
        if not letters:
            continue
        total = sum(len(v) for v in letters.values())
        poc_index = max(sorted(letters), key=lambda i: (len(letters[i]), -abs(i - (max(letters) + min(letters)) / 2)))
        above, below, inside = poc_index + 1, poc_index - 1, len(letters[poc_index])
        while inside < total * 0.7 and (above in letters or below in letters):  # grow the value area to the richer side
            up, down = len(letters.get(above, "")), len(letters.get(below, ""))
            if up >= down and above in letters:
                inside += up
                above += 1
            else:
                inside += down
                below -= 1
        first_slot, last_slot = min(periods), max(periods)
        edge = {TPO_LETTERS[first_slot], TPO_LETTERS[last_slot]}
        profile_rows = [{"price": round(first + i * step, 8), "count": len(letters[i]), "letters": letters[i],
                         "single": len(letters[i]) == 1 and letters[i] not in edge and min(letters) < i < max(letters)}
                        for i in sorted(letters)]
        start = _day_start(day)
        result.append({"day": day.isoformat(), "label": _short_day(day), "start": start.isoformat(), "end": (start + timedelta(days=1)).isoformat(),
                       "running": day == today, "step": step, "periods": len(periods), "rows": profile_rows,
                       "poc": round(first + poc_index * step, 8), "vah": round(first + (above - 1) * step + step, 8),
                       "val": round(first + (below + 1) * step, 8), "high": high, "low": low,
                       "max_count": max(len(v) for v in letters.values())})
    return result


def _level_series(symbol: str, runtime_series: Mapping[str, Sequence[Mapping[str, Any]]] | None,
                  cache: KlineCache, now: datetime) -> tuple[dict[str, list[dict[str, Any]]], str, list[str]]:
    notes: list[str] = []
    if symbol == "BTCUSDT" and runtime_series and runtime_series.get("30m") and runtime_series.get("1h"):
        return dict(runtime_series), "TIM-Runtime (wie Plan-Journale)", notes
    raw: dict[str, list[dict[str, Any]]] = {}
    for tf in LEVEL_TIMEFRAMES:
        rows, error = cache.get(symbol, tf, LEVEL_LIMIT)
        if error:
            notes.append(f"Level {tf}: {error}")
        raw[tf] = [r for r in rows if r.get("closed", True)]
    series = analytical_series(raw, now)
    return {tf: [{**c, "open_time": c["open_time"].isoformat(), "close_time": c["close_time"].isoformat()} for c in rows]
            for tf, rows in series.items() if rows}, "Binance-Klines (nur Anzeige)", notes


def load_plan_journals(paths: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Entries of TIM's paper journals by journal key (missing or locked journals: none)."""
    from src.dashboard.plan_journal import load_view

    result = {}
    for key, path in paths.items():
        if key in PLAN_JOURNALS and path is not None:
            try:
                result[key] = list(load_view(path).get("entries") or [])
            except Exception:  # noqa: BLE001 - a journal must never break the chart
                result[key] = []
    return result


def plan_overlays(journals: Mapping[str, Sequence[Mapping[str, Any]]], times: Sequence[int]) -> list[dict[str, Any]]:
    """TIM's paper plans placed on the shown candles: entry, stop and targets from the plan
    (or fill) until it closed, plus fill and exit times for markers. Corrected entries and
    plans that were never filled are left out; a plan that waits for its entry is drawn dashed."""
    if len(times) < 2:
        return []
    first, last = times[0], times[-1]

    def snap(value: Any) -> int | None:
        if not value:
            return None
        moment = _epoch(value)
        return times[max(0, bisect_right(times, moment) - 1)] if moment >= first else None

    plans = []
    for key, entries in journals.items():
        layer, label = PLAN_JOURNALS.get(key, (None, None))
        if layer is None:
            continue
        for entry in entries:
            if entry.get("excluded") or entry.get("status") not in PLAN_SHOWN or entry.get("entry") is None or entry.get("stop") is None:
                continue
            start = entry.get("filled_at") or entry.get("created_at")
            end_moment = _epoch(entry["closed_at"]) if entry.get("closed_at") else last
            if not start or end_moment < first:
                continue
            t1 = snap(start) or first
            t2 = snap(entry.get("closed_at")) if entry.get("closed_at") else last
            if t2 is None or t2 < t1:
                continue
            if t2 == t1:
                index = times.index(t1)
                t2 = times[min(index + 1, len(times) - 1)]
            # A running trade: where the stop stood since the fill and where it is now (Uzi 27.10.2026).
            steps = []
            if entry.get("status") == "FILLED":
                from src.dashboard.plan_journal import stop_steps
                for at, price, kind in stop_steps(entry):
                    when = snap(at) or first
                    if steps and steps[-1][0] == when:
                        steps[-1] = [when, price, kind]
                    else:
                        steps.append([when, price, kind])
            plans.append({
                "id": entry.get("id"), "journal": key, "group": layer, "label": label, "direction": entry.get("direction"),
                "status": entry.get("status"), "entry": float(entry.get("fill_price") or entry["entry"]), "stop": float(entry["stop"]),
                "targets": [float(t) for t in entry.get("targets") or [] if t is not None], "t1": t1, "t2": t2,
                "fill_t": snap(entry.get("filled_at")), "close_t": snap(entry.get("closed_at")),
                "net_r": entry.get("net_r"), "exit_reason": entry.get("exit_reason"), "clipped": _epoch(start) < first,
                "stop_steps": steps, "stop_now": steps[-1][1] if steps else float(entry["stop"]),
            })
    plans.sort(key=lambda item: item["t1"])
    return plans[-PLAN_LIMIT:]


def build_live_chart(symbol: str | None, timeframe: str | None, runtime_series: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                     cache: KlineCache | None = None, now: datetime | None = None, footprint: Mapping[str, Any] | None = None,
                     plan_journals: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                     gamma: Mapping[str, Any] | None = None, liquidation: Mapping[str, Any] | None = None,
                     perp: Mapping[str, Any] | None = None, open_interest: Mapping[str, Any] | None = None,
                     market: str | None = None) -> dict[str, Any]:
    """Everything the interactive chart draws, as JSON-ready data.

    ``footprint`` is the runtime's aggregated aggTrades store (``DashboardState.footprint``);
    it feeds the volume profiles, footprint bars and volume bubbles (large market orders) for the symbol TIM collects.
    ``plan_journals`` (journal key -> entries, see ``load_plan_journals``) adds TIM's paper
    plans for BTCUSDT, the only symbol the journals follow.
    ``gamma`` is ``DashboardState.gamma`` (snapshot per symbol, gamma_data.py): options
    levels (flip, walls, max pain, expected move) as group "gamma".
    ``liquidation`` is ``DashboardState.liquidation`` (estimate per symbol, liquidation_data.py):
    heat cells under model key ``liquidation`` and the strongest clusters as group "liq".
    ``perp`` is ``DashboardState.perp_flow`` (perp_flow.py, same shape as ``footprint``) and
    ``market`` ("spot" or "perp") picks which trades feed volume profile, footprint and bubbles;
    the levels stay on spot. Both feed the CVD lines (group "cvd"). ``open_interest`` is
    ``DashboardState.open_interest``: hourly open interest with its 7.5-day Z-score (group "oi").
    """
    symbol = symbol if symbol in SYMBOLS else DEFAULT_SYMBOL
    timeframe = timeframe if timeframe in VIEW_TIMEFRAMES else DEFAULT_VIEW
    cache = cache or CACHE
    now = now or datetime.now(timezone.utc)
    model: dict[str, Any] = {"symbol": symbol, "name": SYMBOL_NAMES[symbol], "timeframe": timeframe, "symbols": list(SYMBOLS),
                             "timeframes": list(VIEW_TIMEFRAMES), "generated_at": now.isoformat(), "read_only": True,
                             "provenance": PROVENANCE, "candles": [], "drawings": [], "groups": GROUP_NAMES,
                             "default_groups": list(DEFAULT_GROUPS), "notes": [], "plans": [], "liquidation": None, "fib": None,
                             "markets": {"names": MARKETS, "active": DEFAULT_MARKET, "available": []}, "cvd": None, "oi": None}
    if symbol == "PAXGUSDT":
        model["notes"].append(GOLD_NOTE)
    rows, error = cache.get(symbol, timeframe, VIEW_LIMIT)
    if error:
        model["notes"].append(error)
    candles = clean_candles(rows, timeframe)
    flags = {c["open_time"]: c.get("closed", True) for c in (dict(r, open_time=datetime.fromisoformat(str(r["open_time"]))) for r in rows)}
    if not candles and symbol == "BTCUSDT" and runtime_series and runtime_series.get(timeframe):
        candles = clean_candles(runtime_series[timeframe], timeframe)
        flags = {}
        model["notes"].append("Kerzen aus der TIM-Runtime (Börse nicht erreichbar).")
    for c in candles:
        c["closed"] = flags.get(c["open_time"], c.get("closed", True))
    if len(candles) < 2:
        model["notes"].append("Keine Kerzen für diese Auswahl.")
        return model
    model["candles"] = [{"time": _epoch(c["open_time"]), "open": c["open"], "high": c["high"], "low": c["low"],
                         "close": c["close"], "volume": c["volume"], "closed": bool(c["closed"])} for c in candles]
    model["last"] = candles[-1]["close"]
    model["last_closed"] = next((c["close_time"].isoformat() for c in reversed(candles) if c["closed"]), None)

    level_source, source_name, notes = _level_series(symbol, runtime_series, cache, now)
    model["notes"].extend(notes)
    model["level_source"] = source_name
    trades = footprint if footprint and footprint.get("symbol") == symbol and footprint.get("days") else None
    drawings = level_drawings(level_source, now, trades)
    if INTERVAL_SECONDS[timeframe] >= 86400:
        drawings = [d for d in drawings if d["group"] not in INTRADAY_ONLY]
    drawings += structure_drawings(candles, timeframe) + trend_drawings(candles, timeframe)
    from src.dashboard.htf_levels import build_htf_levels

    drawings += vwap_drawings(build_htf_levels(level_source, now)["vwaps"], candles, timeframe, now)
    if gamma and gamma.get(symbol):
        from src.dashboard.gamma_data import chart_drawings as gamma_drawings

        gamma_items, gamma_notes = gamma_drawings(gamma[symbol], now)
        drawings += gamma_items
        model["notes"].extend(gamma_notes)
    if liquidation and liquidation.get(symbol):
        from src.dashboard.liquidation_data import chart_layer as liquidation_layer

        model["liquidation"], liq_items, liq_notes = liquidation_layer(liquidation[symbol], model["candles"][0]["time"], now)
        drawings += liq_items
        model["notes"].extend(liq_notes)
    times = [c["time"] for c in model["candles"]]
    if open_interest and open_interest.get("symbol") == symbol:
        from src.dashboard.perp_flow import oi_chart

        model["oi"] = oi_chart(open_interest, times[0], now)
        if model["oi"] and model["oi"]["stale"]:
            model["notes"].append("Open Interest: Binance-Stand älter als 3 h, ausgeblendet.")
            model["oi"] = None
    model["drawings"] = place_drawings(drawings, times)
    model["fib"] = fib_retracement(candles, timeframe)
    model["plans"] = plan_overlays(plan_journals, times) if plan_journals and symbol == "BTCUSDT" else []
    model["tpo"], model["volume_profile"], model["footprint"] = [], [], {"step": None, "bars": [], "note": None}
    model["bubbles"] = {"items": [], "min_usd": None, "max_usd": None, "note": None}
    if INTERVAL_SECONDS[timeframe] <= 14400:  # profiles per day only make sense on intraday views
        first_time = times[0]
        model["tpo"] = [p for p in tpo_profiles(level_source, now) if _epoch(p["end"]) > first_time]
        from src.dashboard.footprint_data import footprint_bars, volume_bubbles, volume_profiles

        spot_trades = footprint if footprint and footprint.get("symbol") == symbol and footprint.get("days") else None
        perp_trades = perp if perp and perp.get("symbol") == symbol and perp.get("days") else None
        available = [key for key, store in (("spot", spot_trades), ("perp", perp_trades)) if store]
        active = market if market in available else (available[0] if available else DEFAULT_MARKET)
        model["markets"] = {"names": MARKETS, "active": active, "available": available}
        if market == "perp" and active != "perp":
            model["notes"].append("Perp-Trades noch nicht da (Sammler startet mit dem Vortag): Spot gezeigt.")
        trades_shown = perp_trades if active == "perp" else spot_trades
        if trades_shown:
            model["volume_profile"] = [p for p in volume_profiles(trades_shown, now) if _epoch(p["end"]) > first_time]
            model["footprint"] = footprint_bars(trades_shown, times, INTERVAL_SECONDS[timeframe])
            model["bubbles"] = volume_bubbles(trades_shown, times, INTERVAL_SECONDS[timeframe])
            model["trade_source"] = trades_shown.get("source")
            model["trades_updated_at"] = trades_shown.get("updated_at")
        if spot_trades or perp_trades:
            from src.dashboard.footprint_data import cvd_lines

            model["cvd"] = cvd_lines(spot_trades, perp_trades, times, INTERVAL_SECONDS[timeframe])
        if perp_trades:
            model["perp_health"] = perp_trades.get("health")
        elif footprint and footprint.get("days"):
            model["footprint"]["note"] = f"Volume Profile und Footprint aus echten Trades gibt es nur für {footprint.get('symbol')}: TIM sammelt nur dort Trades."
        else:
            model["footprint"]["note"] = "Noch keine Trades aus der TIM-Datenbank (Runtime liefert sie alle 2 Minuten)."
    if not any(d["group"] in ("day", "week") for d in model["drawings"]):
        model["notes"].append("Keine Tages-/Wochenlevel: zu wenige geschlossene 30m- und 1h-Kerzen.")
    return model
