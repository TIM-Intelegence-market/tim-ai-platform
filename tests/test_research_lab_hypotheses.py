from __future__ import annotations

import random
from collections import Counter
from datetime import date

import pytest

from src.research_lab.backtest.engine import run_backtest
from src.research_lab.data.archive import INTERVAL_MS
from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.hypotheses.calendars import easter, lse_holidays, nyse_holidays, session_bounds
from src.research_lab.hypotheses.registry import VARIANTS
from src.research_lab.protocol import HOLDOUT_START_MS, _utc_ms
from src.research_lab.runner import RunConfig, decide, evaluate_variant
from src.research_lab.synthetic import synthetic_series

START = _utc_ms(2021, 1, 4)  # a Monday


def test_register_holds_48_variants_as_in_the_protocol() -> None:
    assert len(VARIANTS) == 48
    assert len({v.variant_id for v in VARIANTS}) == 48
    per_prefix = Counter(v.hypothesis[0] for v in VARIANTS)
    assert per_prefix == {"L": 12, "M": 22, "S": 8, "T": 6}


def _funding(start: int, count: int, seed: int) -> list[FundingRate]:
    rng = random.Random(seed)
    return [FundingRate(start + i * 8 * 3_600_000, rng.gauss(0.0001, 0.0003)) for i in range(count)]


def _bars_for(spec) -> tuple[list[Kline], int]:
    interval = INTERVAL_MS[spec.interval]
    count = {"1d": 1_200, "1h": 10_000, "15m": 3_000, "5m": 4_000}[spec.interval]
    bars = synthetic_series(count, seed=hash(spec.variant_id) % 1000, start_ms=START, interval_ms=interval,
                            volatility=0.02 if spec.interval == "1d" else 0.004, marker_rate=0.2)
    return bars, interval


@pytest.mark.parametrize("spec", VARIANTS, ids=lambda s: s.variant_id)
def test_every_strategy_ignores_future_data(spec) -> None:
    bars, interval = _bars_for(spec)
    funding = _funding(START - 400 * 86_400_000, 3 * 400 + len(bars) * interval // (8 * 3_600_000), 3)
    cut = int(len(bars) * 0.7)
    altered = bars[:cut] + [
        Kline(b.open_time, b.open * 1.5, b.high * 1.6, b.low * 1.2, b.close * 1.5, b.volume, b.close_time, b.volume * 0.9)
        for b in bars[cut:]
    ]
    # Funding settled at a bar's close is public at that close, so only later values change.
    altered_funding = [f if f.time <= bars[cut].open_time else FundingRate(f.time, -f.rate * 5) for f in funding]
    base = run_backtest(bars, spec.build(funding), interval)
    changed = run_backtest(altered, spec.build(altered_funding), interval)
    boundary = bars[cut].open_time
    before = [s for s in base.signals if s[0] < boundary]
    assert before == [s for s in changed.signals if s[0] < boundary]
    assert base.signals, f"{spec.variant_id} produced no signal on synthetic data; the test would be vacuous"


def test_calendars() -> None:
    assert easter(2024) == date(2024, 3, 31) and easter(2019) == date(2019, 4, 21)
    ny = nyse_holidays
    assert {date(2024, 7, 4), date(2024, 3, 29), date(2021, 12, 24), date(2022, 6, 20), date(2025, 1, 9)} <= ny(2024) | ny(2021) | ny(2022) | ny(2025)
    assert date(2021, 12, 31) not in ny(2021) and date(2019, 6, 19) not in ny(2019)
    uk = lse_holidays
    assert {date(2020, 5, 8), date(2022, 6, 2), date(2022, 6, 3), date(2022, 9, 19), date(2021, 12, 27), date(2021, 12, 28)} <= uk(2020) | uk(2021) | uk(2022)
    assert date(2020, 5, 4) not in uk(2020)
    assert session_bounds("newyork", date(2024, 7, 1)) == (_utc_ms(2024, 7, 1) + 13 * 3_600_000 + 1_800_000, _utc_ms(2024, 7, 1) + 20 * 3_600_000)
    assert session_bounds("newyork", date(2024, 1, 2))[0] == _utc_ms(2024, 1, 2) + 14 * 3_600_000 + 1_800_000
    assert session_bounds("london", date(2024, 7, 1))[0] == _utc_ms(2024, 7, 1) + 7 * 3_600_000
    assert session_bounds("london", date(2024, 12, 2))[0] == _utc_ms(2024, 12, 2) + 8 * 3_600_000
    assert session_bounds("london", date(2024, 7, 6)) is None  # Saturday
    assert session_bounds("newyork", date(2024, 7, 4)) is None


def test_s2_trades_once_per_session_and_leaves_by_session_end() -> None:
    spec = next(v for v in VARIANTS if v.variant_id == "S2-newyork-r30")
    bars, interval = _bars_for(spec)
    result = run_backtest(bars, spec.build(()), interval)
    assert result.trades
    per_day = Counter(t.signal_time // 86_400_000 for t in result.trades)
    assert max(per_day.values()) == 1
    for trade in result.trades:
        day = date.fromtimestamp(trade.signal_time / 1000)
        opens, closes = session_bounds("newyork", day)
        assert opens + 30 * 60_000 <= trade.signal_time and trade.exit_time <= closes


def test_runner_evaluates_and_decides_without_holdout_data() -> None:
    specs = [v for v in VARIANTS if v.hypothesis == "M3"][:4]
    first = _utc_ms(2020, 1, 1)
    days = (_utc_ms(2025, 6, 1) - first) // 86_400_000
    bars = synthetic_series(days, seed=5, start_ms=first, interval_ms=86_400_000, volatility=0.03)
    results, trades = {}, {}
    for spec in specs:
        results[spec.variant_id], trades[spec.variant_id] = evaluate_variant(spec, bars, [], RunConfig(random_runs=19))
        assert all(t.signal_time < HOLDOUT_START_MS and t.entry_time < HOLDOUT_START_MS for t in trades[spec.variant_id])
        assert results[spec.variant_id].train.summary.trades > 100
    candidates = decide(results, trades, specs)
    assert set(candidates) <= {s.variant_id for s in specs}
    assert all(r.verdict in {"failed_train", "failed_validation", "candidate", "not_selected"} for r in results.values())
    assert all(r.reasons for r in results.values() if r.verdict.startswith("failed"))
