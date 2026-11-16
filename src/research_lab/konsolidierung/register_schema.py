"""Schema des Studienregisters der Konsolidierung (Felder, erlaubte Werte, Prüfung)."""
from __future__ import annotations

KLASSEN = ("BELASTBAR", "BEDINGT VERWERTBAR", "EXPLORATIV", "UNGÜLTIG", "NICHT REPRODUZIERBAR")
PRUEFTIEFEN = ("A", "B", "C+", "C", "D")
AUSSAGE_STATUS = ("VERIFIZIERT", "NUR BERICHTET", "ANNAHME", "NICHT PRÜFBAR")
CLUSTER = ("TREND-4H", "BTC-1H", "OF-MIN", "LEVEL-INTRADAY", "FRÜH", "CARRY", "PROSPEKTIV", "OPTIONEN", "PROGNOSE", "INFRA", "EIGEN")

PRUEFTIEFE_TEXT = {
    "A": "Regelcode und Rohdaten unabhängig neu gerechnet; Handelsliste des Labors reproduziert",
    "B": "Rohe Handelsliste oder Rohergebnis des Labors neu ausgewertet (Kennzahlen, Bootstrap)",
    "C+": "Ergebnisdatei gelesen und die Zahlen des Logbuchs darin wiedergefunden (Konsistenz, keine Neuberechnung)",
    "C": "Präregistrierung oder Bericht gelesen, keine Zahlenprüfung",
    "D": "Nur Logbuchzeile und Kopf der Präregistrierung",
}

KLASSEN_TEXT = {
    "BELASTBAR": "Rechnung unabhängig bestätigt (Prüftiefe A oder B), Regel vorab festgelegt, keine bekannte Verzerrung, die das Urteil kippen würde. Sagt nichts über die Richtung: auch ein Negativbefund kann belastbar sein.",
    "BEDINGT VERWERTBAR": "Methode im Kern sauber, aber mit benannter Einschränkung (kleine oder mehrfach verbrauchte Stichprobe, nicht unabhängig nachgerechnet, Annahmen). Nutzbar nur mit dieser Einschränkung.",
    "EXPLORATIV": "Hinweis ohne vorab festgelegte Bestehensregel, zu wenige Fälle, nur Gate/Zähllauf oder noch nicht ausgewertet. Nur zur Hypothesenbildung.",
    "UNGÜLTIG": "Methodischer Fehler oder fehlende Voraussetzung, sodass die Aussage nicht als Evidenz zählt (z. B. Kriterium nach dem Ergebnis geändert, Blick nach vorn, Datenlücke).",
    "NICHT REPRODUZIERBAR": "Ergebnis lässt sich aus Repo und Daten nicht nachvollziehen (Datei oder Daten fehlen, nur Erinnerung).",
}

PFLICHTFELDER = ("id", "titel", "cluster", "typ", "datum", "quellen", "daten", "aufteilung", "kosten", "register", "stichprobe", "ergebnis",
                 "laborurteil", "pruefung", "klasse", "richtung", "begruendung", "maengel", "aussagen", "verwendung")


def e(id: str, titel: str, cluster: str, typ: str, datum: str, quellen: list[str], daten: str, aufteilung: str, kosten: str, register: str,
      stichprobe: str, ergebnis: str, laborurteil: str, pruefung: str, klasse: str, richtung: str, begruendung: str, maengel: list[str],
      aussagen: list[tuple[str, str]], verwendung: str) -> dict:
    """Ein Registereintrag. ``laborurteil`` ist der Status laut Logbuch (englisch, wie dort), ``klasse`` und ``pruefung`` sind unsere Einstufung."""
    assert cluster in CLUSTER, f"{id}: Cluster {cluster}"
    assert pruefung in PRUEFTIEFEN, f"{id}: Prüftiefe {pruefung}"
    assert klasse in KLASSEN, f"{id}: Klasse {klasse}"
    for t, s in aussagen:
        assert s in AUSSAGE_STATUS, f"{id}: Aussagestatus {s}"
    return {"id": id, "titel": titel, "cluster": cluster, "typ": typ, "datum": datum, "quellen": list(quellen), "daten": daten, "aufteilung": aufteilung,
            "kosten": kosten, "register": register, "stichprobe": stichprobe, "ergebnis": ergebnis, "laborurteil": laborurteil, "pruefung": pruefung,
            "klasse": klasse, "richtung": richtung, "begruendung": begruendung, "maengel": list(maengel),
            "aussagen": [{"text": t, "status": s} for t, s in aussagen], "verwendung": verwendung}


def pruefe(eintraege: list[dict]) -> list[str]:
    """Formfehler im Register: doppelte Ids, fehlende Felder, leere Pflichttexte."""
    fehler = []
    ids = [x["id"] for x in eintraege]
    for i in sorted({i for i in ids if ids.count(i) > 1}):
        fehler.append(f"Id doppelt: {i}")
    for x in eintraege:
        for f in PFLICHTFELDER:
            if f not in x:
                fehler.append(f"{x.get('id')}: Feld {f} fehlt")
            elif x[f] in ("", None):
                fehler.append(f"{x['id']}: Feld {f} leer")
        if x.get("klasse") == "BELASTBAR" and x.get("pruefung") not in ("A", "B"):
            fehler.append(f"{x['id']}: BELASTBAR setzt Prüftiefe A oder B voraus")
        if not x.get("aussagen"):
            fehler.append(f"{x['id']}: keine Aussagen")
    return fehler
