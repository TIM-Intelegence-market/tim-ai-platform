"""Study S18: Kronos path fan, scoring and gate on synthetic data (no market data, no model)."""

from __future__ import annotations

import math
import random

import pytest

from src.research_lab.studies import s18

H = s18.HOUR_MS


def _candles(start: int, n: int, seed: int = 1, vol: float = 0.5) -> list[s18.Candle]:
    rng, price, out = random.Random(seed), 50_000.0, []
    for k in range(n):
        o = price
        price = o * math.exp(rng.gauss(0, vol) / 100)
        out.append(s18.Candle(start + k * H, o, max(o, price), min(o, price), price, 1.0, price))
    return out


def _record(t0: int, close0: float, paths: list[float], **over) -> dict:
    rec = {"symbol": "BTCUSDT", "t0_ms": t0, "close0": close0, "kronos_final_logret": paths,
           "written_ms": t0 + 5 * 60 * 1000, "kronos_commit": s18.KRONOS_COMMIT,
           "model_sha256": s18.MODEL_SHA256, "tokenizer_sha256": s18.TOKENIZER_SHA256}
    rec.update(over)
    return rec


def test_forecast_grid_is_4h_utc():
    t = s18.forecast_times(s18.FORWARD_START_MS + 1, s18.FORWARD_START_MS + 9 * H)
    assert t == [s18.FORWARD_START_MS + 4 * H, s18.FORWARD_START_MS + 8 * H]
    assert s18.slot_of(s18.FORWARD_START_MS + 3 * H + 59 * 60_000) == s18.FORWARD_START_MS


def test_forward_window():
    assert s18.is_forward_time(s18.FORWARD_START_MS)
    assert not s18.is_forward_time(s18.FORWARD_START_MS - s18.STEP_MS)
    assert not s18.is_forward_time(s18.FORWARD_START_MS + H)
    assert not s18.is_forward_time(s18.FORWARD_START_MS + s18.FORWARD_MAX_DAYS * 24 * H)


def test_history_uses_only_closed_candles_and_rejects_gaps():
    c = _candles(0, 100)
    t0 = 50 * H
    hist = s18.history_before(c, t0, 10)
    assert hist[-1].open_time == t0 - H and len(hist) == 10
    gap = c[:45] + c[46:]
    assert s18.history_before(gap, t0, 10) is None
    assert s18.history_before(c, t0, 51) is None  # not enough candles


def test_outcome_is_24h_close_to_close():
    c = _candles(0, 100)
    t0 = 40 * H
    y = s18.outcome(c, t0)
    assert y == pytest.approx(100 * math.log(c[63].close / c[39].close))
    assert s18.outcome(c[:63], t0) is None


def test_crps_samples_matches_brute_force():
    rng = random.Random(4)
    xs = [rng.gauss(0, 1) for _ in range(37)]
    y = 0.3
    brute = sum(abs(x - y) for x in xs) / len(xs) - 0.5 * sum(abs(a - b) for a in xs for b in xs) / len(xs) ** 2
    assert s18.crps_samples(xs, y) == pytest.approx(brute)


def test_crps_normal_matches_large_sample():
    rng = random.Random(5)
    xs = [rng.gauss(0, 2.0) for _ in range(4000)]
    assert s18.crps_normal(2.0, 1.0) == pytest.approx(s18.crps_samples(xs, 1.0), rel=0.03)


def test_crps_prefers_the_true_distribution():
    rng = random.Random(6)
    good = bad = 0.0
    for _ in range(400):
        y = rng.gauss(0, 1)
        good += s18.crps_normal(1.0, y)
        bad += s18.crps_normal(3.0, y)
    assert good < bad


def test_quantile_and_coverage():
    xs = list(range(101))
    assert s18.quantile(xs, 0.1) == pytest.approx(10)
    assert s18.inside_samples(xs, 50, 0.8) and not s18.inside_samples(xs, 95, 0.8)
    assert s18.inside_normal(1.0, 1.27, 0.8) and not s18.inside_normal(1.0, 1.29, 0.8)


