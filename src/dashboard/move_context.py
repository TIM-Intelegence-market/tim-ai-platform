"""Why did the price move? Large BTC moves with their context and a short explanation (read-only, paper only).

Uzi 15./16.11.2026 (Bauplan "Preisbewegungen erklären", P1+P2): the sell-off of week 46 could not be
placed by TIM. When BTC makes a large move, TIM now collects what its own data says about that move
and writes a few sentences, each with its evidence and an honest level:

- BELEGT: the data shows it directly (e.g. 40 M$ long liquidations inside the move),
- WAHRSCHEINLICH: the data points to it, but another reading is possible (e.g. open interest fell: which side closed is not shown),
- VERMUTUNG: only the timing fits (e.g. a CPI release in the window, nothing more).

A move counts as explained only by liquidations, open interest, taker flow or the Coinbase premium; volume,
funding, a calendar date or gamma add context but never explain a move on their own.

"Aus den vorhandenen Daten nicht erklärbar" is a valid result.

P3 (Uzi 16.11.2026, "Feed und Aktien ja", ``outside_world.py``): hourly Nasdaq-100, S&P 500 and NVIDIA bars give
the stock move in the same window (a bar counts from the end of its hour); headlines from an allowlist of RSS
feeds published from two hours before the move to its end are listed as VERMUTUNG, never as an explanation:
a headline at the same time is not a proven cause.

P1 detection (``detect``), rules version ``MOVE_RULES`` (0.2, calibrated 16.11.2026 on the PS5 with
``research_lab.studies.move_calibration``: training 2020-2023 20.0 moves a year (12 to 32), validation 2024 13 moves,
the 2025 holdout never read; report in ``docs/research_lab/MOVE_CONTEXT_KALIBRIERUNG.md``; 0.1 had 3x / 0.6 % / 3 σ
and fired 388 times a year):

- a closed 1h candle whose absolute return is at least ``H1_RATIO`` times the median absolute 1h return of
  the candles before it (at least ``H1_MIN_PRIOR`` of them, at most ``H1_PRIOR``) and at least ``H1_FLOOR``,
- or a closed 4h candle whose absolute return is at least ``H4_SIGMA`` standard deviations of the 4h
  returns before it (at least ``H4_MIN_PRIOR``),
- flagged candles closer than ``MERGE_GAP`` are one move; its window is the span of its 1h candles, or of its
  4h candles when no 1h candle was flagged.

Every context value is taken only with a time stamp at or before the end of the move (no look-ahead), except the gamma snapshot (see below):

- liquidations (S12 collector, Binance forceOrder + Bybit allLiquidation) from one hour before the move to its end,
- open interest (Binance, hourly) before and after, funding rate in force at the start,
- Coinbase premium before and after (an hour's value counts from the end of that hour),
- taker delta of the perp (TIM's perp record) and of spot (TIM's footprint store) inside the move,
- CPI/FOMC releases from two hours before the move to its end (``data/macro/calendar.json``),
- gamma levels only from a snapshot within one hour of the move's end (Deribit keeps no history); levels move slowly,
  so a snapshot shortly after the end is used, and the finding is only ever a VERMUTUNG,
- volume of the move against the normal hourly volume.

A missing source is "fehlt", never zero. Nothing here is a signal, a filter or advice; it changes no plan,
no score and no risk limit. ``update`` (runtime hook) appends each move once to ``DEFAULT_PATH`` with the
context as it was then; the chart shows those records and, for moves not recorded yet, the live result.
"""

from __future__ import annotations

import json
import os
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.dashboard.helpers import _safe

SCHEMA = "tim_move_event/1"
MOVE_RULES = "move-context/0.2"
DEFAULT_PATH = Path("data/journal/tim_move_events.jsonl")
LOCAL = ZoneInfo("Europe/Berlin")

H1_RATIO = 15.0
H1_FLOOR = 0.015  # 1.5 %: quiet weeks would otherwise flag ordinary candles
H1_PRIOR = 480  # the runtime keeps 500 candles per timeframe, so about 20 days
H1_MIN_PRIOR = 168  # one week
H4_SIGMA = 5.0
H4_PRIOR = 540
H4_MIN_PRIOR = 90
MERGE_GAP = timedelta(hours=4)
LOOKBACK = timedelta(days=7)
MAX_SHOWN = 5
RECORD_AFTER = timedelta(minutes=15)  # let hourly OI / premium points arrive
RECORD_UNTIL = timedelta(hours=6)  # older moves are not recorded later (their gamma would be missing anyway)

FRESH = timedelta(hours=2)  # heartbeat only while the last closed 1h candle is at most this old
LIQ_BEFORE = timedelta(hours=1)
LIQ_STRONG_USD = 10_000_000.0
LIQ_SOME_USD = 2_000_000.0
OI_DROP = -2.0  # % change of open interest over the move
OI_RISE = 1.0
DELTA_SHARE = 0.08  # taker delta as share of the volume
COVERAGE = 0.8  # share of 5-minute buckets with trades before a delta counts
PREMIUM_SHIFT = 0.05  # percentage points
FUNDING_HIGH_8H = 0.03  # % per 8 h; Binance base rate is 0.01
FUNDING_LOW_8H = -0.005
MACRO_BEFORE = timedelta(hours=2)
GAMMA_FRESH = timedelta(hours=1)  # snapshot from the move's last hour up to one hour after it (only a guess either way)
VOLUME_HIGH = 2.0

FEHLT = "fehlt"
OK = "ok"


# --- helpers -----------------------------------------------------------------------------------------------------


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _ts(value: datetime) -> int:
    return int(value.timestamp())


def _ret(c: Mapping[str, Any]) -> float:
    return float(c["close"]) / float(c["open"]) - 1.0


def _closed(series: Mapping[str, Sequence[Mapping[str, Any]]], tf: str, now: datetime) -> list[dict[str, Any]]:
    from src.dashboard.chart_model import analytical_series, clean_candles

    clean = analytical_series(series, now)
    return [c for c in clean_candles(clean.get(tf) or [], tf) if c["close_time"] <= now]


