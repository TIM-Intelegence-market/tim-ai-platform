"""Assignment driver -> BTC behaviour (EINFLUSS_BAROMETER.md section 5c).

For every driver: its 13-week state today (as published now), how BTC behaved in that state up to 2024
(from the influence report), how stable that was, and the scheduled events of the coming days with what is
known about BTC around them. Descriptive only: no signal, no rule, nothing a trade reads.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

from src.research_lab.forward.macro_filters import Series
from src.research_lab.influence.catalog import DRIVERS, Driver
from src.research_lab.influence.states import (
    TREND_WEEKS,
    change,
    driver_series,
    known_at,
)

AHEAD_DAYS = 7
# What the research lab has measured about BTC around a scheduled release, with its source. Kinds without an
# entry are shown as "noch nicht ausgewertet".
EVENT_HISTORY = {
    "CPI": "BTC-Spanne in der CPI-Stunde 1,40× einer normalen Stunde (S1, 2017–2024, n = 88; regimeabhängig)",
}


def current_state(driver: Driver, data: Mapping[str, Series], today: date) -> dict[str, Any]:
    series = driver_series(driver, data)
    now = known_at(series, today, driver)
    before = known_at(series, today - timedelta(weeks=TREND_WEEKS), driver)
    if now is None or before is None:
        return {"zustand": None}
    c = change(driver.change, before[1], now[1])
    state = None if c is None else "gestiegen" if c > 0 else "gefallen" if c < 0 else "gleich"
    return {"zustand": state, "stand": now[1], "stichtag": now[0].isoformat(), "veraenderung_13w": c}


def build(data: Mapping[str, Series], report: Mapping[str, Any], events: Sequence[Mapping[str, Any]],
          today: date, drivers: Sequence[Driver] = DRIVERS) -> dict[str, Any]:
    rows = []
    for d in drivers:
        now = current_state(d, data, today)
        hist = report.get("treiber", {}).get(d.key)
        row = {"key": d.key, "label": d.label, **now}
        if hist and now["zustand"] in ("gestiegen", "gefallen"):
            other = "gefallen" if now["zustand"] == "gestiegen" else "gestiegen"
            row.update(btc_so=hist["zustaende"][now["zustand"]]["btc_woche_mittel"],
                       btc_gegenrichtung=hist["zustaende"][other]["btc_woche_mittel"],
                       unabhaengig=hist["zustaende"][now["zustand"]]["n_unabhaengig"],
                       stabil=hist["rollierend_52w"]["anteil_gleiches_vorzeichen"],
                       folgt_dem_kurs=hist["folgt_dem_kurs"])
        joint = (report.get("gemeinsam") or {}).get("ergebnis") or {}
        row["r2_beitrag"] = (joint.get("r2_beitrag") or {}).get(d.key)
        rows.append(row)
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    upcoming = [{"kind": e["kind"], "time": e["time"], "label": e.get("label", e["kind"]),
                 "historisch": EVENT_HISTORY.get(e["kind"], "noch nicht ausgewertet")}
                for e in events if start <= _time(e) < start + timedelta(days=AHEAD_DAYS)]
    return {"stand": today.isoformat(), "bericht": report.get("erstellt_utc"), "treiber": rows, "termine": upcoming}


def _time(event: Mapping[str, Any]) -> datetime:
    value = event["time"]
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _p(value: float | None) -> str:
    return "–" if value is None else f"{value:+.2f} %"


def markdown(result: Mapping[str, Any]) -> str:
    lines = [f"# Treiber und BTC, Stand {result['stand']}", "",
             (f"Rein beschreibend, kein Handelssignal. Historie aus der Einfluss-Auswertung vom {result['bericht'] or '–'} "
              "(BTC bis 2024). „Stabil“ = Anteil der 52-Wochen-Fenster, in denen der Gleichlauf dasselbe Vorzeichen hatte."), "",
             "| Treiber | Zustand 13 W | BTC/Woche früher so (unabh.) | … Gegenrichtung | stabil | Beitrag R² | Hinweis |",
             "|---|---|---:|---:|---:|---:|---|"]
    for r in result["treiber"]:
        state = r.get("zustand") or "unbekannt"
        note = "folgt eher dem Kurs" if r.get("folgt_dem_kurs") else ""
        stable = "–" if r.get("stabil") is None else f"{r['stabil']:.0%}"
        contrib = "–" if r.get("r2_beitrag") is None else f"{r['r2_beitrag']:.3f}"
        unab = f" ({r['unabhaengig']})" if "unabhaengig" in r else ""
        lines.append(f"| {r['label']} | {state} | {_p(r.get('btc_so'))}{unab} | {_p(r.get('btc_gegenrichtung'))} | "
                     f"{stable} | {contrib} | {note} |")
    lines += ["", f"## Termine der nächsten {AHEAD_DAYS} Tage", ""]
    if not result["termine"]:
        lines.append("Keine Termine im Kalender.")
    for e in result["termine"]:
        lines.append(f"- {e['time']}: {e['label']}. Früher: {e['historisch']}.")
    return "\n".join(lines) + "\n"
