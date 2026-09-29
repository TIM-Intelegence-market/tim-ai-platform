from __future__ import annotations

import statistics

import pytest

from src.research_lab.backtest.engine import History, Signal, run_backtest
from src.research_lab.backtest.funding import with_pre_perp_proxy
from src.research_lab.backtest.indicators import atr
from src.research_lab.backtest.metrics import max_drawdown_r, summarize
from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.protocol import BASE_COSTS, CostModel
from src.research_lab.synthetic import marker_strategy, synthetic_series

H = 3_600_000
T0 = 1_704_067_200_000
FREE = CostModel(0.0, 0.0, 0.0)


def bar(i: int, o: float, h: float, l: float, c: float, *, t0: int = T0) -> Kline:
    return Kline(t0 + i * H, o, h, l, c, 10.0, t0 + (i + 1) * H - 1, 5.0)


def once(at: int, signal: Signal):
    def strategy(history):
        return signal if len(history) - 1 == at else None
    return strategy


# --- look-ahead trap -------------------------------------------------------

def test_history_hides_the_future() -> None:
    bars = [bar(i, 100, 101, 99, 100) for i in range(5)]
    view = History(bars, 2)
    assert len(view) == 3 and view[-1] is bars[2]
    assert view[:] == bars[:3]
    with pytest.raises(IndexError):
        view[3]

    def peeking(history):
        history[len(history)]  # tries to read the next bar

    with pytest.raises(IndexError):
        run_backtest(bars, peeking, H)


def test_changing_future_data_never_changes_past_signals() -> None:
    bars = synthetic_series(3000, seed=7, edge=0.3)
    base = run_backtest(bars, marker_strategy(), H)
    cut = 1500
    altered = bars[:cut] + [
        Kline(b.open_time, b.open * 1.3, b.high * 1.3, b.low * 1.3, b.close * 1.3, b.volume, b.close_time, b.volume * 0.95)
        for b in bars[cut:]
    ]
    changed = run_backtest(altered, marker_strategy(), H)
    boundary = bars[cut].open_time
    assert [s for s in base.signals if s[0] < boundary] == [s for s in changed.signals if s[0] < boundary]
    assert [t for t in base.trades if t.exit_time <= boundary] == [t for t in changed.trades if t.exit_time <= boundary]
    assert len([s for s in changed.signals if s[0] >= boundary]) > len([s for s in base.signals if s[0] >= boundary])


# --- built-in edge is found, random walk shows none -------------------------

def test_synthetic_edge_is_found_after_costs() -> None:
    bars = synthetic_series(20_000, seed=11, edge=0.3)
    summary = summarize(run_backtest(bars, marker_strategy(), H, costs=BASE_COSTS).trades)
    assert summary.trades > 500
    assert summary.expectancy_r > 0.1


def test_random_walk_shows_no_edge() -> None:
    bars = synthetic_series(20_000, seed=11, edge=0.0)
    trades = run_backtest(bars, marker_strategy(), H, costs=FREE).trades
    results = [t.r for t in trades]
    stderr = statistics.stdev(results) / len(results) ** 0.5
    assert abs(statistics.fmean(results)) < 3 * stderr
    assert summarize(run_backtest(bars, marker_strategy(), H, costs=BASE_COSTS).trades).expectancy_r < 0


# --- execution rules --------------------------------------------------------

def test_entry_next_open_and_target() -> None:
    bars = [bar(0, 100, 101, 99, 100), bar(1, 100, 103, 99.5, 102), bar(2, 102, 102, 101, 101)]
    result = run_backtest(bars, once(0, Signal(1, 98.0, target_r=1.0)), H, costs=FREE)
    (trade,) = result.trades
    assert trade.entry_time == bars[1].open_time and trade.entry_price == 100
    assert trade.reason == "target" and trade.exit_price == 102 and trade.r == pytest.approx(1.0)


def test_stop_wins_tie_with_target() -> None:
    bars = [bar(0, 100, 101, 99, 100), bar(1, 100, 103, 97, 100)]
    (trade,) = run_backtest(bars, once(0, Signal(1, 98.0, target_r=1.0)), H, costs=FREE).trades
    assert trade.reason == "stop" and trade.r == pytest.approx(-1.0)


def test_gap_through_stop_fills_at_open() -> None:
    bars = [bar(0, 100, 101, 99, 100), bar(1, 100, 100.5, 99.5, 100), bar(2, 96, 97, 95, 96)]
    (trade,) = run_backtest(bars, once(0, Signal(1, 98.0)), H, costs=FREE).trades
    assert trade.reason == "stop_gap" and trade.exit_price == 96 and trade.r == pytest.approx(-2.0)


def test_short_time_stop_and_cost_in_r() -> None:
    costs = CostModel(fee=0.001, slippage=0.0, stop_slippage=0.0)
    bars = [bar(0, 100, 101, 99, 100), bar(1, 100, 100.5, 99.5, 99), bar(2, 99, 99.5, 98.5, 99)]
    (trade,) = run_backtest(bars, once(0, Signal(-1, 102.0, time_stop_bars=2)), H, costs=costs).trades
    assert trade.reason == "time" and trade.bars_held == 2
    fees = 0.001 * (100 + 99)
    assert trade.cost_r == pytest.approx(fees / 2)
    assert trade.r == pytest.approx((1 - fees) / 2)


