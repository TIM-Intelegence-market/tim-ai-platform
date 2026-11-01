"""Rules of study S14 (docs/research_lab/studien/S14_PAAR_HANDEL_KOINTEGRATION_PRAEREGISTRIERUNG.md).

Pairs trading on BTC/ETH/SOL perpetuals. Hourly bars are built from 5m bars. For every hour t the
window is the W previous hours (t-W .. t-1, gap-free in both legs): OLS ln y = a + b ln x, residual
standard deviation s. z_t = (ln y_t - a - b ln x_t) / s uses only that window plus the close at t.
Entry when |z| crosses 2, exit at z = 0, stop at |z| = 4, time stop 120 h, all decided on hourly
closes and filled at the next hourly open of both legs. 1 R = 2 s (entry to stop in z units).

The engine trades one instrument, so ``simulate_trade`` books both legs itself with the engine's
cost conventions (taker fee and slippage per leg and side, funding per leg).
"""
from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass

from src.research_lab.backtest.engine import _funding_cost
from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.protocol import BASE_COSTS, CostModel

HYPOTHESIS = "S14"
HOUR_MS = 3_600_000
FIVE_MIN_MS = 300_000
ENTRY_Z = 2.0
EXIT_Z = 0.0
STOP_Z = 4.0
TIME_STOP_HOURS = 120
EG_CRITICAL = -3.34  # Engle-Granger 5 %, two variables with constant (MacKinnon 2010, asymptotic)
SEED = 20261102
PAIRS: tuple[tuple[str, str], ...] = (("ETHUSDT", "BTCUSDT"), ("SOLUSDT", "BTCUSDT"), ("SOLUSDT", "ETHUSDT"))


@dataclass(frozen=True, slots=True)
class S14Variant:
    variant_id: str
    window: int  # hours
    cointegration: bool
    hypothesis: str = HYPOTHESIS

    @property
    def params(self) -> dict[str, float | int | bool | str]:
        return {"interval": "1h", "window_hours": self.window, "cointegration_filter": self.cointegration,
                "entry_z": ENTRY_Z, "exit_z": EXIT_Z, "stop_z": STOP_Z, "time_stop_hours": TIME_STOP_HOURS,
                "eg_critical": EG_CRITICAL}


S14_VARIANTS: tuple[S14Variant, ...] = (
    S14Variant("S14-W168", 168, False), S14Variant("S14-W168-K", 168, True),
    S14Variant("S14-W720", 720, False), S14Variant("S14-W720-K", 720, True),
)


def hourly(bars: Sequence[Kline]) -> list[Kline]:
    """1h bars from 5m bars; an hour exists only when all twelve 5m bars are present."""
    out: list[Kline] = []
    i, n = 0, len(bars)
    while i < n:
        start = bars[i].open_time - bars[i].open_time % HOUR_MS
        j = i
        while j < n and bars[j].open_time < start + HOUR_MS:
            j += 1
        group = bars[i:j]
        if len(group) == 12 and all(b.open_time == start + k * FIVE_MIN_MS for k, b in enumerate(group)):
            out.append(Kline(start, group[0].open, max(b.high for b in group), min(b.low for b in group), group[-1].close,
                             sum(b.volume for b in group), start + HOUR_MS - 1, sum(b.taker_buy_volume for b in group)))
        i = j
    return out


@dataclass(frozen=True, slots=True)
class PairSeries:
    """Common hours of both legs, oldest first."""

    y: str
    x: str
    times: list[int]
    y_open: list[float]
    y_close: list[float]
    x_open: list[float]
    x_close: list[float]

    @property
    def name(self) -> str:
        return f"{self.y[:-4]}/{self.x[:-4]}"


def align(y_symbol: str, y_bars: Sequence[Kline], x_symbol: str, x_bars: Sequence[Kline]) -> PairSeries:
    xs = {b.open_time: b for b in x_bars}
    rows = [(b, xs[b.open_time]) for b in y_bars if b.open_time in xs]
    return PairSeries(y_symbol, x_symbol, [b.open_time for b, _ in rows], [b.open for b, _ in rows],
                      [b.close for b, _ in rows], [x.open for _, x in rows], [x.close for _, x in rows])


@dataclass(frozen=True, slots=True)
class Fit:
    alpha: float
    beta: float
    sigma: float

    def z(self, ly: float, lx: float) -> float:
        return (ly - self.alpha - self.beta * lx) / self.sigma


