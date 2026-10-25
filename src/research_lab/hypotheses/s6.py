"""Study S6 (docs/research_lab/studien/S6_WINRATE_95_MAKER_MEAN_REVERSION_PRAEREGISTRIERUNG.md): maker mean reversion.

Frozen rules of sections 3 and 4.1 on 1-minute perpetual klines: the reference (VWAP over the
last 30 closed bars, sigma from 120 log returns of the last 121 closed bars), resting limit
orders k * sigma30 away from the VWAP, the post-only rule, the trade-through fill rule with
margin delta, the exits (stop checked from the fill bar on, target from the next bar on,
ambiguous bar = stop, time stop at bar 240, gap, section end), the locks, funding inside a
trade and the net result in R. The outcome-blind fill count for the gate (section 6.1) lives
here too and never reads an exit.

Prices are floats as the archive parser delivers them; rounding to the tick is always against
the trade (section 3). Fees: maker for limit fills, taker plus slippage for market exits.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections.abc import Sequence

from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.hypotheses.s5 import normalize_funding
from src.research_lab.protocol import MAKER_FEE  # protocol entry 1.3: maker fee per limit fill (section 5.3, A1)

MINUTE_MS = 60_000
STOP_FRACTION = 0.015  # R = 1.5 % of the entry fill
VWAP_BARS = 30
SIGMA_RETURNS = 120  # log returns, from 121 closes
TIME_STOP_BARS = 240  # the fill bar is bar 1
GAP_BRIDGE_MS = 6 * MINUTE_MS  # up to 5 missing minutes are bridged: the next bar starts <= 6 min after the last
LOCK_AFTER_EXIT = 5  # bars without orders after target / time / section_end
LOCK_AFTER_LOSS = 30  # after stop, both, gap
DELTA_MIN = 0.0001  # trade-through margin: 0.01 % of the limit, at least one tick
NOMINAL = 1_000.0  # USDT per trade (only matters for the aggTrades latency check)

LONG, SHORT = 1, -1


@dataclass(frozen=True, slots=True)
class S6Costs:
    maker_fee: float = MAKER_FEE
    taker_fee: float = 0.0005
    slippage: float = 0.0003  # time, gap, section_end
    stop_slippage: float = 0.0005
    delta_min: float = DELTA_MIN
    funding_against_only: bool = False  # stress: funding never in favour of the trade

    def stressed(self) -> "S6Costs":
        return S6Costs(self.maker_fee * 2, self.taker_fee * 2, self.slippage * 2, self.stop_slippage * 2,
                       self.delta_min * 2, True)


BASE_COSTS = S6Costs()
STRESS_COSTS = BASE_COSTS.stressed()


@dataclass(frozen=True, slots=True)
class S6Variant:
    variant_id: str
    k: float  # limit distance in sigma30
    target_r: float  # target in R


S6_VARIANTS: tuple[S6Variant, ...] = (
    S6Variant("S6-k2-t15", 2.0, 0.15), S6Variant("S6-k2-t20", 2.0, 0.20), S6Variant("S6-k2-t25", 2.0, 0.25),
    S6Variant("S6-k3-t15", 3.0, 0.15), S6Variant("S6-k3-t20", 3.0, 0.20), S6Variant("S6-k3-t25", 3.0, 0.25),
)


# ----------------------------------------------------------------------------- reference


def month_key(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m")


def day_key(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def empirical_ticks(bars: Sequence[Kline]) -> dict[str, float]:
    """Smallest positive difference between any two OHLC values of a calendar month (section 3)."""
    values: dict[str, set[float]] = {}
    for b in bars:
        values.setdefault(month_key(b.open_time), set()).update((b.open, b.high, b.low, b.close))
    out: dict[str, float] = {}
    for month, prices in values.items():
        ordered = sorted(prices)
        diffs = [round(b - a, 10) for a, b in zip(ordered, ordered[1:])]
        positive = [d for d in diffs if d > 0]
        out[month] = min(positive) if positive else 0.0
    return out


def round_against(price: float, tick: float, upward: bool) -> float:
    """Round to the tick in the direction that hurts the trade (section 3)."""
    if tick <= 0:
        return price
    steps = price / tick
    rounded = math.ceil(steps - 1e-9) if upward else math.floor(steps + 1e-9)
    return round(rounded * tick, 10)


@dataclass(slots=True)
class Reference:
    """Per bar index i: VWAP30 and sigma30 from the closed bars before i, or None when the window is incomplete."""

    vwap: list[float | None]
    sigma30: list[float | None]
    contiguous_before: list[bool]  # bar i starts exactly one minute after bar i-1


def compute_reference(bars: Sequence[Kline]) -> Reference:
    n = len(bars)
    vwap: list[float | None] = [None] * n
    sigma: list[float | None] = [None] * n
    contiguous = [False] * n
    run = [0] * n  # bars in the contiguous run ending at i, including i
    for i in range(n):
        if i > 0 and bars[i].open_time - bars[i - 1].open_time == MINUTE_MS:
            contiguous[i] = True
            run[i] = run[i - 1] + 1
        else:
            run[i] = 1
    # rolling sums over contiguous runs only
    pv = cv = 0.0  # sum(close*volume), sum(volume) over the last VWAP_BARS bars
    cs = 0.0  # sum of closes, for the volume-0 fallback
    rs = rs2 = 0.0  # sum and sum of squares of the last SIGMA_RETURNS log returns
    for i in range(n):
        if contiguous[i] and run[i - 1] >= SIGMA_RETURNS + 1:
            if run[i - 1] == SIGMA_RETURNS + 1 or vwap[i - 1] is None or i % 10_000 == 0:
                # first complete window of this run, or a periodic rebuild against float drift: compute directly
                w = bars[i - VWAP_BARS:i]
                pv = sum(b.close * b.volume for b in w)
                cv = sum(b.volume for b in w)
                cs = sum(b.close for b in w)
                closes = [b.close for b in bars[i - SIGMA_RETURNS - 1:i]]
                rets = [math.log(b / a) for a, b in zip(closes, closes[1:])]
                rs = sum(rets)
                rs2 = sum(r * r for r in rets)
            else:
                out_b, in_b = bars[i - VWAP_BARS - 1], bars[i - 1]
                pv += in_b.close * in_b.volume - out_b.close * out_b.volume
                cv += in_b.volume - out_b.volume
                cs += in_b.close - out_b.close
                r_in = math.log(bars[i - 1].close / bars[i - 2].close)
                r_out = math.log(bars[i - SIGMA_RETURNS - 1].close / bars[i - SIGMA_RETURNS - 2].close)
                rs += r_in - r_out
                rs2 += r_in * r_in - r_out * r_out
            vwap[i] = pv / cv if cv > 0 else cs / VWAP_BARS
            mean = rs / SIGMA_RETURNS
            var = max(rs2 / SIGMA_RETURNS - mean * mean, 0.0)
            sigma[i] = math.sqrt(var) * math.sqrt(VWAP_BARS)
    return Reference(vwap, sigma, contiguous)


# ----------------------------------------------------------------------------- orders and fills


def limit_price(ref_vwap: float, sigma30: float, k: float, side: int, tick: float) -> float:
    raw = ref_vwap * (1 - k * sigma30) if side == LONG else ref_vwap * (1 + k * sigma30)
    return round_against(raw, tick, upward=(side == SHORT))


def margin(price: float, tick: float, costs: S6Costs) -> float:
    return max(costs.delta_min * price, tick)


def crosses(bars: Sequence[Kline], i: int, limit: float, side: int) -> bool:
    """Post-only: the order is not placed when the last close or this bar's open is already through the limit."""
    prev_close = bars[i - 1].close
    if side == LONG:
        return prev_close <= limit or bars[i].open <= limit
    return prev_close >= limit or bars[i].open >= limit


