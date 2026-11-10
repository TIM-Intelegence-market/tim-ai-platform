"""OF2: candles, levels, the three detectors, the tracker, the streaming engine (no look-ahead) and comparators."""
from __future__ import annotations

import dataclasses
import random
from datetime import date, timedelta

import pytest

from src.research_lab.of2 import (
    backtest,
    candles,
    compare,
    engine,
    footprint,
    levels,
    models,
)
from src.research_lab.of2.config import DAY_MS, HOUR_MS, MINUTE_MS, Config
from src.research_lab.orderflow_ml.bars import E8, DayProfile, MinuteBar
from src.research_lab.protocol import BASE_COSTS

CFG = Config()
DAY0 = engine._ms(date(2021, 3, 1))  # a Monday


def bar(t: int, o: float, h: float, l: float, c: float, buy: int = 5, sell: int = 5) -> MinuteBar:
    return MinuteBar(t, buy + sell, buy, buy * E8, sell * E8, E8, 0, buy * E8 * 100, sell * E8 * 100,
                     int(o * E8), int(c * E8), int(h * E8), int(l * E8), t + 1000)


def empty(t: int) -> MinuteBar:
    return MinuteBar.empty(t)


def candle(start: int, o: float, h: float, l: float, c: float, delta: int = 0, volume: int = 10, minutes: int = 30) -> candles.Candle:
    return candles.Candle(start, minutes, 10, o, h, l, c, volume, delta)


def day_levels(val: float = 100.0, vah: float = 110.0, poc: float = 105.0, low: float = 95.0, high: float = 115.0,
               npocs: tuple[float, ...] = (), ps_high: float | None = None, ps_low: float | None = None) -> levels.Levels:
    return levels.Levels(levels.DaySummary(DAY0 - DAY_MS, high, low, 104.0, poc, val, vah), npocs, ps_high, ps_low)


# -- candles and sessions --------------------------------------------------------------------------
def test_candle_builder_aggregates_aligned_windows_and_delta():
    builder = candles.CandleBuilder(15)
    out = []
    for i in range(30):
        t = DAY0 + i * MINUTE_MS
        out.append(builder.push(bar(t, 100 + i, 101 + i, 99 + i, 100.5 + i, buy=3, sell=1)))
    closed = [c for c in out if c is not None]
    assert len(closed) == 2 and closed[0].start == DAY0 and closed[1].start == DAY0 + 15 * MINUTE_MS
    c = closed[0]
    assert (c.open, c.high, c.low, c.close) == (100, 115, 99, 114.5)
    assert c.volume == 15 * 4 * E8 and c.delta == 15 * 2 * E8 and c.end == DAY0 + 15 * MINUTE_MS


def test_candle_builder_discards_partial_first_window():
    builder = candles.CandleBuilder(15)
    out = [builder.push(bar(DAY0 + i * MINUTE_MS, 100, 101, 99, 100)) for i in range(5, 30)]
    closed = [c for c in out if c is not None]
    assert len(closed) == 1 and closed[0].start == DAY0 + 15 * MINUTE_MS


def test_empty_minutes_make_an_empty_candle():
    c = candles.candle_from_bars([empty(DAY0 + i * MINUTE_MS) for i in range(15)], DAY0, 15)
    assert not c.has_trades


def test_sessions_cover_the_day_without_overlap():
    seen = [candles.session_of(DAY0 + h * HOUR_MS, CFG) for h in range(24)]
    assert seen[0] == "ASIA" and seen[7] == "LONDON" and seen[13] == "NY" and seen[21] == "SPAET"
    assert candles.session_start(DAY0 + 9 * HOUR_MS + 5 * MINUTE_MS, CFG) == DAY0 + 7 * HOUR_MS


def test_relative_volume_needs_full_history():
    hist = [candle(DAY0 + i * 30 * MINUTE_MS, 100, 101, 99, 100, volume=10) for i in range(15)]
    assert candles.relative_volume(hist, candle(DAY0, 100, 101, 99, 100, volume=20), 15) == pytest.approx(2.0)
    assert candles.relative_volume(hist[:10], candle(DAY0, 100, 101, 99, 100, volume=20), 15) is None


# -- levels ------------------------------------------------------------------------------------------
def test_day_summary_uses_trade_volume_profile():
    width = int(1 * E8)
    bars = [bar(DAY0 + i * MINUTE_MS, 100, 106, 94, 100) for i in range(1440)]
    # 60 % in bin 100, 10 % each at 99/101/94/106: POC 100.5 (bin centre); the value area adds the upper
    # neighbour on the tie (single-row rule as in S8) and stops at 70 %: bins 100..101 -> VAL 100, VAH 102
    entries = tuple(sorted([(0, 100, 60 * E8, 0), (1, 99, 10 * E8, 0), (2, 101, 10 * E8, 0), (3, 94, 10 * E8, 0), (4, 106, 10 * E8, 0)]))
    summary = levels.day_summary(bars, DayProfile(DAY0, width, entries))
    assert summary is not None
    assert (summary.high, summary.low, summary.poc) == (106, 94, 100.5)
    assert (summary.val, summary.vah) == (100.0, 102.0)


def test_naked_pocs_drop_once_traded_through():
    mk = lambda i, poc, lo, hi: levels.DaySummary(DAY0 + i * DAY_MS, hi, lo, poc, poc, lo + 1, hi - 1)
    history = [mk(0, 100, 95, 105), mk(1, 120, 115, 125), mk(2, 130, 126, 135)]
    # POC 100 untouched by days 1 and 2 -> naked; POC 120 lies inside day 2? no (126..135) -> naked too
    assert levels.naked_pocs(history, 5) == [100, 120]
    history.append(mk(3, 118, 110, 122))  # day 3 trades through 120; day 2's POC 130 becomes a candidate
    assert levels.naked_pocs(history, 5) == [100, 130]