def test_funding_is_charged_and_stress_removes_credits() -> None:
    bars = [bar(i, 100, 100.5, 99.5, 100) for i in range(10)]
    funding = [FundingRate(bars[3].open_time, 0.001), FundingRate(bars[5].open_time, -0.002)]
    signal = Signal(1, 99.0, time_stop_bars=7)
    (base,) = run_backtest(bars, once(0, signal), H, costs=FREE, funding=funding).trades
    assert base.funding_r == pytest.approx((0.1 - 0.2) / 1.0)
    stressed = CostModel(0.0, 0.0, 0.0, funding_credits_allowed=False)
    (stress,) = run_backtest(bars, once(0, signal), H, costs=stressed, funding=funding).trades
    assert stress.funding_r == pytest.approx(0.1)
    assert stress.r < base.r


def test_data_gap_closes_at_last_price_before_gap() -> None:
    bars = [bar(0, 100, 101, 99, 100), bar(1, 100, 101, 99.5, 101), bar(5, 90, 91, 89, 90)]
    result = run_backtest(bars, once(0, Signal(1, 98.0)), H, costs=FREE)
    (trade,) = result.trades
    assert trade.reason == "gap" and trade.exit_price == 101 and result.gap_closes == 1


def test_ignored_invalid_and_out_of_range_signals() -> None:
    bars = [bar(i, 100, 100.5, 99.5, 100) for i in range(6)]
    always = lambda history: Signal(1, 99.0, time_stop_bars=3)  # noqa: E731
    result = run_backtest(bars, always, H, costs=FREE, start_ms=bars[1].open_time, end_ms=bars[4].open_time)
    assert [s[0] for s in result.signals] == [b.open_time for b in bars[1:4]]
    assert len(result.trades) == 1 and result.ignored_signals == 2
    stop_above = run_backtest(bars[:2], once(0, Signal(1, 101.0)), H, costs=FREE)
    assert stop_above.trades == [] and stop_above.invalid_signals == 1


def test_exit_rule_fills_at_next_open() -> None:
    bars = [bar(0, 100, 101, 99, 100), bar(1, 100, 101, 99.5, 100.5), bar(2, 101, 101.5, 100.5, 101), bar(3, 101.5, 102, 101, 102)]
    rule = lambda history, position: history[-1].close >= 101  # noqa: E731
    (trade,) = run_backtest(bars, once(0, Signal(1, 98.0, exit_rule=rule)), H, costs=FREE).trades
    assert trade.reason == "rule" and trade.exit_price == 101.5 and trade.exit_time == bars[3].open_time


def test_metrics() -> None:
    assert max_drawdown_r([1, -1, -2, 3, -1]) == 3
    bars = synthetic_series(5000, seed=3, edge=0.3)
    summary = summarize(run_backtest(bars, marker_strategy(), H).trades)
    assert summary.max_drawdown_pct == pytest.approx(summary.max_drawdown_r * 0.01)
    assert sum(n for n, _ in summary.expectancy_by_year.values()) == summary.trades
    assert summarize([]).trades == 0


def test_atr_needs_enough_bars() -> None:
    bars = [bar(i, 100, 102, 98, 100) for i in range(15)]
    assert atr(History(bars, 13), 14) is None
    assert atr(History(bars, 14), 14) == pytest.approx(4.0)


def test_stop_between_open_and_slipped_entry_is_invalid() -> None:
    costs = CostModel(fee=0.0, slippage=0.001, stop_slippage=0.0)
    bars = [bar(0, 100, 101, 99, 100), bar(1, 100, 100.5, 99.5, 100)]
    result = run_backtest(bars, once(0, Signal(-1, 99.95)), H, costs=costs)  # short, stop above slipped entry 99.9 but below open 100
    assert result.trades == [] and result.invalid_signals == 1


def test_rule_exit_makes_room_for_reversal_on_same_bar() -> None:
    bars = [bar(0, 100, 101, 99, 100), bar(1, 100, 101, 99.5, 100.5), bar(2, 100.5, 101, 99, 99.2), bar(3, 99, 99.5, 98.5, 99)]

    def flip(history):
        t = len(history) - 1
        if t == 0:
            return Signal(1, 97.0, exit_rule=lambda h, p: h[-1].close < 100)
        if t == 2:
            return Signal(-1, 102.0, time_stop_bars=1)
        return None

    result = run_backtest(bars, flip, H, costs=FREE)
    assert [(t.side, t.reason, t.entry_time) for t in result.trades] == [(1, "rule", bars[1].open_time), (-1, "time", bars[3].open_time)]
    assert result.ignored_signals == 0


def test_signal_on_last_bar_is_counted() -> None:
    bars = [bar(0, 100, 101, 99, 100)]
    assert run_backtest(bars, once(0, Signal(1, 98.0)), H, costs=FREE).invalid_signals == 1


def test_pre_perp_funding_proxy_charges_both_sides() -> None:
    real = [FundingRate(T0 + 24 * H, -0.001)]
    funding = with_pre_perp_proxy(real, T0 + 1)
    assert [f.time for f in funding[:3]] == [T0 + 8 * H, T0 + 16 * H, T0 + 24 * H]
    assert funding[0].proxy and funding[0].rate == 0.0001 and funding[-1] is real[0]
    assert with_pre_perp_proxy(real, T0, stressed=True)[0].rate == 0.0002
    bars = [bar(i, 100, 100.5, 99.5, 100) for i in range(20)]
    for side, stop in ((1, 99.0), (-1, 101.0)):
        (trade,) = run_backtest(bars, once(0, Signal(side, stop, time_stop_bars=18)), H, costs=FREE, funding=funding[:2]).trades
        assert trade.funding_r == pytest.approx(2 * 0.0001 * 100)
