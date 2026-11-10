"""Comparators for OF2 (protocol 7.1 and prereg section 7).

1. Price-only comparator: the same signals without the orderflow confirmation; the engine already marks
   every signal ``confirmed`` True/False, so this is a split of one run, not a second run.
2. Random comparator: ``draws`` random strategies per section, each with as many pseudo trades as the real
   strategy, same direction, same session window, same stop distance in percent, same target in R and the
   same time frame for the time stop; entry minute drawn uniformly from the minutes of the section in that
   session. Tracked with the same Tracker on a second streaming pass. Fixed seed.

``run_random_parallel`` splits the section by time across worker processes. Pseudo trades never interact
(the Tracker keeps every signal on its own) and close within ``max_hold_minutes``, so the trades are the same
as one pass.
"""
from __future__ import annotations

import multiprocessing
import random
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta

from src.research_lab.of2.backtest import Tracker, Trade
from src.research_lab.of2.config import DAY_MS, HOUR_MS, MINUTE_MS, Config
from src.research_lab.of2.engine import DayLoader, _ms
from src.research_lab.of2.models import MARKET, Signal
from src.research_lab.protocol import CostModel


def _session_window(name: str, cfg: Config) -> tuple[int, int]:
    for n, lo, hi in cfg.sessions:
        if n == name:
            return lo, hi
    raise KeyError(name)


def random_signals(trades: Sequence[Trade], first: date, last: date, cfg: Config, draws: int, seed: int,
                   allowed: Callable[[int, int], bool] | None = None) -> list[Signal]:
    """Pseudo signals for ``draws`` random strategies mirroring the real trades (section [first, last] inclusive).

    ``allowed(minute_ms, direction)``: a selection rule of the strategy that depends on the time alone (OFX direction
    filter). Random entries are redrawn until they obey it too; otherwise a "long only in an uptrend" rule would beat
    random entries by the drift of the market, not by its signals.
    """
    rng = random.Random(seed)
    n_days = (last - first).days + 1
    out: list[Signal] = []
    for draw in range(draws):
        for t in trades:
            s = t.signal
            lo, hi = _session_window(s.session, cfg)
            for _ in range(1000):
                day_ms = _ms(first) + rng.randrange(n_days) * DAY_MS
                minute = day_ms + lo * HOUR_MS + rng.randrange((hi - lo) * 60) * MINUTE_MS
                if allowed is None or allowed(minute, s.direction):
                    break
            else:
                raise ValueError("no random minute obeys the selection rule")
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
               costs: CostModel | None = None) -> list[Trade]:
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


def _run_chunk(loader_factory: Callable[[], DayLoader], first: date, last: date, pseudo: Sequence[Signal],
               cfg: Config, costs: CostModel) -> list[Trade]:
    return run_random(loader_factory(), first, last, pseudo, cfg, costs)


def _fill_day(signal: Signal) -> date:
    """Day of the bar that fills a pseudo signal (the bar after its minute)."""
    return date(1970, 1, 1) + timedelta(days=(signal.signal_ms + MINUTE_MS) // DAY_MS)


def run_random_parallel(loader_factory: Callable[[], DayLoader], first: date, last: date, pseudo: Sequence[Signal],
                        cfg: Config, workers: int = 1, costs: CostModel | None = None) -> list[Trade]:
    """``run_random`` split by time over ``workers`` processes; same trades as one pass.

    The section is cut into ``workers`` contiguous day ranges. Each process takes the pseudo signals that fill
    inside its range and streams from the range start until ``max_hold_minutes`` (rounded up to days, plus one)
    after the range end, never past ``last``. Every pseudo trade is a market order closed by
    ``max_hold_minutes`` at the latest and never interacts with another one, so it ends inside its process's
    window exactly as in one pass, and a trade still open at ``last`` is dropped the same way. Each process
    reads only its own days, so the day loading is split too.

    ``loader_factory`` must be picklable (a module-level function or a ``functools.partial`` of one).
    ``workers <= 1`` runs in this process.
    """
    n_days = (last - first).days + 1
    workers = min(workers, n_days)
    if workers <= 1:
        return run_random(loader_factory(), first, last, pseudo, cfg, costs)
    if any(s.kind != MARKET for s in pseudo):
        raise ValueError("pseudo signals must be market orders")
    spill = timedelta(days=-(-cfg.longest_hold_minutes // (24 * 60)) + 1)
    size = -(-n_days // workers)
    ranges = [(first + timedelta(days=i), min(last, first + timedelta(days=i + size - 1)))
              for i in range(0, n_days, size)]
    parts_in: list[list[Signal]] = [[] for _ in ranges]
    for s in pseudo:
        day = _fill_day(s)
        if first <= day <= last:
            parts_in[(day - first).days // size].append(s)
    jobs = [(lo, min(last, hi + spill), sigs) for (lo, hi), sigs in zip(ranges, parts_in) if sigs]
    if not jobs:
        return []
    ctx = multiprocessing.get_context("fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn")
    with ProcessPoolExecutor(max_workers=len(jobs), mp_context=ctx) as pool:
        parts = list(pool.map(_run_chunk, [loader_factory] * len(jobs), [j[0] for j in jobs], [j[1] for j in jobs],
                              [j[2] for j in jobs], [cfg] * len(jobs), [costs] * len(jobs)))
    return [t for part in parts for t in part]


def strategy_means(trades: Iterable[Trade]) -> dict[int, float]:
    """Mean net R per random strategy (draw index is stored in ``signal.level``)."""
    sums: dict[int, list[float]] = {}
    for t in trades:
        sums.setdefault(int(t.signal.level), []).append(t.net_r)
    return {k: sum(v) / len(v) for k, v in sums.items()}


def p_value(real_mean: float, random_means: Sequence[float]) -> float:
    """Protocol 7.1: (1 + #random >= real) / (1 + draws), one-sided."""
    return (1 + sum(1 for m in random_means if m >= real_mean)) / (1 + len(random_means))
