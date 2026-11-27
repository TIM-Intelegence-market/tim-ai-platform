from datetime import date
from itertools import pairwise

import pytest

from src.research_lab.data.parse import Kline
from src.research_lab.studies import s32, s44
from src.research_lab.studies.s44 import Bar, Breakout, Range


def _flat(price, n=1440):
    return [Bar(price, price, price, price) for _ in range(n)]


def _range_bars(lo, hi):
    """15 closes that touch both edges and leave them again, then sit in the middle."""
    w = hi - lo
    closes = [lo, lo + 0.5 * w, hi, hi - 0.5 * w, lo, lo + 0.5 * w, hi, lo + 0.5 * w] + [lo + 0.5 * w] * 7
    return [Bar(c, c, c, c) for c in closes]


def test_days_exclude_tardis_days_and_holdout():
    days = s44.study_days()
    assert date(2020, 6, 1) not in days and date(2020, 6, 2) in days
    assert not set(days) & set(s32.study_days())
    assert days[-1] == date(2024, 12, 31) and len(days) == 1675 - 55


def test_day_bars_places_minutes():
    start = 1_590_969_600_000  # 2020-06-01 UTC
    k = Kline(start + 61 * 60_000, 1.0, 2.0, 0.5, 1.5, 1.0, start + 62 * 60_000 - 1, 0.5)
    bars = s44.day_bars([k], date(2020, 6, 1))
    assert bars[61] == Bar(1.0, 2.0, 0.5, 1.5) and bars[60] is None and len(bars) == 1440


def test_find_ranges_and_cooldown():
    lo, hi = 100_000.0, 100_400.0  # 40 bp
    bars = _flat(lo + 200)[:100] + _range_bars(lo, hi) + _flat(lo + 200)[:200]
    bars = bars + _range_bars(lo, hi) + _flat(lo + 200)[: 1440 - len(bars) - 15]
    rs = s44.find_ranges(bars, "d")
    wide = [r for r in rs if s44.group_of(r) == "20-60"]
    assert [r.i for r in wide] == [104, 319] and wide[0].width_bp == pytest.approx(40.0)
    for grp in {s44.group_of(r) for r in rs}:
        starts = [r.i for r in rs if s44.group_of(r) == grp]
        assert all(b - a >= 60 for a, b in pairwise(starts))


def test_breakout_up_down_unclear_and_none():
    r = Range("d", 10, 100.0, 110.0, 1000.0)
    bars = _flat(105.0, 200)
    assert s44.find_breakout(bars, r).kind == "bleibt"
    bars[20] = Bar(105, 112.5, 105, 112)
    bo = s44.find_breakout(bars, r)
    assert (bo.kind, bo.side, bo.j) == ("oben", 1, 20)
    bars[15] = Bar(105, 105, 97.5, 98)
    assert s44.find_breakout(bars, r).kind == "unten"
    bars[12] = Bar(105, 113, 97, 105)
    assert s44.find_breakout(bars, r).kind == "unklar"
    assert s44.find_breakout(_flat(105.0, 50), r).kind == "missing"


def test_follow_target_stop_first_and_time():
    r = Range("d", 10, 100.0, 110.0, 1000.0)
    bars = _flat(113.0, 200)
    bo = Breakout(r, 20, 1, "oben")
    o = s44.follow(bars, bo, 1)
    assert o.exit == "time" and o.gross_bp == pytest.approx(0.0)
    assert o.risk_bp == pytest.approx((113 - 105) / 113 * 10_000)
    bars[30] = Bar(113, 123.5, 113, 120)
    o = s44.follow(bars, bo, 1)
    assert o.exit == "target" and o.gross_bp == pytest.approx(10 / 113 * 10_000)
    assert s44.follow(bars, bo, 2).exit == "time"
    bars[30] = Bar(113, 124, 104, 110)  # stop and target in one candle: stop wins
    assert s44.follow(bars, bo, 1).exit == "stop"


def test_follow_short_mirrors_and_no_room():
    r = Range("d", 10, 100.0, 110.0, 1000.0)
    bars = _flat(97.0, 200)
    bars[40] = Bar(97, 97, 86, 87)
    o = s44.follow(bars, Breakout(r, 20, -1, "unten"), 1)
    assert o.exit == "target" and o.gross_bp > 0
    bars[21] = Bar(106, 106, 106, 106)  # opens above the middle: no room for a short
    assert s44.follow(bars, Breakout(r, 20, -1, "unten"), 1).exit == "no_room"
    assert s44.follow(bars, Breakout(r, 20, 0, "unklar"), 1).exit == "unklar"


def test_count_is_results_blind_and_evaluate_locked():
    r = Range("d", 600, 100.0, 100.4, 40.0)
    bos = {date(2020, 6, 2): [Breakout(r, 610, 1, "oben")] * 30 + [Breakout(r, -1, 0, "bleibt")]}
    c = s44.count(bos)
    assert c["training"]["20-60"] == {"ranges": 31, "ausbrueche": 30, "unklar": 0, "pruefbar": True}
    assert "netto_r" not in str(c)
    with pytest.raises(PermissionError):
        s44.evaluate({})
    assert s44.VERSION.startswith("0.")


def test_evaluate_runs_when_frozen():
    from src.research_lab.studies.s32 import Outcome
    r = Range("d", 600, 100.0, 100.4, 40.0)
    win = (Breakout(r, 610, 1, "oben"), Outcome("target", 100.0, 20.0))
    res = {k: {d: [win] * 20 for d in (date(2020, 6, 2), date(2020, 6, 3), date(2023, 6, 2), date(2023, 6, 3))}
           for k in s44.TARGETS_K}
    out = s44.evaluate(res, version="1.0", draws=200)
    assert out["ziel_1x"]["ergebnis"]["20-60"] and out["ziel_1x"]["training"]["20-60"]["trades"] == 40
