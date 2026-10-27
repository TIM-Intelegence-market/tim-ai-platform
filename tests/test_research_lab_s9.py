"""Study S9: CHoCH -> retest band -> reaction close (rules only, synthetic bars, no market data)."""

from __future__ import annotations

import pytest

from src.research_lab.backtest.engine import run_backtest
from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses import s9

T0 = 1_577_836_800_000  # 2020-01-01 00:00 UTC
WICK = 0.5


def _path(waypoints: list[float], step: float = 3.0) -> list[float]:
    closes = [waypoints[0]]
    for target in waypoints[1:]:
        while abs(target - closes[-1]) > 1e-9:
            move = min(step, abs(target - closes[-1]))
            closes.append(closes[-1] + move * (1 if target > closes[-1] else -1))
    return closes


def _bars(closes: list[float], start: int = T0, gap_at: int | None = None) -> list[Kline]:
    bars, prev, t = [], closes[0], start
    for i, close in enumerate(closes):
        if gap_at is not None and i == gap_at:
            t += s9.INTERVAL_MS
        o = (prev + close) / 2  # open between closes, so a turning bar is a strict pivot
        bars.append(Kline(t, o, max(o, close) + WICK, min(o, close) - WICK, close, 10.0, t + s9.INTERVAL_MS - 1, 5.0))
        prev, t = close, t + s9.INTERVAL_MS
    return bars


WARMUP = [100.0 + (i % 2) * 0.2 for i in range(20)]
# H1 120 -> L1 112 -> H2 116 (lower high) -> L2 111 (lower low) -> CHoCH above 116.5 -> impulse 150 -> back to the band
LONG = WARMUP + _path([100, 120, 112, 116, 111, 150, 117], 3.0)[1:]


def _run(closes: list[float], variant: s9.S9Variant = s9.S9_VARIANTS[0], **kw):
    counts = s9.Counts()
    detector = s9.Detector(variant, counts)
    signals = []
    bars = _bars(closes, **kw)
    for t, bar in enumerate(bars):
        signal = detector.step(bar)
        if signal is not None:
            signals.append((t, signal))
    return bars, signals, counts


def _with_reaction(closes: list[float], last: float = 121.0) -> list[float]:
    return closes + [last]


def test_variants_are_the_preregistered_grid() -> None:
    assert [v.variant_id for v in s9.S9_VARIANTS] == ["S9-B25-I", "S9-B50-I", "S9-B25-Z", "S9-B50-Z"]
    assert {spec.variant_id for spec in s9.specs()} == {v.variant_id for v in s9.S9_VARIANTS}
    assert all(spec.horizon == "short" and spec.interval == "15m" and spec.grid_axes == ("b",) for spec in s9.specs())


def test_long_setup_choch_touch_reaction_gives_one_signal() -> None:
    bars, signals, counts = _run(_with_reaction(LONG))
    assert counts.choch >= 1 and len(signals) == 1
    t, signal = signals[0]
    assert t == len(bars) - 1 and signal.side == 1
    origin = min(b.low for b in bars[: t + 1] if b.open_time >= bars[0].open_time)
    assert signal.stop < 111 - WICK  # below the origin low, with the 0.1 ATR buffer
    risk = bars[t].close - signal.stop
    assert signal.target_r == pytest.approx((150 + WICK - bars[t].close) / risk)
    assert signal.target_r >= s9.MIN_RR and signal.time_stop_bars == s9.TIME_STOP_BARS
    assert origin <= 111 - WICK


def test_touch_alone_is_no_signal() -> None:
    _, signals, counts = _run(LONG)  # last bar sits in the band, no reaction close yet
    assert signals == [] and counts.emitted == 0


def test_equal_close_is_no_break() -> None:
    # the LH wick high is 116.5; closing exactly there is no CHoCH
    closes = WARMUP + _path([100, 120, 112, 116, 111, 116.5], 3.0)[1:] + [116.5, 116.5]
    _, _, counts = _run(closes)
    assert counts.choch == 0


def test_close_through_the_lower_high_without_a_lower_low_is_no_choch() -> None:
    # H1 120 -> L1 112 -> H2 116 (LH) -> only 113 (higher low) -> up through 116.5: no LH -> LL sequence
    closes = WARMUP + _path([100, 120, 112, 116, 113, 150, 117], 3.0)[1:] + [121.0]
    _, signals, counts = _run(closes)
    assert counts.choch == 0 and signals == []


def test_one_label_per_impulse() -> None:
    closes = _with_reaction(LONG) + _path([121, 114, 125], 3.0)[1:]  # dips below the level again and closes back above
    _, _, counts = _run(closes)
    assert counts.choch == 1


