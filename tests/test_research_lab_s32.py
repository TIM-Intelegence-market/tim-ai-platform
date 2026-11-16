import gzip
from datetime import date
from itertools import pairwise

import pytest

from src.research_lab.studies import s32
from src.research_lab.studies.s32 import Config, Event, Outcome, Second

CFG = Config()


def _sec(mid, bid=1.0, ask=1.0):
    return Second(mid=mid, bid_q=bid, ask_q=ask)


def _range_path(lo=100_000.0, hi=100_300.0, n=900):
    """Mid path between lo and hi (30 bp): touches both edges several times, ends near the low edge."""
    w = hi - lo
    pts = [lo, hi, lo, hi, lo + 0.05 * w]
    out = []
    seg = n // (len(pts) - 1)
    for a, b in pairwise(pts):
        out += [a + (b - a) * k / seg for k in range(seg)]
    while len(out) < n:
        out.append(pts[-1])
    return out


def _empty(path):
    """Mid path with an empty band book: no event can fire before the tail."""
    return [_sec(m, bid=0, ask=0) for m in path]


def test_defended_needs_both_edges_and_three_touches():
    lo, hi = 100.0, 110.0
    assert s32.defended([100, 108, 101, 109, 100.5], lo, hi)
    assert not s32.defended([100, 104, 101, 104, 100.5], lo, hi)  # upper edge never touched
    assert not s32.defended([100, 110, 105], lo, hi)  # only two touches


def test_side_ratio():
    assert s32.side_ratio(_sec(1, bid=4, ask=2), 1) == pytest.approx(2.0)
    assert s32.side_ratio(_sec(1, bid=4, ask=2), -1) == pytest.approx(0.5)
    assert s32.side_ratio(_sec(1, bid=3, ask=0), 1) == s32.RATIO_CAP
    assert s32.side_ratio(_sec(1, bid=0, ask=0), 1) is None


def test_find_events_records_every_ratio():
    path = _range_path()
    for bid, ask in ((3, 1), (1, 1), (1, 4)):
        secs = _empty(path) + [_sec(path[-1], bid=bid, ask=ask) for _ in range(3)]
        evs = s32.find_events(secs, "2020-06-01")
        assert evs and evs[-1].side == 1 and evs[-1].i == len(secs) - 1
        assert evs[-1].ratio == pytest.approx(bid / ask)  # no threshold: weak and inverted books count too
        assert evs[-1].lo == pytest.approx(100_000.0) and evs[-1].hi == pytest.approx(100_300.0)


def test_ratio_is_lowest_of_last_three_seconds():
    path = _range_path()
    tail = [_sec(path[-1], bid=b, ask=1) for b in (5, 2, 4)]
    assert s32.find_events(_empty(path) + tail, "d")[-1].ratio == pytest.approx(2.0)


def test_bin_label():
    assert s32.bin_label(0.3) == "0-0.5" and s32.bin_label(2.0) == "2-3" and s32.bin_label(7) == ">=5"
    assert s32.bin_label(s32.RATIO_CAP) == ">=5"


def test_range_width_groups():
    def last_event(lo, hi):
        evs = s32.find_events(_empty(_range_path(lo, hi)) + [_sec(lo + 0.05 * (hi - lo), bid=3, ask=1)] * 3, "d")
        return evs[-1] if evs else None

    assert last_event(100_000.0, 100_050.0) is None  # 5 bp: too narrow for every group
    assert last_event(100_000.0, 102_000.0) is None  # 200 bp: too wide for every group
    for hi, group in ((100_150.0, "10-20"), (100_300.0, "20-60"), (100_800.0, "60-100"), (101_200.0, "100-150")):
        e = last_event(100_000.0, hi)
        assert e is not None and s32.width_group(e.width_bp) == group
    assert s32.width_group(20.0) == s32.width_group(60.0) == "20-60"


def test_cooldown():
    path = _range_path()
    secs = [_sec(m) for m in path] + [_sec(path[-1], bid=3, ask=1)] * 60
    assert len(s32.find_events(secs, "d")) == 1


def test_window_needs_valid_book():
    path = _range_path()
    secs = [_sec(m) if k % 10 else None for k, m in enumerate(path)]  # 10 % missing
    secs += [_sec(path[-1], bid=3, ask=1)] * 3
    assert s32.find_events(secs, "d") == []