def window_ok(pair: PairSeries, t: int, window: int) -> bool:
    """The W hours before t exist without gaps (t - W .. t - 1, and t itself directly after)."""
    return t >= window and pair.times[t] - pair.times[t - window] == window * HOUR_MS


def fit_window(ly: Sequence[float], lx: Sequence[float], t: int, window: int) -> Fit | None:
    """OLS on indices t-W .. t-1. None if beta <= 0 or sigma <= 0."""
    ys, xs = ly[t - window:t], lx[t - window:t]
    mx, my = math.fsum(xs) / window, math.fsum(ys) / window
    sxx = math.fsum((v - mx) ** 2 for v in xs)
    if sxx <= 0:
        return None
    beta = math.fsum((a - mx) * (b - my) for a, b in zip(xs, ys)) / sxx
    alpha = my - beta * mx
    resid = [b - alpha - beta * a for a, b in zip(xs, ys)]
    sigma = math.sqrt(math.fsum(e * e for e in resid) / (window - 2))
    if beta <= 0 or sigma <= 0:
        return None
    return Fit(alpha, beta, sigma)


def df_tstat(ly: Sequence[float], lx: Sequence[float], t: int, window: int, fit: Fit) -> float:
    """Dickey-Fuller t-statistic of gamma in de_s = gamma e_{s-1} + phi de_{s-1} + u (no constant) on
    the window residuals."""
    e = [ly[s] - fit.alpha - fit.beta * lx[s] for s in range(t - window, t)]
    rows = [(e[k - 1], e[k - 1] - e[k - 2], e[k] - e[k - 1]) for k in range(2, len(e))]
    s11 = math.fsum(a * a for a, _, _ in rows)
    s12 = math.fsum(a * b for a, b, _ in rows)
    s22 = math.fsum(b * b for _, b, _ in rows)
    s1y = math.fsum(a * y for a, _, y in rows)
    s2y = math.fsum(b * y for _, b, y in rows)
    det = s11 * s22 - s12 * s12
    if det <= 0:
        return 0.0
    gamma = (s22 * s1y - s12 * s2y) / det
    phi = (s11 * s2y - s12 * s1y) / det
    rss = math.fsum((y - gamma * a - phi * b) ** 2 for a, b, y in rows)
    dof = len(rows) - 2
    if dof <= 0 or rss <= 0:
        return 0.0
    se = math.sqrt(rss / dof * s22 / det)
    return gamma / se


@dataclass(frozen=True, slots=True)
class Entry:
    index: int  # hour whose close gave the signal
    side: int  # +1 long spread (buy y, sell x), -1 short spread
    z: float
    fit: Fit


class Signals:
    """Rolling z-values of one pair and variant. ``state(t)`` reads only hours up to t."""

    def __init__(self, pair: PairSeries, variant: S14Variant) -> None:
        self.pair = pair
        self.variant = variant
        self.ly = [math.log(v) for v in pair.y_close]
        self.lx = [math.log(v) for v in pair.x_close]
        self._fits: dict[int, Fit | None] = {}

    def fit(self, t: int) -> Fit | None:
        if t not in self._fits:
            w = self.variant.window
            self._fits[t] = fit_window(self.ly, self.lx, t, w) if window_ok(self.pair, t, w) else None
        return self._fits[t]

    def z(self, t: int) -> float | None:
        f = self.fit(t)
        return None if f is None else f.z(self.ly[t], self.lx[t])

    def possible(self, t: int) -> Fit | None:
        """Fit at t if an entry could be decided here (window, beta, filter); used by the random comparison."""
        f = self.fit(t)
        if f is None or t + 1 >= len(self.pair.times) or self.pair.times[t + 1] - self.pair.times[t] != HOUR_MS:
            return None
        if self.variant.cointegration and df_tstat(self.ly, self.lx, t, self.variant.window, f) > EG_CRITICAL:
            return None
        return f

    def entry(self, t: int) -> Entry | None:
        """|z| crosses ENTRY_Z at t (each z with its own window) and the filter holds."""
        if t < 1:
            return None
        z_now, z_prev = self.z(t), self.z(t - 1)
        if z_now is None or z_prev is None or abs(z_prev) >= ENTRY_Z or abs(z_now) < ENTRY_Z:
            return None
        f = self.possible(t)
        if f is None:
            return None
        self._fits.pop(t - 1, None)  # memory: older fits are never read again
        return Entry(t, -1 if z_now > 0 else 1, z_now, f)