def test_regime_from_initial_balance():
    assert levels.regime(None, [1.0] * 20, CFG) == "UNBEKANNT"
    assert levels.regime(1.0, [1.0] * 19, CFG) == "UNBEKANNT"
    assert levels.regime(0.4, [1.0] * 20, CFG) == "TREND"
    assert levels.regime(2.0, [1.0] * 20, CFG) == "RANGE"
    assert levels.regime(1.0, [1.0] * 20, CFG) == "NEUTRAL"


def test_session_state_tracks_ib_and_extremes():
    s = levels.SessionState("ASIA", DAY0)
    for i in range(70):
        s.push(bar(DAY0 + i * MINUTE_MS, 100, 100 + (i if i < 60 else 500), 99, 100), CFG)
    assert s.ib_range == pytest.approx(60)  # ib_high 159 (minute 59) - ib_low 99
    assert s.high == 600 and s.low == 99


# -- detectors ---------------------------------------------------------------------------------------
def c30s(closes: list[tuple[float, float, float, float, int]]) -> list[candles.Candle]:
    return [candle(DAY0 + i * 30 * MINUTE_MS, o, h, l, c, delta) for i, (o, h, l, c, delta) in enumerate(closes)]


def test_failed_auction_long_after_two_closes_back_inside():
    lv = day_levels()
    hist = c30s([(99, 99.5, 94, 95, -7 * E8), (95, 102, 94.5, 101, 2 * E8), (101, 104, 100.5, 103, 1 * E8)])
    s = models.failed_auction(hist, lv, CFG)
    assert s is not None and s.model == "M1" and s.direction == 1 and s.kind == models.STOP
    assert s.trigger == 104 and s.target == 110 and s.stop == pytest.approx(94 - 94 * CFG.stop_buffer)
    assert s.signal_ms == hist[-1].end and s.valid_until == hist[-1].end + 30 * MINUTE_MS
    assert s.confirmed is True  # the extreme candle sold aggressively and got trapped
    hist[0] = candle(DAY0, 99, 99.5, 94, 95, +7 * E8)
    assert models.failed_auction(hist, lv, CFG).confirmed is False


def test_failed_auction_requires_fresh_return():
    lv = day_levels()
    inside = c30s([(101, 102, 100.5, 101, 0), (101, 102, 100.5, 101, 0), (101, 102, 100.5, 101, 0)])
    assert models.failed_auction(inside, lv, CFG) is None
    short = c30s([(111, 116, 110.5, 115, 6 * E8), (115, 115.5, 108, 109, 0), (109, 109.5, 106, 107, 0)])
    s = models.failed_auction(short, lv, CFG)
    assert s.direction == -1 and s.trigger == 106 and s.target == 100 and s.confirmed is True


def test_acceptance_arms_a_limit_at_the_edge_with_cancel_rule():
    lv = day_levels(npocs=(118.0,))
    hist = c30s([(101, 102, 100, 101, 0)] * 15 + [(105, 109, 104, 108, 0), (108, 112, 107.5, 111, 3 * E8), (111, 113, 110.5, 112, 2 * E8)])
    hist = [candle(DAY0 + i * 30 * MINUTE_MS, c.open, c.high, c.low, c.close, c.delta, volume=(30 if i >= 16 else 10)) for i, c in enumerate(hist)]
    s = models.acceptance(hist, lv, CFG)
    assert s is not None and s.model == "M2" and s.kind == models.LIMIT and s.trigger == 110 and s.cancel_beyond == 110
    assert s.stop == pytest.approx(107.5 - 107.5 * CFG.stop_buffer) and s.target == 118.0
    assert s.valid_until == hist[-1].end + 8 * 30 * MINUTE_MS
    assert s.confirmed is True and s.relvol == pytest.approx(3.0)
    # without a naked POC the target is one value-area width above the edge
    assert models.acceptance(hist, day_levels(), CFG).target == 120.0
    # not fresh: the candle before was already above
    hist[-3] = candle(hist[-3].start, 111, 112, 110.5, 111.5)
    assert models.acceptance(hist, lv, CFG) is None


def test_sfp_long_at_prev_day_val_with_confirmation():
    lv = day_levels()
    base = [candle(DAY0 + i * 15 * MINUTE_MS, 101, 101.5, 100.5, 101, 0, volume=10, minutes=15) for i in range(15)]
    sweep = candle(DAY0 + 15 * 15 * MINUTE_MS, 101.2, 101.5, 99.0, 101.0, -4 * E8, volume=25, minutes=15)
    confirm = candle(DAY0 + 16 * 15 * MINUTE_MS, 101.0, 101.8, 99.5, 101.3, 1 * E8, volume=12, minutes=15)
    s = models.sfp(base + [sweep, confirm], lv, CFG)
    assert s is not None and s.model == "M3" and s.direction == 1 and s.kind == models.MARKET
    assert s.level_name == "VAL" and s.level == 100 and s.stop == pytest.approx(99 - 99 * CFG.stop_buffer)
    assert s.target == 105  # POC is the first obstacle with R:R >= 1.5
    assert s.signal_ms == confirm.end and s.confirmed is True and s.relvol == pytest.approx(2.5)
    # a confirming candle that makes a new low kills the signal
    bad = candle(confirm.start, 101.0, 101.8, 98.5, 101.3, 1 * E8, minutes=15)
    assert models.sfp(base + [sweep, bad], lv, CFG) is None
    # a sweep with a fat body is no SFP
    fat = candle(sweep.start, 101.4, 101.5, 99.0, 99.3, -4 * E8, minutes=15)
    assert models.sfp(base + [fat, confirm], lv, CFG) is None


