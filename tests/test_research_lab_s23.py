"""S23 feature table: only what was known at the close, signed per direction, results-blind."""
from __future__ import annotations

import gzip
import json
import math
import random
from datetime import datetime, timezone

import pytest

from src.research_lab.data.parse import Kline
from src.research_lab.protocol import VALIDATION_START_MS
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


# -- package 2: outcome, models, evaluation -------------------------------------------------------------


def _flat(n: int, price: float = 100.0) -> list[Kline]:
    return [Kline(START + i * HOUR, price, price + 0.5, price - 0.5, price, 1.0, START + (i + 1) * HOUR - 1, 0.5) for i in range(n)]


def _set(bars: list[Kline], k: int, *, high: float | None = None, low: float | None = None) -> None:
    b = bars[k]
    bars[k] = Kline(b.open_time, b.open, b.high if high is None else high, b.low if low is None else low, b.close,
                    b.volume, b.close_time, b.taker_buy_volume)


def test_outcome_costs_stop_slippage_and_funding():
    from src.research_lab.bitunix.contract import FEE_TAKER
    from src.research_lab.bitunix.leverage import SLIPPAGE, STOP_SLIPPAGE

    no_rates = ([], [])
    bars = _flat(60)
    _set(bars, 3, high=103.0)  # target (2 ATR = 2.0 at atr 1.0) hit in the third candle after the entry
    net = s23.outcome(bars, 0, "LONG", 1.0, no_rates)
    assert net == pytest.approx(2.0 - (100 * (FEE_TAKER + SLIPPAGE) + 102 * (FEE_TAKER + SLIPPAGE)) / 1.0)
    bars = _flat(60)
    _set(bars, 2, low=98.5)  # stop
    net = s23.outcome(bars, 0, "LONG", 1.0, no_rates)
    assert net == pytest.approx(-1.0 - (100 * (FEE_TAKER + SLIPPAGE) + 99 * (FEE_TAKER + SLIPPAGE + STOP_SLIPPAGE)))
    # funding inside the holding time: long pays a positive rate, short receives it; after the exit it does not count
    bars = _flat(60)
    rates = ([START + 5 * HOUR, START + 55 * HOUR], [0.001, 0.5])
    flat_long = s23.outcome(bars, 0, "LONG", 1.0, no_rates)
    assert s23.outcome(bars, 0, "LONG", 1.0, rates) == pytest.approx(flat_long - 0.1)
    assert s23.outcome(bars, 0, "SHORT", 1.0, rates) == pytest.approx(s23.outcome(bars, 0, "SHORT", 1.0, no_rates) + 0.1)
    assert s23.outcome(bars, 20, "LONG", 1.0, no_rates) is None  # 48 candles not there


def _row(t: int, section: str, feats: dict, net_r: float, direction: str = "LONG") -> s23.Row:
    return s23.Row(t, section, direction, feats, net_r)


def _feats(c: float = 0.0, k: float = 0.0, g: float = 0.0) -> dict:
    return {"C": (c,) * 5, "K": (k, 0.7, -0.3), "F": (0.0,) * 6, "G": (g, g), "T": (0.0,) * 3, "V": (0.0, 0.0)}


def test_m1_votes_signs_and_thresholds():
    from src.dashboard.chart_verdict import NEUTRAL, SKIP, TAKE

    assert s23.m1_score(_row(0, "training", _feats(c=1.0), 0.0)) == 5
    assert s23.m1_score(_row(0, "training", _feats(k=0.2), 0.0)) == 1  # co-movement and volume trend stay silent
    assert s23.m1_score(_row(0, "training", _feats(g=0.3), 0.0)) == -2  # the paying side votes against
    assert s23.m1_decision(_row(0, "training", _feats(c=1.0), 0.0)) == TAKE
    assert s23.m1_decision(_row(0, "training", _feats(c=-1.0), 0.0)) == SKIP
    assert s23.m1_decision(_row(0, "training", _feats(k=1.0, g=-1.0), 0.0)) == NEUTRAL  # 1 + 2 = 3 < 4


def test_logit_learns_a_planted_feature():
    rng = random.Random(3)
    rows = []
    for j in range(3000):
        x = rng.gauss(0, 1)
        feats = _feats()
        feats["V"] = (x, rng.gauss(0, 1))
        rows.append(_row(j, "training", feats, 1.0 if x + rng.gauss(0, 0.5) > 0 else -1.0))
    model, take_at, skip_at = s23.m2_rule(rows)
    names = ["achse"] + [n for f in s23.FAMILIES for n in s23.FEATURES[f]]
    weights = dict(zip(names, model.weights))
    assert weights["vwap_24h_atr"] > 1.0 and abs(weights["vwap_woche_atr"]) < 0.3
    assert skip_at < take_at
    hi = _feats()
    hi["V"] = (2.0, 0.0)
    assert model.prob(_row(0, "x", hi, 0.0)) > take_at


def _planted(n_weeks: int, effect: float, seed: int) -> list[s23.Row]:
    """Two moments a day; the chart rules (C) carry ``effect`` R, everything else is noise."""
    rng = random.Random(seed)
    rows = []
    for section, start in (("training", START), ("validierung", VALIDATION_START_MS)):
        for j in range(n_weeks * 14):
            t = start + j * 12 * HOUR
            for direction in s22.DIRECTIONS:
                c = rng.choice((-1.0, 0.0, 1.0))
                feats = {"C": (c,) * 5, "K": tuple(rng.gauss(0, 1) for _ in range(3)), "F": tuple(rng.gauss(0, 0.2) for _ in range(6)),
                         "G": (rng.gauss(0, 1), rng.gauss(0, 1)), "T": tuple(rng.choice((-1.0, 1.0)) for _ in range(3)),
                         "V": (rng.gauss(0, 1), rng.gauss(0, 1))}
                rows.append(s23.Row(t, section, direction, feats, effect * c + rng.gauss(0, 1.0)))
    return rows


def test_planted_effect_passes_and_noise_fails(monkeypatch):
    monkeypatch.setattr(s23, "MIN_TRADES", 50)
    monkeypatch.setattr(s23, "MIN_WEEKS", 20)
    good = s23.evaluate(_planted(60, 0.5, 1), list(s23.FAMILIES), boot_draws=199, shift_draws=49)
    assert good["urteil_je_modell"]["M1"].startswith("BESTANDEN") and good["urteil"].startswith("BESTANDEN")
    noise = s23.evaluate(_planted(60, 0.0, 2), list(s23.FAMILIES), boot_draws=199, shift_draws=49)
    assert noise["urteil"] == "NO ROBUST EDGE PROVEN"
    assert set(noise["familien"]["validierung"]) == set(s23.FAMILIES)


def test_evaluate_refuses_a_draft_and_missing_families(monkeypatch):
    with pytest.raises(SystemExit):
        s23.evaluate([], ["C", "K"])
    monkeypatch.setattr(s23, "VERSION", "0.9")
    with pytest.raises(SystemExit):
        s23.evaluate([], list(s23.FAMILIES))
