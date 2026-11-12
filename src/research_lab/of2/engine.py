"""Streaming OF2 engine: consumes S8 days in order, keeps only completed-day and completed-session state,
emits signals at candle closes and lets the tracker follow them minute by minute.

M1/M2 decide on 30-min closes, M3-M6 on 15-min closes; M4-M6 also read the footprint of the closed 15-min candle
(built from the day profile's minutes of that candle only).

Section rule (protocol 3.2, strict): a trade belongs to the section its signal fell in, and only if its
exit was known before the section ended; otherwise it is counted as "offen" and dropped from both sections.
"""
from __future__ import annotations

import dataclasses
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

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
    DayVolume,
    Levels,
    SessionState,
    day_summary,
    day_volume,
    naked_pocs,
    period_summary,
    regime,
)
from src.research_lab.of2.models import (
    Signal,
    absorption,
    acceptance,
    failed_auction,
    poor_edge,
    sfp,
    stacked_retest,
    stop_run,
)
from src.research_lab.orderflow_ml.bars import DayProfile, MinuteBar
from src.research_lab.protocol import CostModel

DayLoader = Callable[[date], tuple[Sequence[MinuteBar], DayProfile]]


def _ms(day: date) -> int:
    return (day - date(1970, 1, 1)).days * DAY_MS


@dataclass
class EngineStats:
    signale: dict[str, int] = field(default_factory=dict)
    verworfen: dict[str, int] = field(default_factory=dict)
    trichter: dict[str, int] = field(default_factory=dict)  # per model: kandidat, bestaetigt, frei, risiko_ok
    tage: int = 0
    tage_ohne_level: int = 0

    def hit(self, bucket: dict[str, int], key: str) -> None:
        bucket[key] = bucket.get(key, 0) + 1


class Engine:
    def __init__(self, cfg: Config, costs: CostModel | None = None) -> None:
        self.cfg = cfg
        self.tracker = Tracker(cfg, costs)
        self.stats = EngineStats()
        self.days: deque[DaySummary] = deque(maxlen=cfg.npoc_days + 2)
        self.ib_history: dict[str, deque[float]] = {name: deque(maxlen=cfg.ib_history) for name, _, _ in cfg.sessions}
        self.prev_session: SessionState | None = None
        self.session: SessionState | None = None
        self.extra_15m: tuple = ()  # extra detectors (hist15, levels, cfg) -> Signal | None; empty = OF2 1.0 unchanged
        self.fired: set[tuple[int, str, int]] = set()  # (day_start, model, direction): one signal per model, direction and day
        # Swing track (off when ``swing_tf`` is 0): candles across days, marks of the last completed week or month.
        self.swing_builder = CandleBuilder(cfg.swing_tf) if cfg.swing_tf else None
        self.swing_hist: deque[Candle] = deque(maxlen=cfg.swing_history)
        self.swing_days: deque[DayVolume] = deque(maxlen=70)
        self.swing_cfg = dataclasses.replace(cfg, tf_value=cfg.swing_tf, tf_sfp=cfg.swing_tf) if cfg.swing_tf else cfg

    # -- levels -----------------------------------------------------------------------------------
    def _levels(self) -> Levels | None:
        if not self.days:
            return None
        prev = self.days[-1]
        npocs = tuple(naked_pocs(list(self.days), self.cfg.npoc_days))
        ps = self.prev_session
        return Levels(prev, npocs, ps.high if ps and ps.seen else None, ps.low if ps and ps.seen else None)

    def _swing_levels(self, day_start: int) -> tuple[Levels | None, int]:
        """Marks of the week or month that ended before ``day_start`` (complete periods only) and the start of the
        running week (the slot key: one swing signal per model, direction and week)."""
        today = datetime.fromtimestamp(day_start / 1000, tz=timezone.utc).date()
        monday = today - timedelta(days=today.weekday())
        if self.cfg.swing_level == "W":
            first, last = monday - timedelta(days=7), monday - timedelta(days=1)
        else:
            last = today.replace(day=1) - timedelta(days=1)
            first = last.replace(day=1)
        lo, hi = _ms(first), _ms(last)
        inside = [d for d in self.swing_days if lo <= d[0].day_start <= hi]
        summary = period_summary(inside) if len(inside) == (last - first).days + 1 else None
        return (Levels(summary) if summary is not None else None), _ms(monday)

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
        swing_levels, week_start = self._swing_levels(day_start) if self.swing_builder is not None else (None, 0)
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
                    self._consider(poor_edge(hist15, fp15, levels, cfg), day_start, t)
                    for extra in self.extra_15m:
                        self._consider(extra(hist15, levels, cfg), day_start, t)
            if (c := c30.push(bar)) is not None:
                hist30.append(c)
                if c.has_trades:
                    self.tracker.cancel_on_close(c.close, cfg.tf_value)
                if levels is not None:
                    self._consider(failed_auction(hist30, levels, cfg), day_start, t)
                    self._consider(acceptance(hist30, levels, cfg), day_start, t)
            if self.swing_builder is not None and (c := self.swing_builder.push(bar)) is not None:
                self.swing_hist.append(c)
                if c.has_trades:
                    self.tracker.cancel_on_close(c.close, cfg.swing_tf)
                if swing_levels is not None:
                    hist, scfg = list(self.swing_hist), self.swing_cfg
                    for found in (failed_auction(_last_excursion(hist, swing_levels), swing_levels, scfg),
                                  acceptance(hist, swing_levels, scfg),
                                  sfp(hist, swing_levels, scfg)):
                        if found is not None:
                            swing = Signal(**{**_fields(found), "model": "S" + found.model[1:], "tf": cfg.swing_tf})
                            self._consider(swing, week_start, t)
        summary = day_summary(bars, profile)
        if summary is not None:
            self.days.append(summary)
            if self.swing_builder is not None:
                self.swing_days.append(day_volume(summary, profile))
        self.stats.tage += 1
        return closed

    def _consider(self, signal: Signal | None, day_start: int, now: int) -> None:
        if signal is None:
            return
        cfg = self.cfg
        key = (day_start, signal.model, signal.direction)
        self.stats.hit(self.stats.trichter, f"{signal.model}|kandidat")
        if signal.confirmed:
            self.stats.hit(self.stats.trichter, f"{signal.model}|bestaetigt")
        if key in self.fired:
            return
        if cfg.of_gate and not signal.confirmed:
            self.stats.hit(self.stats.verworfen, f"{signal.model}_ohne_of")
            return
        self.stats.hit(self.stats.trichter, f"{signal.model}|frei")
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
        if signal.model == "M7" and reg == "TREND":   # range edges hold on balance days, not in a trend
            self.stats.hit(self.stats.verworfen, "M7_trendtag")
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
        self.stats.hit(self.stats.trichter, f"{signal.model}|risiko_ok")
        signal = Signal(**{**_fields(signal), "session": self.session.name, "regime": reg})
        self.stats.hit(self.stats.signale, f"{signal.model}|{signal.session}|{'OF' if signal.confirmed else 'PREIS'}")
        self.tracker.add(signal)


