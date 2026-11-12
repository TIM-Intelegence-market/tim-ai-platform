"""S26 effort against result: fixed candle rules, mirrored per direction, results-blind count."""
from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from src.research_lab.data.parse import Kline
from src.research_lab.protocol import VALIDATION_START_MS
from src.research_lab.studies import s22, s26
from src.research_lab.studies.s20 import HOUR

START = int(datetime(2022, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _bar(k: int, o: float, h: float, low: float, c: float, vol: float, buy: float) -> Kline:
    return Kline(START + k * HOUR, o, h, low, c, vol, START + (k + 1) * HOUR - 1, buy)


def _base(n: int = 30) -> list[Kline]:
    return [_bar(k, 100, 101, 99, 100, 10.0, 5.0) for k in range(n)]


def test_absorption_initiative_sweep_and_mirror():
    bars = _base()
    # sellers aggressive (buy 3 of 20 -> delta share -0.7), double volume, close in the upper half
    bars.append(_bar(30, 100, 101, 98, 100.8, 20.0, 3.0))
    r = s26.candle_reading(bars, 30, 2.0)
    assert s26.patterns_for(r, "LONG") == ("ABSORPTION",)
    assert "ABSORPTION" not in s26.patterns_for(r, "SHORT")
    # buyers aggressive, high effort, close at the top, body 1 ATR: initiative for Long only
    bars[30] = _bar(30, 100, 102.1, 99.9, 102, 20.0, 15.0)
    r = s26.candle_reading(bars, 30, 2.0)
    assert s26.patterns_for(r, "LONG") == ("INITIATIVE",)
    assert s26.patterns_for(r, "SHORT") == ()
    # big range on low effort, body down: sweep for Short
    bars[30] = _bar(30, 103, 103.2, 99.5, 99.6, 6.0, 3.0)
    r = s26.candle_reading(bars, 30, 2.0)
    assert s26.patterns_for(r, "SHORT") == ("SWEEP",) and s26.patterns_for(r, "LONG") == ()


def test_reading_needs_history_and_uses_only_the_past():
    bars = _base()
    assert s26.candle_reading(bars, 10, 1.0) is None  # fewer than 24 candles before
    r = s26.candle_reading(bars, 29, 1.0)
    later = bars + [_bar(30, 1, 500, 0.5, 400, 1e6, 1e6)]
    assert s26.candle_reading(later, 29, 1.0) == r


def _series(hours: int) -> list[Kline]:
    rng = random.Random(5)
    out, price = [], 40000.0
    for k in range(hours):
        move = rng.gauss(0, 60)
        o, c = price, price + move
        vol = rng.uniform(5, 20)
        out.append(_bar(k, o, max(o, c) + rng.uniform(5, 40), min(o, c) - rng.uniform(5, 40), c, vol, vol * rng.uniform(0.2, 0.8)))
        price = c
    return out


def test_count_is_results_blind():
    bars = _series(s22.WINDOW_1H + 200)
    rows = s26.build_rows(bars)
    assert rows and all(r.net_r is None for r in rows)
    counted = s26.count(rows)
    assert counted["training"]["zeilen"] == len(rows)
    assert set(counted["gate"]) == set(s26.PATTERNS)
    with_r = s26.build_rows(bars, rates=[])
    assert len(with_r) == len(rows) and all(r.net_r is not None for r in with_r)


def _planted(effect: float, seed: int) -> list[s26.Row]:
    rng = random.Random(seed)
    rows = []
    for section, start in (("training", START), ("validierung", VALIDATION_START_MS)):
        for j in range(60 * 14):
            t = start + j * 12 * HOUR
            for d in s22.DIRECTIONS:
                pats = tuple(p for p in s26.PATTERNS if rng.random() < 0.2)
                bonus = effect if "ABSORPTION" in pats else 0.0
                rows.append(s26.Row(t, section, d, pats, bonus + rng.gauss(0, 1.0)))
    return rows


def test_planted_absorption_passes_noise_fails(monkeypatch):
    monkeypatch.setattr(s26, "VERSION", "1.0")
    monkeypatch.setattr(s26, "MIN_WEEKS", 20)
    good = s26.evaluate(_planted(0.6, 1), boot_draws=199, shift_draws=49)
    assert good["muster"]["ABSORPTION"]["urteil"].startswith("BESTANDEN")
    assert good["muster"]["SWEEP"]["urteil"] == "NICHT BESTANDEN"
    noise = s26.evaluate(_planted(0.0, 2), boot_draws=199, shift_draws=49)
    assert noise["urteil"] == "NO ROBUST EDGE PROVEN"


def test_draft_refuses_to_evaluate():
    with pytest.raises(SystemExit):
        s26.evaluate([])
