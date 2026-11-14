"""QM/OB/SFP detectors (src/analysis/patterns.py) and the paper shadow (src/dashboard/pattern_shadow.py)."""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from src.analysis import patterns as P
from src.dashboard import pattern_shadow as S

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def walk(n: int, minutes: int, seed: int = 3) -> list[dict]:
    rnd, price, out = random.Random(seed), 100000.0, []
    for i in range(n):
        start = T0 + timedelta(minutes=i * minutes)
        o = price
        c = o + math.sin(i / 37) * 40 + rnd.gauss(0, 120)
        out.append({"open_time": start.isoformat(), "close_time": (start + timedelta(minutes=minutes)).isoformat(), "open": o,
                    "high": max(o, c) + abs(rnd.gauss(0, 60)), "low": min(o, c) - abs(rnd.gauss(0, 60)), "close": c,
                    "volume": abs(rnd.gauss(100, 40)) + 1, "closed": True})
        price = c
    return out


def flat(n: int, price: float = 100.0, minutes: int = 15, volume: float = 100.0) -> list[dict]:
    out = []
    for i in range(n):
        start = T0 + timedelta(minutes=i * minutes)
        out.append({"open_time": start, "close_time": start + timedelta(minutes=minutes), "open": price, "high": price + 1, "low": price - 1,
                    "close": price, "volume": volume, "closed": True})
    return out


def candle(prev: list[dict], o: float, h: float, l: float, c: float, volume: float = 100.0, minutes: int = 15) -> dict:
    start = prev[-1]["close_time"]
    return {"open_time": start, "close_time": start + timedelta(minutes=minutes), "open": o, "high": h, "low": l, "close": c, "volume": volume, "closed": True}


def plan(**over) -> dict:
    base = {"id": "p1", "profile": "day", "htf": "1h", "exec": "15m", "kind": "OB", "direction": P.LONG, "setup_id": "s", "setup_created": T0.isoformat(),
            "htf_invalid_beyond": 90.0, "target": 110.0, "zone_low": 99.0, "zone_high": 101.0, "exec_created": T0.isoformat(), "rvol_origin": 2.0,
            "armed_at": (T0 + timedelta(minutes=15 * 30)).isoformat(), "status": "ARMED"}
    return {**base, **over}


def test_detectors_find_all_three_kinds_and_are_causal():
    htf = P.prep(walk(400, 60))
    found = P.htf_setups(htf, "1h")
    assert {s["kind"] for s in found} == {"OB", "QM", "SFP"}
    cut = 300
    prefix = {s["id"]: s for s in P.htf_setups(htf[:cut], "1h")}
    full = {s["id"]: s for s in found}
    for sid, s in prefix.items():  # nothing found on the prefix may change its zone when later candles arrive
        assert sid in full and (full[sid]["zone_low"], full[sid]["zone_high"], full[sid]["target"]) == (s["zone_low"], s["zone_high"], s["target"])
    assert all(s["created"] <= htf[cut - 1]["close_time"] for s in prefix.values())


def test_order_block_is_invalid_exactly_when_the_six_candles_before_it_are_a_tight_box():
    htf = P.prep(walk(400, 60))
    for ob in P.order_blocks(htf, "1h"):
        k = ob["ob_index"]
        box = max(c["high"] for c in htf[k - 6:k]) - min(c["low"] for c in htf[k - 6:k])
        assert ob["valid"] == (box >= P.COMPRESSION_ATR * P.atr_at(htf, k))
        assert ob["valid"] or ob["reason"] == "Kompression darunter"


def test_risk_multiplier_follows_the_model():
    assert P.risk_multiplier(1, "1h") == 0.7 and P.risk_multiplier(2, "1h") == 1.0 and P.risk_multiplier(3, "1h") == 1.0
    assert P.risk_multiplier(1, "4h") == 1.4 and P.risk_multiplier(2, "1d") == 2.0


def test_delta_share_reads_the_footprint_window_and_none_when_not_covered():
    t = int(T0.timestamp())
    trades = {"days": {"d": [[t, 100.0, 10.0, 30.0], [t + 300, 100.0, 20.0, 20.0], [t + 900, 100.0, 50.0, 0.0]]}}
    assert P.delta_share(trades, T0, T0 + timedelta(minutes=10)) == (30 + 20 - 10 - 20) / 80
    assert P.delta_share(trades, T0 - timedelta(hours=1), T0 - timedelta(minutes=5)) is None
    assert P.delta_share(None, T0, T0 + timedelta(minutes=5)) is None


def _long_touch(volume: float) -> list[dict]:
    ex = flat(30)
    ex.append(candle(ex, 103, 104, 100.5, 102.5, volume))  # touches 101 from above, closes above the zone
    return ex