def test_origin_breach_kills_the_sequence() -> None:
    closes = WARMUP + _path([100, 120, 112, 116, 111, 150, 117, 109], 3.0)[1:] + [121.0]
    _, signals, counts = _run(closes)
    assert signals == [] and counts.invalidated >= 1


def test_rr_below_two_is_skipped() -> None:
    # small impulse: 116.5 -> 122 only, then back and react; reward far below 2 R
    closes = WARMUP + _path([100, 120, 112, 116, 111, 122, 117], 3.0)[1:] + [119.0]
    _, signals, counts = _run(closes)
    assert signals == [] and counts.rr_rejected == 1


def test_setup_expires_after_48_bars() -> None:
    closes = WARMUP + _path([100, 120, 112, 116, 111, 150], 3.0)[1:] + [150.0 + (i % 2) for i in range(60)]
    closes += _path([150, 117], 3.0)[1:] + [121.0]
    _, signals, counts = _run(closes)
    assert signals == [] and counts.expired == 1


def test_rules_are_causal_prefix_gives_the_same_signals() -> None:
    closes = _with_reaction(LONG) + _path([121, 160, 130, 170], 3.0)[1:]
    _, full, _ = _run(closes)
    for cut in range(30, len(closes), 7):
        _, part, _ = _run(closes[:cut])
        assert part == [s for s in full if s[0] < cut]


def test_data_gap_resets_the_structure() -> None:
    gap_at = len(LONG) - 8  # missing 15m bar during the impulse
    _, signals, counts = _run(_with_reaction(LONG), gap_at=gap_at)
    assert signals == [] and counts.resets == 1


def test_short_is_the_mirror_image() -> None:
    closes = [200 - c for c in _with_reaction(LONG)]
    _, signals, _ = _run(closes)
    assert len(signals) == 1 and signals[0][1].side == -1 and signals[0][1].target_r >= s9.MIN_RR


def test_zone_variant_needs_a_previous_day_and_week() -> None:
    _, signals, counts = _run(_with_reaction(LONG), s9.S9_VARIANTS[2])
    assert signals == [] and counts.zone_rejected >= 1


def test_zone_levels_come_from_closed_days_and_weeks_only() -> None:
    htf = s9.HigherTimeframe()
    day = 96
    bars = _bars([100.0 + (i % 5) for i in range(day * 22)])
    for bar in bars[: day * 21]:
        htf.add(bar)
    assert htf.daily_atr() is not None and htf.day_levels and htf.week_levels
    assert htf.day_levels == s9.period_levels(bars[day * 19: day * 20])  # day 21 is still running
    htf.add(bars[day * 21])  # the first bar of a new day closes the previous one
    assert htf.day_levels == s9.period_levels(bars[day * 20: day * 21])
    assert htf.near_level(max(htf.day_levels))
    assert not htf.near_level(max(htf.day_levels) + 100)


def test_volume_profile_puts_poc_where_volume_sits() -> None:
    bars = _bars([100.0] * 10 + [110.0])
    poc, vah, val = s9.volume_profile(bars)
    assert val <= poc <= vah and poc < 102


def test_engine_run_and_outcome_blind_count_agree_on_signals() -> None:
    bars = _bars(_with_reaction(LONG) + _path([121, 160], 3.0)[1:])
    result = run_backtest(bars, s9.choch_retest(s9.S9_VARIANTS[0]), s9.INTERVAL_MS)
    count = s9.count_signals(bars, s9.S9_VARIANTS[0], bars[0].open_time, bars[-1].open_time + 1)
    assert len(result.signals) == count.upper == 1
    assert result.trades and result.trades[0].target_r >= s9.MIN_RR


def test_count_script_writes_an_outcome_blind_report(tmp_path) -> None:
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location("research_lab_s9", "scripts/research_lab_s9.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    class FakeStore:
        def load_klines(self, refs):
            return _bars(_with_reaction(LONG) + _path([121, 160], 3.0)[1:])

        def dataset_hash(self, refs):
            return "fake"

    assert script.count(FakeStore(), tmp_path) == 0
    report = json.loads(next(tmp_path.glob("s9_count_*.json")).read_text())
    assert report["outcome_blind"] and set(report["variants"]) == {v.variant_id for v in s9.S9_VARIANTS}
    row = report["variants"]["S9-B25-I"]
    assert row["train"]["upper"] == 1 and not row["passes_gate"]
    assert "r" not in row["train"] and "expectancy" not in json.dumps(report)
    assert (tmp_path / next(tmp_path.glob("s9_count_*.md")).name).read_text().startswith("# S9 Zähllauf")
