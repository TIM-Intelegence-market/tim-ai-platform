"""Influence report: one section per driver plus the joint view, as Markdown and as JSON.

The JSON is what the barometer and the assignment (``zuordnung``) read instead of fixed numbers.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

from src.research_lab.forward.macro_filters import Series
from src.research_lab.influence import analysis
from src.research_lab.influence.catalog import DRIVERS, Driver
from src.research_lab.influence.states import driver_weeks, weeks

SCHEMA = "tim_influence_report/1"
JOINT_MIN_COVERAGE = 0.8  # a driver enters the joint view only with weekly values in 80 % of the BTC weeks


def build(data: Mapping[str, Series], btc: Mapping[date, float], *, now: datetime,
          drivers: Sequence[Driver] = DRIVERS, inputs: Mapping[str, str] | None = None) -> dict:
    grid = weeks()
    rows = {d.key: driver_weeks(d, data, grid) for d in drivers}
    per_driver = {}
    for d in drivers:
        info = analysis.describe(rows[d.key], btc)
        coverage = sum(1 for r in rows[d.key] if r.change_week is not None and r.week in btc) / max(1, len(btc))
        per_driver[d.key] = {"label": d.label, "familie": d.family, "einheit": d.change, "revidiert": d.revised,
                             "braucht_vorlauf": d.needs_lead, "hinweis": d.note, "abdeckung": coverage, **info}
    # crypto-internal series (dominance holds the BTC price itself) stay out of the joint view (5b)
    in_joint = [d.key for d in drivers if not d.needs_lead and per_driver[d.key]["abdeckung"] >= JOINT_MIN_COVERAGE]
    joint = analysis.joint({k: rows[k] for k in in_joint}, btc)
    joint["treiber"] = in_joint
    joint["ausgelassen"] = [d.key for d in drivers if d.key not in in_joint and not d.needs_lead]
    joint["krypto_getrennt"] = [d.key for d in drivers if d.needs_lead]
    return {"schema": SCHEMA, "erstellt_utc": now.replace(microsecond=0).isoformat(),
            "btc_wochen": len(btc), "erste_woche": grid[0].isoformat(), "letzte_woche": grid[-1].isoformat(),
            "angeschaute_treiber": len(drivers), "eingaben_sha256": dict(inputs or {}),
            "treiber": per_driver, "gemeinsam": joint}


def history_for_barometer(report: Mapping) -> dict[str, dict[str, float | None]]:
    """The three numbers the barometer shows per driver, keyed like macro_filters.HISTORY."""
    out = {}
    for key, info in report["treiber"].items():
        out[key] = {"gestiegen": info["zustaende"]["gestiegen"]["btc_woche_mittel"],
                    "gefallen": info["zustaende"]["gefallen"]["btc_woche_mittel"],
                    "vorlauf": info["vorlauf_13w_auf_4w"]}
    return out


def _f(value: float | None, digits: int = 2, sign: bool = True) -> str:
    if value is None:
        return "–"
    return f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"


def markdown(report: Mapping) -> str:
    lines = [f"# Einfluss-Auswertung (Stand {report['erstellt_utc']})", "",
             ("Rein beschreibend, keine Prognose, kein Handelssignal. BTC-Wochen "
              f"{report['erste_woche']} bis {report['letzte_woche']} ({report['btc_wochen']} Wochen), keine Daten ab "
              f"2025-01-01. Angeschaut: {report['angeschaute_treiber']} Treiber. Wer daraus eine Regel macht, nennt diese "
              "Zahl in der Werkstatt (Mehrfachtests)."), "",
             ("Die 13-Wochen-Zustände überlappen sich: „unabhängig“ ist grob Wochen geteilt durch 13. Gleichlauf und "
              "Vor-/Nachlauf sind Korrelationen der Wochenänderung des Treibers mit der BTC-Wochenrendite."), "",
             ("| Treiber | BTC/Woche nach „gestiegen“ (unabh.) | nach „gefallen“ (unabh.) | Gleichlauf | bester Vorlauf | "
              "bester Nachlauf | 52W min…max | gleiches Vorzeichen | Hinweis |"),
             "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for key, t in report["treiber"].items():
        up, down = t["zustaende"]["gestiegen"], t["zustaende"]["gefallen"]
        lead = max(((k, v) for k, v in t["vorlauf_wochen"].items() if v is not None), key=lambda kv: abs(kv[1]), default=None)
        lag = max(((k, v) for k, v in t["nachlauf_wochen"].items() if v is not None), key=lambda kv: abs(kv[1]), default=None)
        roll = t["rollierend_52w"]
        notes = [t["hinweis"]] if t["hinweis"] else []
        if t["revidiert"]:
            notes.append("letzte Werte, nicht Point-in-Time")
        if t["folgt_dem_kurs"]:
            notes.append("folgt eher dem Kurs" + (" (Krypto: kein Treiber ohne Vorlauf)" if t["braucht_vorlauf"] else ""))
        if t["abdeckung"] < JOINT_MIN_COVERAGE:
            notes.append(f"Abdeckung {t['abdeckung']:.0%}")
        lines.append(
            f"| {t['label']} | {_f(up['btc_woche_mittel'])} % ({up['n_unabhaengig']}) | {_f(down['btc_woche_mittel'])} % "
            f"({down['n_unabhaengig']}) | {_f(t['gleichlauf'])} | {'–' if lead is None else f'{lead[1]:+.2f} ({lead[0]} W)'} | "
            f"{'–' if lag is None else f'{lag[1]:+.2f} ({lag[0]} W)'} | {_f(roll['min'])}…{_f(roll['max'])} | "
            f"{'–' if roll['anteil_gleiches_vorzeichen'] is None else f'{roll['anteil_gleiches_vorzeichen']:.0%}'} | "
            f"{'; '.join(notes)} |")
    j = report["gemeinsam"]
    lines += ["", "## Alle Treiber gemeinsam", ""]
    if j.get("ergebnis") is None:
        lines.append(f"Nicht berechenbar ({j['wochen']} gemeinsame Wochen).")
    else:
        res = j["ergebnis"]
        lines += [(f"Wochen {j['von']} bis {j['bis']} ({j['wochen']}), R² = {res['r2']:.3f}: Anteil der Schwankung der "
                   "BTC-Wochenrendite, der mit den Wochenänderungen aller Treiber zusammen gleichläuft. "
                   "Beitrag = um wie viel R² sinkt, wenn man den Treiber weglässt (was er allein beiträgt)."), "",
                  "| Treiber | Koeffizient (standardisiert) | Beitrag zu R² |", "|---|---:|---:|"]
        for key in j["treiber"]:
            lines.append(f"| {report['treiber'][key]['label']} | {_f(res['beta_std'][key])} | "
                         f"{_f(res['r2_beitrag'][key], 3, sign=False)} |")
        if j["ausgelassen"]:
            lines += ["", "Nicht in der gemeinsamen Rechnung (zu kurze Historie): "
                      + ", ".join(report["treiber"][k]["label"] for k in j["ausgelassen"]) + "."]
    if j.get("krypto_getrennt"):
        lines += ["", "Krypto-interne Reihen nur einzeln, nicht in der gemeinsamen Rechnung (sie enthalten den BTC-Kurs selbst): "
                  + ", ".join(report["treiber"][k]["label"] for k in j["krypto_getrennt"]) + "."]
    lines += ["", "## Je Jahr (Gleichlauf)", "", "| Treiber | " + " | ".join(str(y) for y in _years(report)) + " |",
              "|---|" + "---:|" * len(_years(report))]
    for t in report["treiber"].values():
        lines.append(f"| {t['label']} | " + " | ".join(_f(t["je_jahr"].get(str(y), t["je_jahr"].get(y)))
                                                         for y in _years(report)) + " |")
    lines += ["", "„Warum“ zeigt diese Tabelle nicht: Gleichlauf und Vorlauf sind Hinweise, kein Beweis für Ursache und Wirkung."]
    return "\n".join(lines) + "\n"


def _years(report: Mapping) -> list[int]:
    first = next(iter(report["treiber"].values()), {"je_jahr": {}})
    return sorted(int(y) for y in first["je_jahr"])


def write(report: Mapping, folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = report["erstellt_utc"][:10]
    js, md = folder / f"einfluss_{stamp}.json", folder / f"einfluss_{stamp}.md"
    js.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    md.write_text(markdown(report))
    return js, md
