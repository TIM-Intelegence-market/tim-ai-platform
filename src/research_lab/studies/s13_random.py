"""Study S13, section 6: random entries at the same check bars with the same exit.

Protocol 7.1 with the pool method of R4(a). A random trade is decided on a check bar of the
same variant, instrument and section where a real entry could have been decided (entry
allowed, band and catastrophe stop computable). Its side is drawn from the real trades of that
instrument and section. From there it follows exactly the S13 exit: catastrophe stop on every
bar, trailing stop max/min(band, VWAP) at the check bars with the exit at the next open, flat at
the session end. Fill prices, R unit, fees, slippage and funding are the engine's.

``simulate_trade`` repeats the engine (``backtest.engine._Runner``) for one position; the tests
check that it gives the engine's result for the real signals and for random ones. Like protocol
3.2, a random trade counts only if its exit was fixed by the section end; otherwise it is redrawn.

Pooled over instruments: every run draws as many random trades per instrument as the variant
made there, so the mix of BTC, ETH and SOL is the real one.
"""
from __future__ import annotations

import bisect
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.research_lab.backtest.engine import Trade, _funding_cost, exit_on_bar
from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.hypotheses import s13
from src.research_lab.protocol import BASE_COSTS, CostModel
from src.research_lab.stats.inference import FORCED_CLOSE
from src.research_lab.stats.random_entry import MIN_POOL, POOL_FACTOR

RUNS = 10_000
SEED = s13.SEED


@dataclass(frozen=True, slots=True)
class Instrument:
    bars: Sequence[Kline]
    table: s13.NoiseTable
    funding: Sequence[FundingRate] = ()


@dataclass(frozen=True, slots=True)
class SimTrade:
    signal_time: int
    exit_time: int
    side: int
    reason: str
    r: float


@dataclass(frozen=True, slots=True)
class RandomResult:
    p: float
    observed: float  # mean R of the real trades
    random_mean: float  # mean R over all pool trades
    trades: dict[str, int]  # real trades per instrument
    pool: dict[str, int]  # pool size per instrument


def entry_candidates(inst: Instrument, start_ms: int, end_ms: int) -> list[int]:
    """Bar indices of the check bars in [start_ms, end_ms) where an entry could be decided."""
    times = [b.open_time for b in inst.bars]
    out = []
    for t, check in inst.table.checks.items():
        if not start_ms <= t < end_ms or not s13.entry_possible(check):
            continue
        i = bisect.bisect_left(times, t)
        if i + 1 < len(times) and times[i] == t:
            out.append(i)
    return sorted(out)


def simulate_trade(inst: Instrument, signal_index: int, side: int, costs: CostModel = BASE_COSTS,
                   funding_times: list[int] | None = None) -> SimTrade | None:
    """The engine's trade for an S13 signal on bar ``signal_index``, or None where the engine
    would count the signal as invalid (no contiguous next bar, entry at or beyond the stop)."""
    bars, table = inst.bars, inst.table
    signal_bar = bars[signal_index]
    check = table.check(signal_bar.open_time)
    if check is None or not s13.entry_possible(check):
        return None
    assert check.risk is not None
    first = signal_index + 1
    if first >= len(bars) or bars[first].open_time - signal_bar.open_time != s13.INTERVAL_MS:
        return None
    stop = signal_bar.close - side * check.risk
    entry = bars[first].open * (1 + side * costs.slippage)
    if (entry - stop) * side <= 0 or (bars[first].open - stop) * side <= 0:
        return None
    exit_next = False
    t = first
    while True:
        if t >= len(bars):
            last = bars[-1]
            raw, reason, moment, slip = last.close, FORCED_CLOSE, last.close_time + 1, costs.slippage
            break
        bar = bars[t]
        if t > first and bar.open_time - bars[t - 1].open_time != s13.INTERVAL_MS:
            prev = bars[t - 1]
            raw, reason, moment, slip = prev.close, "gap", prev.close_time + 1, costs.slippage
            break
        if exit_next:
            raw, reason, moment, slip = bar.open, "rule", bar.open_time, costs.slippage
            break
        hit = exit_on_bar(bar, side, stop, None)
        if hit is not None:
            raw, reason, moment = hit
            slip = costs.stop_slippage if reason.startswith("stop") else costs.slippage
            break
        at = table.check(bar.open_time)
        if at is not None and s13.exits(at, side, bar.close):
            exit_next = True
        t += 1
    exit_price = raw * (1 - side * slip)
    risk = abs(entry - stop)
    fees = costs.fee * (entry + exit_price)
    times = funding_times if funding_times is not None else [f.time for f in inst.funding]
    fund = _funding_cost(inst.funding, times, side, entry, bars[first].open_time, moment, costs)
    return SimTrade(signal_bar.open_time, moment, side, reason, (side * (exit_price - entry) - fees - fund) / risk)


def draw_pool(inst: Instrument, sides: Sequence[int], start_ms: int, end_ms: int, size: int, rng: random.Random,
              costs: CostModel = BASE_COSTS, name: str = "") -> list[SimTrade]:
    """``size`` random trades: check bar uniform over the candidates, side drawn from ``sides``.
    A trade the engine would not open, or whose exit is not fixed by ``end_ms``, is redrawn."""
    candidates = entry_candidates(inst, start_ms, end_ms)
    if not candidates or not sides:
        raise ValueError(f"{name}: no check bars or sides for random entries")
    funding_times = [f.time for f in inst.funding]
    pool: list[SimTrade] = []
    attempts = 0
    while len(pool) < size:
        attempts += 1
        if attempts > 20 * size:
            raise ValueError(f"{name}: random entries cannot be placed in this section")
        sim = simulate_trade(inst, rng.choice(candidates), rng.choice(sides), costs, funding_times)
        if sim is None or sim.exit_time > end_ms or sim.reason == FORCED_CLOSE:
            continue
        pool.append(sim)
    return pool


def random_pvalue(instruments: Mapping[str, Instrument], trades: Mapping[str, Sequence[Trade]], start_ms: int,
                  end_ms: int, *, runs: int = RUNS, seed: int = SEED, costs: CostModel = BASE_COSTS) -> RandomResult:
    """One-sided p-value of the pooled mean R against random entries (section 6).

    ``trades``: the variant's trades of this section per instrument, already cut by protocol 3.2."""
    counts = {sym: len(ts) for sym, ts in trades.items() if ts}
    total = sum(counts.values())
    if not total:
        return RandomResult(1.0, 0.0, 0.0, {}, {})
    observed_sum = sum(t.r for ts in trades.values() for t in ts)
    rng = random.Random(seed)
    pools: dict[str, list[float]] = {}
    for sym in sorted(counts):
        n = counts[sym]
        size = min(runs * n, max(POOL_FACTOR * n, MIN_POOL))
        sides = [t.side for t in trades[sym]]
        pools[sym] = [sim.r for sim in draw_pool(instruments[sym], sides, start_ms, end_ms, size, rng, costs, sym)]
    at_least = 0
    for _ in range(runs):
        if sum(sum(rng.choices(pools[sym], k=counts[sym])) for sym in sorted(counts)) >= observed_sum:
            at_least += 1
    all_pool = [r for p in pools.values() for r in p]
    return RandomResult((1 + at_least) / (1 + runs), observed_sum / total, sum(all_pool) / len(all_pool),
                        counts, {sym: len(p) for sym, p in pools.items()})
