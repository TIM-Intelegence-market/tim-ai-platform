"""P0 data maturity, P4 holdout lock at load time and walk-forward scaffold (synthetic data only)."""
from __future__ import annotations

import json
import math
import random
import zipfile

import pytest

from src.research_lab.fusion import datenreife as dr
from src.research_lab.fusion import historisch as hi
from src.research_lab.fusion import walkforward as wf
from src.research_lab.fusion.of_features import Bar
from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS

MIN = 60_000
DAY = 86_400_000


# P0 ---------------------------------------------------------------------------------------------------------------
def test_report_counts_gaps_duplicates_and_delay():
    rows = [{"ts_ms": 1_000 + k * MIN, "trade_id": k, "recv_ms": 1_000 + k * MIN + 50} for k in range(10)]
    rows += [{"ts_ms": 1_000 + 30 * MIN, "trade_id": 99, "recv_ms": 1_000 + 30 * MIN + 50}]   # 21-min gap
    rows += [dict(rows[0]), {"ts_ms": "x"}]
    r = dr.report(rows)
    assert r["rows"] == 11 and r["duplicates"] == 1 and r["bad_rows"] == 1
    assert r["gaps"] == 1 and r["longest_gap_min"] == 21.0 and r["delay_median_ms"] == 50
    assert r["gate_g_a"] is False  # far below 60 days


def test_gate_g_a_passes_on_long_clean_stream():
    rows = ({"ts_ms": 1 + k * 5 * MIN, "trade_id": k} for k in range(61 * 288))
    assert dr.report(rows, recv_key=None)["gate_g_a"] is True