def traded_through(bar: Kline, limit: float, side: int, delta: float) -> bool:
    return bar.low <= limit - delta if side == LONG else bar.high >= limit + delta


# ----------------------------------------------------------------------------- trades


@dataclass(frozen=True, slots=True)
class Trade:
    side: int
    entry_index: int
    entry_time: int
    entry_fill: float
    exit_index: int
    exit_time: int
    exit_fill: float
    reason: str  # stop, target, time, gap, section_end, both
    ambiguous: bool
    fees: float  # USDT
    funding: float  # USDT, positive = cost
    net_r: float

    @property
    def hit(self) -> bool:
        return self.net_r > 0

    @property
    def bars_held(self) -> int:
        return self.exit_index - self.entry_index + 1


def _funding_cost(funding_times: Sequence[int], funding_units: Sequence[float], entry_minute: int, exit_minute: int,
                  side: int, costs: S6Costs) -> float:
    """Funding with entry minute < F <= exit minute (section 4.1), positive = cost."""
    lo = bisect_right(funding_times, entry_minute)
    hi = bisect_right(funding_times, exit_minute)
    total = 0.0
    for j in range(lo, hi):
        cost = funding_units[j] * NOMINAL * (1 if side == LONG else -1)
        if costs.funding_against_only and cost < 0:
            cost = 0.0
        total += cost
    return total


