"""Rules of study S13 (docs/research_lab/studien/S13_NOISE_BAND_INTRADAY_MOMENTUM_PRAEREGISTRIERUNG.md).

Noise-band breakout after Zarattini, Aziz and Barbon (2024), moved to BTC/ETH/SOL perpetuals.
For every minute k after the session anchor, sigma(k) is the mean absolute move from the anchor
open over the 14 previous sessions. The band is max/min(open, previous close) * (1 +/- sigma).
Entries and exits are only decided at the half-hour check bars (the 1m bar that closes at
HH:00 or HH:30). The trailing stop is max(upper band, VWAP) for longs, min(lower band, VWAP) for
shorts; everything is flat at the session end. A catastrophe stop at 3 * sigma * open (checked on
every bar by the engine) is the initial stop and defines 1 R.

Causality: sigma for a session reads only earlier sessions. Band, VWAP and the completeness flag at
a check bar read only bars up to and including that bar. ``NoiseTable`` is built once from the full
bar list for speed; the tests show that a table built from bars cut at a check bar gives the same
decision there.
"""
from __future__ import annotations

import bisect
import math
from array import array
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from src.research_lab.backtest.engine import History, Position, Signal
from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses.calendars import NEW_YORK, nyse_holidays

HYPOTHESIS = "S13"
INTERVAL = "1m"
INTERVAL_MS = 60_000
LOOKBACK_SESSIONS = 14
BAND_MULTIPLIER = 1.0  # the paper's base value, never optimised
CHECK_MINUTES = 30
CATASTROPHE_SIGMA = 3.0
SEED = 20261101
DAY_MS = 86_400_000

NY_OPEN = time(9, 30)
NY_CLOSE = time(16, 0)
UTC_SESSION_MINUTES = 1410  # 00:00 .. 23:30 UTC, last entry check 23:00
NAN = float("nan")


@dataclass(frozen=True, slots=True)
class S13Variant:
    variant_id: str
    anchor: str  # "ny" or "utc"
    hypothesis: str = HYPOTHESIS

    @property
    def params(self) -> dict[str, float | int | str]:
        return {"interval": INTERVAL, "anchor": self.anchor, "lookback_sessions": LOOKBACK_SESSIONS,
                "band_multiplier": BAND_MULTIPLIER, "check_minutes": CHECK_MINUTES,
                "catastrophe_sigma": CATASTROPHE_SIGMA}


S13_VARIANTS: tuple[S13Variant, ...] = (S13Variant("S13-NY", "ny"), S13Variant("S13-UTC", "utc"))


@dataclass(frozen=True, slots=True)
class Session:
    day: date
    anchor_ms: int  # open time of the first 1m bar
    minutes: int  # session length; the last bar closes at anchor + minutes
    prev_close_ms: int | None  # open time of the previous session's last 1m bar (NY only)

    @property
    def end_ms(self) -> int:
        return self.anchor_ms + self.minutes * INTERVAL_MS


def ny_ms(day: date, local: time) -> int:
    return int(datetime.combine(day, local, tzinfo=NEW_YORK).astimezone(timezone.utc).timestamp() * 1000)


def _nyse_day(day: date) -> bool:
    return day.weekday() < 5 and day not in nyse_holidays(day.year)


def sessions(variant: S13Variant, start_ms: int, end_ms: int) -> list[Session]:
    """All sessions of the variant whose anchor lies in [start_ms, end_ms), oldest first."""
    first = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).date() - timedelta(days=1)
    last = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).date() + timedelta(days=1)
    out: list[Session] = []
    day = first
    if variant.anchor == "utc":
        while day <= last:
            anchor = int(datetime.combine(day, time(0), tzinfo=timezone.utc).timestamp() * 1000)
            if start_ms <= anchor < end_ms:
                out.append(Session(day, anchor, UTC_SESSION_MINUTES, None))
            day += timedelta(days=1)
        return out
    if variant.anchor != "ny":
        raise ValueError(f"unknown anchor {variant.anchor!r}")
    prev = first - timedelta(days=1)
    while not _nyse_day(prev):
        prev -= timedelta(days=1)
    while day <= last:
        if _nyse_day(day):
            anchor = ny_ms(day, NY_OPEN)
            minutes = (ny_ms(day, NY_CLOSE) - anchor) // INTERVAL_MS
            if start_ms <= anchor < end_ms:
                out.append(Session(day, anchor, minutes, ny_ms(prev, NY_CLOSE) - INTERVAL_MS))
            prev = day
        day += timedelta(days=1)
    return out