def entries(signals: Signals, start_ms: int, end_ms: int) -> list[Entry]:
    """All entry signals in [start_ms, end_ms), ignoring open positions (count of section 5.1)."""
    times = signals.pair.times
    lo, hi = bisect.bisect_left(times, start_ms), bisect.bisect_left(times, end_ms)
    out = []
    for t in range(max(lo, 1), hi):
        e = signals.entry(t)
        if e is not None:
            out.append(e)
        signals._fits.pop(t - 1, None)
    return out


@dataclass(frozen=True, slots=True)
class PairTrade:
    pair: str
    signal_time: int
    entry_time: int
    exit_time: int
    side: int
    reason: str  # rule (z back to 0), stop, time, gap, end
    hours_held: int
    beta: float
    sigma: float
    r: float
    cost_r: float
    funding_r: float


def simulate_trade(pair: PairSeries, signals: Signals, entry: Entry, costs: CostModel = BASE_COSTS,
                   y_funding: Sequence[FundingRate] = (), x_funding: Sequence[FundingRate] = ()) -> PairTrade | None:
    """Both legs from the open after the signal hour to the exit; None if there is no next hour."""
    t0 = entry.index
    first = t0 + 1
    times = pair.times
    if first >= len(times) or times[first] - times[t0] != HOUR_MS:
        return None
    f, side = entry.fit, entry.side
    exit_at = None
    reason = "end"
    for j in range(first, len(times)):
        if j > first and times[j] - times[j - 1] != HOUR_MS:
            exit_at, reason, close_of = j - 1, "gap", True
            break
        z = f.z(signals.ly[j], signals.lx[j])
        held = j - first + 1
        if side * z >= -EXIT_Z:
            reason = "rule"
        elif side * z <= -STOP_Z:
            reason = "stop"
        elif held >= TIME_STOP_HOURS:
            reason = "time"
        else:
            continue
        if j + 1 < len(times) and times[j + 1] - times[j] == HOUR_MS:
            exit_at, close_of = j + 1, False
        else:
            exit_at, close_of, reason = j, True, "gap" if j + 1 < len(times) else "end"
        break
    if exit_at is None:
        exit_at, close_of = len(times) - 1, True
    legs = ((side, 1.0, pair.y_open, pair.y_close, y_funding), (-side, f.beta, pair.x_open, pair.x_close, x_funding))
    pnl = fees = fund = 0.0
    entry_ms = times[first]
    exit_ms = times[exit_at] + HOUR_MS if close_of else times[exit_at]
    for q, w, opens, closes, funding in legs:
        p_in = opens[first] * (1 + q * costs.slippage)
        raw_out = closes[exit_at] if close_of else opens[exit_at]
        p_out = raw_out * (1 - q * costs.slippage)
        pnl += w * q * (p_out / p_in - 1)
        fees += costs.fee * w * (1 + p_out / p_in)
        fund += _funding_cost(funding, [r.time for r in funding], q, w, entry_ms, exit_ms, costs)
    risk = (STOP_Z - ENTRY_Z) * f.sigma
    hours = exit_at - first + (1 if close_of else 0)
    return PairTrade(pair.name, times[t0], entry_ms, exit_ms, side, reason, hours, f.beta, f.sigma,
                     (pnl - fees - fund) / risk, fees / risk, fund / risk)


def run_pair(pair: PairSeries, variant: S14Variant, start_ms: int, end_ms: int, costs: CostModel = BASE_COSTS,
             y_funding: Sequence[FundingRate] = (), x_funding: Sequence[FundingRate] = ()) -> list[PairTrade]:
    """One position at a time; the next entry needs a new crossing after the exit hour."""
    signals = Signals(pair, variant)
    trades: list[PairTrade] = []
    busy_until = -1  # open time of the exit fill; signals before it are ignored
    for e in entries(signals, start_ms, end_ms):
        if pair.times[e.index] < busy_until:
            continue
        trade = simulate_trade(pair, signals, e, costs, y_funding, x_funding)
        if trade is None:
            continue
        trades.append(trade)
        busy_until = trade.exit_time
    return trades
