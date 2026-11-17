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
    begruendet = [float(p["net_r"]) for p in plaene if p.get("net_r") is not None and p.get("begruendung")]
    for a in aussagen:
        werte = je_id.get(a["id"], [])
        ohne = len(begruendet) - len(werte)
        if a["status"] != "belegt" or len(werte) < MIN_PLAENE or ohne < MIN_PLAENE:
            continue  # steht die Aussage in (fast) jedem Plan, zeigt ihr Mittel nur das Gesamtergebnis
        mit_mittel = sum(werte) / len(werte)
        if mit_mittel < 0 and mit_mittel < (sum(begruendet) - sum(werte)) / ohne:
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


SCORE_MIN_PLAENE = 30  # darunter ist der Vergleich ein Bild, kein Urteil


def ergebnistabelle(aussagen: Sequence[Mapping[str, Any]], plaene: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Je Aussage: Anzahl geschlossener Pläne, die sich auf sie stützen, Summe und Mittel net R.

    Pläne stützen sich auf mehrere Aussagen; die Zeilen überschneiden sich und dürfen nicht addiert werden.
    ``trennt`` ist False, wenn die Aussage in jedem begründeten Plan steht: Dann ist ihr Mittel nur das
    Gesamtergebnis und sagt nichts über die Aussage (Stand 17.11.: gilt für fast alle, siehe ``bausteine``)."""
    je_id, _ = _nutzung_plaene(plaene)
    begruendet = sum(1 for p in plaene if p.get("net_r") is not None and p.get("begruendung"))
    zeilen = []
    for a in aussagen:
        werte = je_id.get(a["id"])
        if werte:
            zeilen.append({"id": a["id"], "aussage": a["aussage"], "status": a["status"], "nutzung": a["nutzung"],
                           "plaene": len(werte), "trennt": len(werte) < begruendet, "summe_r": round(sum(werte), 3),
                           "mittel_r": round(sum(werte) / len(werte), 3)})
    return sorted(zeilen, key=lambda z: (-z["plaene"], z["id"]))


def _raenge(werte: Sequence[float]) -> list[float]:
    ordnung = sorted(range(len(werte)), key=lambda i: werte[i])
    raenge = [0.0] * len(werte)
    i = 0
    while i < len(ordnung):
        j = i
        while j + 1 < len(ordnung) and werte[ordnung[j + 1]] == werte[ordnung[i]]:
            j += 1
        for k in range(i, j + 1):
            raenge[ordnung[k]] = (i + j) / 2 + 1
        i = j + 1
    return raenge


def _spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Rangkorrelation; None, wenn eine Seite keine Streuung hat (z. B. Score immer gleich)."""
    if len(x) < 3:
        return None
    rx, ry = _raenge(x), _raenge(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sx = sum((a - mx) ** 2 for a in rx) ** 0.5
    sy = sum((b - my) ** 2 for b in ry) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return round(sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy), 3)


def _score_zeile(paare: Sequence[tuple[float, float]]) -> dict[str, Any]:
    scores, netto = [p[0] for p in paare], [p[1] for p in paare]
    zeile: dict[str, Any] = {"plaene": len(paare), "werte": len(set(scores)), "rang_korrelation": _spearman(scores, netto),
                             "oben_r": None, "unten_r": None}
    if len(paare) >= 2:
        sortiert = sorted(paare)
        halb = len(sortiert) // 2
        unten, oben = sortiert[:halb], sortiert[len(sortiert) - halb:]
        zeile["unten_r"] = round(sum(p[1] for p in unten) / len(unten), 3)
        zeile["oben_r"] = round(sum(p[1] for p in oben) / len(oben), 3)
    zeile["urteil_moeglich"] = len(paare) >= SCORE_MIN_PLAENE
    return zeile


def score_vergleich(plaene: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Trennt der Score gute von schlechten Plänen? Live-Score und Schatten-Score gegen net R.

    Verglichen wird nur auf Plänen, die beide Scores haben, damit beide dieselbe Stichprobe sehen."""
    live, schatten = [], []
    for plan in plaene:
        net, score = plan.get("net_r"), plan.get("score")
        zweiter = (plan.get("score_schatten") or {}).get("score") if isinstance(plan.get("score_schatten"), Mapping) else None
        if net is None or not isinstance(score, (int, float)) or not isinstance(zweiter, (int, float)):
            continue
        live.append((float(score), float(net)))
        schatten.append((float(zweiter), float(net)))
    return {"live": _score_zeile(live), "schatten": _score_zeile(schatten), "min_plaene": SCORE_MIN_PLAENE}


def _zahl(wert: float | None) -> str:
    return "–" if wert is None else f"{wert:+.2f}".replace(".", ",")


def render_tabelle(zeilen: Sequence[Mapping[str, Any]], maximal: int = 6) -> list[str]:
    if not zeilen:
        return []
    trennend = [z for z in zeilen if z.get("trennt")]
    gleich = len(zeilen) - len(trennend)
    out = ["Ergebnis je Aussage (Pläne überschneiden sich, nicht addieren):"]
    for z in trennend[:maximal]:
        out.append(f"- {z['id']} ({z['status']}): {z['plaene']} Pläne, Mittel {_zahl(z['mittel_r'])} R")
    if gleich:
        out.append(f"- {gleich} Aussagen stehen in jedem Plan und trennen deshalb nichts "
                   f"(Gesamt: {zeilen[0]['plaene']} Pläne, Mittel {_zahl(zeilen[0]['mittel_r'])} R).")
    return out


BAUSTEINE = ("marktzustand", "aggressor", "belege_dafuer", "belege_dagegen", "absorption", "oi", "positionierung")


def bausteine(plaene: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Ergebnis je Baustein des Schatten-Scores: Pläne, bei denen der Baustein gewirkt hat, gegen die übrigen.

    Anders als die Begründung (für jeden Plan gleich) unterscheiden sich die Bausteine von Plan zu Plan. Die
    Tabelle prüft damit die Zuschläge des Scores (Aussage C47) am Journal. ``dafuer`` = Baustein hob den
    Score, ``dagegen`` = senkte ihn, ``ohne`` = wirkte nicht. Kein Urteil unter ``SCORE_MIN_PLAENE`` Plänen."""
    faelle = []
    for plan in plaene:
        schatten = plan.get("score_schatten")
        teile = schatten.get("parts") if isinstance(schatten, Mapping) else None
        if plan.get("net_r") is not None and isinstance(teile, Mapping):
            faelle.append((teile, float(plan["net_r"])))
    zeilen = []
    for name in BAUSTEINE:
        gruppen: dict[str, list[float]] = {"dafuer": [], "dagegen": [], "ohne": []}
        for teile, net in faelle:
            wert = teile.get(name)
            wert = float(wert) if isinstance(wert, (int, float)) else 0.0
            gruppen["dafuer" if wert > 0 else "dagegen" if wert < 0 else "ohne"].append(net)
        if not gruppen["dafuer"] and not gruppen["dagegen"]:
            continue
        zeile: dict[str, Any] = {"baustein": name, "urteil_moeglich": len(faelle) >= SCORE_MIN_PLAENE}
        for key, werte in gruppen.items():
            zeile[key] = {"plaene": len(werte), "mittel_r": round(sum(werte) / len(werte), 3) if werte else None}
        zeilen.append(zeile)
    return zeilen


_WORT = {"marktzustand": "Marktzustand", "aggressor": "Aggressive Seite", "belege_dafuer": "Belege dafür",
         "belege_dagegen": "Belege dagegen", "absorption": "Absorption", "oi": "Open Interest",
         "positionierung": "Funding/Positionierung"}


def render_bausteine(zeilen: Sequence[Mapping[str, Any]]) -> list[str]:
    if not zeilen:
        return []
    out = ["Bausteine des Schatten-Scores gegen Ergebnis (Mittel net R, in Klammern Pläne):"]
    for z in zeilen:
        teile = [f"{wort} {_zahl(z[key]['mittel_r'])} ({z[key]['plaene']})"
                 for key, wort in (("dafuer", "dafür"), ("dagegen", "dagegen"), ("ohne", "ohne")) if z[key]["plaene"]]
        out.append(f"- {_WORT.get(z['baustein'], z['baustein'])}: " + ", ".join(teile))
    if not zeilen[0]["urteil_moeglich"]:
        out.append(f"- Noch kein Urteil (unter {SCORE_MIN_PLAENE} Plänen).")
    return out


def render_score(vergleich: Mapping[str, Any]) -> list[str]:
    n = vergleich["schatten"]["plaene"]
    if not n:
        return []
    live, schatten = vergleich["live"], vergleich["schatten"]
    zeile = (f"Score gegen Ergebnis ({n} Pläne): Live-Score {live['werte']} verschiedene Werte, Rangkorrelation "
             f"{_zahl(live['rang_korrelation'])}; Schatten-Score {schatten['werte']} Werte, Rangkorrelation "
             f"{_zahl(schatten['rang_korrelation'])}, obere Hälfte {_zahl(schatten['oben_r'])} R gegen untere "
             f"{_zahl(schatten['unten_r'])} R.")
    if not schatten["urteil_moeglich"]:
        zeile += f" Noch kein Urteil (unter {vergleich['min_plaene']} Plänen)."
    return [zeile]
