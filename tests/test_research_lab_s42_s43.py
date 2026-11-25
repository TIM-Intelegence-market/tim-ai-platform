import gzip
from datetime import date
from itertools import pairwise

import pytest

from src.research_lab.protocol import MAKER_FEE
from src.research_lab.studies import s32, s42, s43
from src.research_lab.studies.s32 import Event, Outcome, Second
from src.research_lab.studies.s43 import MakerOutcome, TradeSec


def _sec(mid, bid=1.0, ask=1.0):
    return Second(mid=mid, bid_q=bid, ask_q=ask)


def _range_path(lo, hi, n):
    w = hi - lo
    pts = [lo, hi, lo, hi, lo + 0.05 * w]
    out, seg = [], n // 4
    for a, b in pairwise(pts):
        out += [a + (b - a) * k / seg for k in range(seg)]
    while len(out) < n:
        out.append(pts[-1])
    return out


CHAIN_1H = s42.CONFIG.chain(3600)


def test_chain_scales_with_window():
    assert (CHAIN_1H.window_s, CHAIN_1H.horizon_s, CHAIN_1H.cooldown_s) == (3600, 1200, 1200)
    assert CHAIN_1H.stop_bp == s32.CONFIG.stop_bp and CHAIN_1H.band_bp == s32.CONFIG.band_bp


def test_width_groups_and_sessions():
    assert s42.width_group(59.9) is None and s42.width_group(60) == "60-100"
    assert s42.width_group(399.9) == "250-400" and s42.width_group(400) is None
    e = Event("d", 14 * 3600, 1, 2.0, 1.0, 2.0, 120.0)
    assert s42.in_group(e, "100-150") and s42.in_group(e, "100-150|newyork") and not s42.in_group(e, "100-150|asien")
    assert len(s42.GROUPS) == 20


def test_find_events_on_one_hour_range():
    lo, hi = 100_000.0, 101_200.0  # about 120 bp
    path = _range_path(lo, hi, 3600)
    secs = [_sec(m, 0, 0) for m in path] + [_sec(path[-1], bid=3, ask=1)] * 3
    evs = s42.find_events(secs, "d", CHAIN_1H, check_s=1)
    assert evs and evs[-1].side == 1 and evs[-1].ratio == pytest.approx(3.0)
    assert s42.width_group(evs[-1].width_bp) == "100-150"


def test_defended_check_is_throttled():
    lo, hi = 100_000.0, 101_000.0
    path = _range_path(lo, hi, 3600)
    secs = [_sec(m, 0, 0) for m in path] + [_sec(path[-1], bid=3, ask=1)] * 3
    calls = []
    orig = s32.defended
    try:
        s32.defended = lambda *a, **k: calls.append(1) or orig(*a, **k)
        s42.find_events(secs, "d", CHAIN_1H, check_s=10)
    finally:
        s32.defended = orig
    assert len(calls) == 1  # the three tail seconds fall into one 10-second check slot


def test_count_is_results_blind():
    e = Event("d", 3600, 1, 2.5, 1.0, 2.0, 120.0)
    c = s42.count({date(2020, 6, 1): [e] * 31, date(2023, 6, 1): [e]})
    assert c["training"]["100-150"]["alle"] == 31 and c["training"]["100-150"]["pruefbar"]
    assert c["training"]["100-150"]["h2_pruefbare_stufen"] == ["2-3"]
    assert not c["validierung"]["100-150"]["pruefbar"]


def test_evaluate_locked_and_runs_when_frozen():
    with pytest.raises(PermissionError):
        s42.evaluate({}, version="0.1")
    win, loss = Outcome("target", 50.0, 20.0), Outcome("stop", -20.0, 20.0)
    res = {d: [(Event("d", 3600, 1, 3.0, 1, 2, 120.0), win)] * 20 + [(Event("d", 3600, 1, 0.3, 1, 2, 120.0), loss)] * 20
           for d in (date(2020, 6, 1), date(2020, 7, 1), date(2023, 6, 1), date(2023, 7, 1))}
    out = s42.evaluate(res, version="1.0", draws=200)
    assert out["ergebnis"]["100-150"]["h1_bestanden"]
    assert out["training"]["100-150"]["h2_je_verhaeltnis"]["3-5"]["netto_r"] > 0


# -- S43 -----------------------------------------------------------------------------------------------------


def _ev(side=1):
    return Event(day="d", i=0, side=side, ratio=2.0, lo=100.0, hi=110.0, width_bp=1000.0)


def _flat(mid, n):
    return [_sec(mid) for _ in range(n)]


CHAIN = s32.CONFIG  # entry delay 1 s, horizon 300 s, stop 5 bp


def test_maker_needs_trade_through_and_cancels():
    secs = _flat(101.0, 700)
    trades = [None] * 700
    trades[5] = TradeSec(100.9, 101.0)  # touches the limit (100.9, the bid of a one-tick spread), not through
    assert s43.maker_outcome(secs, trades, _ev(), CHAIN, 30).exit == "unfilled"
    trades[40] = TradeSec(100.8, 101.0)  # through, but after 30 s
    assert s43.maker_outcome(secs, trades, _ev(), CHAIN, 30).exit == "unfilled"
    o = s43.maker_outcome(secs, trades, _ev(), CHAIN, 60)
    assert o.exit == "time" and o.fill_s == 39


