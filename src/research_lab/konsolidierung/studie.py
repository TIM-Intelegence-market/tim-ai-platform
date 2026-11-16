"""Erzeugt die konsolidierte Studie (``KONSOLIDIERTE_STUDIE.md``) aus den gespeicherten Ergebnisdateien.

Alle Zahlen im Text stammen aus ``docs/research_lab/konsolidierung/ergebnisse/*.json``, aus dem Register (``studienregister.json``) und aus der
Evidenzmatrix (``evidenzmatrix.json``). Gliederung nach dem Auftrag: zwölf Abschnitte plus Abschlussurteil. Aufruf (aus dem Repo-Wurzelordner)::

    python3 -m src.research_lab.konsolidierung.studie [ausgabeordner]

Die Texte sind Aussagen über die Evidenz, keine Handelsempfehlung. Keine Stufe erlaubt Echtgeld.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

from .evidenz import de, ganz, kapitalbedarf, lade_zahlen, pct

ORDNER = Path("docs/research_lab/konsolidierung")
ERG = ORDNER / "ergebnisse"
Z95, Z80 = NormalDist().inv_cdf(0.95), NormalDist().inv_cdf(0.80)


def J(name: str, ordner: Path = ERG) -> dict:
    return json.loads((ordner / name).read_text(encoding="utf-8"))


def tab(kopf: list[str], zeilen: list[list], rechts: tuple[int, ...] = ()) -> list[str]:
    """Markdown-Tabelle; Spalten in ``rechts`` rechtsbündig."""
    ausr = ["---:" if i in rechts else "---" for i in range(len(kopf))]
    out = ["| " + " | ".join(kopf) + " |", "|" + "|".join(ausr) + "|"]
    for z in zeilen:
        out.append("| " + " | ".join(str(c) for c in z) + " |")
    return out + [""]


def r(x: float | None, nd: int = 3, vz: bool = True) -> str:
    """R-Wert mit Vorzeichen und Komma; None als Strich."""
    return "–" if x is None else de(x, nd, vz)


def n_trades_bis_power(e: float, sd: float, power_z: float = Z80) -> int:
    """Trades für einen einseitigen Test zum Niveau 5 % mit gegebener Power (Normalnäherung)."""
    return int(math.ceil(((Z95 + power_z) * sd / e) ** 2))


def dsep(x: float, nd: int = 1) -> str:
    """Dezimalzahl mit Dezimalkomma und Punkt als Tausendertrenner."""
    return f"{x:,.{nd}f}".replace(",", "§").replace(".", ",").replace("§", ".").replace("-", "−")


def holdout_trades(trades_pro_monat: float, monate: int = 18) -> int:
    """Erwartete Trades im Holdout 2025-01 bis 2026-06 (18 Monate), gerundet; überall im Dokument dieselbe Zahl."""
    return int(round(monate * trades_pro_monat))


def power(e: float, sd: float, n: int) -> float:
    return NormalDist().cdf(e / (sd / math.sqrt(n)) - Z95)


def lade_alles() -> dict:
    d = {"z": lade_zahlen(ERG), "krit": J("kriterien.json"), "t1": J("t01_reproduktion.json")["ergebnis"], "t2": J("t02_kosten.json")["ergebnis"],
         "t3": J("t03_zufall_C1.json")["ergebnis"], "t3c3": J("t03_zufall_C3.json")["ergebnis"], "t4": J("t04_raster_C1.json")["ergebnis"],
         "t5": J("t05_komponenten.json")["ergebnis"], "t6": J("t06_konzentration_C1.json")["ergebnis"], "t7": J("t07_unsicherheit_C1.json")["ergebnis"],
         "t7c3": J("t07_unsicherheit_C3.json")["ergebnis"], "t8": J("t08_dsr_C1.json")["ergebnis"], "t9": J("t09_regime_C1.json")["ergebnis"],
         "t10": J("t10_referenzen.json")["ergebnis"], "t11": J("t11_carry.json")["ergebnis"], "t12": J("t12_kombination.json")["ergebnis"],
         "t13": J("t13_bitunix.json")["ergebnis"], "t15": J("t15_ausserhalb.json"), "t15audit": J("t15_datenaudit.json"), "audit": J("datenaudit.json"),
         "sk": J("studien_kennzahlen.json")["studien"], "lb": J("logbuch_abgleich.json"), "stand": J("PROTOKOLL_STAND.json"),
         "reg": J("studienregister.json", ORDNER), "mat": J("evidenzmatrix.json", ORDNER), "ofx": J("ofx_bestenlisten_aggregat.json"),
         "nachtrag": J("nachtrag_gegenpruefung.json")["ergebnis"]}
    return d


# ---------------------------------------------------------------------------------------------------------------------------------------
# Abschnitte
# ---------------------------------------------------------------------------------------------------------------------------------------

def kopf(d: dict) -> list[str]:
    s, t15 = d["stand"], d["t15"]["meta"]
    return [
        "# Konsolidierte Studie: Gibt es bei TIM einen nach realistischen Kosten belastbaren Handelsvorteil?", "",
        "Stand 16.11.2026. Auftrag von Uzi (Konsolidierung aller TIM-Studien). Nur Analyse und Papier; **keine Echtgeld-Freigabe**, `TRADING_AUTHORIZED=NO` bleibt, "
        "kein Live-Eingriff, kein Merge ohne Uzis Wort. Zeitangaben in diesem Dokument sind UTC (deutsche Winterzeit = UTC + 1 Stunde), damit sie mit den Prüfprotokollen übereinstimmen.", "",
        f"Protokolle: `PROTOKOLL_KONSOLIDIERUNG.md` 1.0 (eingefroren im Commit `{s['git_commit'][:7]}`, SHA-256 `{s['sha256'][:12]}…`, {s['eingefroren_utc'].replace('T', ' ').replace('Z', ' UTC')}) "
        f"und Zusatzprotokoll `PROTOKOLL_KONSOLIDIERUNG_T15.md` 1.1-T15 (Commit `ceed9f9`, vor dem Laden der Daten). Stand des Codes beim Lauf von T1 bis T13: Commit `{d['krit']['meta']['code_commit'][:7]}`; "
        f"beim Lauf von T15: Commit `{t15['code_commit'][:7]}` (der T15-Code selbst wurde im Commit `b0e8575` festgehalten, vor dem Datenbericht und vor dem Lauf). Wiederholung: `README.md` in diesem Ordner.", ""]


def abschnitt1(d: dict) -> list[str]:
    z, reg, krit, t15 = d["z"], d["reg"]["zusammenfassung"], d["krit"]["kriterien"], d["t15"]["ergebnis"]
    kb1 = kapitalbedarf(z["K1_pooled"], z["trades_pro_monat"], 0.01)
    o = ["## 1. Kurzzusammenfassung und belastbares Gesamturteil", "",
         "> **Gesamturteil: INTERESSANTE HYPOTHESE, EVIDENZ UNZUREICHEND.** Das gilt für genau eine Familie: die Trendregel S7b-D20-T3 "
         "(Donchian-20-Ausbruch in Richtung SMA200, 4h-Kerzen, ATR-Stop, Ziel 3 R; Kandidaten C1 = BTC/ETH/SOL und C3 = BTC/ETH). "
         "Für alle übrigen untersuchten Familien (Orderflow, Indikator-Merkmale, Level-Reaktion, frühe Regelfamilien, Plan-Journale, Carry als Handelsvorteil) gilt: **KEIN BELASTBARER VORTEIL**. "
         "Keines dieser Urteile autorisiert Echtgeldhandel oder eine Live-Aktivierung.", "",
         "Warum nicht mehr: C1 besteht die Reproduktion, die Kostenprüfung, den Zufallsvergleich, das Parameter-Plateau, die Konzentrations- und die Unsicherheitsprüfung (G1 bis G6, G11); "
         f"C3 (ohne SOL) verfehlt zusätzlich den Zufallsvergleich im Training (G3: p {de(z['c3_zufall_p_train'], 3)}). "
         f"Beide scheitern an der Mehrfachtest-Korrektur (G7: Deflated Sharpe {de(z['dsr_n64_train'], 2)} / {de(z['dsr_n64_valid'], 2)} bei Schwelle 0,95; schon bei N = 58 nur {de(z['dsr_n58_train'], 2)} / {de(z['dsr_n58_valid'], 2)}) und an der Übertragung auf andere Coins "
         f"(G8: {de(z['s32_e'], 4, True)} R bei n {ganz(z['s32_n'])}). Der einzige Test außerhalb des Entwicklungszeitraums (T15, C3 auf BTC/ETH 2017 bis 2019, ein Lauf, vorab eingefroren) ging in die richtige Richtung, "
         f"verfehlte aber die Schwelle: {r(t15['p1']['e_r'])} R je Trade, p {de(t15['p1']['p_monatsblock_bootstrap_einseitig'], 3)} (Schwelle 0,05). "
         f"Zufällige Einstiege in SMA200-Richtung mit gleicher Ausstiegsregel erreichten dort unter denselben Kosten (K1) im Mittel {r(t15['p3']['e_r_zufall_mittel'])} R gegen {r(t15['p3']['kandidat_e_r'])} R der Regel (p {de(t15['p3']['p_einseitig'], 2)}). "
         f"Gleiche Basis im Entwicklungszeitraum (C3, K1): Zufall {r(z['c3_zufall_e_train'])} / {r(z['c3_zufall_e_valid'])} R gegen {r(z['c3_K1_train'])} / {r(z['c3_K1_valid'])} R der Regel (Training / Validierung, p {de(z['c3_zufall_p_train'], 3)} / {de(z['c3_zufall_p_valid'], 3)}). "
         "Ein positiver Netto-Erwartungswert ist damit **plausibel, aber nicht nachgewiesen**.", "",
         "Der stärkste Einwand gegen die Regel: Ein Vorteil, falls es ihn gibt, kommt vor allem aus der Trendseite (SMA200-Richtung) und der Auszahlungsgeometrie (Ziel 3 R), nicht aus dem Ausbruchszeitpunkt. "
         f"Dafür sprechen T15 (kein Vorsprung gegenüber zufälligen Einstiegen), der kleine und im Training nicht signifikante Abstand bei C3 und die einfache Referenz R2 (SMA200 lang/flat) mit dem höheren Sharpe ({de(z['r2_sharpe'], 2)} gegen {de(z['c1_sharpe'], 2)}). "
         f"Dagegen spricht, dass T15 wenig Aussagekraft hat (n {t15['p1']['n']}, kleinste bei 80 % Power nachweisbare Erwartung {r(t15['aussagekraft_nachtraeglich']['kleinste_bei_80_prozent_power_nachweisbare_erwartung_r'], 2)} R): "
         f"p {de(t15['p1']['p_monatsblock_bootstrap_einseitig'], 3)} und der fehlende Vorsprung vor dem Zufall sind dort keine Widerlegung. Beide Lesarten bleiben offen (Abschnitt 9.3).", "",
         "### Die acht Fragen des Auftrags", ""]
    o += [f"1. **Wie viele Studien wurden gefunden und geprüft?** {reg['gefundene_studien_und_berichte']} Studien und Berichte im durchsuchten Umfang (dazu {reg['eigene_nachrechnungen']} eigene Nachrechnungen, Register: {reg['eintraege_gesamt']} Einträge). "
          f"Prüftiefe: A (Regelcode und Rohdaten unabhängig neu gerechnet) {reg['nach_pruefung']['A']}, B (Handelsliste neu ausgewertet) {reg['nach_pruefung']['B']}, C+ (Zahlen in der Ergebnisdatei wiedergefunden) {reg['nach_pruefung']['C+']}, "
          f"C (Bericht gelesen) {reg['nach_pruefung']['C']}, D (nur Logbuchzeile) {reg['nach_pruefung']['D']}. Aus Rohdaten neu gerechnet sind {reg['nach_pruefung']['A']} Studien (die Trendregel S7 und S7b); "
          f"weitere {reg['nach_pruefung']['B']} wurden aus den Handelslisten oder Rohergebnissen des Labors neu ausgewertet, darunter Fälle mit sehr kleinem n (S7b-Forward 4 Trades, S37 höchstens 5 je Variante). "
          "Alle übrigen sind nur auf Konsistenz geprüft oder gelesen und tragen entsprechend weniger Gewicht (Abschnitt 2). „Gefunden“ gilt nur für den durchsuchten Umfang.",
          f"2. **Was besteht nach der Prüfung?** (a) Eine Hypothese: Trendfolge mit Ausbruchseinstieg in SMA200-Richtung hatte 2020 bis 2024 nach Kosten eine positive Erwartung ({r(z['K1_pooled'])} R je Trade unter K1, "
          f"95-%-Band {r(z['ci_lo'])} bis {r(z['ci_hi'])} R), reproduziert bit-genau aus den Laborlisten. (b) Belastbare Negativbefunde: Level-, Orderflow- und Indikatorfamilien tragen nach Kosten keine Regel (S34, S35a, S36, S38 aus den Handelslisten neu ausgewertet; OFX: 0 von 8,1 Mio. Varianten nach den Bestenlisten des Labors). "
          "(c) Die Kostenarithmetik: Je enger der Stop, desto mehr verbrauchen Kosten den Vorteil (E5).",
          "3. **Welche vermeintlichen Erfolge waren methodisch nicht belastbar?** Unter anderem: das Carry-Ergebnis mit verdecktem Hebel, das OF2-Training (n 56, beste 5 % der Trades = 108 % der Summe), "
          "der S7b-Makrofilter F5 (nach fünf Versuchen, Glückstest p 0,066), der Sortiereffekt von S24 (verliert nach Kosten), die Plan-Journale (Vorzeichen hängt an 27 Ausschlüssen), "
          "der OF-Schatten (Regel nach Ansicht der Zwischenstände) und hohe Trefferquoten ohne Vorteil (S6: 72 bis 82 % bei negativer Erwartung; S4 erreichte sein 75-%-Ziel nicht einmal, höchstens 52,5 %). Tabelle in Abschnitt 4.",
          "4. **Was lässt sich zusammenführen?** Alle Studien zur Trendregel sind **eine** Evidenzquelle (derselbe Datencluster TREND-4H), nicht fünf; die Negativbefunde der Level-, Orderflow- und Indikatorfamilien bilden gemeinsam "
          "das Bild „Kosten schlucken den Vorteil kurzer Regeln“; Trefferquote ist Auszahlungsgeometrie, nicht Qualität des Einstiegs (S6). Ergebnis: drei im Protokoll festgelegte Kandidaten C1, C2, C3 (Abschnitt 7); "
          "als Beobachtungsportfolios für das Papier-Vorwärtsjournal werden C1 und C3 vollständig spezifiziert (Abschnitt 11), C2 (Carry-Anteil) wird nicht weiterverfolgt.",
          f"5. **Ist ein positiver Netto-Erwartungswert nachgewiesen?** Nein. Für die Trendregel ist er **plausibel** (reproduziert, kosten- und parameterrobust im Entwicklungszeitraum, gleiche Richtung in T15), aber **nicht nachgewiesen** (G7, G8, T15 p > 0,05, "
          "keine unabhängige prospektive Bestätigung). Für alle anderen Familien ist er **nicht erkennbar** (negativ oder nicht testbar).",
          f"6. **Unsicherheit und Drawdown?** C1 gepoolt 2020 bis 2024: größter Rückgang {de(z['dd_r_pooled'], 1)} R (etwa 21 % bei 1 % Risiko je Trade); im Monatsblock-Bootstrap Median {de(d['t7']['pooled']['monatsblock_bootstrap']['max_drawdown_r']['median'], 1)} R, "
          f"95. Perzentil {de(d['t7']['pooled']['monatsblock_bootstrap']['max_drawdown_r']['p95'], 1)} R. C3 in T15: {de(t15['p5']['max_drawdown_r'], 1)} R über {ganz(t15['p5']['max_drawdown_dauer_tage'])} Tage. "
          f"Die Streuung je Trade ist etwa {de(d['t7']['pooled']['kennzahlen']['sd_r'], 2)} R: Bei einer wahren Erwartung von 0,24 R wären für einen Nachweis (einseitig 5 %, Power 80 %) rund {n_trades_bis_power(0.24, 1.72)} Trades nötig, bei 0,20 R rund {n_trades_bis_power(0.20, 1.72)} (Abschnitt 10).",
          f"7. **Was fehlt bis zu einem belastbaren prospektiven Nachweis?** Mindestens eine unabhängige Stichprobe ohne Versuchsverbrauch: der einmalige Holdout 2025-01 bis 2026-06 (nur mit Uzis ausdrücklichem Wort und Bartis Zustimmung; etwa {holdout_trades(z['trades_pro_monat'])} Trades, Power nur etwa "
          f"{pct(power(0.24, 1.72, holdout_trades(z['trades_pro_monat'])), 0)}) und/oder rund {n_trades_bis_power(0.24, 1.72)} vorwärts beobachtete Trades (etwa {de(n_trades_bis_power(0.24, 1.72) / z['trades_pro_monat'] / 12, 1)} Jahre). "
          "Außerdem Bitunix-Gebühren, Funding und Ausführung als bestätigte Zahlen (Abschnitt 10, offene Voraussetzungen).",
          "8. **Wo liegen Studie und Artefakte?** `docs/research_lab/konsolidierung/` im Repo `tim-ai-platform` (Branch `claude/project-thread-iky0o0`): `KONSOLIDIERTE_STUDIE.md` (dieses Dokument), `STUDIENREGISTER.md`, `EVIDENZMATRIX.md`, `ergebnisse/` (JSON je Test), "
          "`grafiken/` (8 Bilder, reproduzierbar aus den JSON), `TESTLOG.md`, `TESTLOG_T15.md`, `README.md` (Reproduktion), Code in `src/research_lab/konsolidierung/`. Die Originalstudien bleiben unverändert.", "",
          "Die gewünschte Trefferquote von 75 % ist keine Anforderung und kein Beleg für Profitabilität: Die Trendregel gewinnt nur etwa "
          f"{pct(d['t7']['pooled']['kennzahlen']['trefferquote'], 0)} ihrer Trades und verdient dennoch über asymmetrische Gewinne (Ø {r(d['t7']['pooled']['kennzahlen']['mittel_gewinn_r'], 2)} gegen {r(d['t7']['pooled']['kennzahlen']['mittel_verlust_r'], 2)} R). "
          "Umgekehrt erreichte S6 im Training Trefferquoten von 72 bis 82 % bei negativer Erwartung (−0,07 bis −0,11 R), während S4 sein Ziel von 75 % mit höchstens 52,5 % nicht annähernd erreichte und ebenfalls nach Kosten verlor.", ""]
    o += ["### Die vier Evidenzstufen der Trendregel", ""]
    o += tab(["Stufe", "Stand", "Beleg"], [
        ["Historisch gut ausgesehen", "**ja**", f"2020 bis 2024: {r(z['K1_pooled'])} R je Trade (K1), n {z['n_pooled']}; S7 und S7b im Labor."],
        ["Korrigiert reproduziert", "**ja**", f"Unabhängige Nachrechnung reproduziert {ganz(d['t1']['gesamt']['trades_gespeichert'])} gespeicherte Trades ohne Abweichung (T1); Kostenpuffer, Plateau, Bootstrap-Band über 0."],
        ["Außerhalb der Entwicklung bestätigt", "**nein** (getestet)", f"T15 (BTC/ETH 2017 bis 2019): {r(t15['p1']['e_r'])} R, p {de(t15['p1']['p_monatsblock_bootstrap_einseitig'], 3)}, nicht bestätigt, Richtung positiv. "
         f"S32 (137 andere Coins): {de(z['s32_e'], 4, True)} R, nicht bestanden. Der Holdout ab 2025-01-01 ist unberührt."],
        ["Prospektiv beobachtet", "**zu wenig**", "S7b-Forward: 4 geschlossene Papier-Trades der Regel D20-T3 (alle Short; die Variante D20-T4 mit 3 Trades ist kein Kandidat). S7b-Sonde Juli bis Oktober 2026: 35 Trades, −5,8 R, versehentlich gesehen, nicht aufbewahrt und nicht vorab ausgewertet (NUR BERICHTET)."]])
    o += ["### Kriterien des eingefrorenen Protokolls (Ergebnis je Kandidat)", ""]
    namen = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G11", "CG1", "CG2", "G10"]
    zeilen = []
    for n in namen:
        zeilen.append([n] + [("bestanden" if krit[c]["kriterien"][n] else "**nicht bestanden**") if n in krit[c]["kriterien"] else "–" for c in ("C1", "C2", "C3")])
    o += tab(["Kriterium", "C1 (BTC/ETH/SOL)", "C2 (C1 + Carry)", "C3 (BTC/ETH)"], zeilen)
    nicht = {c: ", ".join(n for n in namen if n in krit[c]["kriterien"] and not krit[c]["kriterien"][n]) for c in ("C1", "C2", "C3")}
    o += ["Stufe nach Protokoll: C1, C2 und C3 jeweils Stufe 2. Das Protokoll verlangt dafür: G1 und G2 bestanden, aber nicht alle Kriterien von G3 bis G8 und G11 erfüllt (für C2 zusätzlich CG1, CG2, G10). "
          f"Nicht bestanden sind bei C1 {nicht['C1']}, bei C2 {nicht['C2']}, bei C3 {nicht['C3']}. Das Gesamturteil ist die höchste erreichte Stufe: **Stufe 2**. "
          "T15 ändert weder ein Kriterium noch die Stufe (Zusatzprotokoll Abschnitt 1 und 6).", "",
          f"Zu G11: Das Teilergebnis zu den Bitunix-Kerzen (Abweichung des E[R] {r(z['bx_delta'], 3)} R gegen die Toleranz von 0,05 R) lag vor dem Einfrieren vor; das Protokoll weist es selbst als berichtet, nicht als vorab festgelegt aus. "
          "Die Stufe hängt nicht daran, denn G7 und G8 scheitern unabhängig davon.", ""]
    return o


def abschnitt2(d: dict) -> list[str]:
    reg = d["reg"]
    zs = reg["zusammenfassung"]
    o = ["## 2. Suchumfang und vollständiges Studienregister", "",
         "**Durchsucht wurden:** das Studienarchiv des Labors im Repo (`docs/research_lab/`: Logbuch, Präregistrierungen, Berichte, Ergebnisdateien), die Ergebnisordner unter `/mnt/project-files/analysen/` (die studienrelevanten Unterordner), "
         "Kopien der PS5/PS4-Ergebnisse (S19 bis S38, OF2, OFX), die Berichte in `tim-master` und im privaten Repo, das Überzeugungsregister (12.11.2026) und die Papier-Journale. "
         "Stand des durchsuchten Repos: `platform-main` am 16.11.2026 um 12:46 UTC (Commit `3799781`, Merge von PR #282). Danach sind weitere Änderungen gemergt worden (Orderbuch-Anzeige im Dashboard, Twelve-Data-Schlüssel, OF2-Bausteine bis zum Modell M8); "
         "sie enthalten Programmcode und Tests, keine neuen Studienergebnisse, und sind nicht im Register. "
         "**Vollständigkeit gilt nur für diesen Umfang.** Nicht zugänglich oder nicht auswertbar waren:", ""]
    o += tab(["Quelle", "Grund"], [[x["quelle"], x["grund"]] for x in reg["nicht_zugaenglich"]])
    o += ["Wo Daten, Rechenleistung oder Zugriff fehlten, wurde das als Grenze der jeweiligen Aussage vermerkt und mit den vorhandenen Mitteln weitergearbeitet (zum Beispiel S32 nur berichtet, weil die Kerzen der 137 Coins nicht im Container liegen).", "",
         "### Einordnung der Registereinträge", "",
         f"{zs['eintraege_gesamt']} Einträge: {zs['gefundene_studien_und_berichte']} gefundene Studien und Berichte, {zs['eigene_nachrechnungen']} eigene Nachrechnungen. Vollständiges Register mit Quellen, Daten, Aufteilung, Kosten, Stichprobe, Mängeln und Aussagen: `STUDIENREGISTER.md` und `studienregister.json`.", ""]
    o += ["**Prüftiefen:** A = Regelcode und Rohdaten unabhängig neu gerechnet, Handelsliste des Labors reproduziert; B = Handelsliste oder Rohergebnis neu ausgewertet; C+ = Zahlen des Logbuchs in der Ergebnisdatei wiedergefunden (Konsistenz, keine Neuberechnung); "
          "C = Präregistrierung oder Bericht gelesen; D = nur Logbuchzeile.", "",
          "**Klassen:** BELASTBAR (Rechnung unabhängig bestätigt, Regel vorab festgelegt; sagt nichts über die Richtung), BEDINGT VERWERTBAR (Methode im Kern sauber, benannte Einschränkung), EXPLORATIV (Hinweis ohne vorab festgelegte Bestehensregel oder zu wenige Fälle), "
          "UNGÜLTIG (methodischer Fehler), NICHT REPRODUZIERBAR (Ergebnis nicht nachvollziehbar). Ein fehlerhaftes Ergebnis zählt nie als positive Evidenz.", ""]
    o += tab(["Klasse", "Anzahl (gefundene Studien und Berichte)"], [[k, v] for k, v in zs["nach_klasse"].items()], rechts=(1,))
    klassen_alle: dict[str, int] = {}
    for x in reg["eintraege"]:
        klassen_alle[x["klasse"]] = klassen_alle.get(x["klasse"], 0) + 1
    status_gefunden: dict[str, int] = {}
    status_alle: dict[str, int] = {}
    for x in reg["eintraege"]:
        for a in x["aussagen"]:
            status_alle[a["status"]] = status_alle.get(a["status"], 0) + 1
            if x["cluster"] != "EIGEN":
                status_gefunden[a["status"]] = status_gefunden.get(a["status"], 0) + 1
    o += [f"Die Zählung gilt für die {zs['gefundene_studien_und_berichte']} gefundenen Studien und Berichte; die {zs['eigene_nachrechnungen']} eigenen Nachrechnungen sind nicht mitgezählt (mit ihnen: "
          + ", ".join(f"{k} {v}" for k, v in klassen_alle.items()) + "). "
          "Keine Studie ist als UNGÜLTIG eingestuft: Das Labor kennzeichnet eigene Mängel (Gate gescheitert, Regel nach Ansicht geschrieben) selbst im Bericht; solche Studien sind EXPLORATIV oder nicht bestanden. "
          "Kein Eintrag ist **BELASTBAR und positiv** (`belastbar_positiv` ist leer): Die vier BELASTBAREN Einträge (S34, S35a, S36, S38) sind Negativ- oder Nullbefunde.", "",
          "BELASTBAR heißt hier nur: Die Kennzahlen wurden aus den Handelslisten des Labors neu berechnet (Prüftiefe B, nicht aus Rohdaten neu erzeugt), die Regel war vorab festgelegt, und die Richtung ist eindeutig. "
          "Zwei Einschränkungen: S34 hatte mit n 53 weniger als die vorab verlangten 60 Trades; sein „nicht bestanden“ beruht deshalb auf der Kostenarithmetik (Kosten 1,2 R je Trade bei einem mittleren Stop von 0,20 %), nicht auf einem Test mit ausreichender Fallzahl. "
          "Bei S36 wurden Konfigurationen nach dem ergebnisblinden Zähllauf und vor jedem R-Wert angepasst (Änderungen 0.2 und 0.3 der Präregistrierung). Beide Befunde sagen nichts über andere Regeln.", "",
          f"**Kennzeichnung der Aussagen:** Jede Aussage im Register trägt eine von vier Kennzeichnungen: VERIFIZIERT (in einer eigenen Rechnung oder im gelesenen Bericht wiedergefunden), NUR BERICHTET (Zahl aus einem Bericht übernommen, nicht nachgerechnet), "
          f"ANNAHME (für die Rechnung gesetzt, nicht belegt) und NICHT PRÜFBAR (Quelle oder Daten nicht zugänglich). Zählung der {sum(status_gefunden.values())} Aussagen zu den gefundenen Studien: "
          + ", ".join(f"{k} {status_gefunden.get(k, 0)}" for k in ("VERIFIZIERT", "NUR BERICHTET", "ANNAHME", "NICHT PRÜFBAR"))
          + f"; mit den eigenen Nachrechnungen insgesamt {sum(status_alle.values())}: "
          + ", ".join(f"{k} {status_alle.get(k, 0)}" for k in ("VERIFIZIERT", "NUR BERICHTET", "ANNAHME", "NICHT PRÜFBAR")) + ". "
          "VERIFIZIERT bedeutet bei Prüftiefe C+ und C nur, dass die Zahl im Bericht steht, nicht dass sie neu berechnet wurde; die Prüftiefe je Eintrag steht in der Tabelle unten. Die tragenden Aussagen dieser Studie stehen mit Kennzeichnung in Abschnitt 3.", ""]
    o += tab(["Datencluster", "Einträge", "Beschreibung (gleiche Daten: keine unabhängige Evidenz)"], [[c, zs["nach_cluster"].get(c, 5 if c == "EIGEN" else 0), t] for c, t in reg["cluster"].items()], rechts=(1,))
    o += ["### Alle Registereinträge", ""]
    zeilen = []
    for x in reg["eintraege"]:
        zeilen.append([x["id"], x["titel"][:78] + ("…" if len(x["titel"]) > 78 else ""), x["cluster"], x["pruefung"], x["klasse"].title() if x["klasse"] != "BEDINGT VERWERTBAR" else "Bedingt verwertbar", x["richtung"][:60]])
    o += tab(["Id", "Titel", "Cluster", "Tiefe", "Klasse", "Richtung"], zeilen)
    return o


def abschnitt3(d: dict) -> list[str]:
    a, lb, t1 = d["audit"], d["lb"], d["t1"]["gesamt"]
    k4 = {x["symbol"]: x for x in a["kerzen_futures_4h"]}
    zahlen_lb = sum(v["zahlen_im_logbuch"] for v in lb.values())
    in_datei = sum(v["davon_in_datei"] for v in lb.values())
    fund = {x["symbol"]: x for x in a["funding"]}
    t15a = d["t15audit"]["ergebnis"]["symbole"]["BTCUSDT"]
    o = ["## 3. Daten- und Methodikprüfung", "",
         "**Geltungsbereich der eigenen Rechnungen:** Eigene Rechnungen verwenden ausschließlich Daten vor 2025-01-01 (Binance-USD-M-Archiv 2020 bis 2024; die Bitunix-Kerzen für G11 reichen von 2022-04-17 bis 2024-12-31) "
         "und für T15 Binance-Spot-Kerzen 2017-08 bis 2019-12. Der Holdout ab 2025-01-01 wurde nie geladen (der Lader verweigert ihn, das Datenaudit hält `holdout_geladen` als falsch fest). "
         "Informationen aus der Zeit danach (S7b-Sonde Juli bis Oktober 2026, Vorwärtsjournal ab 2026-11-01) stammen aus Berichten des Labors und sind **NUR BERICHTET**; sie fließen in keines der Kriterien G1 bis G11 ein. "
         "Die Bitunix-Orderbuch-Momentaufnahme von 2026 dient nur der Ausführungsrealität (Abschnitt 10).", "",
         "### Daten", ""]
    o += tab(["Prüfpunkt", "Ergebnis", "Beleg"], [
        ["Holdout (ab 2025-01-01)", "nicht geladen; der Lader verweigert Daten ab 2025-01-01", "`ergebnisse/datenaudit.json`, `daten.py`"],
        ["Manifest Binance-Archive 2020 bis 2024", f"{a['manifest']['manifest_eintraege']} Einträge: {a['manifest']['geprueft_ok']} Prüfsummen stimmen, {a['manifest']['geprueft_abweichend']} weichen ab, "
         f"{a['manifest']['nicht_bereitgestellt']} nicht bereitgestellt (1m/15m-Serien, für die 4h-Konsolidierung nicht gebraucht)", "`datenaudit.json`"],
        ["4h-Kerzen USD-M BTC/ETH", f"je {ganz(k4['BTCUSDT']['kerzen'])} von {ganz(k4['BTCUSDT']['erwartet_im_Bereich'])} erwarteten Kerzen, keine Lücken, keine Duplikate, keine ungültigen Kerzen", "`datenaudit.json`"],
        ["4h-Kerzen USD-M SOL", f"{ganz(k4['SOLUSDT']['kerzen'])} von {ganz(k4['SOLUSDT']['erwartet_im_Bereich'])} ({k4['SOLUSDT']['fehlende_kerzen']} fehlen, {pct(k4['SOLUSDT']['fehlende_kerzen'] / k4['SOLUSDT']['erwartet_im_Bereich'], 2)}); die Engine setzt nach einer Lücke 200 Kerzen Vorlauf voraus", "`datenaudit.json`"],
        ["Funding BTC/ETH", f"{ganz(fund['BTCUSDT']['zeilen'])} Abrechnungen je Symbol, keine Duplikate, keine unregelmäßigen Abstände, Rate zwischen {de(fund['BTCUSDT']['rate_min'] * 100, 2)} % und {de(fund['BTCUSDT']['rate_max'] * 100, 2)} %; "
         f"{pct(fund['BTCUSDT']['anteil_positiv'], 0)} der Abrechnungen positiv (BTC)", "`datenaudit.json`"],
        ["Plausibilität 4h gegen 1h", "Aus 1h-Kerzen gebaute 4h-Kerzen stimmen bis auf einzelne Ausreißer (höchstens 0,6 % bei einzelnen Preisen) überein", "`datenaudit.json`"],
        ["Spot 2017 bis 2019 (nur T15)", f"{ganz(t15a['kerzen'])} Kerzen je Symbol, {pct(t15a['anteil_fehlend'], 2)} fehlen, acht Lücken (längste {t15a['laengste_luecke_kerzen']} Kerzen), Prüfsummen stimmen (58 Dateien), "
         f"davon nur {ganz(t15a['signalfaehige_kerzen_mit_200er_vorlauf'])} Kerzen mit 200 lückenlosen Vorlaufkerzen", "`T15_DATENBERICHT.md`, `t15_datenaudit.json`"],
        ["Bitunix-Kerzen", "Kerzen ab 2022-04-17 verglichen; vor dem Kontraktstart (2024-06-26) vermutlich Index-Kerzen (ANNAHME)", "`t13_bitunix.json`"]])
    o += ["### Methodik", ""]
    o += tab(["Prüfpunkt", "Vorgehen und Ergebnis"], [
        ["Rechenkern", f"Eigene, vom Laborcode unabhängige Nachrechnung der Regel (`s7b_nachrechnung.py`). Reproduktion der gespeicherten S7- und S7b-Handelslisten: {ganz(t1['trades_gespeichert'])} Trades, {ganz(t1['trades_gemeinsam'])} gemeinsam, "
         f"größte Abweichung {de(t1['max_abw_r'], 1)} R (T1, bestanden). T1 zeigt die Übereinstimmung zweier Rechenwege mit derselben Regelbeschreibung, nicht die Richtigkeit der Beschreibung selbst: Ein gemeinsamer Fehler in der Spezifikation würde T1 nicht finden. "
         "Deshalb prüfen Einheitstests den Simulationskern zusätzlich an handgerechneten Beispielen (Reihenfolge innerhalb der Kerze, Lücken, Zeitstopp, Kosten; `tests/test_konsolidierung_simulation.py`)."],
        ["Look-ahead", "Signale nur aus geschlossenen Kerzen; Einstieg zur Eröffnung der Folgekerze; Stop gewinnt vor Ziel innerhalb derselben Kerze; Lücken füllen zum Eröffnungskurs. Eine Kerze Einstiegsverzögerung (L1) wird als Stress gerechnet. "
         "T9 ordnet jeden Trade über die Eröffnungszeit der Signalkerze der BTC-Schwankung am Schluss genau dieser Kerze zu (kein Blick nach vorn); das setzt lückenlose BTC-4h-Kerzen voraus, die das Datenaudit bestätigt (eine Lücke würde die Zuordnung verschieben)."],
        ["Aufteilung und Holdout", "Das Protokoll folgt der Aufteilung des Labors: Training bis 2022, Validierung 2023 bis 2024, Holdout ab 2025 versiegelt. Handelsabschnitte nach Regel 1.2 (Signal im Abschnitt, Ausstieg spätestens am Abschnittsende). "
         "Die Validierung wurde vom Labor schon mehrfach verbraucht und ist **keine** unberührte Schlussprüfung. Der Auftrag nennt Training 2020 bis 2023 und Validierung 2024; diese Aufteilung ist im Nachtrag N3 (unten) als zusätzliche Ansicht gerechnet und ändert kein Urteil."],
        ["Mehrfachtest", f"Deflated Sharpe nach Bailey und López de Prado, eigene Rechnung mit der vereinfachten Nullfall-Varianz 1/(n−1) (Protokoll, wie im Laborbericht), für N = 58, 64 (G7, Konvention des Labors), 100, 200 und 26.707 Versuche. "
         "26.707 ist die Zahl der OFX-Konfigurationen beim Einfrieren des Protokolls; die später kopierte Ergebnisdatei zählt 27.023. Gegenprobe mit der empirischen Streuung der Sharpes im Parameter-Raster (T4, 600 Zellen): DSR bei N = 64 dann "
         f"{de(d['t8']['K1']['train']['raster_varianz']['dsr_n64']['dsr'], 2)} / {de(d['t8']['K1']['validation']['raster_varianz']['dsr_n64']['dsr'], 2)} / {de(d['t8']['K1']['pooled']['raster_varianz']['dsr_n64']['dsr'], 2)} (Training / Validierung / gepoolt). "
         f"G7 scheitert schon bei N = 58 ({de(d['z']['dsr_n58_train'], 2)} / {de(d['z']['dsr_n58_valid'], 2)}); das Urteil hängt an keiner der genannten Zahlen."],
        ["Kosten", "Szenarien K0 (Protokoll), K1 (Bitunix-Basis, Gebühr 0,06 % je Seite, unbestätigt), K2 (konservativ: Schlupf 0,06 %, Stop-Schlupf 0,10 %, Funding ohne Gutschrift), K3 (pessimistisch), K4 (Maker-Ziel, optimistisch), L1 (eine Kerze Verzögerung). Unbekannte Gebühren sind nie null."],
        ["Statistik", "Monatsblock-Bootstrap (10.000 Ziehungen, Seed 20261116, Trades gehören dem Monat ihres Signals), Newey-West für Wochenreihen, Wilson-Intervalle, Zufallseinstiege in SMA200-Richtung (1.000 Ziehungen), Parameter-Raster nur als Stabilitätsprüfung (Optimierungsbudget null). "
         "Der Bootstrap zieht nur Monate mit Trades (Abweichung und Größe: Nachtrag N1); das Perzentil des größten Rückgangs wird aus 2.000 der Ziehungen berechnet. In T15 ist p der Anteil der 10.000 Ziehungen mit Mittel ≤ 0 (vorab so festgelegt, ein Perzentil-Bootstrap, kein Test gegen eine Nullverteilung). "
         "Das Raster (8 × 5 × 5 × 3 = 600 Zellen) ist im Code festgelegt; das Protokoll nennt die Werte der 81 Nachbarzellen von C1, die übrigen Werte sind eine beschreibende Erweiterung im Code."],
        ["Gemeinsame Kennzahlenbasis", "Alle Handelslisten werden gleich gemessen (Abschnitt 5): E[R] netto, Trefferquote mit Wilson-Intervall, Ø Gewinn und Verlust, Profitfaktor, größter Rückgang in R und Tagen, Rendite mit ausdrücklicher Kapital- und Risikobasis. "
         "Nicht berechenbare Kennzahlen stehen als Strich, nie als Ersatzwert; unvereinbare Kennzahlen werden nicht gemittelt."],
        ["Logbuch gegen Ergebnisdateien", f"Von {zahlen_lb} Zahlen im Logbuch (29 Studien) wurden {in_datei} in den Ergebnisdateien wiedergefunden; der Rest (Rundung, Textverweise, nicht kopierte Datei) ist in `logbuch_abgleich.json` einzeln benannt."],
        ["Unabhängigkeit der Studien", "Studien mit denselben Daten gelten als eine Evidenzquelle (Cluster, Abschnitt 2); es gibt keine Doppelzählung in der Evidenzmatrix."]])
    z = d["z"]
    o += ["### Kennzeichnung der tragenden Aussagen", "",
          "Jede Aussage, auf der das Urteil beruht, mit ihrer Kennzeichnung: VERIFIZIERT (eigene Rechnung oder im gelesenen Bericht wiedergefunden), NUR BERICHTET (übernommen, nicht nachgerechnet), ANNAHME (für die Rechnung gesetzt, nicht belegt), NICHT PRÜFBAR (nicht zugänglich).", ""]
    o += tab(["Aussage", "Kennzeichnung", "Grundlage"], [
        [f"Die gespeicherten Handelslisten von S7 und S7b ({ganz(t1['trades_gespeichert'])} Trades) lassen sich aus Rohkerzen ohne Abweichung reproduzieren", "VERIFIZIERT", "T1, eigene Rechnung; Rohdaten gegen das Manifest geprüft"],
        ["Erwartung nach Kosten, Bänder, Kostenszenarien, Zufallsvergleich, Raster, Konzentration, Regime und Referenzen von C1 und C3 (2020 bis 2024)", "VERIFIZIERT", "T2 bis T10, eigene Rechnung auf den Rohdaten"],
        ["Alle bereitgestellten Archivdateien stimmen mit den Prüfsummen des Manifests überein; BTC/ETH-4h-Kerzen sind lückenlos, SOL hat wenige Lücken", "VERIFIZIERT", "`datenaudit.json`, `t15_datenaudit.json`"],
        ["T15 wurde vor dem Laden der Daten eingefroren und einmal gerechnet", "VERIFIZIERT (Commit-Reihenfolge); Einmaligkeit nur verfahrensmäßig", "Protokoll-Commit `ceed9f9` vor dem Datenbericht, dem Code und dem Lauf (siehe Grenzen der Prüfung)"],
        [f"S32: Übertragung auf andere Coins {r(z['s32_e'], 4)} R bei n {ganz(z['s32_n'])}", "NUR BERICHTET", "Ergebnisdatei gelesen, SHA-256 festgehalten; Kerzen der 137 Coins nicht im Container, nicht neu gerechnet"],
        ["Laborbericht Deflated Sharpe 0,81 (N = 64, beide Abschnitte gemeinsam)", "NUR BERICHTET", f"`deflated_sharpe_2026-11-11.md`; die eigene Rechnung (gepoolt {de(z['dsr_n64_pooled'], 2)}, VERIFIZIERT) ersetzt den Wert"],
        ["Mehr als 150 Prüfungen auf BTC 2020 bis 2024 ohne Gesamtzähler", "NUR BERICHTET", "Überzeugungsregister vom 12.11.2026, nicht nachgezählt; das Urteil hängt nicht daran (G7 scheitert schon bei N = 58)"],
        ["OFX: 27.023 Konfigurationen × 300 Filter, 0 Varianten bestehen das Sieb", "NUR BERICHTET", "Suchumfang und Siebergebnis aus den Laborfassungen; die Bestenlisten (135.100 Einträge) wurden neu ausgewertet (Prüftiefe B)"],
        ["S7b-Sonde Juli bis Oktober 2026: 35 Trades, −5,8 R", "NUR BERICHTET", "versehentlich gesehen, nicht aufbewahrt, nicht reproduzierbar"],
        ["S7b-Vorwärtsjournal: 4 geschlossene Trades der Regel D20-T3", "VERIFIZIERT", "Hash-Kette lückenlos, Zahlen nachgerechnet (Kopie des Journals mit SHA-256)"],
        ["Bitunix-Gebühren VIP0: Taker 0,06 %, Maker 0,02 %", "ANNAHME", "von Uzi genannt, im Code `FEES_VERIFIED = False`; ohne Konto nicht prüfbar. K1 und K2 rechnen mit 0,06 % je Seite"],
        ["Bitunix-Funding entspricht dem Binance-Funding", "ANNAHME", "keine öffentliche Funding-Historie von Bitunix; Einheit der Rate unklar"],
        ["Bitunix-Kerzen vor dem Kontraktstart (2024-06-26) sind Index-Kerzen", "ANNAHME", "Vermutung aus dem Kerzenvergleich"],
        ["Geldmarktzins im Carry-Vergleich", "ANNAHME", "aus dem Gedächtnis gesetzt, nicht aus TIM-Daten"],
        ["Spread und Marktorder-Schlupf von Bitunix", "VERIFIZIERT für eine Momentaufnahme von etwa 90 Sekunden in ruhigem Markt; nicht repräsentativ", "Rohproben in `eingaben/bitunix/bitunix_depth_samples.json` (Abschnitt 10)"],
        ["Kraken-Echtgeldtest, Bitunix-Konto, V2-Archiv, Mac-Journale", "NICHT PRÜFBAR", "nicht zugänglich (Abschnitt 2)"]])
    n = d["nachtrag"]
    n1c, n1a = n["N1"]["C1_pooled"]["nur_monate_mit_trade_lauf"], n["N1"]["C1_pooled"]["alle_monate"]
    n2, n3, n4 = n["N2"], n["N3"], n["N4"]
    o += ["### Nachtrag: Gegenprüfung nach dem Einfrieren", "",
          "Nach einer unabhängigen Gegenprüfung wurden vier Fragen nachgerechnet (`nachtrag_gegenpruefung.py`, `ergebnisse/nachtrag_gegenpruefung.json`; Holdout nicht geladen). Das ist Diagnose: Sie ändert kein Kriterium und kein Urteil, die ursprünglichen Ergebnisse stehen unverändert daneben.", ""]
    o += tab(["Nr", "Frage", "Ergebnis", "Wirkung"], [
        ["N1", f"Der Monatsblock-Bootstrap des Protokolls zieht nur Monate mit Trades. Was ändert sich, wenn alle {n1a['monate']} Kalendermonate ein Los bekommen (C1 gepoolt; {n1a['monate_mit_trade']} haben Trades)?",
         f"Untere 95-%-Grenze von E[R] {r(n1c['e_r']['ci95'][0])} → {r(n1a['e_r']['ci95'][0])} R, obere {r(n1c['e_r']['ci95'][1])} → {r(n1a['e_r']['ci95'][1])} R; 95. Perzentil des größten Rückgangs {de(n1c['max_drawdown_r']['p95'], 1)} → {de(n1a['max_drawdown_r']['p95'], 1)} R",
         "G6 bleibt bestanden (untere Grenze über 0)"],
        ["N2", f"Das Labor belastet Funding-Abrechnungen ab dem Einstiegszeitpunkt (bei {n2['c1_k2_einstiege_mit_abrechnung_im_fenster']['anzahl']} von {n2['c1_k2_einstiege_mit_abrechnung_im_fenster']['von']} Trades fällt der Einstieg mit einer Abrechnung zusammen). Was ändert sich, wenn nur spätere Abrechnungen zählen?",
         f"C1 K2 gepoolt {r(n2['C1_K2_pooled']['lauf']['e_r'])} → {r(n2['C1_K2_pooled']['streng']['e_r'])} R (Training {r(n2['C1_K2_train']['lauf']['e_r'])} → {r(n2['C1_K2_train']['streng']['e_r'])}, Validierung {r(n2['C1_K2_validation']['lauf']['e_r'])} → {r(n2['C1_K2_validation']['streng']['e_r'])})",
         "Die Laborkonvention ist die vorsichtigere; kein Urteil ändert sich"],
        ["N3", "Aufteilung des Auftrags (Training 2020 bis 2023, Validierung 2024) statt der Aufteilung des Protokolls",
         f"C1 K1: {r(n3['C1_K1']['training_2020_2023']['e_r'])} R (n {n3['C1_K1']['training_2020_2023']['n']}) / {r(n3['C1_K1']['validierung_2024']['e_r'])} R (n {n3['C1_K1']['validierung_2024']['n']}); "
         f"C1 K2: {r(n3['C1_K2']['training_2020_2023']['e_r'])} / {r(n3['C1_K2']['validierung_2024']['e_r'])} R; C3 K1: {r(n3['C3_K1']['training_2020_2023']['e_r'])} (n {n3['C3_K1']['training_2020_2023']['n']}) / {r(n3['C3_K1']['validierung_2024']['e_r'])} R (n {n3['C3_K1']['validierung_2024']['n']}); "
         f"C3 K2: {r(n3['C3_K2']['training_2020_2023']['e_r'])} / {r(n3['C3_K2']['validierung_2024']['e_r'])} R",
         "Gleiches Bild: positiv in beiden Abschnitten. Zufalls- und Mehrfachtest-Prüfungen wurden für diese Aufteilung nicht wiederholt"],
        ["N4", f"T15: Warum ist der Nettoertrag auf das Nominal ({de(n4['netto_bp_gespeichert'], 1)} bp je Trade) so viel kleiner als E[R] mal mittlerer Stop-Abstand ({de(n4['produkt_der_mittel_bp'], 0)} bp)?",
         f"Mittlerer Stop-Abstand {de(n4['mittlerer_stop_abstand_prozent_rueckgerechnet'], 2)} %; Mittel von R × Stop {de(n4['netto_bp_rueckgerechnet'], 1)} bp; Korrelation von R und Stop-Abstand {de(n4['korrelation_r_stop'], 2)}. "
         f"Je Jahr: 2017 {de(n4['je_jahr']['2017']['netto_bp'], 0)} bp bei Stop {de(n4['je_jahr']['2017']['mittlerer_stop_abstand_prozent'], 1)} %, 2018 {de(n4['je_jahr']['2018']['netto_bp'], 0)} bp, 2019 {de(n4['je_jahr']['2019']['netto_bp'], 0)} bp. "
         f"Stop unter 4 %: n {n4['stop_unter_4_prozent']['n']}, E[R] {r(n4['stop_unter_4_prozent']['e_r'], 2)}; ab 4 %: n {n4['stop_ab_4_prozent']['n']}, E[R] {r(n4['stop_ab_4_prozent']['e_r'], 2)}",
         "Weite Stopps verlieren, enge gewinnen: Die Erwartung in R lässt sich nicht einfach auf das Nominal übertragen (nachträglich, beschreibend)"]])
    o += ["### Grenzen der Prüfung", "",
          "- **Einmaligkeit von T15:** Der Lauf verweigert den Start, wenn eine Vorbedingung fehlt oder schon ein Ergebnis vorliegt. Das ist eine Schranke im Code, kein technischer Zwang. Dass es genau einen Lauf mit echten Daten gab, belegen die Reihenfolge der Commits "
          "(Protokoll, Datenbericht, Code, Lauf) und der Zeitpunkt der Daten; davor liefen nur Tests mit künstlichen Daten.",
          "- **Seltene Zweige im Simulationskern:** Der Zweig „Stop vor dem Einstieg“ kam in der Hauptrechnung (C1 gepoolt, K1) nicht vor (Ausstiegsgründe nur Stop, Ziel und Zeitstopp); er ist nur durch Einheitstests abgedeckt.",
          "- **Art der Gegenprüfung:** Sie erfolgte durch zwei nur lesende Prüfer (KI-Subagenten mit frischem Kontext), die Code und Text gelesen haben; ihre Befunde wurden einzeln gegen die Quellen geprüft, bestätigte Fehler korrigiert und Fehlalarme verworfen. "
          "Eine Prüfung durch Dritte oder mit unabhängig von Dritten geschriebenem Code gab es nicht.", ""]
    return o


def abschnitt4(d: dict) -> list[str]:
    z, t15, t6 = d["z"], d["t15"]["ergebnis"], d["t6"]
    o = ["## 4. Fehler, ausgeschlossene Ergebnisse und Begründungen", "",
         "**Ausgeschlossen wurde nichts**: Alle gefundenen Studien stehen im Register, auch gescheiterte; korrigierte Ergebnisse stehen neben den ursprünglichen. "
         "Folgende vermeintliche Erfolge zählen **nicht** als positive Evidenz:", ""]
    o += tab(["Vermeintlicher Erfolg", "Warum nicht belastbar", "Konsequenz"], [
        [f"Carry „formal bestanden“ (T11/S33): konstante Stückzahl {pct(z['carry_konst_train'])} je Jahr im Training, {pct(z['carry_konst_valid'])} in der Validierung",
         "Die konstante Stückzahl erzeugt verdeckten Hebel: Das Nominal wächst mit dem Kurs bis zum etwa 14-Fachen (BTC) und 37-Fachen (ETH) des Anfangskapitals (Grenze in `t11_carry.json`). Bei konstantem Nominal monatlich neu abgesichert: "
         f"{pct(z['carry_monat_train'])} und {pct(z['carry_monat_valid'])} je Jahr (Training / Validierung); der angenommene Geldmarkt liegt bei {pct(z['geld_train'])} und {pct(z['geld_valid'])} (ANNAHME aus dem Gedächtnis). "
         "In der Validierung ist der Carry also kein Mehrertrag gegenüber dem Geldmarkt.", "Kapitalrendite mit Gegenparteirisiko, kein Handelsvorteil; C2 wird nicht gegenüber C1 bevorzugt."],
        ["OF2-Training: n 56, +0,27 R je Trade, Labor-p 0,006", "Weit unter jeder tragfähigen Mindestzahl; beste 5 % der Trades = 108 % der Summe; Median −0,35 R; eigenes 95-%-Band −0,20 bis +0,66 R; Deflated Sharpe (N = 64) etwa 0,06.", "Nur Hypothese; die Kostengrenze (Bitunix-Edge) sinkt mit wachsendem n."],
        ["OFX: 27.023 Konfigurationen × 300 Filter", f"{ganz(d['ofx']['zeilen'] if 'zeilen' in d['ofx'] else 135100)} Bestenlisten-Einträge, Median n = 5; 0 Varianten bestehen das Sieb; bestes t bei n ≥ 130 ist 2,66, ein Zufallsmaximum von etwa 3 ist bei Millionen Varianten zu erwarten.", "Suche ohne Ergebnis; keine weitere Suche auf demselben Training ohne Zählung der Versuche."],
        ["S24-M2: Sortiereffekt 0,135 R (p 0,004)", "Echter Unterschied zwischen Gruppen, aber NEHMEN verliert nach Kosten −0,378 R (n 11.181).", "Sortiert, nicht handelbar."],
        ["S7b-Makro: Filter F5 besteht", "Fünf Filter getestet, nur F5 besteht; Glückstest über fünf Filter p = 0,066, F1 bis F4 bestehen nicht.", "Nicht an die Regel hängen; als Vorwärts-Log beobachten."],
        ["Plan-Journale (84 Pläne): ohne das Level-Journal +8,39 R", "Gesamt −9,32 R; laut Überzeugungsregister kippen 27 Ausschlüsse das Vorzeichen des Hauptjournals von −27,6 R auf +0,9 R; alle Pläne Grade C, Score streut nicht, vier Wochen.", "Keine Aussage; Auswahl bestimmt das Vorzeichen."],
        ["OF-Schatten: Orderflow-Ausstieg −0,23 R gegen Journal −11,44 R", "Regel nach Ansicht von 25 Zwischenständen geschrieben, nur Long in fallendem Markt, Pläne überlappen, Kosten ungleich.", "Nur Beobachtung."],
        ["Hohe Trefferquoten (S6: 72 bis 82 % im Training; S4 verfehlte sein 75-%-Ziel)", "S6: Erwartung −0,07 bis −0,11 R; Zufallseinstiege mit gleicher Geometrie treffen genauso oft (82,0 % gegen 81,9 %): Die Trefferquote kommt aus dem Verhältnis von Ziel zu Stop, nicht aus dem Einstieg. "
         "S4: höchste Trefferquote 52,5 %, Erwartung −0,12 bis −0,23 R.", "Trefferquote ist kein Gütekriterium; maßgeblich ist E[R] nach Kosten."],
        ["S7b-Forward: 4 und 3 Trades, +3,8 R und +6,8 R", "n viel zu klein, alle Short, ein Marktabschnitt; die Summe liegt im Rahmen von Glück. Die S7b-Sonde Juli bis Oktober 2026 (35 Trades, −5,8 R) wurde versehentlich gesehen, nicht aufbewahrt und nicht vorab ausgewertet.", "Weder Beleg noch Gegenbeleg; beide zählen nicht."],
        [f"Trendregel unter K1: {r(z['K1_pooled'])} R, Band über 0", f"Nach der Zählung der Versuche kein Nachweis: DSR {de(z['dsr_n64_train'], 2)} / {de(z['dsr_n64_valid'], 2)} (N = 64), Beste 5 % der Trades = {pct(z['top5_anteil'])} der Summe, 2020 liefert {de(z['jahr2020_r'], 0)} von {de(z['summe_r_pooled'], 0)} R, "
         f"2021 {r(z['jahr2021_e'], 2)} R je Trade; eine Kerze Verzögerung ergibt in der Validierung {r(z['L1_valid'])} R.", "Plausible Hypothese, kein Nachweis (Stufe 2)."],
        [f"T15: {r(t15['p1']['e_r'])} R außerhalb der Entwicklung", f"p {de(t15['p1']['p_monatsblock_bootstrap_einseitig'], 3)} (Schwelle 0,05 verfehlt); Zufallseinstiege in SMA200-Richtung im Mittel {r(t15['p3']['e_r_zufall_mittel'])} R gegen {r(t15['p3']['kandidat_e_r'])} R der Regel (beide K1, p {de(t15['p3']['p_einseitig'], 2)}); beste 5 % der Trades = {pct(t15['p7']['anteil_beste_5_prozent_an_summe'])} der Summe.", "Positive Richtung, aber kein Nachweis und kein Vorsprung des Einstiegs gegenüber der Trendseite."]])
    o += ["### Korrekturen gegenüber ursprünglichen Ergebnissen (getrennt ausgewiesen)", "",
          "- **Carry:** ursprüngliche Rechnung (konstante Stückzahl) und Rechnung mit konstantem Nominal stehen nebeneinander (`t11_carry.json`); die Kriterien des Protokolls wurden dadurch nicht geändert.",
          "- **S32 (Übertragung auf 137 Coins):** nur berichtet (Ergebnisdatei gelesen, SHA-256 festgehalten); die Kerzen liegen nicht im Container und konnten nicht neu gerechnet werden.",
          f"- **T15:** Der Zeitraum mit Signalmöglichkeit ist wegen acht Datenlücken kürzer als im Zusatzprotokoll geschätzt (etwa 19,8 statt 27 Monate); das wurde vor dem Lauf festgehalten (`T15_DATENBERICHT.md`), Regel und Kriterien blieben unverändert.",
          "- **Logbuch-Zahlen:** Wo das Logbuch Zahlen nennt, die in den Ergebnisdateien nicht stehen, steht das einzeln in `logbuch_abgleich.json`; keine dieser Zahlen wird als Evidenz verwendet.", "",
          "### Korrekturen an dieser Studie nach der Gegenprüfung", "",
          "Die unabhängige Gegenprüfung hat in einer ersten Fassung dieser Studie Fehler gefunden; sie wurden einzeln gegen die Quellen geprüft und vor der Abgabe korrigiert (die Fehlalarme sind hier nicht aufgeführt):", "",
          "- Die Trefferquoten von 72 bis 82 % gehören zu S6, nicht zu S4 (S4: höchstens 52,5 %).",
          "- Die Stichprobengröße 318 gilt für eine wahre Erwartung von 0,24 R (bei 0,20 R sind es 458), nicht für 0,2 R.",
          "- Eine Kerze Verzögerung halbiert die Erwartung im Training nicht (+0,221 → +0,181 R, etwa −18 %); sie löscht sie in der Validierung (+0,264 → −0,007 R).",
          "- Der Zufallsvergleich in T15 (C3) wurde zuerst mit den Zahlen von C1 verglichen; verglichen wird jetzt mit C3 auf derselben Basis (Abschnitt 1 und 9.3).",
          "- Evidenzmatrix E1: T15 wurde doppelt gezählt (als Beleg und als Gegenbeleg) und „7 geschlossene Papier-Trades“ stimmte nicht (4 der Regel D20-T3).",
          "- Register: S7-Werte (Training / Validierung getrennt), S9 (nur BTCUSDT 15m, Prüftiefe C), K1 (Prüftiefe C) und der Zufallswert von S7b (+0,097 R eigene Rechnung statt eines nicht auffindbaren Laborwerts +0,095 R).", ""]
    return o


def abschnitt5(d: dict) -> list[str]:
    z, t2, t7, t7c3, t15 = d["z"], d["t2"], d["t7"], d["t7c3"], d["t15"]["ergebnis"]
    kp = t7["pooled"]["kennzahlen"]
    k2c1, k2c3 = t2["C1"]["szenarien"]["K2"]["pooled"], t2["C3"]["szenarien"]["K2"]["pooled"]
    kc3 = t7c3["pooled"]["kennzahlen"]
    k15 = t15["primaer_k2"]["kennzahlen"]
    b15 = t15["primaer_k2"]["monatsblock_bootstrap"]["e_r"]
    o = ["## 5. Vergleichbare neu berechnete Resultate", "",
         "Alle Zahlen aus der eigenen Nachrechnung, in R-Vielfachen des Anfangsrisikos je Trade (1 R = Abstand Einstieg bis Stop), netto nach Kosten. Die Rendite hat eine ausdrückliche Basis: 10.000 USDT, 1 % Risiko je R, nicht aufgezinst. "
         "„–“ bedeutet: in diesem Test nicht berechnet (nicht ersetzt).", "", "### 5.1 Trendregel: Entwicklungszeitraum und Test außerhalb", ""]
    o += tab(["Kennzahl", "C1 K1 gepoolt 2020–24", "C1 K2 gepoolt 2020–24", "C3 K2 gepoolt 2020–24", "C3 K2 T15 2017–19 (Spot)"], [
        ["Trades n", ganz(kp["n"]), ganz(k2c1["n"]), ganz(k2c3["n"]), ganz(k15["n"])],
        ["Trades je Monat", de(kp["trades_pro_monat"], 1), "–", "–", de(k15["trades_pro_monat"], 1)],
        ["E[R] je Trade", r(kp["e_r"]), r(k2c1["e_r"]), r(k2c3["e_r"]), r(k15["e_r"])],
        ["95-%-Band (Monatsblock-Bootstrap)", f"{r(z['ci_lo'])} bis {r(z['ci_hi'])}", "–", "–", f"{r(b15['ci95'][0])} bis {r(b15['ci95'][1])}"],
        ["Summe R", r(kp["summe_r"], 1), r(k2c1["summe_r"], 1), r(k2c3["summe_r"], 1), r(k15["summe_r"], 1)],
        ["Streuung je Trade (R)", de(kp["sd_r"], 2), de(k2c1["sd_r"], 2), de(k2c3["sd_r"], 2), de(k15["sd_r"], 2)],
        ["Trefferquote", pct(kp["trefferquote"]), pct(k2c1["trefferquote"]), pct(k2c3["trefferquote"]), pct(k15["trefferquote"])],
        ["Wilson-Intervall der Trefferquote", f"{pct(kp['trefferquote_ci95_wilson'][0])} bis {pct(kp['trefferquote_ci95_wilson'][1])}", "–", "–", f"{pct(k15['trefferquote_ci95_wilson'][0])} bis {pct(k15['trefferquote_ci95_wilson'][1])}"],
        ["Ø Gewinn / Ø Verlust (R)", f"{r(kp['mittel_gewinn_r'], 2)} / {r(kp['mittel_verlust_r'], 2)}", "–", "–", f"{r(k15['mittel_gewinn_r'], 2)} / {r(k15['mittel_verlust_r'], 2)}"],
        ["Profitfaktor", de(kp["profit_faktor"], 2), de(k2c1["profit_faktor"], 2), de(k2c3["profit_faktor"], 2), de(k15["profit_faktor"], 2)],
        ["Größter Rückgang (R)", de(kp["max_drawdown_r"], 1), de(k2c1["max_drawdown_r"], 1), de(k2c3["max_drawdown_r"], 1), de(k15["max_drawdown_r"], 1)],
        ["Dauer des längsten Rückgangs (Tage)", ganz(kp["max_drawdown_dauer_tage"]), "–", "–", ganz(k15["max_drawdown_dauer_tage"])],
        ["Kosten je Trade (R) / Stop-Abstand", f"{de(kp['kosten_r_je_trade'], 3)} / {de(kp['mittlerer_stop_abstand_prozent'], 2)} %", "–", "–", f"{de(k15['kosten_r_je_trade'], 3)} / {de(k15['mittlerer_stop_abstand_prozent'], 2)} %"],
        ["Netto je Trade in Basispunkten des Nominals", de(kp["netto_bp_je_trade_auf_nominal"], 1), "–", "–", de(k15["netto_bp_je_trade_auf_nominal"], 1)],
        ["Anteil der besten 5 % der Trades an der Summe", pct(kp["anteil_beste_5_prozent_an_summe"], 0), "–", "–", pct(k15["anteil_beste_5_prozent_an_summe"], 0)],
        ["Zeit im Markt", pct(kp["zeit_im_markt_anteil"], 0), "–", "–", pct(k15["zeit_im_markt_anteil"], 0)],
        ["Rendite nicht aufgezinst (1 % Risiko, 10.000 USDT)", de(kp["netto_rendite_nicht_aufgezinst_prozent"], 0) + " %", "–", "–", de(k15["netto_rendite_nicht_aufgezinst_prozent"], 0) + " %"]], rechts=(1, 2, 3, 4))
    n4 = d["nachtrag"]["N4"]
    o += ["C1 enthält SOL, C3 nicht; K1 und K2 sind Kostenszenarien (Abschnitt 3). T15 läuft ohne Funding (keine Historie) auf Spot-Kerzen; die Spalten sind deshalb nicht streng vergleichbar. Aufteilung nach Instrument und Jahr: Abschnitt 9.", "",
          f"Zur Zeile „Netto je Trade in Basispunkten des Nominals“: Sie ist der Mittelwert von R × Stop-Abstand je Trade, nicht E[R] mal mittlerer Stop-Abstand. Bei T15 liegt sie mit {de(k15['netto_bp_je_trade_auf_nominal'], 1)} bp weit unter dem Produkt der Mittelwerte "
          f"({de(n4['produkt_der_mittel_bp'], 0)} bp), weil weite Stopps verlieren und enge gewinnen (Korrelation von R und Stop-Abstand {de(n4['korrelation_r_stop'], 2)}; 2017 bei mittlerem Stop {de(n4['je_jahr']['2017']['mittlerer_stop_abstand_prozent'], 1)} % {de(n4['je_jahr']['2017']['netto_bp'], 0)} bp, 2019 bei {de(n4['je_jahr']['2019']['mittlerer_stop_abstand_prozent'], 1)} % {de(n4['je_jahr']['2019']['netto_bp'], 0)} bp; Nachtrag N4, nachträglich und beschreibend). "
          f"Das passt zum Befund aus T9, dass C1 im oberen Schwankungsterzil (weite Stopps) nur {r(z['terzil_hoch_e'], 2)} R je Trade bringt.", "",
          "### 5.2 Kostenempfindlichkeit (E[R] je Trade, Training / Validierung)", ""]
    zs = []
    for k, name in (("K0", "K0 Protokoll"), ("K1", "K1 Bitunix-Basis"), ("K2", "K2 konservativ"), ("K3", "K3 pessimistisch"), ("K4", "K4 Maker-Ziel (optimistisch)"), ("L1", "L1 eine Kerze Verzögerung")):
        c1, c3 = t2["C1"]["szenarien"][k], t2["C3"]["szenarien"][k]
        zs.append([name, f"{r(c1['train']['e_r'])} / {r(c1['validation']['e_r'])}", f"{r(c3['train']['e_r'])} / {r(c3['validation']['e_r'])}"])
    o += tab(["Szenario", "C1", "C3"], zs)
    bm = t2["C1"]["bruchstelle"]["null_durchgang_multiplikator"]["pooled"]
    o += [f"Die Erwartung von C1 erreicht null erst bei etwa dem {de(bm, 1)}-Fachen der K1-Kosten (Gebühr und Schlupf skaliert); die Empfindlichkeit liegt woanders: eine Kerze Verzögerung des Einstiegs senkt die Erwartung im Training um {de(100 * (1 - z['L1_train'] / z['K1_train']), 0)} % (von {r(z['K1_train'])} auf {r(z['L1_train'])} R) und löscht sie in der Validierung ({r(z['K1_valid'])} → {r(z['L1_valid'])} R).", "",
          "### 5.3 Andere Handelslisten (Training, einheitliche Kennzahlen)", "",
          "Aus den rohen Handelslisten neu ausgewertet. Je Studie sind die Varianten mit höchstem und niedrigstem E[R] gezeigt (Spannweite, keine Auswahl); alle Werte in `studien_kennzahlen.json`. Nur Training, keine Validierung geöffnet (außer wo das Register es nennt).", ""]
    zeilen = []
    for stud, varianten in d["sk"].items():
        alle = [(k, v) for k, v in varianten.items() if v.get("n")]
        items = [(k, v) for k, v in alle if v["n"] >= 30]
        if not alle:
            continue
        if not items:
            zeilen.append([stud, f"alle {len(alle)} Varianten mit n < 30 (größtes n {max(v['n'] for _, v in alle)}): nicht auswertbar", "–", "–", "–", "–", "–", "–"])
            continue
        lo = min(items, key=lambda kv: kv[1]["e_r"])
        hi = max(items, key=lambda kv: kv[1]["e_r"])
        for tag, (k, v) in (("höchster", hi), ("niedrigster", lo)) if len(items) > 1 else (("einzige", hi),):
            zeilen.append([stud, f"{k} ({tag} E[R] von {len(items)})" if len(items) > 1 else k, ganz(v["n"]), r(v["e_r"]), de(v["profit_faktor"], 2) if v.get("profit_faktor") is not None else "–",
                           pct(v["trefferquote"], 0), dsep(v["max_drawdown_r"], 1), de(v["kosten_r_je_trade"], 2) if v.get("kosten_r_je_trade") is not None else "–"])
    o += tab(["Studie", "Variante", "n", "E[R]", "PF", "Treffer", "Rückgang R", "Kosten R/Trade"], zeilen, rechts=(2, 3, 4, 5, 6, 7))
    o += ["Varianten mit n unter 30 sind nicht auswertbar und fehlen in dieser Tabelle; sie stehen vollständig in `studien_kennzahlen.json`.", "",
          "### 5.4 Einfache Referenzen und Carry (risikogleich, 2020 bis 2024, gepoolt)", ""]
    t10, t11 = d["t10"], d["t11"]
    ref = t10["referenzen"]
    o += tab(["Strategie", "Summe in %", "Sharpe je Jahr", "Größter Rückgang in %"], [
        ["C1 (Trendregel)", de(z["c1_rendite"], 0), de(z["c1_sharpe"], 2), de(z["c1_dd"], 1)],
        ["R1 Kaufen und Halten (BTC/ETH/SOL gleichgewichtet)", de(z["r1_rendite"], 0), de(z["r1_sharpe"], 2), de(z["r1_dd"], 1)],
        ["R2 SMA200 lang/flat (gleicher Korb)", de(z["r2_rendite"], 0), de(z["r2_sharpe"], 2), de(z["r2_dd"], 1)]], rechts=(1, 2, 3))
    o += [f"Alle auf die Tagesschwankung von C1 skaliert (Hebel höchstens 3). Gegen die einfache Referenz R2 liegt die Trendregel bei Rendite und Sharpe zurück. "
          f"Carry (BTC+ETH, Spot long / Perp short), Rendite je Jahr auf das gebundene Kapital (Training / Validierung): konstante Stückzahl {pct(z['carry_konst_train'])} und {pct(z['carry_konst_valid'])} (verdeckter Hebel, siehe Abschnitt 4), "
          f"konstantes Nominal monatlich neu abgesichert {pct(z['carry_monat_train'])} und {pct(z['carry_monat_valid'])}; Geldmarkt (ANNAHME) {pct(z['geld_train'])} und {pct(z['geld_valid'])}.", ""]
    return o


def abschnitt6(d: dict) -> list[str]:
    m = d["mat"]
    o = ["## 6. Evidenzmatrix der tragfähigen Erkenntnisse", "",
         f"Erzeugt aus den Ergebnisdateien und dem Register: {len(m['zeilen'])} Erkenntnisse, alle {m['abdeckung']['gefunden']} gefundenen Studien und Berichte sind mindestens einer Erkenntnis zugeordnet. "
         "Je Erkenntnis: unterstützende Studien, Gegenbelege, Datenüberschneidung, Unsicherheit, praktische Konsequenz und Evidenzstand in den vier Stufen. Volltext: `EVIDENZMATRIX.md`, Maschinenlesbar: `evidenzmatrix.json`.", ""]
    o += tab(["Nr", "Erkenntnis", "Richtung", "Evidenzstand"], [[x["nr"], x["erkenntnis"], x["richtung"], x["evidenzstand"]] for x in m["zeilen"]])
    o += ["Lesehilfe: Die einzige Erkenntnis mit positiver Richtung und eigener Nachrechnung ist E1 (Trendregel). Sie ist **eine** Evidenzquelle; E1b (T15) und E2 (S32) sind ihre beiden Prüfungen außerhalb der Entwicklung mit gemischtem Ergebnis. "
          "Alle anderen Zeilen mit eigener Rechnung sind negativ (E3 bis E6, E9, E13) oder ohne Handelsaussage.", ""]
    return o


def abschnitt7(d: dict) -> list[str]:
    o = ["## 7. Herleitung der konsolidierten Kandidaten", "",
         "**Regel der Auswahl (vor jeder Auswertung festgelegt):** Es kommen nur Regeln in Frage, die (1) eine Handelsliste mit ausreichend Trades haben, (2) vorab mit Bestehensregel geprüft wurden, (3) nicht schon an ihrem eigenen Gate oder in der Validierung gescheitert sind und (4) vollständig spezifizierbar sind. "
         "Von allen Familien erfüllt nur die Trendregel S7b-D20-T3 diese Bedingungen; die Level-, Orderflow-, Indikator- und frühen Familien sind gescheitert, am Gate hängen geblieben oder haben n < 100. Höchstens drei Kandidaten, Hebel ist kein Vorteil:", ""]
    o += tab(["Kandidat", "Inhalt", "Herkunft und Grund"], [
        ["**C1**", "S7b-D20-T3 unverändert auf BTC, ETH, SOL (4h), höchstens eine Position, Vorrang BTC > ETH > SOL", "Kern des Trend-Datenclusters; die Regel, die im Labor als Kandidat läuft und im Vorwärtsjournal beobachtet wird."],
        ["**C2**", "C1 plus 50 % des Kapitals im Funding-Carry (BTC+ETH, Spot long / Perp short)", "Einziges weiteres Ergebnis mit positiver Kapitalrendite. Carry ist Kapitalrendite mit Basis- und Gegenparteirisiko, kein Vorteil; wird getrennt bewertet (CG1, CG2, G10)."],
        ["**C3**", "C1 nur auf BTC und ETH", "Weniger Auswahl im Nachhinein (SOL fehlt); die einzige Variante, die außerhalb der Entwicklung getestet werden kann, weil SOL 2017 bis 2019 nicht existierte (T15)."]])
    o += ["**Nicht ausgewählt und warum:** OF2 (n 56, nicht belegt, Tiefe B), S31-Regeln (n < 100), OFX (kein Kandidat), S34/S35a/S36 (negativ nach Kosten), S38 (knapp positiv, Band über null nicht erreicht), S7b-Makro F5 (Mehrfachtest nicht bestanden), "
          "Plan-Journale und Schatten (Auswahleffekte, n klein), GARCH und KI (Anzeige, kein Handelsvorteil). Es gab keine Optimierung: Parameter von C1 bis C3 sind die der ursprünglichen Präregistrierung (S7b), das Raster in T4 dient nur der Stabilitätsprüfung.", "",
          "**Spezifikation:** vollständig in Abschnitt 11 (Parameter, Kosten, Datenbedarf).", ""]
    return o


def abschnitt8(d: dict) -> list[str]:
    s, t15 = d["stand"], d["t15"]["meta"]
    o = ["## 8. Vorab festgelegtes Validierungsprotokoll", "",
         f"`PROTOKOLL_KONSOLIDIERUNG.md` Version 1.0 wurde im Commit `{s['git_commit'][:7]}` eingefroren ({s['eingefroren_utc'].replace('T', ' ').replace('Z', ' UTC')}, SHA-256 `{s['sha256']}`), **bevor** die Tests T2 bis T13 liefen. "
         "Vor dem Einfrieren gerechnet und deshalb als berichtet, nicht als vorab festgelegt ausgewiesen: " + "; ".join(s["vor_dem_einfrieren_gerechnet"]) + ". "
         "Das Ergebnis von G8 (S32 negativ) lag ebenfalls vor und wurde als bekannt in das Protokoll geschrieben.", ""]
    o += tab(["Teil", "Festlegung"], [
        ["Kandidaten", "C1, C2, C3 (Abschnitt 7); keine Auswahl nach Ergebnis, alle drei werden mit denselben Kriterien berichtet."],
        ["Optimierungsbudget", "null; kein Parameter wird angepasst."],
        ["Kosten", "K0 bis K4 und L1; G2 prüft K2."],
        ["Kriterien", "G1 Reproduktion; G2 E[R] > 0 unter K2 in Training und Validierung; G3 Zufallsvergleich p ≤ 0,05 in beiden; G4 mindestens 70 % der 81 Nachbarzellen positiv; G5 positiv bei Weglassen jedes Jahres und Instruments; "
         "G6 untere 95-%-Grenze des gepoolten Monatsblock-Bootstraps über 0; G7 Deflated Sharpe (N = 64) mindestens 0,95; G8 Übertragung auf unabhängiges Universum (S32); G11 Bitunix-Übertragbarkeit; für C2 CG1, CG2, G10."],
        ["Stufen", "1 Kein belastbarer Vorteil; 2 Interessante Hypothese, Evidenz unzureichend; 3 Historisch robust, prospektiver Test ausstehend; 4 Für begrenztes Paper-Trading geeignet: Stufe 3 und eine vorab festgelegte Vorwärts-Mindestzahl (mindestens 30 geschlossene Papier-Trades mit E[R] > 0 unter K2 und Zahl der Stopps im erwarteten Bereich) oder ein einmaliger, von Uzi und Barti freigegebener Holdout-Lauf mit vorab festgelegten Kriterien (so im Wortlaut des Protokolls)."],
        ["Statistik", "Monatsblock-Bootstrap 10.000 Ziehungen, Seed 20261116; Zufallsvergleich 1.000 Ziehungen; eigene DSR-Rechnung; keine p-Wert-Korrektur über T2 bis T14, weil die Kriterien eine Schnittmenge bilden."],
        ["Abbruch", "Reproduktion weicht ab oder Datenintegritätsfehler: Auswertung der betroffenen Reihe stoppt, Befund wird berichtet. Ein Test, der den Holdout bräuchte, wird nicht gerechnet."],
        ["Nicht entfernt", "Fehlgeschlagene Studien und Varianten bleiben im Register und in der Matrix."]])
    o += [f"**Zusatzprotokoll T15 (1.1-T15)**, eingefroren im Commit `ceed9f9` am 16.11.2026 um 14:10 UTC, **vor dem Laden** der Spot-Daten 2017 bis 2019 (Dateizeit im Container 14:13 UTC): ein Lauf, Kandidat C3, primäre Kosten K2 ohne Funding, "
          f"einziges Bestehenskriterium P1 (E[R] > 0 und einseitiges Monatsblock-p ≤ 0,05), berichtet P2 bis P8, Einordnung in drei Klassen vorab. Der Datenbericht (Commit `3fb2198`) und der Code (Commit `b0e8575`) wurden vor dem Lauf festgehalten; der Lauf verweigert den Start, wenn eine Vorbedingung fehlt "
          f"und wenn schon ein Ergebnis vorliegt. T15 ändert keines der Kriterien G1 bis G11 und keine Stufe.", "",
          "**Grenzen des Protokolls:** Die Entwicklungsdaten 2020 bis 2024 waren dem Labor und uns aus S7b und S32 bekannt; die Validierung 2023 bis 2024 ist mehrfach verbraucht. Das Protokoll prüft deshalb Robustheit (G2 bis G7), nicht Neuheit. "
          "Als Bestätigung außerhalb der Entwicklung zählen nur T15 (Spot 2017 bis 2019) und ein künftiger, einmaliger Holdout; bisher ist keines davon bestanden.", ""]
    return o


def abschnitt9(d: dict) -> list[str]:
    z, t2, t5, t6, t9, t11, t12, t13, t15 = d["z"], d["t2"], d["t5"], d["t6"], d["t9"], d["t11"], d["t12"], d["t13"], d["t15"]["ergebnis"]
    p1, p3, p4, p6, p8 = t15["p1"], t15["p3"], t15["p4"], t15["p6"], t15["p8"]
    o = ["## 9. Ergebnisse inklusive negativer und widersprüchlicher Befunde", "", "### 9.1 Trendregel im Entwicklungszeitraum 2020 bis 2024 (T1 bis T9)", ""]
    o += tab(["Test", "Befund", "Wertung"], [
        ["T1 Reproduktion", f"{ganz(d['t1']['gesamt']['trades_gespeichert'])} Trades, Abweichung {de(d['t1']['gesamt']['max_abw_r'], 1)} R", "positiv, G1 bestanden"],
        ["T2 Kosten", f"K2 Training {r(z['K2_train'])} / Validierung {r(z['K2_valid'])}; K3 {r(z['K3_train'])} / {r(z['K3_valid'])}; Nullpunkt beim {de(z['bruch_mult'], 1)}-Fachen der K1-Kosten", "positiv, G2 bestanden"],
        ["T3 Zufallseinstiege (C1)", f"p {de(z['zufall_p_train'])} / {de(z['zufall_p_valid'])}; Zufallsmittel Training {r(z['zufall_e_train'])} R (Regel {r(z['K1_train'])}), Validierung {r(z['zufall_e_valid'])} R (Regel {r(z['K1_valid'])}), alle unter K1. **C3:** Training Zufall {r(z['c3_zufall_e_train'])} R gegen Regel {r(z['c3_K1_train'])} R, p {de(z['c3_zufall_p_train'])}; Validierung {r(z['c3_zufall_e_valid'])} R gegen {r(z['c3_K1_valid'])} R, p {de(z['c3_zufall_p_valid'])}", "positiv für C1; für C3 G3 im Training nicht bestanden"],
        ["T4 Raster", f"{pct(z['nachbarn_train'])} / {pct(z['nachbarn_valid'])} der Nachbarzellen positiv, {pct(z['raster_pooled'])} aller 600 Zellen; C1 liegt bei Rang {pct(z['rang_pooled'], 0)}, nicht an der Spitze", "positiv, G4 bestanden"],
        ["T5 Komponenten", f"Ohne SMA200-Filter {r(t5['ohne SMA200-Filter']['pooled']['e_r'])} R (n {t5['ohne SMA200-Filter']['pooled']['n']}), nur long {r(t5['nur long']['pooled']['e_r'])}, nur short {r(t5['nur short']['pooled']['e_r'])}, nur SOL {r(t5['nur SOL (allein gerechnet)']['pooled']['e_r'])}, "
         f"gespiegelte Reihenfolge der Instrumente {r(t5['gespiegelte Reihenfolge (SOL > ETH > BTC)']['pooled']['e_r'])}", "gemischt: der Ausbruch trägt allein, die Positionsreihenfolge verschiebt das Ergebnis um 0,06 R"],
        ["T6 Konzentration", f"Beste 5 % der Trades = {pct(z['top5_anteil'])} der Summe; ohne die besten 10 Trades {r(t6['ohne_beste_trades']['10']['e_r'])}, ohne die besten 25 {r(t6['ohne_beste_trades']['25']['e_r'])} R; 2020 liefert {de(z['jahr2020_r'], 0)} von {de(z['summe_r_pooled'], 0)} R, "
         f"2021 {de(t6['summe_r_je_jahr']['2021'], 1)} R; {t6['monate_positiv']} von {t6['monate_gesamt']} Monaten positiv", "G5 bestanden (jedes Jahr und Instrument weglassbar), aber stark konzentriert"],
        ["T7 Unsicherheit", f"Band {r(z['ci_lo'])} bis {r(z['ci_hi'])} R (Monatsblock); Newey-West t {de(z['nw_t'], 2)}", "positiv, G6 bestanden"],
        ["T8 Mehrfachtest", f"DSR (N = 64) Training {de(z['dsr_n64_train'], 2)}, Validierung {de(z['dsr_n64_valid'], 2)}, gepoolt {de(z['dsr_n64_pooled'], 2)}; bei N = 26.707 {de(z['dsr_nmax_pooled'], 2)}. Der Laborbericht `deflated_sharpe_2026-11-11.md` nennt 0,81 (N = 64, beide Abschnitte gemeinsam; nur berichtet); keine Rechnung erreicht 0,95", "**nicht bestanden, G7**"],
        ["T9 Regime", f"2021 {r(z['jahr2021_e'], 2)} R je Trade, hohes Volatilitätsterzil {r(z['terzil_hoch_e'], 2)} R; Long {r(z['long_e'], 2)}, Short {r(z['short_e'], 2)}; schlechtestes gleitendes 6-Monats-E[R] {r(t9['gleitend_min_e_r'], 2)}", "beschreibend: nicht in jedem Regime wirksam"],
        ["G8 Übertragung (S32)", f"{r(z['s32_e'], 4)} R bei n {ganz(z['s32_n'])}, Zufalls-p {de(z['s32_p'])}, Band {r(z['s32_ci_lo'])} bis {r(z['s32_ci_hi'])} R; nur berichtet", "**nicht bestanden**"],
        ["T10 Referenzen", f"C1 Sharpe {de(z['c1_sharpe'], 2)}, R2 (SMA200 lang/flat) {de(z['r2_sharpe'], 2)}, R1 (Korb) {de(z['r1_sharpe'], 2)}", "kein Vorsprung gegen die einfache Referenz"],
        ["T13 Bitunix (G11)", f"E[R] auf Bitunix-Kerzen {r(z['bx_e'], 4)} gegen Binance {r(z['bn_e'], 4)} (Δ {r(z['bx_delta'], 3)} R); Mindestkontrakt bei 1.000 USDT ausführbar", "bestanden; Gebühren, Funding, Stressausführung offen"]])
    o += ["![Netto-Verlauf, Drawdown und Referenzen](grafiken/g1_netto_verlauf.png)", "",
          "*Abb. 1: Kumulierter Nettoertrag von C1 und den risikogleichen Referenzen (gleiche Skalierung auf die Tagesschwankung).*", "",
          "![Größter Rückgang](grafiken/g2_drawdown.png)", "", "*Abb. 2: Rückgänge von der jeweiligen Spitze (Tagesreihe), C1 gegen Referenzen.*", "",
          "![Kostensensitivität](grafiken/g3_kostensensitivitaet.png)", "", "*Abb. 3: E[R] je Trade bei steigenden Kosten und in den Szenarien K0 bis L1, Training und Validierung.*", "",
          "![Zeitliche Stabilität](grafiken/g4_zeitliche_stabilitaet.png)", "", "*Abb. 4: E[R] und Summe je Jahr und im gleitenden 6-Monatsfenster; 2021 liegt unter null.*", "",
          "![Zufall und Raster](grafiken/g5_zufall_und_raster.png)", "", "*Abb. 5: Zufallseinstiege in SMA200-Richtung gegen die Regel (links) und Verteilung des E[R] über 600 Raster-Zellen (rechts).*", "",
          "### 9.2 Test außerhalb der Entwicklung (T15, ein Lauf)", "",
          f"**Einordnung nach Zusatzprotokoll: {t15['einordnung']['klasse']}.** {t15['einordnung']['text']}", ""]
    o += tab(["Kriterium", "Ergebnis"], [
        ["**P1** (einziges Bestehenskriterium)", f"E[R] unter K2 (Funding aus) {r(p1['e_r'])} R > 0: **ja**; einseitiges Monatsblock-p {de(p1['p_monatsblock_bootstrap_einseitig'], 4)} ≤ 0,05: **nein** ({p1['ziehungen_mit_mittel_nicht_positiv']} von {ganz(10000)} Ziehungen mit Mittel ≤ 0). n {p1['n']}, "
         f"95-%-Band {r(p1['ci95_bootstrap'][0])} bis {r(p1['ci95_bootstrap'][1])} R. **P1 nicht erfüllt.**"],
        ["P2 andere Kosten", f"K1: {r(t15['p2']['K1']['e_r'])} R (n {t15['p2']['K1']['n']}); K0: {r(t15['p2']['K0']['e_r'])} R (n {t15['p2']['K0']['n']})"],
        ["P3 Zufallseinstiege in SMA200-Richtung", f"Regel (K1) {r(p3['kandidat_e_r'])} R, Zufall im Mittel {r(p3['e_r_zufall_mittel'])} R (90-%-Spanne {r(p3['e_r_zufall_ci90'][0])} bis {r(p3['e_r_zufall_ci90'][1])}), {pct(p3['anteil_ziehungen_positiv'], 0)} der Ziehungen positiv; p {de(p3['p_einseitig'], 3)}: "
         "die Regel schlägt zufällige Einstiege in Trendrichtung **nicht**"],
        ["P4 je Jahr (Signaljahr)", "; ".join(f"{j}: {r(v['e_r'], 2)} R (n {v['n']})" for j, v in p4["je_jahr"].items())],
        ["P5 größter Rückgang", f"{de(t15['p5']['max_drawdown_r'], 1)} R über {ganz(t15['p5']['max_drawdown_dauer_tage'])} Tage; Bootstrap-Median {de(t15['p5']['bootstrap_max_drawdown_r']['median'], 1)} R, 95. Perzentil {de(t15['p5']['bootstrap_max_drawdown_r']['p95'], 1)} R"],
        ["P6 Funding-Sensitivität", f"Abzug des mittleren Funding-Kostenanteils der Regel 2020 bis 2024 ({de(p6['funding_kostenanteil_je_trade_r'], 3)} R je Trade, K2 ohne Gutschrift): E[R] {r(p6['e_r_nach_funding_abzug'])} R; "
         f"ergänzend (nicht vorab festgelegt) p {de(p6['ergaenzend_bootstrap_nach_abzug']['p_einseitig'], 3)}. Abgleich der Quellrechnung mit T2: n {p6['abgleich_t02']['n_t02']}, E[R] {r(p6['abgleich_t02']['e_r_t02'], 4)}, gleich: {'ja' if p6['abgleich_t02']['gleich'] else 'nein'}"],
        ["P7 Trefferquote und Gewinnstruktur", f"Treffer {pct(t15['p7']['trefferquote'])} (Wilson {pct(t15['p7']['trefferquote_ci95_wilson'][0])} bis {pct(t15['p7']['trefferquote_ci95_wilson'][1])}), Profitfaktor {de(t15['p7']['profit_faktor'], 2)}, "
         f"Ø Gewinn {r(t15['p7']['mittel_gewinn_r'], 2)} R, Ø Verlust {r(t15['p7']['mittel_verlust_r'], 2)} R, Median {r(t15['p7']['median_r'], 2)} R, beste 5 % der Trades = {pct(t15['p7']['anteil_beste_5_prozent_an_summe'], 0)} der Summe"],
        ["P8 je Instrument und Seite", f"BTC {r(p8['je_symbol']['BTCUSDT']['e_r'], 2)} R (n {p8['je_symbol']['BTCUSDT']['n']}), ETH {r(p8['je_symbol']['ETHUSDT']['e_r'], 2)} R (n {p8['je_symbol']['ETHUSDT']['n']}); "
         f"Long {r(p8['je_seite']['1']['e_r'], 2)} R (n {p8['je_seite']['1']['n']}), Short {r(p8['je_seite']['-1']['e_r'], 2)} R (n {p8['je_seite']['-1']['n']}); Ausstiege: Stop {p8['je_grund']['stop']['n']}, Ziel {p8['je_grund']['target']['n']}, Zeitstopp {p8['je_grund']['time']['n']}"],
        ["Aussagekraft", f"n {t15['aussagekraft_nachtraeglich']['n']} (Zusatzprotokoll schätzte 195, der Datenbericht 143); kleinste bei 80 % Power nachweisbare Erwartung {r(t15['aussagekraft_nachtraeglich']['kleinste_bei_80_prozent_power_nachweisbare_erwartung_r'], 2)} R. "
         "Das Band enthält null **und** den Wert 0,21 aus 2020 bis 2024: kein Nachweis, keine Widerlegung."]])
    o += ["![T15 außerhalb der Entwicklung](grafiken/g8_t15_ausserhalb.png)", "",
          "*Abb. 6: T15, kumulierte Nettosumme der 157 Trades 2017 bis 2019 (links) und Zufallseinstiege in SMA200-Richtung (rechts).*", "",
          "### 9.3 Widersprüche und wie sie zu lesen sind", "",
          f"- **Positiv gegen negativ:** Im Entwicklungszeitraum schlägt C1 zufällige Einstiege in SMA200-Richtung mit gleicher Ausstiegsregel (p {de(z['zufall_p_train'])} / {de(z['zufall_p_valid'])}; "
          f"Zufallsmittel {r(z['zufall_e_train'])} / {r(z['zufall_e_valid'])} R gegen {r(z['K1_train'])} / {r(z['K1_valid'])} R der Regel, alle unter K1). Auf derselben Basis wie T15 (C3, BTC/ETH): Training Zufall {r(z['c3_zufall_e_train'])} R gegen Regel {r(z['c3_K1_train'])} R (p {de(z['c3_zufall_p_train'], 3)}, knapp nicht signifikant), "
          f"Validierung {r(z['c3_zufall_e_valid'])} R gegen {r(z['c3_K1_valid'])} R (p {de(z['c3_zufall_p_valid'], 3)}). In T15 ist es umgekehrt: Zufall {r(p3['e_r_zufall_mittel'])} R, Regel {r(p3['kandidat_e_r'])} R (K1, p {de(p3['p_einseitig'], 2)}). "
          "Mit den Daten vereinbar sind drei Lesarten: (a) der Wert des Ausbruchszeitpunkts hängt vom Marktabschnitt ab; (b) ein Teil des Entwicklungsvorteils ist Auswahl im Nachhinein (Coins, Zeitraum und Regelfamilie waren bekannt); "
          "(c) 2017 bis 2019 trugen Trendseite und Auszahlungsgeometrie allein, weil die Märkte stark trendeten. Die Daten entscheiden nicht zwischen ihnen; jede Lesart ist eine Hypothese, kein Beweis.",
          f"- **Stärkster Einwand und Gegenargument:** Die einfache Referenz R2 (SMA200 lang/flat) hat den höheren Sharpe ({de(z['r2_sharpe'], 2)} gegen {de(z['c1_sharpe'], 2)} für C1): Die Trendseite allein erklärt auf Tagesbasis mindestens so viel wie die Regel, und in T15 liegt der Zufall vorn. "
          f"Das spricht dafür, dass ein Vorteil vor allem Trendseite und Auszahlungsgeometrie ist. Dagegen steht die geringe Aussagekraft von T15: n {t15['p1']['n']}, die 90-%-Spanne der Zufallsmittel reicht von {r(p3['e_r_zufall_ci90'][0])} bis {r(p3['e_r_zufall_ci90'][1])} R und enthält den Wert der Regel; "
          f"die kleinste bei 80 % Power nachweisbare Erwartung ist {r(t15['aussagekraft_nachtraeglich']['kleinste_bei_80_prozent_power_nachweisbare_erwartung_r'], 2)} R. p {de(p1['p_monatsblock_bootstrap_einseitig'], 3)} und der fehlende Vorsprung sind daher kein Beleg gegen die Regel; T15 hat zu wenig Aussagekraft, um zwischen den Lesarten zu entscheiden.",
          "- **Plateau gegen Verzögerung:** Die Regel ist gegen Parameteränderungen robust, aber empfindlich gegen eine Kerze Verzögerung (Validierung −0,007 R). Für die Ausführung bedeutet das: Latenz und Schlupf beim Einstieg sind wichtiger als die Wahl der Parameter.",
          "- **Mehrere Studien, eine Quelle:** S7, S7b, S25, S7b-Makro, S32 und T1 bis T15 nutzen denselben Trend-Datencluster; ihre Übereinstimmung ist keine unabhängige Bestätigung.",
          "- **Gegen alle Erwartung nicht gefunden:** Weder bei Orderflow (OF2/OFX/S19/S31), Indikator-Merkmalen (S20 bis S28), Level-Regeln (S30, S34 bis S38) noch bei frühen Familien (R4, S4, S6, S13, S14) gab es nach Kosten einen belegten Vorteil. "
          "OF2 (n 56, +0,27 R) und S38 (+0,09 R, n 191) sind die einzigen positiven Zahlen und beide nicht von null unterscheidbar.", ""]
    return o


def abschnitt10(d: dict) -> list[str]:
    z, t7, t15 = d["z"], d["t7"], d["t15"]["ergebnis"]
    tpm = z["trades_pro_monat"]
    kb_c1 = kapitalbedarf(z["K1_pooled"], tpm, 0.01)
    kb_t15 = kapitalbedarf(t15["p1"]["e_r"], t15["primaer_k2"]["kennzahlen"]["trades_pro_monat"], 0.01)
    kb_lo = kapitalbedarf(z["ci_lo"], tpm, 0.01)
    holdout_n = holdout_trades(tpm)
    n80_a, n80_b = n_trades_bis_power(0.24, 1.72), n_trades_bis_power(t15["p1"]["e_r"], t15["primaer_k2"]["kennzahlen"]["sd_r"])
    o = ["## 10. Unsicherheit, Robustheit und praktische Grenzen", "", "### Statistische Unsicherheit", "",
         f"- **Erwartung je Trade:** C1 {r(z['K1_pooled'])} R (95-%-Band {r(z['ci_lo'])} bis {r(z['ci_hi'])} R, K1); T15 {r(t15['p1']['e_r'])} R (Band {r(t15['p1']['ci95_bootstrap'][0])} bis {r(t15['p1']['ci95_bootstrap'][1])} R, K2). Die Bänder überlappen zwischen {r(max(z['ci_lo'], t15['p1']['ci95_bootstrap'][0]), 2)} und {r(min(z['ci_hi'], t15['p1']['ci95_bootstrap'][1]), 2)} R: Eine gemeinsame wahre Erwartung in diesem Bereich ist mit beiden Stichproben vereinbar, "
         "für T15 allein auch eine Erwartung nahe null. (Die Stichproben unterscheiden sich in Daten, Kosten und Funding und sind nur bedingt vergleichbar.)",
         f"- **Stichprobengröße für einen Nachweis:** Bei Streuung {de(1.72, 2)} R je Trade braucht ein einseitiger Test zum Niveau 5 % mit 80 % Power für eine wahre Erwartung von +0,24 R rund {n80_a} Trades "
         f"(bei {de(tpm, 1)} Trades im Monat etwa {de(n80_a / tpm / 12, 1)} Jahre); für die in T15 beobachteten {r(t15['p1']['e_r'], 2)} R wären es rund {n80_b} Trades (etwa {de(n80_b / tpm / 12, 0)} Jahre). 30 Trades haben nur etwa {pct(power(0.24, 1.72, 30), 0)} Power: "
         "die Mindestzahl 30 für Stufe 4 ist eine Plausibilitätsschranke, kein Nachweis.",
         f"- **Holdout:** Das Protokoll sieht 2025-01-01 bis 2026-09 vor; für die Aussagekraft zählt nur der bis dahin ungesehene Teil 2025-01 bis 2026-06 (18 Monate). Er ergäbe etwa {holdout_n} Trades (C1) und damit eine Power von nur etwa {pct(power(0.24, 1.72, holdout_n), 0)} bei +0,24 R und {pct(power(0.15, 1.72, holdout_n), 0)} bei +0,15 R; "
         f"die kleinste bei 80 % Power nachweisbare Erwartung wäre etwa {r((Z95 + Z80) * 1.72 / math.sqrt(holdout_n), 2)} R. Juli bis Oktober 2026 ist durch die S7b-Sonde schon gesehen und müsste getrennt ausgewiesen werden. Ein Fehlschlag widerlegte also kleinere Vorteile nicht.",
         "- **Mehrfachtest:** Laut Überzeugungsregister (NUR BERICHTET, nicht nachgezählt) mehr als 150 Prüfungen auf BTC 2020 bis 2024 ohne fortlaufenden Gesamtzähler, dazu die Orderflow-Suche (26.707 Konfigurationen beim Einfrieren des Protokolls, 27.023 in der Kopie vom 16.11.) "
         f"und die mehrfach verbrauchte Validierung: Das macht jede p-Aussage optimistisch; die Deflated-Sharpe-Werte bei N = 64 ({de(z['dsr_n64_train'], 2)} / {de(z['dsr_n64_valid'], 2)}) sind die ehrlichere Zahl, und G7 scheitert schon bei N = 58 ({de(z['dsr_n58_train'], 2)} / {de(z['dsr_n58_valid'], 2)}).", "",
         "### Drawdown-Risiko", ""]
    o += tab(["Größe", "Wert"], [
        ["C1 gepoolt 2020–24, größter Rückgang", f"{de(z['dd_r_pooled'], 1)} R, Dauer {ganz(t7['pooled']['kennzahlen']['max_drawdown_dauer_tage'])} Tage"],
        ["C1 Monatsblock-Bootstrap", f"Median {de(t7['pooled']['monatsblock_bootstrap']['max_drawdown_r']['median'], 1)} R, 95. Perzentil {de(t7['pooled']['monatsblock_bootstrap']['max_drawdown_r']['p95'], 1)} R "
         f"(2.000 Ziehungen; wenn alle Kalendermonate ein Los bekommen: Median {de(d['nachtrag']['N1']['C1_pooled']['alle_monate']['max_drawdown_r']['median'], 1)} R, 95. Perzentil {de(d['nachtrag']['N1']['C1_pooled']['alle_monate']['max_drawdown_r']['p95'], 1)} R, Nachtrag N1)"],
        ["C3 T15 2017–19", f"{de(t15['p5']['max_drawdown_r'], 1)} R über {ganz(t15['p5']['max_drawdown_dauer_tage'])} Tage; Bootstrap 95. Perzentil {de(t15['p5']['bootstrap_max_drawdown_r']['p95'], 1)} R"],
        ["In Prozent des Kontos bei 1 % Risiko je Trade", f"etwa {de(z['dd_r_pooled'], 0)} % historisch, etwa {de(t7['pooled']['monatsblock_bootstrap']['max_drawdown_r']['p95'], 0)} % im 95. Perzentil"],
        ["Verlustserien", f"Trefferquote nur {pct(d['t7']['pooled']['kennzahlen']['trefferquote'], 0)}: lange Serien von Stopps sind normal; der schlechteste Monat kostete {de(abs(d['t6']['schlechtester_monat']['summe_r']), 1)} R"]])
    o += ["### Das Ziel von 50 USDT je Tag", "",
          "Das Ziel ist ein Richtwert, keine Pflicht; Tage ohne Setup bleiben Tage ohne Trade. Reine Arithmetik, **wenn** die jeweilige Erwartung wahr wäre (keine Prognose):", ""]
    o += tab(["Annahme", "R je Jahr", "USDT je R für 50 USDT/Tag", "Kapital bei 1 % Risiko je Trade"], [
        [f"C1, E[R] {r(z['K1_pooled'], 2)} (K1, {de(tpm, 1)} Trades/Monat)", de(kb_c1["jahres_r"], 1), ganz(kb_c1["usdt_je_r"]), ganz(kb_c1["kapital_usdt"]) + " USDT"],
        [f"C1 mit Untergrenze des Bandes {r(z['ci_lo'], 2)}", de(kb_lo["jahres_r"], 1), ganz(kb_lo["usdt_je_r"]), ganz(kb_lo["kapital_usdt"]) + " USDT"],
        [f"C3 wie in T15, E[R] {r(t15['p1']['e_r'], 2)} (K2, {de(t15['primaer_k2']['kennzahlen']['trades_pro_monat'], 1)} Trades/Monat)", de(kb_t15["jahres_r"], 1), ganz(kb_t15["usdt_je_r"]), ganz(kb_t15["kapital_usdt"]) + " USDT"]], rechts=(1, 2, 3))
    o += [f"Auf einem Konto von 10.000 USDT wären dafür {de(100 * z['risiko_noetig_10k'], 1)} % Risiko je Trade nötig; der historische Rückgang von {de(z['dd_r_pooled'], 0)} R entspräche dann {pct(z['dd_bei_10k'], 0)} des Kontos. "
          "Das Ziel ist mit der Trendregel und kleinem Kapital nicht erreichbar, auch wenn der Vorteil echt ist; Hebel erhöht das Risiko, nicht die Erwartung.", "",
          "### Praktische Grenzen und offene Voraussetzungen für Bitunix", ""]
    o += tab(["Punkt", "Stand"], [
        ["Gebühren", "VIP0 Taker 0,06 %, Maker 0,02 % stammen von Uzi (10.11.2026), im Code `FEES_VERIFIED = False`; **keine Kontoprüfung möglich**. Unbekannt heißt hier nie null: K1 und K2 rechnen mit 0,06 % je Seite."],
        ["Funding", "Bitunix liefert keine öffentliche Funding-Historie in den vorhandenen Daten; Binance dient als Stellvertreter. Einheit der Rate in der API unklar (Dezimal oder Prozent). Offene Voraussetzung."],
        ["Kerzen und Kontrakte", f"E[R] auf Bitunix-Kerzen {r(z['bx_e'], 4)} gegen Binance {r(z['bn_e'], 4)}; Mindestkontrakt bei 1.000 USDT und 1 % Risiko ausführbar. Kerzen vor dem Kontraktstart (2024-06-26) vermutlich Index-Kerzen (ANNAHME)."],
        ["Ausführung", "Spread und Marktorder-Schlupf nur aus einer Momentaufnahme von etwa 90 Sekunden in ruhigem Markt (BTC 0,016 bp, ETH 0,056 bp, SOL 1,41 bp). Keine Messung zu Nachrichtenzeiten, Nacht, Wochenende, Stop-Marktorder bei Spitzen; Orderarten, Latenz, Teilfüllung und Reduce-only nicht geprüft. Da eine Kerze Verzögerung die Erwartung vernichtet, ist das die kritischste offene Frage."],
        ["Regime und Auswahl", "Alle Instrumente im Nachhinein gewählt (BTC, ETH, SOL überlebten); BTC und ETH sind stark korreliert; 2021 negativ; 2020 trägt fast die Hälfte der Summe."],
        ["Spot gegen Perpetual (T15)", "T15 läuft auf Spot-Kerzen; Basis, Funding, Leerverkauf und Liquidation sind nicht abgebildet."]])
    return o


def abschnitt11(d: dict) -> list[str]:
    z = d["z"]
    o = ["## 11. Vollständig spezifizierte bevorzugte Strategie, falls gerechtfertigt", "",
         "**Rechtfertigung:** Als Handelsstrategie ist nichts gerechtfertigt (Stufe 2, kein Echtgeld). Als **Beobachtungskandidat** für das laufende Papier-Vorwärtsjournal ist C1 gerechtfertigt, weil die Strategie bereits vorab festgelegt ist, "
         "keine Entwicklungsfreiheitsgrade mehr hat und der Papierlauf nichts kostet. C3 wird als zweites virtuelles Portfolio aus denselben Kerzen mitgeführt, damit die Variante ohne SOL ohne neuen Test beurteilt werden kann. "
         "Die Spezifikation ist die der Präregistrierung S7b und des Protokolls 1.0; **kein Parameter darf geändert werden** (eine Änderung ist eine neue Version und beginnt die Zählung von vorn).", ""]
    o += tab(["Baustein", "Festlegung"], [
        ["Version", "S7b-D20-T3, Protokoll 1.0; Hash der Konfiguration wird im Journal festgehalten; Änderung = neue Version"],
        ["Märkte", "Bitunix USDT-M-Perpetuals BTCUSDT, ETHUSDT, SOLUSDT (C1); BTCUSDT, ETHUSDT (C3). Datenquelle zur Bewertung: Kerzen des Handelsplatzes, Referenz Binance USD-M"],
        ["Zeitrahmen", "4h-Kerzen im UTC-Raster (00, 04, 08, 12, 16, 20 Uhr); Entscheidungen nur auf geschlossenen Kerzen"],
        ["Indikatoren", "SMA200 der Schlusskurse; ATR14 als einfacher Mittelwert der True Range über 14 geschlossene Kerzen; Donchian-Kanal 20 (höchstes Hoch und tiefstes Tief der 20 vorherigen Kerzen)"],
        ["Signal", "Long: Schluss(t) > höchstes Hoch der Kerzen t−20 bis t−1 **und** Schluss(t) > SMA200(t). Short spiegelbildlich. Kein Signal, wenn eine der letzten 200 Kerzen fehlt"],
        ["Einstieg", "Marktorder zur Eröffnung der Kerze t+1; die Verzögerung wird gemessen und berichtet (Stress L1: eine Kerze später)"],
        ["Anfangsrisiko und Stop", "R0 = max(1,5 × ATR14(t), 1 % × Schluss(t)); Stop = Schluss(t) ∓ R0, fest ab Signal; 1 R = |Einstiegskurs − Stop|"],
        ["Ziel", "Einstieg ± 3 R"],
        ["Zeitstopp", "Ausstieg zum Schluss der 30. Kerze (Einstiegskerze = 1), wenn weder Stop noch Ziel erreicht"],
        ["Innerhalb einer Kerze", "Stop vor Ziel (konservativ); Lücken über Stop oder Ziel füllen zum Eröffnungskurs"],
        ["Positionsgrenze", "Höchstens eine offene oder vorgemerkte Position über alle Märkte; bei gleichem Zeitstempel Vorrang BTC > ETH > SOL; Ausstiege vor Signalen derselben Kerze"],
        ["Positionsgröße (nur Papier)", f"Virtuelles Kapital 10.000 USDT, 1 % Risiko je R, nicht aufgezinst; bei mittlerem Stop von {de(z['stop_abstand_prozent'], 1)} % ergibt das ein Nominal von etwa {de(1.0 / z['stop_abstand_prozent'] * 100, 0)} % des Kapitals je Position (ohne Hebel ausführbar; Hebel ändert nur die Marge, nicht das Risiko je R)"],
        ["Kostenmodell", "K1 (Gebühr 0,06 % je Seite, Schlupf 0,03 % Einstieg/Ziel/Zeit, 0,05 % Stop) und K2 (Schlupf 0,06 %, Stop 0,10 %, Funding ohne Gutschrift) parallel; Gebühren und Funding sind **bis zur Bestätigung durch das Konto als unbestätigt gekennzeichnet**"],
        ["Journal", "Hash-Kette, Eintrag je Signal mit Kerzenzeit, Signalpreis, Stop, Ziel, tatsächlichem Fill-Modell, Kosten; Ausschlüsse nur mit vorab festgelegtem Grund"],
        ["Nicht Teil der Strategie", "Makrofilter (F5), GARCH-Größe, Orderflow-Filter, Parameteranpassung, Hebelerhöhung, Echtgeld"]])
    return o


def abschnitt12(d: dict) -> list[str]:
    z, t15 = d["z"], d["t15"]["ergebnis"]
    tpm = z["trades_pro_monat"]
    n24 = n_trades_bis_power(0.24, 1.72)
    o = ["## 12. Konkreter nächster Forschungs- oder Paper-Trading-Schritt", "",
         "Kein Kandidat erreicht Stufe 4. Deshalb ist der Plan **kein Eignungsurteil**, sondern ein Beobachtungs- und Prüfplan, der klärt, was bisher nicht klärbar ist.", "",
         "### 12.1 Papier-Vorwärtsjournal weiterführen (läuft seit 2026-11-01)", ""]
    o += tab(["Baustein", "Festlegung"], [
        ["Strategieversion", "unverändert S7b-D20-T3 (C1) und C3 als zweites virtuelles Portfolio (Abschnitt 11); kein Parameter, keine Kosten, kein Kriterium ändert sich während der Beobachtung"],
        ["Datenumfang und Dauer", f"**Empfehlung für ein Zusatzprotokoll, das vor der ersten Auswertung einzufrieren ist** (nicht Teil von Protokoll 1.0): Auswertung genau einmal bei **{n24} geschlossenen Trades je Portfolio** (Power 80 % für +0,24 R bei Streuung 1,72 R), das sind bei {de(tpm, 1)} Trades im Monat (C1) etwa {de(n24 / tpm / 12, 1)} Jahre, bei C3 ({de(d['t7c3']['pooled']['kennzahlen']['trades_pro_monat'], 1)} im Monat) etwa {de(n24 / d['t7c3']['pooled']['kennzahlen']['trades_pro_monat'] / 12, 1)} Jahre. "
         "Zwischenstände dienen nur der Überwachung, nicht dem Urteil. Die Zahlen von Protokoll 1.0 (mindestens 30 Trades für Stufe 4) und der S7b-Präregistrierung (100 Trades für das endgültige Urteil) bleiben bestehen; sie sind Plausibilitätsschranken, keine Nachweisgrenzen (Stufe 4 braucht außerdem Stufe 3)."],
        ["Warum nicht weniger", f"Mit 30 Trades beträgt die Power nur {pct(power(0.24, 1.72, 30), 0)}, mit 100 Trades (Mindestzahl der S7b-Präregistrierung für das endgültige Urteil) {pct(power(0.24, 1.72, 100), 0)}; für die in T15 beobachtete Erwartung wären rund {n_trades_bis_power(t15['p1']['e_r'], t15['primaer_k2']['kennzahlen']['sd_r'])} Trades nötig. Eine kürzere Beobachtung kann Vorteile weder belegen noch widerlegen."],
        ["Kostenmodell", "K1 und K2 parallel; zusätzlich wird je Trade der tatsächlich gemessene Schlupf zwischen Signalkurs und Fill-Modell (Orderbuch des Handelsplatzes zum Zeitpunkt) festgehalten, um die Annahmen zu prüfen"],
        ["Monitoring (wöchentlich, nur lesend)", "Trades, E[R] mit Band, Rückgang, Kosten in R je Trade, Anzahl Stopps gegen Ziel gegen Zeitstopp, Lücken in den Kerzen, Journal-Hash-Kette; Abgleich der Signale mit der Nachrechnung (`s7b_nachrechnung.py`) auf denselben Kerzen"],
        ["Abbruchregeln", f"(1) Abweichung zwischen Journal und Nachrechnung (Integritätsfehler); (2) tatsächlicher Kostenanteil über dem Doppelten der K1-Kosten ({de(2 * z['kosten_r_je_trade'], 2)} R je Trade; der Nullpunkt der Erwartung läge beim {de(z['bruch_mult'], 1)}-Fachen) auf mindestens 20 Trades; (3) größter Rückgang über dem 95. Perzentil des Bootstraps "
         f"({de(d['t7']['pooled']['monatsblock_bootstrap']['max_drawdown_r']['p95'], 0)} R): Stopp und Ursachenprüfung, kein Weiterlaufen mit geänderter Regel; (4) Datenlücken über 5 % der erwarteten Kerzen."],
        ["Abschlusskriterien (Vorschlag für das Zusatzprotokoll)", "Nach der festgelegten Trade-Zahl einmalige Auswertung: E[R] unter K2 > 0 und einseitiges Monatsblock-p ≤ 0,05 und Zufallsvergleich in SMA200-Richtung p ≤ 0,05; Ergebnis wird berichtet wie ein Erfolg, auch bei Fehlschlag. Echtgeld bleibt ausgeschlossen, bis Uzi ausdrücklich anders entscheidet."]])
    o += ["### 12.2 Einmaliger Holdout-Lauf (braucht Uzis ausdrückliches Wort und Bartis Zustimmung)", "",
          f"Der einzige schnelle Weg zu neuen, unberührten Daten ist der Holdout (Protokoll 1.0: 2025-01-01 bis 2026-09; ungesehen sind nur 2025-01 bis 2026-06 mit etwa {holdout_trades(tpm)} Trades für C1, Juli bis Oktober 2026 ist durch die S7b-Sonde gesehen und müsste getrennt ausgewiesen werden). "
          "Vorab festzulegen: Kandidat C1 und C3 unverändert, Kosten K1/K2, Kriterien G2 und G6 sowie Zufallsvergleich, genau ein Lauf, Bericht in jedem Fall. Zur Aussagekraft: Power etwa "
          f"{pct(power(0.24, 1.72, holdout_trades(tpm)), 0)} bei +0,24 R; ein Fehlschlag widerlegt kleinere Vorteile nicht. **Dieser Schritt wird nicht ausgeführt, solange keine Freigabe vorliegt.**", "",
          "### 12.3 Höchster Erkenntniswert der nächsten Untersuchung", "",
          f"Die Daten widersprechen sich an genau einer Stelle: Der Einstiegszeitpunkt (Donchian-Ausbruch) schlug zufällige Einstiege in Trendrichtung im Entwicklungszeitraum bei C1 deutlich "
          f"({r(z['zufall_e_train'])} / {r(z['zufall_e_valid'])} R gegen {r(z['K1_train'])} / {r(z['K1_valid'])} R, Training / Validierung) und bei C3 (der Variante aus T15) in der Validierung ({r(z['c3_zufall_e_valid'])} gegen {r(z['c3_K1_valid'])} R), "
          f"im Training aber nur knapp und nicht signifikant ({r(z['c3_zufall_e_train'])} gegen {r(z['c3_K1_train'])} R, p {de(z['c3_zufall_p_train'], 3)}) und in 2017 bis 2019 (C3) nicht ({r(t15['p3']['e_r_zufall_mittel'])} R gegen {r(t15['p3']['kandidat_e_r'])} R). "
          "Die nächste Untersuchung mit dem höchsten Erkenntniswert ist deshalb, **vorab festzulegen und einmal zu prüfen, ob die Trendseite mit der Auszahlungsgeometrie allein (SMA200-Richtung, feste Ausstiegsregel, keine Einstiegssuche) denselben Vorteil trägt wie C1/C3**: "
          "weniger Freiheitsgrade und ein kleineres N für den Mehrfachtest. Sie muss auf Daten laufen, die weder zur Entwicklung noch zu T15 gehören (Holdout oder Vorwärtsjournal), und kann dort gemeinsam mit C1/C3 geprüft werden; "
          "auf den schon gesehenen Daten wäre sie nur eine weitere Auswahl nach Ergebnis. "
          "Parallel: Bitunix-Gebühren, Funding und Ausführung aus dem eigenen Konto und dem laufenden Recorder messen (kritisch, weil eine Kerze Verzögerung die Erwartung vernichtet), und eine **fortlaufende Versuchszählung** einführen, ohne die keine Signifikanzaussage glaubwürdig ist.", "",
          "## Abschlussurteil und nächste Entscheidung", "",
          "**INTERESSANTE HYPOTHESE, EVIDENZ UNZUREICHEND** (Trendregel S7b-D20-T3, Kandidaten C1/C2/C3). Alle anderen Familien: **KEIN BELASTBARER VORTEIL**. Keine Echtgeld-Freigabe.", "",
          "- **Welche Annahme ist gescheitert?** Die Annahme, dass der Donchian-Ausbruch in SMA200-Richtung einen eigenständigen, übertragbaren Einstiegsvorteil trägt. Er überträgt sich nicht auf andere Coins (S32), schlägt in 2017 bis 2019 den Zufall nicht (T15) und übersteht weder die Mehrfachtest-Korrektur noch eine Kerze Verzögerung. "
          "Ebenso gescheitert: die Annahme, dass Orderflow-, Indikator- oder Level-Merkmale kurzfristiger Regeln nach Kosten tragen, und dass hohe Trefferquoten ein Qualitätsmerkmal sind.",
          "- **Welche Ergebnisse bleiben nutzbar?** Die Trendseite plus Auszahlungsgeometrie als Hypothese mit positiver Richtung in zwei Zeiträumen; die unabhängige Nachrechnung, das eingefrorene Protokoll, der Datencluster-Ansatz und die Kostenarithmetik; belastbare Negativbefunde (S34 bis S36, OFX, S24, frühe Familien), die künftige Suchen sparen; die Kerzen- und Kontraktgleichheit von Bitunix; "
          "Anzeige- und Risikobausteine (GARCH, Kalibrierung).",
          "- **Nächste Entscheidung (Uzi):** (1) Journal unverändert weiterlaufen lassen (kostet nichts, kein Echtgeld) – empfohlen; (2) den einmaligen Holdout-Lauf freigeben oder nicht (braucht auch Barti); (3) Bitunix-Gebühren und Funding aus dem Konto bestätigen lassen; (4) die vorab festzulegende Prüfung der einfachen Trendseiten-Regel beauftragen.", ""]
    return o


def baue(d: dict | None = None) -> str:
    d = d or lade_alles()
    teile = [kopf(d), abschnitt1(d), abschnitt2(d), abschnitt3(d), abschnitt4(d), abschnitt5(d), abschnitt6(d), abschnitt7(d), abschnitt8(d), abschnitt9(d), abschnitt10(d), abschnitt11(d), abschnitt12(d)]
    return "\n".join(x for t in teile for x in t) + "\n"


def schreibe(ordner: Path = ORDNER) -> Path:
    pfad = ordner / "KONSOLIDIERTE_STUDIE.md"
    pfad.write_text(baue(), encoding="utf-8")
    return pfad


if __name__ == "__main__":
    print(schreibe(Path(sys.argv[1]) if len(sys.argv) > 1 else ORDNER))
