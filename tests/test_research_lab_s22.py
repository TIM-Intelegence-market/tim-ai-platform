"""S22: Chart-Urteil (candle rules) on hypothetical standard trades: outcome, no look-ahead, tests, freeze guard."""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone

import pytest

from src.dashboard import chart_verdict
from src.research_lab.data.parse import Kline
from src.research_lab.protocol import VALIDATION_START_MS
from src.research_lab.studies import s22
from src.research_lab.studies.s20 import HOUR, atr_series
from src.research_lab.studies.s22 import HALF, Row

START = int(datetime(2022, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
WEEK = 7 * 24 * HOUR


def _price(hours: float) -> float:
    return 40000.0 + 4.0 * hours + 900.0 * math.sin(hours / 30.0) + 250.0 * math.sin(hours / 5.0)


def _series(hours: int, start: int = START) -> tuple[list[Kline], list[Kline]]:
    """1h and 30m candles of one wavy path; the 30m candles add up to the 1h candles."""
    half = []
    for j in range(hours * 2):
        o, c = _price(j / 2), _price((j + 1) / 2)
        half.append(Kline(start + j * HALF, o, max(o, c) + 15, min(o, c) - 15, c, 5.0, start + (j + 1) * HALF - 1, 2.5))
    full = []
    for i in range(hours):
        a, b = half[2 * i], half[2 * i + 1]
        full.append(Kline(a.open_time, a.open, max(a.high, b.high), min(a.low, b.low), b.close, 10.0, b.close_time, 5.0))
    return full, half


def _flat(n: int, price: float = 100.0) -> list[Kline]:
    return [Kline(START + i * HOUR, price, price + 0.5, price - 0.5, price, 1.0, START + (i + 1) * HOUR - 1, 0.5) for i in range(n)]


def _set(bars: list[Kline], k: int, *, high: float | None = None, low: float | None = None, close: float | None = None) -> None:
    b = bars[k]
    bars[k] = Kline(b.open_time, b.open, b.high if high is None else high, b.low if low is None else low,
                    b.close if close is None else close, b.volume, b.close_time, b.taker_buy_volume)


def test_outcome_target_stop_first_timeout_and_costs():
    bars = _flat(60)
    cost = 2 * 100.0 * s22.COST_BPS_PER_SIDE / 10_000 / 2.0  # entry and exit near 100, risk 2
    _set(bars, 5, high=104.5)  # target of a Long from candle 0 with ATR 2: 104
    assert s22.outcome(bars, 0, "LONG", 2.0) == pytest.approx(2.0 - (100 + 104) * 0.0005 / 2.0)
    _set(bars, 5, low=97.5)  # same candle now also holds the stop 98: the stop counts
    assert s22.outcome(bars, 0, "LONG", 2.0) == pytest.approx(-1.0 - (100 + 98) * 0.0005 / 2.0)
    assert s22.outcome(bars, 0, "SHORT", 2.0) == pytest.approx(-1.0 - (100 + 102) * 0.0005 / 2.0)  # high 104.5 >= stop 102
    assert s22.outcome(_flat(60), 0, "LONG", 2.0) == pytest.approx(-cost)  # nothing hit: out at the close after 48 h
    assert s22.outcome(_flat(40), 0, "LONG", 2.0) is None  # horizon not in the data
    gap = _flat(60)
    del gap[10]
    assert s22.outcome(gap, 0, "LONG", 2.0) is None


def test_moments_need_warmup_and_stay_inside_their_section():
    hours = s22.WINDOW_1H + 200
    start = VALIDATION_START_MS - (hours - 100) * HOUR  # the path crosses from training into validation
    bars, _ = _series(hours, start)
    picked = s22.moments(bars, atr_series(bars))
    closes = [bars[i].open_time + HOUR for i in picked]
    assert picked and min(picked) >= s22.WINDOW_1H - 1
    for t in closes:
        section = s22.section_of(t)
        assert section and t + s22.HORIZON * HOUR <= s22.SECTIONS[section][1]
    assert not any(VALIDATION_START_MS - s22.HORIZON * HOUR < t < VALIDATION_START_MS for t in closes)  # purged border
    assert all(t + s22.HORIZON * HOUR <= bars[-1].open_time + HOUR for t in closes)


def test_one_missing_candle_does_not_lock_sixty_days():
    hours = s22.WINDOW_1H + 300
    bars, _ = _series(hours)
    full = set(s22.moments(bars, atr_series(bars)))
    gone = s22.WINDOW_1H + 50
    holed = bars[:gone] + bars[gone + 1:]
    kept = s22.moments(holed, atr_series(holed))
    times = {holed[i].open_time for i in kept}
    lost = {bars[i].open_time for i in full} - times
    # Lost: the 48 moments whose horizon holds the hole, the hole itself and the day after it (ATR needs it complete).
    assert 0 < len(lost) <= s22.HORIZON + 1 + s22.RECENT
    assert max(times) == max(bars[i].open_time for i in full)
    many = bars[:gone] + bars[gone + s22.MAX_WARMUP_GAPS + 1:]  # more than 24 candles missing: locked as before
    after = [many[i].open_time for i in s22.moments(many, atr_series(many)) if many[i].open_time > bars[gone].open_time]
    assert not after or min(after) - bars[gone + s22.MAX_WARMUP_GAPS + 1].open_time >= (s22.WINDOW_1H - 2) * HOUR


def test_verdict_uses_only_candles_closed_by_then():
    hours = s22.WINDOW_1H + 120
    bars, half = _series(hours)
    i = s22.WINDOW_1H + 10
    atr = atr_series(bars)[i]

    def run(b1, b30):
        return s22.verdicts(b1, s22.candles(b1, "1h", HOUR), s22.candles(b30, "30m", HALF), [b.open_time for b in b30], i, atr)

    before = run(bars, half)
    later_1h = bars[:i + 1] + [Kline(b.open_time, 1.0, 2.0, 0.5, 1.5, 1.0, b.close_time, 0.5) for b in bars[i + 1:]]
    cut = bars[i].open_time + HOUR
    later_30m = [b if b.open_time + HALF <= cut else Kline(b.open_time, 1.0, 2.0, 0.5, 1.5, 1.0, b.close_time, 0.5) for b in half]
    assert run(later_1h, later_30m) == before  # whatever comes after the close changes nothing
    assert before["LONG"]["ruleset"] == chart_verdict.RULESET
    assert all(p["rule"] in s22.RULES for d in s22.DIRECTIONS for p in before[d]["points"])  # no order flow rule fires
    assert "R6-R8 keine frische Orderflow-Lage" in before["LONG"]["skipped"]


def test_count_is_results_blind_and_rows_carry_both_directions():
    bars, half = _series(s22.WINDOW_1H + 150)
    rows = s22.build_rows(bars, half, with_outcome=False)
    assert rows and all(r.net_r is None for r in rows) and {r.direction for r in rows} == set(s22.DIRECTIONS)
    counted = s22.count(rows)
    assert counted["training"]["trades"] == len(rows) == 2 * counted["training"]["momente"]
    assert counted["gate"] is False  # far too few for the gate
    with_r = s22.build_rows(bars, half, with_outcome=True)
    assert len(with_r) == len(rows) and all(r.net_r is not None for r in with_r)


def test_workers_get_the_data_whatever_the_default_start_method():
    import multiprocessing

    bars, half = _series(s22.WINDOW_1H + 80)
    single = s22.build_rows(bars, half, with_outcome=True)
    before = multiprocessing.get_start_method()
    # Python 3.14 on the PS5 starts workers with forkserver: a plain Pool would see an empty module state.
    multiprocessing.set_start_method("forkserver", force=True)
    try:
        assert s22.build_rows(bars, half, with_outcome=True, workers=2) == single
    finally:
        multiprocessing.set_start_method(before, force=True)


def _rows(n_weeks: int, effect: float, seed: int = 1, start: int = VALIDATION_START_MS) -> list[Row]:
    """Synthetic rows: decisions in runs of two days, outcome = noise + effect for NEHMEN, - effect for AUSLASSEN."""
    rng = random.Random(seed)
    rows = []
    decisions = (chart_verdict.TAKE, chart_verdict.NEUTRAL, chart_verdict.SKIP)
    for h in range(n_weeks * 7 * 24):
        for d, direction in enumerate(s22.DIRECTIONS):
            decision = decisions[(h // 48 + d) % 3]
            shift = effect if decision == chart_verdict.TAKE else -effect if decision == chart_verdict.SKIP else 0.0
            t = start + h * HOUR
            rows.append(Row(t, s22.section_of(t), direction, 0, decision, (0, 0, 0, 0, 0), rng.gauss(-0.1, 1.2) + shift))
    return rows


def test_planted_effect_passes_and_noise_fails(monkeypatch):
    monkeypatch.setattr(s22, "VERSION", "1.0")
    train_start = VALIDATION_START_MS - 60 * WEEK
    good = _rows(55, 0.25, seed=2, start=train_start) + _rows(60, 0.25, seed=3)
    result = s22.evaluate(good, boot_draws=499, shift_draws=99)
    assert result["urteil"] == "BESTANDEN (Kandidat)" and result["h1"]["nehmen_minus_auslassen_r"] > 0.3
    assert all(result["kriterien"].values())
    noise = _rows(55, 0.0, seed=4, start=train_start) + _rows(60, 0.0, seed=5)
    result = s22.evaluate(noise, boot_draws=499, shift_draws=99)
    assert result["urteil"] == "NICHT BESTANDEN"
    few = _rows(55, 0.25, seed=2, start=train_start)[:500] + _rows(60, 0.25, seed=3)
    assert s22.evaluate(few, boot_draws=99, shift_draws=19)["urteil"] == "nicht testbar (Gate)"


def test_describe_reports_rules_and_scores():
    rows = [Row(VALIDATION_START_MS, "validierung", "LONG", 2, chart_verdict.TAKE, (1, 1, 0, -1, 0), 1.0),
            Row(VALIDATION_START_MS, "validierung", "SHORT", -2, chart_verdict.SKIP, (-1, -1, 0, 0, 0), -1.0)]
    d = s22.describe(rows)
    assert d["regeln"]["R1"]["dafuer"] == {"n": 1, "mittel_netto_r": 1.0} and d["regeln"]["R4"]["dagegen"]["n"] == 1
    assert d["score"]["2"]["n"] == 1 and d["entscheidung"][chart_verdict.SKIP]["mittel_netto_r"] == -1.0


def test_archive_refs_cover_both_intervals_and_stop_before_the_holdout():
    for interval in ("1h", "30m"):  # the first PS5 count run stopped here: 30m was not an archive interval
        rs = s22.refs(interval)
        assert rs[0].period == "2019-10" and rs[-1].period == "2024-12" and all(r.interval == interval for r in rs)


def test_frozen_version_and_draft_guard(tmp_path, monkeypatch):
    assert s22.VERSION == "1.0"
    monkeypatch.setattr(s22, "VERSION", "0.9")  # a later draft must lock evaluate again
    with pytest.raises(SystemExit):
        s22.evaluate([])
    with pytest.raises(SystemExit):
        s22.main(["evaluate", "--root", str(tmp_path), "--out", str(tmp_path)])
