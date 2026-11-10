"""S20: swing levels, clear breaks, flip label, no look-ahead, window features, model, tests and the freeze guard."""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone

import pytest

from src.research_lab.data.parse import Kline
from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS
from src.research_lab.studies import s20
from src.research_lab.studies.s20 import DOWN, HOUR, UP, Event, Row

START = int(datetime(2021, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _bar(i: int, close: float, *, high: float | None = None, low: float | None = None, open_: float | None = None,
         volume: float = 10.0, taker: float = 5.0, start: int = START) -> Kline:
    o = close if open_ is None else open_
    return Kline(start + i * HOUR, o, max(o, close) + 0.5 if high is None else high,
                 min(o, close) - 0.5 if low is None else low, close, volume, start + (i + 1) * HOUR - 1, taker)


def _series(closes: list[float], **kw) -> list[Kline]:
    return [_bar(i, c, **kw) for i, c in enumerate(closes)]


def _peak_then_break(after: list[float]) -> list[Kline]:
    """100 flat candles, a peak at index 100 (high 110), 60 calm candles below it, then ``after``."""
    closes = [100.0] * 100 + [105.0] + [100.0] * 60 + after
    bars = _series(closes)
    bars[100] = _bar(100, 105.0, high=110.0)
    return bars


def test_pivot_is_found_and_known_only_k_candles_later():
    bars = _peak_then_break([100.0] * 40)
    highs, _lows = s20.pivots(bars)
    peak = [lv for lv in highs if lv.pivot == 100]
    assert len(peak) == 1 and peak[0].price == 110.0 and peak[0].confirmed == 100 + s20.PIVOT_K


def test_gap_inside_the_pivot_span_drops_the_pivot():
    bars = _peak_then_break([100.0] * 40)
    bars = bars[:110] + [Kline(b.open_time + HOUR, b.open, b.high, b.low, b.close, b.volume, b.close_time + HOUR, b.taker_buy_volume)
                         for b in bars[110:]]
    highs, _ = s20.pivots(bars)
    assert not [lv for lv in highs if lv.pivot == 100]


def test_clear_break_is_one_event_at_the_break_candle():
    bars = _peak_then_break([112.0] + [113.0] * 30)
    events, _drops = s20.find_events(bars)
    ups = [e for e in events if e.direction == UP]
    assert [(e.index, e.level) for e in ups] == [(161, 110.0)]
    assert ups[0].section == "training" and s20.label(bars, ups[0]) == 1


def test_close_just_beyond_leaves_the_level_alive_until_a_clear_close():
    bars = _peak_then_break([110.1] + [113.0] * 30)  # ATR is about 1, so 0.1 above is not clear
    ups = [e for e in s20.find_events(bars)[0] if e.direction == UP]
    assert [(e.index, e.level) for e in ups] == [(162, 110.0)]


def test_failed_break_is_labelled_zero():
    bars = _peak_then_break([112.0] + [111.0] * 5 + [109.0] + [111.0] * 30)
    up = next(e for e in s20.find_events(bars)[0] if e.direction == UP)
    assert s20.label(bars, up) == 0


def test_features_and_event_do_not_use_candles_after_the_break():
    a = _peak_then_break([112.0] + [113.0] * 30)
    b = _peak_then_break([112.0] + [90.0] * 30)
    ea = next(e for e in s20.find_events(a)[0] if e.direction == UP)
    eb = next(e for e in s20.find_events(b)[0] if e.direction == UP)
    assert ea == eb
    assert s20.candle_features(a, ea) == s20.candle_features(b, eb)
    assert all(s20.window_features(a, ea, n) == s20.window_features(b, eb, n) for n in s20.WINDOWS)
    assert s20.label(a, ea) != s20.label(b, eb)


def test_event_needs_the_full_label_window_inside_its_section():
    start = VALIDATION_START_MS - 170 * HOUR  # the break at index 161 has its label window across New Year
    closes = [100.0] * 100 + [105.0] + [100.0] * 60 + [112.0] + [113.0] * 30
    bars = _series(closes, start=start)
    bars[100] = _bar(100, 105.0, high=110.0, start=start)
    events, drops = s20.find_events(bars)
    assert not [e for e in events if e.direction == UP] and drops["abschnittsende"] == 1


def test_debounce_skips_a_second_break_inside_the_label_window():
    closes = [100.0] * 100 + [105.0] + [100.0] * 30 + [106.0] + [100.0] * 60 + [112.0] + [113.0] * 30
    bars = _series(closes)
    bars[100] = _bar(100, 105.0, high=110.0)
    bars[131] = _bar(131, 106.0, high=115.0)
    bars += [_bar(len(bars) + i, 117.0) for i in range(30)]  # breaks the 115 level 31 candles later: allowed
    events, _ = s20.find_events(bars)
    ups = [e for e in events if e.direction == UP]
    assert [e.level for e in ups] == [110.0, 115.0] and ups[1].index - ups[0].index > s20.HOLD_BARS


def test_holdout_is_outside_every_section_and_never_requested():
    assert s20.section_of(HOLDOUT_START_MS) is None
    assert s20.section_of(HOLDOUT_START_MS - 1) == "validierung"
    assert all((r.year, r.month) <= (2024, 12) for r in s20.refs())


def test_window_features_change_with_the_window_but_not_the_event():
    bars = _peak_then_break([112.0] + [113.0] * 30)
    bars[158] = _bar(158, 100.0, high=109.9)  # a test of the level 3 candles before the break
    e = next(e for e in s20.find_events(bars)[0] if e.direction == UP)
    f5, f50 = s20.window_features(bars, e, 5), s20.window_features(bars, e, 50)
    assert f5[1] == pytest.approx(1 / 5) and f50[1] == pytest.approx(1 / 50)


def test_down_break_mirrors_up():
    closes = [100.0] * 100 + [95.0] + [100.0] * 60 + [88.0] + [87.0] * 30
    bars = _series(closes)
    bars[100] = _bar(100, 95.0, low=90.0)
    down = next(e for e in s20.find_events(bars)[0] if e.direction == DOWN)
    assert down.level == 90.0 and s20.label(bars, down) == 1
    f = s20.candle_features(bars, down)
    assert f[2] > 0 and f[6] == 0.0  # distance counted in break direction, direction flag 0


def test_fit_finds_a_planted_signal():
    rng = random.Random(1)
    x = [[rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(600)]
    y = [int(rng.random() < 1 / (1 + math.exp(-2 * a))) for a, _ in x]
    m = s20.fit(x, y)
    assert m.beta[1] > 1.0 and abs(m.beta[2]) < 0.4
    assert 0 < m.predict([3, 0]) < 1 and m.predict([3, 0]) > m.predict([-3, 0])


def test_auc_and_quintile_spread():
    assert s20.auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert s20.auc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]) == 0.5
    assert s20.quintile_spread_pp([0] * 5 + [1] * 5, [i / 10 for i in range(10)]) == 100.0


def test_window_choice_prefers_the_smallest_within_the_margin(monkeypatch):
    scores = {5: 0.6800, 10: 0.6790, 20: 0.6788, 50: 0.6700}
    monkeypatch.setattr(s20, "cv_loss", lambda rows, n: scores[n])
    assert s20.choose_window([])[0] == 50
    scores[50] = 0.6786
    assert s20.choose_window([])[0] == 10  # 0.6790 is within 0.0005 of the best 0.6786


def test_block_bootstrap_is_reproducible_and_directional():
    weeks = [i // 3 for i in range(300)]
    good = [0.05 + 0.01 * ((i % 7) - 3) for i in range(300)]
    a = s20.block_bootstrap_p(weeks, good, seed="x", draws=499)
    assert a == s20.block_bootstrap_p(weeks, good, seed="x", draws=499) and a < 0.01
    assert s20.block_bootstrap_p(weeks, [-g for g in good], seed="x", draws=499) > 0.99


def test_count_is_results_blind_and_gates():
    ev = [Event(i, START + i * 30 * HOUR * 7, UP, 1.0, 0, 1.0, "training") for i in range(10)]
    out = s20.count(ev, {"unklar": 3})
    text = repr(out)
    assert "flip" not in text and "label" not in text
    assert out["abschnitte"]["training"]["ereignisse"] == 10 and not out["gate_bestanden"]


def _rows(signal: float, seed: int) -> list[Row]:
    rng = random.Random(seed)
    rows = []
    spans = [(2017, 2018, 60), (2019, 2019, 50), (2020, 2020, 50), (2021, 2021, 50), (2022, 2022, 50),
             (2023, 2023, 60), (2024, 2024, 60)]
    for y0, _, n in spans:
        t0 = int(datetime(y0, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)
        for i in range(n):
            t = t0 + i * 120 * HOUR
            c = [rng.gauss(0, 1) for _ in s20.CANDLE_FEATURES]
            w = {k: tuple(rng.gauss(0, 1) for _ in s20.WINDOW_FEATURES) for k in s20.WINDOWS}
            y = int(rng.random() < 1 / (1 + math.exp(-signal * c[0])))
            rows.append(Row(t, s20.week_of(t), y0, s20.section_of(t), UP, y, tuple(c), w))
    return rows


def test_evaluate_refuses_while_the_rules_are_a_draft():
    with pytest.raises(PermissionError):
        s20.evaluate(_rows(0.0, 1))


def test_evaluate_passes_a_planted_signal_and_rejects_noise():
    strong = s20.evaluate(_rows(3.0, 2), shift_draws=3, boot_draws=199, version="1.0")
    assert strong["H1_gegen_mechanik"]["rel_gewinn"] > 0.1 and "H1" in strong["holm_bestanden"]
    assert strong["glueckstest"]["p"] == 0.25  # 3 draws: nothing shifted reaches the planted signal
    noise = s20.evaluate(_rows(0.0, 3), shift_draws=3, boot_draws=199, version="1.0")
    assert not noise["H1_bestanden"] and noise["urteil"].startswith("NICHT BESTANDEN")


def test_distance_alone_does_not_pass_h1():
    """A flip that depends only on the distance beyond the line (random-walk mechanics) is not candle structure."""
    rows = _rows(0.0, 4)
    rng = random.Random(9)
    rows = [s20._relabel(r, int(rng.random() < 1 / (1 + math.exp(-3 * r.candle[s20.MECHANICS_FEATURE])))) for r in rows]
    out = s20.evaluate(rows, shift_draws=3, boot_draws=199, version="1.0")
    assert out["H1_gegen_mechanik"]["rel_gewinn_mechanik_gegen_basisrate"] > 0.1
    assert not out["H1_bestanden"]