@dataclass(frozen=True, slots=True)
class Check:
    """State at one check bar (minute k of a session, k a multiple of CHECK_MINUTES)."""

    session: int
    k: int
    last: bool  # session end: every position closes here
    entry_allowed: bool
    upper: float | None  # None: band not computable (sigma or today's data missing)
    lower: float | None
    vwap: float | None
    risk: float | None  # catastrophe stop distance = 1 R in price


@dataclass(slots=True)
class NoiseTable:
    variant: S13Variant
    sessions: list[Session]
    opens: array = field(default_factory=lambda: array("d"))  # NaN when the anchor bar is missing
    checks: dict[int, Check] = field(default_factory=dict)  # by open time of the check bar

    def check(self, open_time: int) -> Check | None:
        return self.checks.get(open_time)


def _lookup(times: Sequence[int], bars: Sequence[Kline], t: int) -> Kline | None:
    i = bisect.bisect_left(times, t)
    return bars[i] if i < len(times) and times[i] == t else None


def build_table(bars: Sequence[Kline], variant: S13Variant, start_ms: int, end_ms: int) -> NoiseTable:
    """Sessions with anchors in [start_ms, end_ms). Warm-up sessions belong in the range too:
    the first LOOKBACK_SESSIONS sessions never have a band."""
    times = [b.open_time for b in bars]
    table = NoiseTable(variant, sessions(variant, start_ms, end_ms))
    moves: list[array] = []
    for s, sess in enumerate(table.sessions):
        first = _lookup(times, bars, sess.anchor_ms)
        o = first.open if first is not None else NAN
        table.opens.append(o)
        prev_close = o
        if sess.prev_close_ms is not None:
            prev_bar = _lookup(times, bars, sess.prev_close_ms)
            prev_close = prev_bar.close if prev_bar is not None else NAN
        row = array("d", [NAN]) * (sess.minutes + 1)  # index k = 1..minutes, 0 unused
        i = bisect.bisect_left(times, sess.anchor_ms)
        complete = first is not None
        pv = vol = 0.0
        for k in range(1, sess.minutes + 1):
            t = sess.anchor_ms + (k - 1) * INTERVAL_MS
            bar = bars[i] if i < len(times) and times[i] == t else None
            if bar is None:
                complete = False
            else:
                i += 1
                if not math.isnan(o):
                    row[k] = abs(bar.close / o - 1)
                pv += (bar.high + bar.low + bar.close) / 3 * bar.volume
                vol += bar.volume
            if k % CHECK_MINUTES:
                continue
            sigma = _sigma(moves, s, k)
            ok = bar is not None and complete and sigma is not None and not math.isnan(o) and not math.isnan(prev_close)
            upper = max(o, prev_close) * (1 + BAND_MULTIPLIER * sigma) if ok else None
            lower = min(o, prev_close) * (1 - BAND_MULTIPLIER * sigma) if ok else None
            vwap = pv / vol if bar is not None and complete and vol > 0 else None
            risk = CATASTROPHE_SIGMA * BAND_MULTIPLIER * sigma * o if ok else None
            last = k == sess.minutes
            table.checks[t] = Check(s, k, last, not last and k < sess.minutes, upper, lower, vwap, risk)
        moves.append(row)
    return table