def test_ewma_sigma_scales_with_volatility():
    lo = s18.ewma_sigma_24h(_candles(0, s18.LOOKBACK_H, vol=0.3))
    hi = s18.ewma_sigma_24h(_candles(0, s18.LOOKBACK_H, vol=0.9))
    assert hi > 2 * lo
    assert lo == pytest.approx(0.3 * math.sqrt(24), rel=0.35)


def test_historical_returns_count_and_last():
    c = _candles(0, s18.LOOKBACK_H)
    r = s18.historical_returns(c)
    assert len(r) == s18.HIST_N
    assert r[0] == pytest.approx(100 * math.log(c[-1].close / c[-25].close))


def test_dm_lag_at_least_6():
    assert s18.dm_lag(50) == 6 and s18.dm_lag(100_000) > 6


def test_valid_record_rules():
    t0 = s18.FORWARD_START_MS
    ok = _record(t0, 1.0, [0.0] * s18.N_PATHS)
    assert s18.valid_record(ok)
    assert not s18.valid_record({**ok, "t0_ms": t0 - s18.STEP_MS})                 # before forward start
    assert not s18.valid_record({**ok, "written_ms": t0 + 3 * H})                   # written too late
    assert not s18.valid_record({**ok, "model_sha256": "x"})                        # other weights
    assert not s18.valid_record({**ok, "kronos_final_logret": [0.0] * 99})          # not 100 paths
    assert not s18.valid_record({**ok, "kronos_final_logret": [float("nan")] * 100})


def _scored_set(n: int, k_sigma: float, seed: int = 7) -> list[s18.Scored]:
    """Forecasts where truth ~ N(0, 1) per step; Kronos samples N(0, k_sigma); B1 sigma 1.5 (too wide)."""
    rng = random.Random(seed)
    out = []
    levels = s18.DESCRIPTIVE_LEVELS
    for i in range(n):
        y = rng.gauss(0, 1)
        k = [rng.gauss(0, k_sigma) for _ in range(s18.N_PATHS)]
        h2 = [rng.gauss(0, 2.0) for _ in range(s18.HIST_N)]
        out.append(s18.Scored(i * s18.STEP_MS, y, s18.crps_samples(k, y), s18.crps_normal(1.5, y),
                              s18.crps_samples(h2, y), {lv: s18.inside_samples(k, y, lv) for lv in levels},
                              {lv: s18.inside_normal(1.5, y, lv) for lv in levels},
                              {lv: s18.inside_samples(h2, y, lv) for lv in levels}))
    return out


def test_gate_refuses_scores():
    v = s18.verdict(_scored_set(s18.GATE_MIN_FORECASTS - 1, 1.0))
    assert v["gate"] is False and "dm_vs_b1" not in v


def test_verdict_passes_calibrated_better_model():
    v = s18.verdict(_scored_set(800, 1.0))
    assert v["verdict"] == "BESTANDEN", v["criteria"]


def test_verdict_rejects_too_narrow_fan():
    v = s18.verdict(_scored_set(800, 0.5))
    assert v["criteria"]["4_calibrated"] is False
    assert v["verdict"].startswith("NICHT BESTANDEN")


def test_score_checks_close0_and_history():
    t0 = s18.LOOKBACK_H * H
    c = _candles(0, s18.LOOKBACK_H + 30)
    rec = _record(t0, c[s18.LOOKBACK_H - 1].close, [0.1] * s18.N_PATHS)
    sc = s18.score(rec, c)
    assert sc is not None and sc.y == pytest.approx(s18.outcome(c, t0))
    assert s18.score({**rec, "close0": 1.0}, c) is None
    assert s18.score(rec, c[: s18.LOOKBACK_H + 10]) is None  # outcome not yet there
