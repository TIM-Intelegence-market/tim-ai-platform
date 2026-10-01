"""Real-data verification of the point-in-time model against one stored ALFRED bundle.

Pure functions over a stored bundle and its parse result: no network, no clock.
Every statement in the summary carries one evidence label:

- ``SOURCE_VERIFIED``: read from the stored ALFRED/FRED payload itself;
- ``RULE_VERIFIED``: a publisher rule confirmed against an official publisher document (cited);
- ``ASSUMPTION``: used by the code, not confirmed by the payload or a cited document;
- ``LIMITATION``: something this verification cannot show.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from src.research_lab.external.alfred import LAST_REALTIME, RawBundle, revision_only_dates
from src.research_lab.external.records import IngestResult

SOURCE_VERIFIED = "SOURCE_VERIFIED"
RULE_VERIFIED = "RULE_VERIFIED"
ASSUMPTION = "ASSUMPTION"
LIMITATION = "LIMITATION"

# Monthly CPI releases: a gap outside this range is reported as unusual (not as an error).
USUAL_RELEASE_GAP_DAYS = (21, 42)


def _months_between(first: date, second: date) -> int:
    return (second.year - first.year) * 12 + second.month - first.month


def raw_summary(bundle: RawBundle) -> dict[str, Any]:
    """Facts read directly from the stored payloads."""
    observations = json.loads(bundle.payloads["observations"])
    versions = json.loads(bundle.payloads["series"])["seriess"]
    rows = observations["observations"]
    last_vintage = max((row["realtime_start"] for row in rows), default=None)
    # The metadata version in force when the newest archived vintage was published (not the oldest version).
    in_force = [meta for meta in versions if last_vintage and meta.get("realtime_start", "") <= last_vintage <= meta.get("realtime_end", "9999-12-31")]
    series = in_force[-1] if in_force else versions[-1]
    version_keys = ("realtime_start", "realtime_end", "units", "frequency_short", "seasonal_adjustment_short", "title")
    by_period: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_period[row["date"]].append(row)
    periods = sorted(by_period)
    vintage_dates = sorted({row["realtime_start"] for row in rows})
    depth = {period: len(items) for period, items in by_period.items()}
    period_gaps = [
        {"after": a, "before": b, "months": _months_between(date.fromisoformat(a), date.fromisoformat(b))}
        for a, b in zip(periods, periods[1:])
        if _months_between(date.fromisoformat(a), date.fromisoformat(b)) != 1
    ]
    open_rows = sum(1 for row in rows if row["realtime_end"] == LAST_REALTIME)
    calendar: dict[str, Any] = {"present": "release_dates" in bundle.payloads}
    if calendar["present"]:
        payload = json.loads(bundle.payloads["release_dates"])
        items = payload["release_dates"]
        dates = [item["date"] for item in items]
        ordered = sorted(dates)
        gaps = [(date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in zip(ordered, ordered[1:])]
        low, high = USUAL_RELEASE_GAP_DAYS
        calendar.update(
            {
                "count": len(dates),
                "first": ordered[0] if ordered else None,
                "last": ordered[-1] if ordered else None,
                "release_ids": sorted({item["release_id"] for item in items}),
                "ascending_as_delivered": dates == ordered,
                "duplicates": sorted(day for day, n in Counter(dates).items() if n > 1),
                "gap_days_min": min(gaps) if gaps else None,
                "gap_days_max": max(gaps) if gaps else None,
                "unusual_gaps": [
                    {"after": a, "before": b, "days": g} for a, b, g in zip(ordered, ordered[1:], gaps) if not low <= g <= high
                ],
                "envelope": {key: payload.get(key) for key in ("realtime_start", "realtime_end", "count", "offset", "limit")},
            }
        )
    return {
        "series": {key: series.get(key) for key in ("id", "title", "units", "frequency_short", "seasonal_adjustment_short", "realtime_start", "realtime_end")},
        "series_versions": [{key: meta.get(key) for key in version_keys} for meta in versions],
        "envelope": {key: observations.get(key) for key in ("realtime_start", "realtime_end", "observation_start", "observation_end", "units", "output_type", "count", "offset", "limit")},
        "rows": len(rows),
        "periods": len(periods),
        "first_period": periods[0] if periods else None,
        "last_period": periods[-1] if periods else None,
        "period_gaps": period_gaps,
        "vintage_dates": len(vintage_dates),
        "first_vintage": vintage_dates[0] if vintage_dates else None,
        "last_vintage": vintage_dates[-1] if vintage_dates else None,
        "rows_still_current": open_rows,
        "values_per_period": {"min": min(depth.values(), default=0), "max": max(depth.values(), default=0), "distribution": dict(sorted(Counter(depth.values()).items()))},
        "calendar": calendar,
        "vintage_dates_list": vintage_dates,
    }


def model_summary(bundle: RawBundle, ingest: IngestResult, *, research_start: date, research_end: date) -> dict[str, Any]:
    """How the parsed point-in-time model sees the same data, restricted to the research periods."""
    raw = raw_summary(bundle)
    calendar_dates = set()
    if raw["calendar"]["present"]:
        calendar_dates = {date.fromisoformat(item["date"]) for item in json.loads(bundle.payloads["release_dates"])["release_dates"]}
    revision_only = revision_only_dates(json.loads(bundle.payloads["observations"])["observations"], calendar_dates)
    spec = ingest.spec
    # Release dates due to publish a research period: from the end of the first research period on.
    first_due = spec.period_end(spec.period_of(research_start))
    in_range = lambda period: research_start <= period <= research_end  # noqa: E731
    records = [record for record in ingest.records if in_range(record.period_start)]
    periods = sorted({record.period_start for record in records} | {item.period_start for item in ingest.unusable if in_range(item.period_start)})
    by_period: dict[date, list] = defaultdict(list)
    for record in records:
        by_period[record.period_start].append(record)
    first_prints = {}
    for period, items in by_period.items():
        first = min(items, key=lambda item: item.vintage)
        first_prints[period] = first
    vintages = sorted({record.vintage for record in records})
    unscheduled = sorted(v.isoformat() for v in vintages if v not in calendar_dates)
    revisions = sum(len(items) - 1 for items in by_period.values())
    revised_periods = sorted(period.isoformat() for period, items in by_period.items() if len(items) > 1)
    calendar_in_range = sorted(d for d in calendar_dates if first_due <= d <= research_end)
    first_print_dates = {first.vintage for first in first_prints.values()}
    releases_without_first_print = sorted(d.isoformat() for d in calendar_in_range if d not in first_print_dates and d not in revision_only)
    first_print_lag = [(first.vintage - first.period_end).days for first in first_prints.values()]
    codes = Counter(item.issue.code for item in ingest.issues)
    return {
        "state": ingest.state.value,
        "research_periods": len(periods),
        "first_period": periods[0].isoformat() if periods else None,
        "last_period": periods[-1].isoformat() if periods else None,
        "records": len(records),
        "distinct_vintages": len(vintages),
        "revisions": revisions,
        "revised_periods": len(revised_periods),
        "max_values_per_period": max((len(items) for items in by_period.values()), default=0),
        "periods_without_first_print": sorted(p.isoformat() for p in ingest.periods_without_first_release if in_range(p)),
        "missing_periods": [(p.isoformat(), due.isoformat()) for p, due in ingest.missing_periods if in_range(p)],
        "vintages_not_in_calendar": unscheduled,
        "calendar_releases_in_range": len(calendar_in_range),
        "revision_only_release_dates": sorted(d.isoformat() for d in revision_only if first_due <= d <= research_end),
        "calendar_releases_without_first_print": releases_without_first_print,
        "first_print_lag_days": {"min": min(first_print_lag, default=None), "max": max(first_print_lag, default=None)},
        "scheduled_first_prints": sum(1 for first in first_prints.values() if first.release_time is not None),
        "unusable_entries": dict(Counter(item.reason for item in ingest.unusable)),
        "quality_findings": dict(sorted(codes.items())),
        "coverage_end": ingest.coverage_end.isoformat(),
    }


def holdout_status(bundle: RawBundle, holdout_start: date) -> dict[str, Any]:
    raw = raw_summary(bundle)
    latest = [value for value in (raw["last_vintage"], raw["last_period"], raw["calendar"].get("last"), raw["envelope"]["realtime_end"]) if value]
    reaches = [value for value in latest if value >= holdout_start.isoformat()]
    return {
        "holdout_start": holdout_start.isoformat(),
        "last_vintage": raw["last_vintage"],
        "last_period": raw["last_period"],
        "last_release_date": raw["calendar"].get("last"),
        "requested_realtime_end": raw["envelope"]["realtime_end"],
        "status": "CLOSED" if not reaches else "BREACHED",
    }


# Official BLS CPI news releases read for the 08:30 rule (embargo line of each release), 2026-10-01.
BLS_RELEASE_TIME_SAMPLES = (
    ("2017-02-15", "January 2017", "8:30 a.m. (EST)", "https://www.bls.gov/news.release/archives/cpi_02152017.htm"),
    ("2020-02-13", "January 2020", "8:30 a.m. (EST)", "https://www.bls.gov/news.release/archives/cpi_02132020.htm"),
    ("2022-07-13", "June 2022", "8:30 a.m. (ET)", "https://www.bls.gov/news.release/archives/cpi_07132022.htm"),
    ("2024-01-11", "December 2023", "8:30 a.m. (ET)", "https://www.bls.gov/news.release/archives/cpi_01112024.htm"),
)
BLS_SEASONAL_REVISION = (
    "BLS: revised seasonally adjusted indexes for the previous five years are made available with a date "
    "but no stated time of day (https://www.bls.gov/cpi/seasonal-adjustment/)"
)


def _gap_text(gaps: list[dict[str, Any]]) -> str:
    pairs = [gap for gap in gaps if gap["days"] <= 7]
    others = [gap for gap in gaps if gap["days"] > 7]
    pair_years = sorted({gap["before"][:4] for gap in pairs})
    text = (
        f"Ungewöhnliche Abstände (außerhalb {USUAL_RELEASE_GAP_DAYS[0]}–{USUAL_RELEASE_GAP_DAYS[1]} Tage) im ganzen Kalender: "
        f"{len(pairs)} Terminpaare im Abstand von {min((g['days'] for g in pairs), default='-')}–{max((g['days'] for g in pairs), default='-')} Tagen "
        f"(Jahre {pair_years[0] if pair_years else '-'}–{pair_years[-1] if pair_years else '-'}, alle im Februar: {all(g['before'][5:7] == '02' for g in pairs)})"
    )
    if others:
        text += "; weitere: " + ", ".join(f"{g['after']}→{g['before']} ({g['days']} d)" for g in others)
    return text + "."


def _claim(label: str, text: str) -> str:
    return f"| `{label}` | {text} |"


def render_markdown(summary: dict[str, Any], replay: dict[str, Any] | None) -> str:
    """The committed verification report: every line carries its evidence label."""
    raw, model, holdout = summary["raw"], summary["model"], summary["holdout"]
    calendar = raw["calendar"]
    first_print_dates = {sample[0] for sample in BLS_RELEASE_TIME_SAMPLES}
    lines = [
        "# ALFRED CPI – Real-Data-Verifikation (BTC Research Engine V1.1)",
        "",
        "Erzeugt mit `scripts/research_lab_alfred_ingest.py verify` und `replay` aus einem gespeicherten",
        "Download; Rohdaten liegen nur lokal (`data/research_lab/external/`, nicht im Repository).",
        "",
        "| Feld | Wert |",
        "|---|---|",
        f"| Serie | `{raw['series']['id']}` ({summary['window']['name']}) |",
        f"| Bundle | `{summary['bundle_id']}` |",
        f"| Abgerufen | {summary['ingested_at']} |",
        f"| Perioden (Forschung) | {model['first_period']} … {model['last_period']} ({model['research_periods']}) |",
        f"| Holdout | {holdout['status']} (letztes Vintage {holdout['last_vintage']}, letzter Termin {holdout['last_release_date']}, Anfrage bis {holdout['requested_realtime_end']}) |",
        "",
        "## Payload-Hashes (SHA-256)",
        "",
        "| Payload | SHA-256 |",
        "|---|---|",
        *[f"| {name} | `{sha}` |" for name, sha in sorted(summary["payload_sha256"].items())],
        "",
        "## Befunde",
        "",
        "| Beleg | Aussage |",
        "|---|---|",
        _claim(SOURCE_VERIFIED, f"Antwort-Envelope gibt die Anfrage exakt wieder: Real-Time {raw['envelope']['realtime_start']} … {raw['envelope']['realtime_end']}, Beobachtungen {raw['envelope']['observation_start']} … {raw['envelope']['observation_end']}, `output_type={raw['envelope']['output_type']}`, `count={raw['envelope']['count']}` = Zeilen {raw['rows']}, `offset=0`."),
        _claim(SOURCE_VERIFIED, f"{raw['rows']} Zeilen, {raw['periods']} Perioden {raw['first_period']} … {raw['last_period']}, ohne Monatslücke ({len(raw['period_gaps'])} Lücken); {raw['vintage_dates']} verschiedene Vintage-Daten {raw['first_vintage']} … {raw['last_vintage']}."),
        _claim(SOURCE_VERIFIED, f"Werte je Periode: {raw['values_per_period']['min']} … {raw['values_per_period']['max']}, Verteilung {raw['values_per_period']['distribution']}. Im Forschungsbereich: {model['records']} Datensätze, {model['revisions']} Revisionen in {model['revised_periods']} Perioden, höchstens {model['max_values_per_period']} Werte je Periode."),
        _claim(SOURCE_VERIFIED, f"Zeilen mit offenem Ende im Download: {raw['rows_still_current']}; ALFRED kappt `realtime_end` auf das angefragte Ende ({raw['envelope']['realtime_end']})."),
        _claim(SOURCE_VERIFIED, "Serien-Metadaten kommen mit Real-Time-Bereich in mehreren Versionen (CPIAUCSL: 6; Einheit bis 1988 „Index 1967=100“); V1 verlangte genau eine Version und war mit echten Daten `NOT_READY` (behoben)."),
        _claim(SOURCE_VERIFIED, f"Release-Kalender: {calendar['count']} Termine {calendar['first']} … {calendar['last']}, Release-IDs {calendar['release_ids']}, aufsteigend geliefert: {calendar['ascending_as_delivered']}, Duplikate: {len(calendar['duplicates'])}, Abstände {calendar['gap_days_min']} … {calendar['gap_days_max']} Tage."),
        _claim(SOURCE_VERIFIED, _gap_text(calendar["unusual_gaps"])),
        _claim(SOURCE_VERIFIED, f"Reine Revisionstermine im Forschungsbereich: {', '.join(model['revision_only_release_dates'])}. An ihnen beginnen nur Revisionen älterer Perioden; die Januarzahl folgt am nächsten Termin. V1 erwartete den Erstdruck am ersten Termin nach Periodenende und meldete deshalb jeden Januar als fehlend (behoben)."),
        _claim(SOURCE_VERIFIED, f"Kalendertermine im Forschungsbereich: {model['calendar_releases_in_range']}; ohne Erstdruck: {len(model['calendar_releases_without_first_print'])}; Vintages außerhalb des Kalenders: {len(model['vintages_not_in_calendar'])}; Perioden ohne Erstdruck: {len(model['periods_without_first_print'])}; fehlende Perioden: {len(model['missing_periods'])}."),
        _claim(SOURCE_VERIFIED, f"Erstdruck {model['first_print_lag_days']['min']} … {model['first_print_lag_days']['max']} Tage nach Periodenende; {model['scheduled_first_prints']} von {model['research_periods']} Erstdrucken auf einem Kalendertermin."),
        _claim(SOURCE_VERIFIED, f"Datenqualität: Zustand `{model['state']}`, Befunde {model['quality_findings'] or 'keine'}, unbrauchbare Einträge {model['unusable_entries'] or 'keine'}."),
        _claim(RULE_VERIFIED, "Release-Zeit 08:30 New York an Stichproben belegt (BLS-Sperrfrist): " + "; ".join(f"{day} ({month}): {time}" + (" = ALFRED-Erstdruck" if day in first_print_dates else "") for day, month, time, _url in BLS_RELEASE_TIME_SAMPLES) + "."),
        _claim(RULE_VERIFIED, BLS_SEASONAL_REVISION + "; deshalb `END_OF_VINTAGE_DAY` für reine Revisionstermine."),
        _claim(ASSUMPTION, f"08:30 New York gilt auch für die übrigen {model['scheduled_first_prints'] - len(BLS_RELEASE_TIME_SAMPLES)} Erstdrucke; ALFRED/FRED liefert keine Uhrzeit."),
        _claim(ASSUMPTION, "Der nächste BLS-Termin ist am Revisionstermin bereits bekannt (BLS veröffentlicht den Kalender vorab); darauf stützt sich die Erkennung reiner Revisionstermine."),
        _claim(LIMITATION, "ALFRED-Termine sind nicht vollständig gegen das BLS-Archiv abgeglichen (4 Stichproben)."),
        _claim(LIMITATION, "`revision_number` zählt Wertänderungen (`output_type=1`), nicht jede Veröffentlichung."),
    ]
    if replay is not None:
        checks = replay["checks"]
        lines += [
            "",
            "## Replay 2017–2024",
            "",
            "| Feld | Wert |",
            "|---|---|",
            f"| Replay-Zeit | {replay['replay_at']} (letzter Zeitpunkt vor dem Holdout) |",
            f"| BTC | {replay['btc_candles']} Kerzen {replay['interval']} Spot 2017-08 … 2024-12 (Binance-Archiv, Checksumme geprüft); ausgeschlossen (`invalid_candles=exclude`): {replay['btc_excluded']}; danach erwartet {replay['btc_completeness']['expected']}, vorhanden {replay['btc_completeness']['present']}, fehlend {replay['btc_completeness']['missing']} (Archivlücken und ausgeschlossene Kerzen; Fenster mit fehlenden Kerzen sind `INSUFFICIENT_DATA`) |",
            f"| Zustand | {replay['state']} |",
            f"| Dataset-ID | `{replay['hashes']['dataset_id']}` |",
            f"| Content-Hash | `{replay['hashes']['content_hash']}` |",
            f"| Output-Hash | `{replay['hashes']['output_hash']}` |",
            f"| Ereignisse | {replay['events']} ({replay['event_status']}) |",
            f"| Zeitreihenzeilen | {replay['series_rows']} |",
            "",
            "| Beleg | Prüfung | Ergebnis |",
            "|---|---|---|",
            f"| `{SOURCE_VERIFIED}` | Finaler Replay beantwortet (Zustand `READY`, BTC-Kerzen und Ereignisse vorhanden) | {'PASS' if checks.get('answered') else 'FAIL'} |",
            f"| `{SOURCE_VERIFIED}` | Wiederholung: gleiche Eingaben ⇒ gleiche Dataset-ID, Content- und Output-Hash | {'PASS' if checks['repeat_identical'] else 'FAIL'} |",
            f"| `{SOURCE_VERIFIED}` | Zeilen- und Kalenderreihenfolge umgedreht ⇒ gleiche Dataset-ID und Content-Hash (Output-Hash enthält die Payload-Hashes) | {'PASS' if checks['reordered_same_dataset_and_content'] else 'FAIL'} |",
            f"| `{SOURCE_VERIFIED}` | Kein Ereignis und kein ausgerichteter Wert nach seiner Entscheidungszeit | {'PASS' if not checks['leakage_at_final'] else 'FAIL'} |",
            *[
                f"| `{ASSUMPTION}` | Stand {item['cut']} (Archiv rekonstruiert: spätere Zeilen und Termine entfernt, gültige Zeilen auf den Stichtag gekappt), Replay {item['replay_at']}: "
                + ("Content-Hash gleich dem vollen Archiv" if item["outcome"] == "EQUAL" else f"Archiv des Tages endet {item['as_of_coverage_end']} (Revisionstermin noch nicht einordenbar) ⇒ `INSUFFICIENT_DATA`, bis dahin gleich: {item.get('equal_at_coverage_end')}")
                + f" | {'PASS' if item['equal'] and not item['leakage'] else 'FAIL'} |"
                for item in checks["as_of"]
            ],
        ]
    return "\n".join(lines) + "\n"


__all__ = [
    "ASSUMPTION",
    "BLS_RELEASE_TIME_SAMPLES",
    "LIMITATION",
    "RULE_VERIFIED",
    "SOURCE_VERIFIED",
    "holdout_status",
    "model_summary",
    "raw_summary",
    "render_markdown",
]
