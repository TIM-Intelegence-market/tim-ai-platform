"""S23 feature table: only what was known at the close, signed per direction, results-blind."""
from __future__ import annotations

import gzip
import json
import math
from datetime import datetime, timezone

from src.research_lab.data.parse import Kline
from src.research_lab.studies import s22, s23
from src.research_lab.studies.s20 import HOUR, UP

START = int(datetime(2022, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
HALF = s22.HALF


def _price(hours: float) -> float:
    return 40000.0 + 4.0 * hours + 900.0 * math.sin(hours / 30.0) + 250.0 * math.sin(hours / 5.0)


def _series(hours: int, start: int = START) -> tuple[list[Kline], list[Kline]]:
    half = []
    for j in range(hours * 2):
        o, c = _price(j / 2), _price((j + 1) / 2)
        buy = 3.0 if c > o else 2.0
        half.append(Kline(start + j * HALF, o, max(o, c) + 15, min(o, c) - 15, c, 5.0, start + (j + 1) * HALF - 1, buy))
    full = []
    for i in range(hours):
        a, b = half[2 * i], half[2 * i + 1]
        full.append(Kline(a.open_time, a.open, max(a.high, b.high), min(a.low, b.low), b.close, 10.0, b.close_time,
                          a.taker_buy_volume + b.taker_buy_volume))
    return full, half


def test_rows_cover_both_directions_and_are_mirrored():
    bars, half = _series(s22.WINDOW_1H + 120)
    rows = s23.build_rows(bars, half)
    assert rows and {r.direction for r in rows} == set(s22.DIRECTIONS)
    by_time: dict[int, dict[str, s23.Row]] = {}
    for r in rows:
        by_time.setdefault(r.time, {})[r.direction] = r
    for pair in by_time.values():
        long, short = pair["LONG"], pair["SHORT"]
        for fam in ("V", "T"):
            assert long.features[fam] == tuple(-x for x in short.features[fam])
        assert long.features["K"][0] == -short.features["K"][0]  # CVD share is signed
        assert long.features["K"][1:] == short.features["K"][1:]  # co-movement and volume trend are not
        assert long.features["F"] is None and long.features["G"] is None  # not loaded


def test_features_use_only_candles_closed_by_then():
    hours = s22.WINDOW_1H + 120
    bars, half = _series(hours)
    rows = s23.build_rows(bars, half)
    cut = rows[len(rows) // 2].time
    later_1h = [b if b.open_time + HOUR <= cut else Kline(b.open_time, 1.0, 2.0, 0.5, 1.5, 99.0, b.close_time, 90.0) for b in bars]
    later_30m = [b if b.open_time + HALF <= cut else Kline(b.open_time, 1.0, 2.0, 0.5, 1.5, 99.0, b.close_time, 90.0) for b in half]
    # the S22 moment filter looks 48 h ahead at candle times only; times stay, so the moments stay
    again = s23.build_rows(later_1h, later_30m)
    before = {(r.time, r.direction): r.features for r in rows if r.time <= cut}
    after = {(r.time, r.direction): r.features for r in again if r.time <= cut}
    assert before == after


def test_vwap_and_week_anchor():
    bars = [Kline(START + i * HOUR, 100.0, 101.0, 99.0, 100.0 + i, 1.0, START + (i + 1) * HOUR - 1, 0.5) for i in range(30)]
    v = s23.Vwap(bars)
    assert v.between(0, 0) == (101 + 99 + 100) / 3
    feats = v.features(bars, 29, 1.0, 2.0)
    assert feats is not None and feats[0] > 0  # rising closes sit above their 24h VWAP
    assert v.features(bars, 29, -1.0, 2.0) == (-feats[0], -feats[1])
    monday = int(datetime(2022, 3, 7, tzinfo=timezone.utc).timestamp() * 1000)
    assert s23.week_start(monday + 5 * HOUR) == monday and s23.week_start(monday - 1) == monday - 7 * 24 * HOUR


def test_trend_uses_only_completed_days():
    bars = [Kline(START + i * HOUR, 100.0, 101.0, 99.0, 100.0 + i, 1.0, START + (i + 1) * HOUR - 1, 0.5) for i in range(24 * 30)]
    day = datetime.fromtimestamp((START + 24 * 25 * HOUR) / 1000, tz=timezone.utc).date()
    states = s23.trend_states(bars, [day])
    assert states[day][0] == 1  # steady rise: day close above the mean of the last 20
    assert s23.trend_states(bars[:24 * 25], [day]) == states  # the day itself is never read


def test_funding_and_footprint_keys_map_to_directions():
    events = [s23.SimpleNamespace(time=10, direction=UP), s23.SimpleNamespace(time=10, direction="down")]
    keyed = s23._keyed({(10, UP): (1.0,), (10, "down"): (-1.0,)}, events)
    assert keyed == {(10, "LONG"): (1.0,), (10, "SHORT"): (-1.0,)}


def test_count_and_export_are_results_blind(tmp_path):
    bars, half = _series(s22.WINDOW_1H + 100)
    rows = s23.build_rows(bars, half)
    loaded = ["C", "K", "T", "V"]
    counted = s23.count(rows, loaded)
    assert counted["training"]["zeilen"] == len(rows) and counted["training"]["abdeckung"]["F"] == "nicht geladen"
    assert counted["gate"] is False
    path = tmp_path / "t.jsonl.gz"
    assert s23.export(rows, path) == len(rows)
    with gzip.open(path, "rt") as fh:
        first = json.loads(fh.readline())
    assert "net_r" not in first and "ergebnis" not in first
    assert set(first) >= {"zeit", "richtung", "r1_value", "cvd_anteil", "trend_m", "vwap_woche_atr", "fp_I", "funding_z"}


def test_workers_match_single_process():
    import multiprocessing

    bars, half = _series(s22.WINDOW_1H + 60)
    single = s23.build_rows(bars, half)
    before = multiprocessing.get_start_method()
    multiprocessing.set_start_method("forkserver", force=True)
    try:
        assert s23.build_rows(bars, half, workers=2) == single
    finally:
        multiprocessing.set_start_method(before, force=True)


def test_no_holdout_and_no_live_only_family_in_the_table():
    assert s22.LAST_MONTH == (2024, 12)
    names = {n for f in s23.FAMILIES for n in s23.FEATURES[f]}
    assert not any("liquid" in n or "orderbuch" in n or "gamma" in n for n in names)
    assert set(s23.SHADOW_ONLY) and all(isinstance(v, str) for v in s23.SHADOW_ONLY.values())
