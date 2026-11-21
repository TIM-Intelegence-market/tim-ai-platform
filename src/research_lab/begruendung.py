"""Begründung je Plan (TIM-Gehirn G3): welche Gedächtnis-Aussagen standen hinter einem Plan.

Nur eine Notiz am Journaleintrag. Sie ändert keinen Plan, keine Regel und keinen Score. Die Aussagen
(``docs/research_lab/gedaechtnis/aussagen.jsonl``) werden anhand dessen gewählt, was im Plan tatsächlich vorkommt
(Grade, Score, GARCH-Feld, Stopp-Regel, Ziele). Gespeichert wird der Stand der Aussage zum Zeitpunkt des Plans, damit der
Fehlerfinder (G4) später sieht, ob ein Plan sich auf Widerlegtes oder Ungeprüftes stützte.

Seit 17.11. kommen Aussagen dazu, die nur bei diesem Plan zutreffen (Feld ``rolle``): ``gegen_trend`` (C38, Plan
läuft gegen TIMs Marktzustand) und ``schatten`` (C09 Absorption, C11 Open Interest, C32 Funding: der Baustein hat im
Schatten-Score gewirkt, ``richtung`` dafuer/dagegen). Sie haben nichts entschieden. Einträge ohne ``rolle`` sind die
feste Grundlage, die bei jedem Plan gleich ist.

Pflicht: ein Fehler hier darf das Journal nie stoppen. ``fuer_plan`` liefert im Zweifel eine leere Liste.
"""
from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from src.research_lab import gedaechtnis

# Aussage -> Bedingung am Plan. Reihenfolge = Reihenfolge in der Notiz.
_IMMER = ("C01", "C02", "C03", "C07", "C08", "C49", "C37")


def _wirkt(plan: Mapping[str, Any]) -> list[str]:
    ids = [i for i in _IMMER]
    if plan.get("setup_grade") is not None or plan.get("grade"):
        ids.append("C46")
    if plan.get("score") is not None:
        ids.append("C47")
    if plan.get("vol_4h"):
        ids += ["C21", "C22"]
    return ids


# Bausteine des Schatten-Scores -> Aussage. Nur was eindeutig zu einer Aussage gehört; die aggressive Seite und
# die gezählten Belege haben keine einzelne Aussage und werden über ``gedaechtnis_fehler.bausteine`` ausgewertet.
_SCHATTEN = (("absorption", "C09"), ("oi", "C11"), ("positionierung", "C32"))
_GEGEN_TREND = {"LONG": "TREND_DOWN", "SHORT": "TREND_UP"}  # wie plan_journal.AGAINST_TREND


def _je_plan(plan: Mapping[str, Any]) -> list[tuple[str, dict[str, str]]]:
    """Aussagen, die nur bei diesem Plan zutreffen. Sie haben nichts entschieden (``rolle``), unterscheiden
    aber die Pläne, sodass die Ergebnistabelle je Aussage etwas trennen kann."""
    out: list[tuple[str, dict[str, str]]] = []
    if _GEGEN_TREND.get(str(plan.get("direction"))) == str(plan.get("market_state")):
        out.append(("C38", {"rolle": "gegen_trend"}))
    schatten = plan.get("score_schatten")
    teile = schatten.get("parts") if isinstance(schatten, Mapping) else None
    if isinstance(teile, Mapping):
        for name, kennung in _SCHATTEN:
            wert = teile.get(name)
            if isinstance(wert, (int, float)) and not isinstance(wert, bool) and wert:
                out.append((kennung, {"rolle": "schatten", "richtung": "dafuer" if wert > 0 else "dagegen"}))
    return out


@lru_cache(maxsize=1)
def _register() -> dict[str, dict]:
    return {a["id"]: a for a in gedaechtnis.laden()}


def fuer_plan(plan: Mapping[str, Any]) -> list[dict[str, str]]:
    """``[{"id", "status", "nutzung"}]`` der Aussagen, auf die sich dieser Plan stützt."""
    try:
        register = _register()
        fest = [{"id": i, "status": register[i]["status"], "nutzung": register[i]["nutzung"]}
                for i in _wirkt(plan) if i in register]
        schon = {b["id"] for b in fest}
        je_plan = [{"id": i, "status": register[i]["status"], "nutzung": register[i]["nutzung"], **extra}
                   for i, extra in _je_plan(plan) if i in register and i not in schon]
        return fest + je_plan
    except Exception:  # noqa: BLE001 - Notiz darf das Journal nie stoppen
        return []