def _last_excursion(hist: list[Candle], lv: Levels) -> list[Candle]:
    """The swing history from the start of the last run of closes outside the value area (before the two closes
    back inside). The intraday M1 reads the whole day; across weeks only the excursion that just failed counts."""
    d = lv.prev_day
    i = len(hist) - 2
    while i > 0 and hist[i - 1].has_trades and not d.val <= hist[i - 1].close <= d.vah:
        i -= 1
    return hist[i:]


def _fields(signal: Signal) -> dict:
    return {name: getattr(signal, name) for name in Signal.__slots__}  # type: ignore[attr-defined]


def funnel(trichter: dict[str, int], trades: Iterable[Trade]) -> dict[str, dict[str, int]]:
    """Signal funnel per model: candidates -> confirmed -> slot free -> risk passed -> filled and closed.
    ``bestaetigt`` counts every confirmed candidate (also after the slot was taken); with ``of_gate`` off the
    later steps include price-only signals."""
    out: dict[str, dict[str, int]] = {}
    for key, n in sorted(trichter.items()):
        model, step = key.split("|")
        out.setdefault(model, {"kandidat": 0, "bestaetigt": 0, "frei": 0, "risiko_ok": 0, "geschlossen": 0,
                               "geschlossen_bestaetigt": 0})[step] = n
    for t in trades:
        row = out.setdefault(t.signal.model, {"kandidat": 0, "bestaetigt": 0, "frei": 0, "risiko_ok": 0,
                                              "geschlossen": 0, "geschlossen_bestaetigt": 0})
        row["geschlossen"] += 1
        row["geschlossen_bestaetigt"] += bool(t.signal.confirmed)
    return out


def run_days(loader: DayLoader, days: Iterable[date], cfg: Config, costs: CostModel | None = None) -> tuple[list[Trade], Engine]:
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
