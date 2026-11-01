"""Study S14: pairs trading rules (synthetic bars, no market data)."""

from __future__ import annotations

import itertools
import math
import random

import pytest

from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.hypotheses import s14
from src.research_lab.protocol import CostModel

H = s14.HOUR_MS
ZERO = CostModel(0.0, 0.0, 0.0)
T0 = 1_609_459_200_000  # 2021-01-01 00:00 UTC
V168 = s14.S14_VARIANTS[0]


def _k(t: int, o: float, c: float) -> Kline:
    return Kline(t, o, max(o, c), min(o, c), c, 1.0, t + H - 1, 0.5)


def _pair(y_close: list[float], x_close: list[float], times: list[int] | None = None) -> s14.PairSeries:
    """Open = previous close, so fills at the next open equal the signal close."""
    times = times or [T0 + i * H for i in range(len(y_close))]
    y_open = [y_close[0]] + y_close[:-1]
    x_open = [x_close[0]] + x_close[:-1]
    return s14.PairSeries("ETHUSDT", "BTCUSDT", times, y_open, list(y_close), x_open, list(x_close))


def _cointegrated(n: int, seed: int, beta: float = 1.2, noise: float = 0.01, rho: float = 0.9) -> tuple[list[float], list[float]]:
    rng = random.Random(seed)
    lx, e, ys, xs = math.log(100.0), 0.0, [], []
    for _ in range(n):
        lx += rng.gauss(0, 0.005)
        e = rho * e + rng.gauss(0, noise)
        xs.append(math.exp(lx))
        ys.append(math.exp(0.3 + beta * lx + e))
    return ys, xs


def test_variants_are_the_preregistered_four() -> None:
    assert [(v.variant_id, v.window, v.cointegration) for v in s14.S14_VARIANTS] == [
        ("S14-W168", 168, False), ("S14-W168-K", 168, True), ("S14-W720", 720, False), ("S14-W720-K", 720, True)]
    assert (s14.ENTRY_Z, s14.EXIT_Z, s14.STOP_Z, s14.TIME_STOP_HOURS) == (2.0, 0.0, 4.0, 120)


def test_hourly_needs_all_twelve_five_minute_bars() -> None:
    bars = [Kline(T0 + k * 300_000, 100 + k, 101 + k, 99 + k, 100.5 + k, 2.0, T0 + (k + 1) * 300_000 - 1, 1.0) for k in range(24)]
    bars = [b for b in bars if b.open_time != T0 + H + 5 * 300_000]  # second hour misses one bar
    out = s14.hourly(bars)
    assert len(out) == 1
    h = out[0]
    assert (h.open_time, h.open, h.close, h.high, h.low, h.volume) == (T0, 100, 111.5, 112, 99, 24.0)


def test_fit_recovers_the_hedge_ratio_and_reads_only_the_window() -> None:
    ys, xs = _cointegrated(400, 1, noise=0.002, rho=0.5)
    pair = _pair(ys, xs)
    sig = s14.Signals(pair, V168)
    f = sig.fit(300)
    assert f is not None and f.beta == pytest.approx(1.2, abs=0.25) and f.sigma > 0
    # Changing hour 300 itself or anything later leaves the fit at 300 unchanged.
    ys2 = ys[:300] + [v * 1.5 for v in ys[300:]]
    f2 = s14.Signals(_pair(ys2, xs), V168).fit(300)
    assert (f2.alpha, f2.beta, f2.sigma) == (f.alpha, f.beta, f.sigma)
    assert sig.fit(100) is None  # window not full


def test_gap_in_the_window_means_no_fit() -> None:
    ys, xs = _cointegrated(500, 2, noise=0.002, rho=0.5)
    times = [T0 + i * H for i in range(500)]
    times = times[:250] + [t + H for t in times[250:]]  # one missing hour before index 250
    pair = _pair(ys, xs, times)
    sig = s14.Signals(pair, V168)
    assert sig.fit(300) is None and sig.fit(250 + 168) is not None


def test_dickey_fuller_separates_stationary_from_random_walk_residuals() -> None:
    ys, xs = _cointegrated(800, 3, rho=0.8)
    sig = s14.Signals(_pair(ys, xs), s14.S14_VARIANTS[3])
    f = sig.fit(760)
    assert s14.df_tstat(sig.ly, sig.lx, 760, 720, f) < s14.EG_CRITICAL
    ys, xs = _cointegrated(800, 3, rho=1.0)  # residual is a random walk: no cointegration
    sig = s14.Signals(_pair(ys, xs), s14.S14_VARIANTS[3])
    f = sig.fit(760)
    assert s14.df_tstat(sig.ly, sig.lx, 760, 720, f) > s14.EG_CRITICAL


def _sigma_at(ys: list[float], xs: list[float], t: int = 200) -> float:
    """Residual sigma of the window before t (unchanged by edits at t or later)."""
    f = s14.Signals(_pair(ys, xs), V168).fit(t)
    assert f is not None
    return f.sigma


def _shift(ys: list[float], start: int, stop: int, size: float) -> list[float]:
    return [v * math.exp(size) if start <= k < stop else v for k, v in enumerate(ys)]


def _pinned(ys: list[float], xs: list[float], plan: dict[range, float]) -> list[float]:
    """Hours in each range get z exactly equal to the given value under the fit at 200."""
    f = s14.Signals(_pair(ys, xs), V168).fit(200)
    out = list(ys)
    for hours, z in plan.items():
        for k in hours:
            out[k] = math.exp(f.alpha + f.beta * math.log(xs[k]) + z * f.sigma)
    return out


