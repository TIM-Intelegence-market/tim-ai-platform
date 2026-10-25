"""Study S6 rules (docs/research_lab/studien/S6_WINRATE_95_MAKER_MEAN_REVERSION_PRAEREGISTRIERUNG.md, sections 3, 4.1, 6.1)."""
from __future__ import annotations

import math

import pytest

from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.hypotheses import s6

M = s6.MINUTE_MS
T0 = 1_577_836_800_000  # 2020-01-01T00:00:00Z
V = s6.S6Variant("test-k2-t20", 2.0, 0.20)
WARM = s6.SIGMA_RETURNS + 1  # index of the first bar with a reference (121 closed bars before it)


def flat_bars(n: int, price: float = 100.0, *, wiggle: float = 0.001, t0: int = T0, skip: set[int] = frozenset()) -> list[Kline]:
    """Contiguous bars with a tiny alternating wiggle (sigma > 0) around `price`."""
    bars = []
    for i in range(n):
        if i in skip:
            continue
        c = price * (1 + wiggle * (1 if i % 2 else -1))
        t = t0 + i * M
        bars.append(Kline(t, price, max(price, c) + 0.001, min(price, c) - 0.001, c, 10.0, t + M - 1, 5.0))
    return bars


def with_bar(bars: list[Kline], index: int, *, open=None, high=None, low=None, close=None) -> list[Kline]:
    b = bars[index]
    bars[index] = Kline(b.open_time, open if open is not None else b.open, high if high is not None else b.high,
                        low if low is not None else b.low, close if close is not None else b.close, b.volume, b.close_time,
                        b.taker_buy_volume)
    return bars


def test_reference_uses_only_closed_contiguous_bars() -> None:
    bars = flat_bars(300)
    ref = s6.compute_reference(bars)
    assert ref.vwap[WARM - 1] is None and ref.vwap[WARM] is not None
    # vwap over bars i-30..i-1 equals the direct computation
    i = 200
    w = bars[i - 30:i]
    assert ref.vwap[i] == pytest.approx(sum(b.close * b.volume for b in w) / sum(b.volume for b in w))
    closes = [b.close for b in bars[i - 121:i]]
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    mean = sum(rets) / 120
    sigma = math.sqrt(sum((r - mean) ** 2 for r in rets) / 120) * math.sqrt(30)
    assert ref.sigma30[i] == pytest.approx(sigma, rel=1e-9)
    # the incremental path agrees with a fresh computation far from the window start
    direct = s6.compute_reference(bars[i - 125:])
    assert direct.vwap[125] == pytest.approx(ref.vwap[i]) and direct.sigma30[125] == pytest.approx(ref.sigma30[i])
    # a one-minute gap invalidates the reference for 121 bars
    gapped = flat_bars(400, skip={150})
    ref2 = s6.compute_reference(gapped)
    k = next(j for j, b in enumerate(gapped) if b.open_time == T0 + 151 * M)
    assert ref2.vwap[k] is None and ref2.vwap[k + 120] is None and ref2.vwap[k + 121] is not None


def test_empirical_tick_and_rounding_against_the_trade() -> None:
    bars = flat_bars(10, 100.0, wiggle=0.001)
    ticks = s6.empirical_ticks(bars)
    assert ticks["2020-01"] == pytest.approx(0.001)
    assert s6.round_against(99.9994, 0.001, upward=False) == pytest.approx(99.999)
    assert s6.round_against(99.9994, 0.001, upward=True) == pytest.approx(100.0)
    assert s6.round_against(100.0, 0.001, upward=True) == pytest.approx(100.0)
    assert s6.limit_price(100.0, 0.01, 2.0, s6.LONG, 0.001) == pytest.approx(98.0)
    assert s6.limit_price(100.0, 0.01, 2.0, s6.SHORT, 0.001) == pytest.approx(102.0)


def _setup(below_limit: float, *, n: int = 600, dip_at: int = WARM + 10) -> tuple[list[Kline], float, float]:
    """Flat market at 100, one bar whose low is `below_limit` under the long limit of that bar (0.5 stays above
    the stop, which lies about 1.5 % under the limit). Returns bars, the limit and sigma30 of that bar."""
    bars = flat_bars(n)
    ref = s6.compute_reference(bars)
    limit = s6.limit_price(ref.vwap[dip_at], ref.sigma30[dip_at], V.k, s6.LONG, 0.001)
    with_bar(bars, dip_at, low=limit - below_limit)
    # after the dip the market stays just under the limit: above the stop, below the target
    after = flat_bars(n - dip_at - 1, limit - 0.3, t0=T0 + (dip_at + 1) * M)
    bars[dip_at + 1:] = after
    return bars, limit, ref.sigma30[dip_at]


