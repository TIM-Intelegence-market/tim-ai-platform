"""S28 1.0: family O from the metrics archive. No look-ahead, strict parsing, results-blind count."""
from __future__ import annotations

import math

import pytest

from src.research_lab.data.parse import Kline
from src.research_lab.studies import s28
from src.research_lab.studies.s20 import HOUR

T0 = 1_600_000_000_000 - 1_600_000_000_000 % HOUR  # a full hour
STEP = s28.STEP_MS


def bars(n=60, start=T0, price=100.0, slope=0.0):
    return [Kline(start + k * HOUR, price + slope * k, price + slope * k, price + slope * k, price + slope * k, 1.0,
                  start + (k + 1) * HOUR - 1, 0.5)
            for k in range(n)]


def snapshots(first, last, oi=lambda t: 100.0, top=2.0, taker=1.5):
    times = list(range(first, last + 1, STEP))
    return s28.Snapshots(times, [oi(t) for t in times], [top] * len(times), [taker] * len(times))


def test_parse_collapses_identical_repeats_and_rejects_conflicts():
    head = ",".join(s28.COLUMNS)
    row = "2022-06-01 00:00:00,BTCUSDT,100,1,1,1.2,1,1.5"
    assert len(s28.parse_snapshots("\n".join([head, row, row]))) == 1
    with pytest.raises(ValueError):
        s28.parse_snapshots("\n".join([head, row, row.replace("1.5", "1.6")]))
    with pytest.raises(ValueError):
        s28.parse_snapshots("\n".join([head, "2022-06-01 00:00:00,BTCUSDT,100"]))


def test_empty_fields_are_missing_not_guessed():
    head = ",".join(s28.COLUMNS)
    row = "2022-06-01 00:00:00,BTCUSDT,100,1,1,,1,1.5"
    parsed = s28.parse_snapshots("\n".join([head, row, row]))
    assert math.isnan(parsed[next(iter(parsed))][1])
    b = bars()
    snap = snapshots(T0 - 3 * 24 * HOUR, b[30].open_time + HOUR, top=float("nan"))
    assert s28.features(snap, b, 30, 1.0) is None


def test_features_sign_and_values():
    b = bars(slope=1.0)  # price rises
    snap = snapshots(T0 - 3 * 24 * HOUR, T0 + 60 * HOUR, oi=lambda t: 100.0 + (t - T0) / HOUR)
    long = s28.features(snap, b, 30, 1.0)
    short = s28.features(snap, b, 30, -1.0)
    assert long is not None and short is not None
    assert long[0] > 0 and long[0] == -short[0]
    assert math.isclose(long[1], math.log(2.0)) and math.isclose(long[2], math.log(1.5))
    assert short[1] == -long[1]


def test_no_look_ahead_snapshot_inside_lag_is_not_used():
    b = bars()
    close_time = b[30].open_time + HOUR
    snap = snapshots(T0 - 3 * 24 * HOUR, close_time, top=2.0)
    base = s28.features(snap, b, 30, 1.0)
    # a poisoned snapshot stamped inside the last 5 minutes before the close must not change anything
    k = len(snap.times) - 1
    assert close_time - snap.times[k] < s28.LAG_MS
    snap.top[k] = 99.0
    snap.oi[k] = 1e9
    snap.taker[k] = 99.0
    assert s28.features(snap, b, 30, 1.0) == base


def test_gap_in_snapshots_gives_none():
    b = bars()
    times = [t for t in range(T0 - 3 * 24 * HOUR, b[30].open_time + HOUR, STEP)
             if not (b[30].open_time - 2 * HOUR < t < b[30].open_time + HOUR)]
    snap = s28.Snapshots(times, [100.0] * len(times), [2.0] * len(times), [1.5] * len(times))
    assert s28.features(snap, b, 30, 1.0) is None


def test_count_is_results_blind_and_gates():
    class Row:  # the count reads time, section, direction and the family only
        def __init__(self, t, section, direction, ok):
            self.time, self.section, self.direction = t, section, direction
            self.features = {"O": (0.0, 0.0, 0.0) if ok else None}

    rows = [Row(T0 + k * HOUR, name, d, True) for name in ("training", "validierung") for k in range(4) for d in ("LONG", "SHORT")]
    out = s28.count(rows)
    assert out["training"]["abdeckung"] == 8 and out["gate"] is False  # far below 300 per direction
    assert "net_r" not in json_dump(out)


def json_dump(obj):
    import json
    return json.dumps(obj)


def test_family_set_patches_and_restores_s24():
    from src.research_lab.studies import s24

    before = (s24.FAMILIES, dict(s24.FEATURES), dict(s24.FAMILY_NAMES))
    with s28.family_set("A") as fams:
        assert fams == ("O",) and s24.FEATURES["O"] == s28.FEATURES
    with s28.family_set("B") as fams:
        assert fams == (*before[0], "O") and s24.FAMILY_NAMES["O"] == s28.FAMILY_NAME
    assert (s24.FAMILIES, s24.FEATURES, s24.FAMILY_NAMES) == before


def test_holm_runs_over_both_variants(monkeypatch):
    def fake(rows, fams, exits, **_):
        p = 0.001 if fams == ["O"] else 0.2
        crit = {"holm": False, "abstand": True}
        return {"modelle": {"M1": {"p": p, "kriterien": dict(crit)}, "M2": {"p": 0.5, "kriterien": dict(crit)}}}

    monkeypatch.setattr(s28.s27, "evaluate", fake)
    out = s28.evaluate([], ["C", "K", "F", "G", "T", "V"], {})
    assert out["holm"]["m"] == 4 and out["holm"]["verworfen"] == ["A:M1"]
    assert out["urteil_je_modell"]["A:M1"] == "BESTANDEN (Kandidat)"
    assert out["urteil_je_modell"]["B:M1"] == "NICHT BESTANDEN" and out["urteil"].startswith("BESTANDEN")


def test_evaluate_needs_footprint(tmp_path, monkeypatch):
    monkeypatch.setattr(s28.s22, "load", lambda *a, **k: ([], [], "x"))
    monkeypatch.setattr(s28, "load_snapshots", lambda *a, **k: s28.Snapshots([], [], [], []))
    with pytest.raises(SystemExit):
        s28.main(["evaluate", "--out", str(tmp_path)])
