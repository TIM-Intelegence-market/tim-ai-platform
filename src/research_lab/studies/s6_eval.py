"""Study S6, sections 5, 6 and 7: metrics, the judgement K1-K10 and the baselines.

Everything here works on the frozen ``Trade`` records of ``hypotheses/s6.py`` and never
loads data itself. Clopper-Pearson is exact (bisection on the binomial tail), the design
effect is the day-cluster estimator of section 5.2, and baseline A is the volatility-matched
pool method of section 7 (deterministic for a seed).
"""
from __future__ import annotations

import math
import operator
import random
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.hypotheses import s6
from src.research_lab.hypotheses.s6 import LONG, SHORT, NOMINAL, STOP_FRACTION, Reference, S6Costs, S6Variant, Trade
from src.research_lab.stats.inference import Window, walk_forward_windows

N_MIN_EFFECTIVE = 160
HIT_POINT = 0.95
HIT_LOWER = 0.90
MAX_DRAWDOWN_R = 20.0
HOLM_M = 60
POOL_PER_DECILE = 2_000
BASELINE_RUNS = 10_000
BASELINE_SEED = 20261030
LAMBDA_MIN = 0.05
# Protocol cost model (section 5.3, reported only): every leg taker fee + slippage = 0.08 %, stops as before.
PROTOCOL_COSTS = S6Costs(maker_fee=0.0008)
MIN_TRADES_TRAIN = 500
N_MIN_VALIDATION = 183
P_TRAIN = 0.10
P_VALIDATION = 0.05
PF_VALIDATION = 1.1
YEAR_MIN_TRADES = 30
YEAR_SHARE = 0.60
WALK_FORWARD_HIT = 0.90
GRID_K = (2.0, 3.0)
GRID_T = (0.15, 0.20, 0.25)


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

    fill_deciles: (pool key, decile) per trade of the variant; pools: pool per key. Every run draws one pool
    trade per fill (with replacement) from the fill's decile; the draws are made fill by fill, which gives the
    same distribution as run by run and is deterministic for the seed."""
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
    sums = [0.0] * runs
    for rs in choices:
        sums = list(map(operator.add, sums, rng.choices(rs, k=runs)))
    n = len(choices)
    at_least = sum(1 for total in sums if total / n >= observed_expectancy)
    return (1 + at_least) / (runs + 1), sum(sums) / (runs * n)


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


# ----------------------------------------------------------------------------- re-pricing, gap alternative (5.3, A5)


def reprice(trade: Trade, costs_from: S6Costs, costs_to: S6Costs) -> Trade:
    """The same fills under another fee schedule (protocol cost model, reported only). Exit prices keep the
    slippage of the simulated run; only the fee legs change."""
    if trade.reason == "both":
        loss_r = -(1 + (costs_to.maker_fee + costs_to.taker_fee + costs_to.stop_slippage) / STOP_FRACTION)
        fee = (costs_to.maker_fee + costs_to.taker_fee) * NOMINAL
        return Trade(trade.side, trade.entry_index, trade.entry_time, trade.entry_fill, trade.exit_index, trade.exit_time,
                     trade.exit_fill, trade.reason, trade.ambiguous, fee, trade.funding, loss_r)
    q = NOMINAL / trade.entry_fill
    exit_rate_from = costs_from.maker_fee if trade.reason == "target" else costs_from.taker_fee
    exit_rate_to = costs_to.maker_fee if trade.reason == "target" else costs_to.taker_fee
    gross = trade.net_r * STOP_FRACTION * NOMINAL + trade.fees + trade.funding
    fees = costs_to.maker_fee * NOMINAL + exit_rate_to * q * trade.exit_fill
    assert abs(trade.fees - (costs_from.maker_fee * NOMINAL + exit_rate_from * q * trade.exit_fill)) < 1e-6
    net = gross - fees - trade.funding
    return Trade(trade.side, trade.entry_index, trade.entry_time, trade.entry_fill, trade.exit_index, trade.exit_time,
                 trade.exit_fill, trade.reason, trade.ambiguous, fees, trade.funding, net / (STOP_FRACTION * NOMINAL))


def gap_alternative(trades: Sequence[Trade], bars: Sequence[Kline], costs: S6Costs) -> list[Trade]:
    """A5: `gap` trades closed on the first bar after the gap at min(stop, open) with stop slippage instead of the
    last bar before it. Other trades unchanged."""
    out = []
    for t in trades:
        if t.reason != "gap" or t.exit_index + 1 >= len(bars):
            out.append(t)
            continue
        nxt = bars[t.exit_index + 1]
        stop = t.entry_fill * (1 - STOP_FRACTION * t.side)
        price = (min(stop, nxt.open) if t.side == LONG else max(stop, nxt.open)) * (1 - costs.stop_slippage * t.side)
        q = NOMINAL / t.entry_fill
        fees = costs.maker_fee * NOMINAL + costs.taker_fee * q * price
        net = t.side * (price - t.entry_fill) * q - fees - t.funding
        out.append(Trade(t.side, t.entry_index, t.entry_time, t.entry_fill, t.exit_index + 1, nxt.open_time, price, "gap_after",
                         t.ambiguous, fees, t.funding, net / (STOP_FRACTION * NOMINAL)))
    return out


# ----------------------------------------------------------------------------- training, validation, robustness (5.1, 5.4)


def training_verdict(s: Summary, p_baseline: float) -> dict:
    reasons = []
    if s.expectancy <= 0:
        reasons.append("E[R] <= 0")
    if s.n < MIN_TRADES_TRAIN:
        reasons.append(f"n < {MIN_TRADES_TRAIN}")
    if s.n_eff < N_MIN_EFFECTIVE:
        reasons.append(f"n_eff < {N_MIN_EFFECTIVE}")
    if p_baseline >= P_TRAIN:
        reasons.append(f"p >= {P_TRAIN}")
    if s.hit_rate < HIT_POINT:
        reasons.append("hit rate < 95 %")
    if s.hit_lower_bound < HIT_LOWER:
        reasons.append("lower bound < 90 %")
    return {"pass": not reasons, "reasons": reasons}


def validation_verdict(s: Summary, p_baseline: float, robustness: Mapping[str, bool]) -> dict:
    reasons = []
    if s.n_eff < N_MIN_VALIDATION:
        reasons.append(f"n_eff < {N_MIN_VALIDATION}")
    if s.expectancy <= 0:
        reasons.append("E[R] <= 0")
    if p_baseline >= P_VALIDATION:
        reasons.append(f"p >= {P_VALIDATION}")
    if s.profit_factor <= PF_VALIDATION:
        reasons.append(f"profit factor <= {PF_VALIDATION}")
    if s.max_drawdown > MAX_DRAWDOWN_R:
        reasons.append(f"drawdown > {MAX_DRAWDOWN_R:.0f} R")
    if s.hit_rate < HIT_POINT:
        reasons.append("hit rate < 95 %")
    if s.hit_lower_bound < HIT_LOWER:
        reasons.append("lower bound < 90 %")
    reasons.extend(f"robustness: {name}" for name, ok in robustness.items() if not ok)
    return {"pass": not reasons, "reasons": reasons}


def year_stability(trades: Sequence[Trade]) -> dict:
    """E[R] > 0 in at least 60 % of the years with >= 30 trades (training + validation)."""
    by_year: dict[str, list[float]] = {}
    for t in trades:
        by_year.setdefault(s6.day_key(t.entry_time)[:4], []).append(t.net_r)
    rows = {y: {"n": len(rs), "expectancy": sum(rs) / len(rs)} for y, rs in sorted(by_year.items())}
    counted = [r for r in rows.values() if r["n"] >= YEAR_MIN_TRADES]
    positive = sum(1 for r in counted if r["expectancy"] > 0)
    ok = bool(counted) and positive >= YEAR_SHARE * len(counted) - 1e-9
    return {"pass": ok, "years": rows, "years_counted": len(counted), "years_positive": positive}


def walk_forward(variant_trades: Mapping[str, Sequence[Trade]], start_ms: int, end_ms: int, *, fit_months: int = 24,
                 test_months: int = 6) -> dict:
    """Choose the best of all variants per fit window by E[R] of trades closed by the fit end (known_at), measure it
    on the trades entered in the following test window; chained E[R] > 0 and chained hit rate >= 90 % (section 5.4)."""
    windows: Sequence[Window] = walk_forward_windows(start_ms, end_ms, fit_months=fit_months, test_months=test_months)
    chained: list[float] = []
    chosen = []
    for w in windows:
        def fit_mean(variant: str) -> float:
            rs = [t.net_r for t in variant_trades[variant] if w.fit_start <= t.entry_time < w.fit_end and t.exit_time <= w.fit_end]
            return sum(rs) / len(rs) if rs else -math.inf

        best = max(sorted(variant_trades), key=fit_mean)
        chosen.append(best)
        chained.extend(t.net_r for t in variant_trades[best] if w.fit_end <= t.entry_time < w.test_end)
    expectancy = sum(chained) / len(chained) if chained else 0.0
    hit = sum(1 for r in chained if r > 0) / len(chained) if chained else 0.0
    return {"pass": bool(chained) and expectancy > 0 and hit >= WALK_FORWARD_HIT, "windows": len(windows), "chosen": chosen,
            "trades": len(chained), "expectancy": expectancy, "hit_rate": hit}


def neighbours_positive(variant: S6Variant, train_expectancy: Mapping[str, float]) -> dict:
    """E[R] > 0 in training for every direct grid neighbour (same T other k; same k adjacent T)."""
    names = {(v.k, v.target_r): v.variant_id for v in s6.S6_VARIANTS}
    neighbours = [names[(k, variant.target_r)] for k in GRID_K if k != variant.k]
    ti = GRID_T.index(variant.target_r)
    neighbours += [names[(variant.k, GRID_T[j])] for j in (ti - 1, ti + 1) if 0 <= j < len(GRID_T)]
    values = {n: train_expectancy.get(n, -math.inf) for n in neighbours}
    return {"pass": all(v > 0 for v in values.values()), "neighbours": values}


def select_candidates(validation_expectancy: Mapping[str, float], passed: Sequence[str]) -> list[str]:
    """At most two candidates, at most one per target, highest validation E[R] first (section 5.1 step 3)."""
    chosen: list[str] = []
    used_targets: set[float] = set()
    by_id = {v.variant_id: v for v in s6.S6_VARIANTS}
    for vid in sorted(passed, key=lambda v: (-validation_expectancy[v], v)):
        t = by_id[vid].target_r
        if t in used_targets or len(chosen) >= 2:
            continue
        chosen.append(vid)
        used_targets.add(t)
    return chosen
