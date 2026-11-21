"""TIM-Gedächtnis: Liste prüfbarer Aussagen mit Status, Nutzung, Beleg und Code-Stelle.

Nur Daten und Auswertung. Nichts hier verändert eine Regel, ein Journal oder einen Plan. Die Liste steht in
``docs/research_lab/gedaechtnis/aussagen.jsonl`` (eine Aussage je Zeile). Befehl::

    python -m src.research_lab.gedaechtnis            # Gruppen und Zählung
    python -m src.research_lab.gedaechtnis --gruppe 2 # Aussagen einer Gruppe
    python -m src.research_lab.gedaechtnis --pruefen  # Schema und Code-Verweise prüfen
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PFAD = ROOT / "docs" / "research_lab" / "gedaechtnis" / "aussagen.jsonl"

STATUS = ("belegt", "hinweis", "ungeprueft", "widerlegt")
NUTZUNG = ("entscheidet", "papier", "schatten", "anzeige", "ruhend", "vorschlag", "unklar", "keine")
LIVE = ("entscheidet", "papier")
FELDER = ("id", "aussage", "bereich", "status", "nutzung", "beleg", "code", "anmerkung", "geprueft")
GRUPPEN = {
    1: "Live benutzt und widerlegt",
    2: "Live benutzt, ungeprüft oder nur Hinweis",
    3: "Belegt oder Hinweis, nur Schatten, Anzeige oder ungenutzt",
    4: "Widerlegt, nicht für Entscheidungen genutzt (Negativwissen)",
    5: "Live benutzt und belegt",
    6: "Ungeprüft, nur Schatten, Anzeige, ruhend oder ungenutzt",
}
_STUDIE = re.compile(r"\bS\d+|\bR4\b|research_lab")
_PFAD = re.compile(r"(?:src|docs|tests)/[\w./\-]*\.(?:py|md|json|jsonl)")


def laden(pfad: Path = PFAD) -> list[dict]:
    return [json.loads(zeile) for zeile in pfad.read_text(encoding="utf-8").splitlines() if zeile.strip()]


def gruppe(aussage: dict) -> int:
    status, nutzung = aussage["status"], aussage["nutzung"]
    live = nutzung in LIVE
    if live and status == "widerlegt":
        return 1
    if live and status in ("ungeprueft", "hinweis"):
        return 2
    if live and status == "belegt":
        return 5
    if nutzung == "unklar":
        return 2
    if status == "widerlegt":
        return 4
    if status in ("belegt", "hinweis"):
        return 3
    return 6


def pruefen(aussagen: list[dict], root: Path = ROOT) -> list[str]:
    """Fehler als Texte: Schema, doppelte Nummern, Code-Pfade, die es nicht gibt."""
    fehler: list[str] = []
    gesehen: set[str] = set()
    for a in aussagen:
        nr = a.get("id", "?")
        fehlt = [f for f in FELDER if f not in a]
        if fehlt:
            fehler.append(f"{nr}: Felder fehlen: {', '.join(fehlt)}")
            continue
        if nr in gesehen:
            fehler.append(f"{nr}: doppelte Nummer")
        gesehen.add(nr)
        if a["status"] not in STATUS:
            fehler.append(f"{nr}: Status {a['status']!r} unbekannt")
        if a["nutzung"] not in NUTZUNG:
            fehler.append(f"{nr}: Nutzung {a['nutzung']!r} unbekannt")
        if not a["aussage"].strip() or not a["beleg"].strip():
            fehler.append(f"{nr}: Aussage oder Beleg leer")
        if a["status"] == "widerlegt" and not _STUDIE.search(a["beleg"]):
            fehler.append(f"{nr}: widerlegt ohne Studienverweis im Beleg")
        for pfad in _PFAD.findall(a["code"]):
            if not (root / pfad).exists():
                fehler.append(f"{nr}: Pfad fehlt: {pfad}")
        if a["nutzung"] in LIVE and a["code"].strip() in ("", "-"):
            fehler.append(f"{nr}: genutzt, aber ohne Code-Stelle")
    return fehler


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--gruppe", type=int, choices=sorted(GRUPPEN))
    p.add_argument("--pruefen", action="store_true")
    args = p.parse_args(argv)
    aussagen = laden()
    if args.pruefen:
        fehler = pruefen(aussagen)
        print("\n".join(fehler) if fehler else f"{len(aussagen)} Aussagen in Ordnung")
        return 1 if fehler else 0
    if args.gruppe:
        for a in aussagen:
            if gruppe(a) == args.gruppe:
                print(f"{a['id']} [{a['status']}/{a['nutzung']}] {a['aussage']}")
        return 0
    zaehlung = Counter(gruppe(a) for a in aussagen)
    for nr, name in GRUPPEN.items():
        print(f"{nr} {name}: {zaehlung[nr]}")
    print(f"gesamt: {len(aussagen)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
