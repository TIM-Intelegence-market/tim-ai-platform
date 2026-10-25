"""Study S6, sections 5, 6 and 7: metrics, the judgement K1-K10 and the baselines.

Everything here works on the frozen ``Trade`` records of ``hypotheses/s6.py`` and never
loads data itself. Clopper-Pearson is exact (bisection on the binomial tail), the design
effect is the day-cluster estimator of section 5.2, and baseline A is the volatility-matched
pool method of section 7 (deterministic for a seed).
"""
from __future__ import annotations

import math
import random
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.hypotheses import s6
from src.research_lab.hypotheses.s6 import LONG, SHORT, NOMINAL, STOP_FRACTION, Reference, S6Costs, S6Variant, Trade

N_MIN_EFFECTIVE = 160
HIT_POINT = 0.95
HIT_LOWER = 0.90
MAX_DRAWDOWN_R = 20.0
HOLM_M = 60
POOL_PER_DECILE = 2_000
BASELINE_RUNS = 10_000
BASELINE_SEED = 20261030
LAMBDA_MIN = 0.05


# ----------------------------------------------------------------------------- statistics


def binom_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p), summed in log space."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    total = 0.0
    for i in range(k, n + 1):
        total += math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p))
    return min(total, 1.0)


def clopper_pearson_lower(successes: int, n: int, alpha: float = 0.05) -> float:
    """One-sided (1 - alpha) lower bound: largest p with P(X >= successes | p) <= alpha... exact by bisection."""
    if n <= 0:
        return 0.0
    if successes <= 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if binom_tail(successes, n, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return lo


def design_effect(hits: Sequence[bool], clusters: Sequence[str]) -> float:
    """Variance of the cluster means relative to the binomial variance (section 5.2); at least 1, 1 when p = 1."""
    n = len(hits)
    if n == 0:
        return 1.0
    p = sum(hits) / n
    if p in (0.0, 1.0):
        return 1.0
    groups: dict[str, list[bool]] = {}
    for h, c in zip(hits, clusters):
        groups.setdefault(c, []).append(h)
    if len(groups) < 2:
        return 1.0
    # D = n * Var(p_hat) / (p(1-p)), with Var(p_hat) estimated from independent clusters of unequal size
    total_var = sum(len(g) ** 2 * (sum(g) / len(g) - p) ** 2 for g in groups.values())
    var_p_hat = total_var / (n * n) * len(groups) / (len(groups) - 1)
    return max(1.0, n * var_p_hat / (p * (1 - p)))


def effective_counts(n: int, losers: int, d: float) -> tuple[int, int]:
    """n_eff = floor(n / D), losers_eff = ceil(losers / D) (section 5.2)."""
    return int(math.floor(n / d + 1e-9)), int(math.ceil(losers / d - 1e-9))


def max_drawdown_r(results: Sequence[float]) -> float:
    peak = cum = 0.0
    worst = 0.0
    for r in results:
        cum += r
        peak = max(peak, cum)
        worst = max(worst, peak - cum)
    return worst


# ----------------------------------------------------------------------------- summary and judgement


@dataclass(frozen=True, slots=True)
class Summary:
    n: int
    hits: int
    hit_rate: float
    expectancy: float
    profit_factor: float
    max_drawdown: float
    mean_loss: float
    worst_loss: float
    mean_win: float
    design_effect: float
    n_eff: int
    losers_eff: int
    hit_lower_bound: float
    by_reason: dict[str, int]
    by_side: dict[str, int]


def summarize(trades: Sequence[Trade], clusters: Sequence[str] | None = None) -> Summary:
    n = len(trades)
    if n == 0:
        return Summary(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, 0, 0.0, {}, {})
    results = [t.net_r for t in trades]
    hits = [t.hit for t in trades]
    wins = [r for r in results if r > 0]
    losses = [r for r in results if r <= 0]
    clusters = clusters if clusters is not None else [s6.day_key(t.entry_time) for t in trades]
    d = design_effect(hits, clusters)
    n_eff, losers_eff = effective_counts(n, len(losses), d)
    lower = clopper_pearson_lower(n_eff - losers_eff, n_eff) if n_eff > 0 else 0.0
    gross_loss = -sum(losses)
    by_reason: dict[str, int] = {}
    by_side = {"long": 0, "short": 0, "both": 0}
    for t in trades:
        by_reason[t.reason] = by_reason.get(t.reason, 0) + 1
        by_side["long" if t.side == LONG else "short" if t.side == SHORT else "both"] += 1
    return Summary(n, sum(hits), sum(hits) / n, sum(results) / n,
                   (sum(wins) / gross_loss) if gross_loss > 0 else math.inf, max_drawdown_r(results),
                   (sum(losses) / len(losses)) if losses else 0.0, min(results), (sum(wins) / len(wins)) if wins else 0.0,
                   d, n_eff, losers_eff, lower, dict(sorted(by_reason.items())), by_side)


def judge(trades_by_symbol: Mapping[str, Sequence[Trade]], stress_by_symbol: Mapping[str, Sequence[Trade]],
          baseline_p: float, holm_threshold: float, lam: float = LAMBDA_MIN) -> dict[str, dict]:
    """K1-K10 of section 5.2 on pooled holdout trades. Returns per criterion {"pass": bool, ...details}."""
    pooled = [t for ts in trades_by_symbol.values() for t in ts]
    s = summarize(pooled)
    out: dict[str, dict] = {}
    out["K1"] = {"pass": s.expectancy > 0, "expectancy": s.expectancy}
    out["K2"] = {"pass": baseline_p < holm_threshold, "p": baseline_p, "threshold": holm_threshold}
    out["K3"] = {"pass": s.n >= 200 and s.n_eff >= N_MIN_EFFECTIVE, "n": s.n, "n_eff": s.n_eff, "design_effect": s.design_effect}
    out["K4"] = {"pass": s.max_drawdown <= MAX_DRAWDOWN_R, "max_drawdown": s.max_drawdown}
    out["K5"] = {"pass": s.profit_factor > 1.0, "profit_factor": s.profit_factor}
    out["K6"] = {"pass": s.hit_rate >= HIT_POINT and s.hit_lower_bound >= HIT_LOWER, "hit_rate": s.hit_rate,
                 "lower_bound": s.hit_lower_bound, "n_eff": s.n_eff, "losers_eff": s.losers_eff}
    stressed = [t for ts in stress_by_symbol.values() for t in ts]
    stressed_after_haircut = fill_haircut(stressed, lam)
    ss = summarize(stressed_after_haircut)
    out["K7"] = {"pass": ss.n > 0 and ss.expectancy > 0, "expectancy_stress": ss.expectancy, "lambda": lam,
                 "removed": len(stressed) - len(stressed_after_haircut)}
    ambiguous = sum(1 for t in pooled if t.ambiguous or t.reason == "both")
    forced = sum(1 for t in pooled if t.reason in ("time", "gap", "section_end"))
    out["K8"] = {"pass": s.n > 0 and s.worst_loss >= -2.0 and s.mean_loss >= -1.2 and ambiguous <= 0.05 * s.n and forced <= 0.25 * s.n,
                 "worst_loss": s.worst_loss, "mean_loss": s.mean_loss, "ambiguous_share": ambiguous / s.n if s.n else 0.0,
                 "forced_share": forced / s.n if s.n else 0.0}
    required_win = 1.5 * (1 - s.hit_rate) / s.hit_rate * (-s.mean_loss) if s.hit_rate > 0 else math.inf
    out["K9"] = {"pass": s.mean_win >= required_win, "mean_win": s.mean_win, "required": required_win}
    shares = {sym: len(ts) / s.n if s.n else 0.0 for sym, ts in trades_by_symbol.items()}
    side_shares = {k: v / s.n if s.n else 0.0 for k, v in s.by_side.items() if k != "both"}
    out["K10"] = {"pass": s.n > 0 and all(v >= 0.15 for v in shares.values()) and all(v >= 0.25 for v in side_shares.values()),
                  "instrument_shares": shares, "side_shares": side_shares}
    verdict = "KEIN URTEIL" if not out["K3"]["pass"] else ("BESTANDEN (Holdout)" if all(v["pass"] for v in out.values()) else "NICHT BESTANDEN")
    out["verdict"] = {"pass": verdict == "BESTANDEN (Holdout)", "verdict": verdict}
    return out


def fill_haircut(trades: Sequence[Trade], lam: float) -> list[Trade]:
    """Stress fill haircut (section 5.3): drop the lambda * n trades with the highest R."""
    lam = max(lam, LAMBDA_MIN)
    drop = int(math.ceil(lam * len(trades) - 1e-9))
    if drop <= 0:
        return list(trades)
    ordered = sorted(trades, key=lambda t: t.net_r, reverse=True)
    return ordered[drop:]


# ----------------------------------------------------------------------------- baselines (section 7)


def random_entry_trade(bars: Sequence[Kline], i: int, side: int, variant: S6Variant, tick: float, costs: S6Costs,
                       end_ms: int, f_times: Sequence[int], f_units: Sequence[float]) -> Trade:
    """A baseline trade entered at the open of bar i with the variant's exits and the maker entry fee."""
    fill = bars[i].open
    exit_index, exit_fill, reason, ambiguous, exit_fee_rate = s6._exit(bars, i, side, fill, variant, tick, costs, end_ms)
    q = NOMINAL / fill
    fees = costs.maker_fee * NOMINAL + exit_fee_rate * q * exit_fill
    fund = s6._funding_cost(f_times, f_units, bars[i].open_time, bars[exit_index].open_time, side, costs)
    net = side * (exit_fill - fill) * q - fees - fund
    return Trade(side, i, bars[i].open_time, fill, exit_index, bars[exit_index].open_time, exit_fill, reason, ambiguous,
                 fees, fund, net / (STOP_FRACTION * NOMINAL))


def sigma_deciles(reference: Reference, bars: Sequence[Kline], start_ms: int, end_ms: int) -> list[float]:
    """Nine cut points of sigma30 over all minutes of the section with a reference."""
    values = sorted(reference.sigma30[i] for i in range(len(bars)) if start_ms <= bars[i].open_time < end_ms
                    and reference.sigma30[i] is not None)
    if not values:
        return []
    return [values[min(len(values) - 1, int(len(values) * q / 10))] for q in range(1, 10)]


def decile_of(sigma: float, cuts: Sequence[float]) -> int:
    return bisect_right(cuts, sigma)


@dataclass(slots=True)
class Pool:
    """Baseline A pool for one instrument and section: per decile, results of pre-drawn random-entry trades."""

    results: dict[int, list[float]]
    hit_rates: dict[int, float]


def build_pool(bars: Sequence[Kline], reference: Reference, funding: Sequence[FundingRate], variant: S6Variant,
               start_ms: int, end_ms: int, costs: S6Costs, ticks: Mapping[str, float], *, seed: int = BASELINE_SEED,
               per_decile: int = POOL_PER_DECILE, cuts: Sequence[float] | None = None) -> Pool:
    cuts = cuts if cuts is not None else sigma_deciles(reference, bars, start_ms, end_ms)
    candidates: dict[int, list[int]] = {d: [] for d in range(10)}
    for i in range(1, len(bars)):
        if start_ms <= bars[i].open_time < end_ms and reference.sigma30[i] is not None:
            candidates[decile_of(reference.sigma30[i], cuts)].append(i)
    normalized, _ = s6.normalize_funding(funding)
    f_times = [f.time for f in normalized]
    f_units = [f.rate for f in normalized]
    rng = random.Random(seed)
    results: dict[int, list[float]] = {}
    hit_rates: dict[int, float] = {}
    for d, idx in candidates.items():
        if not idx:
            continue
        draws = [rng.choice(idx) for _ in range(per_decile)]
        rs = []
        for i in draws:
            side = LONG if rng.random() < 0.5 else SHORT
            tick = ticks.get(s6.month_key(bars[i].open_time), 0.0)
            rs.append(random_entry_trade(bars, i, side, variant, tick, costs, end_ms, f_times, f_units).net_r)
        results[d] = rs
        hit_rates[d] = sum(1 for r in rs if r > 0) / len(rs)
    return Pool(results, hit_rates)


def baseline_a_pvalue(fill_deciles: Sequence[tuple[str, int]], pools: Mapping[str, Pool], observed_expectancy: float, *,
                      runs: int = BASELINE_RUNS, seed: int = BASELINE_SEED) -> tuple[float, float]:
    """p = (1 + runs with E[R] >= observed) / (runs + 1); also the mean baseline expectancy.

    fill_deciles: (pool key, decile) per trade of the variant; pools: pool per key."""
    rng = random.Random(seed + 1)
    choices = []
    for key, d in fill_deciles:
        pool = pools[key].results
        rs = pool.get(d) or next((v for v in pool.values() if v), None)
        if rs is None:
            raise ValueError(f"no pool trades for {key}")
        choices.append(rs)
    if not choices:
        return 1.0, 0.0
    at_least = 0
    total = 0.0
    n = len(choices)
    for _ in range(runs):
        s = sum(rng.choice(rs) for rs in choices)
        e = s / n
        total += e
        if e >= observed_expectancy:
            at_least += 1
    return (1 + at_least) / (runs + 1), total / runs


def mirrored_trades(bars: Sequence[Kline], trades: Sequence[Trade], variant: S6Variant, costs: S6Costs, end_ms: int,
                    ticks: Mapping[str, float], funding: Sequence[FundingRate]) -> list[Trade]:
    """Baseline B: the same fills in the opposite direction (section 7)."""
    normalized, _ = s6.normalize_funding(funding)
    f_times = [f.time for f in normalized]
    f_units = [f.rate for f in normalized]
    out = []
    for t in trades:
        if t.side == 0:
            continue
        side = -t.side
        tick = ticks.get(s6.month_key(t.entry_time), 0.0)
        exit_index, exit_fill, reason, ambiguous, exit_fee_rate = s6._exit(bars, t.entry_index, side, t.entry_fill, variant,
                                                                           tick, costs, end_ms)
        q = NOMINAL / t.entry_fill
        fees = costs.maker_fee * NOMINAL + exit_fee_rate * q * exit_fill
        fund = s6._funding_cost(f_times, f_units, t.entry_time, bars[exit_index].open_time, side, costs)
        net = side * (exit_fill - t.entry_fill) * q - fees - fund
        out.append(Trade(side, t.entry_index, t.entry_time, t.entry_fill, exit_index, bars[exit_index].open_time, exit_fill,
                         reason, ambiguous, fees, fund, net / (STOP_FRACTION * NOMINAL)))
    return out


def day_block_bootstrap(trades: Sequence[Trade], *, draws: int = BASELINE_RUNS, seed: int = BASELINE_SEED + 2) -> tuple[float, float]:
    """90 % band of E[R] from resampling whole days (section 7, reported only)."""
    days: dict[str, list[float]] = {}
    for t in trades:
        days.setdefault(s6.day_key(t.entry_time), []).append(t.net_r)
    keys = list(days)
    if not keys:
        return 0.0, 0.0
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        sample = [r for _ in keys for r in days[rng.choice(keys)]]
        means.append(sum(sample) / len(sample))
    means.sort()
    return means[int(0.05 * draws)], means[min(draws - 1, int(0.95 * draws))]
