"""Per-variant key figures (protocol section 5)."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from src.research_lab.backtest.engine import Trade
from src.research_lab.protocol import RISK_PER_TRADE


@dataclass(frozen=True, slots=True)
class Summary:
    trades: int
    expectancy_r: float
    median_r: float
    std_r: float
    profit_factor: float
    win_rate: float
    avg_win_r: float
    avg_loss_r: float
    max_drawdown_r: float
    max_drawdown_pct: float
    longest_losing_streak: int
    expectancy_by_year: dict[int, tuple[int, float]]


def max_drawdown_r(results: Sequence[float]) -> float:
    peak = equity = worst = 0.0
    for value in results:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def summarize(trades: Sequence[Trade], risk_per_trade: float = RISK_PER_TRADE) -> Summary:
    results = [trade.r for trade in trades]
    if not results:
        return Summary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, {})
    wins = [r for r in results if r > 0]
    losses = [r for r in results if r <= 0]
    gross_loss = -sum(losses)
    streak = longest = 0
    for r in results:
        streak = streak + 1 if r <= 0 else 0
        longest = max(longest, streak)
    by_year: dict[int, list[float]] = {}
    for trade in trades:
        year = datetime.fromtimestamp(trade.entry_time / 1000, tz=timezone.utc).year
        by_year.setdefault(year, []).append(trade.r)
    drawdown = max_drawdown_r(results)
    return Summary(
        trades=len(results),
        expectancy_r=statistics.fmean(results),
        median_r=statistics.median(results),
        std_r=statistics.pstdev(results),
        profit_factor=sum(wins) / gross_loss if gross_loss > 0 else float("inf"),
        win_rate=len(wins) / len(results),
        avg_win_r=statistics.fmean(wins) if wins else 0.0,
        avg_loss_r=statistics.fmean(losses) if losses else 0.0,
        max_drawdown_r=drawdown,
        max_drawdown_pct=drawdown * risk_per_trade,
        longest_losing_streak=longest,
        expectancy_by_year={year: (len(values), statistics.fmean(values)) for year, values in sorted(by_year.items())},
    )
