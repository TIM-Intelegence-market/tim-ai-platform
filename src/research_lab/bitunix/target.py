"""50-USD-per-day model (Phase 6): what capital and edge the target needs.

Inputs are trade statistics in R (net after costs). Daily PnL in USD = sum of the day's trades x R_usd, with
R_usd = equity x risk_fraction. Trades per day are Poisson; trade results are drawn from a two-point distribution
(win +win_r, loss -1 R) matched to the given win rate. That is an approximation: real trades also end at time stops.
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Edge:
    win_rate: float
    win_r: float  # average winner in R
    loss_r: float = 1.0  # average loser in R (positive number)
    trades_per_day: float = 0.2

    @property
    def expectancy_r(self) -> float:
        return self.win_rate * self.win_r - (1 - self.win_rate) * self.loss_r

    @property
    def sd_r(self) -> float:
        m = self.expectancy_r
        return math.sqrt(self.win_rate * (self.win_r - m) ** 2 + (1 - self.win_rate) * (-self.loss_r - m) ** 2)

    def breakeven_win_rate(self) -> float:
        return self.loss_r / (self.win_r + self.loss_r)


def required_equity(target_per_day: float, edge: Edge, risk_fraction: float) -> float:
    """Equity whose expected calendar-day PnL equals the target. inf if the edge is <= 0."""
    daily_r = edge.trades_per_day * edge.expectancy_r
    if daily_r <= 0:
        return math.inf
    return target_per_day / (daily_r * risk_fraction)


@dataclass(frozen=True)
class Simulation:
    equity: float
    risk_fraction: float
    r_usd: float
    required_daily_return: float
    mean_day: float
    sd_day: float
    share_days_no_trade: float
    share_days_profit: float
    share_days_target: float
    share_months_loss: float
    max_drawdown_usd_p50: float
    max_drawdown_usd_p95: float
    longest_loss_streak_p95: int
    ruin_share: float  # paths that lost >= 50 % of equity within the horizon

    def as_dict(self) -> dict:
        return asdict(self)


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def simulate(
    *, equity: float, edge: Edge, risk_fraction: float, target_per_day: float = 50.0, days: int = 365,
    paths: int = 2000, seed: int = 2026, compounding: bool = False,
) -> Simulation:
    rng = random.Random(seed)
    day_pnls: list[float] = []
    month_pnls: list[float] = []
    max_dds: list[float] = []
    streaks: list[int] = []
    no_trade = ruin = 0
    for _ in range(paths):
        eq = peak = equity
        dd = 0.0
        streak = best_streak = 0
        month = 0.0
        ruined = False
        for d in range(days):
            r_usd = (eq if compounding else equity) * risk_fraction
            n = _poisson(rng, edge.trades_per_day)
            if n == 0:
                no_trade += 1
            pnl = 0.0
            for _ in range(n):
                if rng.random() < edge.win_rate:
                    pnl += edge.win_r * r_usd
                    streak = 0
                else:
                    pnl -= edge.loss_r * r_usd
                    streak += 1
                    best_streak = max(best_streak, streak)
            eq += pnl
            day_pnls.append(pnl)
            month += pnl
            if (d + 1) % 30 == 0:
                month_pnls.append(month)
                month = 0.0
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
            if eq <= 0.5 * equity:
                ruined = True
        max_dds.append(dd)
        streaks.append(best_streak)
        ruin += ruined
    day_pnls_n = len(day_pnls)
    mean = sum(day_pnls) / day_pnls_n
    sd = math.sqrt(sum((x - mean) ** 2 for x in day_pnls) / day_pnls_n)
    max_dds.sort()
    streaks.sort()
    return Simulation(
        equity=equity,
        risk_fraction=risk_fraction,
        r_usd=round(equity * risk_fraction, 2),
        required_daily_return=round(target_per_day / equity, 5),
        mean_day=round(mean, 2),
        sd_day=round(sd, 2),
        share_days_no_trade=round(no_trade / day_pnls_n, 3),
        share_days_profit=round(sum(x > 0 for x in day_pnls) / day_pnls_n, 3),
        share_days_target=round(sum(x >= target_per_day for x in day_pnls) / day_pnls_n, 3),
        share_months_loss=round(sum(x < 0 for x in month_pnls) / max(1, len(month_pnls)), 3),
        max_drawdown_usd_p50=round(max_dds[len(max_dds) // 2], 2),
        max_drawdown_usd_p95=round(max_dds[int(0.95 * (len(max_dds) - 1))], 2),
        longest_loss_streak_p95=streaks[int(0.95 * (len(streaks) - 1))],
        ruin_share=round(ruin / paths, 4),
    )


def edge_ci(mean_r: float, sd_r: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Normal-approximation confidence interval of the mean R per trade."""
    half = z * sd_r / math.sqrt(n)
    return mean_r - half, mean_r + half
