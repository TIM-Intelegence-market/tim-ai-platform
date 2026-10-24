"""Zusatzstudie S-K: Kontrollklassen und Regime für die V2-Qualifizierung.

Die laufende Kampagne (V2_PROSPECTIVE_QUALIFICATION_V1) sammelt nur Fenster,
in denen ein Detektor ausgelöst hat. Sie bildet keine Negativ- oder
Neutralkontrollen und ordnet keine Regime zu. Diese Studie macht das offline
auf Kopien derselben Daten, mit Regeln aus einer eigenen, gehashten
Spezifikation (artifacts/v2_completion/sk_control_regime_spec.json).

Kontrollen werden nicht zufällig gezogen, sondern vollständig aus einem festen
Halbstunden-Raster (:00 und :30 UTC) gebildet. Jede Rasterzelle wird nur nach
ihren eigenen Daten beurteilt. Darum ändert sich eine einmal gebildete
Kontrolle nicht, wenn der Auswertungszeitraum wächst oder anderswo eine Lücke
liegt, und es gibt nichts auszusuchen.

Alles hier ist rein rechnend: kein Datenbankzugriff, keine Netzwerkzugriffe,
keine Schreibzugriffe. Gewertet werden nur Fenster, die ab T0 beginnen.
T0 ist der Merge der Spezifikation in platform-main und wird getrennt
festgehalten, damit der Spezifikations-Hash stabil bleibt.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

from src.v2_completion.independent_cases import (
    UTC,
    CanonicalIndependentUnit,
    iso,
    stable_hash,
    validate_independent_units,
)

STUDY_ID = "V2_SK_CONTROL_REGIME_V1"
SPEC_PATH = Path("artifacts/v2_completion/sk_control_regime_spec.json")
MINUTE = timedelta(minutes=1)
LEVELS = ("LOW", "MID", "HIGH")
UNASSIGNED = "UNASSIGNED"
CLASSES = ("POSITIVE", "NEGATIVE", "NEUTRAL_CONTROL")
REQUIRED_SPEC_FIELDS = (
    "window_minutes", "lookback_minutes", "negative_lookback_minutes", "grid_minutes",
    "sessions", "weekday_classes", "regimes", "controls", "minimums", "calibration",
)


class SpecError(ValueError):
    """Die Spezifikation fehlt, ist verändert oder unvollständig."""


@dataclass(frozen=True, slots=True)
class MinuteBar:
    """Eine geschlossene 1-Minuten-Kerze aus öffentlichen Binance-Daten."""

    open_time: datetime
    close: float
    quote_volume: float

    def __post_init__(self) -> None:
        if self.open_time.tzinfo is None:
            raise ValueError("minute bar timestamp must be timezone-aware")
        if self.open_time.second or self.open_time.microsecond:
            raise ValueError("minute bar must start on a full minute")
        if not self.close > 0:
            raise ValueError("minute bar close must be positive")
        if self.quote_volume < 0:
            raise ValueError("minute bar quote volume must not be negative")


# --- Spezifikation ---------------------------------------------------------


def spec_content_hash(spec: Mapping[str, Any]) -> str:
    """Hash über alle Felder außer dem Hash selbst."""
    return stable_hash({key: value for key, value in spec.items() if key != "spec_hash"})


def verify_spec(spec: Mapping[str, Any]) -> None:
    """Weist jede Spezifikation ab, deren Inhalt nicht zu ihrem Hash passt.

    Jede öffentliche Funktion ruft das auf, damit ein im Speicher veränderter
    Regelsatz nicht unter dem alten Hash weiterläuft.
    """
    if spec.get("study_id") != STUDY_ID:
        raise SpecError("spec belongs to a different study")
    if spec.get("spec_hash") != spec_content_hash(spec):
        raise SpecError("spec hash mismatch: the rules were changed after hashing")
    for key in REQUIRED_SPEC_FIELDS:
        if key not in spec:
            raise SpecError(f"spec field missing: {key}")


def load_spec(path: Path = SPEC_PATH) -> dict[str, Any]:
    if not path.exists():
        raise SpecError(f"spec missing: {path}")
    spec = json.loads(path.read_text(encoding="utf-8"))
    verify_spec(spec)
    return spec


def _minute(value: datetime) -> datetime:
    value = value.astimezone(UTC)
    if value.second or value.microsecond:
        raise ValueError(f"timestamp must be minute-aligned: {iso(value)}")
    return value


def _ceil_minute(value: datetime) -> datetime:
    value = value.astimezone(UTC)
    floor = value.replace(second=0, microsecond=0)
    return floor if floor == value else floor + MINUTE


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SpecError("spec timestamps must carry a timezone")
    return parsed.astimezone(UTC)


# --- Regime ------------------------------------------------------------------


def _bars_by_minute(bars: Iterable[MinuteBar]) -> dict[datetime, MinuteBar]:
    return {bar.open_time.astimezone(UTC): bar for bar in bars}


def lookback_bars(bars: Mapping[datetime, MinuteBar], start: datetime, minutes: int) -> list[MinuteBar] | None:
    """Die `minutes` Kerzen direkt vor `start`. None, wenn auch nur eine fehlt."""
    found = []
    for offset in range(minutes, 0, -1):
        bar = bars.get(start - offset * MINUTE)
        if bar is None:
            return None
        found.append(bar)
    return found


def realized_volatility(window: Sequence[MinuteBar]) -> float:
    """Wurzel der Summe quadrierter 1-Minuten-Log-Renditen."""
    returns = [math.log(b.close / a.close) for a, b in pairwise(window)]
    return math.sqrt(sum(value * value for value in returns))


def quote_volume(window: Sequence[MinuteBar]) -> float:
    return sum(bar.quote_volume for bar in window)


def regime_values(bars: Mapping[datetime, MinuteBar], start: datetime, lookback: int) -> dict[str, float] | None:
    """Messgrößen nur aus Daten vor dem Fensterbeginn (kein Blick nach vorn)."""
    window = lookback_bars(bars, _minute(start), lookback)
    if window is None:
        return None
    return {"volatility": realized_volatility(window), "liquidity": quote_volume(window)}


def nearest_rank(sorted_values: Sequence[float], fraction: float) -> float:
    if not sorted_values:
        raise ValueError("no values to rank")
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def _window_complete(bars: Mapping[datetime, MinuteBar], start: datetime, minutes: int) -> bool:
    return all(start + offset * MINUTE in bars for offset in range(minutes))


def calibrate_thresholds(bars: Iterable[MinuteBar], spec: Mapping[str, Any]) -> dict[str, Any]:
    """Terzilgrenzen aus dem Kalibrierzeitraum der Spezifikation (vor Kampagnenstart)."""
    verify_spec(spec)
    lookup = _bars_by_minute(bars)
    calibration = spec["calibration"]
    begin = _parse(calibration["start_utc"])
    end = _parse(calibration["end_utc"])
    step = timedelta(minutes=int(spec["grid_minutes"]))
    window = int(spec["window_minutes"])
    values: dict[str, list[float]] = {"volatility": [], "liquidity": []}
    start = _grid_ceil(begin, int(spec["grid_minutes"]))
    while start + window * MINUTE <= end:
        if _window_complete(lookup, start, window):
            measured = regime_values(lookup, start, int(spec["lookback_minutes"]))
            if measured is not None:
                for name, value in measured.items():
                    values[name].append(value)
        start += step
    minimum = int(calibration["minimum_windows"])
    thresholds: dict[str, Any] = {}
    for name, collected in values.items():
        if len(collected) < minimum:
            raise SpecError(f"calibration has {len(collected)} {name} windows, needs {minimum}")
        ordered = sorted(collected)
        thresholds[name] = {
            "low_max": nearest_rank(ordered, 1 / 3),
            "mid_max": nearest_rank(ordered, 2 / 3),
            "windows": len(ordered),
        }
    payload = {
        "study_id": STUDY_ID,
        "spec_hash": spec["spec_hash"],
        "calibration_start_utc": iso(begin),
        "calibration_end_utc": iso(end),
        "thresholds": thresholds,
    }
    payload["thresholds_hash"] = stable_hash(payload)
    return payload


def verify_thresholds(thresholds: Mapping[str, Any], spec: Mapping[str, Any]) -> None:
    body = {key: value for key, value in thresholds.items() if key != "thresholds_hash"}
    if thresholds.get("thresholds_hash") != stable_hash(body):
        raise SpecError("thresholds hash mismatch: thresholds were changed after calibration")
    if thresholds.get("spec_hash") != spec["spec_hash"]:
        raise SpecError("thresholds were calibrated under a different spec")


def level(value: float, threshold: Mapping[str, float]) -> str:
    if value <= threshold["low_max"]:
        return "LOW"
    if value <= threshold["mid_max"]:
        return "MID"
    return "HIGH"


def session_of(start: datetime, spec: Mapping[str, Any]) -> str:
    hour = start.astimezone(UTC).hour
    for session in spec["sessions"]:
        if int(session["start_hour"]) <= hour < int(session["end_hour"]):
            return str(session["name"])
    raise SpecError(f"no session covers UTC hour {hour}")


def weekday_class(start: datetime, spec: Mapping[str, Any]) -> str:
    day = start.astimezone(UTC).isoweekday()
    for name, days in spec["weekday_classes"].items():
        if day in days:
            return str(name)
    raise SpecError(f"no weekday class covers ISO day {day}")


def assign_regimes(
    start: datetime,
    bars: Mapping[datetime, MinuteBar],
    thresholds: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> dict[str, str]:
    verify_spec(spec)
    verify_thresholds(thresholds, spec)
    measured = regime_values(bars, start, int(spec["lookback_minutes"]))
    limits = thresholds["thresholds"]
    return {
        "volatility_regime": level(measured["volatility"], limits["volatility"]) if measured else UNASSIGNED,
        "liquidity_regime": level(measured["liquidity"], limits["liquidity"]) if measured else UNASSIGNED,
        "session": session_of(start, spec),
        "weekday": weekday_class(start, spec),
    }


def with_regimes(
    units: Sequence[CanonicalIndependentUnit],
    bars: Iterable[MinuteBar],
    thresholds: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    """Setzt die Regimefelder. Einheiten ohne vollständigen Rückblick werden
    ausgeschlossen und gezählt, nicht still behalten."""
    lookup = _bars_by_minute(bars)
    kept: list[CanonicalIndependentUnit] = []
    excluded: list[str] = []
    for unit in units:
        regimes = assign_regimes(unit.start_utc, lookup, thresholds, spec)
        if UNASSIGNED in regimes.values():
            excluded.append(unit.unit_id)
            continue
        kept.append(replace(unit, **regimes))
    return {"units": kept, "excluded_incomplete_lookback": excluded}


# --- Kontrollen aus dem Raster ---------------------------------------------


def _grid_ceil(value: datetime, grid_minutes: int) -> datetime:
    value = _ceil_minute(value)
    offset = (value.hour * 60 + value.minute) % grid_minutes
    return value if offset == 0 else value + (grid_minutes - offset) * MINUTE


def _on_grid(value: datetime, grid_minutes: int) -> bool:
    value = value.astimezone(UTC)
    return not value.second and not value.microsecond and (value.hour * 60 + value.minute) % grid_minutes == 0


def _trigger_set(trigger_minutes: Iterable[datetime]) -> set[datetime]:
    return {value.astimezone(UTC).replace(second=0, microsecond=0) for value in trigger_minutes}


def negative_eligible(start: datetime, triggers: set[datetime], lookback: int) -> bool:
    """Kein Signal dieses Typs im Rückblick und in der Startminute.

    Bewusst NICHT „kein Signal im ganzen Fenster“: Die Detektoren reagieren auf
    Aktivität, also würde das Negativfenster nach seinem eigenen Ausgang
    (ruhig) ausgewählt. Entschieden wird nur mit dem Wissen zum Fensterbeginn.
    """
    return all(start - offset * MINUTE not in triggers for offset in range(lookback + 1))


def build_controls(
    *,
    detector_kind: str,
    bars: Iterable[MinuteBar],
    trigger_minutes: Iterable[datetime],
    t0: datetime,
    study_end: datetime,
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    """Bildet Negativ- und Neutralkontrollen für EINEN Signaltyp aus dem Raster.

    NEUTRAL_CONTROL: jede gültige Rasterzelle (vollständiges Fenster und
    vollständiger Rückblick) in [t0, study_end).
    NEGATIVE: jede gültige Rasterzelle ohne Signal dieses Typs im Rückblick
    und in der Startminute. Abgeglichen mit den Positivfenstern wird in der
    Auswertung über Schichten (UTC-Stunde, Wochentagsart, Regime).
    Innerhalb einer Klasse überlappen Rasterzellen nie.
    """
    verify_spec(spec)
    grid = int(spec["grid_minutes"])
    window = int(spec["window_minutes"])
    lookback = int(spec["lookback_minutes"])
    negative_lookback = int(spec["negative_lookback_minutes"])
    if grid < window:
        raise SpecError("grid must be at least as wide as a window, or controls overlap")
    lookup = _bars_by_minute(bars)
    triggers = _trigger_set(trigger_minutes)
    t0 = t0.astimezone(UTC)
    study_end = study_end.astimezone(UTC)
    controls: list[dict[str, Any]] = []
    skipped_incomplete = 0
    start = _grid_ceil(t0, grid)
    while start + window * MINUTE <= study_end:
        if _window_complete(lookup, start, window) and lookback_bars(lookup, start, lookback) is not None:
            stamp = iso(start)
            controls.append({"unit_id": f"NEUTRAL_CONTROL:{stamp}", "sample_class": "NEUTRAL_CONTROL", "start_utc": stamp})
            if negative_eligible(start, triggers, negative_lookback):
                controls.append({"unit_id": f"NEGATIVE:{detector_kind}:{stamp}", "sample_class": "NEGATIVE", "start_utc": stamp})
        else:
            skipped_incomplete += 1
        start += grid * MINUTE
    payload = {
        "study_id": STUDY_ID,
        "spec_hash": spec["spec_hash"],
        "detector_kind": detector_kind,
        "t0_utc": iso(t0),
        "study_end_utc": iso(study_end),
        "grid_cells_skipped_incomplete": skipped_incomplete,
        "counts": {
            name: sum(item["sample_class"] == name for item in controls)
            for name in ("NEGATIVE", "NEUTRAL_CONTROL")
        },
        "controls": controls,
    }
    payload["controls_hash"] = stable_hash(payload)
    return payload


# --- Abnahme -----------------------------------------------------------------


def validate_study(
    units: Iterable[CanonicalIndependentUnit],
    *,
    detector_kind: str,
    trigger_minutes: Iterable[datetime],
    t0: datetime,
    study_end: datetime,
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    """Prüft die fertige Stichprobe EINES Signaltyps gegen die Spezifikation.

    Geprüft wird nicht nur gezählt, sondern ob jede Einheit ihre
    Klassendefinition erfüllt: Positivfenster beginnen bei einem Signal
    dieses Typs, Kontrollen liegen auf dem Raster, Negativfenster haben kein
    Signal im Rückblick, alles liegt in [t0, study_end). Eine leere oder rein
    positive Stichprobe ergibt FAIL.
    """
    verify_spec(spec)
    values = list(units)
    triggers = _trigger_set(trigger_minutes)
    grid = int(spec["grid_minutes"])
    window = int(spec["window_minutes"])
    negative_lookback = int(spec["negative_lookback_minutes"])
    t0 = t0.astimezone(UTC)
    study_end = study_end.astimezone(UTC)
    reasons: list[str] = []

    ids = [unit.unit_id for unit in values]
    if len(set(ids)) != len(ids):
        reasons.append("duplicate_unit_ids_across_classes")

    out_of_range = sorted(
        unit.unit_id for unit in values
        if unit.start_utc < t0 or unit.start_utc + window * MINUTE > study_end
    )
    if out_of_range:
        reasons.append("units_outside_t0_and_study_end")

    wrong_class: list[str] = []
    for unit in values:
        start = unit.start_utc.astimezone(UTC)
        if start.second or start.microsecond:
            wrong_class.append(unit.unit_id)
        elif unit.sample_class == "POSITIVE" and start not in triggers:
            wrong_class.append(unit.unit_id)
        elif unit.sample_class in ("NEGATIVE", "NEUTRAL_CONTROL") and not _on_grid(start, grid):
            wrong_class.append(unit.unit_id)
        elif unit.sample_class == "NEGATIVE" and not negative_eligible(start, triggers, negative_lookback):
            wrong_class.append(unit.unit_id)
    if wrong_class:
        reasons.append("units_violate_class_definition")

    per_class = {
        name: validate_independent_units([unit for unit in values if unit.sample_class == name])
        for name in CLASSES
    }
    for name, check in per_class.items():
        if check["gate_status"] != "PASS":
            reasons.append(f"{name.lower()}_independence_or_quality_failed")
    counts = {name: check["unit_count"] for name, check in per_class.items()}

    minimums = spec["minimums"]
    for name in CLASSES:
        if counts[name] < int(minimums["units_per_class"]):
            reasons.append(f"{name.lower()}_below_minimum")

    allowed = {
        "volatility_regime": set(LEVELS),
        "liquidity_regime": set(LEVELS),
        "session": {str(item["name"]) for item in spec["sessions"]},
        "weekday": set(spec["weekday_classes"]),
    }
    unassigned = sorted(
        unit.unit_id for unit in values
        if any(getattr(unit, field) not in options for field, options in allowed.items())
    )
    if unassigned:
        reasons.append("regime_unassigned_or_invalid")

    per_level = int(minimums["units_per_regime_level_per_class"])
    coverage: dict[str, dict[str, dict[str, int]]] = {}
    for name in CLASSES:
        coverage[name] = {}
        for field, options in allowed.items():
            tally = {option: 0 for option in sorted(options)}
            for unit in values:
                if unit.sample_class == name and getattr(unit, field) in tally:
                    tally[getattr(unit, field)] += 1
            coverage[name][field] = tally
            if any(count < per_level for count in tally.values()):
                reasons.append(f"{name.lower()}_{field}_coverage_below_minimum")

    return {
        "study_id": STUDY_ID,
        "spec_hash": spec["spec_hash"],
        "detector_kind": detector_kind,
        "t0_utc": iso(t0),
        "study_end_utc": iso(study_end),
        "unit_count": len(values),
        "sample_class_counts": counts,
        "regime_coverage": coverage,
        "units_outside_range": out_of_range,
        "units_violating_class_definition": sorted(wrong_class),
        "unassigned_unit_ids": unassigned,
        "independence_within_class": per_class,
        "gate_status": "FAIL" if reasons else "PASS",
        "reasons": reasons,
        "human_approval": False,
    }


def kind_testability(
    *,
    trigger_minutes: Iterable[datetime],
    begin: datetime,
    end: datetime,
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    """Anteil der Rasterzellen in [begin, end), die als Negativfenster taugen.

    Vor T0 auf Daten vor dem Kampagnenstart laufen lassen: Ein Signaltyp,
    der in fast jedem Rückblick feuert, hat keine Negativfenster und ist mit
    diesem Design nicht prüfbar.
    """
    verify_spec(spec)
    grid = int(spec["grid_minutes"])
    window = int(spec["window_minutes"])
    negative_lookback = int(spec["negative_lookback_minutes"])
    triggers = _trigger_set(trigger_minutes)
    end = end.astimezone(UTC)
    total = 0
    eligible = 0
    start = _grid_ceil(begin, grid)
    while start + window * MINUTE <= end:
        total += 1
        eligible += negative_eligible(start, triggers, negative_lookback)
        start += grid * MINUTE
    return {
        "grid_cells": total,
        "negative_eligible_cells": eligible,
        "negative_eligible_share": (eligible / total) if total else None,
        "trigger_minutes": len(triggers),
    }
