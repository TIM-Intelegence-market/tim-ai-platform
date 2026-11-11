"""S21: order flow and funding features at S20's breaks, each family against the mechanics model, freeze guard."""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone

import pytest

from src.research_lab.data.parse import Kline
from src.research_lab.studies import s19, s20, s21
from src.research_lab.studies.s20 import DOWN, HOUR, UP, Event
from src.research_lab.studies.s21 import Row

START = int(datetime(2021, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _bar(i: int, close: float, *, high: float | None = None, volume: float = 10.0, taker: float = 5.0) -> Kline:
    return Kline(START + i * HOUR, close, close + 0.5 if high is None else high, close - 0.5, close, volume,
                 START + (i + 1) * HOUR - 1, taker)


def _break_series() -> tuple[list[Kline], Event]:
    bars = [_bar(i, c) for i, c in enumerate([100.0] * 100 + [105.0] + [100.0] * 60 + [112.0] + [113.0] * 30)]
    bars[100] = _bar(100, 105.0, high=110.0)
    event = next(e for e in s20.find_events(bars)[0] if e.direction == UP)
    return bars, event


def _replace(bars: list[Kline], k: int, **kw) -> None:
    b = bars[k]
    fields = {"open_time": b.open_time, "open": b.open, "high": b.high, "low": b.low, "close": b.close,
              "volume": b.volume, "close_time": b.close_time, "taker_buy_volume": b.taker_buy_volume} | kw
    bars[k] = Kline(**fields)


def test_s20_events_and_rules_are_reused_unchanged():
    _, e = _break_series()
    assert e.index == 161 and e.level == 110.0
    assert s21.WINDOW == 10 and s20.VERSION != s21.VERSION


def test_cvd_share_and_divergence():
    bars, e = _break_series()
    for k in range(e.index - 10, e.index + 1):
        _replace(bars, k, taker_buy_volume=8.0, close=100.0 + (k - e.index + 10) * 0.2 if k < e.index else bars[k].close)
    share, together, _ = s21.candle_flow(bars, e)
    assert share == pytest.approx(0.6) and together > 0.5
    for k in range(e.index - 10, e.index + 1):
        _replace(bars, k, taker_buy_volume=2.0)
    share, together, _ = s21.candle_flow(bars, e)
    assert share == pytest.approx(-0.6) and together < -0.5  # price rises while sellers dominate: divergence


def test_volume_trend_into_the_break():
    bars, e = _break_series()
    for j, k in enumerate(range(e.index - 10, e.index)):
        _replace(bars, k, volume=10.0 * (1 + j), taker_buy_volume=5.0 * (1 + j))
    assert s21.candle_flow(bars, e)[2] > 1.0


def test_candle_flow_ignores_candles_after_the_break():
    bars, e = _break_series()
    before = s21.candle_flow(bars, e)
    for k in range(e.index + 1, len(bars)):
        _replace(bars, k, volume=999.0, taker_buy_volume=0.0, close=50.0)
    assert s21.candle_flow(bars, e) == before


def test_footprint_counts_todays_flags_with_and_against_the_break():
    today = s19.TODAY_KEYS
    t = START + 100 * HOUR
    q = s21.FP_CANDLE_MS
    readings = {t + (k - 4) * q: s19.Reading(t + (k - 4) * q, 100.0, True, 30, ()) for k in range(8)}
    readings[t] = s19.Reading(t, 100.0, True, 30, (f"{today['I']}|up", f"{today['C']}|down", "I:3x2|up"))
    readings[t - 4 * q] = s19.Reading(t - 4 * q, 100.0, True, 30, (f"{today['I']}|up",))
    f = dict(zip(s21.FEATURES["F"], s21.footprint_features(readings, t, UP, today)))
    assert f["fp_I"] == pytest.approx(2 / 8) and f["fp_C"] == pytest.approx(-1 / 8)  # grid neighbour ignored
    assert s21.footprint_features(readings, t, DOWN, today)[0] == pytest.approx(-2 / 8)
    readings[t + 3 * q] = s19.Reading(t + 3 * q, 0.0, False, 0, ())
    assert s21.footprint_features(readings, t, UP, today) is None
    readings.pop(t + 3 * q)
    assert s21.footprint_features(readings, t, UP, today) is None


def test_funding_only_rates_known_at_the_break_close():
    e = Event(500, START + 100 * 24 * HOUR, UP, 1.0, 0, 1.0, "training")
    rates = [(START + k * 8 * HOUR, 0.0001) for k in range(299)]
    rates.append((e.time + HOUR, 0.0005))  # published at the break close: known
    rates.append((e.time + 9 * HOUR, 0.01))  # later: ignored
    last, z = s21.funding_features(rates, e)
    assert last == pytest.approx(5.0) and z == 0.0
    assert s21.funding_features(rates, Event(e.index, e.time, DOWN, 1.0, 0, 1.0, "training"))[0] == pytest.approx(-5.0)
    assert s21.funding_features(rates[:50], e) is None


def _rows(planted: str | None, seed: int, *, mechanics_signal: float = 0.0) -> list[Row]:
    rng = random.Random(seed)
    rows = []
    t0 = int(datetime(2020, 1, 6, tzinfo=timezone.utc).timestamp() * 1000)
    for i in range(1000):  # 2020-01 to about 2024-10, one event every 42 h
        t = t0 + i * 42 * HOUR
        section = s20.section_of(t)
        if section is None:
            break
        extra = {f: tuple(rng.gauss(0, 1) for _ in s21.FEATURES[f]) for f in s21.FAMILIES}
        mech = abs(rng.gauss(0, 1))
        z = mechanics_signal * mech + (3.0 * extra[planted][0] if planted else 0.0)
        rows.append(Row(t, s20.week_of(t), section, int(rng.random() < 1 / (1 + math.exp(-z))), mech, extra))
    return rows


def test_planted_flow_passes_only_its_own_family():
    out = s21.evaluate(_rows("F", 1), boot_draws=199, shift_draws=39, version="1.0")
    assert out["urteile"]["F"] == "BESTANDEN (Kandidat)"
    assert out["familien"]["F"]["rel_gewinn"] > 0.1 and "F" in out["holm_bestanden"]
    assert out["urteile"]["K"] == "NICHT BESTANDEN" and out["urteile"]["G"] == "NICHT BESTANDEN"


def test_distance_alone_passes_no_family():
    out = s21.evaluate(_rows(None, 2, mechanics_signal=2.0), boot_draws=199, shift_draws=3, version="1.0")
    assert all(v == "NICHT BESTANDEN" for v in out["urteile"].values())
    assert out["urteil"].startswith("NICHT BESTANDEN")


def test_missing_family_is_not_testable_and_counts_as_p_one():
    rows = [Row(r.time, r.week, r.section, r.y, r.mechanics, {**r.extra, "F": None}) for r in _rows(None, 3)]
    out = s21.evaluate(rows, boot_draws=99, shift_draws=3, version="1.0")
    assert out["urteile"]["F"] == "nicht testbar (Gate)" and out["familien"]["F"]["p"] is None


def test_count_is_results_blind():
    ev = [Event(i, START + i * 50 * HOUR, UP, 1.0, 0, 1.0, "training") for i in range(5)]
    out = s21.count(ev, {"entprellt": 2}, {"F": None, "G": {ev[0].time}})
    assert "flip" not in repr(out).lower()
    assert out["familien"]["K"]["ereignisse"]["training"] == 5
    assert out["familien"]["F"]["ereignisse"]["training"] == 0 and out["familien"]["G"]["ereignisse"]["training"] == 1


def test_evaluate_refuses_while_draft():
    with pytest.raises(PermissionError):
        s21.evaluate(_rows(None, 4))