def test_oi_age_and_cli(tmp_path, capsys):
    assert dr.oi_age([{"ts_ms": 0, "recv_ms": 20 * MIN}, {"ts_ms": 0, "recv_ms": MIN}])["stale"] == 1
    p = tmp_path / "a.jsonl"
    p.write_text("\n".join(json.dumps({"ts_ms": 1 + k, "trade_id": k}) for k in range(3)) + "\nnot json\n")
    assert dr.main([str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["rows"] == 3 and out["bad_rows"] == 1 and out["files"] == 1


# P4 Weg H -----------------------------------------------------------------------------------------------------------
def test_guard_drops_holdout_and_adds_receive_time():
    c = hi.HoldoutCounter()
    rows = list(hi.guard([{"ts_ms": HOLDOUT_START_MS - 1}, {"ts_ms": HOLDOUT_START_MS}], c))
    assert len(rows) == 1 and c.dropped == 1 and rows[0]["recv_ms"] == HOLDOUT_START_MS - 1 + hi.LATENCY_MS
    assert hi.split(VALIDATION_START_MS - 1) == "train" and hi.split(VALIDATION_START_MS) == "validation"
    with pytest.raises(ValueError):
        hi.split(HOLDOUT_START_MS)


def _zip(tmp_path, name, text):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(name.replace(".zip", ".csv"), text)
    return p


def test_aggtrades_zip_reader(tmp_path):
    csv_text = ("agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
                f"1,100.5,2,1,1,{VALIDATION_START_MS},true\n2,100.6,1,2,2,{VALIDATION_START_MS + 1},False\n"
                f"3,100.7,1,3,3,{HOLDOUT_START_MS},false\n")
    c = hi.HoldoutCounter()
    rows = list(hi.read_aggtrades_zip(_zip(tmp_path, "BTCUSDT-aggTrades-2023-01-01.zip", csv_text), c))
    assert [r["side"] for r in rows] == [-1, 1] and c.dropped == 1
    rows2 = list(hi.read_aggtrades_zip(_zip(tmp_path, "BTCUSDT-aggTrades-2025-03-01.zip", csv_text), c))
    assert rows2 == [] and c.dropped == 2  # file skipped unopened
    micro = f"7,1,1,7,7,{VALIDATION_START_MS * 1000},true\n"
    assert next(hi.parse_aggtrades_csv(micro))["ts_ms"] == VALIDATION_START_MS


def test_seconds_timestamps_are_refused_not_let_through():
    secs = HOLDOUT_START_MS // 1000 + 86_400  # a 2025 time in seconds would look like 1970 in ms
    with pytest.raises(ValueError):
        list(hi.guard([{"ts_ms": secs}], hi.HoldoutCounter()))
    with pytest.raises(ValueError):
        hi.split(secs)
    with pytest.raises(ValueError):
        next(hi.parse_aggtrades_csv(f"1,1,1,1,1,{secs},true\n"))
    assert hi.to_ms(HOLDOUT_START_MS * 1_000_000) == HOLDOUT_START_MS  # nanoseconds


def test_deribit_history_rows():
    c = hi.HoldoutCounter()
    res = {"trades": [{"timestamp": VALIDATION_START_MS}, {"timestamp": HOLDOUT_START_MS}, {"timestamp": "x"}]}
    rows = list(hi.deribit_history_rows(res, c))
    assert len(rows) == 1 and c.dropped == 1 and rows[0]["recv_ms"] == VALIDATION_START_MS + hi.LATENCY_MS


# P4 walk-forward ----------------------------------------------------------------------------------------------------
def test_forward_label_enters_only_after_the_signal_is_known():
    bars = [Bar(k * MIN, 100.0 + k, 0, 0, 0, 0, 0, known_ms=(k + 1) * MIN) for k in range(6)]
    lab, end = wf.forward_label(bars, 0, 2)
    assert lab == pytest.approx(math.log(103 / 101)) and end == 3 * MIN
    late = [*bars[:1], *bars[1:]]
    late[0] = Bar(0, 100.0, 0, 0, 0, 0, 0, known_ms=MIN + 2_000)  # last trade arrived 2 s after the bar end
    lab2, _ = wf.forward_label(late, 0, 2)
    assert lab2 == pytest.approx(math.log(104 / 102))  # entry moves one bar later
    assert wf.forward_label(bars, 3, 2) is None


def test_purged_splits_remove_overlapping_labels():
    times = [VALIDATION_START_MS + k * 10 for k in range(100)]
    ends = [t + 35 for t in times]  # each label spans 3.5 rows
    folds = wf.purged_splits(times, ends, folds=4, min_train=40, embargo_ms=10)
    assert len(folds) == 4 and folds[-1].test[-1] == 99
    for fold in folds:
        start = times[fold.test[0]]
        assert all(ends[j] < start - 10 for j in fold.train)
        assert max(fold.train) < fold.test[0] - 3
    with pytest.raises(ValueError):
        wf.purged_splits([VALIDATION_START_MS + 2, VALIDATION_START_MS + 1], [VALIDATION_START_MS + 3] * 2,
                         folds=1, min_train=1, embargo_ms=0)
    t0 = HOLDOUT_START_MS - 10 * DAY
    with pytest.raises(ValueError):  # the last label ends inside the holdout
        wf.purged_splits([t0, t0 + DAY], [t0 + DAY, HOLDOUT_START_MS], folds=1, min_train=1, embargo_ms=0)


def test_ridge_recovers_signal_and_ic():
    rnd = random.Random(1)
    x = [[rnd.gauss(0, 1), rnd.gauss(0, 1)] for _ in range(400)]
    y = [2 * a - 1 * b + rnd.gauss(0, 0.1) for a, b in x]
    m = wf.ridge_fit(x, y, lam=0.0)
    assert m.coef[0] / m.scale[0] == pytest.approx(2, abs=0.05) and m.coef[1] / m.scale[1] == pytest.approx(-1, abs=0.05)
    assert wf.spearman_ic(wf.predict(m, x), y) > 0.95
    assert wf.spearman_ic([1, 1, 1], [1, 2, 3]) is None
    assert wf.spearman_ic([1, 2, 2, 3], [10, 20, 20, 30]) == pytest.approx(1.0)  # ties handled


def _synthetic_rows(n=600, seed=3):
    rnd = random.Random(seed)
    rows = []
    for k in range(n):
        price, of, opt, gam = (rnd.gauss(0, 1) for _ in range(4))
        t = VALIDATION_START_MS - (n - k) * 3_600_000
        rows.append({"t_ms": t, "label_end_ms": t + 3_600_000, "mom": price, "ofi": of, "pcr": opt,
                     "gex": gam, "y": 0.6 * of + rnd.gauss(0, 1)})
    return rows


def test_compare_finds_planted_orderflow_effect_only():
    rows = _synthetic_rows()
    times = [r["t_ms"] for r in rows]
    folds = wf.purged_splits(times, [t + 3_600_000 for t in times], folds=4, min_train=200, embargo_ms=3_600_000)
    groups = {"price": ["mom"], "orderflow": ["ofi"], "optionsflow": ["pcr"], "gamma": ["gex"]}
    res = wf.compare(rows, groups, label="y", folds=folds)
    assert set(res) == set(wf.MODELS) | {"_excluded"}
    assert len({res[m]["n"] for m in wf.MODELS}) == 1  # all models scored on the same rows
    assert res["A1_orderflow"]["ic"] > 0.3 and abs(res["A0_price"]["ic"]) < 0.15
    assert res["A1_orderflow"]["clark_west_t"] > 3
    assert res["A2_optionsflow"]["clark_west_t"] < 1.645  # nothing planted there


def test_compare_refuses_holdout_rows_and_labels():
    rows = _synthetic_rows(50)
    rows[-1]["t_ms"] = HOLDOUT_START_MS
    with pytest.raises(ValueError):
        wf.compare(rows, {"price": ["mom"]}, label="y", folds=[])
    rows = _synthetic_rows(50)
    rows[-1]["label_end_ms"] = HOLDOUT_START_MS
    with pytest.raises(ValueError):
        wf.compare(rows, {"price": ["mom"]}, label="y", folds=[])


def test_compare_drops_missing_features_for_all_models():
    rows = _synthetic_rows(300)
    rows[250]["ofi"] = None
    rows[260]["pcr"] = float("nan")
    times = [r["t_ms"] for r in rows]
    folds = wf.purged_splits(times, [r["label_end_ms"] for r in rows], folds=2, min_train=150, embargo_ms=3_600_000)
    groups = {"price": ["mom"], "orderflow": ["ofi"], "optionsflow": ["pcr"], "gamma": ["gex"]}
    res = wf.compare(rows, groups, label="y", folds=folds)
    assert res["_excluded"] == {"rows": 2, "of": 300}
    assert res["A0_price"]["n"] == res["A6_all"]["n"] == 148


def test_clark_west_numbers():
    assert wf.clark_west([1.0], [0.0], [1.0]) is None
    y, small, big = [1.0, -1.0, 2.0, 0.5], [0.0, 0.0, 0.0, 0.0], [0.9, -0.8, 1.7, 0.6]
    f = [(a - s) ** 2 - ((a - b) ** 2 - (s - b) ** 2) for a, s, b in zip(y, small, big, strict=True)]
    import statistics as st
    assert wf.clark_west(y, small, big) == pytest.approx(st.fmean(f) / (st.stdev(f) / math.sqrt(4)))
    assert wf.clark_west(y, small, big) > 1.645