def _exit(bars: Sequence[Kline], i: int, side: int, fill: float, variant: S6Variant, tick: float, costs: S6Costs,
          end_ms: int) -> tuple[int, float, str, bool, float]:
    """Walk forward from the fill bar. Returns (exit_index, exit_fill, reason, ambiguous, exit_fee_rate)."""
    stop = round_against(fill * (1 - STOP_FRACTION * side), tick, upward=(side == LONG))
    target = round_against(fill * (1 + variant.target_r * STOP_FRACTION * side), tick, upward=(side == LONG))
    delta_t = margin(target, tick, costs)
    stop_slip = 1 - costs.stop_slippage * side
    mkt_slip = 1 - costs.slippage * side
    # fill bar: stop only (anything beyond the stop happened after the fill, section 4.1)
    b = bars[i]
    if (b.low <= stop if side == LONG else b.high >= stop):
        return i, stop * stop_slip, "stop", False, costs.taker_fee
    j = i + 1
    while True:
        if j >= len(bars) or bars[j].open_time >= end_ms:
            return j - 1, bars[j - 1].close * mkt_slip, "section_end", False, costs.taker_fee
        b = bars[j]
        if b.open_time - bars[j - 1].open_time > GAP_BRIDGE_MS:
            return j - 1, bars[j - 1].close * mkt_slip, "gap", False, costs.taker_fee
        stop_hit = b.low <= stop if side == LONG else b.high >= stop
        target_hit = b.high >= target + delta_t if side == LONG else b.low <= target - delta_t
        if stop_hit:
            price = min(stop, b.open) if side == LONG else max(stop, b.open)
            return j, price * stop_slip, "stop", target_hit, costs.taker_fee
        if target_hit:
            return j, target, "target", False, costs.maker_fee
        if j - i + 1 >= TIME_STOP_BARS:
            return j, b.close * mkt_slip, "time", False, costs.taker_fee
        j += 1


