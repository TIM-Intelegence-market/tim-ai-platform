"""Study S14, section 6: random entries at the same hours with the same exit.

Protocol 7.1 with the pool method of R4(a). A random trade starts at an hour of the same variant,
pair and section where a real entry could have been decided (``Signals.possible``: full gap-free
window, beta > 0, filter where the variant has one, next hour present). Its side is drawn from the
real trades of that pair and section; alpha, beta and sigma are frozen at that hour, and from there
it follows exactly ``s14.simulate_trade`` (same exit, fees, slippage and funding). Like protocol 3.2,
a random trade counts only if its exit was fixed by the section end; otherwise it is redrawn.

Pooled over pairs: every run draws as many random trades per pair as the variant made there. The
p-value uses ``s13_random.pvalue_from_pools`` (one generator, pairs in sorted order).
"""
from __future__ import annotations

import bisect
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from src.research_lab.data.parse import FundingRate
from src.research_lab.hypotheses import s14
from src.research_lab.protocol import BASE_COSTS, CostModel
from src.research_lab.stats.inference import FORCED_CLOSE
from src.research_lab.studies.s13_random import (
    RandomResult,
    pool_size,
    pvalue_from_pools,
)

RUNS = 10_000
SEED = s14.SEED


@dataclass(slots=True)
class PairData:
    """One pair and variant with its funding; ``signals`` caches the fits of the candidate hours."""

    pair: s14.PairSeries
    signals: s14.Signals
    y_funding: Sequence[FundingRate] = ()
    x_funding: Sequence[FundingRate] = ()
    funding_times: tuple[list[int], list[int]] = field(init=False)

    def __post_init__(self) -> None:
        self.funding_times = ([r.time for r in self.y_funding], [r.time for r in self.x_funding])


def candidates(data: PairData, start_ms: int, end_ms: int) -> list[tuple[int, s14.Fit]]:
    """(hour index, fit) of every hour in [start_ms, end_ms) where an entry could be decided."""
    times = data.pair.times
    lo, hi = bisect.bisect_left(times, start_ms), bisect.bisect_left(times, end_ms)
    out = []
    for t in range(lo, hi):
        f = data.signals.possible(t)
        if f is not None:
            out.append((t, f))
        data.signals._fits.pop(t, None)  # memory: the fit is kept in the list
    return out


def simulate(data: PairData, t: int, fit: s14.Fit, side: int, costs: CostModel = BASE_COSTS) -> s14.PairTrade | None:
    z = fit.z(data.signals.ly[t], data.signals.lx[t])
    return s14.simulate_trade(data.pair, data.signals, s14.Entry(t, side, z, fit), costs, data.y_funding, data.x_funding,
                              data.funding_times)


def draw_pool(data: PairData, sides: Sequence[int], start_ms: int, end_ms: int, size: int, rng: random.Random,
              costs: CostModel = BASE_COSTS, name: str = "",
              pool_candidates: Sequence[tuple[int, s14.Fit]] | None = None) -> list[s14.PairTrade]:
    """``size`` random trades: hour uniform over the candidates, side drawn from ``sides``.
    A trade that cannot open, or whose exit is not fixed by ``end_ms``, is redrawn."""
    cands = list(pool_candidates) if pool_candidates is not None else candidates(data, start_ms, end_ms)
    if not cands or not sides:
        raise ValueError(f"{name}: no candidate hours or sides for random entries")
    pool: list[s14.PairTrade] = []
    attempts = 0
    while len(pool) < size:
        attempts += 1
        if attempts > 20 * size:
            raise ValueError(f"{name}: random entries cannot be placed in this section")
        t, fit = rng.choice(cands)
        sim = simulate(data, t, fit, rng.choice(sides), costs)
        if sim is None or sim.exit_time > end_ms or sim.reason == FORCED_CLOSE:
            continue
        pool.append(sim)
    return pool


def random_pvalue(pairs: Mapping[str, PairData], trades: Mapping[str, Sequence[s14.PairTrade]], start_ms: int,
                  end_ms: int, *, runs: int = RUNS, seed: int = SEED, costs: CostModel = BASE_COSTS) -> RandomResult:
    """One-sided p-value of the pooled mean R against random entries (section 6).

    ``trades``: the variant's trades of this section per pair, already cut by protocol 3.2."""
    counts = {name: len(ts) for name, ts in trades.items() if ts}
    if not counts:
        return RandomResult(1.0, 0.0, 0.0, {}, {})
    observed_sum = sum(t.r for ts in trades.values() for t in ts)
    rng = random.Random(seed)
    pools: dict[str, list[float]] = {}
    for name in sorted(counts):
        sides = [t.side for t in trades[name]]
        pool = draw_pool(pairs[name], sides, start_ms, end_ms, pool_size(counts[name], runs), rng, costs, name)
        pools[name] = [sim.r for sim in pool]
    return pvalue_from_pools(pools, counts, observed_sum, runs, rng)
