"""Signal rules of study S10 (docs/research_lab/studien/S10_IB_AUSBRUCH_POC_RETEST_PRAEREGISTRIERUNG.md).

Initial Balance (09:30-10:00 New York) breakout by a 5m close until 12:00, first retest of the
zone between POC and value-area edge of the IB volume profile (1m bars), reaction close back
beyond the value-area edge until 13:00. Variant O additionally needs seller (buyer) absorption
at the zone. One signal per instrument and NYSE trading day.

Every rule reads only bars that are closed when the decision falls. Nothing here computes
outcomes: ``scan_day`` stops at the signal bar, ``count_signals`` is the outcome-blind count
of the feasibility gate (section 5.1). Stop distance is returned for the later run, the
target (2 R) and exits are not evaluated here.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses.calendars import NEW_YORK, nyse_holidays

HYPOTHESIS = "S10"
IB_INTERVAL_MS = 60_000  # 1m bars build the IB profile
INTERVAL = "5m"
INTERVAL_MS = 300_000
IB_MINUTES = 30
PROFILE_BINS = 40
VALUE_AREA_SHARE = 0.70
ATR_PERIOD = 14  # 5m bars, stop buffer
DAILY_ATR_PERIOD = 14  # UTC days before the trading day, IB width filter
MIN_IB_ATR_1D = 0.25
STOP_BUFFER_ATR = 0.1
TARGET_R = 2.0
ABSORPTION_LOOKBACK = 5
ABSORPTION_VOLUME_RATIO = 1.2  # "schwer" in ORDERFLOW_REGELN.md
ABSORPTION_RANGE_RATIO = 0.8  # "schrumpfend"
SEED = 20261029
DAY_MS = 86_400_000

IB_START = time(9, 30)
IB_END = time(10, 0)
LAST_BREAKOUT_CLOSE = time(12, 0)
LAST_REACTION_CLOSE = time(13, 0)
SESSION_CLOSE = time(16, 0)  # time stop (not used by the count)


@dataclass(frozen=True, slots=True)
class S10Variant:
    variant_id: str
    orderflow: bool
    hypothesis: str = HYPOTHESIS

    @property
    def params(self) -> dict[str, float | int | str | bool]:
        return {"interval": INTERVAL, "orderflow": self.orderflow, "ib_minutes": IB_MINUTES, "bins": PROFILE_BINS,
                "value_area": VALUE_AREA_SHARE, "min_ib_atr_1d": MIN_IB_ATR_1D, "stop_buffer_atr": STOP_BUFFER_ATR,
                "target_r": TARGET_R, "absorption_volume_ratio": ABSORPTION_VOLUME_RATIO,
                "absorption_range_ratio": ABSORPTION_RANGE_RATIO}


S10_VARIANTS: tuple[S10Variant, ...] = (S10Variant("S10-P", False), S10Variant("S10-O", True))


# ----------------------------------------------------------------------------- calendar


def ny_ms(day: date, local: time) -> int:
    return int(datetime.combine(day, local, tzinfo=NEW_YORK).astimezone(timezone.utc).timestamp() * 1000)


def trading_days(start_ms: int, end_ms: int) -> list[date]:
    """NYSE trading days whose IB starts in [start_ms, end_ms)."""
    first = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).date() - timedelta(days=1)
    last = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).date() + timedelta(days=1)
    days, day = [], first
    while day <= last:
        if day.weekday() < 5 and day not in nyse_holidays(day.year) and start_ms <= ny_ms(day, IB_START) < end_ms:
            days.append(day)
        day += timedelta(days=1)
    return days


# ----------------------------------------------------------------------------- IB profile


@dataclass(frozen=True, slots=True)
class IBProfile:
    high: float
    low: float
    poc: float
    vah: float
    val: float


def ib_profile(bars: Sequence[Kline]) -> IBProfile | None:
    """Profile of the IB: each bar's volume spread evenly over its range, PROFILE_BINS equal bins from
    IBL to IBH, POC = fullest bin (ties: the one nearest the IB middle, then the lower), value area
    70 % grown from the POC towards the fuller neighbour (ties: upwards)."""
    if not bars:
        return None
    low, high = min(b.low for b in bars), max(b.high for b in bars)
    if high <= low:
        return None
    step = (high - low) / PROFILE_BINS
    bins = [0.0] * PROFILE_BINS
    for b in bars:
        if b.volume <= 0:
            continue
        first = min(PROFILE_BINS - 1, int((b.low - low) / step))
        last = min(PROFILE_BINS - 1, int((b.high - low) / step))
        if b.high <= b.low or first == last:
            bins[first] += b.volume
            continue
        for i in range(first, last + 1):
            lo, hi = max(b.low, low + i * step), min(b.high, low + (i + 1) * step)
            if hi > lo:
                bins[i] += b.volume * (hi - lo) / (b.high - b.low)
    total = sum(bins)
    if total <= 0:
        return None
    middle = (PROFILE_BINS - 1) / 2
    poc = max(range(PROFILE_BINS), key=lambda i: (bins[i], -abs(i - middle), -i))
    lo_i = hi_i = poc
    covered = bins[poc]
    while covered < total * VALUE_AREA_SHARE and (lo_i > 0 or hi_i < PROFILE_BINS - 1):
        below = bins[lo_i - 1] if lo_i > 0 else -1.0
        above = bins[hi_i + 1] if hi_i < PROFILE_BINS - 1 else -1.0
        if above >= below:
            hi_i += 1
            covered += bins[hi_i]
        else:
            lo_i -= 1
            covered += bins[lo_i]
    return IBProfile(high, low, low + (poc + 0.5) * step, low + (hi_i + 1) * step, low + lo_i * step)


# ----------------------------------------------------------------------------- ATR helpers


def true_range(bar: Kline, prev_close: float) -> float:
    return max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close))


def daily_bars(bars_5m: Iterable[Kline]) -> dict[int, tuple[float, float, float, int]]:
    """UTC day start -> (high, low, close, bar count) from 5m bars."""
    days: dict[int, list[float]] = {}
    for b in bars_5m:
        key = b.open_time - b.open_time % DAY_MS
        row = days.get(key)
        if row is None:
            days[key] = [b.high, b.low, b.close, 1]
        else:
            row[0] = max(row[0], b.high)
            row[1] = min(row[1], b.low)
            row[2] = b.close
            row[3] += 1
    return {k: (v[0], v[1], v[2], int(v[3])) for k, v in days.items()}


def daily_atr_before(days: dict[int, tuple[float, float, float, int]], day_start_ms: int) -> float | None:
    """Simple mean true range of the DAILY_ATR_PERIOD complete UTC days before ``day_start_ms``
    (one more complete day for the first previous close); None if any of them is incomplete."""
    full = DAY_MS // INTERVAL_MS
    keys = [day_start_ms - k * DAY_MS for k in range(DAILY_ATR_PERIOD + 1, 0, -1)]
    rows = [days.get(k) for k in keys]
    if any(r is None or r[3] != full for r in rows):
        return None
    trs = []
    for prev, cur in zip(rows, rows[1:]):
        trs.append(max(cur[0] - cur[1], abs(cur[0] - prev[2]), abs(cur[1] - prev[2])))
    return sum(trs) / len(trs)


def atr_5m(window: Sequence[Kline]) -> float:
    """Simple mean true range of the last ATR_PERIOD bars of ``window`` (needs ATR_PERIOD + 1 bars)."""
    tail = window[-(ATR_PERIOD + 1):]
    return sum(true_range(cur, prev.close) for prev, cur in zip(tail, tail[1:])) / ATR_PERIOD


def absorbed(window: Sequence[Kline], direction: int) -> bool:
    """Last bar of ``window`` shows absorption of the side attacking the zone: delta against the trade
    direction, volume >= 1.2 x and range < 0.8 x the mean of the ABSORPTION_LOOKBACK bars before."""
    bar, before = window[-1], window[-1 - ABSORPTION_LOOKBACK:-1]
    if len(before) < ABSORPTION_LOOKBACK:
        return False
    delta = 2 * bar.taker_buy_volume - bar.volume
    if delta * direction >= 0:
        return False
    mean_volume = sum(b.volume for b in before) / ABSORPTION_LOOKBACK
    mean_range = sum(b.high - b.low for b in before) / ABSORPTION_LOOKBACK
    if mean_volume <= 0 or mean_range <= 0:
        return False
    return bar.volume >= ABSORPTION_VOLUME_RATIO * mean_volume and (bar.high - bar.low) < ABSORPTION_RANGE_RATIO * mean_range


# ----------------------------------------------------------------------------- one trading day


@dataclass(slots=True)
class Counts:
    days: int = 0
    data_missing: int = 0
    atr_missing: int = 0
    ib_narrow: int = 0
    no_breakout: int = 0
    invalidated: int = 0
    no_retest: int = 0
    no_reaction: int = 0
    no_absorption: int = 0
    no_entry_bar: int = 0
    signals: int = 0


@dataclass(frozen=True, slots=True)
class DaySignal:
    day: date
    direction: int  # +1 long, -1 short
    signal_time: int  # close time of the reaction bar (UTC ms, exclusive end)
    entry_time: int  # open time of the next 5m bar
    stop: float
    profile: IBProfile


@dataclass(slots=True)
class DayData:
    """Bars one trading day needs: the 30 IB 1m bars and the 5m bars from WARMUP before 09:30 to 16:00."""

    ib: list[Kline] = field(default_factory=list)
    session: list[Kline] = field(default_factory=list)


WARMUP_5M = max(ATR_PERIOD + 1, ABSORPTION_LOOKBACK + 1)


def session_window(day: date) -> tuple[int, int]:
    return ny_ms(day, IB_START) - WARMUP_5M * INTERVAL_MS, ny_ms(day, SESSION_CLOSE)


def _complete(bars: Sequence[Kline], start: int, end: int, step: int) -> bool:
    return len(bars) == (end - start) // step and all(b.open_time == start + i * step for i, b in enumerate(bars))


def scan_day(day: date, data: DayData, daily_atr: float | None, variant: S10Variant, counts: Counts) -> DaySignal | None:
    """Rules 4.1-4.3 for one NYSE trading day. Reads bars only up to the reaction close and the open
    time of the entry bar (the entry price is not read)."""
    counts.days += 1
    ib_start, ib_end = ny_ms(day, IB_START), ny_ms(day, IB_END)
    window_start, close_ms = session_window(day)
    if not _complete(data.ib, ib_start, ib_end, IB_INTERVAL_MS) or not _complete(data.session, window_start, close_ms, INTERVAL_MS):
        counts.data_missing += 1
        return None
    if daily_atr is None:
        counts.atr_missing += 1
        return None
    profile = ib_profile(data.ib)
    if profile is None or profile.high - profile.low < MIN_IB_ATR_1D * daily_atr:
        counts.ib_narrow += 1
        return None
    bars = data.session
    first = next(i for i, b in enumerate(bars) if b.open_time >= ib_end)
    last_breakout = ny_ms(day, LAST_BREAKOUT_CLOSE)
    last_reaction = ny_ms(day, LAST_REACTION_CLOSE)

    breakout, direction = None, 0
    for i in range(first, len(bars)):
        b = bars[i]
        if b.open_time + INTERVAL_MS > last_breakout:
            break
        if b.close > profile.high:
            breakout, direction = i, 1
            break
        if b.close < profile.low:
            breakout, direction = i, -1
            break
    if breakout is None:
        counts.no_breakout += 1
        return None

    edge = profile.vah if direction > 0 else profile.val  # zone edge on the breakout side
    far = profile.val if direction > 0 else profile.vah  # invalidation edge
    touched = absorption = reacted = False
    for j in range(breakout + 1, len(bars)):
        b = bars[j]
        if b.open_time + INTERVAL_MS > last_reaction:
            break
        if (b.close - far) * direction < 0:
            counts.invalidated += 1
            return None
        if (b.low <= edge) if direction > 0 else (b.high >= edge):
            touched = True
            if variant.orderflow and absorbed(bars[: j + 1], direction):
                absorption = True
        if not touched or (b.close - edge) * direction <= 0:
            continue
        reacted = True
        if variant.orderflow and not absorption:
            continue  # variant O waits for a later reaction close with absorption at the zone
        if j + 1 >= len(bars):
            counts.no_entry_bar += 1
            return None
        stop = far - direction * STOP_BUFFER_ATR * atr_5m(bars[: j + 1])
        counts.signals += 1
        return DaySignal(day, direction, b.open_time + INTERVAL_MS, bars[j + 1].open_time, stop, profile)
    if not touched:
        counts.no_retest += 1
    elif variant.orderflow and reacted:
        counts.no_absorption += 1
    else:
        counts.no_reaction += 1
    return None


# ----------------------------------------------------------------------------- outcome-blind count


def split_day_data(days: Sequence[date], bars_1m: Iterable[Kline], bars_5m: Sequence[Kline]) -> dict[date, DayData]:
    """Assign the 1m IB bars and the 5m session bars to their trading days."""
    data = {d: DayData() for d in days}
    ib_minute = {ny_ms(d, IB_START) + k * IB_INTERVAL_MS: d for d in days for k in range(IB_MINUTES)}
    for b in bars_1m:
        d = ib_minute.get(b.open_time)
        if d is not None:
            data[d].ib.append(b)
    windows = sorted((session_window(d), d) for d in days)
    k = 0
    for b in bars_5m:
        while k < len(windows) and windows[k][0][1] <= b.open_time:
            k += 1
        m = k
        while m < len(windows) and windows[m][0][0] <= b.open_time:
            (lo, hi), d = windows[m]
            if lo <= b.open_time < hi:
                data[d].session.append(b)
            m += 1
    return data


@dataclass(frozen=True, slots=True)
class SignalCount:
    signals: list[DaySignal]
    counts: Counts


def count_signals(days: Sequence[date], data: dict[date, DayData], daily: dict[int, tuple[float, float, float, int]],
                  variant: S10Variant) -> SignalCount:
    counts = Counts()
    signals = []
    for d in days:
        day_start = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)
        signal = scan_day(d, data[d], daily_atr_before(daily, day_start), variant, counts)
        if signal is not None:
            signals.append(signal)
    return SignalCount(signals, counts)
