"""Study S4 rules (docs/research_lab/studien/S4_TREFFERQUOTE_75_PRAEREGISTRIERUNG.md): causality, cost gate,
geometry, gap entries and the outcome-blind count."""
from __future__ import annotations

import random

import pytest

from src.research_lab.backtest.engine import History, Signal, run_backtest
from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses import s4
from src.research_lab.protocol import BASE_COSTS

H = 3_600_000
DAY = 86_400_000
T0 = 1_577_836_800_000  # 2020-01-01T00:00:00Z


def bar(i: int, o: float, h: float, l: float, c: float, *, vol: float = 10.0, buy: float = 5.0, t0: int = T0) -> Kline:
    return Kline(t0 + i * H, o, h, l, c, vol, t0 + (i + 1) * H - 1, buy)


def walk(n: int, seed: int, *, scale: float = 0.012, t0: int = T0) -> list[Kline]:
    rng = random.Random(seed)
    price, bars = 100.0, []
    for i in range(n):
        o = price
        c = o * (1 + rng.gauss(0, scale))
        h = max(o, c) * (1 + abs(rng.gauss(0, scale / 2)))
        l = min(o, c) * (1 - abs(rng.gauss(0, scale / 2)))
        vol = 10 + rng.random() * 10
        bars.append(bar(i, o, h, l, c, vol=vol, buy=vol * rng.random(), t0=t0))
        price = c
    return bars