def test_touch_is_no_fill_trade_through_by_margin_is() -> None:
    bars, limit, _ = _setup(0.0)
    with_bar(bars, WARM + 10, low=limit)  # touch
    assert not s6.simulate(bars, [], V, T0, T0 + 600 * M).trades
    with_bar(bars, WARM + 10, low=limit - 0.5 * max(0.0001 * limit, 0.001))  # inside the margin
    assert not s6.simulate(bars, [], V, T0, T0 + 600 * M).trades
    with_bar(bars, WARM + 10, low=limit - max(0.0001 * limit, 0.001))  # exactly through
    sim = s6.simulate(bars, [], V, T0, T0 + 600 * M)
    assert len(sim.trades) == 1 and sim.trades[0].side == s6.LONG and sim.trades[0].entry_fill == pytest.approx(limit)


def test_post_only_skips_orders_that_would_cross() -> None:
    bars, limit, _ = _setup(0.0)
    with_bar(bars, WARM + 10, open=limit - 0.01, low=limit - 1.0)  # bar opens below the limit
    sim = s6.simulate(bars, [], V, T0, T0 + 600 * M)
    assert not sim.trades and sim.skipped_cross >= 1
    bars, limit, _ = _setup(0.0)
    with_bar(bars, WARM + 9, close=limit - 0.01)  # previous close below the limit
    with_bar(bars, WARM + 10, low=limit - 1.0)
    assert not s6.simulate(bars, [], V, T0, T0 + 600 * M).trades


def test_target_fill_is_maker_and_net_matches_formula() -> None:
    bars, limit, _ = _setup(0.5)  # deep enough for any k=2 limit at this wiggle
    i = WARM + 10
    target = s6.round_against(limit * (1 + 0.20 * 0.015), 0.001, upward=True)
    with_bar(bars, i + 3, high=target + max(0.0001 * target, 0.001))  # traded through the target
    sim = s6.simulate(bars, [], V, T0, T0 + 600 * M)
    (t,) = sim.trades
    assert t.reason == "target" and t.exit_index == i + 3 and t.exit_fill == pytest.approx(target)
    q = s6.NOMINAL / limit
    fees = s6.MAKER_FEE * s6.NOMINAL + s6.MAKER_FEE * q * target
    assert t.net_r == pytest.approx(((target - limit) * q - fees) / (0.015 * s6.NOMINAL))
    assert t.hit and 0.15 < t.net_r < 0.20
    # the target is never taken in the fill bar itself
    bars2, limit2, _ = _setup(0.5)
    with_bar(bars2, i, high=target + 1.0)
    assert s6.simulate(bars2, [], V, T0, T0 + 600 * M).trades[0].reason != "target"


def test_stop_in_the_fill_bar_and_ambiguous_bar_is_a_stop() -> None:
    bars, limit, _ = _setup(0.5)
    i = WARM + 10
    stop = s6.round_against(limit * (1 - 0.015), 0.001, upward=True)
    with_bar(bars, i, low=stop - 0.01)  # the fill bar already trades below the stop
    sim = s6.simulate(bars, [], V, T0, T0 + 600 * M)
    (t,) = sim.trades
    assert t.reason == "stop" and t.exit_index == i and t.exit_fill == pytest.approx(stop * (1 - 0.0005))
    assert t.net_r < -1.0 and not t.hit
    # stop and target in the same later bar: stop wins, flagged ambiguous, gap-open fills at the open
    bars, limit, _ = _setup(0.5)
    target = s6.round_against(limit * (1 + 0.20 * 0.015), 0.001, upward=True)
    with_bar(bars, i + 2, open=stop - 0.5, high=target + 1.0, low=stop - 1.0)
    (t,) = s6.simulate(bars, [], V, T0, T0 + 600 * M).trades
    assert t.reason == "stop" and t.ambiguous and t.exit_fill == pytest.approx((stop - 0.5) * (1 - 0.0005))


