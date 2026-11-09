"""Run the OF2 engine split by time over several processes (same trades and counters as one pass).

The days are cut into contiguous ranges. Every process starts ``warmup_days`` before its range, so the engine
state that reaches across days is the same as in one pass when the range begins:

* the previous days for levels and naked POCs (``npoc_days + 2`` days),
* the initial-balance history per session (``ib_history`` sessions, one per day),
* the open and pending orders (an order waits at most one day and is held at most ``max_hold_minutes``).

Signals fired on the first warm-up days can differ (their history is still short), but those orders are gone
before the range starts. A process keeps only what happens on its own days: the trades that close there and
the counters (signals, rejections, days, expired and cancelled orders) counted there. Trades still open after
the last day are dropped exactly as ``run_days`` drops them.
"""
from __future__ import annotations

import multiprocessing
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.research_lab.of2.backtest import Trade
from src.research_lab.of2.config import Config
from src.research_lab.of2.engine import DayLoader, Engine, EngineStats
from src.research_lab.protocol import BASE_COSTS, CostModel


def warmup_days(cfg: Config) -> int:
    order_days = -(-(cfg.max_hold_minutes + 24 * 60) // (24 * 60))  # one day pending + max hold
    return max(cfg.npoc_days + 2, cfg.ib_history) + order_days + 1


@dataclass
class TrackerCounts:
    expired: int = 0
    cancelled: int = 0


@dataclass
class EngineTotals:
    """What callers read from an ``Engine`` after a run: ``stats`` and ``tracker.expired/cancelled``."""
    stats: EngineStats = field(default_factory=EngineStats)
    tracker: TrackerCounts = field(default_factory=TrackerCounts)


def _snapshot(engine: Engine) -> tuple[dict[str, int], dict[str, int], int, int, int, int]:
    s = engine.stats
    return dict(s.signale), dict(s.verworfen), s.tage, s.tage_ohne_level, engine.tracker.expired, engine.tracker.cancelled


def _run_range(loader_factory: Callable[[], DayLoader], days: Sequence[date], lo: int, hi: int, warm: int,
               cfg: Config, costs: CostModel) -> tuple[list[Trade], EngineTotals]:
    loader = loader_factory()
    engine = Engine(cfg, costs)
    start = max(0, lo - warm)
    for i in range(start, lo):
        engine.run_day(*loader(days[i]))
    if lo > 0 and any(len(h) < (h.maxlen or 0) for h in engine.ib_history.values()):
        raise RuntimeError(f"{days[lo]}: initial-balance history not full after the warm-up; run with one process")
    before = _snapshot(engine)
    trades: list[Trade] = []
    for i in range(lo, hi + 1):
        trades.extend(engine.run_day(*loader(days[i])))
    after = _snapshot(engine)
    totals = EngineTotals()
    for k, v in after[0].items():
        if v - before[0].get(k, 0):
            totals.stats.signale[k] = v - before[0].get(k, 0)
    for k, v in after[1].items():
        if v - before[1].get(k, 0):
            totals.stats.verworfen[k] = v - before[1].get(k, 0)
    totals.stats.tage, totals.stats.tage_ohne_level = after[2] - before[2], after[3] - before[3]
    totals.tracker.expired, totals.tracker.cancelled = after[4] - before[4], after[5] - before[5]
    return trades, totals


def run_days_parallel(loader_factory: Callable[[], DayLoader], days: Sequence[date], cfg: Config, workers: int = 1,
                      costs: CostModel = BASE_COSTS) -> tuple[list[Trade], EngineTotals | Engine]:
    """``run_days`` over ``workers`` processes. Same closed trades (sorted by exit, then signal) and counters.

    ``loader_factory`` must be picklable (a module-level function or a ``functools.partial`` of one).
    ``workers <= 1`` or too few days for a warm-up per range runs ``run_days`` in this process.
    """
    from src.research_lab.of2.engine import run_days

    days = list(days)
    for a, b in zip(days, days[1:]):
        if b != a + timedelta(days=1):
            raise ValueError(f"days must be consecutive: {a} -> {b}")
    warm = warmup_days(cfg)
    workers = min(workers, len(days) // max(warm, 1))
    if workers <= 1:
        return run_days(loader_factory(), days, cfg, costs)
    size = -(-len(days) // workers)
    ranges = [(i, min(len(days) - 1, i + size - 1)) for i in range(0, len(days), size)]
    ctx = multiprocessing.get_context("fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn")
    with ProcessPoolExecutor(max_workers=len(ranges), mp_context=ctx) as pool:
        parts = list(pool.map(_run_range, [loader_factory] * len(ranges), [days] * len(ranges),
                              [r[0] for r in ranges], [r[1] for r in ranges], [warm] * len(ranges),
                              [cfg] * len(ranges), [costs] * len(ranges)))
    trades: list[Trade] = []
    total = EngineTotals()
    for part_trades, part in parts:
        trades.extend(part_trades)
        for k, v in part.stats.signale.items():
            total.stats.signale[k] = total.stats.signale.get(k, 0) + v
        for k, v in part.stats.verworfen.items():
            total.stats.verworfen[k] = total.stats.verworfen.get(k, 0) + v
        total.stats.tage += part.stats.tage
        total.stats.tage_ohne_level += part.stats.tage_ohne_level
        total.tracker.expired += part.tracker.expired
        total.tracker.cancelled += part.tracker.cancelled
    trades.sort(key=lambda t: (t.exit_ms, t.signal.signal_ms, t.signal.model))
    return trades, total