def _with_jump(n: int, at: int, z: float, seed: int = 4) -> tuple[s14.PairSeries, s14.Signals]:
    ys, xs = _cointegrated(n, seed, noise=0.002, rho=0.5)
    ys = _shift(ys, at, n, z * _sigma_at(ys, xs, at))
    pair = _pair(ys, xs)
    return pair, s14.Signals(pair, V168)


def test_entry_is_a_crossing_of_two_with_the_right_side() -> None:
    _, sig = _with_jump(260, 200, 3.0)  # y jumps up: spread far above, short spread
    e = sig.entry(200)
    assert e is not None and e.side == -1 and e.z >= 2
    assert sig.entry(201) is None  # still beyond 2 relative to its own window: no new crossing
    _, sig = _with_jump(260, 200, -3.0)
    e = sig.entry(200)
    assert e is not None and e.side == 1


def test_trade_exits_when_the_spread_returns_with_r_in_units_of_two_sigma() -> None:
    ys, xs = _cointegrated(260, 5, noise=0.002, rho=0.5)
    ys = _shift(ys, 200, 205, 3 * _sigma_at(ys, xs))  # 3 sigma out for five hours, back at 205
    pair = _pair(ys, xs)
    sig = s14.Signals(pair, V168)
    e = sig.entry(200)
    trade = s14.simulate_trade(pair, sig, e, ZERO)
    assert trade is not None and trade.reason == "rule"
    assert trade.entry_time == pair.times[201]
    assert trade.exit_time == pair.times[206]  # z back at the 205 close, filled at the 206 open
    py = pair.y_open[206] / pair.y_open[201] - 1
    px = pair.x_open[206] / pair.x_open[201] - 1
    expected = (-1 * py + e.fit.beta * px) / (2 * e.fit.sigma)
    assert trade.r == pytest.approx(expected, rel=1e-12) and trade.r > 0


def test_stop_time_and_gap_exits() -> None:
    ys, xs = _cointegrated(400, 6, noise=0.002, rho=0.5)
    jump = _pinned(ys, xs, {range(200, 203): 3.0, range(203, 400): 8.0})
    pair = _pair(jump, xs)
    sig = s14.Signals(pair, V168)
    trade = s14.simulate_trade(pair, sig, sig.entry(200), ZERO)
    assert trade.reason == "stop" and trade.exit_time == pair.times[204] and trade.r < -1

    hold = _pinned(ys, xs, {range(200, 400): 3.0})
    pair = _pair(hold, xs)
    sig = s14.Signals(pair, V168)
    trade = s14.simulate_trade(pair, sig, sig.entry(200), ZERO)
    assert trade.reason == "time" and trade.hours_held == s14.TIME_STOP_HOURS

    times = [T0 + i * H for i in range(400)]
    times = times[:230] + [t + 5 * H for t in times[230:]]
    pair = _pair(hold, xs, times)
    sig = s14.Signals(pair, V168)
    trade = s14.simulate_trade(pair, sig, sig.entry(200), ZERO)
    assert trade.reason == "gap" and trade.exit_time == pair.times[229] + H


def test_costs_and_funding_on_both_legs() -> None:
    ys, xs = _cointegrated(260, 5, noise=0.002, rho=0.5)
    ys = _shift(ys, 200, 205, 3 * _sigma_at(ys, xs))
    pair = _pair(ys, xs)
    sig = s14.Signals(pair, V168)
    e = sig.entry(200)
    free = s14.simulate_trade(pair, sig, e, ZERO)
    costs = CostModel(0.0005, 0.0, 0.0)
    paid = s14.simulate_trade(pair, sig, e, costs)
    fee = 0.0005 * (1 * (1 + pair.y_open[206] / pair.y_open[201]) + e.fit.beta * (1 + pair.x_open[206] / pair.x_open[201]))
    assert paid.cost_r == pytest.approx(fee / (2 * e.fit.sigma)) and paid.r == pytest.approx(free.r - paid.cost_r)
    rate = [FundingRate(pair.times[203], 0.001)]
    funded = s14.simulate_trade(pair, sig, e, ZERO, y_funding=rate, x_funding=rate)
    # Short y pays nothing on a positive rate (receives), long x pays beta * rate.
    assert funded.funding_r == pytest.approx((-0.001 + e.fit.beta * 0.001) / (2 * e.fit.sigma))


def test_run_pair_holds_one_position_and_needs_a_new_crossing() -> None:
    ys, xs = _cointegrated(3000, 7, noise=0.004, rho=0.97)
    pair = _pair(ys, xs)
    trades = s14.run_pair(pair, V168, pair.times[0], pair.times[-1] + H, ZERO)
    assert len(trades) >= 5
    for a, b in itertools.pairwise(trades):
        assert b.signal_time >= a.exit_time  # the next signal hour opens at or after the exit fill
    signals = s14.entries(s14.Signals(pair, V168), pair.times[0], pair.times[-1] + H)
    assert len(signals) >= len(trades)
    assert all(e.side in (1, -1) and abs(e.z) >= 2 for e in signals)


def test_cointegration_filter_blocks_entries_only_in_the_k_variant() -> None:
    k168 = s14.S14_VARIANTS[1]
    for rho, blocked in ((1.0, True), (0.5, False)):
        ys, xs = _cointegrated(260, 9, noise=0.002, rho=rho)
        ys = _shift(ys, 200, 260, 3 * _sigma_at(ys, xs, 200))
        pair = _pair(ys, xs)
        plain, filtered = s14.Signals(pair, V168), s14.Signals(pair, k168)
        f = filtered.fit(200)
        assert (s14.df_tstat(filtered.ly, filtered.lx, 200, 168, f) > s14.EG_CRITICAL) is blocked
        assert plain.entry(200) is not None
        assert (filtered.entry(200) is None) is blocked
        assert (filtered.possible(200) is None) is blocked