def test_time_stop_at_bar_240_and_locks() -> None:
    bars, limit, _ = _setup(0.5, n=900)
    i = WARM + 10
    sim = s6.simulate(bars, [], V, T0, T0 + 900 * M)
    (t,) = sim.trades
    assert t.reason == "time" and t.bars_held == s6.TIME_STOP_BARS and t.exit_index == i + 239
    assert t.exit_fill == pytest.approx(bars[i + 239].close * (1 - 0.0003))
    # a second dip inside the 5-bar lock after the time stop is ignored, one after it fills
    bars2 = [b for b in bars]
    ref = s6.compute_reference(bars2)
    j = i + 240 + 2
    with_bar(bars2, j, low=s6.limit_price(ref.vwap[j], ref.sigma30[j], V.k, s6.LONG, 0.001) - 1.0)
    assert len(s6.simulate(bars2, [], V, T0, T0 + 900 * M).trades) == 1
    bars3 = [b for b in bars]
    j = i + 240 + 5 + 121  # after the lock and after the reference window recovered from the dip bar
    with_bar(bars3, j, low=s6.limit_price(ref.vwap[j], ref.sigma30[j], V.k, s6.LONG, 0.001) - 1.0)
    assert len(s6.simulate(bars3, [], V, T0, T0 + 900 * M).trades) == 2


def test_both_sides_through_is_a_booked_loser() -> None:
    bars, limit, _ = _setup(0.5)
    with_bar(bars, WARM + 10, high=106.0)
    sim = s6.simulate(bars, [], V, T0, T0 + 600 * M)
    (t,) = sim.trades
    assert t.reason == "both" and t.net_r < -1.0 and not t.hit


def test_gap_and_section_end_close_the_trade() -> None:
    bars, limit, _ = _setup(0.5, n=600)
    i = WARM + 10
    gapped = bars[: i + 5] + [b for b in bars[i + 5 + 7:]]  # 7 missing minutes after bar i+4
    (t,) = s6.simulate(gapped, [], V, T0, T0 + 600 * M).trades
    assert t.reason == "gap" and t.exit_index == i + 4 and t.exit_fill == pytest.approx(bars[i + 4].close * (1 - 0.0003))
    bridged = bars[: i + 5] + [b for b in bars[i + 5 + 5:]]  # 5 missing minutes: bridged
    (t,) = s6.simulate(bridged, [], V, T0, T0 + 600 * M).trades
    assert t.reason == "time"
    end = bars[i + 50].open_time
    (t,) = s6.simulate(bars, [], V, T0, end).trades
    assert t.reason == "section_end" and t.exit_index == i + 49


def test_funding_inside_the_trade_and_stress_never_in_favour() -> None:
    bars, limit, _ = _setup(0.5, n=900)
    i = WARM + 10
    f_in = bars[i + 100].open_time  # inside (entry < F <= exit)
    f_entry = bars[i].open_time  # at the entry minute: not booked
    funding = [FundingRate(f_entry, 0.001), FundingRate(f_in, -0.0005)]
    (t,) = s6.simulate(bars, funding, V, T0, T0 + 900 * M).trades
    assert t.funding == pytest.approx(-0.0005 * s6.NOMINAL)  # long receives a negative rate
    (t2,) = s6.simulate(bars, funding, V, T0, T0 + 900 * M, costs=s6.STRESS_COSTS).trades
    assert t2.funding == 0.0


def test_count_fills_is_outcome_blind_and_matches_simulation_entries() -> None:
    bars, limit, _ = _setup(0.5, n=900)
    c = s6.count_fills(bars, V, T0, T0 + 900 * M)
    assert c.fills == 1 and c.fills_unlocked == 1 and c.fill_days == {"2020-01-01"} and c.fills_by_side == {"long": 1, "short": 0}
    sim = s6.simulate(bars, [], V, T0, T0 + 900 * M)
    assert [t.entry_index for t in sim.trades] == [WARM + 10]
    assert c.skipped_cross == sim.skipped_cross
    assert s6.STRESS_COSTS.delta_min == 2 * s6.DELTA_MIN and s6.STRESS_COSTS.funding_against_only


def test_count_script_refs_stop_before_holdout() -> None:
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("s6_script", Path("scripts/research_lab_s6.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    refs = module.all_refs()
    assert len(refs) == 172 and not any(ref.touches_holdout for ref in refs)
    assert {r.interval for r in refs} == {"1m"}
