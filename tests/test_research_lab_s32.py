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


def test_defended_needs_both_edges_and_three_touches():
    lo, hi = 100.0, 110.0
    assert s32.defended([100, 108, 101, 109, 100.5], lo, hi)
    assert not s32.defended([100, 104, 101, 104, 100.5], lo, hi)  # upper edge never touched
    assert not s32.defended([100, 110, 105], lo, hi)  # only two touches


def test_book_side():
    assert s32.book_side(_sec(1, bid=4, ask=2)) == 1
    assert s32.book_side(_sec(1, bid=1, ask=2)) == -1
    assert s32.book_side(_sec(1, bid=3, ask=2)) == 0
    assert s32.book_side(_sec(1, bid=0, ask=0)) == 0


def test_find_events_chain_and_control():
    path = _range_path()
    secs = [_sec(m) for m in path]
    # last 3 seconds: bid side twice the ask side -> ask thin -> long chain
    secs += [_sec(path[-1], bid=3, ask=1) for _ in range(3)]
    evs = s32.find_events(secs, "2020-06-01")
    chain = [e for e in evs if e.chain]
    assert chain and chain[-1].side == 1 and chain[-1].i == len(secs) - 1
    assert chain[-1].lo == pytest.approx(100_000.0) and chain[-1].hi == pytest.approx(100_300.0)
    # without the book condition only control events
    plain = s32.find_events([_sec(m) for m in path] + [_sec(path[-1])] * 3, "2020-06-01")
    assert plain and not any(e.chain for e in plain)


def test_imbalance_must_hold_three_seconds():
    path = _range_path()
    secs = [_sec(m) for m in path] + [_sec(path[-1], bid=3, ask=1)] * 2
    assert not any(e.chain for e in s32.find_events(secs, "d"))


def test_range_width_limits():
    narrow = [_sec(m) for m in _range_path(100_000.0, 100_100.0)]  # 10 bp
    wide = [_sec(m) for m in _range_path(100_000.0, 101_000.0)]  # 100 bp
    assert s32.find_events(narrow, "d") == [] and s32.find_events(wide, "d") == []


def test_cooldown_per_group():
    path = _range_path()
    secs = [_sec(m) for m in path] + [_sec(path[-1], bid=3, ask=1)] * 60
    chain = [e for e in s32.find_events(secs, "d") if e.chain]
    assert len(chain) == 1


def test_window_needs_valid_book():
    path = _range_path()
    secs = [_sec(m) if k % 10 else None for k, m in enumerate(path)]  # 10 % missing
    secs += [_sec(path[-1], bid=3, ask=1)] * 3
    assert s32.find_events(secs, "d") == []


def _ev(side=1):
    return Event(day="d", i=0, side=side, chain=True, lo=100.0, hi=110.0)


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
        s32.evaluate({}, version="0.2")
    assert s32.VERSION.startswith("0.")


def test_count_is_results_blind():
    evs = {date(2020, 6, 1): [_ev(), Event("d", 5, -1, False, 1.0, 2.0)]}
    c = s32.count(evs)
    assert c["training"]["kette_long"] == 1 and c["training"]["kontrolle_short"] == 1
    assert c["training"]["pruefbar"] is False
    assert "ziel" not in str(c)


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
