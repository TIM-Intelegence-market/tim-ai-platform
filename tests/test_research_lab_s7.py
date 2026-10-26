"""Study S7 rules (docs/research_lab/studien/S7_3_4R_TRENDFOLGE_AUSBRUCH_PRAEREGISTRIERUNG.md): channel without
the current bar, SMA filter, causality, geometry, gaps and the outcome-blind count."""
from __future__ import annotations

import random

from src.research_lab.backtest.engine import History, run_backtest
from src.research_lab.backtest.indicators import atr, sma_close
from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses import s7
from src.research_lab.protocol import BASE_COSTS
from src.research_lab.stats.random_entry import atr_at_signal

H4 = s7.INTERVAL_MS
T0 = 1_577_836_800_000  # 2020-01-01T00:00:00Z


def bar(i: int, o: float, h: float, l: float, c: float, *, t0: int = T0) -> Kline:
    return Kline(t0 + i * H4, o, h, l, c, 10.0, t0 + (i + 1) * H4 - 1, 5.0)


def walk(n: int, seed: int, *, scale: float = 0.02, drift: float = 0.0) -> list[Kline]:
    rng = random.Random(seed)
    price, bars = 100.0, []
    for i in range(n):
        o = price
        c = o * (1 + drift + rng.gauss(0, scale))
        h = max(o, c) * (1 + abs(rng.gauss(0, scale / 2)))
        l = min(o, c) * (1 - abs(rng.gauss(0, scale / 2)))
        bars.append(bar(i, o, h, l, c))
        price = c
    return bars


def test_four_variants_with_frozen_geometry() -> None:
    assert [v.variant_id for v in s7.S7_VARIANTS] == ["S7-D20-T3", "S7-D20-T4", "S7-D55-T3", "S7-D55-T4"]
    assert {v.channel for v in s7.S7_VARIANTS} == {20, 55}
    assert {v.target_r for v in s7.S7_VARIANTS} == {3.0, 4.0}
    bars = walk(1500, 1)
    seen = 0
    for variant in s7.S7_VARIANTS:
        strategy = s7.breakout(variant)
        for t in range(len(bars)):
            signal = strategy(History(bars, t))
            if signal is None:
                continue
            seen += 1
            history = History(bars, t)
            close = bars[t].close
            width = atr(history, s7.ATR_PERIOD)
            assert signal.target_r == variant.target_r
            assert signal.time_stop_bars == s7.TIME_STOP_BARS
            expected_risk = max(s7.ATR_FACTOR * width, s7.MIN_STOP_DISTANCE * close)
            assert abs(abs(close - signal.stop) - expected_risk) < 1e-9
            assert (close - signal.stop) * signal.side > 0
            high, low = s7.channel(history, variant.channel)
            sma = sma_close(history, s7.SMA_PERIOD)
            if signal.side == 1:
                assert close > high and close > sma
            else:
                assert close < low and close < sma
    assert seen > 0


def test_channel_excludes_current_bar() -> None:
    bars = walk(300, 2)
    history = History(bars, 299)
    high, low = s7.channel(history, 20)
    assert high == max(b.high for b in bars[279:299])
    assert low == min(b.low for b in bars[279:299])
    assert bars[299] not in bars[279:299]


def test_breakout_requires_trend_filter() -> None:
    # 199 flat bars at 100, one bar closing above the 20-bar channel but below the SMA of a falling series
    bars = [bar(i, 200 - i * 0.5, 200 - i * 0.5 + 0.1, 200 - i * 0.5 - 0.1, 200 - i * 0.5) for i in range(199)]
    last_close = 200 - 198 * 0.5
    bars.append(bar(199, last_close, last_close + 3.0, last_close - 0.1, last_close + 2.0))  # above channel
    history = History(bars, 199)
    sma = sma_close(history, 200)
    assert bars[199].close < sma  # above the channel, below the SMA: no long
    assert s7.breakout(s7.S7_VARIANTS[0])(history) is None


