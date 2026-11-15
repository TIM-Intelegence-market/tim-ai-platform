"""Begründung je Plan (TIM-Gehirn G3): welche Gedächtnis-Aussagen standen hinter einem Plan.

Nur eine Notiz am Journaleintrag. Sie ändert keinen Plan, keine Regel und keinen Score. Die Aussagen
(``docs/research_lab/gedaechtnis/aussagen.jsonl``) werden anhand dessen gewählt, was im Plan tatsächlich vorkommt
(Grade, Score, GARCH-Feld, Stopp-Regel, Ziele). Gespeichert wird der Stand der Aussage zum Zeitpunkt des Plans, damit der
Fehlerfinder (G4) später sieht, ob ein Plan sich auf Widerlegtes oder Ungeprüftes stützte.

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


@lru_cache(maxsize=1)
def _register() -> dict[str, dict]:
    return {a["id"]: a for a in gedaechtnis.laden()}


def fuer_plan(plan: Mapping[str, Any]) -> list[dict[str, str]]:
    """``[{"id", "status", "nutzung"}]`` der Aussagen, auf die sich dieser Plan stützt."""
    try:
        register = _register()
        return [{"id": i, "status": register[i]["status"], "nutzung": register[i]["nutzung"]}
                for i in _wirkt(plan) if i in register]
    except Exception:  # noqa: BLE001 - Notiz darf das Journal nie stoppen
        return []
