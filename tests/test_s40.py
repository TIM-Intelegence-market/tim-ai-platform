"""S40 study code: fast features equal the building blocks, no look-ahead, holdout never enters, statistics right."""
from __future__ import annotations

import math
import random
import statistics
from datetime import datetime, timezone

import pytest

from src.research_lab.fusion import of_features as off
from src.research_lab.fusion.of_features import Bar
from src.research_lab.options_flow import contract
from src.research_lab.options_flow import features_q as fq
from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS
from src.research_lab.studies import s40

T0 = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def synth_bars(n: int, seed: int = 1, start: int = T0) -> list[Bar]:
    rng = random.Random(seed)
    p, out = 30000.0, []
    for k in range(n):
        o = p
        p *= math.exp(rng.gauss(0, 0.002))
        hi, lo = max(o, p) * (1 + abs(rng.gauss(0, 0.001))), min(o, p) * (1 - abs(rng.gauss(0, 0.001)))
        t = start + k * s40.BAR_MS
        out.append(Bar(t, o, hi, lo, p, rng.uniform(1, 10), rng.uniform(1, 10), t + s40.BAR_MS + rng.choice([0, 1500])))
    return out


def test_fast_cvd_divergence_equals_building_block():
    bars = synth_bars(2000)
    fast = s40.FastOF(bars)
    for i in range(0, 2000, 3):
        assert fast.cvd_divergence(i) == off.cvd_divergence(bars, i, **s40.CVD)


def _raw_trade(tid, ts, direction="buy", block=None, iv=55.0, inst="BTC-26MAR21-40000-C"):
    return {"trade_id": tid, "timestamp": ts, "instrument_name": inst, "direction": direction, "price": 0.05,
            "amount": 2.0, "index_price": 30000.0, "iv": iv, "block_trade_id": block, "recv_ms": ts + 2000}


def test_option_window_equals_greek_flow_without_blocks():
    t = T0 + 10 * s40.H_MS
    raws = [_raw_trade("1", t - 30 * 60_000), _raw_trade("2", t - 50 * 60_000, "sell"),
            _raw_trade("3", t - 10 * 60_000, block="B1"), _raw_trade("4", t - 1000),  # 4 not received yet
            _raw_trade("5", t - 2 * s40.H_MS), _raw_trade("6", t - 5 * 60_000, iv=None)]
    flow = s40.build_option_flow(s40.option_contributions(raws), set())
    norm = [contract.normalize_trade({k: v for k, v in r.items() if k != "recv_ms"}, r["recv_ms"]) for r in raws]
    ref = fq.greek_flow([r for r in norm if not r["group_id"]], t, s40.H_MS)
    d, g = flow.window(t, s40.H_MS)
    assert d == pytest.approx(ref["daf_usd"]) and g == pytest.approx(ref["gaf_usd_per_pct"])
    assert ref["used"] == 2


def test_features_do_not_look_ahead():
    bars = synth_bars(800, seed=3)
    t = T0 + 40 * s40.H_MS
    opens = [b.open_ms for b in bars]
    a = s40.raw_features(bars, opens, t, s40.FastOF(bars), None)
    future = [b if b.open_ms + s40.BAR_MS <= t - 10_000 else Bar(b.open_ms, b.open * 2, b.high * 3, b.low, b.close * 2,
                                                                     b.buy * 9, b.sell, b.known_ms) for b in bars]
    b2 = s40.raw_features(future, opens, t, s40.FastOF(future), None)
    assert a == b2 and a["cvd_div"] in (-1.0, 0.0, 1.0) and a["ai_1h"] is not None
    _, entry, _ = s40.label(bars, opens, t, 1)
    assert entry >= t


