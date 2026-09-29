"""Benchmark against random entries (protocol section 7.1).

Each random run draws as many trades as the variant made. Entry bars are drawn
uniformly from the allowed bars of the same period. Side, stop distance (in ATR
units), target in R and holding time are drawn jointly from the variant's real
trades. Random trades may overlap. Exits and costs follow the engine exactly.

For runtime, random trades are simulated once into a pool of at least 50 times
the variant's trade count, and each run draws its trades from that pool.
"""
from __future__ import annotations

import bisect
import random
from collections.abc import Sequence

from src.research_lab.backtest.engine import History, Trade, _funding_cost, exit_on_bar
from src.research_lab.backtest.indicators import atr
from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.protocol import BASE_COSTS, CostModel

ATR_PERIOD = 14
POOL_FACTOR = 50
MIN_POOL = 5_000


def atr_series(bars: Sequence[Kline], period: int = ATR_PERIOD) -> list[float | None]:
    return [atr(History(bars, t), period) for t in range(len(bars))]


def atr_at_signal(history: History) -> float | None:
    """Pass to run_backtest so trades record their stop distance in ATR units."""
    return atr(history, ATR_PERIOD)


def simulate_trade(
    bars: Sequence[Kline],
    signal_index: int,
    side: int,
    risk: float,
    target_r: float | None,
    max_bars: int,
    interval_ms: int,
    costs: CostModel,
    funding: Sequence[FundingRate],
    funding_times: list[int],
) -> float | None:
    """Net R of one trade entered at the open after signal_index, or None if no entry is possible."""
    first = signal_index + 1
    if first >= len(bars) or bars[first].open_time - bars[signal_index].open_time != interval_ms or risk <= 0:
        return None
    entry = bars[first].open * (1 + side * costs.slippage)
    stop = entry - side * risk
    target = None if target_r is None else entry + side * target_r * risk
    exit_raw = slip = moment = None
    t = first
    while t < len(bars):
        bar = bars[t]
        if t > first and bar.open_time - bars[t - 1].open_time != interval_ms:
            exit_raw, slip, moment = bars[t - 1].close, costs.slippage, bars[t - 1].close_time + 1
            break
        hit = exit_on_bar(bar, side, stop, target)
        if hit is not None:
            exit_raw, reason, moment = hit
            slip = costs.stop_slippage if reason.startswith("stop") else costs.slippage
            break
        if t - first + 1 >= max_bars:
            exit_raw, slip, moment = bar.close, costs.slippage, bar.close_time + 1
            break
        t += 1
    if exit_raw is None:
        last = bars[-1]
        exit_raw, slip, moment = last.close, costs.slippage, last.close_time + 1
    exit_price = exit_raw * (1 - side * slip)
    fees = costs.fee * (entry + exit_price)
    fund = _funding_cost(funding, funding_times, side, entry, bars[first].open_time, moment, costs)
    return (side * (exit_price - entry) - fees - fund) / risk


def random_entry_pvalue(
    bars: Sequence[Kline],
    trades: Sequence[Trade],
    interval_ms: int,
    *,
    runs: int,
    seed: int,
    costs: CostModel = BASE_COSTS,
    funding: Sequence[FundingRate] = (),
    start_ms: int | None = None,
    end_ms: int | None = None,
    atr_values: Sequence[float | None] | None = None,
) -> float:
    """One-sided p-value: share of random runs whose mean R is at least the variant's."""
    if not trades:
        return 1.0
    if any(trade.stop_atr is None for trade in trades):
        raise ValueError("trades need stop_atr; run the backtest with atr_at_signal")
    atr_values = atr_series(bars) if atr_values is None else atr_values
    templates = [(t.side, t.stop_atr, t.target_r, t.bars_held) for t in trades]
    lo = 0 if start_ms is None else bisect.bisect_left([b.open_time for b in bars], start_ms)
    candidates = [
        i for i in range(lo, len(bars) - 1)
        if atr_values[i] and (end_ms is None or bars[i].open_time < end_ms)
    ]
    if not candidates:
        raise ValueError("no bars available for random entries")
    observed = sum(t.r for t in trades) / len(trades)
    funding_times = [f.time for f in funding]
    rng = random.Random(seed)
    n = len(trades)
    # Monte Carlo pool: simulate a large set of uniformly random trades once, then
    # build each run from n draws of that pool. With the pool far larger than n
    # this matches drawing fresh random trades per run, at a fraction of the cost.
    pool_size = min(runs * n, max(POOL_FACTOR * n, MIN_POOL))
    pool: list[float] = []
    attempts = 0
    while len(pool) < pool_size:
        attempts += 1
        if attempts > 20 * pool_size:
            raise ValueError("random entries cannot be placed in this period")
        index = rng.choice(candidates)
        side, stop_atr, target_r, held = rng.choice(templates)
        result = simulate_trade(bars, index, side, stop_atr * atr_values[index], target_r, held, interval_ms, costs, funding, funding_times)
        if result is not None:
            pool.append(result)
    threshold = observed * n
    at_least = 0
    for _ in range(runs):
        if sum(rng.choices(pool, k=n)) >= threshold:
            at_least += 1
    return (1 + at_least) / (1 + runs)