def _ev(side=1, ratio=2.5, width=40.0):
    return Event(day="d", i=0, side=side, ratio=ratio, lo=100.0, hi=110.0, width_bp=width)


def test_outcome_target_stop_time():
    up = [_sec(101.0), _sec(101.0)] + [_sec(101.0 + k * 0.5) for k in range(1, 20)]
    o = s32.outcome(up, _ev())
    assert o.exit == "target" and o.gross_bp == pytest.approx((105 - 101) / 101 * 1e4)
    down = [_sec(101.0), _sec(101.0)] + [_sec(101.0 - k * 0.5) for k in range(1, 20)]
    o = s32.outcome(down, _ev())
    assert o.exit == "stop" and o.gross_bp == pytest.approx((100 * (1 - 5e-4) - 101) / 101 * 1e4)
    flat = [_sec(101.0)] * (CFG.horizon_s + 5)
    assert s32.outcome(flat, _ev()).exit == "time"
    assert s32.outcome([_sec(101.0)] * 10, _ev()).exit == "missing"  # day ends inside the horizon
    assert s32.outcome([_sec(106.0)] * 400, _ev()).exit == "no_room"


def test_outcome_short_mirrors():
    down = [_sec(109.0), _sec(109.0)] + [_sec(109.0 - k * 0.5) for k in range(1, 20)]
    assert s32.outcome(down, _ev(-1)).exit == "target"


def test_net_r_uses_protocol_costs():
    o = Outcome("stop", -20.0, 20.0)
    # 2 x 5 bp fee + 3 bp slippage + 5 bp stop slippage = 18 bp
    assert s32.net_r(o) == pytest.approx((-20 - 18) / 20)
    assert s32.net_r(Outcome("target", 20.0, 20.0)) == pytest.approx((20 - 13) / 20)


def test_study_days_and_sections():
    days = s32.study_days()
    assert days[0] == date(2020, 6, 1) and days[-1] == date(2024, 12, 1) and len(days) == 55
    assert sum(s32.section(d) == "training" for d in days) == 31


def test_holdout_and_non_free_days_refused(tmp_path):
    with pytest.raises(ValueError):
        s32.seconds_from_book_csv(tmp_path / "x.csv.gz", date(2025, 1, 1))
    with pytest.raises(ValueError):
        s32.seconds_from_book_csv(tmp_path / "x.csv.gz", date(2021, 3, 2))


def test_evaluate_locked_while_draft():
    with pytest.raises(PermissionError):
        s32.evaluate({}, version="0.8")
    assert s32.VERSION.startswith("0.")


def test_count_is_results_blind():
    evs = {date(2020, 6, 1): [_ev(), Event("d", 5, -1, 0.7, 1.0, 2.0, 80.0)]}
    c = s32.count(evs)
    assert c["training"]["20-60"]["2-3_long"] == 1 and c["training"]["60-100"]["0.5-1_short"] == 1
    assert c["training"]["20-60"]["alle"] == 1 and c["training"]["60-100"]["alle"] == 1
    assert c["training"]["10-20"]["alle"] == 0 and c["training"]["20-60"]["h2_pruefbare_stufen"] == []
    assert c["training"]["20-60"]["pruefbar"] is False
    assert "ziel" not in str(c)


def test_slope_rises_with_ratio():
    hit, miss = Outcome("target", 10.0, 10.0), Outcome("stop", -10.0, 10.0)
    rows = [(0.5, miss), (0.5, miss), (1.0, miss), (1.0, hit), (3.0, hit), (3.0, hit)]
    assert s32.slope(rows) > 0
    assert s32.slope([(r, hit) for r, _ in rows]) == pytest.approx(0.0)
    assert s32.slope([(2.0, hit)] * 5) is None  # no spread in the ratio


def test_evaluate_runs_once_frozen():
    hit, miss = Outcome("target", 30.0, 10.0), Outcome("stop", -10.0, 10.0)
    res = {}
    for d in (date(2020, 6, 1), date(2020, 7, 1), date(2023, 6, 1), date(2023, 7, 1)):
        res[d] = [(_ev(ratio=r), o) for r, o in ((0.5, miss), (1.0, miss), (3.0, hit), (4.0, hit))]
    out = s32.evaluate(res, version="1.0", draws=200)
    g = out["training"]["20-60"]
    assert g["h1_steigung"] > 0 and g["pruefbar"] is False and g["h1_untere_grenze"] is None
    assert out["ergebnis"]["20-60"]["h1_bestanden"] is False  # too few events: never passes
    assert set(g["je_verhaeltnis"]) == {"0.5-1", "1-1.5", "3-5"}
    assert set(out["ergebnis"]) == set(s32.GROUPS) and len(s32.GROUPS) == 20


