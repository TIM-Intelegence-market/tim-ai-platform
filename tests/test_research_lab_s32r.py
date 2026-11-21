from datetime import date
from itertools import pairwise

import pytest

from src.research_lab.studies import s32, s32r
from src.research_lab.studies.s32 import Second
from src.research_lab.studies.s32r import Range, Result


def _sec(mid, bid=1.0, ask=1.0):
    return Second(mid=mid, bid_q=bid, ask_q=ask)


def _range_path(lo=100_000.0, hi=100_300.0, n=900):
    w = hi - lo
    pts = [lo, hi, lo, hi, lo + 0.5 * w]
    out = []
    seg = n // (len(pts) - 1)
    for a, b in pairwise(pts):
        out += [a + (b - a) * k / seg for k in range(seg)]
    while len(out) < n:
        out.append(pts[-1])
    return out


def test_book_ratio_takes_value_closest_to_one():
    assert s32r.book_ratio([_sec(1, 4, 1), _sec(1, 2, 1), _sec(1, 3, 1)]) == pytest.approx(2.0)
    assert s32r.book_ratio([_sec(1, 1, 4), _sec(1, 1, 2)]) == pytest.approx(0.5)
    assert s32r.book_ratio([_sec(1, 1, 0)]) is None


def test_range_counted_once_per_hour_and_group():
    path = _range_path()
    secs = [_sec(m, 0, 0) for m in path] + [_sec(path[-1], 3, 1)] * 2000
    rs = s32r.find_ranges(secs, "d")
    main = [r for r in rs if s32r.group_of(r) == "20-60"]
    assert len(main) == 1 and main[0].ratio == pytest.approx(3.0)  # once per hour in its width group
    assert all(s32r.group_of(r) != "20-60" for r in rs[1:])  # a narrower range later is a new range
    assert main[0].lo == pytest.approx(100_000.0) and main[0].hi == pytest.approx(100_300.0)


def _r(ratio=2.0, i=0):
    return Range(day="d", i=i, lo=100.0, hi=110.0, width_bp=40.0, ratio=ratio)


def test_outcome_breakouts_and_stay():
    up = [_sec(105.0)] * 10 + [_sec(113.0)] * 7300  # 113 > 110 + 2.5
    o = s32r.outcome(up, _r())
    assert o.exit == "oben" and o.holds is True
    down = [_sec(105.0)] * 10 + [_sec(97.0)] * 10 + [_sec(105.0)] * 7300  # back inside later
    o = s32r.outcome(down, _r())
    assert o.exit == "unten" and o.holds is False
    near = [_sec(105.0)] * 10 + [_sec(112.0)] * 4000  # 112 < 112.5: not a breakout
    assert s32r.outcome(near, _r()).exit == "bleibt"
    assert s32r.outcome([_sec(105.0)] * 100, _r()).exit == "missing"


def test_a1_a2_directions():
    o_up, o_dn, o_stay = Result("oben", None), Result("unten", None), Result("bleibt", None)
    rows = [(_r(3.0), o_up), (_r(3.0), o_up), (_r(1 / 3), o_dn), (_r(1 / 3), o_dn), (_r(1.0), o_stay)]
    assert s32r.a1(rows) > 0  # breakouts go to the thin side
    assert s32r.a2(rows) > 0  # lopsided books break out, balanced one stays
    flipped = [(_r(3.0), o_dn), (_r(1 / 3), o_up), (_r(3.0), o_dn)]
    assert s32r.a1(flipped) < 0


def test_count_is_results_blind_and_groups():
    rs = {date(2020, 6, 1): [_r(2.0, i=15 * 3600), _r(0.5, i=3 * 3600)]}
    c = s32r.count(rs)
    assert c["training"]["20-60"]["ranges"] == 2 and c["training"]["20-60"]["oben_duenner"] == 1
    assert c["training"]["20-60|newyork"]["ranges"] == 1 and c["training"]["20-60"]["mit_urteil"] is False
    assert "oben\"" not in str(c) and "bleibt" not in str(c)


def test_evaluate_locked_and_runs_when_frozen():
    with pytest.raises(PermissionError):
        s32r.evaluate({}, version="0.1")
    assert s32r.VERSION.startswith("0.")
    o_up, o_dn = Result("oben", True), Result("unten", False)
    res = {d: [(_r(3.0), o_up)] * 20 + [(_r(1 / 3), o_dn)] * 20
           for d in (date(2020, 6, 1), date(2020, 7, 1), date(2023, 6, 1), date(2023, 7, 1))}
    out = s32r.evaluate(res, version="1.0", draws=100)
    assert out["training"]["20-60"]["grundverhalten"] == {"oben": 40, "unten": 40, "bleibt": 0}
    assert out["training"]["20-60"]["ausbruch_haelt_60min"] == pytest.approx(0.5)
    assert out["ergebnis"]["20-60"]["a1_bestanden"] is True
    assert set(out["ergebnis"]) == set(s32.GROUPS)


def test_digest_includes_s32_rules():
    assert s32r.CONFIG.digest() != s32.CONFIG.digest() and len(s32r.CONFIG.digest()) == 64