@dataclass(slots=True)
class Simulation:
    trades: list[Trade] = field(default_factory=list)
    skipped_cross: int = 0
    no_reference: int = 0

    @property
    def by_reason(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in self.trades:
            out[t.reason] = out.get(t.reason, 0) + 1
        return dict(sorted(out.items()))


def simulate(bars: Sequence[Kline], funding: Sequence[FundingRate], variant: S6Variant, start_ms: int, end_ms: int,
             costs: S6Costs = BASE_COSTS, reference: Reference | None = None,
             ticks: dict[str, float] | None = None) -> Simulation:
    """All trades of one instrument and one section [start_ms, end_ms) by the rules of 4.1."""
    ref = reference or compute_reference(bars)
    ticks = ticks if ticks is not None else empirical_ticks(bars)
    normalized, _ = normalize_funding(funding)
    f_times = [f.time for f in normalized]
    f_units = [f.rate for f in normalized]
    sim = Simulation()
    i = bisect_left([b.open_time for b in bars], start_ms)
    locked_until = -1  # bar index
    while i < len(bars) and bars[i].open_time < end_ms:
        if i < locked_until or ref.vwap[i] is None or ref.sigma30[i] is None or i == 0:
            if i >= locked_until and (i == 0 or ref.vwap[i] is None):
                sim.no_reference += 1
            i += 1
            continue
        tick = ticks.get(month_key(bars[i].open_time), 0.0)
        b = bars[i]
        fills = []
        for side in (LONG, SHORT):
            limit = limit_price(ref.vwap[i], ref.sigma30[i], variant.k, side, tick)
            if crosses(bars, i, limit, side):
                sim.skipped_cross += 1
                continue
            if traded_through(b, limit, side, margin(limit, tick, costs)):
                fills.append((side, limit))
        if not fills:
            i += 1
            continue
        if len(fills) == 2:
            # side unknown from candles: booked as a loser of -(1 + c_l) R (section 4.1)
            loss_r = -(1 + (costs.maker_fee + costs.taker_fee + costs.stop_slippage) / STOP_FRACTION)
            fee = (costs.maker_fee + costs.taker_fee) * NOMINAL
            sim.trades.append(Trade(0, i, b.open_time, fills[0][1], i, b.open_time, fills[0][1], "both", False,
                                    fee, 0.0, loss_r))
            locked_until = i + 1 + LOCK_AFTER_LOSS
            i += 1
            continue
        side, fill = fills[0]
        exit_index, exit_fill, reason, ambiguous, exit_fee_rate = _exit(bars, i, side, fill, variant, tick, costs, end_ms)
        q = NOMINAL / fill
        fees = costs.maker_fee * NOMINAL + exit_fee_rate * q * exit_fill
        fund = _funding_cost(f_times, f_units, b.open_time, bars[exit_index].open_time, side, costs)
        net = side * (exit_fill - fill) * q - fees - fund
        sim.trades.append(Trade(side, i, b.open_time, fill, exit_index, bars[exit_index].open_time, exit_fill, reason,
                                ambiguous, fees, fund, net / (STOP_FRACTION * NOMINAL)))
        lock = LOCK_AFTER_LOSS if reason in ("stop", "gap") else LOCK_AFTER_EXIT
        locked_until = exit_index + 1 + lock
        i = exit_index + 1
    return sim


# ----------------------------------------------------------------------------- gate count (6.1)


@dataclass(slots=True)
class FillCount:
    fills: int = 0  # with the conservative locks (every trade reaches the time stop)
    both: int = 0
    fills_unlocked: int = 0  # upper bound: every qualifying bar, no open-trade constraint
    skipped_cross: int = 0
    no_reference: int = 0
    fill_days: set = field(default_factory=set)
    fills_by_month: dict = field(default_factory=dict)
    fills_by_side: dict = field(default_factory=lambda: {"long": 0, "short": 0})


@dataclass(frozen=True, slots=True)
class Fill:
    """One bar in which the trade-through rule is met (section 6.1); `counted` is False while a lock is active."""

    index: int
    open_time: int
    sides: tuple[int, ...]  # (LONG,), (SHORT,) or (LONG, SHORT) = both
    limits: tuple[float, ...]  # one per side
    margins: tuple[float, ...]  # trade-through margin delta per side, absolute price
    counted: bool

    @property
    def both(self) -> bool:
        return len(self.sides) == 2


def list_fills(bars: Sequence[Kline], variant: S6Variant, start_ms: int, end_ms: int, costs: S6Costs = BASE_COSTS,
               reference: Reference | None = None, ticks: dict[str, float] | None = None) -> tuple[list[Fill], int, int]:
    """Outcome-blind fill events plus (skipped_cross, no_reference); reads prices up to the fill, never an exit."""
    ref = reference or compute_reference(bars)
    ticks = ticks if ticks is not None else empirical_ticks(bars)
    fills: list[Fill] = []
    skipped_cross = no_reference = 0
    i = bisect_left([b.open_time for b in bars], start_ms)
    locked_until = -1
    while i < len(bars) and bars[i].open_time < end_ms:
        if i == 0 or ref.vwap[i] is None:
            if i >= locked_until:
                no_reference += 1
            i += 1
            continue
        tick = ticks.get(month_key(bars[i].open_time), 0.0)
        b = bars[i]
        sides: list[int] = []
        limits: list[float] = []
        margins: list[float] = []
        for side in (LONG, SHORT):
            limit = limit_price(ref.vwap[i], ref.sigma30[i], variant.k, side, tick)
            if crosses(bars, i, limit, side):
                if i >= locked_until:
                    skipped_cross += 1
                continue
            delta = margin(limit, tick, costs)
            if traded_through(b, limit, side, delta):
                sides.append(side)
                limits.append(limit)
                margins.append(delta)
        if sides:
            counted = i >= locked_until
            fills.append(Fill(i, b.open_time, tuple(sides), tuple(limits), tuple(margins), counted))
            if counted:
                locked_until = i + 1 + LOCK_AFTER_LOSS if len(sides) == 2 else i + TIME_STOP_BARS + LOCK_AFTER_EXIT
        i += 1
    return fills, skipped_cross, no_reference


def count_fills(bars: Sequence[Kline], variant: S6Variant, start_ms: int, end_ms: int, costs: S6Costs = BASE_COSTS,
                reference: Reference | None = None, ticks: dict[str, float] | None = None) -> FillCount:
    """Outcome-blind: reads prices up to the fill, never a stop or target (section 6.1).

    Locks assume every trade reaches the time stop (240 bars + 5); `both` locks like a loss (1 + 30 bars).
    """
    fills, skipped_cross, no_reference = list_fills(bars, variant, start_ms, end_ms, costs, reference, ticks)
    count = FillCount(skipped_cross=skipped_cross, no_reference=no_reference)
    for f in fills:
        count.fills_unlocked += 1
        if not f.counted:
            continue
        count.fills += 1
        count.fill_days.add(day_key(f.open_time))
        key = month_key(f.open_time)
        count.fills_by_month[key] = count.fills_by_month.get(key, 0) + 1
        if f.both:
            count.both += 1
        else:
            count.fills_by_side["long" if f.sides[0] == LONG else "short"] += 1
    return count
