"""Zusatzstudie S-K: Spezifikation, Regime, Kontrollen und Abnahme.

Alles mit synthetischen Daten; die laufende Kampagne wird nicht berührt.
Mehrere Tests bilden Befunde der unabhängigen Prüfung vom 22.10.2026 nach.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.v2_completion import control_regime_study as sk
from src.v2_completion.independent_cases import CanonicalIndependentUnit

UTC = timezone.utc
MIN = timedelta(minutes=1)
SPEC = sk.load_spec()
KIND = "FAILED_CONTINUATION"


def bars(start: datetime, minutes: int, *, skip: frozenset[datetime] = frozenset()) -> list[sk.MinuteBar]:
    out = []
    for i in range(minutes):
        t = start + i * MIN
        if t in skip:
            continue
        close = 30000 + 50 * ((i * 7919) % 13 - 6) * (1 + (t.hour % 6))
        out.append(sk.MinuteBar(open_time=t, close=float(close), quote_volume=float(1000 + (t.hour * 37 + i) % 500)))
    return out


def unit(uid: str, start: datetime, sample_class: str = "POSITIVE", **regimes: str) -> CanonicalIndependentUnit:
    fields = {"volatility_regime": "LOW", "liquidity_regime": "LOW", "session": "ASIA", "weekday": "WEEKDAY"}
    fields.update(regimes)
    return CanonicalIndependentUnit(
        unit_id=uid, start_utc=start, end_utc=start + timedelta(minutes=30), source_window=f"w-{uid}",
        data_complete=True, gap_exposure=False, observation_id=None, label="PRICE_SIDEWAYS",
        sample_class=sample_class, trend_regime="UNASSIGNED", reviewer_id=None, provenance="PUBLIC_MARKET_DATA",
        input_hash=hashlib.sha256(uid.encode()).hexdigest(), **fields,
    )


def resign(spec: dict) -> dict:
    spec = copy.deepcopy(spec)
    spec["spec_hash"] = sk.spec_content_hash(spec)
    return spec


# --- Spezifikation -------------------------------------------------------------


def test_spec_is_hash_bound_and_rejects_edits(tmp_path: Path) -> None:
    assert SPEC["spec_hash"] == sk.spec_content_hash(SPEC)
    changed = copy.deepcopy(SPEC)
    changed["minimums"]["units_per_class"] = 5
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(sk.SpecError, match="hash mismatch"):
        sk.load_spec(path)


def test_every_entry_point_rejects_a_spec_changed_in_memory() -> None:
    # Review finding 3: a changed dict used to run under the old hash.
    tampered = dict(SPEC, grid_minutes=5)
    t0 = datetime(2026, 10, 26, tzinfo=UTC)
    with pytest.raises(sk.SpecError, match="hash mismatch"):
        sk.build_controls(detector_kind=KIND, bars=[], trigger_minutes=[], t0=t0, study_end=t0, spec=tampered)
    with pytest.raises(sk.SpecError, match="hash mismatch"):
        sk.validate_study([], detector_kind=KIND, trigger_minutes=[], t0=t0, study_end=t0, spec=tampered)
    with pytest.raises(sk.SpecError, match="hash mismatch"):
        sk.calibrate_thresholds([], tampered)
    with pytest.raises(sk.SpecError, match="hash mismatch"):
        sk.kind_testability(trigger_minutes=[], begin=t0, end=t0, spec=tampered)


def test_spec_does_not_touch_parent_campaign() -> None:
    assert SPEC["parent_campaign"]["frozen_commit"] == "f469ad66d2796ec39d6c8e646acd222ae5826f14"
    assert SPEC["pre_t0_windows"] == "CALIBRATION_AND_EXPLORATION_ONLY"
    assert SPEC["human_approval"] is False
    assert "seed" not in SPEC  # controls are exhaustive, nothing is drawn
    assert any("PRICE_INCREASED" in item for item in SPEC["prohibitions"])
    assert SPEC["calibration"]["end_utc"] <= SPEC["parent_campaign"]["start_utc"]


def test_sessions_and_weekdays_cover_every_hour_and_day() -> None:
    monday = datetime(2026, 10, 26, tzinfo=UTC)
    seen = {sk.session_of(monday + timedelta(hours=h), SPEC) for h in range(24)}
    assert seen == {"ASIA", "EUROPE", "US"}
    assert sk.session_of(monday.replace(hour=7, minute=59), SPEC) == "ASIA"
    assert sk.session_of(monday.replace(hour=8), SPEC) == "EUROPE"
    assert [sk.weekday_class(monday + timedelta(days=d), SPEC) for d in range(7)] == ["WEEKDAY"] * 5 + ["WEEKEND"] * 2


# --- Regime --------------------------------------------------------------------


def test_regime_uses_only_data_before_window_start() -> None:
    start = datetime(2026, 10, 26, 12, tzinfo=UTC)
    series = {b.open_time: b for b in bars(start - 60 * MIN, 120)}
    before = sk.regime_values(series, start, 60)
    for t in list(series):
        if t >= start:
            series[t] = sk.MinuteBar(open_time=t, close=99999.0, quote_volume=1e12)
    assert sk.regime_values(series, start, 60) == before


def _calibrated() -> tuple[dict, list[sk.MinuteBar]]:
    spec = copy.deepcopy(SPEC)
    spec["calibration"].update(start_utc="2026-10-01T00:00:00Z", end_utc="2026-10-08T00:00:00Z")
    spec = resign(spec)
    series = bars(datetime(2026, 9, 30, 23, tzinfo=UTC), 7 * 1440 + 60)
    return spec, series


def test_calibration_gives_frozen_hash_bound_terciles() -> None:
    spec, series = _calibrated()
    result = sk.calibrate_thresholds(series, spec)
    for name in ("volatility", "liquidity"):
        limits = result["thresholds"][name]
        assert limits["low_max"] <= limits["mid_max"] and limits["windows"] >= 300
    assert result == sk.calibrate_thresholds(series, spec)
    sk.verify_thresholds(result, spec)
    edited = copy.deepcopy(result)
    edited["thresholds"]["volatility"]["low_max"] = 0
    with pytest.raises(sk.SpecError, match="thresholds hash"):
        sk.verify_thresholds(edited, spec)
    short = copy.deepcopy(spec)
    short["calibration"]["end_utc"] = "2026-10-01T12:00:00Z"
    with pytest.raises(sk.SpecError, match="needs 300"):
        sk.calibrate_thresholds(series, resign(short))


def test_units_without_full_lookback_are_excluded_and_counted() -> None:
    # Review finding 5: one missing lookback minute used to fail the whole study.
    spec, series = _calibrated()
    thresholds = sk.calibrate_thresholds(series, spec)
    start = datetime(2026, 10, 7, 12, tzinfo=UTC)
    gap = frozenset({start - 10 * MIN})
    data = [b for b in series if b.open_time not in gap]
    result = sk.with_regimes([unit("ok", start + timedelta(hours=2)), unit("gap", start)], data, thresholds, spec)
    assert [u.unit_id for u in result["units"]] == ["ok"]
    assert result["excluded_incomplete_lookback"] == ["gap"]
    assert sk.UNASSIGNED not in (result["units"][0].volatility_regime, result["units"][0].liquidity_regime)


# --- Kontrollen ------------------------------------------------------------------


T0 = datetime(2026, 10, 26, tzinfo=UTC)


def _controls(days: int = 2, triggers=(), gaps: frozenset[datetime] = frozenset()) -> dict:
    series = bars(T0 - 120 * MIN, days * 1440 + 120, skip=gaps)
    end = T0 + timedelta(days=days)
    return sk.build_controls(detector_kind=KIND, bars=series, trigger_minutes=list(triggers), t0=T0, study_end=end, spec=SPEC)


def test_controls_cover_the_grid_and_negatives_skip_recent_triggers() -> None:
    # 05:25 lies exactly 5 minutes before 05:30 (inside the negative lookback);
    # 06:24 lies 6 minutes before 06:30 (outside it)
    result = _controls(triggers=[T0 + timedelta(hours=5, minutes=25), T0 + timedelta(hours=6, minutes=24)])
    assert result["counts"]["NEUTRAL_CONTROL"] == 96  # 2 days x 48 half hours
    negatives = {c["start_utc"] for c in result["controls"] if c["sample_class"] == "NEGATIVE"}
    assert "2026-10-26T05:30:00Z" not in negatives
    assert "2026-10-26T05:00:00Z" in negatives and "2026-10-26T06:00:00Z" in negatives
    assert "2026-10-26T06:30:00Z" in negatives
    assert result["counts"]["NEGATIVE"] == 95


def test_negative_lookback_is_separate_from_regime_lookback() -> None:
    # Measured before T0: a 60-minute same-kind lookback leaves almost no negatives.
    assert SPEC["negative_lookback_minutes"] == 5 and SPEC["lookback_minutes"] == 60
    kinds = SPEC["kind_testability_pre_t0"]["kinds"]
    assert SPEC["kind_testability_pre_t0"]["outcomes_read"] is False
    assert kinds["LARGE_INDIVIDUAL_TRADE_ACTIVITY"]["status"] == "NOT_TESTABLE"
    assert sum(k["status"] == "TESTABLE" for k in kinds.values()) == 5


def test_controls_stay_the_same_when_the_range_grows_or_a_gap_appears() -> None:
    # Review finding 4: random picks used to shift when study_end moved.
    base = {c["unit_id"] for c in _controls(days=2)["controls"]}
    longer = {c["unit_id"] for c in _controls(days=4)["controls"]}
    assert base <= longer
    gap = frozenset({T0 + timedelta(days=1, hours=3, minutes=7)})
    with_gap = _controls(days=2, gaps=gap)
    lost = base - {c["unit_id"] for c in with_gap["controls"]}
    # only the cell holding the gap (03:00) and the two whose lookback covers it (03:30, 04:00) drop out,
    # each as one neutral and one negative
    assert {c["unit_id"] for c in with_gap["controls"]} <= base and len(lost) == 6
    assert with_gap["grid_cells_skipped_incomplete"] == 3


def test_negative_rule_does_not_look_inside_the_window() -> None:
    # Review concern: "no trigger in the 30 minutes" selects quiet outcomes.
    trigger_inside = T0 + timedelta(hours=3, minutes=15)
    negatives = {c["start_utc"] for c in _controls(triggers=[trigger_inside])["controls"] if c["sample_class"] == "NEGATIVE"}
    assert "2026-10-26T03:00:00Z" in negatives  # trigger lies inside this window, after its start


def test_testability_rounds_start_and_flags_kinds_that_fire_constantly() -> None:
    # Review finding 6: a start with seconds used to report 1.0.
    begin = datetime(2026, 10, 1, 0, 0, 30, tzinfo=UTC)
    every_minute = [datetime(2026, 10, 1, tzinfo=UTC) + i * MIN for i in range(600)]
    dense = sk.kind_testability(trigger_minutes=every_minute, begin=begin, end=begin + timedelta(hours=8), spec=SPEC)
    assert dense["negative_eligible_share"] == 0.0
    quiet = sk.kind_testability(trigger_minutes=[], begin=begin, end=begin + timedelta(hours=8), spec=SPEC)
    assert quiet["negative_eligible_share"] == 1.0 and quiet["grid_cells"] == 15


# --- Abnahme -------------------------------------------------------------------


def _regimes(cell: datetime, i: int) -> dict[str, str]:
    combos = [(v, l) for v in sk.LEVELS for l in sk.LEVELS]
    v, l = combos[i % len(combos)]
    return dict(volatility_regime=v, liquidity_regime=l, session=sk.session_of(cell, SPEC), weekday=sk.weekday_class(cell, SPEC))


def _full_sample(per_class: int = 300) -> tuple[list[CanonicalIndependentUnit], list[datetime], datetime]:
    """Controls on the :00/:30 grid in the first ~6 days; positives (and their triggers) at :10/:40
    from day 20 on, so every control cell has a trigger-free lookback."""
    units: list[CanonicalIndependentUnit] = []
    triggers: list[datetime] = []
    for i in range(per_class):
        cell = T0 + timedelta(minutes=30 * i)
        units.append(unit(f"NEUTRAL_CONTROL:{i}", cell, "NEUTRAL_CONTROL", **_regimes(cell, i)))
        units.append(unit(f"NEGATIVE:{i}", cell, "NEGATIVE", **_regimes(cell, i)))
        positive = T0 + timedelta(days=20, minutes=30 * i + 10)
        units.append(unit(f"POSITIVE:{i}", positive, "POSITIVE", **_regimes(positive, i)))
        triggers.append(positive)
    return units, triggers, T0 + timedelta(days=40)


def _validate(units, triggers, end, t0=T0):
    return sk.validate_study(units, detector_kind=KIND, trigger_minutes=triggers, t0=t0, study_end=end, spec=SPEC)


def test_complete_sample_passes() -> None:
    units, triggers, end = _full_sample()
    result = _validate(units, triggers, end)
    assert result["gate_status"] == "PASS", result["reasons"]
    assert result["human_approval"] is False


def test_empty_sample_fails_where_old_validator_passed() -> None:
    from src.v2_completion.independent_cases import validate_independent_units
    assert validate_independent_units([])["gate_status"] == "PASS"  # the gap this study closes
    result = _validate([], [], T0 + timedelta(days=1))
    assert result["gate_status"] == "FAIL" and "positive_below_minimum" in result["reasons"]


def test_positive_only_sample_fails() -> None:
    units, triggers, end = _full_sample()
    result = _validate([u for u in units if u.sample_class == "POSITIVE"], triggers, end)
    assert {"negative_below_minimum", "neutral_control_below_minimum"} <= set(result["reasons"])


def test_relabelled_positives_cannot_pose_as_controls() -> None:
    # Review finding 2: copying each positive as NEGATIVE and NEUTRAL used to PASS.
    units, triggers, end = _full_sample()
    positives = [u for u in units if u.sample_class == "POSITIVE"]
    fake = positives + [
        unit(f"{cls}-copy-{p.unit_id}", p.start_utc, cls, volatility_regime=p.volatility_regime,
             liquidity_regime=p.liquidity_regime, session=p.session, weekday=p.weekday)
        for p in positives for cls in ("NEGATIVE", "NEUTRAL_CONTROL")
    ]
    result = _validate(fake, triggers, end)
    assert result["gate_status"] == "FAIL"
    assert "units_violate_class_definition" in result["reasons"]


def test_positive_must_start_at_a_trigger_of_its_kind() -> None:
    units, triggers, end = _full_sample()
    assert "units_violate_class_definition" in _validate(units, triggers[1:], end)["reasons"]


def test_duplicate_ids_out_of_range_and_unassigned_fail() -> None:
    units, triggers, end = _full_sample()
    first = units[0]
    dup = units + [unit(first.unit_id, first.start_utc + timedelta(days=30), first.sample_class)]
    assert "duplicate_unit_ids_across_classes" in _validate(dup, triggers, end)["reasons"]
    assert "units_outside_t0_and_study_end" in _validate(units, triggers, end, t0=T0 + timedelta(hours=1))["reasons"]
    assert "units_outside_t0_and_study_end" in _validate(units, triggers, T0 + timedelta(days=5))["reasons"]
    broken = [unit(first.unit_id, first.start_utc, first.sample_class, volatility_regime=sk.UNASSIGNED)] + units[1:]
    assert "regime_unassigned_or_invalid" in _validate(broken, triggers, end)["reasons"]


def test_thin_regime_level_fails_for_controls_too() -> None:
    units, triggers, end = _full_sample()
    thin = [u for u in units if not (u.sample_class == "NEGATIVE" and u.volatility_regime == "LOW")]
    assert "negative_volatility_regime_coverage_below_minimum" in _validate(thin, triggers, end)["reasons"]


def test_overlap_within_a_class_fails() -> None:
    units, triggers, end = _full_sample()
    first_positive = next(u for u in units if u.sample_class == "POSITIVE")
    clash = unit("POSITIVE:clash", first_positive.start_utc + 10 * MIN, "POSITIVE", **_regimes(first_positive.start_utc, 0))
    result = _validate(units + [clash], triggers + [clash.start_utc], end)
    assert "positive_independence_or_quality_failed" in result["reasons"]


def test_realistic_size_runs_fast_enough() -> None:
    # Review: the old random draw took ~60 s for 30 days; the grid is linear.
    import time
    series = bars(T0 - 120 * MIN, 30 * 1440 + 120)
    triggers = [T0 + i * 3 * MIN for i in range(30 * 1440 // 3)]  # every 6-minute lookback holds one
    started = time.monotonic()
    result = sk.build_controls(detector_kind=KIND, bars=series, trigger_minutes=triggers, t0=T0,
                               study_end=T0 + timedelta(days=30), spec=SPEC)
    assert time.monotonic() - started < 20
    assert result["counts"] == {"NEGATIVE": 0, "NEUTRAL_CONTROL": 1440}
