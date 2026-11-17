"""G4: wöchentlicher Fehlerfinder für das TIM-Gedächtnis (nur lesen, rechnet nichts um, ändert nichts).

Aus der Aussagenliste (``gedaechtnis``) und den geschlossenen Papier-Plänen (Feld ``begruendung`` je Plan, G3)
werden höchstens ``MAX_PUNKTE`` Auffälligkeiten gebildet, in dieser Reihenfolge der Wichtigkeit:

1. ``widerspruch``: Aussage wird live benutzt (entscheidet/papier), ist aber widerlegt.
2. ``journal``: als „belegt“ geführte Aussage, deren Pläne im Journal (mind. ``MIN_PLAENE``) im Mittel Verlust
   nach Kosten bringen. Das ist ein Hinweis zum Nachprüfen, kein Beweis (Pläne überschneiden sich).
3. ``ungeprueft``: Aussage entscheidet, ist aber ungeprüft oder nur Hinweis; zuerst die, auf die sich die
   meisten Pläne stützen.

Pläne ohne ``begruendung`` (vor G3 geschrieben) zählen als „unbekannt“, nie als Beleg. Der Abschnitt im
Sonntagsbericht ist reine Information; Uzi entscheidet, nichts wird ohne sein Wort entfernt.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

MAX_PUNKTE = 3
MIN_PLAENE = 10


def _nutzung_plaene(plaene: Sequence[Mapping[str, Any]]) -> tuple[dict[str, list[float]], int]:
    """Net R der geschlossenen Pläne je Aussage-ID und Anzahl Pläne ohne Begründung."""
    je_id: dict[str, list[float]] = defaultdict(list)
    unbekannt = 0
    for plan in plaene:
        net = plan.get("net_r")
        if net is None:
            continue
        begruendung = plan.get("begruendung")
        if not begruendung:
            unbekannt += 1
            continue
        for punkt in begruendung:
            if isinstance(punkt, Mapping) and punkt.get("id"):
                je_id[str(punkt["id"])].append(float(net))
    return je_id, unbekannt


def finde(aussagen: Sequence[Mapping[str, Any]], plaene: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    je_id, unbekannt = _nutzung_plaene(plaene)
    punkte: list[dict[str, Any]] = []

    def kopf(a: Mapping[str, Any], art: str, text: str) -> dict[str, Any]:
        werte = je_id.get(a["id"], [])
        return {"art": art, "id": a["id"], "aussage": a["aussage"], "text": text, "plaene": len(werte),
                "mittel_r": round(sum(werte) / len(werte), 3) if werte else None}

    for a in aussagen:
        if a["nutzung"] in ("entscheidet", "papier") and a["status"] == "widerlegt":
            punkte.append(kopf(a, "widerspruch", "wird live benutzt, ist aber widerlegt"))
    for a in aussagen:
        werte = je_id.get(a["id"], [])
        if a["status"] == "belegt" and len(werte) >= MIN_PLAENE and sum(werte) / len(werte) < 0:
            punkte.append(kopf(a, "journal", "gilt als belegt, aber die Pläne dazu verlieren im Journal im Mittel"))
    offen = [a for a in aussagen if a["nutzung"] == "entscheidet" and a["status"] in ("ungeprueft", "hinweis")]
    offen.sort(key=lambda a: -len(je_id.get(a["id"], [])))
    for a in offen:
        punkte.append(kopf(a, "ungeprueft", "entscheidet, ist aber nicht belegt"))
    return {"punkte": punkte[:MAX_PUNKTE], "gesamt": len(punkte), "plaene_ohne_begruendung": unbekannt,
            "plaene": sum(1 for p in plaene if p.get("net_r") is not None)}


def render(ergebnis: Mapping[str, Any]) -> list[str]:
    zeilen = ["**Fehler im Gedächtnis** (nur Hinweis, nichts wird geändert):"]
    if not ergebnis["punkte"]:
        zeilen.append("- Nichts Auffälliges gefunden.")
    for p in ergebnis["punkte"]:
        extra = f" ({p['plaene']} Pläne, Mittel {p['mittel_r']:+.2f} R)".replace(".", ",") if p["plaene"] else ""
        zeilen.append(f"- {p['id']}: {p['aussage']} – {p['text']}{extra}")
    rest = ergebnis["gesamt"] - len(ergebnis["punkte"])
    if rest > 0:
        zeilen.append(f"- Weitere {rest} Auffälligkeiten in der Liste.")
    if ergebnis["plaene_ohne_begruendung"]:
        zeilen.append(f"- {ergebnis['plaene_ohne_begruendung']} von {ergebnis['plaene']} geschlossenen Plänen haben "
                      "keine zuordenbare Begründung (älter als G3 oder ohne passende Aussage): unbekannt.")
    return zeilen
