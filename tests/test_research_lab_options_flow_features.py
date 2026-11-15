"""A3 options-flow features: arithmetic, sign convention and the point-in-time rule."""
from __future__ import annotations

import pytest

from src.research_lab.options_flow import features as f

T = 1_800_000_000_000
H = 3_600_000


def row(ts, recv=None, *, call=True, side="buy", prem=1000.0, block=False, liq=False, days=30):
    return {"ts_ms": ts, "recv_ms": ts if recv is None else recv, "is_call": call, "side": side,
            "premium_usd": prem, "block": block, "liquidation": liq, "expiry_ms": ts + days * f.DAY_MS}


def test_direction_convention():
    assert f.direction(row(T)) == 1                      # call bought
    assert f.direction(row(T, side="sell")) == -1        # call sold
    assert f.direction(row(T, call=False)) == -1         # put bought
    assert f.direction(row(T, call=False, side="sell")) == 1  # put sold


def test_flow_features_numbers():
    rows = [row(T - 10, prem=3000), row(T - 20, call=False, prem=1000, block=True),
            row(T - 30, side="sell", prem=500, days=2), row(T - 40, liq=True, prem=9999)]
    x = f.flow_features(rows, T, H, big_usd=2000)
    assert x["n"] == 3 and x["liquidations"] == 1
    assert x["premium_usd"] == 4500
    assert x["signed_premium_usd"] == 3000 - 1000 - 500
    assert x["put_call_premium"] == pytest.approx(1000 / 3500)
    assert x["big_n"] == 1 and x["big_signed"] == 1
    assert x["block_share"] == pytest.approx(1000 / 4500) and x["block_signed_usd"] == -1000
    assert x["short_share"] == pytest.approx(500 / 4500)


def test_no_lookahead_by_receive_time():
    late = row(T - 10, recv=T + 5)          # exchange time inside, but TIM saw it after t
    future = row(T + 10)                    # after t
    old = row(T - H - 1)                    # outside window
    x = f.flow_features([late, future, old, row(T - 1)], T, H, big_usd=10**9)
    assert x["n"] == 1


def test_empty_window_gives_none_ratios():
    x = f.flow_features([], T, H, big_usd=1)
    assert x["n"] == 0 and x["signed_share"] is None and x["put_call_premium"] is None


def test_bad_params():
    with pytest.raises(ValueError):
        f.flow_features([], T, H, big_usd=0)


def test_oi_features():
    prev = [{"instrument_name": "BTC-27MAR26-80000-C", "open_interest": 10},
            {"instrument_name": "BTC-27MAR26-70000-P", "open_interest": 5}]
    now = [{"instrument_name": "BTC-27MAR26-80000-C", "open_interest": 12},
           {"instrument_name": "BTC-27MAR26-70000-P", "open_interest": 8},
           {"instrument_name": "BTC-27MAR26-70000-P", "open_interest": None}]
    x = f.oi_features(prev, now)
    assert x["call_oi_change"] == 2 and x["put_oi_change"] == 3 and x["put_call_oi"] == pytest.approx(8 / 12)
    assert f.oi_features(None, now)["call_oi_change"] is None


def test_dvol_change_uses_only_past_candles():
    data = {"data": [[T - 2 * H, 0, 0, 0, 50.0], [T - H, 0, 0, 0, 55.0], [T, 0, 0, 0, 60.0], [T + H, 0, 0, 0, 99.0]]}
    assert f.dvol_change(data, T, H) == pytest.approx(60 / 55 - 1)
    assert f.dvol_change({"weird": 1}, T, H) is None