def test_plan_enters_at_the_close_of_the_retest_with_a_confluence_and_hits_the_target():
    ex = _long_touch(volume=300.0)  # RVOL 3 at the retest
    p = plan(rvol_origin=None, armed_at=ex[29]["close_time"].isoformat())
    S.advance(p, ex, {"p1": p})
    assert p["status"] == "OPEN" and p["entry"] == 102.5 and p["risk_mult"] == 0.7 * 1.0  # 1h HTF counts as 1 confluence, no 4h doubling
    assert p["stop"] < p["zone_low"] and p["confluence"]["found"]["rvol_retest"]
    ex.append(candle(ex, 102.5, 111.0, 102.0, 110.5))
    S.advance(p, ex, {"p1": p})
    assert p["status"] == "CLOSED" and p["how"] == "ZIEL" and abs(p["net_r"] - (p["gross_r"] - p["cost_r"])) < 0.002 and p["gross_r"] > 1.5


def test_stop_wins_when_stop_and_target_are_in_one_candle():
    ex = _long_touch(300.0)
    p = plan(rvol_origin=None, armed_at=ex[29]["close_time"].isoformat())
    S.advance(p, ex, {"p1": p})
    ex.append(candle(ex, 102.5, 111.0, 90.0, 100.0))
    S.advance(p, ex, {"p1": p})
    assert p["status"] == "CLOSED" and p["how"] == "STOP" and p["net_r"] < -1.0 and p["weighted_r"] == round(p["net_r"] * p["risk_mult"], 3)


def test_no_confluence_means_no_entry():
    ex = _long_touch(volume=100.0)
    p = plan(rvol_origin=1.0, armed_at=ex[29]["close_time"].isoformat())
    S.advance(p, ex, {"p1": p})
    assert p["status"] == "SKIPPED" and p["reason"] == "keine Konfluenz"


def test_rr_cost_and_zone_break_are_skipped():
    ex = _long_touch(300.0)
    low_rr = plan(target=103.0, armed_at=ex[29]["close_time"].isoformat())
    S.advance(low_rr, ex, {"p1": low_rr})
    assert low_rr["reason"] == "R:R unter 1,5"
    broken = flat(30)
    broken.append(candle(broken, 100, 100.5, 95.0, 96.0, 300.0))
    p = plan(armed_at=broken[29]["close_time"].isoformat())
    S.advance(p, broken, {"p1": p})
    assert p["status"] == "SKIPPED" and p["reason"] == "gebrochen"


def test_day_limit_and_cooldown_after_a_loss():
    ex = _long_touch(300.0)
    armed = ex[29]["close_time"].isoformat()
    shots = {f"o{i}": {"entry_time": (T0 + timedelta(hours=i)).isoformat(), "weighted_r": 0.5, "closed_at": (T0 + timedelta(hours=i, minutes=30)).isoformat()}
             for i in range(2)}
    p = plan(armed_at=armed)
    S.advance(p, ex, {**shots, "p1": p})
    assert p["reason"] == "Tageslimit"
    loss = {"o": {"entry_time": (T0 - timedelta(days=2)).isoformat(), "weighted_r": -1.0, "closed_at": (T0 + timedelta(minutes=15 * 20)).isoformat()}}
    q = plan(armed_at=armed, setup_created=(T0 + timedelta(minutes=15 * 10)).isoformat())
    S.advance(q, ex, {**loss, "p1": q})
    assert q["reason"] == "Sperre nach Verlust/verpasst"


def test_update_is_prospective_idempotent_and_renders(tmp_path):
    series = {"1h": walk(400, 60), "15m": walk(1600, 15, seed=5), "4h": walk(200, 240, seed=7), "30m": walk(800, 30, seed=9),
              "1d": walk(120, 1440, seed=11), "1w": walk(60, 10080, seed=13)}
    path = tmp_path / "shadow.json"
    late = datetime(2027, 1, 1, tzinfo=timezone.utc)
    state = S.update(path, series, now=late)
    assert state["setups"] == {} and state["plans"] == {}  # everything in the series is older than started_at
    path.unlink()
    now = T0 + timedelta(days=400)
    first = S.update(path, series, now=T0)  # started before the data: all setups count
    assert first["setups"] and set(S.summary(first)["setups"]) <= {"OB", "QM", "SFP"}
    second = S.update(path, series, now=now)
    assert second["setups"] == first["setups"]
    for pid, done in first["plans"].items():
        if done["status"] in ("CLOSED", "SKIPPED"):
            assert second["plans"][pid] == done  # a finished plan never changes
    html = S.render_de(S.current(series), second)
    assert "Muster: QM, OB, SFP" in html and P.RULESET in html
    assert "keine Order" in S.render_de(None, None)
