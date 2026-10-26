"""Study S7, sections 5, 6 and 7: pooled metrics, the judgement K1-K10 and the baselines.

Everything here works on the engine's frozen ``Trade`` records (``run_backtest`` with
``gap_entry_as_loss=True`` and ``atr_at_signal``), pooled over the three instruments, and
never loads data itself. The hit-rate statistics use the ISO-week cluster across all
instruments (section 5.2); baseline A is protocol 7.1 (``stats/random_entry``) extended to
several instruments, A' draws comparison bars from the same ATR/price decile.
"""
from __future__ import annotations

import bisect
import math
import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.research_lab.backtest.engine import History, Trade
from src.research_lab.backtest.indicators import atr, sma_close
from src.research_lab.backtest.metrics import max_drawdown_r
from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.hypotheses import s7
from src.research_lab.protocol import BASE_COSTS, FAMILY_ALPHA, CostModel
from src.research_lab.stats.clustered import clopper_pearson_lower, design_effect, effective_counts
from src.research_lab.stats.inference import holm, neighbours_positive, walk_forward, walk_forward_windows, year_stability
from src.research_lab.stats.random_entry import simulate_trade_detail

HOLM_M = 60
MAX_DRAWDOWN_R = 20.0  # protocol K4: 20 % at 1 % risk per trade
HIT_MARGIN = 0.05  # reported with K6: point estimate against p* + 5 points (no criterion, section 2.1)
TARGET_SHORTFALL_R = 0.5  # K9: mean net R of the hits at least T - 0.5
MIN_TRADES = {"train": (200, 100), "validation": (100, 50), "holdout": (100, 60)}  # (trades, signal weeks)
EDGE_BARS = s7.TIME_STOP_BARS + 1  # random entries stay this many bars before the section end
P_TRAIN = 0.10
P_VALIDATION = 0.05
PF_VALIDATION = 1.1
YEAR_MIN_TRADES = 20
YEAR_SHARE = 0.60
BASELINE_RUNS = 10_000
SEED = s7.SEED
POOL_FACTOR = 50
MIN_POOL = 5_000
POOL_PER_DECILE = 2_000
GRID = {"N": s7.CHANNELS, "T": s7.TARGETS}
HIT_REASONS = ("target", "target_gap")
FORCED_REASONS = ("time", "gap")

TradesBySymbol = Mapping[str, Sequence[Trade]]


# ----------------------------------------------------------------------------- cost geometry (2.1)


def cost_r(stop_fraction: float, costs: CostModel = BASE_COSTS) -> tuple[float, float]:
    """(c_w, c_l): round-trip costs in R of a winner and a loser at a stop `stop_fraction` of the price away."""
    winner = 2 * costs.fee + 2 * costs.slippage
    loser = 2 * costs.fee + costs.slippage + costs.stop_slippage
    return winner / stop_fraction, loser / stop_fraction


def p_star(target_r: float, stop_fraction: float, costs: CostModel = BASE_COSTS) -> float:
    """Break-even hit rate p* = (1 + c_l) / (1 + T + c_l - c_w) (section 2.1)."""
    c_w, c_l = cost_r(stop_fraction, costs)
    return (1 + c_l) / (1 + target_r + c_l - c_w)


def is_hit(trade: Trade) -> bool:
    return trade.reason in HIT_REASONS and trade.r > 0


def stop_fraction(trade: Trade) -> float:
    return abs(trade.entry_price - trade.stop) / trade.entry_price


# ----------------------------------------------------------------------------- summary (5.2)


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
    mean_stop_fraction: float
    p_star: float
    by_reason: dict[str, int]
    by_side: dict[str, int]
    by_symbol: dict[str, int]
    expectancy_by_symbol: dict[str, float]
    expectancy_by_side: dict[str, float]
    expectancy_by_year: dict[int, tuple[int, float]]
    mean_bars_held: float
    signal_weeks: int
    mean_hit_r: float
    ignored_signals: int = 0


def pooled(trades_by_symbol: TradesBySymbol) -> list[tuple[str, Trade]]:
    out = [(symbol, t) for symbol, ts in trades_by_symbol.items() for t in ts]
    out.sort(key=lambda item: (item[1].entry_time, item[0]))
    return out


