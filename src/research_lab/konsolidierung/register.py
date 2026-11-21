"""Studienregister der Konsolidierung: Einträge zusammenführen, prüfen, als JSON und Markdown schreiben.

Aufruf: ``python3 -m src.research_lab.konsolidierung.register <ausgabeordner>`` (schreibt studienregister.json und STUDIENREGISTER.md).
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

from src.research_lab.konsolidierung.register_daten_a import EINTRAEGE_A
from src.research_lab.konsolidierung.register_daten_b import EINTRAEGE_B
from src.research_lab.konsolidierung.register_daten_c import EINTRAEGE_C
from src.research_lab.konsolidierung.register_schema import KLASSEN, KLASSEN_TEXT, PRUEFTIEFE_TEXT, PRUEFTIEFEN, pruefe

CLUSTER_TEXT = {
    "TREND-4H": "Binance USD-M 4h BTC/ETH/SOL 2020–2024, Donchian/SMA200-Regel (S7, S7b). S7b-Makro und S25 verwenden dieselbe Handelsliste, S32 dieselbe Regel auf anderen Märkten. Eine Evidenzquelle für die Regel, nicht fünf.",
    "BTC-1H": "BTC 1h, S8-Minutenbalken-Datensatz (SHA-256 9083b6ae…), Standard-Trades. Die Validierung 2023–2024 wurde von S20–S28 wiederholt verwendet; die Studien sind nicht unabhängig voneinander.",
    "OF-MIN": "S8-Minutenbalken (Orderflow/Footprint, BTC 2020–2024). OF2, S31 (B1–B5 sind OF2-Modelle), OFX, S19, S17 und die Move-Kalibrierung teilen dieselben Daten.",
    "LEVEL-INTRADAY": "BTC/ETH/SOL 1m–15m aus Binance-Archiven, Training 2020–2022/23; S30, S34–S38 und die VWAP-Beschreibung testen Level-Ideen auf überlappenden Zeiträumen.",
    "FRÜH": "Frühe Studien (Sept.–Nov. 2026) auf BTC/ETH/SOL 2020–2024 mit Protokoll 1.x: R4 (48 Varianten), S4, S6, S9, S10, S13, S14.",
    "CARRY": "Funding-Carry: S5 (nicht testbar), S33-Carry (nur Training), eigene Prüfung T11.",
    "PROSPEKTIV": "Papier-Journale, Schatten und Echtgeld-Mini-Test: einzelne Beobachtungsfenster ab Oktober/November 2026, kleine Stichproben.",
    "OPTIONEN": "Deribit-Optionen/Gamma: Entwürfe, nur vorwärts; keine Historie.",
    "PROGNOSE": "Prognose-, Verteilungs- und KI-Studien ohne oder mit Papiertrades: Risiko- und Anzeigebausteine, keine Gewinnaussage.",
    "INFRA": "Plattform-, Daten- und Software-Abnahmen: prüfen Pipeline und Governance, nicht Profitabilität.",
    "EIGEN": "Eigene Nachrechnungen dieser Konsolidierung (Protokoll 1.0, eingefroren).",
}

NICHT_ZUGAENGLICH = [
    ("Mac-Dateien außerhalb des Repos", "~/Documents/TIM/evidence/S33-*.md und E0E1-2026-11-12.md (Entwürfe und Bericht zu S30/S33-Carry), ~/TIM-live/data/journal/ (Roh-Journale, auto.jsonl), Hermes-Evals; nur über Berichte des Labors bekannt, nicht selbst gelesen."),
    ("Kraken-Echtgeldtest und Bitunix-Konto", "Kontoauszüge, Orderlisten und Journal des Live-Traders nicht zugänglich; nur Berichte (Kraken-Kosten 04.11., Kapitalrechnung 12.11.)."),
    ("PS5/PS4-Rohdaten", "S8-Minutenbalken und die vollen OFX-Läufe sind nur als Ergebnisdateien kopiert (OFX: Suchprotokoll vollständig gezählt); keine eigene Neuberechnung der Orderflow-Studien."),
    ("V2-Archiv und Hermes", "V2-Kampagnenseiten (System → Archiv V2) und Hermes-Evals nicht im Repo; ohne Handelsbezug laut Gedächtnis."),
    ("Repos tim-ai-platform-private und tim-master", "Dateilisten verglichen und die einschlägigen Berichte gelesen (V1-Juli, Plan-Journal-Evidenz); keine vollständige Durchsicht der 2.041 bzw. 23 Dateien. Das private Repo enthält die Forschungsdateien ebenfalls (94 Dateien nur dort, überwiegend Infrastrukturbelege)."),
    ("GitHub-Issues und Pull-Request-Diskussionen", "nicht gelesen; Studienstände nur aus Repo, Logbuch und Ergebnisdateien."),
    ("Holdout ab 2025-01-01", "bewusst nicht geladen (versiegelt; Freigabe nur durch Uzi, bei S7b auch Barti)."),
    ("S29, S12, S18, S8, L1, KI1, GEX-Wand, S33-Optionsflow, S23", "kein Ergebnis vorhanden oder noch nicht ausgewertet; Status nicht prüfbar."),
    ("Projektordner /mnt/project-files/analysen", "rund 70 Unterordner; die studienrelevanten (Bitunix-Edge, Ziel 50 USDT, Indikator-/Orderflow-Prüfung, Läufer, VWAP, OF2-Kostengrenze, Stop-Analyse, Kraken-Kosten) wurden gelesen, Chart-/Layout-/Control-Center-Ordner nicht."),
    ("Externe Quellen", "Reels, Videos und Bootcamp-Material sind keine Messungen und wurden nur über TIMs Auswertungen (Bewertungsberichte) einbezogen."),
]


def alle_eintraege() -> list[dict]:
    return [*EINTRAEGE_A, *EINTRAEGE_B, *EINTRAEGE_C]


def zusammenfassung(eintraege: list[dict]) -> dict:
    """Zählungen für den Kopf des Registers. ``studien`` zählt nur Einträge der Cluster ohne EIGEN (also gefundene Studien und Berichte)."""
    fremd = [x for x in eintraege if x["cluster"] != "EIGEN"]
    return {
        "eintraege_gesamt": len(eintraege),
        "gefundene_studien_und_berichte": len(fremd),
        "eigene_nachrechnungen": len(eintraege) - len(fremd),
        "nach_klasse": dict(collections.Counter(x["klasse"] for x in fremd)),
        "nach_pruefung": {k: sum(1 for x in fremd if x["pruefung"] == k) for k in PRUEFTIEFEN},
        "nach_cluster": dict(collections.Counter(x["cluster"] for x in fremd)),
        "nach_typ_grob": dict(collections.Counter(_grob(x) for x in fremd)),
        "nach_laborurteil": dict(collections.Counter(x["laborurteil"].split(" ")[0] for x in fremd)),
        "belastbar_positiv": [x["id"] for x in fremd if x["klasse"] == "BELASTBAR" and x["richtung"].startswith("positiv")],
        "ungueltig": [x["id"] for x in fremd if x["klasse"] == "UNGÜLTIG"],
    }


def _grob(x: dict) -> str:
    t = x["typ"].lower()
    if any(w in t for w in ("handelsregel", "regelfamilie", "übertragung", "suchprozess", "größenregel")):
        return "Handelsregel oder Regelfamilie (gerechnet)"
    if any(w in t for w in ("filter",)):
        return "Filterstudie"
    if any(w in t for w in ("prognose", "beobachtung", "kalibrierung", "verteilung", "kostenstudie", "zerlegung", "beschreib", "fallanalyse")):
        return "Prognose-, Beobachtungs- oder Kalibrierstudie"
    if any(w in t for w in ("prospektiv", "papier", "journal", "schatten", "live", "echtgeld", "kostenmessung", "realisiert")):
        return "Prospektive oder reale Beobachtung"
    if any(w in t for w in ("plattform", "software", "prüf", "meta", "audit", "datenkampagne", "datenprobe")):
        return "Plattform, Prüfbericht, Meta"
    if any(w in t for w in ("carry",)):
        return "Carry"
    return "Sonstiges (Entwurf, Gate, Zähllauf)"


def markdown(eintraege: list[dict]) -> str:
    z = zusammenfassung(eintraege)
    L = ["# Studienregister der Konsolidierung (Stand 16.11.2026)", ""]
    L += ["Quelle der Wahrheit ist `studienregister.json` (maschinenlesbar). Diese Datei wird daraus erzeugt (`python3 -m src.research_lab.konsolidierung.register`).",
          "Vollständigkeit gilt nur im durchsuchten Umfang (Abschnitt „Nicht zugängliche oder nicht durchgesehene Quellen“).", ""]
    L += ["## Zählung", "",
          f"- Einträge gesamt: **{z['eintraege_gesamt']}**, davon gefundene Studien und Berichte: **{z['gefundene_studien_und_berichte']}**, eigene Nachrechnungen dieser Konsolidierung: {z['eigene_nachrechnungen']}.",
          "- Klassen (gefundene Studien): " + ", ".join(f"{k} {z['nach_klasse'].get(k, 0)}" for k in KLASSEN) + ".",
          "- Prüftiefe (gefundene Studien): " + ", ".join(f"{k} {z['nach_pruefung'][k]}" for k in PRUEFTIEFEN) + ".",
          "- Art (gefundene Studien): " + "; ".join(f"{k} {v}" for k, v in sorted(z["nach_typ_grob"].items())) + ".",
          "- Urteil des Labors laut Logbuch (erstes Wort): " + ", ".join(f"{k} {v}" for k, v in sorted(z["nach_laborurteil"].items())) + ".",
          ""]
    L += ["## Prüftiefen", ""] + [f"- **{k}**: {v}" for k, v in PRUEFTIEFE_TEXT.items()] + [""]
    L += ["## Qualitätsklassen", ""] + [f"- **{k}**: {v}" for k, v in KLASSEN_TEXT.items()]
    L += ["- Regel: `BELASTBAR` setzt Prüftiefe A oder B voraus. Aussagen werden einzeln gekennzeichnet: VERIFIZIERT (selbst nachgerechnet oder in der Ergebnisdatei gefunden), NUR BERICHTET, ANNAHME, NICHT PRÜFBAR.", ""]
    L += ["## Datenüberschneidung (Cluster)", ""]
    for c, text in CLUSTER_TEXT.items():
        ids = ", ".join(x["id"] for x in eintraege if x["cluster"] == c)
        L.append(f"- **{c}**: {text} Einträge: {ids}.")
    L += ["", "## Übersicht", "", "| Id | Titel | Cluster | Labor | Prüftiefe | Klasse | Richtung | Stichprobe |", "|---|---|---|---|---|---|---|---|"]
    for x in eintraege:
        L.append(f"| {x['id']} | {_zelle(x['titel'], 90)} | {x['cluster']} | {x['laborurteil'].split(' ')[0]} | {x['pruefung']} | {x['klasse']} | {_zelle(x['richtung'], 40)} | {_zelle(x['stichprobe'], 50)} |")
    L += ["", "## Einträge", ""]
    for x in eintraege:
        L += [f"### {x['id']}: {x['titel']}", "",
              f"- Cluster / Art / Beginn: {x['cluster']} / {x['typ']} / {x['datum']}",
              f"- Quellen: " + "; ".join(f"`{q}`" for q in x["quellen"]),
              f"- Daten: {x['daten']}",
              f"- Aufteilung: {x['aufteilung']}",
              f"- Kosten: {x['kosten']}",
              f"- Register: {x['register']}",
              f"- Stichprobe: {x['stichprobe']}",
              f"- Ergebnis: {x['ergebnis']}",
              f"- Urteil des Labors: {x['laborurteil']}",
              f"- **Prüftiefe {x['pruefung']}, Klasse {x['klasse']}, Richtung: {x['richtung']}**",
              f"- Begründung: {x['begruendung']}",
              "- Mängel: " + ("; ".join(x["maengel"]) if x["maengel"] else "keine benannt"),
              "- Aussagen: " + "; ".join(f"{a['text']} [{a['status']}]" for a in x["aussagen"]),
              f"- Verwendung in der Konsolidierung: {x['verwendung']}", ""]
    L += ["## Nicht zugängliche oder nicht durchgesehene Quellen", ""] + [f"- **{k}**: {v}" for k, v in NICHT_ZUGAENGLICH] + [""]
    return "\n".join(L)


def _zelle(text: str, n: int) -> str:
    t = text.replace("|", "/").replace("\n", " ")
    return t if len(t) <= n else t[: n - 1] + "…"


def schreibe(ordner: Path) -> dict:
    eintraege = alle_eintraege()
    fehler = pruefe(eintraege)
    if fehler:
        raise ValueError("Register fehlerhaft: " + "; ".join(fehler))
    ordner.mkdir(parents=True, exist_ok=True)
    daten = {"stand": "2026-11-16", "zusammenfassung": zusammenfassung(eintraege), "cluster": CLUSTER_TEXT, "nicht_zugaenglich": [{"quelle": k, "grund": v} for k, v in NICHT_ZUGAENGLICH],
             "eintraege": eintraege}
    (ordner / "studienregister.json").write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
    (ordner / "STUDIENREGISTER.md").write_text(markdown(eintraege), encoding="utf-8")
    return daten["zusammenfassung"]


if __name__ == "__main__":
    ziel = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/research_lab/konsolidierung")
    print(json.dumps(schreibe(ziel), ensure_ascii=False, indent=1))