def test_signals_do_not_depend_on_later_bars() -> None:
    bars = walk(900, 3)
    variant = s7.S7_VARIANTS[2]
    strategy = s7.breakout(variant)
    full = [strategy(History(bars, t)) for t in range(len(bars))]
    cut = bars[:600]
    assert [strategy(History(cut, t)) for t in range(len(cut))] == full[:600]
    # changing bar 601 changes nothing before it
    altered = list(bars)
    altered[601] = bar(601, 1.0, 1.0, 1.0, 1.0)
    assert [s7.breakout(variant)(History(altered, t)) for t in range(601)] == full[:601]


def test_minimum_stop_distance_is_one_percent() -> None:
    # tiny ranges: ATR far below 1 % of the price, the stop still sits 1 % away
    bars = [bar(i, 100.0, 100.001, 99.999, 100.0) for i in range(220)]
    bars.append(bar(220, 100.0, 100.01, 100.0, 100.005))  # closes above channel and SMA
    signal = s7.breakout(s7.S7_VARIANTS[0])(History(bars, 220))
    assert signal is not None and signal.side == 1
    assert abs((bars[220].close - signal.stop) / bars[220].close - 0.01) < 1e-9


def test_gap_inside_indicator_window_blocks_the_signal() -> None:
    bars = walk(400, 4, drift=0.01)
    variant = s7.S7_VARIANTS[0]
    counts = s7.Counts()
    strategy = s7.breakout(variant, counts)
    signals = [t for t in range(len(bars)) if strategy(History(bars, t)) is not None]
    assert signals
    t = signals[-1]
    shifted = list(bars)
    for i in range(t - 5, len(bars)):  # remove one bar before t: the window is no longer contiguous
        shifted[i] = Kline(bars[i].open_time + H4, bars[i].open, bars[i].high, bars[i].low, bars[i].close, 10.0,
                           bars[i].close_time + H4, 5.0)
    counts2 = s7.Counts()
    assert s7.breakout(variant, counts2)(History(shifted, t)) is None
    assert counts2.skipped_gap == 1


def test_engine_trade_geometry_and_time_stop() -> None:
    bars = walk(1200, 5, drift=0.002)
    variant = s7.S7_VARIANTS[1]
    result = run_backtest(bars, s7.breakout(variant), H4, costs=BASE_COSTS, atr_at_signal=atr_at_signal,
                          gap_entry_as_loss=True)
    assert result.trades
    for trade in result.trades:
        assert trade.target_r == 4.0
        assert trade.bars_held <= s7.TIME_STOP_BARS
        if trade.reason == "time":
            assert trade.bars_held == s7.TIME_STOP_BARS
        if trade.reason == "target":
            assert trade.r > 3.5  # 4 R minus costs
        if trade.reason == "stop":
            assert -1.3 < trade.r < -0.99
        # entry one bar after the signal
        assert trade.entry_time == trade.signal_time + H4
    reasons = {t.reason for t in result.trades}
    assert reasons & {"stop", "target", "time"}


def test_count_is_outcome_blind_and_matches_the_engine_signals() -> None:
    bars = walk(1500, 6, drift=0.001)
    variant = s7.S7_VARIANTS[0]
    start, end = bars[300].open_time, bars[1400].open_time
    count = s7.count_signals(bars, variant, start, end)
    # upper bound: every emitted signal in the window, independent of positions
    strategy = s7.breakout(variant)
    emitted = sum(1 for t in range(300, 1400) if strategy(History(bars, t)) is not None)
    assert count.upper == emitted
    # lower bound: spacing of 30 bars, at most what the engine could ever take
    result = run_backtest(bars, s7.breakout(variant), H4, start_ms=start, end_ms=end, gap_entry_as_loss=True)
    taken = len(result.trades)
    assert count.lower <= taken + result.invalid_signals <= count.upper
    assert all(b - a >= s7.TIME_STOP_BARS * H4 for a, b in zip(count.lower_times, count.lower_times[1:]))
    # the same count when all prices after the last counted bar change: no outcome enters the count
    altered = bars[:1400] + [bar(i, 1.0, 1.0, 1.0, 1.0) for i in range(1400, 1500)]
    assert s7.count_signals(altered, variant, start, end) == count


def test_iso_week_and_year() -> None:
    assert s7.iso_week(T0) == "2020-W01"
    assert s7.year_of(T0) == 2020
    assert s7.iso_week(1_609_372_800_000) == "2020-W53"  # 2020-12-31