def summarize(trades_by_symbol: TradesBySymbol, target_r: float, *, ignored_signals: int = 0,
              costs: CostModel = BASE_COSTS) -> Summary:
    tagged = pooled(trades_by_symbol)
    n = len(tagged)
    if n == 0:
        return Summary(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, 0, 0.0, 0.0, p_star(target_r, s7.MIN_STOP_DISTANCE, costs),
                       {}, {}, {}, {}, {}, {}, 0.0, 0, 0.0, ignored_signals)
    trades = [t for _, t in tagged]
    results = [t.r for t in trades]
    hits = [is_hit(t) for t in trades]
    wins = [r for r in results if r > 0]
    losses = [r for r in results if r <= 0]
    clusters = [s7.iso_week(t.signal_time) for t in trades]  # ISO week of the signal bar, all instruments together
    d = design_effect(hits, clusters)
    n_eff, losers_eff = effective_counts(n, n - sum(hits), d)
    lower = clopper_pearson_lower(n_eff - losers_eff, n_eff) if n_eff > 0 else 0.0
    gross_loss = -sum(losses)
    mean_stop = statistics.fmean(stop_fraction(t) for t in trades)
    by_reason: dict[str, int] = {}
    by_side = {"long": 0, "short": 0}
    by_symbol: dict[str, int] = {}
    side_results: dict[str, list[float]] = {"long": [], "short": []}
    symbol_results: dict[str, list[float]] = {}
    by_year: dict[int, list[float]] = {}
    for symbol, t in tagged:
        by_reason[t.reason] = by_reason.get(t.reason, 0) + 1
        side = "long" if t.side == 1 else "short"
        by_side[side] += 1
        side_results[side].append(t.r)
        by_symbol[symbol] = by_symbol.get(symbol, 0) + 1
        symbol_results.setdefault(symbol, []).append(t.r)
        by_year.setdefault(s7.year_of(t.entry_time), []).append(t.r)
    return Summary(
        n, sum(hits), sum(hits) / n, statistics.fmean(results),
        (sum(wins) / gross_loss) if gross_loss > 0 else math.inf, max_drawdown_r(results),
        statistics.fmean(losses) if losses else 0.0, min(results), statistics.fmean(wins) if wins else 0.0,
        d, n_eff, losers_eff, lower, mean_stop, p_star(target_r, max(mean_stop, s7.MIN_STOP_DISTANCE), costs),
        dict(sorted(by_reason.items())), by_side, dict(sorted(by_symbol.items())),
        {k: statistics.fmean(v) for k, v in sorted(symbol_results.items())},
        {k: statistics.fmean(v) for k, v in side_results.items() if v},
        {y: (len(v), statistics.fmean(v)) for y, v in sorted(by_year.items())},
        statistics.fmean(t.bars_held for t in trades), len(set(clusters)),
        statistics.fmean(t.r for t, h in zip(trades, hits) if h) if any(hits) else 0.0, ignored_signals,
    )


def hit_report(s: Summary) -> dict:
    """K6, reported only (section 2.1): hit rate, lower bound and p* with the actual mean stop distance."""
    return {"criterion": False, "hit_rate": s.hit_rate, "lower_bound": s.hit_lower_bound, "p_star": s.p_star,
            "above_p_star_plus_margin": s.n > 0 and s.hit_rate >= s.p_star + HIT_MARGIN,
            "mean_stop_fraction": s.mean_stop_fraction, "design_effect": s.design_effect, "n_eff": s.n_eff,
            "losers_eff": s.losers_eff}


Minimums = Mapping[str, tuple[int, int]]


def sample_ok(s: Summary, section: str, minimums: Minimums = MIN_TRADES) -> bool:
    """K3 and the training/validation minimums: trades and signal weeks, both outcome-free."""
    n_min, weeks_min = minimums[section]
    return s.n >= n_min and s.signal_weeks >= weeks_min


# ----------------------------------------------------------------------------- judgement (5.2)


