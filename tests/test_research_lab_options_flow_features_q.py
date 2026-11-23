"""P2 options-flow features Q2, Q4-Q10: signs, structures, point-in-time rule, past-only percentiles."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.options_gamma.greeks import bs_delta
from src.research_lab.options_flow import contract
from src.research_lab.options_flow import features_q as q

T = 1_800_000_000_000
H = 3_600_000
DAY = 86_400_000


def row(ts=T - 1000, *, call=True, side="buy", amount=1.0, iv=50.0, strike=70000.0, days=30, recv=None, gid=None,
        inst="BTC-X-70000-C"):
    return {"ts_ms": ts, "recv_ms": ts if recv is None else recv, "is_call": call, "side": side, "amount": amount,
            "iv": iv, "strike": strike, "index_price": 67000.0, "expiry_ms": ts + days * DAY,
            "premium_usd": 100.0 * amount, "group_id": gid, "instrument": inst, "liquidation": False}


def test_greek_flow_signs():
    x = q.greek_flow([row()], T, H)
    assert x["daf_usd"] > 0 and x["gaf_usd_per_pct"] > 0           # taker bought a call
    y = q.greek_flow([row(call=False)], T, H)
    assert y["daf_usd"] < 0 and y["gaf_usd_per_pct"] > 0           # taker bought a put: short delta, long gamma
    z = q.greek_flow([row(side="sell")], T, H)
    assert z["daf_usd"] == pytest.approx(-x["daf_usd"]) and z["gaf_usd_per_pct"] < 0
    d = bs_delta(67000.0, 70000.0, 30 * DAY / q.YEAR_MS, 0.5, True)
    assert x["daf_usd"] == pytest.approx(d * 67000.0)


def test_greek_flow_point_in_time_and_missing_iv():
    rows = [row(recv=T + 1), row(iv=None), row()]
    x = q.greek_flow(rows, T, H)
    assert x["used"] == 1 and x["skipped_no_iv"] == 1


def test_structures_net_out_legs():
    legs = [row(gid="b1", side="buy"), row(gid="b1", side="sell", strike=75000.0), row()]
    s = q.structures(legs, T, H)
    assert len(s) == 1 and s[0]["legs"] == 2 and s[0]["complete"]
    single = q.greek_flow([legs[0]], T, H)["daf_usd"]
    assert 0 < s[0]["net_delta_usd"] < single  # call spread: less delta than the bought leg alone


def test_contract_keeps_group_id():
    raw = {"trade_id": "1", "timestamp": T, "direction": "buy", "instrument_name": "BTC-27DEC26-70000-C",
           "price": 0.05, "amount": 1.0, "index_price": 67000.0, "iv": 50.0, "block_trade_id": "BLK1"}
    assert contract.normalize_trade(raw, T)["group_id"] == "BLK1"
    raw.pop("block_trade_id")
    assert contract.normalize_trade(raw, T)["group_id"] is None


def test_volume_to_oi():
    trades = [row(amount=5, inst="A"), row(amount=5, inst="A"), row(amount=1, inst="B")]
    summary = [{"instrument_name": "A", "open_interest": 100.0, "recv_ms": T},
               {"instrument_name": "C", "open_interest": 50.0, "recv_ms": T},
               {"instrument_name": "B", "open_interest": 1.0, "recv_ms": T + 1}]  # arrived later: not used
    x = q.volume_to_oi(trades, summary, T)
    assert x["per_instrument"] == {"A": 0.1} and x["without_oi"] == ["B"]
    assert x["total"] == pytest.approx(11 / 150)


def test_vol_helpers():
    assert q.realized_vol([100.0, 101.0], 365) is None
    rv = q.realized_vol([100.0, 101.0, 100.0, 101.0], 365)
    assert rv and rv > 0
    assert q.variance_premium(0.6, 0.5) == pytest.approx(0.11)
    flat = [(7 / 365, 0.5), (30 / 365, 0.5), (60 / 365, 0.5)]
    assert q.term_structure(flat) == pytest.approx(0.0)
    inverted = [(3 / 365, 0.8), (30 / 365, 0.5)]
    assert q.term_structure(inverted) > 0
    assert q.term_structure([(30 / 365, 0.5)]) is None  # no extrapolation
    smile = [(-0.5, 0.50), (-0.25, 0.56), (0.25, 0.52), (0.5, 0.50)]
    assert q.risk_reversal(smile) == pytest.approx(-0.04)


def test_next_expiry_is_0800_utc():
    t = int(datetime(2026, 11, 23, 7, 59, tzinfo=timezone.utc).timestamp() * 1000)
    assert q.next_expiry(t) == datetime(2026, 11, 23, 8, tzinfo=timezone.utc)
    t2 = int(datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert q.next_expiry(t2) == datetime(2026, 11, 24, 8, tzinfo=timezone.utc)


def test_expiry_percentile_uses_only_the_past():
    t = int(datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc).timestamp() * 1000)
    e = int(datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
    summary = [{"expiry_ms": e, "strike": 67000.0, "open_interest": 50.0, "recv_ms": t},
               {"expiry_ms": e + 30 * DAY, "strike": 80000.0, "open_interest": 150.0, "recv_ms": t},
               {"expiry_ms": t - DAY, "strike": 67000.0, "open_interest": 0.0001, "recv_ms": t}]  # expired
    past = [(t - 3 * DAY, 10.0), (t - 2 * DAY, 100.0), (t + DAY, 1.0)]  # last one lies in the future
    x = q.expiry_features(summary, 67000.0, t, past_atm_oi=past)
    assert x["hours_to_expiry"] == 2 and x["share_oi_24h"] == pytest.approx(50 / 200.0001) and x["atm_oi_next"] == 50.0
    assert x["past_n"] == 2 and x["atm_oi_percentile"] == 0.5
    with pytest.raises(ValueError):
        q.expiry_features([{"expiry_ms": e, "strike": 1.0, "open_interest": 1.0}], 67000.0, t)