def _last_before(points: Sequence[Sequence[Any]], limit: int, offset: int = 0) -> Sequence[Any] | None:
    """Last point whose time (+ offset seconds) is at or before ``limit`` (points sorted by time)."""
    found = None
    for point in points:
        if int(point[0]) + offset <= limit:
            found = point
        else:
            break
    return found


# --- P1: detection -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Thresholds:
    """The detection thresholds; the defaults are the rules ``MOVE_RULES``. The calibration varies them."""

    h1_ratio: float = H1_RATIO
    h1_floor: float = H1_FLOOR
    h4_sigma: float = H4_SIGMA


def scores(candles: Sequence[Mapping[str, Any]], tf: str) -> list[tuple[int, float, float]]:
    """``(index, return, score)`` per candle with enough history before it: 1h score = |return| / median
    |return| of the candles before it, 4h score = |return| / standard deviation of the returns before it."""
    rets = [_ret(c) for c in candles]
    out = []
    for i, r in enumerate(rets):
        if tf == "1h":
            prior = [abs(x) for x in rets[max(0, i - H1_PRIOR):i]]
            if len(prior) < H1_MIN_PRIOR:
                continue
            base = statistics.median(prior)
        else:
            prior = rets[max(0, i - H4_PRIOR):i]
            if len(prior) < H4_MIN_PRIOR:
                continue
            base = statistics.pstdev(prior)
        if base > 0:
            out.append((i, r, abs(r) / base))
    return out


def flags_from(candles: Sequence[Mapping[str, Any]], tf: str, scored: Sequence[tuple[int, float, float]],
               limits: Thresholds | None = None) -> list[dict[str, Any]]:
    limits = limits or Thresholds()
    flags = []
    for i, r, score in scored:
        hit = (score >= limits.h1_ratio and abs(r) >= limits.h1_floor) if tf == "1h" else score >= limits.h4_sigma
        if hit:
            c = candles[i]
            flags.append({"tf": tf, "start": c["open_time"], "end": c["close_time"], "ret": r, "score": score,
                          "unit": "x Median" if tf == "1h" else "σ"})
    return flags


