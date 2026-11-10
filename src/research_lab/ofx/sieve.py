"""Filter application, metrics and the sieve rules of the OFX plan (training only)."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import NormalDist

from src.research_lab.of2.backtest import Trade
from src.research_lab.ofx.space import TradeFilter

TRAIN_YEARS = (2020, 2021, 2022, 2023)


@dataclass(frozen=True)
class Rules:
    min_trades: int = 130          # 4 training years; below 100 nothing is testable (protocol), Uzi guide 56-124 per 3 years
    min_mean_r: float = 0.10       # net R per trade after Bitunix taker costs
    max_drawdown_r: float = 15.0
    alpha: float = 0.05            # one-sided, Bonferroni over the engine configurations tried so far
    neighbour_share: float = 0.5   # every neighbour keeps >= 50 % of the mean
    random_p: float = 0.01         # against random entries


DEFAULT_RULES = Rules()


def _day(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def apply_filter(trades: Sequence[Trade], f: TradeFilter) -> list[Trade]:
    """Confirmed trades the filter keeps, in fill order. Day rules count per UTC signal day; a loss only stops
    later trades of that day whose fill comes after the losing exit (no look-ahead)."""
    kept: list[Trade] = []
    per_day: dict[str, list[Trade]] = {}
    for t in sorted(trades, key=lambda t: (t.fill_ms, t.signal.signal_ms)):
        s = t.signal
        if not s.confirmed or s.model not in f.models or s.session not in f.sessions or s.regime not in f.regimes:
            continue
        day = _day(s.signal_ms)
        if f.skip_weekend and day.weekday() >= 5:
            continue
        taken = per_day.setdefault(day.date().isoformat(), [])
        if f.max_trades_day is not None and len(taken) >= f.max_trades_day:
            continue
        if f.stop_after_losses_day is not None:
            losses = sum(1 for p in taken if p.exit_ms <= t.fill_ms and p.net_r < 0)
            if losses >= f.stop_after_losses_day:
                continue
        taken.append(t)
        kept.append(t)
    return kept


def metrics(trades: Sequence[Trade]) -> dict:
    r = [t.net_r for t in trades]
    n = len(r)
    if n == 0:
        return {"n": 0, "mean": 0.0, "sd": 0.0, "t": 0.0, "sum": 0.0, "hit": 0.0, "max_dd": 0.0, "years": {}}
    mean = sum(r) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in r) / (n - 1)) if n > 1 else 0.0
    eq = peak = dd = 0.0
    for x in r:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    years: dict[int, float] = {}
    for t in trades:
        y = _day(t.signal.signal_ms).year
        years[y] = years.get(y, 0.0) + t.net_r
    return {"n": n, "mean": round(mean, 4), "sd": round(sd, 4), "t": round(mean / sd * math.sqrt(n), 3) if sd > 0 else 0.0,
            "sum": round(sum(r), 3), "hit": round(sum(1 for x in r if x > 0) / n, 4), "max_dd": round(dd, 3),
            "years": {str(y): round(v, 3) for y, v in sorted(years.items())}}


def t_threshold(configs_tried: int, alpha: float) -> float:
    """One-sided Bonferroni threshold over the engine configurations tried so far (filters count as tuning
    inside a configuration; validation and final test on unseen years are the real protection)."""
    return NormalDist().inv_cdf(1 - alpha / max(1, configs_tried))


def basic_pass(m: dict, configs_tried: int, rules: Rules = DEFAULT_RULES) -> tuple[bool, list[str]]:
    why = []
    if m["n"] < rules.min_trades:
        why.append("zu_wenig_trades")
    if m["mean"] < rules.min_mean_r:
        why.append("mittel_zu_klein")
    if any(m["years"].get(str(y), 0.0) <= 0 for y in TRAIN_YEARS):
        why.append("jahr_nicht_im_plus")
    if m["max_dd"] > rules.max_drawdown_r:
        why.append("rueckgang_zu_gross")
    if m["t"] < t_threshold(configs_tried, rules.alpha):
        why.append("mehrfachtest")
    return not why, why


def neighbours_pass(candidate_mean: float, neighbour_means: Sequence[float], rules: Rules = DEFAULT_RULES) -> bool:
    return bool(neighbour_means) and all(m >= rules.neighbour_share * candidate_mean for m in neighbour_means)
