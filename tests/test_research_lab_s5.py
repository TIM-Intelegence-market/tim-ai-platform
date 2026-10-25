"""Study S5 episode rules (docs/research_lab/studien/S5_WINRATE_95_FUNDING_CARRY_PRAEREGISTRIERUNG.md, section 4.1)
and the outcome-blind count (6.1)."""
from __future__ import annotations

from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.hypotheses import s5

H = s5.HOUR_MS
F = 8 * H
T0 = 1_577_836_800_000  # 2020-01-01T00:00:00Z
V7 = s5.S5Variant("test-t01-h7", 10_000, 7 * s5.DAY_MS)


def funding(rates: list[float], t0: int = T0) -> list[FundingRate]:
    return [FundingRate(t0 + i * F, r) for i, r in enumerate(rates)]


def hours(n: int, *, missing: set[int] = frozenset(), t0: int = T0) -> list[int]:
    return [t0 + i * H for i in range(n) if i not in missing]


def bars(times: list[int]) -> list[Kline]:
    return [Kline(t, 1.0, 1.0, 1.0, 1.0, 1.0, t + H - 1, 0.5) for t in times]


def test_entry_needs_rate_strictly_above_theta_and_fills_one_hour_later() -> None:
    rates = [0.0001] * 5 + [0.00011] + [0.0001] * 40
    count = s5.episodes(funding(rates), hours(400), V7, T0, T0 + 400 * H)
    assert len(count.episodes) == 1
    episode = count.episodes[0]
    assert episode.signal_time == T0 + 5 * F and episode.entry_fill == T0 + 5 * F + H
    # exactly 0.01 % never qualifies (integer units, no float noise)
    assert s5.episodes(funding([0.0001] * 30), hours(400), V7, T0, T0 + 400 * H).episodes == []


def test_min_hold_then_exit_at_first_non_positive_rate() -> None:
    # rate > theta at t=0, then negative at period 2 (inside the 7-day hold), zero at period 25 (after the hold)
    rates = [0.0003, 0.0002, -0.0001] + [0.0002] * 22 + [0.0] + [0.0001] * 10
    count = s5.episodes(funding(rates), hours(400), V7, T0, T0 + 400 * H)
    assert len(count.episodes) == 1
    episode = count.episodes[0]
    assert episode.reason == "regular"
    assert episode.exit_fill == T0 + 25 * F + H  # the zero rate at period 25, fill one hour later
    assert episode.duration_ms >= V7.hold_ms


def test_reentry_lock_second_funding_time_after_exit() -> None:
    rates = [0.0003] + [0.0002] * 21 + [0.0] + [0.0003] * 30
    count = s5.episodes(funding(rates), hours(600), V7, T0, T0 + 600 * H)
    assert len(count.episodes) == 2
    first, second = count.episodes
    assert first.exit_fill == T0 + 22 * F + H
    # funding time 23 is the first after the exit fill, 24 is the second: earliest allowed entry
    assert second.signal_time == T0 + 24 * F
    assert count.skipped_locked == 1


def test_gap_closes_the_episode_on_the_last_present_bar() -> None:
    rates = [0.0003] + [0.0002] * 60
    missing = {50}  # hour 50 is missing in one of the two series
    count = s5.episodes(funding(rates), hours(600, missing=missing), V7, T0, T0 + 600 * H)
    assert len(count.episodes) >= 1
    assert count.episodes[0].reason == "gap" and count.episodes[0].exit_fill == T0 + 50 * H


def test_section_end_and_max_hold() -> None:
    rates = [0.0003] + [0.0002] * 400  # never non-positive
    end = T0 + 30 * s5.DAY_MS
    count = s5.episodes(funding(rates), hours(400 * 8), V7, T0, end)
    assert count.episodes[0].reason == "section_end" and count.episodes[0].exit_fill == end
    count = s5.episodes(funding(rates), hours(400 * 8), V7, T0, T0 + 130 * s5.DAY_MS)
    assert count.episodes[0].reason == "max_hold" and count.episodes[0].duration_ms == s5.MAX_HOLD_MS


def test_signal_without_entry_bar_is_invalid() -> None:
    rates = [0.0003] + [0.0001] * 10
    count = s5.episodes(funding(rates), hours(200, missing={1}), V7, T0, T0 + 200 * H)
    assert count.invalid_signals == 1 and not count.episodes


def test_count_uses_no_prices() -> None:
    perp = bars(hours(100))
    spot = bars(hours(100, missing={7}))
    assert s5.common_hours(perp, spot) == hours(100, missing={7})
    assert len(s5.S5_VARIANTS) == 4 and len({v.variant_id for v in s5.S5_VARIANTS}) == 4


def test_count_script_refs_stop_before_holdout() -> None:
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("s5_script", Path("scripts/research_lab_s5.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    refs = module.all_refs()
    assert refs and not any(ref.touches_holdout for ref in refs)
    assert {(r.market.value, r.symbol) for r in refs} >= {("spot", "SOLUSDT"), ("futures/um", "SOLUSDT")}