def test_maker_target_needs_trade_through_and_stop_comes_first():
    secs = _flat(101.0, 700)
    trades = [None] * 700
    trades[3] = TradeSec(100.8, 101.0)  # fill
    for j in range(4, 600):
        secs[j] = _sec(105.0)  # mid at the target, but no trade through it
    o = s43.maker_outcome(secs, trades, _ev(), CHAIN, 30)
    assert o.exit == "time"
    trades[10] = TradeSec(105.0, 105.1)
    o = s43.maker_outcome(secs, trades, _ev(), CHAIN, 30)
    assert o.exit == "target" and o.gross_bp == pytest.approx((105 - 100.9) / 100.9 * 10_000)
    secs[10] = _sec(99.9)  # stop in the same second wins
    assert s43.maker_outcome(secs, trades, _ev(), CHAIN, 30).exit == "stop"


def test_maker_short_mirrors():
    secs = _flat(109.0, 700)
    trades = [None] * 700
    trades[3] = TradeSec(109.0, 109.2)  # sell limit at 109.1, a trade at 109.2 goes through
    trades[8] = TradeSec(104.9, 105.0)
    o = s43.maker_outcome(secs, trades, _ev(-1), CHAIN, 30)
    assert o.exit == "target" and o.gross_bp > 0


def test_maker_costs():
    risk = 10.0
    assert s43.net_r(Outcome("target", 30.0, risk)) == pytest.approx((30 - 2 * MAKER_FEE * 1e4) / risk)
    assert s43.net_r(Outcome("stop", -10.0, risk)) == pytest.approx((-10 - (2 + 5 + 3 + 5)) / risk)
    assert s43.net_r(Outcome("time", 0.0, risk)) == pytest.approx(-(2 + 5 + 3) / risk)
    assert s43.net_r_stress(Outcome("time", 0.0, risk)) == pytest.approx(-(4 + 10 + 6) / risk)


def test_trade_seconds_from_csv(tmp_path):
    p = tmp_path / "t.csv.gz"
    base = 1_590_969_600_000_000  # 2020-06-01 UTC
    rows = ["exchange,symbol,timestamp,local_timestamp,id,side,price,amount",
            f"binance-futures,BTCUSDT,{base},{base + 10},1,buy,100.0,1",
            f"binance-futures,BTCUSDT,{base},{base + 500_000},2,sell,99.5,1",
            f"binance-futures,BTCUSDT,{base},{base + 2_000_000},3,buy,101.0,1"]
    with gzip.open(p, "wt") as fh:
        fh.write("\n".join(rows) + "\n")
    t = s43.trade_seconds_from_csv(p, date(2020, 6, 1))
    assert t[0] == TradeSec(99.5, 100.0) and t[1] is None and t[2] == TradeSec(101.0, 101.0)


def test_fill_report_compares_with_market_outcome():
    d = date(2020, 6, 1)
    e = _ev()
    res = {d: [(e, MakerOutcome("target", 10.0, 10.0, 3)), (e, MakerOutcome("unfilled", 0.0, 0.0))]}
    mkt = {d: [(e, Outcome("target", 30.0, 10.0)), (e, Outcome("stop", -10.0, 10.0))]}
    f = s43.fills(res, mkt, ("all",), lambda ev, g: True)
    assert f["training"]["all"]["fuellquote"] == 0.5
    assert f["training"]["all"]["markt_netto_r_gefuellt"] > f["training"]["all"]["markt_netto_r_nicht_gefuellt"]


def test_frozen_versions():
    assert s42.VERSION == "1.0" and s43.VERSION == "1.0"
    assert set(s43.WINDOWS) == {"15m", "1h", "2h", "4h"} and s43.CANCEL_S == (30, 60, 300)


def test_passive_price_on_grid():
    assert s43.passive_price(101.0, 1) == pytest.approx(100.9)
    assert s43.passive_price(101.05, 1) == pytest.approx(101.0)
    assert s43.passive_price(109.0, -1) == pytest.approx(109.1)
    assert s43.passive_price(105.03, -1, exact=True) == pytest.approx(105.1)
    assert s43.passive_price(105.03, 1, exact=True) == pytest.approx(105.0)


def test_missing_does_not_depend_on_cancel_time():
    n = 500  # room for 30 s or 60 s plus the 300 s horizon, not for 300 s plus horizon
    secs = _flat(101.0, n)
    trades = [None] * n
    trades[3] = TradeSec(100.8, 101.0)
    assert {s43.maker_outcome(secs, trades, _ev(), CHAIN, c).exit for c in s43.CANCEL_S} == {"missing"}


def test_h2_field_total():
    assert s42.H2_FIELDS_TOTAL == 20 * 2 * 7 + 3 * 20 * 2 * 7 + 4 * 3 * 20 * 2 * 7