def test_known_ms_after_t_excludes_the_bar():
    bars = synth_bars(400)
    t = bars[300].open_ms + s40.BAR_MS  # bar 300 ends at t but its last trade arrives 1.5 s later
    late = [*bars[:300], Bar(*[getattr(bars[300], f) for f in ("open_ms", "open", "high", "low", "close", "buy", "sell")],
                             t + 1500), *bars[301:]]
    late[300] = Bar(late[300].open_ms, late[300].open, late[300].high, late[300].low, 1.0, 1e9, 0.0, t + 1500)
    opens = [b.open_ms for b in late]
    f = s40.raw_features(late, opens, t, s40.FastOF(late), None)
    assert f["ai_1h"] < 0.9  # the huge buy volume of the not-yet-known bar is not used


def test_zscore_uses_only_previous_hours():
    times = [T0 + k * s40.H_MS for k in range(600)]
    vals = [float(k % 7) for k in range(600)]
    z = s40.zscore_series(times, vals)
    assert all(v is None for v in z[: s40.Z_MIN])
    hist = vals[0:599]  # 720-hour window reaches back to the first value
    assert z[599] == pytest.approx((vals[599] - statistics.fmean(hist)) / statistics.pstdev(hist))
    vals2 = [*vals[:599], 1e6]
    assert s40.zscore_series(times, vals2)[598] == z[598]


def test_clark_west_hac_by_hand():
    rng = random.Random(5)
    y = [rng.gauss(0, 1) for _ in range(300)]
    small = [0.0] * 300
    big = [0.3 * v + rng.gauss(0, 1) * 0.1 for v in y]
    t, p = s40.clark_west_hac(y, small, big)
    f = s40.cw_terms(y, small, big)
    n, mu, lag = len(f), statistics.fmean(f), s40.newey_west_lag(300)
    d = [x - mu for x in f]
    var = sum(x * x for x in d) / n + sum(2 * (1 - k / (lag + 1)) * sum(d[i] * d[i - k] for i in range(k, n)) / n
                                          for k in range(1, lag + 1))
    assert lag == 5 and t == pytest.approx(mu / math.sqrt(var / n)) and 0 <= p < 0.01


def test_holm_and_year_rule():
    adj = s40.holm_p({"a": 0.001, "b": 0.02, "c": None}, m=12)
    assert adj["a"] == pytest.approx(0.012) and adj["b"] == pytest.approx(0.22) and adj["c"] == 1.0
    y20, y21, y22 = (int(datetime(y, 6, 1, tzinfo=timezone.utc).timestamp() * 1000) for y in (2020, 2021, 2022))
    times, f = [y20] * 600 + [y21] * 600 + [y22] * 600, [1.0] * 600 + [1.0] * 600 + [-0.2] * 600
    assert s40.year_rule(times, f, 500)["ok"]  # 2 of 3 years positive, each about 56 % of the total
    assert s40.year_rule(times, [1.0] * 600 + [-0.1] * 600 + [-0.1] * 600, 500)["ok"] is False
    assert not s40.year_rule(times, [5.0] * 600 + [0.1] * 600 + [-0.1] * 600, 500)["ok"]  # one year > 60 %


def test_rows_respect_months_holdout_and_validation_purge():
    start = HOLDOUT_START_MS - 40 * 86_400_000
    bars = synth_bars(40 * 288 + 50, seed=7, start=start)[: 40 * 288]
    months = {datetime.fromtimestamp(b.open_ms / 1000, tz=timezone.utc).strftime("%Y-%m") for b in bars}
    rows = s40.build_rows(bars, None, months - {"2024-12"}, start + 21 * 86_400_000, HOLDOUT_START_MS)
    assert rows["1h"] == []  # every remaining row touches December 2024, marked invalid
    rows = s40.build_rows(bars, None, months, start + 21 * 86_400_000, HOLDOUT_START_MS + 10 * 86_400_000)
    assert rows["1h"] and all(r["label_end_ms"] < HOLDOUT_START_MS for r in rows["1h"] + rows["4h"])
    assert all(datetime.fromtimestamp(r["t_ms"] / 1000, tz=timezone.utc).hour % 4 == 0 for r in rows["4h"])
    with pytest.raises(ValueError):
        s40.evaluate_train([{"t_ms": VALIDATION_START_MS, "label_end_ms": VALIDATION_START_MS + 1, "y": 0.0,
                             **{k: 0.0 for k in s40.keys_of("A1")}}], "A0", "A1", "1h")