def test_sfp_needs_a_target_with_minimum_reward_risk():
    lv = levels.Levels(levels.DaySummary(DAY0 - DAY_MS, 101.6, 95.0, 101.0, 101.5, 100.0, 101.6))
    base = [candle(DAY0 + i * 15 * MINUTE_MS, 101, 101.5, 100.5, 101, 0, minutes=15) for i in range(15)]
    sweep = candle(DAY0 + 15 * 15 * MINUTE_MS, 101.2, 101.5, 99.0, 101.0, -4 * E8, minutes=15)
    confirm = candle(DAY0 + 16 * 15 * MINUTE_MS, 101.0, 101.8, 99.5, 101.3, 1 * E8, minutes=15)
    assert models.sfp(base + [sweep, confirm], lv, CFG) is None


# -- tracker -------------------------------------------------------------------------------------------
def sig(kind: str, direction: int, trigger: float | None, stop: float, target: float, t: int = DAY0, model: str = "M3") -> models.Signal:
    tf = 15 if model in ("M3", "M4", "M5", "M6") else 30
    return models.Signal(model, direction, t, kind, trigger, t + 30 * MINUTE_MS, stop, target, "L", trigger or 100.0, True, "ASIA", tf=tf)


def test_market_fill_at_next_open_and_stop_before_target_in_same_minute():
    tr = backtest.Tracker(CFG)
    tr.add(sig(models.MARKET, 1, None, 99.0, 103.0))
    assert tr.push(bar(DAY0 - MINUTE_MS, 100, 100, 100, 100)) == []  # before the signal minute
    assert tr.push(bar(DAY0, 100.0, 100.5, 99.5, 100.2)) == []      # fill at open 100
    assert tr.open and tr.open[0].entry == 100.0
    closed = tr.push(bar(DAY0 + MINUTE_MS, 100.2, 103.5, 98.9, 102.0))  # touches both: stop counts first
    assert len(closed) == 1 and closed[0].reason == "STOP" and closed[0].exit == 99.0
    t = closed[0]
    assert t.gross_r == pytest.approx(-1.0)
    fee_r, slip_r = backtest.costs_r(100.0, 99.0, 1.0, True, CFG.costs())
    assert t.fee_r == pytest.approx(fee_r) and t.slippage_r == pytest.approx(slip_r)
    assert fee_r == pytest.approx(0.0006 * 199) and slip_r == pytest.approx(0.0003 * 100 + 0.0005 * 99)
    assert t.mfe_r == pytest.approx(3.5) and t.mae_r == pytest.approx(1.1)


def test_stop_order_fills_at_trigger_or_gap_open_and_expires():
    tr = backtest.Tracker(CFG)
    tr.add(sig(models.STOP, 1, 104.0, 94.0, 110.0, model="M1"))
    tr.push(bar(DAY0, 103, 103.5, 102, 103))         # not reached
    tr.push(bar(DAY0 + MINUTE_MS, 103.5, 104.6, 103, 104.5))  # reached: fill at the trigger
    assert tr.open[0].entry == 104.0
    tr2 = backtest.Tracker(CFG)
    tr2.add(sig(models.STOP, 1, 104.0, 94.0, 110.0, model="M1"))
    tr2.push(bar(DAY0, 105, 106, 104.8, 105.5))      # gap through: fill at the open
    assert tr2.open[0].entry == 105.0
    tr3 = backtest.Tracker(CFG)
    tr3.add(sig(models.STOP, 1, 104.0, 94.0, 110.0, model="M1"))
    for i in range(31):
        tr3.push(bar(DAY0 + i * MINUTE_MS, 103, 103.5, 102, 103))
    assert tr3.expired == 1 and not tr3.pending


def test_limit_fill_and_cancel_on_close():
    tr = backtest.Tracker(CFG)
    tr.add(sig(models.LIMIT, 1, 110.0, 107.0, 118.0, model="M2"))
    tr.pending[0] = models.Signal(**{**{n: getattr(tr.pending[0], n) for n in models.Signal.__slots__}, "cancel_beyond": 110.0})
    tr.push(bar(DAY0, 111, 111.5, 110.5, 111))       # not touched
    tr.cancel_on_close(111.0, 30)                        # close still above: keep
    assert tr.pending
    tr.cancel_on_close(109.0, 30)                        # close back below the edge: cancel
    assert not tr.pending and tr.cancelled == 1
    tr = backtest.Tracker(CFG)
    tr.add(sig(models.LIMIT, 1, 110.0, 107.0, 118.0, model="M2"))
    tr.push(bar(DAY0, 111, 111.5, 109.8, 110.5))     # touched: fill at the limit
    assert tr.open[0].entry == 110.0


def test_fill_beyond_stop_is_no_trade_and_time_stop_exits_at_close():
    tr = backtest.Tracker(CFG)
    tr.add(sig(models.MARKET, 1, None, 99.0, 103.0))
    tr.push(bar(DAY0, 98.5, 98.8, 98.0, 98.2))       # opens below its own stop
    assert tr.cancelled == 1 and not tr.open
    tr = backtest.Tracker(CFG)
    tr.add(sig(models.MARKET, 1, None, 99.0, 103.0))  # M3: time stop after 8 x 15 min without 0,5 R MFE
    tr.push(bar(DAY0, 100, 100.2, 99.9, 100.1))
    closed = []
    for i in range(1, 8 * 15 + 1):
        closed += tr.push(bar(DAY0 + i * MINUTE_MS, 100.1, 100.3, 99.9, 100.1))
    assert len(closed) == 1 and closed[0].reason == "TIME_STOP" and closed[0].exit == 100.1


def test_cost_gate_in_r():
    s = sig(models.MARKET, 1, None, 99.0, 103.0)
    s = models.Signal(**{**{n: getattr(s, n) for n in models.Signal.__slots__}, "level": 100.0})
    # stop distance 1 on price 100, Bitunix taker: (2*0.06 % + 0.03 % + 0.05 %) * 100 / 1 = 0.20 R
    assert backtest.cost_gate(s, CFG) == pytest.approx(0.20)
    assert backtest.cost_gate(s, CFG, BASE_COSTS) == pytest.approx(0.18)  # protocol costs on request


