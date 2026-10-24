"""Zusatzstudie S-K: Kalibrierung und Zwischenstand aus der Backup-Datei.

Liest Tabellen als COPY-Text, wie ihn ``pg_restore -a -t <tabelle> -f -``
aus dem täglichen Backup ausgibt. Keine Datenbankverbindung, keine
Zugangsdaten, kein Schreiben in die Datenbank.

Der Zwischenstand zählt nur Fenster und prüft die Abnahmeregeln. Ergebnisse
(Kursverläufe nach Fensterbeginn) werden dabei nicht gelesen: Jede Einheit
trägt das Label ``NOT_EVALUATED``. Ausgewertet wird erst am Studienende.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from src.v2_completion import control_regime_study as sk
from src.v2_completion.independent_cases import UTC, CanonicalIndependentUnit, iso

SYMBOL = "BTCUSDT"
NOT_EVALUATED = "NOT_EVALUATED"
PROVENANCE = "BINANCE_SPOT_AGGTRADE_DETERMINISTIC_BACKUP_READ"
_COPY = re.compile(r"^COPY\s+(?P<table>[\w.\"]+)\s*\((?P<cols>[^)]*)\)\s+FROM\s+stdin;")
_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(\.\d+)?([+-]\d{2})(?::?(\d{2}))?$")


def parse_timestamp(value: str) -> datetime:
    """Postgres-Ausgabe wie ``2026-07-23 14:43:00+02`` nach UTC."""
    match = _TS.match(value.strip())
    if not match:
        raise ValueError(f"unexpected timestamp format: {value!r}")
    day, clock, fraction, hours, minutes = match.groups()
    naive = datetime.fromisoformat(f"{day}T{clock}{fraction or ''}")
    sign = -1 if hours.startswith("-") else 1
    offset = timedelta(hours=int(hours), minutes=sign * int(minutes or 0))
    return (naive - offset).replace(tzinfo=UTC)


def copy_rows(lines: Iterable[str]) -> Iterable[dict[str, str]]:
    """Zeilen eines COPY-Blocks als Dicts; Spaltennamen aus dem COPY-Kopf."""
    columns: list[str] | None = None
    for raw in lines:
        line = raw.rstrip("\n")
        if columns is None:
            match = _COPY.match(line)
            if match:
                columns = [name.strip().strip('"') for name in match.group("cols").split(",")]
            continue
        if line == "\\.":
            columns = None
            continue
        values = line.split("\t")
        if len(values) == len(columns):
            yield dict(zip(columns, values, strict=True))


def trigger_minutes_by_kind(lines: Iterable[str], symbol: str = SYMBOL) -> dict[str, list[datetime]]:
    """Signalminuten pro Signaltyp aus ``orderflow_observations``."""
    found: dict[str, set[datetime]] = {}
    for row in copy_rows(lines):
        if row.get("symbol") != symbol:
            continue
        minute = parse_timestamp(row["observed_at"]).replace(second=0, microsecond=0)
        found.setdefault(row["kind"], set()).add(minute)
    return {kind: sorted(values) for kind, values in sorted(found.items())}


def minute_bars(lines: Iterable[str], symbol: str = SYMBOL) -> list[sk.MinuteBar]:
    """Geschlossene 1-Minuten-Kerzen aus ``candles``.

    Das Handelsvolumen in USDT wird als Schlusskurs mal Basisvolumen
    angenähert (die Tabelle speichert nur das Basisvolumen); so steht es
    auch in der Spezifikation.
    """
    bars: list[sk.MinuteBar] = []
    for row in copy_rows(lines):
        if row.get("symbol") != symbol or row.get("timeframe") != "1m" or row.get("closed", "t") != "t":
            continue
        close = float(row["close"])
        bars.append(sk.MinuteBar(
            open_time=parse_timestamp(row["open_time"]),
            close=close,
            quote_volume=close * float(row["volume"]),
        ))
    return bars


def _unit(kind: str, sample_class: str, start: datetime, spec: Mapping[str, Any]) -> CanonicalIndependentUnit:
    stamp = iso(start)
    uid = f"{sample_class}:{kind}:{stamp}"
    return CanonicalIndependentUnit(
        unit_id=uid,
        start_utc=start,
        end_utc=start + timedelta(minutes=int(spec["window_minutes"])),
        source_window=f"{kind}:{stamp}",
        data_complete=True,
        gap_exposure=False,
        observation_id=None,
        label=NOT_EVALUATED,
        sample_class=sample_class,
        volatility_regime=sk.UNASSIGNED,
        liquidity_regime=sk.UNASSIGNED,
        session=sk.UNASSIGNED,
        weekday=sk.UNASSIGNED,
        trend_regime=sk.UNASSIGNED,
        reviewer_id=None,
        provenance=PROVENANCE,
        input_hash=hashlib.sha256(f"{spec['spec_hash']}|{uid}".encode()).hexdigest(),
    )


def positive_starts(
    triggers: Iterable[datetime],
    bars: Mapping[datetime, sk.MinuteBar],
    *,
    t0: datetime,
    study_end: datetime,
    spec: Mapping[str, Any],
) -> tuple[list[datetime], int]:
    """Gierig nicht überlappende Positivfenster ab T0, wie die Fallprüfung der Kampagne.

    Zuerst werden nur Signale mit vollständigem Fenster und Rückblick
    zugelassen, dann wird gierig ausgewählt. Gibt (Starts, verworfene Signale) zurück.
    """
    window = int(spec["window_minutes"])
    lookback = int(spec["lookback_minutes"])
    eligible: list[datetime] = []
    dropped = 0
    for start in sorted(set(triggers)):
        if start < t0 or start + window * sk.MINUTE > study_end:
            continue
        complete = all(start + i * sk.MINUTE in bars for i in range(window))
        if complete and sk.lookback_bars(bars, start, lookback) is not None:
            eligible.append(start)
        else:
            dropped += 1
    selected: list[datetime] = []
    next_allowed: datetime | None = None
    for start in eligible:
        if next_allowed is None or start >= next_allowed:
            selected.append(start)
            next_allowed = start + window * sk.MINUTE
    return selected, dropped


def study_status(
    *,
    triggers_by_kind: Mapping[str, Iterable[datetime]],
    bars: Iterable[sk.MinuteBar],
    thresholds: Mapping[str, Any],
    t0: datetime,
    study_end: datetime,
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    """Zwischenstand pro Signaltyp: Anzahl je Klasse, Regimeabdeckung, Abnahme.

    Liest keine Ergebnisse. ``gate_status`` PASS heißt nur: genug saubere
    Fenster für die Auswertung, nicht: Signal wirkt.
    """
    sk.verify_spec(spec)
    sk.verify_thresholds(thresholds, spec)
    bar_list = list(bars)
    lookup = {bar.open_time.astimezone(UTC): bar for bar in bar_list}
    t0 = t0.astimezone(UTC)
    study_end = study_end.astimezone(UTC)
    kinds: dict[str, Any] = {}
    for kind, raw in sorted(triggers_by_kind.items()):
        triggers = sorted(set(raw))
        starts, dropped = positive_starts(triggers, lookup, t0=t0, study_end=study_end, spec=spec)
        controls = sk.build_controls(
            detector_kind=kind, bars=bar_list, trigger_minutes=triggers, t0=t0, study_end=study_end, spec=spec,
        )
        units = [_unit(kind, "POSITIVE", start, spec) for start in starts]
        for control in controls["controls"]:
            start = datetime.fromisoformat(control["start_utc"].replace("Z", "+00:00"))
            units.append(_unit(kind, control["sample_class"], start, spec))
        regimed = sk.with_regimes(units, bar_list, thresholds, spec)
        check = sk.validate_study(
            regimed["units"], detector_kind=kind, trigger_minutes=triggers, t0=t0, study_end=study_end, spec=spec,
        )
        kinds[kind] = {
            "sample_class_counts": check["sample_class_counts"],
            "regime_coverage": check["regime_coverage"],
            "positive_triggers_dropped_incomplete_data": dropped,
            "grid_cells_skipped_incomplete": controls["grid_cells_skipped_incomplete"],
            "excluded_incomplete_lookback": len(regimed["excluded_incomplete_lookback"]),
            "gate_status": check["gate_status"],
            "reasons": check["reasons"],
        }
    return {
        "study_id": sk.STUDY_ID,
        "spec_hash": spec["spec_hash"],
        "thresholds_hash": thresholds["thresholds_hash"],
        "t0_utc": iso(t0),
        "study_end_utc": iso(study_end),
        "outcomes_read": False,
        "kinds": kinds,
    }
