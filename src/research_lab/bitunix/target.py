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


# --- Empirical model from a real trade list (review PR #226: reproducible inputs) -------------------------------

REPORT_VERSION = "1.0"
TARGET_PER_DAY = 50.0
RISK_FRACTIONS = (0.0025, 0.01)
EQUITIES = (500, 1_000, 2_500, 5_000, 10_000, 25_000)


def daily_r(trades: list[dict], first_day: int, n_days: int) -> list[float]:
    """Net R summed per calendar day (``day`` = days since 1970-01-01 UTC), days without trades = 0."""
    out = [0.0] * n_days
    for t in trades:
        i = int(t["day"]) - first_day
        if not 0 <= i < n_days:
            raise ValueError(f"trade day {t['day']} outside the section")
        out[i] += float(t["net_r"])
    return out


def bootstrap_mean_ci(values: list[float], *, draws: int = 5000, seed: int = 2026, alpha: float = 0.05,
                      block: int = 10) -> tuple[float, float]:
    """Moving-block bootstrap of the mean; blocks of ``block`` days keep clustered days together."""
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(draws):
        s = 0.0
        k = 0
        while k < n:
            start = rng.randrange(n)
            for j in range(block):
                if k >= n:
                    break
                s += values[(start + j) % n]
                k += 1
        means.append(s / n)
    means.sort()
    return means[int(alpha / 2 * draws)], means[int((1 - alpha / 2) * draws) - 1]


def simulate_days(daily: list[float], *, equity: float, risk_fraction: float, target_per_day: float = TARGET_PER_DAY,
                  days: int = 365, paths: int = 1000, seed: int = 2026, block: int = 10) -> dict:
    """Resample blocks of real days (net R) into ``paths`` years; fixed R in USD (no compounding)."""
    rng = random.Random(seed)
    r_usd = equity * risk_fraction
    n = len(daily)
    all_days = 0
    pos = tgt = zero = 0
    month_loss = months = 0
    dds: list[float] = []
    ruin = 0
    for _ in range(paths):
        seq: list[float] = []
        while len(seq) < days:
            start = rng.randrange(n)
            seq.extend(daily[(start + j) % n] for j in range(block))
        seq = seq[:days]
        eq = peak = 0.0
        dd = 0.0
        ruined = False
        for d, r in enumerate(seq):
            pnl = r * r_usd
            all_days += 1
            pos += pnl > 0
            tgt += pnl >= target_per_day
            zero += r == 0.0
            eq += pnl
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
            if eq <= -0.5 * equity:
                ruined = True
            if (d + 1) % 30 == 0:
                month = sum(seq[d - 29:d + 1])
                months += 1
                month_loss += month < 0
        dds.append(dd)
        ruin += ruined
    dds.sort()
    mean_r = sum(daily) / n
    return {
        "equity": equity,
        "risk_fraction": risk_fraction,
        "r_usd": round(r_usd, 2),
        "mean_per_calendar_day_usd": round(mean_r * r_usd, 2),
        "share_days_no_trade": round(zero / all_days, 3),
        "share_days_profit": round(pos / all_days, 3),
        "share_days_target": round(tgt / all_days, 3),
        "share_months_loss": round(month_loss / max(1, months), 3),
        "max_drawdown_usd_p50": round(dds[len(dds) // 2], 2),
        "max_drawdown_usd_p95": round(dds[int(0.95 * (len(dds) - 1))], 2),
        "ruin_share": round(ruin / paths, 4),
    }


def build_report(trade_file: dict) -> dict:
    """Deterministic 50-USD report from a committed trade extract (see docs/research_lab/reports/bitunix/)."""
    from datetime import date

    first = (date.fromisoformat(trade_file["erster_tag"]) - date(1970, 1, 1)).days
    n_days = int(trade_file["tage"])
    trades = trade_file["of_trades"]
    rs = [float(t["net_r"]) for t in trades]
    daily = daily_r(trades, first, n_days)
    mean_trade = sum(rs) / len(rs)
    sd_trade = math.sqrt(sum((x - mean_trade) ** 2 for x in rs) / (len(rs) - 1))
    mean_day = sum(daily) / n_days
    lo, hi = bootstrap_mean_ci(daily)
    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x <= 0]
    stops = sorted(float(t["stop_dist"]) for t in trades)

    def equity_for(day_r: float, f: float) -> float | None:
        return round(TARGET_PER_DAY / (day_r * f)) if day_r > 0 else None

    return {
        "report": "bitunix-target-50usd",
        "version": REPORT_VERSION,
        "inputs": {
            "source": trade_file["source"],
            "studie": trade_file["studie"],
            "abschnitt": trade_file["abschnitt"],
            "config_digest": trade_file["config_digest"],
            "datensatz_hash": trade_file["datensatz_hash"],
            "cost_per_side": trade_file["cost"],
            "first_day": trade_file["erster_tag"],
            "last_day": trade_file["letzter_tag"],
            "calendar_days": n_days,
            "target_per_day_usd": TARGET_PER_DAY,
            "model": "moving-block bootstrap of real calendar days, block 10, 5000 draws (CI) / 1000 paths x 365 "
                     "days (simulation), seed 2026, fixed R in USD",
        },
        "trades": {
            "n": len(rs),
            "per_calendar_day": round(len(rs) / n_days, 4),
            "win_rate": round(len(wins) / len(rs), 4),
            "avg_win_r": round(sum(wins) / len(wins), 4),
            "avg_loss_r": round(sum(losses) / len(losses), 4),
            "mean_r": round(mean_trade, 4),
            "sd_r": round(sd_trade, 4),
            "stop_distance_min": stops[0],
            "stop_distance_median": stops[len(stops) // 2],
        },
        "per_calendar_day_r": {"mean": round(mean_day, 6), "ci95": [round(lo, 6), round(hi, 6)]},
        "required_equity_usd": {
            str(f): {"point": equity_for(mean_day, f), "at_ci_upper": equity_for(hi, f),
                     "at_ci_lower": equity_for(lo, f)}
            for f in RISK_FRACTIONS
        },
        "simulation_risk_0_0025": [simulate_days(daily, equity=e, risk_fraction=0.0025) for e in EQUITIES],
        "verdict": "TARGET NOT PROVEN" if lo <= 0 else "TARGET MODELLED (edge still needs validation)",
    }