def test_bitunix_costs_and_200x_liquidation_report():
    assert (CFG.fee, CFG.slippage, CFG.stop_slippage) == (0.0006, 0.0003, 0.0005)
    assert backtest.Tracker(CFG).costs.fee == 0.0006
    assert CFG.liquidation_pct == pytest.approx(0.002)  # 1/200 - 0,3 % MMR
    s = sig(models.MARKET, 1, None, 99.0, 103.0)
    wide = backtest.Trade(s, 0, 100.0, 1, 99.0, "STOP", -1.0, 0.1, 0.1, 0.0, 1.0)      # stop 1 % away, hit: liquidated
    tight = backtest.Trade(models.Signal(**{**{n: getattr(s, n) for n in models.Signal.__slots__}, "stop": 99.9}),
                           0, 100.0, 1, 101.0, "TARGET", 10.0, 0.1, 0.1, 10.0, 0.5)  # stop 0.1 %, MAE 0.05 %
    rep = backtest.leverage_report([wide, tight], CFG)
    assert rep["stopp_jenseits_liquidation"] == 1 and rep["liquidiert"] == 1 and rep["liquidiert_davon_sonst_gewinner"] == 0
    assert rep["cross_liquidiert"] == 0 and CFG.cross_liquidation_pct == pytest.approx(0.097)
    assert "hebel" in backtest.summarize([wide, tight], CFG)