def test_evaluate_keeps_width_groups_apart():
    hit, miss = Outcome("target", 30.0, 10.0), Outcome("stop", -10.0, 10.0)
    res = {date(2020, 6, 1): [(_ev(ratio=0.5), miss), (_ev(ratio=3.0), hit), (_ev(ratio=3.0, width=120.0), miss)]}
    out = s32.evaluate(res, version="1.0", draws=50)
    assert out["training"]["20-60"]["alle"] == 2 and out["training"]["100-150"]["alle"] == 1
    assert out["training"]["10-20"]["alle"] == 0


def test_seconds_from_book_csv(tmp_path):
    s = 1_590_969_600_000_000  # 2020-06-01 00:00 UTC in µs
    head = "exchange,symbol,timestamp,local_timestamp,is_snapshot,side,price,amount\n"
    rows = [(s, "true", "bid", "9500.00", "2"), (s, "true", "ask", "9500.10", "1"),
            (s + 1_500_000, "false", "bid", "9499.00", "4"),  # second 1
            (s + 3_200_000, "false", "ask", "9500.10", "0"),  # second 3: ask side empty -> unusable
            (s + 3_300_000, "false", "ask", "9500.20", "3")]
    with gzip.open(tmp_path / "b.csv.gz", "wt") as fh:
        fh.write(head + "".join(f"binance-futures,BTCUSDT,{t},{t},{sn},{sd},{p},{q}\n" for t, sn, sd, p, q in rows))
    secs = s32.seconds_from_book_csv(tmp_path / "b.csv.gz", date(2020, 6, 1))
    assert len(secs) == 86_400
    assert secs[0] is None  # still inside the snapshot block at the end of second 0
    assert secs[1].mid == pytest.approx(9500.05) and secs[1].bid_q == pytest.approx(6) and secs[1].ask_q == 1
    assert secs[2] == secs[1]  # no row in second 2: carried forward
    assert secs[3].mid == pytest.approx(9500.10) and secs[3].ask_q == pytest.approx(3)
    assert secs[4] is None  # nothing after the last row's second


def test_h2_checks_every_ratio_bin():
    win, loss = Outcome("target", 40.0, 10.0), Outcome("stop", -10.0, 10.0)
    res = {}
    for k in range(4):
        for d in (date(2020, 6 + k, 1), date(2023, 6 + k, 1)):
            # 1-1.5 always wins after costs, 0.5-1 always loses; 40 events per bin and day
            res[d] = [(_ev(ratio=1.2), win) for _ in range(40)] + [(_ev(ratio=0.7), loss) for _ in range(40)]
    out = s32.evaluate(res, version="1.0", draws=200)
    t = out["training"]["20-60"]["h2_je_verhaeltnis"]
    assert t["1-1.5"]["pruefbar"] and t["1-1.5"]["untere_grenze"] > 0 and t["0.5-1"]["untere_grenze"] < 0
    assert out["ergebnis"]["20-60"]["h2_bestandene_stufen"] == ["1-1.5"]
    assert out["ergebnis"]["20-60"]["h2_bestanden"] is True and out["ergebnis"]["10-20"]["h2_bestanden"] is False
    assert s32.ALPHA_H1 + s32.H2_BINS * s32.ALPHA_H2 == pytest.approx(s32.ALPHA)  # per width group


def test_sessions():
    assert s32.session_of(0) == "asien" and s32.session_of(7 * 3600) == "london"
    assert s32.session_of(13 * 3600 + 1799) == "london" and s32.session_of(13 * 3600 + 1800) == "newyork"
    assert s32.session_of(86_399) == "spaet"
    e = Event("d", 15 * 3600, 1, 2.0, 1.0, 2.0, 40.0)
    assert s32.in_group(e, "20-60") and s32.in_group(e, "20-60|newyork") and not s32.in_group(e, "20-60|london")
    c = s32.count({date(2020, 6, 1): [e]})
    assert c["training"]["20-60|newyork"]["alle"] == 1 and c["training"]["20-60|asien"]["alle"] == 0