def judge(trades_by_symbol: TradesBySymbol, stress_by_symbol: TradesBySymbol, target_r: float, baseline_p: float,
          significant: bool, *, ignored_signals: int = 0, minimums: Minimums = MIN_TRADES) -> dict[str, dict]:
    """K1-K10 of section 5.2 on pooled holdout trades. `significant` is the Holm decision over all candidates."""
    s = summarize(trades_by_symbol, target_r, ignored_signals=ignored_signals)
    n_min, weeks_min = minimums["holdout"]
    out: dict[str, dict] = {}
    out["K1"] = {"pass": s.expectancy > 0, "expectancy": s.expectancy}
    out["K2"] = {"pass": significant, "p": baseline_p, "m": HOLM_M}
    out["K3"] = {"pass": sample_ok(s, "holdout", minimums), "n": s.n, "signal_weeks": s.signal_weeks, "min": [n_min, weeks_min],
                 "design_effect": s.design_effect, "n_eff": s.n_eff}
    out["K4"] = {"pass": s.max_drawdown <= MAX_DRAWDOWN_R, "max_drawdown": s.max_drawdown}
    out["K5"] = {"pass": s.profit_factor > 1.0, "profit_factor": s.profit_factor}
    out["K6"] = {"pass": True, **hit_report(s)}  # reported only, never decides
    ss = summarize(stress_by_symbol, target_r, costs=BASE_COSTS.stressed())
    out["K7"] = {"pass": ss.n > 0 and ss.expectancy > 0, "expectancy_stress": ss.expectancy}
    stop_gap = s.by_reason.get("stop_gap", 0) + s.by_reason.get("stop_before_entry", 0)
    forced = sum(s.by_reason.get(r, 0) for r in FORCED_REASONS)
    out["K8"] = {"pass": s.n > 0 and s.worst_loss >= -2.0 and s.mean_loss >= -1.2 and stop_gap <= 0.10 * s.n and forced <= 0.50 * s.n,
                 "worst_loss": s.worst_loss, "mean_loss": s.mean_loss,
                 "stop_gap_share": stop_gap / s.n if s.n else 0.0, "forced_share": forced / s.n if s.n else 0.0}
    required_hit_r = target_r - TARGET_SHORTFALL_R
    out["K9"] = {"pass": s.hits > 0 and s.mean_hit_r >= required_hit_r, "mean_hit_r": s.mean_hit_r, "required": required_hit_r,
                 "mean_win": s.mean_win}
    shares = {sym: cnt / s.n for sym, cnt in s.by_symbol.items()} if s.n else {}
    side_shares = {k: v / s.n for k, v in s.by_side.items()} if s.n else {}
    out["K10"] = {"pass": s.n > 0 and len(shares) == 3 and all(v >= 0.15 for v in shares.values()),
                  "instrument_shares": shares, "side_shares": side_shares,  # side shares reported only
                  "expectancy_by_symbol": s.expectancy_by_symbol, "expectancy_by_side": s.expectancy_by_side}
    verdict = "KEIN URTEIL" if not out["K3"]["pass"] else (
        "BESTANDEN (Holdout)" if all(v["pass"] for v in out.values()) else "NICHT BESTANDEN")
    out["verdict"] = {"pass": verdict == "BESTANDEN (Holdout)", "verdict": verdict}
    return out


def holm_significant(pvalues: Mapping[str, float], m: int = HOLM_M, alpha: float = FAMILY_ALPHA) -> set[str]:
    return holm(pvalues, m, alpha)


# ----------------------------------------------------------------------------- training, validation (5.1), robustness (5.4)


def training_verdict(s: Summary, p_a: float, p_a_prime: float, minimums: Minimums = MIN_TRADES) -> dict:
    n_min, weeks_min = minimums["train"]
    reasons = []
    if s.expectancy <= 0:
        reasons.append("E[R] <= 0")
    if s.n < n_min:
        reasons.append(f"n < {n_min}")
    if s.signal_weeks < weeks_min:
        reasons.append(f"Signal-Wochen < {weeks_min}")
    if p_a >= P_TRAIN:
        reasons.append(f"p(A) >= {P_TRAIN}")
    if p_a_prime >= P_TRAIN:
        reasons.append(f"p(A') >= {P_TRAIN}")
    return {"pass": not reasons, "reasons": reasons}