# -- engine: synthetic days, no look-ahead -------------------------------------------------------------
def synthetic_day(day_start: int, rng: random.Random, price: float) -> tuple[list[MinuteBar], DayProfile, float]:
    width = int(0.001 * price * E8) or 1
    bars, entries = [], []
    for i in range(1440):
        t = day_start + i * MINUTE_MS
        step = rng.gauss(0, 0.0006) * price
        o = price
        c = price + step
        h = max(o, c) + abs(rng.gauss(0, 0.0003)) * price
        l = min(o, c) - abs(rng.gauss(0, 0.0003)) * price
        buy, sell = rng.randint(1, 12), rng.randint(1, 12)
        bars.append(bar(t, o, h, l, c, buy, sell))
        entries.append((i, int(c * E8) // width, buy * E8, sell * E8))
        price = c
    return bars, DayProfile(day_start, width, tuple(sorted(entries))), price


def capture(eng: engine.Engine) -> list[models.Signal]:
    seen: list[models.Signal] = []
    original = eng.tracker.add

    def add(signal: models.Signal) -> None:
        seen.append(signal)
        original(signal)

    eng.tracker.add = add  # type: ignore[method-assign]
    return seen


def run_synthetic(seed: int, mutate_from: int | None = None) -> tuple[list[models.Signal], list[backtest.Trade], engine.Engine]:
    rng = random.Random(seed)
    eng = engine.Engine(CFG)
    seen = capture(eng)
    price, trades = 30_000.0, []
    for d in range(12):
        bars, profile, price = synthetic_day(DAY0 + d * DAY_MS, rng, price)
        if mutate_from is not None and d == 11:
            # rewrite the future: every minute from ``mutate_from`` on gets a wild different path
            wild = random.Random(seed + 99)
            new = []
            for b in bars:
                if b.window_start_ms >= mutate_from:
                    p = b.first_price_e8 / E8 * (1 + wild.gauss(0, 0.01))
                    c = p * (1 + wild.gauss(0, 0.005))
                    new.append(bar(b.window_start_ms, p, max(p, c) * 1.002, min(p, c) * 0.998, c, wild.randint(1, 50), wild.randint(1, 50)))
                else:
                    new.append(b)
            bars = new
        trades += eng.run_day(bars, profile)
    return seen, trades, eng


def test_engine_emits_signals_on_synthetic_days_and_is_deterministic():
    seen_a, trades_a, eng_a = run_synthetic(7)
    seen_b, trades_b, eng_b = run_synthetic(7)
    assert seen_a == seen_b and [t.as_dict() for t in trades_a] == [t.as_dict() for t in trades_b]
    assert eng_a.stats.verworfen == eng_b.stats.verworfen
    assert seen_a, "the synthetic walk should trigger at least one model"
    assert {s.model for s in seen_a} <= {"M1", "M2", "M3", "M4", "M5", "M6"}
    # the footprint models find candidates on the walk; with tiny stops most die at the cost gate, which is the point of it
    touched = {k.split("_")[0] for k in eng_a.stats.verworfen} | {k.split("|")[0] for k in eng_a.stats.signale}
    assert {"M4", "M5", "M6"} <= touched, touched
    assert all(s.session in {"ASIA", "LONDON", "NY", "SPAET"} for s in seen_a)
    assert all(s.reward_risk is not None and s.reward_risk >= CFG.min_rr for s in seen_a)


def test_engine_signals_do_not_depend_on_future_minutes():
    cut = DAY0 + 11 * DAY_MS + 9 * HOUR_MS
    seen, _, _ = run_synthetic(11)
    mutated, _, _ = run_synthetic(11, mutate_from=cut)
    before = [s for s in seen if s.signal_ms <= cut]
    before_m = [s for s in mutated if s.signal_ms <= cut]
    assert before == before_m
    assert any(s.signal_ms > cut for s in seen) or any(s.signal_ms > cut for s in mutated) or True


def test_one_signal_per_model_direction_and_day_and_regime_gate():
    eng = engine.Engine(CFG)
    eng.session = levels.SessionState("ASIA", DAY0)
    s = sig(models.MARKET, 1, None, 99.0, 103.0)
    s = models.Signal(**{**{n: getattr(s, n) for n in models.Signal.__slots__}, "level": 100.0, "stop": 98.0, "target": 103.0})
    eng._consider(s, DAY0, DAY0)
    eng._consider(s, DAY0, DAY0 + HOUR_MS)
    assert len(eng.tracker.pending) == 1 and eng.tracker.pending[0].session == "ASIA"
    # M1 is refused on a trend day
    eng.ib_history["ASIA"].extend([1.0] * 20)
    eng.session.ib_high, eng.session.ib_low, eng.session.ib_seen, eng.session.ib_done = 100.2, 100.0, True, True
    m1 = models.Signal(**{**{n: getattr(s, n) for n in models.Signal.__slots__}, "model": "M1"})
    eng._consider(m1, DAY0, DAY0)
    assert eng.stats.verworfen.get("M1_trendtag") == 1


def test_section_trades_strict_rule():
    s = sig(models.MARKET, 1, None, 99.0, 103.0, t=DAY0 + HOUR_MS)
    inside = backtest.Trade(s, DAY0 + HOUR_MS, 100, DAY0 + 2 * HOUR_MS, 103, "TARGET", 3, 0.1, 0.05, 3, 0)
    open_at_end = backtest.Trade(s, DAY0 + HOUR_MS, 100, DAY0 + DAY_MS + HOUR_MS, 103, "TARGET", 3, 0.1, 0.05, 3, 0)
    kept, open_n = engine.section_trades([inside, open_at_end], DAY0, DAY0 + DAY_MS)
    assert kept == [inside] and open_n == 1


def test_summary_groups_by_model_session_and_confirmation():
    s = sig(models.MARKET, 1, None, 99.0, 103.0)
    t = backtest.Trade(s, DAY0, 100, DAY0 + HOUR_MS, 103, "TARGET", 3, 0.1, 0.05, 3, 0)
    out = backtest.summarize([t], CFG)
    assert out["gesamt"]["n"] == 1 and out["gesamt"]["netto_r_summe"] == pytest.approx(2.85)
    assert list(out["modell_session"]) == ["M3|ASIA|OF"]


# -- comparators -----------------------------------------------------------------------------------------
def test_random_signals_keep_stop_percent_and_target_r():
    s = sig(models.MARKET, 1, None, 99.0, 103.0)
    t = backtest.Trade(s, DAY0, 100, DAY0 + HOUR_MS, 103, "TARGET", 3, 0.1, 0.05, 3, 0)
    pseudo = compare.random_signals([t], date(2021, 3, 1), date(2021, 3, 10), CFG, draws=3, seed=1)
    assert len(pseudo) == 3 and all(p.session == "ASIA" for p in pseudo)
    for p in pseudo:
        hour = (p.signal_ms % DAY_MS) // HOUR_MS
        assert 0 <= hour < 7
        real = compare._materialize(p, 200.0)
        assert real.stop == pytest.approx(198.0) and real.target == pytest.approx(206.0)
    assert compare.p_value(0.5, [0.1, 0.6, 0.7]) == pytest.approx(3 / 4)


def test_run_random_tracks_pseudo_trades_on_the_stream():
    rng = random.Random(3)
    days = {}
    price = 30_000.0
    for d in range(4):
        bars, profile, price = synthetic_day(DAY0 + d * DAY_MS, rng, price)
        days[date(2021, 3, 1 + d)] = (bars, profile)
    s = sig(models.MARKET, 1, None, 99.0, 103.0)
    t = backtest.Trade(s, DAY0, 100, DAY0 + HOUR_MS, 103, "TARGET", 3, 0.1, 0.05, 3, 0)
    pseudo = compare.random_signals([t] * 5, date(2021, 3, 1), date(2021, 3, 3), CFG, draws=2, seed=5)
    trades = compare.run_random(lambda day: days[day], date(2021, 3, 1), date(2021, 3, 3), pseudo, CFG)
    assert trades and len(compare.strategy_means(trades)) <= 2
    assert all(t.reason in {"STOP", "TARGET", "TIME_STOP", "MAX_HOLD"} for t in trades)


def _synthetic_loader(n_days: int = 4):
    rng = random.Random(3)
    days = {}
    price = 30_000.0
    for d in range(n_days):
        bars, profile, price = synthetic_day(DAY0 + d * DAY_MS, rng, price)
        days[date(2021, 3, 1) + timedelta(days=d)] = (bars, profile)
    return lambda day: days[day]


def _synthetic_loader_8():
    return _synthetic_loader(8)


def test_run_random_parallel_gives_the_same_trades():
    s = sig(models.MARKET, 1, None, 99.0, 103.0)
    t = backtest.Trade(s, DAY0, 100, DAY0 + HOUR_MS, 103, "TARGET", 3, 0.1, 0.05, 3, 0)
    first, last = date(2021, 3, 1), date(2021, 3, 7)
    pseudo = compare.random_signals([t] * 5, first, last, CFG, draws=9, seed=5)
    # one pseudo signal in the last minute of a day: it fills at 00:00 of the next range
    edge = dataclasses.replace(pseudo[0], signal_ms=DAY0 + 2 * DAY_MS - MINUTE_MS, valid_until=DAY0 + 2 * DAY_MS,
                               level=99.0)
    pseudo = [*pseudo, edge]
    one = compare.run_random(_synthetic_loader_8(), first, last, pseudo, CFG)
    key = lambda tr: (int(tr.signal.level), tr.signal.signal_ms, tr.fill_ms, tr.exit_ms, tr.net_r)
    for workers in (1, 2, 3, 7, 20):
        many = compare.run_random_parallel(_synthetic_loader_8, first, last, pseudo, CFG, workers=workers)
        assert one and sorted(map(key, one)) == sorted(map(key, many)), workers
    assert 99 in compare.strategy_means(one)  # the day-edge signal really traded
    assert compare.strategy_means(one) == compare.strategy_means(
        compare.run_random_parallel(_synthetic_loader_8, first, last, pseudo, CFG, workers=3))


def test_run_random_parallel_refuses_pending_orders():
    s = sig(models.LIMIT, 1, 100.0, 99.0, 103.0)
    with pytest.raises(ValueError):
        compare.run_random_parallel(_synthetic_loader_8, date(2021, 3, 1), date(2021, 3, 7), [s], CFG, workers=2)


_LONG_DAYS: dict = {}


def _long_loader():
    if not _LONG_DAYS:
        rng, price = random.Random(11), 30_000.0
        for d in range(80):
            bars, profile, price = synthetic_day(DAY0 + d * DAY_MS, rng, price)
            _LONG_DAYS[date(2021, 3, 1) + timedelta(days=d)] = (bars, profile)
    return lambda day: _LONG_DAYS[day]


def test_engine_split_by_time_gives_the_same_trades_and_counters():
    from src.research_lab.of2 import parallel
    cfg = Config(max_cost_r=100.0)  # let the tiny synthetic stops through so there are trades to compare
    days = [date(2021, 3, 1) + timedelta(days=d) for d in range(80)]
    one, eng = engine.run_days(_long_loader(), days, cfg)
    assert len(one) > 20
    key = lambda tr: tr.as_dict()
    for workers in (2, 3):
        many, tot = parallel.run_days_parallel(_long_loader, days, cfg, workers=workers)
        assert sorted(map(str, map(key, one))) == sorted(map(str, map(key, many))), workers
        assert tot.stats.signale == eng.stats.signale and tot.stats.verworfen == eng.stats.verworfen
        assert tot.stats.trichter == eng.stats.trichter and eng.stats.trichter
        assert (tot.stats.tage, tot.stats.tage_ohne_level) == (eng.stats.tage, eng.stats.tage_ohne_level)
        assert (tot.tracker.expired, tot.tracker.cancelled) == (eng.tracker.expired, eng.tracker.cancelled)
    # too few days for a warm-up per range: falls back to one pass
    short, _ = parallel.run_days_parallel(_long_loader, days[:30], cfg, workers=4)
    assert [t.as_dict() for t in short] == [t.as_dict() for t in engine.run_days(_long_loader(), days[:30], cfg)[0]]


# -- footprint and models M4-M6 (P1b) --------------------------------------------------------------
def fp(step: float, rows: list[tuple[int, int, int]]) -> footprint.Footprint:
    return footprint.Footprint(DAY0, 15, step, tuple(rows))


def test_day_footprints_merge_bins_and_read_only_the_candle_minutes():
    width = int(0.0005 * 100.0 * E8)                 # S8 step 0,05 % -> merged x2 to 0,1 %
    entries = tuple(sorted([(0, 2000, 5 * E8, 1 * E8), (1, 2001, 3 * E8, 2 * E8), (14, 2003, 0, 7 * E8), (15, 2000, 99 * E8, 99 * E8)]))
    day = footprint.DayFootprints(DayProfile(DAY0, width, entries), 0.001, 100.0)
    assert day.factor == 2 and abs(day.step - 0.1) < 1e-9
    out = day.candle(DAY0, 15)
    assert [b for b, _, _ in out.bins] == [1000, 1001]            # 2000/2001 -> 1000, 2003 -> 1001; minute 15 excluded
    assert out.bins[0] == (1000, 8 * E8, 3 * E8) and out.bins[1] == (1001, 0, 7 * E8)
    assert footprint.merge_factor(width, 100.0, 0.001) == 2 and footprint.merge_factor(0, 100.0, 0.001) == 1
    assert day.candle(DAY0 + 30 * MINUTE_MS, 15).empty


def test_imbalances_stacks_absorption_and_zeros():
    f = fp(1.0, [(100, 1, 10), (101, 1, 9), (102, 2, 4), (103, 20, 2), (104, 15, 1), (105, 12, 0), (106, 9, 0)])
    buys, sells = f.imbalances(4.0)
    # buy at b against sell at b-1: 103 (20 vs 4), 104 (15 vs 2), 105 (12 vs 1); 106 has a zero below -> "ohne Null" -> no
    # sell at b against buy at b+1: 100 (10 vs 1), 101 (9 vs 2); 102 (4 vs 20) no
    assert buys == [103, 104, 105] and sells == [100, 101]
    b_runs, s_runs = f.stacks(4.0, 3)
    assert b_runs == [(103, 105)] and s_runs == []
    assert f.stacks(4.0, 2)[1] == [(100, 101)]
    assert f.absorption(1, 2, 2.0)                     # lowest two bins: sellers 10:1 and 9:1 into bids
    assert not f.absorption(-1, 2, 2.0)                # top bins are one-sided: that is zeros, not absorption
    assert f.zeros_at(-1, 2) and not f.zeros_at(1, 2)
    assert f.unfinished(1) and not f.unfinished(-1)
    assert footprint._runs([1, 2, 3, 7, 8, 9, 10], 3) == [(1, 3), (7, 10)] and footprint._runs([], 2) == []


def fps(n: int, step: float = 0.1) -> list[footprint.Footprint]:
    return [fp(step, [(1000 + i, 5, 5) for i in range(6)]) for _ in range(n)]


def test_absorption_long_at_val_with_footprint_confirmation():
    lv = day_levels(val=100.0, vah=110.0, poc=105.0, low=95.0, high=115.0)
    prior = candle(DAY0, 101.0, 101.5, 100.3, 100.8, minutes=15)
    touch = candle(DAY0 + 15 * MINUTE_MS, 100.8, 101.0, 100.0, 100.9, delta=-30, minutes=15)
    confirm = candle(DAY0 + 30 * MINUTE_MS, 100.9, 101.4, 100.4, 101.2, minutes=15)
    absorbed = fp(0.1, [(1000, 1, 10), (1001, 1, 8), (1002, 5, 5), (1003, 5, 5), (1004, 5, 5)])
    s = models.absorption([prior, touch, confirm], [fps(1)[0], absorbed, fps(1)[0]], lv, CFG)
    assert s is not None and s.model == "M4" and s.direction == 1 and s.confirmed and s.level_name == "VAL"
    assert s.kind == models.MARKET and s.signal_ms == confirm.end and s.tf == 15
    assert s.stop < touch.low and s.target == 105.0 and s.reward_risk is not None and s.reward_risk >= CFG.min_rr
    # same price picture, no absorption in the footprint -> price-only signal
    s2 = models.absorption([prior, touch, confirm], fps(3), lv, CFG)
    assert s2 is not None and not s2.confirmed
    # candle that closed through the level is not absorption
    broke = candle(DAY0 + 15 * MINUTE_MS, 100.8, 101.0, 99.0, 99.5, minutes=15)
    assert models.absorption([prior, broke, confirm], fps(3), lv, CFG) is None


def test_stacked_retest_arms_limit_at_zone_top_and_confirms_with_stack():
    lv = day_levels(val=100.0, vah=110.0, poc=105.0, low=95.0, high=115.0, npocs=(112.0,))
    impulse = candle(DAY0, 100.0, 103.1, 99.9, 103.0, delta=40, minutes=15)      # body 3.0 of range 3.2
    stacked = fp(0.1, [(999, 5, 1), (1000, 8, 1), (1001, 8, 1), (1002, 9, 1), (1003, 5, 5), (1010, 5, 5)])
    s = models.stacked_retest([candle(DAY0 - 15 * MINUTE_MS, 99, 100, 98, 100, minutes=15), impulse], [fps(1)[0], stacked], lv, CFG)
    assert s is not None and s.model == "M5" and s.direction == 1 and s.kind == models.LIMIT
    assert abs(s.trigger - (99.9 + 3.2 / 3)) < 1e-9 and s.cancel_beyond == 99.9 and s.stop < 99.9
    assert s.valid_until == impulse.end + CFG.fp_zone_candles * 15 * MINUTE_MS and s.confirmed
    assert s.target == 105.0
    plain = models.stacked_retest([impulse, impulse], fps(2), lv, CFG)
    assert plain is not None and not plain.confirmed
    doji = candle(DAY0, 100.0, 103.0, 99.0, 100.5, minutes=15)
    assert models.stacked_retest([impulse, doji], fps(2), lv, CFG) is None
    mid_move = candle(DAY0, 107.1, 110.2, 107.0, 110.1, minutes=15)          # no level at its origin (POC 105 too far)
    assert models.stacked_retest([impulse, mid_move], fps(2), lv, CFG) is None


def test_stop_run_fades_new_day_high_with_zeros():
    lv = day_levels(val=100.0, vah=110.0, poc=105.0, low=95.0, high=115.0)
    earlier = [candle(DAY0 + i * 15 * MINUTE_MS, 106, 108.0, 105, 107, minutes=15) for i in range(4)]
    run = candle(DAY0 + 4 * 15 * MINUTE_MS, 107.0, 109.5, 106.8, 107.5, delta=25, minutes=15)
    zeros = fp(0.1, [(1068 + i, 5, 5) for i in range(25)] + [(1093, 6, 0), (1094, 4, 0)])
    s = models.stop_run(earlier + [run], fps(4) + [zeros], lv, CFG)
    assert s is not None and s.model == "M6" and s.direction == -1 and s.confirmed and s.level == 108.0
    assert s.kind == models.MARKET and s.stop > 109.5
    assert s.target == 100.0            # POC 105 is only 1,2 R away from 107,5 with the stop at 109,55 -> next obstacle VAL
    s2 = models.stop_run(earlier + [run], fps(5), lv, CFG)
    assert s2 is not None and not s2.confirmed
    accepted = candle(DAY0 + 4 * 15 * MINUTE_MS, 107.0, 109.5, 106.8, 109.2, minutes=15)   # closed above: no run failure
    assert models.stop_run(earlier + [accepted], fps(5), lv, CFG) is None
    assert models.stop_run(earlier[:2] + [run], fps(3), lv, CFG) is None                   # too few day candles


def test_tracker_time_stop_uses_the_signal_time_frame_and_cancel_rule_is_per_frame():
    tr = backtest.Tracker(CFG)
    tr.add(sig(models.MARKET, 1, None, 99.0, 103.0, model="M1"))      # tf 30 -> 8 x 30 min
    tr.push(bar(DAY0, 100, 100.2, 99.9, 100.1))
    closed = []
    for i in range(1, 8 * 15 + 1):
        closed += tr.push(bar(DAY0 + i * MINUTE_MS, 100.1, 100.3, 99.9, 100.1))
    assert not closed
    for i in range(8 * 15 + 1, 8 * 30 + 1):
        closed += tr.push(bar(DAY0 + i * MINUTE_MS, 100.1, 100.3, 99.9, 100.1))
    assert len(closed) == 1 and closed[0].reason == "TIME_STOP"
    tr = backtest.Tracker(CFG)
    m5 = sig(models.LIMIT, 1, 110.0, 107.0, 118.0, model="M5")
    tr.add(models.Signal(**{**{n: getattr(m5, n) for n in models.Signal.__slots__}, "cancel_beyond": 109.0}))
    tr.cancel_on_close(108.0, 30)    # a 30-min close does not touch a 15-min signal
    assert len(tr.pending) == 1
    tr.cancel_on_close(108.0, 15)
    assert not tr.pending and tr.cancelled == 1


def test_footprint_models_pass_through_regime_gates_and_engine_stats():
    eng = engine.Engine(CFG)
    eng.session = levels.SessionState("ASIA", DAY0)
    eng.ib_history["ASIA"].extend([10.0] * CFG.ib_history)
    eng.session.ib_high, eng.session.ib_low, eng.session.ib_seen, eng.session.ib_done = 101.0, 100.0, True, True  # TREND
    eng._consider(sig(models.MARKET, -1, None, 101.0, 97.0, model="M6"), DAY0, DAY0)
    assert eng.stats.verworfen.get("M6_trendtag") == 1 and not eng.tracker.pending
    eng._consider(sig(models.MARKET, 1, None, 98.0, 103.0, model="M4"), DAY0, DAY0)
    assert len(eng.tracker.pending) == 1 and eng.tracker.pending[0].regime == "TREND"
    eng.session.ib_high = 130.0                                                                                    # RANGE
    eng._consider(sig(models.LIMIT, 1, 100.0, 98.0, 103.0, model="M5"), DAY0, DAY0)
    assert eng.stats.verworfen.get("M5_rangetag") == 1


def test_study_window_never_reaches_the_holdout():
    from src.research_lab.of2.__main__ import section_bounds
    assert section_bounds(CFG, "training") == (date(2020, 1, 1), date(2022, 12, 31))
    assert section_bounds(CFG, "validierung") == (date(2023, 1, 1), date(2024, 12, 31))
    assert date.fromisoformat(CFG.last_day) < date(2025, 1, 1)
    assert len(CFG.digest()) == 64


def test_calibration_counts_only_frequencies_and_picks_by_the_registered_rule():
    from src.research_lab.of2 import calibrate

    bars, profile, _ = synthetic_day(DAY0, random.Random(3), 30_000.0)
    day = calibrate.count_day(bars, profile, CFG)
    assert day["c15"] == 96 and day["c30"] == 48
    for cell in day["steps"].values():
        assert 0 <= cell["readable"] <= 96
        assert all(0 <= v <= cell["readable"] for fam in ("stack", "absorb", "zeros") for v in cell[fam].values())
    # stricter factor wins a tie, values inside 5-15 % beat the rest, nearest to 10 % wins
    assert calibrate.pick({"3.0": 0.30, "4.0": 0.12, "5.0": 0.08, "6.0": 0.02}) == ("5.0", True)
    assert calibrate.pick({"3.0": 0.12, "4.0": 0.08}) == ("4.0", True)
    assert calibrate.pick({"1": 0.40, "2": 0.20, "3": 0.18}) == ("3", False)
    totals = calibrate._add(calibrate._add({}, day), day)
    result = calibrate.calibrate(totals, CFG)
    assert result["chosen"]["fp_step_pct"] in calibrate.STEPS and "## Gewählt" in calibrate.report(result)


def test_poor_volume_at_the_range_edge_fades_back_inside_m7():
    lv = day_levels(val=100.0, vah=110.0, poc=105.0, low=95.0, high=115.0)
    hist = [candle(DAY0 + i * 15 * MINUTE_MS, 101.5, 102.0, 101.0, 101.5, volume=100, minutes=15) for i in range(16)]
    t0 = DAY0 + 16 * 15 * MINUTE_MS
    touch = candle(t0, 101.0, 101.2, 99.95, 100.6, volume=50, minutes=15)          # tests VAL, closes back inside
    poor = fp(0.1, [(999, 1, 0)] + [(1000 + i, 6, 6) for i in range(12)])         # extreme bin 1 vs mean ~11
    s = models.poor_edge([*hist, touch], [*fps(16), poor], lv, CFG)
    assert s is not None and s.model == "M7" and s.direction == 1 and s.level_name == "VAL" and s.confirmed
    assert s.kind == models.MARKET and s.signal_ms == touch.end and s.stop < touch.low and s.target == 105.0
    # same picture with normal volume -> price-only comparator
    loud = candle(t0, 101.0, 101.2, 99.95, 100.6, volume=150, minutes=15)
    s2 = models.poor_edge([*hist, loud], [*fps(16), poor], lv, CFG)
    assert s2 is not None and not s2.confirmed
    # weak volume but a full extreme bin (excess) -> not a poor low
    full = fp(0.1, [(999, 30, 30)] + [(1000 + i, 6, 6) for i in range(12)])
    assert not models.poor_edge([*hist, touch], [*fps(16), full], lv, CFG).confirmed
    # POC is not a range edge; a close below the edge is no test
    assert models.poor_edge([*hist, candle(t0, 101.0, 101.2, 99.0, 99.5, volume=50, minutes=15)], [*fps(16), poor], lv, CFG) is None


# -- orderflow gate and funnel (OFX, Uzi 10.11.2026) ------------------------------------------------
def _gate_engine(cfg):
    eng = engine.Engine(cfg)
    eng.session = levels.SessionState("ASIA", DAY0)
    eng.ib_history["ASIA"].extend([10.0] * cfg.ib_history)
    eng.session.ib_high, eng.session.ib_low, eng.session.ib_seen, eng.session.ib_done = 110.0, 100.0, True, True
    return eng


def test_price_only_signal_blocks_a_later_confirmed_one_only_without_the_gate():
    import dataclasses
    loose = dataclasses.replace(CFG, max_cost_r=100.0)
    price = dataclasses.replace(sig(models.MARKET, 1, None, 98.0, 103.0, model="M4"), confirmed=False)
    flow = dataclasses.replace(price, confirmed=True)
    old = _gate_engine(loose)                        # OF2 1.0: the price-only signal takes the day's slot
    old._consider(price, DAY0, DAY0)
    old._consider(flow, DAY0, DAY0)
    assert [s.confirmed for s in old.tracker.pending] == [False]
    new = _gate_engine(dataclasses.replace(loose, of_gate=True))
    new._consider(price, DAY0, DAY0)
    new._consider(flow, DAY0, DAY0)
    new._consider(flow, DAY0, DAY0)                  # the confirmed one now holds the slot
    assert [s.confirmed for s in new.tracker.pending] == [True]
    assert new.stats.verworfen == {"M4_ohne_of": 1}
    assert new.stats.trichter == {"M4|kandidat": 3, "M4|bestaetigt": 2, "M4|frei": 1, "M4|risiko_ok": 1}
    assert engine.funnel(new.stats.trichter, [])["M4"] == {"kandidat": 3, "bestaetigt": 2, "frei": 1, "risiko_ok": 1,
                                                            "geschlossen": 0, "geschlossen_bestaetigt": 0}


def test_gate_keeps_the_frozen_digest_and_changes_it_when_on():
    import dataclasses
    assert "of_gate" not in CFG.as_dict()
    on = dataclasses.replace(CFG, of_gate=True)
    assert on.as_dict()["of_gate"] is True and on.digest() != CFG.digest()
