"""Study S13 section 6: random entries at the same check bars with the same exit (synthetic bars)."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, datetime, time, timezone

import pytest

from src.research_lab.backtest.engine import Signal, run_backtest
from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.hypotheses import s13
from src.research_lab.protocol import BASE_COSTS
from src.research_lab.stats.inference import section_trades
from src.research_lab.studies import s13_random as sr

NY, UTC = s13.S13_VARIANTS
M = s13.INTERVAL_MS
DAYS = 24


def _walk(seed: int, days: int = DAYS, drop: range | None = None) -> tuple[list[Kline], int]:
    """1m random walk with a daily drift, so that breakouts and trailing exits occur."""
    rng = random.Random(seed)
    anchor0 = int(datetime.combine(date(2021, 3, 1), time(0), tzinfo=timezone.utc).timestamp() * 1000)
    bars, price = [], 100.0
    for d in range(days):
        drift = rng.choice((-1, 1)) * rng.uniform(0, 0.0004)
        for k in range(1440):
            t = anchor0 + (d * 1440 + k) * M
            close = price * (1 + drift + rng.gauss(0, 0.0012))
            hi, lo = max(price, close) * (1 + abs(rng.gauss(0, 0.0004))), min(price, close) * (1 - abs(rng.gauss(0, 0.0004)))
            if drop is None or (d * 1440 + k) not in drop:
                bars.append(Kline(t, price, hi, lo, close, 1 + rng.random(), t + M - 1, 0.5))
            price = close
    return bars, anchor0


def _funding(anchor0: int, days: int = DAYS) -> list[FundingRate]:
    return [FundingRate(anchor0 + i * 8 * 3_600_000, 0.0001 * (1 if i % 3 else -1)) for i in range(days * 3)]


def _instrument(seed: int, drop: range | None = None) -> tuple[sr.Instrument, int]:
    bars, anchor0 = _walk(seed, drop=drop)
    table = s13.build_table(bars, UTC, anchor0, anchor0 + DAYS * s13.DAY_MS)
    return sr.Instrument(bars, table, _funding(anchor0)), anchor0


def _one_shot(table: s13.NoiseTable, at: int, side: int):
    """The engine with exactly one S13 signal (given side) on check bar `at` and the S13 exit."""

    def exit_rule(history, position) -> bool:
        check = table.check(history[-1].open_time)
        return check is not None and s13.exits(check, position.side, history[-1].close)

    def decide(history):
        bar = history[-1]
        if bar.open_time != at:
            return None
        check = table.check(at)
        assert check is not None and check.risk is not None
        return Signal(side, bar.close - side * check.risk, exit_rule=exit_rule)

    return decide


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_simulation_repeats_the_engine_for_the_real_signals(seed: int) -> None:
    inst, _ = _instrument(seed)
    real = run_backtest(inst.bars, s13.strategy(inst.table), M, costs=BASE_COSTS, funding=inst.funding).trades
    assert len(real) >= 3
    index = {b.open_time: i for i, b in enumerate(inst.bars)}
    for trade in real:
        sim = sr.simulate_trade(inst, index[trade.signal_time], trade.side)
        assert sim is not None
        assert (sim.exit_time, sim.reason) == (trade.exit_time, trade.reason)
        assert sim.r == pytest.approx(trade.r, abs=1e-12)


def test_simulation_repeats_the_engine_for_random_signals_with_gaps() -> None:
    inst, anchor0 = _instrument(4, drop=range(20 * 1440 + 200, 20 * 1440 + 203))
    candidates = sr.entry_candidates(inst, anchor0, anchor0 + DAYS * s13.DAY_MS)
    assert candidates
    rng = random.Random(7)
    picks = rng.sample(candidates, 25) + [i for i in candidates if 20 * 1440 + 150 < i < 20 * 1440 + 200][:2]
    reasons = set()
    for i in picks:
        side = rng.choice((1, -1))
        at = inst.bars[i].open_time
        engine = run_backtest(inst.bars, _one_shot(inst.table, at, side), M, costs=BASE_COSTS, funding=inst.funding).trades
        sim = sr.simulate_trade(inst, i, side)
        if not engine:
            assert sim is None
            continue
        assert sim is not None and len(engine) == 1
        assert (sim.signal_time, sim.exit_time, sim.reason) == (engine[0].signal_time, engine[0].exit_time, engine[0].reason)
        assert sim.r == pytest.approx(engine[0].r, abs=1e-12)
        reasons.add(sim.reason)
    assert "rule" in reasons


def test_candidates_are_only_check_bars_where_an_entry_may_be_decided() -> None:
    inst, anchor0 = _instrument(5)
    start = anchor0 + 16 * s13.DAY_MS
    candidates = sr.entry_candidates(inst, start, anchor0 + 20 * s13.DAY_MS)
    assert candidates and all(start <= inst.bars[i].open_time < anchor0 + 20 * s13.DAY_MS for i in candidates)
    checks = [inst.table.check(inst.bars[i].open_time) for i in candidates]
    assert all(c is not None and c.entry_allowed and c.risk and not c.last for c in checks)
    assert not sr.entry_candidates(inst, anchor0, anchor0 + 14 * s13.DAY_MS)  # warm-up: no band yet
    per_session = 1410 // 30 - 1  # 46 entry checks, the session end is not one
    assert len(candidates) == 4 * per_session


def test_pvalue_is_deterministic_pooled_and_detects_a_planted_edge() -> None:
    insts = {"A": _instrument(1)[0], "B": _instrument(2)[0]}
    anchor0 = _instrument(1)[1]
    start, end = anchor0, anchor0 + DAYS * s13.DAY_MS
    real = {sym: section_trades(run_backtest(i.bars, s13.strategy(i.table), M, funding=i.funding).trades, start, end)
            for sym, i in insts.items()}
    a = sr.random_pvalue(insts, real, start, end, runs=500, seed=11)
    b = sr.random_pvalue(insts, real, start, end, runs=500, seed=11)
    assert a == b and 0 < a.p <= 1
    assert a.trades == {sym: len(ts) for sym, ts in real.items() if ts}
    assert a.pool == {sym: min(500 * n, max(sr.POOL_FACTOR * n, sr.MIN_POOL)) for sym, n in a.trades.items()}
    assert a.observed == pytest.approx(sum(t.r for ts in real.values() for t in ts) / sum(map(len, real.values())))

    def shifted(delta: float) -> dict:
        return {sym: [replace(t, r=t.r + delta) for t in ts] for sym, ts in real.items()}

    # Real trades moved to the random mean are ordinary (p near 0.5); far above it, p is tiny.
    middle = sr.random_pvalue(insts, shifted(a.random_mean - a.observed), start, end, runs=2000, seed=11)
    assert 0.3 < middle.p < 0.7
    assert sr.random_pvalue(insts, shifted(a.random_mean - a.observed + 3), start, end, runs=500, seed=11).p < 0.01
    assert sr.random_pvalue(insts, shifted(a.random_mean - a.observed - 3), start, end, runs=500, seed=11).p > 0.99


def test_pvalue_without_trades_is_one() -> None:
    inst, anchor0 = _instrument(1)
    assert sr.random_pvalue({"A": inst}, {"A": []}, anchor0, anchor0 + s13.DAY_MS).p == 1.0


def test_simulation_repeats_the_engine_on_a_catastrophe_stop() -> None:
    """Breakout long at k=30, then a crash through 3 sigma: stop fill with stop slippage."""
    bars, anchor0 = _walk(6, days=16)
    base = 15 * 1440
    bars = bars[:base]
    t0 = anchor0 + base * M
    for k in range(1440):  # last day: flat at 100, breakout to 103 from k=30, crash to 80 at k=45
        close = 100.0 if k < 29 else (103.0 if k < 44 else 80.0)
        prev = bars[-1].close
        bars.append(Kline(t0 + k * M, prev, max(prev, close), min(prev, close), close, 1.0, t0 + k * M + M - 1, 0.5))
    table = s13.build_table(bars, UTC, anchor0, anchor0 + 16 * s13.DAY_MS)
    inst = sr.Instrument(bars, table, _funding(anchor0, 16))
    real = run_backtest(bars, s13.strategy(table), M, costs=BASE_COSTS, funding=inst.funding).trades
    last = [t for t in real if t.signal_time >= t0]
    assert last and last[0].reason.startswith("stop")
    sim = sr.simulate_trade(inst, base + 29, last[0].side)
    assert sim is not None and sim.reason == last[0].reason and sim.r == pytest.approx(last[0].r, abs=1e-12)


def test_pool_respects_section_end_and_drawn_sides() -> None:
    inst, anchor0 = _instrument(3)
    start, end = anchor0 + 15 * s13.DAY_MS, anchor0 + 20 * s13.DAY_MS + 12 * 3_600_000  # end mid-session
    pool = sr.draw_pool(inst, [-1], start, end, 400, random.Random(3))
    assert len(pool) == 400 and all(t.side == -1 for t in pool)
    assert all(start <= t.signal_time < end and t.exit_time <= end for t in pool)
    unbounded = sr.draw_pool(inst, [-1], start, anchor0 + DAYS * s13.DAY_MS, 400, random.Random(3))
    assert any(t.exit_time > end for t in unbounded)  # the cut matters here
    both = sr.draw_pool(inst, [1, 1, 1, -1], start, end, 2000, random.Random(4))
    assert 0.65 < sum(t.side > 0 for t in both) / len(both) < 0.85
