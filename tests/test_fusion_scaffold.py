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


def test_deribit_history_rows():
    c = hi.HoldoutCounter()
    res = {"trades": [{"timestamp": VALIDATION_START_MS}, {"timestamp": HOLDOUT_START_MS}, {"timestamp": "x"}]}
    rows = list(hi.deribit_history_rows(res, c))
    assert len(rows) == 1 and c.dropped == 1 and rows[0]["recv_ms"] == VALIDATION_START_MS + hi.LATENCY_MS


# P4 walk-forward ----------------------------------------------------------------------------------------------------
def test_forward_label_enters_after_signal():
    opens = [100.0, 101.0, 102.0, 103.0]
    assert wf.forward_label(opens, 0, 2) == pytest.approx(math.log(103 / 101))
    assert wf.forward_label(opens, 1, 2) is None


def test_purged_splits_remove_overlapping_labels():
    times = [k * 10 for k in range(100)]
    ends = [t + 35 for t in times]  # each label spans 3.5 rows
    folds = wf.purged_splits(times, ends, folds=4, min_train=40, embargo_ms=10)
    assert len(folds) == 4 and folds[-1].test[-1] == 99
    for fold in folds:
        start = times[fold.test[0]]
        assert all(ends[j] < start - 10 for j in fold.train)
        assert max(fold.train) < fold.test[0] - 3
    with pytest.raises(ValueError):
        wf.purged_splits([2, 1], [3, 4], folds=1, min_train=1, embargo_ms=0)


def test_ridge_recovers_signal_and_ic():
    rnd = random.Random(1)
    x = [[rnd.gauss(0, 1), rnd.gauss(0, 1)] for _ in range(400)]
    y = [2 * a - 1 * b + rnd.gauss(0, 0.1) for a, b in x]
    m = wf.ridge_fit(x, y, lam=0.0)
    assert m.coef[0] / m.scale[0] == pytest.approx(2, abs=0.05) and m.coef[1] / m.scale[1] == pytest.approx(-1, abs=0.05)
    assert wf.spearman_ic(wf.predict(m, x), y) > 0.95
    assert wf.spearman_ic([1, 1, 1], [1, 2, 3]) is None


def _synthetic_rows(n=600, seed=3):
    rnd = random.Random(seed)
    rows = []
    for k in range(n):
        price, of, opt, gam = (rnd.gauss(0, 1) for _ in range(4))
        rows.append({"t_ms": VALIDATION_START_MS - (n - k) * 3_600_000, "mom": price, "ofi": of, "pcr": opt,
                     "gex": gam, "y": 0.6 * of + rnd.gauss(0, 1)})
    return rows


def test_compare_finds_planted_orderflow_effect_only():
    rows = _synthetic_rows()
    times = [r["t_ms"] for r in rows]
    folds = wf.purged_splits(times, [t + 3_600_000 for t in times], folds=4, min_train=200, embargo_ms=3_600_000)
    groups = {"price": ["mom"], "orderflow": ["ofi"], "optionsflow": ["pcr"], "gamma": ["gex"]}
    res = wf.compare(rows, groups, label="y", folds=folds)
    assert set(res) == set(wf.MODELS)
    assert res["A1_orderflow"]["ic"] > 0.3 and abs(res["A0_price"]["ic"]) < 0.15
    assert res["A1_orderflow"]["clark_west_t"] > 3
    assert res["A2_optionsflow"]["clark_west_t"] < 1.645  # nothing planted there


def test_compare_refuses_holdout_rows():
    rows = _synthetic_rows(50)
    rows[-1]["t_ms"] = HOLDOUT_START_MS
    with pytest.raises(ValueError):
        wf.compare(rows, {"price": ["mom"]}, label="y", folds=[])


def test_clark_west_needs_rows():
    assert wf.clark_west([1.0], [0.0], [1.0]) is None