def merge(flags: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Flags closer than ``MERGE_GAP`` are one move; its window is the span of its 1h flags, else of its 4h flags."""
    merged: list[dict[str, Any]] = []
    for f in sorted(flags, key=lambda f: (f["start"], f["end"])):
        if merged and f["start"] <= merged[-1]["end"] + MERGE_GAP:
            m = merged[-1]
            m["end"] = max(m["end"], f["end"])
            m["triggers"].append(f)
        else:
            merged.append({"start": f["start"], "end": f["end"], "triggers": [f]})
    for m in merged:
        # A 4h candle around a 1h spike would blur the window: the 1h triggers set it when there are any.
        hourly = [f for f in m["triggers"] if f["tf"] == "1h"]
        if hourly:
            m["start"], m["end"] = min(f["start"] for f in hourly), max(f["end"] for f in hourly)
    return merged


def detect(series: Mapping[str, Sequence[Mapping[str, Any]]], now: datetime, lookback: timedelta = LOOKBACK,
           limits: Thresholds | None = None) -> list[dict[str, Any]]:
    """Large moves that ended within ``lookback`` before ``now``, oldest first (pure)."""
    h1 = _closed(series, "1h", now)
    h4 = _closed(series, "4h", now)
    limits = limits or Thresholds()
    merged = merge(flags_from(h1, "1h", scores(h1, "1h"), limits) + flags_from(h4, "4h", scores(h4, "4h"), limits))
    events = []
    by_open = {c["open_time"]: c for c in h1}
    for m in merged:
        if m["end"] < now - lookback:
            continue
        inside = [c for c in h1 if m["start"] <= c["open_time"] and c["close_time"] <= m["end"]]
        if not inside:
            continue
        first, last = by_open.get(m["start"]) or inside[0], inside[-1]
        open_, close = float(first["open"]), float(last["close"])
        change = close / open_ - 1.0
        events.append({
            "id": _iso(m["start"]), "start": m["start"], "end": m["end"], "open": open_, "close": close,
            "high": max(float(c["high"]) for c in inside), "low": min(float(c["low"]) for c in inside),
            "change_pct": round(change * 100, 2), "direction": "UP" if change > 0 else "DOWN",
            "triggers": [{"tf": f["tf"], "end": _iso(f["end"]), "ret_pct": round(f["ret"] * 100, 2), "score": round(f["score"], 1), "unit": f["unit"]}
                         for f in m["triggers"]],
            "_h1": h1,
        })
    return events


# --- P1: context -------------------------------------------------------------------------------------------------


def _volume(event: Mapping[str, Any]) -> dict[str, Any]:
    h1 = event["_h1"]
    inside = [c for c in h1 if event["start"] <= c["open_time"] and c["close_time"] <= event["end"]]
    prior = [float(c["volume"]) for c in h1 if c["close_time"] <= event["start"]][-H1_PRIOR:]
    prior = [v for v in prior if v > 0]
    if not inside or len(prior) < H1_MIN_PRIOR or not any(float(c["volume"]) > 0 for c in inside):
        return {"status": FEHLT}
    normal = statistics.median(prior) * len(inside)
    total = sum(float(c["volume"]) for c in inside)
    return {"status": OK, "btc": round(total, 1), "ratio": round(total / normal, 2) if normal > 0 else None, "source": "Runtime-Kerzen 1h"}


def _liquidations(event: Mapping[str, Any], liquidations: Mapping[str, Sequence[Any]] | None) -> dict[str, Any]:
    if liquidations is None:
        return {"status": FEHLT, "note": "S12-Sammler ohne Daten für diesen Zeitraum"}
    start_ms = int((event["start"] - LIQ_BEFORE).timestamp() * 1000)
    end_ms = int(event["end"].timestamp() * 1000)
    sums = {"long": 0.0, "short": 0.0}
    largest: list[dict[str, Any]] = []
    count = 0
    for venue, items in liquidations.items():
        for e in items:
            if not (start_ms <= e.time_ms < end_ms) or not e.counts:
                continue
            usd = float(e.notional)
            sums[e.side] = sums.get(e.side, 0.0) + usd
            count += 1
            largest.append({"venue": venue, "side": e.side, "usd": round(usd), "time": _iso(datetime.fromtimestamp(e.time_ms / 1000, timezone.utc))})
    largest.sort(key=lambda x: -x["usd"])
    return {"status": OK, "long_usd": round(sums["long"]), "short_usd": round(sums["short"]), "count": count, "largest": largest[:3],
            "source": "Binance forceOrder + Bybit allLiquidation (S12)", "note": "Binance meldet höchstens eine Liquidation je Sekunde: eher zu niedrig"}


def _open_interest(event: Mapping[str, Any], oi: Mapping[str, Any] | None) -> dict[str, Any]:
    points = sorted((oi or {}).get("points") or [], key=lambda p: p[0])
    start, end = _ts(event["start"]), _ts(event["end"])
    before, after = _last_before(points, start), _last_before(points, end)
    if not before or not after or start - int(before[0]) > 7200 or end - int(after[0]) > 7200 or before is after:
        return {"status": FEHLT}
    change = (float(after[1]) / float(before[1]) - 1.0) * 100 if float(before[1]) > 0 else None
    if change is None:
        return {"status": FEHLT}
    return {"status": OK, "before_usd": float(before[2]), "after_usd": float(after[2]), "change_pct": round(change, 2), "source": (oi or {}).get("source")}


def _funding(event: Mapping[str, Any], funding: Mapping[str, Any] | None) -> dict[str, Any]:
    points = sorted((funding or {}).get("points") or [], key=lambda p: p[0])
    last = _last_before(points, _ts(event["start"]))
    if not last:
        return {"status": FEHLT}
    hours = float((funding or {}).get("interval_hours") or 8.0) or 8.0
    return {"status": OK, "rate_8h": round(float(last[1]) * 8.0 / hours, 5), "settled": _iso(datetime.fromtimestamp(int(last[0]), timezone.utc)),
            "source": (funding or {}).get("source")}


def _premium(event: Mapping[str, Any], premium: Mapping[str, Any] | None) -> dict[str, Any]:
    points = sorted((premium or {}).get("points") or [], key=lambda p: p[0])
    start, end = _ts(event["start"]), _ts(event["end"])
    before, after = _last_before(points, start, 3600), _last_before(points, end, 3600)
    if not before or not after or before is after or start - int(before[0]) > 3 * 3600 or end - int(after[0]) > 3 * 3600:
        return {"status": FEHLT}
    return {"status": OK, "before_pct": float(before[1]), "after_pct": float(after[1]), "shift_pp": round(float(after[1]) - float(before[1]), 4),
            "source": (premium or {}).get("source")}


def _delta(event: Mapping[str, Any], store: Mapping[str, Any] | None, label: str) -> dict[str, Any]:
    if not store or not store.get("days"):
        return {"status": FEHLT}
    bucket = int(store.get("bucket_seconds") or 300)
    start, end = _ts(event["start"]), _ts(event["end"])
    bid = ask = 0.0
    seen: set[int] = set()
    first, last = event["start"].astimezone(timezone.utc).date(), event["end"].astimezone(timezone.utc).date()
    days = {(first + timedelta(days=n)).isoformat() for n in range((last - first).days + 1)}
    for key, rows in (store.get("days") or {}).items():
        if key not in days:  # only the UTC days of the move: a 14-day store has about a million rows
            continue
        for b, _level, sell, buy in rows:
            b = int(b)
            if start <= b and b + bucket <= end:
                bid += float(sell)
                ask += float(buy)
                seen.add(b)
    expected = max(1, (end - start) // bucket)
    volume = bid + ask
    if len(seen) < COVERAGE * expected or volume <= 0:
        return {"status": FEHLT, "note": f"{label}: Aufzeichnung lückenhaft ({len(seen)}/{expected} 5-Min-Abschnitte)"}
    return {"status": OK, "delta_btc": round(ask - bid, 1), "volume_btc": round(volume, 1), "share": round((ask - bid) / volume, 3),
            "source": store.get("source")}


def _macro(event: Mapping[str, Any], calendar: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    if calendar is None:
        return {"status": FEHLT}
    hits = [{"kind": e["kind"], "label": e.get("label") or e["kind"], "time": _iso(e["time"]),
             "minutes_before_start": int((event["start"] - e["time"]).total_seconds() // 60)}
            for e in calendar if event["start"] - MACRO_BEFORE <= e["time"] <= event["end"]]
    return {"status": OK, "events": hits, "source": "data/macro/calendar.json (CPI/FOMC)"}


def _gamma(event: Mapping[str, Any], gamma: Mapping[str, Any] | None) -> dict[str, Any]:
    inp = (gamma or {}).get("analysis_input") or {}
    try:
        as_of = datetime.fromisoformat(str(inp.get("as_of") or (gamma or {}).get("as_of")))
    except ValueError:
        return {"status": FEHLT, "note": "kein Gamma-Stand innerhalb 1 h um das Ende der Bewegung (Deribit hat keine Historie)"}
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    if not (event["end"] - GAMMA_FRESH <= as_of <= event["end"] + GAMMA_FRESH):
        return {"status": FEHLT, "note": "kein Gamma-Stand innerhalb 1 h um das Ende der Bewegung (Deribit hat keine Historie)"}
    flip = inp.get("gamma_flip")
    return {"status": OK, "as_of": _iso(as_of), "flip": flip, "call_wall": inp.get("call_wall"), "put_wall": inp.get("put_wall"),
            "net_gex": inp.get("net_gex"), "below_flip": None if flip is None else float(event["close"]) < float(flip), "source": inp.get("source")}


NEWS_BEFORE = timedelta(hours=2)
NEWS_SHOWN = 3
NEWS_WORDS = ("bitcoin", "btc", "crypto", "krypto", "ether", "fed", "powell", "fomc", "cpi", "inflation", "rate", "tariff",
              "nvidia", "nvda", "nasdaq", "stocks", "equities", "sell-off", "selloff", "liquidat", "etf", "sec", "hack", "war")
STOCK_SAME = 0.8  # % move of the Nasdaq-100 / S&P 500 in the same direction
STOCK_CALM = 0.3  # % : stocks hardly moved
SINGLE_SAME = 2.5  # % move of NVIDIA in the same direction
STOCK_MIN_BARS = 1  # an index needs at least this many hour bars that ended in the window


US_EAST = ZoneInfo("America/New_York")
US_OPEN, US_CLOSE = (9, 30), (16, 0)


def us_session_overlap(start: datetime, end: datetime) -> bool:
    """True when ``start..end`` touches a regular US session (Mon-Fri 9:30-16:00 New York); holidays are not known."""
    day = start.astimezone(US_EAST).date() - timedelta(days=1)
    last = end.astimezone(US_EAST).date()
    while day <= last:
        if day.weekday() < 5:
            open_ = datetime(day.year, day.month, day.day, *US_OPEN, tzinfo=US_EAST)
            close = datetime(day.year, day.month, day.day, *US_CLOSE, tzinfo=US_EAST)
            if start < close and end > open_:
                return True
        day += timedelta(days=1)
    return False


def _stocks(event: Mapping[str, Any], stocks: Mapping[str, Any] | None) -> dict[str, Any]:
    from src.dashboard.outside_world import stock_move

    series = (stocks or {}).get("series") or {}
    if not series:
        return {"status": FEHLT}
    moves = {}
    for symbol, item in series.items():
        move = stock_move(item.get("bars") or [], event["start"], event["end"])
        if move is not None:
            moves[symbol] = {"name": item.get("name") or symbol, **move}
    if not moves:
        # "closed" only when the series runs past the move (so the gap is the market's, not a stale feed)
        last_end = max((int(b[0]) + 3600 for item in series.values() for b in item.get("bars") or []), default=0)
        if last_end >= int(event["end"].timestamp()) or not us_session_overlap(event["start"], event["end"]):
            return {"status": "geschlossen", "note": "US-Börse im Zeitfenster geschlossen"}
        return {"status": FEHLT, "note": "Aktienkurse reichen nicht bis zum Ende der Bewegung"}
    return {"status": OK, "moves": moves, "source": (stocks or {}).get("source")}


def _news(event: Mapping[str, Any], headlines: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    from src.dashboard.outside_world import headlines_between

    if not headlines:
        return {"status": FEHLT}
    start = event["start"] - NEWS_BEFORE
    if min(datetime.fromisoformat(h["time"]) for h in headlines) > start:  # times are UTC-aware (outside_world.read_log)
        return {"status": FEHLT, "note": "Schlagzeilen-Log beginnt erst nach diesem Zeitfenster"}
    found = headlines_between(headlines, start, event["end"])
    found.sort(key=lambda h: (not _relevant(h["title"]), h["time"]))
    return {"status": OK, "count": len(found), "items": found[:NEWS_SHOWN], "source": "RSS-Allowlist (outside_world.FEEDS)"}


def _relevant(title: str) -> bool:
    """A listed word at the start of a word ("liquidat" matches "liquidations", "sec" does not match "second")."""
    import re

    words = re.findall(r"[a-z0-9-]+", title.lower())
    return any(w == k or (len(k) >= 6 and w.startswith(k)) for w in words for k in NEWS_WORDS)


def _when_short(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(LOCAL).strftime("%d.%m. %H:%M")


def _stock_findings(stocks: Mapping[str, Any], event: Mapping[str, Any], down: bool) -> list[dict[str, str]]:
    sign = -1 if down else 1
    moves = stocks["moves"]

    def ev(symbols: Sequence[str], de: bool) -> str:
        parts = [f"{moves[s]['name']} {_n(moves[s]['change_pct'], '+.2f', de)}{' %' if de else '%'}" for s in symbols if s in moves]
        return ", ".join(parts) + (" (Yahoo, 1h-Kerzen ab :30 ET, die im Fenster endeten)" if de else " (Yahoo, 1h bars from :30 ET that ended in the window)")
    out = []
    index = [s for s in ("^NDX", "^GSPC") if s in moves and moves[s]["bars"] >= STOCK_MIN_BARS]
    if index:
        same = [s for s in index if moves[s]["change_pct"] * sign >= STOCK_SAME]
        if same:
            out.append(_finding("stocks", "WAHRSCHEINLICH",
                                "Aktien " + ("fielen" if down else "stiegen") + " gleichzeitig: breites Risiko-" + ("Aus" if down else "An") + ", nicht nur Krypto.",
                                "Stocks " + ("fell" if down else "rose") + " at the same time: broad risk-" + ("off" if down else "on") + ", not only crypto.",
                                ev(index, True), ev(index, False)))
        elif all(abs(moves[s]["change_pct"]) <= STOCK_CALM for s in index):
            out.append(_finding("stocks_calm", "WAHRSCHEINLICH", "Aktien blieben ruhig: die Bewegung kam aus dem Kryptomarkt selbst.",
                                "Stocks stayed calm: the move came from the crypto market itself.", ev(index, True), ev(index, False)))
    if "NVDA" in moves and moves["NVDA"]["change_pct"] * sign >= SINGLE_SAME and moves["NVDA"]["bars"] >= STOCK_MIN_BARS:
        out.append(_finding("nvda", "VERMUTUNG", "NVIDIA " + ("fiel" if down else "stieg") + " gleichzeitig deutlich: Tech-Stimmung könnte mitgezogen haben.",
                            "NVIDIA " + ("fell" if down else "rose") + " sharply at the same time: tech sentiment may have pulled along.",
                            ev(["NVDA"], True), ev(["NVDA"], False)))
    return out


def context(event: Mapping[str, Any], sources: Mapping[str, Any]) -> dict[str, Any]:
    """Every context value for one move; ``sources`` keys may be missing (then "fehlt")."""
    return {
        "volume": _volume(event),
        "liquidations": _liquidations(event, sources.get("liquidations_for")(event) if callable(sources.get("liquidations_for")) else sources.get("liquidations")),
        "open_interest": _open_interest(event, sources.get("open_interest")),
        "funding": _funding(event, sources.get("funding")),
        "premium": _premium(event, sources.get("premium")),
        "perp_delta": _delta(event, sources.get("perp"), "Perp"),
        "spot_delta": _delta(event, sources.get("spot"), "Spot"),
        "macro": _macro(event, sources.get("calendar")),
        "gamma": _gamma(event, sources.get("gamma")),
        "stocks": _stocks(event, sources.get("stocks")),
        "news": _news(event, sources.get("headlines")),
    }


# --- P2: explanation ---------------------------------------------------------------------------------------------


def _n(value: float, fmt: str, de: bool) -> str:
    """A number in German (decimal comma) or English notation; only the number, never the text around it."""
    text = format(value, fmt)
    return text.replace(".", ",") if de else text


def _mio(usd: float, de: bool = True) -> str:
    return _n(usd / 1e6, ".1f", de)


def _finding(key: str, level: str, de: str, en: str, evidence: str, evidence_en: str) -> dict[str, str]:
    return {"key": key, "level": level, "de": de, "en": en, "evidence": evidence, "evidence_en": evidence_en}


CAUSES = ("liq", "oi", "flow", "premium", "stocks")  # findings that can explain a move; the rest only adds context


def explain(event: Mapping[str, Any], ctx: Mapping[str, Any]) -> list[dict[str, str]]:
    """Fixed rules from the context fields; every finding names its evidence and level (pure)."""
    down = event["direction"] == "DOWN"
    out: list[dict[str, str]] = []

    liq = ctx.get("liquidations") or {}
    if liq.get("status") == OK:
        same = liq["long_usd"] if down else liq["short_usd"]
        side_de, side_en = ("Long", "long") if down else ("Short", "short")
        ev = (f"{side_de}-Liquidationen {_mio(same)} Mio. $ von 1 h vor Beginn bis Ende ({liq['count']} Meldungen, {liq.get('source')})")
        ev_en = (f"{side_en} liquidations {_mio(same, False)} M$ from 1 h before the start to the end ({liq['count']} reports, {liq.get('source')})")
        if same >= LIQ_STRONG_USD:
            out.append(_finding("liq", "BELEGT", f"Zwangsschließungen: {_mio(same)} Mio. $ {side_de}-Liquidationen fielen in die Bewegung.",
                                f"Forced closing: {_mio(same, False)} M$ of {side_en} liquidations hit during the move.", ev, ev_en))
        elif same >= LIQ_SOME_USD:
            out.append(_finding("liq", "WAHRSCHEINLICH", f"Liquidationen ({_mio(same)} Mio. $ {side_de}) haben die Bewegung verstärkt, aber nicht allein getragen.",
                                f"Liquidations ({_mio(same, False)} M$ {side_en}) amplified the move but did not carry it alone.", ev, ev_en))

    oi = ctx.get("open_interest") or {}
    if oi.get("status") == OK:
        ch = oi["change_pct"]
        ev = f"Open Interest {_n(ch, '+.2f', True)} % über die Bewegung ({oi.get('source')})"
        ev_en = f"open interest {_n(ch, '+.2f', False)}% over the move ({oi.get('source')})"
        if ch <= OI_DROP:
            de = "Positionen wurden netto geschlossen (Open Interest fiel): eher Ausstieg von Longs als neuer Short-Druck." if down else \
                 "Positionen wurden netto geschlossen (Open Interest fiel): eher Eindecken von Shorts als neue Käufer."
            en = "Positions were closed on balance (open interest fell): more longs exiting than new shorts." if down else \
                 "Positions were closed on balance (open interest fell): more shorts covering than new buyers."
            out.append(_finding("oi", "WAHRSCHEINLICH", de, en, ev, ev_en))
        elif ch >= OI_RISE:
            de = "Neue Positionen wurden eröffnet (Open Interest stieg): eher aktiver Verkauf auf Hebel." if down else \
                 "Neue Positionen wurden eröffnet (Open Interest stieg): eher neue Long-Positionen, aktiver Kauf auf Hebel."
            en = "New positions were opened (open interest rose): more likely active selling with leverage." if down else \
                 "New positions were opened (open interest rose): more likely new longs, active buying with leverage."
            out.append(_finding("oi", "WAHRSCHEINLICH", de, en, ev, ev_en))

    perp, spot = ctx.get("perp_delta") or {}, ctx.get("spot_delta") or {}
    sign = -1 if down else 1
    perp_ok, spot_ok = perp.get("status") == OK, spot.get("status") == OK
    perp_push = perp_ok and perp["share"] * sign >= DELTA_SHARE
    spot_push = spot_ok and spot["share"] * sign >= DELTA_SHARE

    def dev(d: Mapping[str, Any], name: str, de: bool) -> str:
        share = _n(d["share"] * 100, "+.0f", de)
        return (f"{name}-Delta {_n(d['delta_btc'], '+.0f', de)} BTC = {share} % des Volumens" if de
                else f"{name} delta {_n(d['delta_btc'], '+.0f', de)} BTC = {share}% of volume")
    if spot_push and perp_push:
        out.append(_finding("flow", "BELEGT",
                            "Breiter " + ("Verkauf" if down else "Kauf") + ": aggressive " + ("Verkäufer" if down else "Käufer") + " dominierten auf Spot und Perp.",
                            "Broad " + ("selling" if down else "buying") + ": aggressive " + ("sellers" if down else "buyers") + " dominated spot and perp.",
                            dev(spot, "Spot", True) + "; " + dev(perp, "Perp", True), dev(spot, "spot", False) + "; " + dev(perp, "perp", False)))
    elif spot_push:
        out.append(_finding("flow", "BELEGT", ("Spot-Verkauf" if down else "Spot-Kauf") + ": echte Abgabe bzw. Nachfrage auf Spot, nicht nur Hebel.",
                            ("Spot selling" if down else "Spot buying") + ": real supply or demand on spot, not only leverage.",
                            dev(spot, "Spot", True), dev(spot, "spot", False)))
    elif perp_push and spot_ok:
        out.append(_finding("flow", "BELEGT", "Hebel-getrieben: der Druck kam vom Perp, Spot ging kaum mit.",
                            "Leverage-driven: the pressure came from the perp, spot hardly followed.",
                            dev(perp, "Perp", True) + "; " + dev(spot, "Spot", True), dev(perp, "perp", False) + "; " + dev(spot, "spot", False)))
    elif perp_push:
        out.append(_finding("flow", "WAHRSCHEINLICH", "Druck auf dem Perp: aggressive " + ("Verkäufer" if down else "Käufer") + " dominierten, Spot unbekannt.",
                            "Pressure on the perp: aggressive " + ("sellers" if down else "buyers") + " dominated, spot unknown.",
                            dev(perp, "Perp", True), dev(perp, "perp", False)))

    prem = ctx.get("premium") or {}
    if prem.get("status") == OK and prem["shift_pp"] * sign >= PREMIUM_SHIFT:
        ev = f"Coinbase-Premium {_n(prem['before_pct'], '+.3f', True)} → {_n(prem['after_pct'], '+.3f', True)} %"
        ev_en = f"Coinbase premium {_n(prem['before_pct'], '+.3f', False)} → {_n(prem['after_pct'], '+.3f', False)}%"
        out.append(_finding("premium", "WAHRSCHEINLICH",
                            "US-Anleger " + ("verkauften" if down else "kauften") + " stärker als der Rest (Coinbase-Premium " + ("fiel" if down else "stieg") + ").",
                            "US investors " + ("sold" if down else "bought") + " harder than the rest (Coinbase premium " + ("fell" if down else "rose") + ").", ev, ev_en))

    fund = ctx.get("funding") or {}
    if fund.get("status") == OK:
        rate = fund["rate_8h"]
        ev = f"Funding vor der Bewegung {_n(rate, '+.4f', True)} % je 8 h"
        ev_en = f"funding before the move {_n(rate, '+.4f', False)}% per 8 h"
        if down and rate >= FUNDING_HIGH_8H:
            out.append(_finding("funding", "WAHRSCHEINLICH", "Vorher waren viele Longs teuer gehebelt (hohes Funding): anfällig für einen Abverkauf.",
                                "Many longs were expensively leveraged beforehand (high funding): prone to a flush.", ev, ev_en))
        elif not down and rate <= FUNDING_LOW_8H:
            out.append(_finding("funding", "WAHRSCHEINLICH", "Vorher waren viele Shorts im Markt (negatives Funding): anfällig für einen Squeeze.",
                                "Many shorts were in the market beforehand (negative funding): prone to a squeeze.", ev, ev_en))

    macro = ctx.get("macro") or {}
    for m in (macro.get("events") or [])[:2]:
        out.append(_finding("macro", "VERMUTUNG",
                            f"{m['label']} lag im Zeitfenster: Zeitpunkt belegt, Wirkung nur aus der Gleichzeitigkeit geschlossen.",
                            f"{m['label']} fell into the window: the timing is a fact, its effect is inferred from timing only.",
                            f"{m['label']} {m['time']} (Kalender)", f"{m['label']} {m['time']} (calendar)"))

    stocks = ctx.get("stocks") or {}
    if stocks.get("status") == OK:
        out.extend(_stock_findings(stocks, event, down))

    news = ctx.get("news") or {}
    if news.get("status") == OK and news.get("items"):
        titles = "; ".join(f"{_when_short(i['time'])} {i['feed']}: {i['title']}" for i in news["items"])
        out.append(_finding("news", "VERMUTUNG", f"{len(news['items'])} Schlagzeile(n) im Zeitfenster, Zusammenhang nicht belegt.",
                            f"{len(news['items'])} headline(s) in the window, connection not shown.", titles, titles))

    gamma = ctx.get("gamma") or {}
    if gamma.get("status") == OK and gamma.get("below_flip"):
        out.append(_finding("gamma", "VERMUTUNG", "Der Kurs lag unter dem Gamma-Flip: Options-Händler verstärken dort eher Bewegungen.",
                            "Price was below the gamma flip, where option dealers tend to amplify moves.",
                            f"Flip {gamma['flip']} (Deribit-Stand {gamma['as_of']})", f"flip {gamma['flip']} (Deribit snapshot {gamma['as_of']})"))

    vol = ctx.get("volume") or {}
    if vol.get("status") == OK and vol.get("ratio") and vol["ratio"] >= VOLUME_HIGH:
        out.append(_finding("volume", "BELEGT", f"Volumen {_n(vol['ratio'], '.1f', True)}-fach normal: viele Marktteilnehmer haben mitgehandelt.",
                            f"Volume {_n(vol['ratio'], '.1f', False)}x normal: many participants traded the move.",
                            f"{_n(vol['btc'], '.1f', True)} BTC in der Bewegung", f"{vol['btc']} BTC during the move"))
    return out


def explained(findings: Sequence[Mapping[str, str]]) -> bool:
    """True when a cause (liquidations, open interest, taker flow, premium) is BELEGT or WAHRSCHEINLICH."""
    return any(f["level"] in ("BELEGT", "WAHRSCHEINLICH") and f["key"] in CAUSES for f in findings)


def _public(event: Mapping[str, Any]) -> dict[str, Any]:
    return {k: (_iso(v) if isinstance(v, datetime) else v) for k, v in event.items() if not k.startswith("_")}


def build(series: Mapping[str, Sequence[Mapping[str, Any]]], sources: Mapping[str, Any], now: datetime | None = None,
          lookback: timedelta = LOOKBACK) -> list[dict[str, Any]]:
    """Moves of the last ``lookback`` with context and findings, newest first (pure apart from ``sources``)."""
    now = now or datetime.now(timezone.utc)
    rows = []
    for event in detect(series, now, lookback):
        ctx = context(event, sources)
        findings = explain(event, ctx)
        rows.append({"schema": SCHEMA, "rules": MOVE_RULES, **_public(event), "context": ctx, "findings": findings,
                     "explained": explained(findings), "computed_at": _iso(now)})
    return list(reversed(rows))


# --- record (runtime hook) ---------------------------------------------------------------------------------------


def load(path: Path = DEFAULT_PATH) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()  # a cut multi-byte tail never blocks
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not (isinstance(row, dict) and row.get("schema") == SCHEMA and isinstance(row.get("id"), str)):
            continue
        try:  # a line without its times or change is skipped, one broken line never hides the section
            datetime.fromisoformat(row["start"]), datetime.fromisoformat(row["end"]), float(row["change_pct"])
        except (KeyError, TypeError, ValueError):
            continue
        if row.get("direction") in ("UP", "DOWN"):
            rows.append(row)
    return rows


def latest(path: Path = DEFAULT_PATH) -> dict[str, dict[str, Any]]:
    """The newest record per move id: a move that grew after its first record is recorded again, the later line wins."""
    return {row["id"]: row for row in load(path)}


def update(path: Path, series: Mapping[str, Sequence[Mapping[str, Any]]], sources: Mapping[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    """Append each move ``RECORD_AFTER`` to ``RECORD_UNTIL`` after its end, with the context as it is now.

    A move is recorded once per end: when a later candle joins it (same id, later end), it is recorded again
    and ``latest`` shows the newer line. Old lines stay (append-only).
    """
    now = now or datetime.now(timezone.utc)
    known = {key: row["end"] for key, row in latest(path).items()}
    new = []
    for row in reversed(build(series, sources, now, lookback=RECORD_UNTIL)):
        end = datetime.fromisoformat(row["end"])
        if (row["id"] in known and datetime.fromisoformat(known[row["id"]]) >= end) or not (end + RECORD_AFTER <= now <= end + RECORD_UNTIL):
            continue
        new.append({**row, "recorded_at": _iso(now)})
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in new:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    hours = _closed(series, "1h", now)
    if len(hours) > H1_MIN_PRIOR and now - hours[-1]["close_time"] <= FRESH:
        beat(path, now)  # only a recorder that sees fresh candles counts as watching (a dead feed finds no move)
    return new


def heartbeat_path(path: Path) -> Path:
    return path.with_name(path.stem + ".heartbeat.jsonl")


def beat(path: Path, now: datetime) -> None:
    """One line per hour in which the recorder ran (move_label labels trades only across hours without a long gap)."""
    hour = _iso(now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0))
    beats = heartbeat_path(path)
    try:
        last = beats.read_text(encoding="utf-8", errors="replace").rstrip("\n").rsplit("\n", 1)[-1]
    except OSError:
        last = ""
    if not beats.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()  # first watch: the record exists from now on, so a lost record is told apart from "no move"
    elif not path.exists():
        return  # record lost while the heartbeat stays: no more beats, move_label gives no label
    if last.strip('"') != hour:
        with beats.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(hour) + "\n")


def beats(path: Path) -> list[datetime]:
    """Hours in which the recorder ran, sorted; unreadable lines are skipped."""
    try:
        lines = heartbeat_path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            moment = datetime.fromisoformat(json.loads(line))
        except (TypeError, ValueError):
            continue
        if moment.tzinfo is not None:  # beat() writes UTC with offset; anything else is not ours
            out.append(moment)
    return sorted(out)


def shown(series: Mapping[str, Sequence[Mapping[str, Any]]], sources: Mapping[str, Any], path: Path = DEFAULT_PATH,
          now: datetime | None = None) -> list[dict[str, Any]]:
    """What the chart shows: recorded moves as recorded, others live (marked ``live``), newest first."""
    now = now or datetime.now(timezone.utc)
    recorded = {key: row for key, row in latest(path).items() if datetime.fromisoformat(row["end"]) >= now - LOOKBACK}
    rows = []
    for row in build(series, sources, now):
        kept = recorded.pop(row["id"], None)
        # the live move ran on after its record (later end): show it live until it is recorded again
        if kept is not None and datetime.fromisoformat(kept["end"]) >= datetime.fromisoformat(row["end"]):
            rows.append(kept)
        else:
            rows.append({**row, "live": True})
    rows.extend(recorded.values())
    rows.sort(key=lambda r: r["start"], reverse=True)
    return rows[:MAX_SHOWN]


# --- sources from the dashboard state ----------------------------------------------------------------------------


def sources_from_state(state: Any) -> dict[str, Any]:
    """Collect the inputs from the dashboard state; anything unavailable is left out (then "fehlt")."""
    from src.dashboard import liquidation_events, macro_calendar, perp_flow

    sources: dict[str, Any] = {}
    with state.lock:
        store, oi = perp_flow.chart_inputs(state, "BTCUSDT")
        spot = getattr(state, "footprint", None)
        gamma = (getattr(state, "gamma", None) or {}).get("BTCUSDT")
    sources.update(perp=store or None, open_interest=oi or None, gamma=gamma,
                   spot=spot if spot and spot.get("symbol") in (None, "BTCUSDT") else None)
    if os.environ.get("TIM_RUNTIME_ENV") != "test":
        from src.dashboard.market_context import CACHE

        snap = CACHE.snapshot("BTCUSDT")
        sources.update(funding=snap.get("funding"), premium=snap.get("premium"))
    path = macro_calendar.calendar_path()
    sources["calendar"] = macro_calendar.load_calendar(path) if path.exists() else None
    root = liquidation_events.default_root()

    def liquidations_for(event: Mapping[str, Any]) -> dict[str, list[Any]] | None:
        from src.research_lab.liquidations.store import raw_path

        start, end = event["start"] - LIQ_BEFORE, event["end"]
        days = liquidation_events._days(start, end)
        if not any(raw_path(root, venue, day).exists() for venue in liquidation_events.VENUES for day in days):
            return None
        return liquidation_events.window_events(root, start, end)

    sources["liquidations_for"] = liquidations_for
    from src.dashboard import outside_world

    sources.update(outside_world.sources())
    return sources


# --- text --------------------------------------------------------------------------------------------------------

LEVEL_CLASS = {"BELEGT": "sev--ok", "WAHRSCHEINLICH": "sev--info", "VERMUTUNG": "sev--warn"}
LEVEL_EN = {"BELEGT": "SHOWN", "WAHRSCHEINLICH": "LIKELY", "VERMUTUNG": "GUESS"}
MISSING_DE = {"liquidations": "Liquidationen", "open_interest": "Open Interest", "funding": "Funding", "premium": "Coinbase-Premium",
              "perp_delta": "Perp-Delta", "spot_delta": "Spot-Delta", "macro": "Makro-Kalender", "gamma": "Gamma",
              "stocks": "Aktien", "news": "Schlagzeilen", "volume": "Volumen"}
CLOSED_DE = {"stocks": "US-Börse geschlossen"}
CLOSED_EN = {"stocks": "US market closed"}
MISSING_EN = {"liquidations": "liquidations", "open_interest": "open interest", "funding": "funding", "premium": "Coinbase premium",
              "perp_delta": "perp delta", "spot_delta": "spot delta", "macro": "macro calendar", "gamma": "gamma",
              "stocks": "stocks", "news": "headlines", "volume": "volume"}


def _when(value: str, de: bool) -> str:
    moment = datetime.fromisoformat(value).astimezone(LOCAL)
    return moment.strftime("%d.%m. %H:%M") if de else moment.strftime("%d %b %H:%M")


def _event_html(row: Mapping[str, Any], de: bool) -> str:
    change = f"{row['change_pct']:+.2f} %".replace(".", ",") if de else f"{row['change_pct']:+.2f}%"
    word = ("fiel" if row["direction"] == "DOWN" else "stieg") if de else ("fell" if row["direction"] == "DOWN" else "rose")
    head = (f"{_when(row['start'], de)} bis {_when(row['end'], de)}: BTC {word} {change}" if de
            else f"{_when(row['start'], de)} to {_when(row['end'], de)} (Berlin time): BTC {word} {change}")
    if row.get("live"):
        head += " (vorläufig, noch nicht aufgezeichnet)" if de else " (preliminary, not recorded yet)"
    items = []
    for f in row.get("findings") or []:
        level = f["level"] if de else LEVEL_EN.get(f["level"], f["level"])
        items.append(f"<li><span class='sev {LEVEL_CLASS.get(f['level'], '')}'>{_safe(level)}</span> {_safe(f['de'] if de else f['en'])} "
                     f"<span class='cc-note'>Beleg: {_safe(f['evidence'])}</span></li>" if de else
                     f"<li><span class='sev {LEVEL_CLASS.get(f['level'], '')}'>{_safe(level)}</span> {_safe(f['en'])} "
                     f"<span class='cc-note'>Evidence: {_safe(f.get('evidence_en') or f['evidence'])}</span></li>")
    if not row.get("explained"):
        items.append("<li>" + ("Aus den vorhandenen Daten nicht erklärbar. Ursache liegt vermutlich außerhalb dessen, was TIM misst (z. B. Nachrichten)."
                               if de else "Not explained by the data TIM has. The cause probably lies outside what TIM measures (e.g. news).") + "</li>")
    missing = [(MISSING_DE if de else MISSING_EN)[k] for k, v in (row.get("context") or {}).items() if (v or {}).get("status") == FEHLT]
    closed = [(CLOSED_DE if de else CLOSED_EN)[k] for k, v in (row.get("context") or {}).items()
              if (v or {}).get("status") == "geschlossen" and k in CLOSED_DE]
    gap = ""
    if missing:
        gap = ("<p class='cc-note'>Fehlt: " if de else "<p class='cc-note'>Missing: ") + _safe(", ".join(missing)) + "</p>"
    if closed:
        gap += "<p class='cc-note'>" + _safe(", ".join(closed)) + "</p>"
    return f"<li class='tc-moves__item'><p><b>{_safe(head)}</b></p><ul>{''.join(items)}</ul>{gap}</li>"


def render(rows: Sequence[Mapping[str, Any]], de: bool = True) -> str:
    eyebrow = "Warum hat sich der Preis bewegt?" if de else "Why did the price move?"
    if not rows:
        body = ("<p class='empty'>Keine große Bewegung in den letzten 7 Tagen.</p>" if de
                else "<p class='empty'>No large move in the last 7 days.</p>")
    else:
        body = "<ul class='tc-moves'>" + "".join(_event_html(r, de) for r in rows) + "</ul>"
    note = ("Große Bewegung = 1h-Kerze mindestens 15-mal so groß wie üblich und mindestens 1,5 % oder 4h-Kerze über 5 σ "
            "(Regeln move-context/0.2, kalibriert auf 2020–2023: etwa 20 Bewegungen im Jahr). "
            "BELEGT = Daten zeigen es, WAHRSCHEINLICH = mehrere Hinweise, VERMUTUNG = nur der Zeitpunkt passt. Nur Beobachtung, keine Order, keine Empfehlung."
            if de else
            "Large move = 1h candle at least 15x its usual size and at least 1.5%, or 4h candle beyond 5σ "
            "(rules move-context/0.2, calibrated on 2020-2023: about 20 moves a year). "
            "SHOWN = the data shows it, LIKELY = several hints agree, GUESS = only the timing fits. Observation only: no orders, not advice.")
    return f"<section class='cc-section tc-moves' data-moves='{SCHEMA}'><p class='cc-section__eyebrow'>{eyebrow}</p>{body}<p class='cc-note'>{note}</p></section>"


def render_de(rows: Sequence[Mapping[str, Any]]) -> str:
    return render(rows, True)


def render_en(rows: Sequence[Mapping[str, Any]]) -> str:
    return render(rows, False)