def _sigma(moves: list[array], s: int, k: int) -> float | None:
    """Mean |move| at minute k over the LOOKBACK_SESSIONS sessions before s; None if any is missing."""
    if s < LOOKBACK_SESSIONS:
        return None
    total = 0.0
    for j in range(s - LOOKBACK_SESSIONS, s):
        row = moves[j]
        if k >= len(row) or math.isnan(row[k]):
            return None
        total += row[k]
    return total / LOOKBACK_SESSIONS


def entry_side(check: Check, close: float) -> int:
    """+1 above the upper band, -1 below the lower band, 0 inside or not computable."""
    if not check.entry_allowed or check.upper is None or check.lower is None or check.risk is None or check.risk <= 0:
        return 0
    if close > check.upper:
        return 1
    if close < check.lower:
        return -1
    return 0


def exits(check: Check, side: int, close: float) -> bool:
    """Trailing stop at a check bar: long below max(upper, VWAP), short above min(lower, VWAP).
    Session end always exits. Without a band or VWAP the position exits too (counted in the report)."""
    if check.last or check.upper is None or check.lower is None or check.vwap is None:
        return True
    if side > 0:
        return close < max(check.upper, check.vwap)
    return close > min(check.lower, check.vwap)


def strategy(table: NoiseTable):
    """Engine strategy (``backtest.engine.run_backtest``) on 1m bars of one instrument."""

    exited: dict[int, int] = {}  # check-bar open time -> side that left there

    def exit_rule(history: History, position: Position) -> bool:
        bar = history[-1]
        check = table.check(bar.open_time)
        if check is not None and exits(check, position.side, bar.close):
            exited[bar.open_time] = position.side
            return True
        return False

    def decide(history: History) -> Signal | None:
        bar = history[-1]
        check = table.check(bar.open_time)
        if check is None:
            return None
        side = entry_side(check, bar.close)
        # Above the band but below VWAP: the long just left by its trailing stop and is not
        # re-entered on the same check bar (only the opposite band starts a reversal).
        if side == 0 or exited.pop(bar.open_time, 0) == side:
            return None
        assert check.risk is not None
        return Signal(side, bar.close - side * check.risk, exit_rule=exit_rule)

    return decide


# ----------------------------------------------------------------------------- feasibility count


@dataclass(slots=True)
class Counts:
    sessions: int = 0
    warmup: int = 0  # first LOOKBACK_SESSIONS sessions, never a band
    no_band: int = 0  # no check bar of the session had a band (data or sigma missing)
    no_breakout: int = 0
    signals: int = 0


@dataclass(frozen=True, slots=True)
class FirstSignal:
    day: date
    signal_time: int  # open time of the check bar
    direction: int


@dataclass(slots=True)
class CountResult:
    counts: Counts = field(default_factory=Counts)
    signals: list[FirstSignal] = field(default_factory=list)


def count_signals(bars: Sequence[Kline], table: NoiseTable, start_ms: int) -> CountResult:
    """Outcome-blind gate count (section 5.1): the first entry signal per session with anchor
    at or after start_ms. Reads only check-bar closes, no exits, no R."""
    times = [b.open_time for b in bars]
    by_session: dict[int, list[tuple[int, Check]]] = {}
    for t, check in table.checks.items():
        by_session.setdefault(check.session, []).append((t, check))
    result = CountResult()
    c = result.counts
    for s, sess in enumerate(table.sessions):
        if sess.anchor_ms < start_ms:
            continue
        c.sessions += 1
        if s < LOOKBACK_SESSIONS:
            c.warmup += 1
            continue
        checks = sorted(by_session.get(s, []))
        if not any(ch.upper is not None for _, ch in checks):
            c.no_band += 1
            continue
        for t, ch in checks:
            bar = _lookup(times, bars, t)
            side = entry_side(ch, bar.close) if bar is not None else 0
            if side:
                c.signals += 1
                result.signals.append(FirstSignal(sess.day, t, side))
                break
        else:
            c.no_breakout += 1
    return result