def test_trade_returns_costs_and_funding():
    rows = [{"y": math.log(1.01), "entry_ms": 0, "label_end_ms": 10}, {"y": 0.0, "entry_ms": 0, "label_end_ms": 10}]
    funding = [(5, 0.0001), (20, 0.5)]
    base = s40.trade_returns(rows, [0.01, 0.0001], funding, s40.BASE_ROUND_TRIP, credits=True)
    assert len(base) == 1 and base[0][1] == pytest.approx(0.01 - 0.0018 - 0.0001)
    short = s40.trade_returns(rows[:1], [-0.01], [(5, 0.0001)], s40.STRESS_ROUND_TRIP, credits=False)
    assert short[0][1] == pytest.approx(-0.01 - 0.0036)  # no funding credit under stress


def test_evaluate_train_finds_planted_orderflow_effect():
    rng = random.Random(11)
    rows = []
    for k in range(9000):
        t = T0 - 365 * 86_400_000 + k * s40.H_MS
        r = {key: rng.gauss(0, 1) for key in s40.keys_of("A1")}
        r.update(t_ms=t, entry_ms=t, label_end_ms=t + s40.H_MS, y=0.3 * r["ai_1h"] + rng.gauss(0, 1))
        rows.append(r)
    res = s40.evaluate_train(rows, "A0", "A1", "1h")
    assert res["n_oos"] > 4000 and res["cw_p"] < 1e-6 and res["ic_big"] > res["ic_small"]
    null = s40.evaluate_train([{**r, "y": rng.gauss(0, 1)} for r in rows], "A0", "A1", "1h")
    assert null["cw_p"] > 0.01


def _hours(ms: int) -> int:
    return ms // s40.H_MS


def test_training_rows_end_before_validation_start():
    start = VALIDATION_START_MS - 30 * 86_400_000
    bars = synth_bars(32 * 288, seed=9, start=start)
    months = {s40._month(b.open_ms) for b in bars}
    rows = s40.build_rows(bars, None, months, start + 21 * 86_400_000, VALIDATION_START_MS)
    assert rows["1h"] and all(r["label_end_ms"] < VALIDATION_START_MS for r in rows["1h"] + rows["4h"])
    assert rows["_dropped"]["1h"]["past_end"] >= 1


def test_invalid_month_values_stay_out_of_z_windows():
    start = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    bars = synth_bars(75 * 288, seed=4, start=start)
    months = {"2021-02", "2021-03"}
    changed = [Bar(b.open_ms, b.open, b.high, b.low, b.close, b.buy * 50, b.sell, b.known_ms)
               if s40._month(b.open_ms) == "2021-01" else b for b in bars]
    a = s40.build_rows(bars, None, months, start, start + 75 * 86_400_000)["1h"]
    b = s40.build_rows(changed, None, months, start, start + 75 * 86_400_000)["1h"]
    assert a and [r["ai_1h"] for r in a] == [r["ai_1h"] for r in b]


def test_entry_needs_the_bar_right_after_t():
    bars = synth_bars(200)
    t = bars[100].open_ms
    gap = bars[:100] + bars[102:]
    assert s40.label(gap, [x.open_ms for x in gap], t, 1) is None
    assert s40.label(bars, [x.open_ms for x in bars], t, 1)[1] == t


