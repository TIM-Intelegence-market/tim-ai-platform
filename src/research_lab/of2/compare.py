"""Comparators for OF2 (protocol 7.1 and prereg section 7).

1. Price-only comparator: the same signals without the orderflow confirmation; the engine already marks
   every signal ``confirmed`` True/False, so this is a split of one run, not a second run.
2. Random comparator: ``draws`` random strategies per section, each with as many pseudo trades as the real
   strategy, same direction, same session window, same stop distance in percent, same target in R and the
   same time frame for the time stop; entry minute drawn uniformly from the minutes of the section in that
   session. Tracked with the same Tracker on a second streaming pass. Fixed seed.
"""
from __future__ import annotations

import random
from collections.abc import Iterable, Sequence
from datetime import date, timedelta

from src.research_lab.of2.backtest import Tracker, Trade
from src.research_lab.of2.config import DAY_MS, HOUR_MS, MINUTE_MS, Config
from src.research_lab.of2.engine import DayLoader, _ms
from src.research_lab.of2.models import MARKET, Signal
from src.research_lab.protocol import BASE_COSTS, CostModel


def _session_window(name: str, cfg: Config) -> tuple[int, int]:
    for n, lo, hi in cfg.sessions:
        if n == name:
            return lo, hi
    raise KeyError(name)


def random_signals(trades: Sequence[Trade], first: date, last: date, cfg: Config, draws: int, seed: int) -> list[Signal]:
    """Pseudo signals for ``draws`` random strategies mirroring the real trades (section [first, last] inclusive)."""
    rng = random.Random(seed)
    n_days = (last - first).days + 1
    out: list[Signal] = []
    for draw in range(draws):
        for t in trades:
            s = t.signal
            lo, hi = _session_window(s.session, cfg)
            day_ms = _ms(first) + rng.randrange(n_days) * DAY_MS
            minute = day_ms + lo * HOUR_MS + rng.randrange((hi - lo) * 60) * MINUTE_MS
            stop_pct = abs(t.entry - s.stop) / t.entry
            target_r = abs(s.target - t.entry) / abs(t.entry - s.stop)
            out.append(Signal(s.model, s.direction, minute, MARKET, None, minute + MINUTE_MS, -stop_pct, target_r,
                              "ZUFALL", float(draw), s.confirmed, s.session, s.regime, None, None, ("zufall",), s.tf))
    return out


def _materialize(signal: Signal, open_price: float, fill_ms: int | None = None) -> Signal:
    """Turn the relative stop (negative percent) and target (R) of a pseudo signal into prices at the fill open."""
    stop_pct, target_r = -signal.stop, signal.target
    dist = open_price * stop_pct
    stop = open_price - signal.direction * dist
    target = open_price + signal.direction * dist * target_r
    at = signal.signal_ms if fill_ms is None else fill_ms
    return Signal(signal.model, signal.direction, at, MARKET, None, at + MINUTE_MS, stop, target,
                  signal.level_name, signal.level, signal.confirmed, signal.session, signal.regime, None, None, signal.notes,
                  signal.tf)


def run_random(loader: DayLoader, first: date, last: date, pseudo: Sequence[Signal], cfg: Config,
               costs: CostModel = BASE_COSTS) -> list[Trade]:
    """Second streaming pass: fills every pseudo signal at the open of its minute and follows it like a real trade.

    Streams exactly [first, last] like the real run; pseudo trades still open at the end are dropped the same way
    the real run drops them. Never reads a day past ``last`` (the day after the validation section is holdout).
    """
    tracker = Tracker(cfg, costs)
    by_minute: dict[int, list[Signal]] = {}
    for s in pseudo:
        by_minute.setdefault(s.signal_ms, []).append(s)
    trades: list[Trade] = []
    day = first
    while day <= last:
        bars, _ = loader(day)
        for bar in bars:
            t = bar.window_start_ms
            waiting = by_minute.pop(t - MINUTE_MS, None)
            if waiting and bar.has_trades:
                open_price = bar.first_price_e8 / 1e8
                for s in waiting:
                    tracker.add(_materialize(s, open_price, t))
            trades.extend(tracker.push(bar))
        day += timedelta(days=1)
    return trades


def strategy_means(trades: Iterable[Trade]) -> dict[int, float]:
    """Mean net R per random strategy (draw index is stored in ``signal.level``)."""
    sums: dict[int, list[float]] = {}
    for t in trades:
        sums.setdefault(int(t.signal.level), []).append(t.net_r)
    return {k: sum(v) / len(v) for k, v in sums.items()}


def p_value(real_mean: float, random_means: Sequence[float]) -> float:
    """Protocol 7.1: (1 + #random >= real) / (1 + draws), one-sided."""
    return (1 + sum(1 for m in random_means if m >= real_mean)) / (1 + len(random_means))