def validation_verdict(s: Summary, p_a: float, p_a_prime: float, robustness: Mapping[str, bool],
                       minimums: Minimums = MIN_TRADES) -> dict:
    n_min, weeks_min = minimums["validation"]
    reasons = []
    if s.n < n_min:
        reasons.append(f"n < {n_min}")
    if s.signal_weeks < weeks_min:
        reasons.append(f"Signal-Wochen < {weeks_min}")
    if s.expectancy <= 0:
        reasons.append("E[R] <= 0")
    if p_a >= P_VALIDATION:
        reasons.append(f"p(A) >= {P_VALIDATION}")
    if p_a_prime >= P_VALIDATION:
        reasons.append(f"p(A') >= {P_VALIDATION}")
    if s.profit_factor <= PF_VALIDATION:
        reasons.append(f"PF <= {PF_VALIDATION}")
    if s.max_drawdown > MAX_DRAWDOWN_R:
        reasons.append(f"DD > {MAX_DRAWDOWN_R:.0f} R")
    reasons += [f"Robustheit: {name}" for name, ok in robustness.items() if not ok]
    return {"pass": not reasons, "reasons": reasons}


def year_rule(train: Summary, validation: Summary) -> bool:
    """E[R] > 0 in at least 60 % of the calendar years with >= 20 trades, training and validation together."""
    merged: dict[int, tuple[int, float]] = {}
    for summary in (train, validation):
        for year, (count, mean) in summary.expectancy_by_year.items():
            c0, m0 = merged.get(year, (0, 0.0))
            merged[year] = (c0 + count, (m0 * c0 + mean * count) / (c0 + count))
    return year_stability(merged, min_trades=YEAR_MIN_TRADES, share=YEAR_SHARE)


def neighbour_rule(train_expectancy: Mapping[str, float], variant: s7.S7Variant,
                   variants: Sequence[s7.S7Variant] = s7.S7_VARIANTS) -> bool:
    by_point = {(v.channel, v.target_r): train_expectancy[v.variant_id] for v in variants if v.variant_id in train_expectancy}
    return neighbours_positive(GRID, by_point, (variant.channel, variant.target_r))


def walk_forward_rule(trades_by_variant: Mapping[str, Sequence[Trade]], start_ms: int, end_ms: int) -> tuple[bool, float, list[str]]:
    """24/6 walk-forward over all four variants on the pooled trades (section 5.4)."""
    windows = walk_forward_windows(start_ms, end_ms, fit_months=24, test_months=6)
    chained, chosen = walk_forward(trades_by_variant, windows)
    return chained > 0, chained, chosen


def select_candidates(validation_expectancy: Mapping[str, float], variants: Sequence[s7.S7Variant] = s7.S7_VARIANTS) -> list[str]:
    """At most one candidate per target T (the higher validation E[R]), at most two in all (5.1 step 3)."""
    best: dict[float, tuple[float, str]] = {}
    for variant in variants:
        if variant.variant_id not in validation_expectancy:
            continue
        score = (validation_expectancy[variant.variant_id], variant.variant_id)
        if variant.target_r not in best or score > best[variant.target_r]:
            best[variant.target_r] = score
    return sorted(vid for _, vid in best.values())


# ----------------------------------------------------------------------------- baselines (7)


@dataclass(frozen=True, slots=True)
class SectionData:
    """Bars, ATR series, funding and the section window of one instrument."""

    bars: Sequence[Kline]
    atr_values: Sequence[float | None]
    funding: Sequence[FundingRate]
    start_ms: int
    end_ms: int
    trend_values: Sequence[int | None] | None = None  # from trend_series, optional cache for baseline C

    def candidates(self) -> list[int]:
        """Bars of the section with a contiguous ATR window, at least EDGE_BARS before the section end."""
        times = [b.open_time for b in self.bars]
        lo = bisect.bisect_left(times, self.start_ms)
        hi = bisect.bisect_left(times, self.end_ms - EDGE_BARS * s7.INTERVAL_MS)
        return [i for i in range(lo, min(hi, len(self.bars) - 1)) if self.atr_values[i]]

    def trend(self, i: int) -> int | None:
        """+1 above the SMA 200, -1 below, None without a contiguous SMA window (baseline C)."""
        if self.trend_values is not None:
            return self.trend_values[i]
        return trend_at(self.bars, i)

    def index_of(self, open_time: int) -> int:
        times = [b.open_time for b in self.bars]
        i = bisect.bisect_left(times, open_time)
        if i >= len(times) or times[i] != open_time:
            raise ValueError("signal time not in bars")
        return i


