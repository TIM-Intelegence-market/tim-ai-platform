"""Study S13, section 5: key figures and verdicts for training and validation (own family, no holdout).

Criteria (preregistration 5, protocol 8 steps 1-2 and 7.3), per variant, pooled over BTC/ETH/SOL:
- Training: n >= 500, E[R] > 0, p < 0.10 against random entries, n_eff >= 160.
- Validation: n >= 250, E[R] > 0, p < 0.05, profit factor > 1.1, drawdown <= 20 % (1 % risk per
  trade), n_eff >= 183, year stability and walk-forward > 0 (7.3). The anchor (NY/UTC) is a
  category, so there is no neighbour rule.
n_eff = floor(n / D) with the design effect D of the win flag (R > 0) clustered by UTC calendar day of
the signal over all instruments, as in S6/S10.
"""
from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

from src.research_lab.backtest.engine import Trade
from src.research_lab.backtest.metrics import summarize
from src.research_lab.protocol import MAX_DRAWDOWN_LIMIT, MIN_TRADES_TRAIN
from src.research_lab.stats.clustered import design_effect, effective_counts
from src.research_lab.stats.inference import (
    walk_forward,
    walk_forward_windows,
    year_stability,
)

TradesBySymbol = Mapping[str, Sequence[Trade]]

MIN_N = {"train": MIN_TRADES_TRAIN["short"], "validation": MIN_TRADES_TRAIN["short"] // 2}
MIN_N_EFF = {"train": 160, "validation": 183}
P_MAX = {"train": 0.10, "validation": 0.05}
PF_VALIDATION = 1.1
SESSION_END = "rule"  # trailing stop and session end both leave through the exit rule


def day_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def pooled(trades: TradesBySymbol) -> list[Trade]:
    return sorted((t for ts in trades.values() for t in ts), key=lambda t: (t.entry_time, t.signal_time))


def section_figures(trades: TradesBySymbol, session_end_exits: Mapping[str, set[int]] | None = None) -> dict:
    """Key figures of one section, pooled in entry-time order. ``session_end_exits``: per instrument
    the exit moments of the session end (open of the bar after the last check bar)."""
    all_trades = pooled(trades)
    s = summarize(all_trades)
    n = s.trades
    wins = [t.r > 0 for t in all_trades]
    d = design_effect(wins, [day_of(t.signal_time) for t in all_trades])
    n_eff, _ = effective_counts(n, n - sum(wins), d)
    reasons: dict[str, int] = {}
    for t in all_trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1
    by_symbol = {sym: {"n": len(ts), "expectancy_r": statistics.fmean(t.r for t in ts) if ts else 0.0}
                 for sym, ts in sorted(trades.items())}
    by_side = {name: [t.r for t in all_trades if t.side == side] for name, side in (("long", 1), ("short", -1))}
    return {
        "n": n, "expectancy_r": s.expectancy_r, "median_r": s.median_r, "profit_factor": s.profit_factor,
        "win_rate": s.win_rate, "avg_win_r": s.avg_win_r, "avg_loss_r": s.avg_loss_r,
        "max_drawdown_r": s.max_drawdown_r, "max_drawdown_pct": s.max_drawdown_pct,
        "design_effect": d, "n_eff": n_eff, "signal_days": len({day_of(t.signal_time) for t in all_trades}),
        "by_reason": dict(sorted(reasons.items())),
        "session_end_share": (sum(1 for sym, ts in trades.items() for t in ts if t.reason == SESSION_END
                                  and t.exit_time in (session_end_exits or {}).get(sym, set())) / n
                              if n and session_end_exits is not None else None),
        "catastrophe_stop_share": (reasons.get("stop", 0) + reasons.get("stop_gap", 0)) / n if n else 0.0,
        "mean_funding_r": statistics.fmean(t.funding_r for t in all_trades) if n else 0.0,
        "mean_fee_r": statistics.fmean(t.cost_r for t in all_trades) if n else 0.0,
        "mean_bars_held": statistics.fmean(t.bars_held for t in all_trades) if n else 0.0,
        "by_symbol": by_symbol,
        "by_side": {k: {"n": len(v), "expectancy_r": statistics.fmean(v) if v else 0.0} for k, v in by_side.items()},
        "by_year": {str(y): {"n": c, "expectancy_r": m} for y, (c, m) in s.expectancy_by_year.items()},
    }


def needs_pvalue(figures: Mapping, section: str) -> bool:
    """The random comparison only runs where it can decide (as in the general runner)."""
    return figures["expectancy_r"] > 0 and figures["n"] >= MIN_N[section]


def section_verdict(figures: Mapping, p: float | None, section: str) -> dict:
    reasons = []
    if figures["n"] < MIN_N[section]:
        reasons.append(f"n < {MIN_N[section]}")
    if figures["n_eff"] < MIN_N_EFF[section]:
        reasons.append(f"n_eff < {MIN_N_EFF[section]}")
    if figures["expectancy_r"] <= 0:
        reasons.append("E[R] <= 0")
    if p is None or p >= P_MAX[section]:
        reasons.append(f"p >= {P_MAX[section]}" if p is not None else "p nicht berechnet")
    if section == "validation":
        if not figures["profit_factor"] > PF_VALIDATION:
            reasons.append(f"PF <= {PF_VALIDATION}")
        if figures["max_drawdown_pct"] > MAX_DRAWDOWN_LIMIT + 1e-12:
            reasons.append(f"DD > {MAX_DRAWDOWN_LIMIT:.0%}")
    return {"pass": not reasons, "reasons": reasons}


def year_rule(trades: TradesBySymbol) -> bool:
    """7.3: E[R] > 0 in >= 60 % of the calendar years with >= 5 trades, training and validation together."""
    return year_stability(summarize(pooled(trades)).expectancy_by_year, min_trades=5, share=0.6)


def walk_forward_rule(trades_by_variant: Mapping[str, TradesBySymbol], start_ms: int, end_ms: int) -> dict:
    """7.3: 24 months fit, 6 months test, best variant per fit window, chained test mean > 0.
    A failure blocks every variant."""
    windows = walk_forward_windows(start_ms, end_ms, fit_months=24, test_months=6)
    chained, chosen = walk_forward({v: pooled(t) for v, t in trades_by_variant.items()}, windows)
    return {"pass": bool(windows) and chained > 0, "chained_expectancy_r": chained, "chosen": chosen,
            "windows": len(windows)}


def final_verdict(train: Mapping, validation: Mapping, years_ok: bool, walk: Mapping) -> str:
    if not train["pass"]:
        return "NICHT BESTANDEN (Training)"
    reasons = list(validation["reasons"])
    if not years_ok:
        reasons.append("Jahresstabilität")
    if not walk["pass"]:
        reasons.append("Walk-Forward")
    return "KANDIDAT (prospektiver Test nötig)" if not reasons else "NICHT BESTANDEN (Validierung)"