def test_option_features_do_not_look_ahead():
    bars = synth_bars(600, seed=2)
    t = T0 + 30 * s40.H_MS
    days = {s40._day(t - 86_400_000), s40._day(t - 1)}
    early = [(t - 3_600_000 + 5_000, 1.0, 2.0), (t - 2_000, 3.0, 4.0)]
    flow_a = s40.build_option_flow(early, days)
    flow_b = s40.build_option_flow([*early, (t - 1_999, 100.0, 100.0), (t + 60_000, 9.0, 9.0)], days)
    opens = [b.open_ms for b in bars]
    fa = s40.raw_features(bars, opens, t, s40.FastOF(bars), flow_a)
    fb = s40.raw_features(bars, opens, t, s40.FastOF(bars), flow_b)
    assert fa == fb and fa["daf_1h"] == 4.0 and fa["gaf_24h"] == 6.0
    assert "daf_1h" not in s40.raw_features(bars, opens, t, s40.FastOF(bars), s40.build_option_flow(early, set()))


def test_validation_fit_respects_the_boundary_and_hashes():
    rng = random.Random(3)
    rows = []
    for k in range(20_000):
        t = VALIDATION_START_MS - 8_000 * s40.H_MS + k * s40.H_MS
        if t + s40.H_MS >= HOLDOUT_START_MS:
            break
        r = {key: rng.gauss(0, 1) for key in s40.keys_of("A1")}
        r.update(t_ms=t, entry_ms=t, label_end_ms=t + s40.H_MS, y=0.2 * r["ai_1h"] + rng.gauss(0, 1))
        rows.append(r)
    v1 = s40.evaluate_validation(rows, "A0", "A1", "1h")
    v2 = s40.evaluate_validation(rows, "A0", "A1", "1h")
    assert v1["coef_sha256"] == v2["coef_sha256"] and v1["cw_p"] < 1e-6
    assert all(r["t_ms"] >= VALIDATION_START_MS for r in v1["rows"])
    shifted = [{**r, "y": 50.0} if VALIDATION_START_MS - 25 * s40.H_MS <= r["label_end_ms"] < VALIDATION_START_MS
               else r for r in rows]  # rows inside the embargo must not change the fit
    assert s40.evaluate_validation(shifted, "A0", "A1", "1h")["coef_sha256"] == v1["coef_sha256"]


def test_trading_check_and_iso_week_bootstrap():
    rng = random.Random(8)
    rows, preds = [], []
    for k in range(600):
        t = VALIDATION_START_MS + k * 4 * s40.H_MS
        rows.append({"y": rng.gauss(0.004, 0.01), "entry_ms": t, "label_end_ms": t + 4 * s40.H_MS})
        preds.append(0.01)
    res = s40.trading_check(rows, preds, [])
    assert res["n"] == 600 and res["mean"] > res["mean_protocol_stress"] > res["mean_stress"]
    assert res["boot_lower_90"] is not None and res["dsr"] is not None
    assert s40.week_bootstrap_lower([(VALIDATION_START_MS, 1.0)]) is None


def test_runs_are_locked(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "datenreife.json").write_text("{}")
    (tmp_path / "o").mkdir()
    (tmp_path / "o" / "s40_train.json").write_text("{}")
    with pytest.raises(SystemExit):
        s40.main(["--phase", "train", "--daten", str(tmp_path / "d"), "--aus", str(tmp_path / "o")])
    with pytest.raises(SystemExit):
        s40.main(["--phase", "validate", "--daten", str(tmp_path / "d"), "--aus", str(tmp_path / "o")])
    assert not s40._before_holdout("2025-01-01.jsonl.gz") and s40._before_holdout("BTCUSDT-fundingRate-2024-12.zip")


def test_clark_west_hac_fixed_value():
    y = [0.5, -0.2, 0.1, 0.4, -0.3, 0.2, 0.0, -0.1, 0.3, 0.6]
    big = [0.2, -0.1, 0.0, 0.3, -0.1, 0.1, 0.1, 0.0, 0.2, 0.3]
    t, _ = s40.clark_west_hac(y, [0.0] * 10, big)
    assert s40.newey_west_lag(10) == 2 and t == pytest.approx(3.1278009342726083, rel=1e-9)  # computed once by hand-script