def trend_at(bars: Sequence[Kline], i: int) -> int | None:
    history = History(bars, i)
    if len(history) < s7.SMA_PERIOD or not s7.contiguous(history, s7.SMA_PERIOD):
        return None
    sma = sma_close(history, s7.SMA_PERIOD)
    close = bars[i].close
    return 1 if close > sma else -1 if close < sma else None


def trend_series(bars: Sequence[Kline]) -> list[int | None]:
    """SMA 200 trend state per bar (baseline C), computed once per instrument."""
    closes = [b.close for b in bars]
    out: list[int | None] = []
    running = 0.0
    for i, close in enumerate(closes):
        running += close
        if i >= s7.SMA_PERIOD:
            running -= closes[i - s7.SMA_PERIOD]
        if i + 1 < s7.SMA_PERIOD or not s7.contiguous(History(bars, i), s7.SMA_PERIOD):
            out.append(None)
            continue
        sma = running / s7.SMA_PERIOD
        out.append(1 if close > sma else -1 if close < sma else None)
    return out

def atr_series_contiguous(bars: Sequence[Kline]) -> list[float | None]:
    """ATR14 per bar, None where a 4h bar is missing inside the ATR window (section 3)."""
    out: list[float | None] = []
    for t in range(len(bars)):
        history = History(bars, t)
        value = atr(history, s7.ATR_PERIOD)
        out.append(value if value is not None and s7.contiguous(history, s7.ATR_PERIOD + 1) else None)
    return out


def volatility_deciles(data: SectionData) -> list[float]:
    """Nine cut points of ATR14 / close over the section's candidate bars (baseline A')."""
    values = sorted(data.atr_values[i] / data.bars[i].close for i in data.candidates())
    if not values:
        return []
    return [values[min(len(values) - 1, int(len(values) * q / 10))] for q in range(1, 10)]


def decile_of(value: float, cuts: Sequence[float]) -> int:
    return bisect.bisect_right(cuts, value)


@dataclass(slots=True)
class BaselineResult:
    p: float
    mean_expectancy: float
    hit_rate: float
    pool_sizes: dict[str, int]


def _pool(data: SectionData, indices: Sequence[int], templates: Sequence[tuple[int, float, float, int]], size: int,
          rng: random.Random, costs: CostModel) -> list[tuple[float, bool]]:
    funding_times = [f.time for f in data.funding]
    out: list[tuple[float, bool]] = []
    attempts = 0
    while len(out) < size:
        attempts += 1
        if attempts > 20 * size:
            raise ValueError("random entries cannot be placed in this period")
        index = rng.choice(indices)
        side, stop_atr, target_r, held = rng.choice(templates)
        detail = simulate_trade_detail(data.bars, index, side, stop_atr * data.atr_values[index], target_r, held,
                                       s7.INTERVAL_MS, costs, data.funding, funding_times)
        if detail is not None:
            r, reason, _ = detail
            out.append((r, reason in HIT_REASONS and r > 0))
    return out


MODES = ("A", "A'", "C")


