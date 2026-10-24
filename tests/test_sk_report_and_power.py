"""Zusatzstudie S-K: Lesen aus dem Backup, Zwischenstand und Power-Simulation S2.

Alles mit synthetischen Daten; keine Datenbank, kein Netzwerk.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from src.v2_completion import control_regime_study as sk
from src.v2_completion import sk_power, sk_report

UTC = timezone.utc
MIN = timedelta(minutes=1)
SPEC = sk.load_spec()


def test_timestamps_from_pg_restore_are_converted_to_utc() -> None:
    assert sk_report.parse_timestamp("2026-07-23 14:43:00+02") == datetime(2026, 7, 23, 12, 43, tzinfo=UTC)
    assert sk_report.parse_timestamp("2026-07-23 14:43:00.25+00") == datetime(2026, 7, 23, 14, 43, 0, 250000, tzinfo=UTC)
    assert sk_report.parse_timestamp("2026-07-23 14:43:00-05:30") == datetime(2026, 7, 23, 20, 13, tzinfo=UTC)


OBS_DUMP = """--
-- PostgreSQL database dump
--
SET statement_timeout = 0;
COPY public.orderflow_observations (observation_id, kind, symbol, timeframe, observed_at, summary, evidence, rule_version, input_hash, provenance, mode) FROM stdin;
a\tSTRONG_BUYER_ACTIVITY\tBTCUSDT\t1m\t2026-10-26 02:10:00+02\ts\t[]\t1.0.0\th\tp\tOBSERVE
b\tSTRONG_BUYER_ACTIVITY\tBTCUSDT\t1m\t2026-10-26 02:10:00+02\ts\t[]\t1.0.0\th\tp\tOBSERVE
c\tSTRONG_BUYER_ACTIVITY\tETHUSDT\t1m\t2026-10-26 02:11:00+02\ts\t[]\t1.0.0\th\tp\tOBSERVE
d\tHIGH_TRADE_FREQUENCY\tBTCUSDT\t1m\t2026-10-26 01:05:30+01\ts\t[]\t1.0.0\th\tp\tOBSERVE
\\.
"""


def test_observations_become_trigger_minutes_per_kind() -> None:
    found = sk_report.trigger_minutes_by_kind(OBS_DUMP.splitlines(keepends=True))
    assert found == {
        "HIGH_TRADE_FREQUENCY": [datetime(2026, 10, 26, 0, 5, tzinfo=UTC)],
        "STRONG_BUYER_ACTIVITY": [datetime(2026, 10, 26, 0, 10, tzinfo=UTC)],
    }


def test_candles_become_minute_bars_with_usdt_volume() -> None:
    dump = (
        "COPY public.candles (symbol, timeframe, open_time, close_time, open, high, low, close, volume, trade_count, closed) FROM stdin;\n"
        "BTCUSDT\t1m\t2026-10-26 00:00:00+00\t2026-10-26 00:00:59+00\t1\t1\t1\t100\t2\t5\tt\n"
        "BTCUSDT\t5m\t2026-10-26 00:00:00+00\t2026-10-26 00:04:59+00\t1\t1\t1\t100\t2\t5\tt\n"
        "BTCUSDT\t1m\t2026-10-26 00:01:00+00\t2026-10-26 00:01:59+00\t1\t1\t1\t100\t2\t5\tf\n"
        "\\.\n"
    )
    bars = sk_report.minute_bars(dump.splitlines(keepends=True))
    assert len(bars) == 1 and bars[0].quote_volume == 200.0


def _bars(start: datetime, minutes: int, skip: frozenset[datetime] = frozenset()) -> list[sk.MinuteBar]:
    out = []
    for i in range(minutes):
        t = start + i * MIN
        if t in skip:
            continue
        close = 30000 + 40 * ((i * 7919) % 11 - 5) * (1 + t.hour % 5)
        out.append(sk.MinuteBar(open_time=t, close=float(close), quote_volume=float(500 + (t.hour * 31 + i) % 700)))
    return out


def test_positive_windows_are_greedy_and_skip_incomplete_data() -> None:
    t0 = datetime(2026, 10, 26, tzinfo=UTC)
    gap = t0 + timedelta(hours=3, minutes=5)
    lookup = {b.open_time: b for b in _bars(t0 - 120 * MIN, 600, skip=frozenset({gap}))}
    triggers = [t0 + timedelta(hours=1), t0 + timedelta(hours=1, minutes=10), t0 + timedelta(hours=1, minutes=30),
                t0 + timedelta(hours=3)]
    starts, dropped = sk_report.positive_starts(triggers, lookup, t0=t0, study_end=t0 + timedelta(hours=6), spec=SPEC)
    assert starts == [t0 + timedelta(hours=1), t0 + timedelta(hours=1, minutes=30)]
    assert dropped == 1  # 03:00 holds the gap in its window


def test_status_counts_units_without_reading_outcomes() -> None:
    calibration = _bars(datetime(2026, 9, 30, 22, tzinfo=UTC), 21 * 1440)
    thresholds = sk.calibrate_thresholds(calibration, SPEC)
    t0 = datetime(2026, 10, 26, tzinfo=UTC)
    study = _bars(t0 - 120 * MIN, 2 * 1440 + 120)
    triggers = {"STRONG_BUYER_ACTIVITY": [t0 + timedelta(hours=h, minutes=12) for h in range(0, 48, 3)]}
    result = sk_report.study_status(triggers_by_kind=triggers, bars=study, thresholds=thresholds, t0=t0,
                                    study_end=t0 + timedelta(days=2), spec=SPEC)
    kind = result["kinds"]["STRONG_BUYER_ACTIVITY"]
    assert result["outcomes_read"] is False
    assert kind["sample_class_counts"] == {"POSITIVE": 16, "NEGATIVE": 96, "NEUTRAL_CONTROL": 96}
    assert kind["gate_status"] == "FAIL" and "positive_below_minimum" in kind["reasons"]
    assert "units_violate_class_definition" not in kind["reasons"]
    assert "regime_unassigned_or_invalid" not in kind["reasons"]


def test_identical_rows_give_p_one_and_clear_difference_gives_small_p() -> None:
    assert sk_power.chi2_2x3_pvalue([10, 10, 10], [20, 20, 20]) == 1.0
    assert sk_power.chi2_2x3_pvalue([200, 50, 50], [50, 200, 50]) < 1e-20
    assert sk_power.chi2_2x3_pvalue([0, 0, 0], [1, 2, 3]) == 1.0


def test_power_simulation_is_deterministic_and_sane() -> None:
    first = sk_power.run(n_neg_values=(100, 850), sideways_values=(0.45,), reps=300)
    again = sk_power.run(n_neg_values=(100, 850), sideways_values=(0.45,), reps=300)
    assert first == again and first["market_data_read"] is False
    by = {(r["n_neg"], r["effect"]): r for r in first["rows"]}
    for effect in ("DIRECTIONAL", "VOLATILITY"):
        assert by[(850, effect)]["minimum_detectable_effect"] <= by[(100, effect)]["minimum_detectable_effect"]
    rng = random.Random(1)
    fpr = sk_power.false_positive_rate(n_pos=1200, n_neg=300, base=sk_power.baseline(0.45), alpha=0.05, reps=2000, rng=rng)
    assert 0.03 < fpr < 0.07


def test_spec_records_power_result_and_open_items() -> None:
    assert SPEC["power_simulation_s2"]["market_data_read"] is False
    assert SPEC["evaluation"]["primary_test"]["regime_levels"].startswith("DESCRIPTIVE_ONLY")
    assert "human_approval_of_this_spec" in SPEC["open_before_t0"]
