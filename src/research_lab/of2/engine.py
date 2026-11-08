"""Streaming OF2 engine: consumes S8 days in order, keeps only completed-day and completed-session state,
emits signals at candle closes and lets the tracker follow them minute by minute.

M1/M2 decide on 30-min closes, M3-M6 on 15-min closes; M4-M6 also read the footprint of the closed 15-min candle
(built from the day profile's minutes of that candle only).

Section rule (protocol 3.2, strict): a trade belongs to the section its signal fell in, and only if its
exit was known before the section ended; otherwise it is counted as "offen" and dropped from both sections.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.research_lab.of2.backtest import Tracker, Trade, cost_gate
from src.research_lab.of2.candles import (
    Candle,
    CandleBuilder,
    session_of,
    session_start,
)
from src.research_lab.of2.config import DAY_MS, Config
from src.research_lab.of2.footprint import DayFootprints, Footprint
from src.research_lab.of2.levels import (
    DaySummary,
    Levels,
    SessionState,
    day_summary,
    naked_pocs,
    regime,
)
from src.research_lab.of2.models import (
    Signal,
    absorption,
    acceptance,
    failed_auction,
    sfp,
    stacked_retest,
    stop_run,
)
from src.research_lab.orderflow_ml.bars import DayProfile, MinuteBar
from src.research_lab.protocol import BASE_COSTS, CostModel

DayLoader = Callable[[date], tuple[Sequence[MinuteBar], DayProfile]]


def _ms(day: date) -> int:
    return (day - date(1970, 1, 1)).days * DAY_MS


@dataclass
class EngineStats:
    signale: dict[str, int] = field(default_factory=dict)
    verworfen: dict[str, int] = field(default_factory=dict)
    tage: int = 0
    tage_ohne_level: int = 0

    def hit(self, bucket: dict[str, int], key: str) -> None:
        bucket[key] = bucket.get(key, 0) + 1


class Engine:
    def __init__(self, cfg: Config, costs: CostModel = BASE_COSTS) -> None:
        self.cfg = cfg
        self.tracker = Tracker(cfg, costs)
        self.stats = EngineStats()
        self.days: deque[DaySummary] = deque(maxlen=cfg.npoc_days + 2)
        self.ib_history: dict[str, deque[float]] = {name: deque(maxlen=cfg.ib_history) for name, _, _ in cfg.sessions}
        self.prev_session: SessionState | None = None
        self.session: SessionState | None = None
        self.fired: set[tuple[int, str, int]] = set()  # (day_start, model, direction): one signal per model, direction and day

    # -- levels -----------------------------------------------------------------------------------
    def _levels(self) -> Levels | None:
        if not self.days:
            return None
        prev = self.days[-1]
        npocs = tuple(naked_pocs(list(self.days), self.cfg.npoc_days))
        ps = self.prev_session
        return Levels(prev, npocs, ps.high if ps and ps.seen else None, ps.low if ps and ps.seen else None)

    def _roll_session(self, t: int) -> None:
        start = session_start(t, self.cfg)
        if self.session is None or self.session.start != start:
            if self.session is not None:
                rng = self.session.ib_range
                if rng is not None:
                    self.ib_history[self.session.name].append(rng)
                self.prev_session = self.session
            self.session = SessionState(session_of(t, self.cfg), start)

    # -- one day ----------------------------------------------------------------------------------
    def run_day(self, bars: Sequence[MinuteBar], profile: DayProfile) -> list[Trade]:
        """Process one UTC day; returns the trades that closed during it. Levels come from completed days only."""
        cfg = self.cfg
        day_start = bars[0].window_start_ms
        levels = self._levels()
        if levels is None:
            self.stats.tage_ohne_level += 1
        c30, c15 = CandleBuilder(cfg.tf_value), CandleBuilder(cfg.tf_sfp)
        hist30: list[Candle] = []
        hist15: list[Candle] = []
        fp15: list[Footprint] = []
        first_price = next((b.first_price_e8 / 1e8 for b in bars if b.has_trades), 0.0)
        footprints = DayFootprints(profile, cfg.fp_step_pct, first_price)
        closed: list[Trade] = []
        for bar in bars:
            t = bar.window_start_ms
            self._roll_session(t)
            assert self.session is not None
            closed.extend(self.tracker.push(bar))  # fills and exits of earlier signals, this minute
            self.session.push(bar, cfg)
            # naked POCs touched today stop being naked (past-only: this minute is already over)
            if levels is not None and bar.has_trades:
                lo, hi = bar.low_price_e8 / 1e8, bar.high_price_e8 / 1e8
                touched = tuple(p for p in levels.npocs if lo <= p <= hi)
                if touched:
                    levels = Levels(levels.prev_day, tuple(p for p in levels.npocs if p not in touched),
                                    levels.prev_session_high, levels.prev_session_low)
            if (c := c15.push(bar)) is not None:
                hist15.append(c)
                fp15.append(footprints.candle(c.start, c.minutes))  # minutes of the closed candle only
                if c.has_trades:
                    self.tracker.cancel_on_close(c.close, cfg.tf_sfp)
                if levels is not None:
                    self._consider(sfp(hist15, levels, cfg), day_start, t)
                    self._consider(absorption(hist15, fp15, levels, cfg), day_start, t)
                    self._consider(stacked_retest(hist15, fp15, levels, cfg), day_start, t)
                    self._consider(stop_run(hist15, fp15, levels, cfg), day_start, t)
            if (c := c30.push(bar)) is not None:
                hist30.append(c)
                if c.has_trades:
                    self.tracker.cancel_on_close(c.close, cfg.tf_value)
                if levels is not None:
                    self._consider(failed_auction(hist30, levels, cfg), day_start, t)
                    self._consider(acceptance(hist30, levels, cfg), day_start, t)
        summary = day_summary(bars, profile)
        if summary is not None:
            self.days.append(summary)
        self.stats.tage += 1
        return closed

    def _consider(self, signal: Signal | None, day_start: int, now: int) -> None:
        if signal is None:
            return
        cfg = self.cfg
        key = (day_start, signal.model, signal.direction)
        if key in self.fired:
            return
        assert self.session is not None
        reg = regime(self.session.ib_range, list(self.ib_history[self.session.name]), cfg)
        if signal.model == "M1" and reg == "TREND":
            self.stats.hit(self.stats.verworfen, "M1_trendtag")
            return
        if signal.model == "M2" and reg == "RANGE":
            self.stats.hit(self.stats.verworfen, "M2_rangetag")
            return
        if signal.model == "M5" and reg == "RANGE":   # continuation needs imbalance, not a wide-IB range day
            self.stats.hit(self.stats.verworfen, "M5_rangetag")
            return
        if signal.model == "M6" and reg == "TREND":   # never fade the run on a trend day (Axia)
            self.stats.hit(self.stats.verworfen, "M6_trendtag")
            return
        rr = signal.reward_risk
        if rr is None or rr < cfg.min_rr:
            self.stats.hit(self.stats.verworfen, f"{signal.model}_rr")
            return
        cost = cost_gate(signal, cfg, self.tracker.costs)
        if cost is None or cost > cfg.max_cost_r:
            self.stats.hit(self.stats.verworfen, f"{signal.model}_kosten")
            return
        self.fired.add(key)
        signal = Signal(**{**_fields(signal), "session": self.session.name, "regime": reg})
        self.stats.hit(self.stats.signale, f"{signal.model}|{signal.session}|{'OF' if signal.confirmed else 'PREIS'}")
        self.tracker.add(signal)


def _fields(signal: Signal) -> dict:
    return {name: getattr(signal, name) for name in Signal.__slots__}  # type: ignore[attr-defined]


def run_days(loader: DayLoader, days: Iterable[date], cfg: Config, costs: CostModel = BASE_COSTS) -> tuple[list[Trade], Engine]:
    """Run the engine over consecutive days (lead days included by the caller). Missing days raise."""
    engine = Engine(cfg, costs)
    trades: list[Trade] = []
    previous: date | None = None
    for day in days:
        if previous is not None and day != previous + timedelta(days=1):
            raise ValueError(f"days must be consecutive: {previous} -> {day}")
        bars, profile = loader(day)
        trades.extend(engine.run_day(bars, profile))
        previous = day
    return trades, engine


def section_trades(trades: Iterable[Trade], lo_ms: int, hi_ms: int) -> tuple[list[Trade], int]:
    """Trades whose signal fell in [lo, hi) and whose exit was known before hi; second value = open at the end."""
    inside, open_at_end = [], 0
    for t in trades:
        if lo_ms <= t.signal.signal_ms < hi_ms:
            if t.exit_ms < hi_ms:
                inside.append(t)
            else:
                open_at_end += 1
    return inside, open_at_end