def random_baseline(data_by_symbol: Mapping[str, SectionData], trades_by_symbol: TradesBySymbol, *, mode: str = "A",
                    runs: int = BASELINE_RUNS, seed: int = SEED, costs: CostModel = BASE_COSTS) -> BaselineResult:
    """Baseline A (protocol 7.1 per instrument, pooled), A' (comparison bars from the same ATR/close decile as the
    real signal bar) or C (comparison bars with the same SMA 200 trend state as the template's side).
    p = (1 + runs with pooled E[R] >= observed) / (runs + 1)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    tagged = pooled(trades_by_symbol)
    if not tagged:
        return BaselineResult(1.0, 0.0, 0.0, {})
    if any(t.stop_atr is None for _, t in tagged):
        raise ValueError("trades need stop_atr; run the backtest with atr_at_signal")
    observed = statistics.fmean(t.r for _, t in tagged)
    rng = random.Random(seed + MODES.index(mode))
    groups: dict[str, list[Trade]] = {}
    for symbol, t in tagged:
        key = symbol
        if mode == "A'":
            data = data_by_symbol[symbol]
            cuts = volatility_deciles(data)
            i = data.index_of(t.signal_time)
            key = f"{symbol}/{decile_of(data.atr_values[i] / data.bars[i].close, cuts)}"
        elif mode == "C":
            key = f"{symbol}/{'long' if t.side == 1 else 'short'}"
        groups.setdefault(key, []).append(t)
    pools: dict[str, list[tuple[float, bool]]] = {}
    for key, trades in sorted(groups.items()):
        symbol = key.split("/")[0]
        data = data_by_symbol[symbol]
        indices = data.candidates()
        size = min(runs * len(trades), max(POOL_FACTOR * len(trades), MIN_POOL))
        if mode == "A'":
            cuts = volatility_deciles(data)
            decile = int(key.split("/")[1])
            indices = [i for i in indices if decile_of(data.atr_values[i] / data.bars[i].close, cuts) == decile]
            size = POOL_PER_DECILE
        elif mode == "C":
            side = 1 if key.endswith("long") else -1
            indices = [i for i in indices if data.trend(i) == side]
        if not indices:
            raise ValueError(f"no comparison bars for {key}")
        templates = [(t.side, t.stop_atr, t.target_r, t.bars_held) for t in trades]
        pools[key] = _pool(data, indices, templates, size, rng, costs)
    n = len(tagged)
    threshold = observed * n
    at_least = 0
    total = 0.0
    for _ in range(runs):
        run_sum = 0.0
        for key, trades in groups.items():
            run_sum += sum(r for r, _ in rng.choices(pools[key], k=len(trades)))
        total += run_sum
        if run_sum >= threshold:
            at_least += 1
    hits = sum(h for pool in pools.values() for _, h in pool)
    size = sum(len(pool) for pool in pools.values())
    return BaselineResult((1 + at_least) / (1 + runs), total / (runs * n), hits / size, {k: len(v) for k, v in pools.items()})


def mirrored(data_by_symbol: Mapping[str, SectionData], trades_by_symbol: TradesBySymbol, *, costs: CostModel = BASE_COSTS
             ) -> dict[str, list[tuple[float, bool]]]:
    """Baseline B: the same signals in the opposite direction, same stop distance, target and time stop."""
    out: dict[str, list[tuple[float, bool]]] = {}
    for symbol, trades in trades_by_symbol.items():
        data = data_by_symbol[symbol]
        funding_times = [f.time for f in data.funding]
        rows = []
        for t in trades:
            index = data.index_of(t.signal_time)
            detail = simulate_trade_detail(data.bars, index, -t.side, abs(t.entry_price - t.stop), t.target_r,
                                           s7.TIME_STOP_BARS, s7.INTERVAL_MS, costs, data.funding, funding_times)
            if detail is not None:
                r, reason, _ = detail
                rows.append((r, reason in HIT_REASONS and r > 0))
        out[symbol] = rows
    return out


def buy_and_hold(data: SectionData) -> float | None:
    """Return of holding the instrument from the first to the last bar of the section (reported, long only)."""
    times = [b.open_time for b in data.bars]
    lo = bisect.bisect_left(times, data.start_ms)
    hi = bisect.bisect_left(times, data.end_ms)
    if hi <= lo:
        return None
    return data.bars[hi - 1].close / data.bars[lo].open - 1


def baseline_summary(rows: Mapping[str, Sequence[tuple[float, bool]]]) -> dict[str, float | int]:
    flat = [row for rs in rows.values() for row in rs]
    if not flat:
        return {"n": 0, "expectancy": 0.0, "hit_rate": 0.0}
    return {"n": len(flat), "expectancy": statistics.fmean(r for r, _ in flat), "hit_rate": sum(h for _, h in flat) / len(flat)}