def daily_from(hours: list[Kline]) -> list[Kline]:
    days: dict[int, list[Kline]] = {}
    for b in hours:
        days.setdefault(b.open_time // DAY, []).append(b)
    out = []
    for key in sorted(days):
        group = days[key]
        if len(group) == 24:
            out.append(Kline(key * DAY, group[0].open, max(b.high for b in group), min(b.low for b in group),
                             group[-1].close, sum(b.volume for b in group), key * DAY + DAY - 1,
                             sum(b.taker_buy_volume for b in group)))
    return out


def all_strategies(daily: list[Kline]):
    regime = s4.DailyRegime(daily)
    return {v.variant_id: v.build(regime, s4.Counts()) for v in s4.S4_VARIANTS}


def test_ten_variants_with_frozen_geometry() -> None:
    assert len(s4.S4_VARIANTS) == 10
    assert len({v.variant_id for v in s4.S4_VARIANTS}) == 10
    assert {v.hypothesis for v in s4.S4_VARIANTS} == {"H1", "H2", "H3", "H4", "H5"}
    bars = walk(2500, 1)
    daily = daily_from(bars)
    seen = 0
    for name, strategy in all_strategies(daily).items():
        for t in range(len(bars)):
            signal = strategy(History(bars, t))
            if signal is None:
                continue
            seen += 1
            assert signal.target_r == s4.TARGET_R
            close = bars[t].close
            assert (close - signal.stop) * signal.side > 0
            assert abs(close - signal.stop) / close >= s4.MIN_STOP_DISTANCE
            if name.startswith("S4-H5"):
                assert signal.time_stop_bars == s4.H5_LAST_BAR_HOUR - (bars[t].open_time // H) % 24
            else:
                assert signal.time_stop_bars == s4.TIME_STOP_BARS
    assert seen > 0


def test_signals_do_not_depend_on_later_bars() -> None:
    """Look-ahead test (section 9, P1): changing every bar after t never changes the signal at t."""
    bars = walk(2200, 2)
    daily = daily_from(bars)
    cut = 1900
    altered = bars[: cut + 1] + [Kline(b.open_time, b.open * 3, b.high * 3, b.low * 3, b.close * 3, b.volume * 7,
                                       b.close_time, b.taker_buy_volume) for b in bars[cut + 1:]]
    altered_daily = daily_from(altered)
    first, second = all_strategies(daily), all_strategies(altered_daily)
    for name in first:
        for t in range(cut - 300, cut + 1):
            assert first[name](History(bars, t)) == second[name](History(altered, t)), (name, t)


def test_cost_gate_blocks_tight_stops_and_counts_them() -> None:
    flat = [bar(i, 100, 100.1, 99.9, 100) for i in range(80)]
    tight = flat + [bar(80, 99.95, 100.08, 99.85, 100.05)]  # sweep 99.85 < 99.9, close back in the upper half
    counts = s4.Counts()
    assert s4.h1_sweep(24, counts)(History(tight, 80)) is None  # stop ~99.8 is only ~0.25 % away
    assert counts.skipped_cost == 1
    wide = flat + [bar(80, 99.95, 100.08, 98.6, 100.05)]
    signal = s4.h1_sweep(24, s4.Counts())(History(wide, 80))
    assert signal is not None and signal.side == 1
    assert abs(100.05 - signal.stop) / 100.05 >= 0.01


def test_cost_gate_boundary() -> None:
    counts = s4.Counts()
    assert s4._gate(1, 100.0, 99.0, counts, 0) is not None  # exactly 1.0 % passes
    assert s4._gate(1, 100.0, 99.01, counts, 0) is None
    assert counts.skipped_cost == 1
    assert s4._gate(1, 100.0, 101.0, counts, 0) is None  # stop on the wrong side: no signal, not a cost skip
    assert counts.skipped_cost == 1


def test_regime_uses_only_days_closed_by_the_hourly_close() -> None:
    days = [Kline(T0 + i * DAY, 100, 100, 100, 100.0 if i < 20 else 110.0, 1, T0 + (i + 1) * DAY - 1, 0.5)
            for i in range(22)]
    regime = s4.DailyRegime(days)
    assert regime.at(days[20].close_time) == s4.UP  # 21 closes: day 20 (110) vs day 0 (100); the 23:00 bar closes with the day
    assert regime.at(days[20].close_time - 1) is None  # day 20 not closed yet: only 20 closes
    flat = s4.DailyRegime([Kline(T0 + i * DAY, 100, 100, 100, 100 + i * 0.1, 1, T0 + (i + 1) * DAY - 1, 0.5)
                           for i in range(22)])
    assert flat.at(T0 + 22 * DAY) == s4.SIDEWAYS
    down = s4.DailyRegime([Kline(T0 + i * DAY, 100, 100, 100, 100 if i < 10 else 90, 1, T0 + (i + 1) * DAY - 1, 0.5)
                           for i in range(21)])
    assert down.at(T0 + 21 * DAY) == s4.DOWN


def test_h5_one_signal_per_day_and_asia_range() -> None:
    bars = []
    for i in range(48):
        hour = i % 24
        if hour < 7:
            bars.append(bar(i, 100, 101, 99, 100))
        else:
            bars.append(bar(i, 100, 100.5, 99.5, 100))
    # day 2, 08:00 bar sweeps the Asia high 101 and closes back inside; stop 103 + 0.25 ATR is far enough
    i = 24 + 8
    bars[i] = bar(i, 100.5, 103, 100.4, 100.8)
    bars[i + 1] = bar(i + 1, 100.5, 103, 100.4, 100.8)
    strategy = s4.h5_session_sweep("london")
    first = strategy(History(bars, i))
    assert first is not None and first.side == -1 and first.time_stop_bars == 19 - 8
    assert strategy(History(bars, i + 1)) is None  # second sweep the same day is ignored


def test_gap_through_stop_is_a_full_loss_not_dropped() -> None:
    bars = [bar(0, 100, 100, 100, 100), bar(1, 100, 100, 100, 100), bar(2, 97, 98, 96, 97), bar(3, 97, 97, 97, 97)]

    def strategy(history: History) -> Signal | None:
        return Signal(1, 98.5, target_r=0.75, time_stop_bars=24) if len(history) == 2 else None

    plain = run_backtest(bars, strategy, H)
    assert plain.invalid_signals == 1 and not plain.trades
    strict = run_backtest(bars, strategy, H, gap_entry_as_loss=True)
    assert strict.invalid_signals == 0 and len(strict.trades) == 1
    trade = strict.trades[0]
    cost = (2 * BASE_COSTS.fee + BASE_COSTS.slippage + BASE_COSTS.stop_slippage) * 100 / 1.5
    assert trade.reason == "stop_before_entry"
    assert trade.r == pytest.approx(-1 - cost)


def test_fees_are_charged_exactly_once() -> None:
    """Section 5.3: gross from the fills minus fees (no funding here) equals net; slippage is not booked twice."""
    bars = [bar(0, 100, 100, 100, 100), bar(1, 100, 100, 100, 100), bar(2, 100, 102, 99.9, 101.5)]

    def strategy(history: History) -> Signal | None:
        return Signal(1, 98.0, target_r=0.75, time_stop_bars=24) if len(history) == 2 else None

    trade = run_backtest(bars, strategy, H).trades[0]
    risk = abs(trade.entry_price - trade.stop)
    gross = (trade.exit_price - trade.entry_price) / risk
    assert trade.reason == "target"
    assert trade.entry_price == pytest.approx(100 * (1 + BASE_COSTS.slippage))
    assert trade.r == pytest.approx(gross - trade.cost_r - trade.funding_r)
    assert trade.cost_r == pytest.approx(BASE_COSTS.fee * (trade.entry_price + trade.exit_price) / risk)


def test_count_is_outcome_blind_and_bounds_hold() -> None:
    bars = walk(3000, 3)
    daily = daily_from(bars)
    start, end = bars[800].open_time, bars[-1].open_time + 1
    for variant in s4.S4_VARIANTS:
        count = s4.count_signals(bars, variant, daily, start, end)
        assert 0 <= count.lower <= count.upper
        # changing prices after the counting window leaves the count unchanged
        cut = len(bars) - 200
        moved = bars[:cut] + [Kline(b.open_time, b.open * 2, b.high * 2, b.low * 2, b.close * 2, b.volume, b.close_time,
                                    b.taker_buy_volume) for b in bars[cut:]]
        again = s4.count_signals(moved, variant, daily_from(moved), start, bars[cut].open_time)
        same = s4.count_signals(bars, variant, daily, start, bars[cut].open_time)
        assert again == same


def test_nearest_rank_percentile() -> None:
    assert s4.nearest_rank([1, 2, 3, 4, 5], 0.8) == 4
    assert s4.nearest_rank(list(range(1, 11)), 0.8) == 8


def test_count_script_refs_stop_before_holdout_and_start_sol_late() -> None:
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("s4_script", Path("scripts/research_lab_s4.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    refs = module.all_refs()
    assert refs and not any(ref.touches_holdout for ref in refs)
    sol = [r for r in refs if r.symbol == "SOLUSDT"]
    assert min((r.year, r.month) for r in sol) == (2020, 9)
    assert {r.symbol for r in refs} == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
