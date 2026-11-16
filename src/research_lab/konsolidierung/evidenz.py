"""Evidenzmatrix der Konsolidierung: Erkenntnis, unterstützende Studien, Gegenbelege, Datenüberschneidung, Unsicherheit, Konsequenz.

Zahlen kommen aus den Ergebnisdateien (``docs/research_lab/konsolidierung/ergebnisse``), Verweise auf Studien werden gegen das Register geprüft.
Mehrere Studien desselben Datenclusters zählen als eine Evidenzquelle (Spalte Datenüberschneidung)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .register import alle_eintraege

ERGEBNISSE = Path("docs/research_lab/konsolidierung/ergebnisse")
STUFEN = ("historisch gut ausgesehen", "korrigiert reproduziert", "außerhalb der Entwicklung bestätigt", "prospektiv beobachtet")
ZIEL_USDT_PRO_TAG = 50.0


def de(x: float, nd: int = 3, vz: bool = False) -> str:
    """Zahl mit Dezimalkomma (optional mit Vorzeichen)."""
    s = f"{x:+.{nd}f}" if vz else f"{x:.{nd}f}"
    return s.replace(".", ",").replace("-", "−")


def ganz(n: int | float) -> str:
    """Ganzzahl mit Punkt als Tausendertrenner."""
    return f"{int(round(n)):,}".replace(",", ".")


def pct(x: float, nd: int = 1) -> str:
    return de(100 * x, nd) + " %"


def kapitalbedarf(e_r: float, trades_pro_monat: float, risiko_je_trade: float, ziel_usdt_pro_tag: float = ZIEL_USDT_PRO_TAG) -> dict:
    """Kapital, das für ein Durchschnittsziel je Kalendertag nötig wäre, WENN die Erwartung e_r je Trade stimmt (reine Arithmetik, keine Prognose).

    Annahmen: Risiko je Trade ist ein fester Anteil des Kapitals (nicht aufgezinst), Gewinne = e_r × Trades × Risiko, 365 Kalendertage."""
    jahres_r = e_r * trades_pro_monat * 12
    if jahres_r <= 0:
        return {"jahres_r": jahres_r, "usdt_je_r": None, "kapital_usdt": None}
    usdt_je_r = ziel_usdt_pro_tag * 365 / jahres_r
    return {"jahres_r": jahres_r, "usdt_je_r": usdt_je_r, "kapital_usdt": usdt_je_r / risiko_je_trade}


def lade_zahlen(ordner: Path = ERGEBNISSE) -> dict:
    """Liest die Kennzahlen aus den Ergebnisdateien. Schlüssel sind kurze Namen, die in den Zeilen verwendet werden."""
    def j(name: str) -> dict:
        return json.loads((ordner / name).read_text(encoding="utf-8"))

    sz = j("t02_kosten.json")["ergebnis"]["C1"]
    t3 = j("t03_zufall_C1.json")["ergebnis"]["sektionen"]
    t4 = j("t04_raster_C1.json")["ergebnis"]
    t6 = j("t06_konzentration_C1.json")["ergebnis"]
    t7 = j("t07_unsicherheit_C1.json")["ergebnis"]
    t8 = j("t08_dsr_C1.json")["ergebnis"]["K1"]
    t9 = j("t09_regime_C1.json")["ergebnis"]
    t10 = j("t10_referenzen.json")["ergebnis"]
    t11 = j("t11_carry.json")["ergebnis"]
    t13 = j("t13_bitunix.json")["ergebnis"]["kerzen"]
    kr = j("kriterien.json")["kriterien"]
    pool = t7["pooled"]
    z: dict = {}
    for s in ("K0", "K1", "K2", "K3", "L1"):
        for a, kurz in (("train", "train"), ("validation", "valid"), ("pooled", "pooled")):
            z[f"{s}_{kurz}"] = sz["szenarien"][s][a]["e_r"]
    z["n_train"], z["n_valid"], z["n_pooled"] = (sz["szenarien"]["K1"][a]["n"] for a in ("train", "validation", "pooled"))
    z["bruch_mult"] = sz["bruchstelle"]["null_durchgang_multiplikator"]["pooled"]
    z["zufall_p_train"], z["zufall_p_valid"], z["zufall_p_pooled"] = (t3[a]["p_einseitig"] for a in ("train", "validation", "pooled"))
    z["zufall_e_train"], z["zufall_e_valid"] = t3["train"]["e_r_zufall_mittel"], t3["validation"]["e_r_zufall_mittel"]
    z["nachbarn_train"], z["nachbarn_valid"] = t4["anteil_positiv_nachbarn"]["train"], t4["anteil_positiv_nachbarn"]["validation"]
    z["raster_pooled"] = t4["anteil_positiv_raster"]["pooled"]
    z["rang_pooled"] = t4["c1_rang_prozent"]["pooled"]
    z["top5_anteil"] = t6["anteil_beste_5_prozent_an_summe"]
    z["dd_r_pooled"] = t6["gepoolt"]["max_drawdown_r"]
    z["summe_r_pooled"] = t6["gepoolt"]["summe_r"]
    z["ci_lo"], z["ci_hi"] = pool["monatsblock_bootstrap"]["e_r"]["ci95"]
    z["nw_t"] = pool["woechentlich_newey_west"]["t"]
    z["trades_pro_monat"] = pool["kennzahlen"]["trades_pro_monat"]
    z["stop_abstand_prozent"] = pool["kennzahlen"]["mittlerer_stop_abstand_prozent"]
    z["kosten_r_je_trade"] = pool["kennzahlen"]["kosten_r_je_trade"]
    z["dsr_n64_train"], z["dsr_n64_valid"], z["dsr_n64_pooled"] = (t8[a]["nullfall"]["64"]["dsr"] for a in ("train", "validation", "pooled"))
    z["dsr_nmax_pooled"] = t8["pooled"]["nullfall"]["26707"]["dsr"]
    z["jahr2020_r"], z["jahr2021_e"] = t9["je_jahr"]["2020"]["summe_r"], t9["je_jahr"]["2021"]["e_r"]
    z["terzil_hoch_e"] = t9["je_volatilitaets_terzil"]["hoch"]["e_r"]
    z["long_e"], z["short_e"] = t9["je_seite"]["long"]["e_r"], t9["je_seite"]["short"]["e_r"]
    ref = t10["referenzen"]
    z["c1_sharpe"], z["c1_dd"], z["c1_rendite"] = (t10["kandidat"]["pooled"][k] for k in ("sharpe_jahr", "max_rueckgang_prozent", "summe_prozent"))
    for r in ("R1", "R2"):
        for k, n in (("sharpe_jahr", "sharpe"), ("max_rueckgang_prozent", "dd"), ("summe_prozent", "rendite")):
            z[f"{r.lower()}_{n}"] = ref[r]["kennzahlen"]["pooled"][k]
    lauf = t11["lauf"]
    z["carry_konst_train"], z["carry_konst_valid"] = (lauf["basis_marge100"][a]["paar_netto_rendite_je_jahr"] for a in ("train", "validation"))
    z["carry_monat_train"], z["carry_monat_valid"] = (lauf["monatlich_nachjustiert"][a]["paar_netto_rendite_je_jahr"] for a in ("train", "validation"))
    z["geld_train"], z["geld_valid"] = (lauf["basis_marge100"][a]["geldmarkt_je_jahr_annahme"] for a in ("train", "validation"))
    z["bx_e"], z["bn_e"], z["bx_delta"] = t13["bitunix"]["e_r"], t13["binance"]["e_r"], t13["differenz_e_r"]
    g8 = kr["G8_berichtet"]
    z["s32_e"], z["s32_n"], z["s32_p"] = g8["netto_e_r"], g8["n_trades"], g8["zufall_p"]
    z["s32_ci_lo"], z["s32_ci_hi"] = g8["bootstrap_ci95"]
    kb1 = kapitalbedarf(z["K1_pooled"], z["trades_pro_monat"], 0.01)
    kb2 = kapitalbedarf(z["ci_lo"], z["trades_pro_monat"], 0.01)
    z["jahres_r"] = kb1["jahres_r"]
    z["kapital_c1_1pct"] = kb1["kapital_usdt"]
    z["kapital_c1_05pct"] = kapitalbedarf(z["K1_pooled"], z["trades_pro_monat"], 0.005)["kapital_usdt"]
    z["kapital_c1_untergrenze_1pct"] = kb2["kapital_usdt"]
    z["usdt_je_r"] = kb1["usdt_je_r"]
    z["risiko_noetig_10k"] = kb1["usdt_je_r"] / 10_000
    z["dd_bei_10k"] = z["dd_r_pooled"] * z["risiko_noetig_10k"]
    return z


def zeilen(z: dict) -> list[dict]:
    """Die Zeilen der Evidenzmatrix. Zahlen aus ``z`` (lade_zahlen), alles andere aus dem Register und den gelesenen Berichten."""
    def zeile(nr, erkenntnis, richtung, unterstuetzend, ids_u, gegen, ids_g, ueberschneidung, unsicherheit, konsequenz, stufe):
        return {"nr": nr, "erkenntnis": erkenntnis, "richtung": richtung, "unterstuetzend": unterstuetzend, "unterstuetzende_ids": ids_u,
                "gegenbelege": gegen, "gegenbeleg_ids": ids_g, "ueberschneidung": ueberschneidung, "unsicherheit": unsicherheit,
                "konsequenz": konsequenz, "evidenzstand": stufe}

    return [
        zeile(
            "E1",
            "Die Trendregel S7b-D20-T3 (Donchian-20-Ausbruch in Richtung SMA200, 4h, Ziel 3 R, ATR-Stop, höchstens eine Position) hatte 2020–2024 auf BTC, ETH und SOL nach Kosten eine positive Erwartung.",
            "positiv (Hypothese)",
            f"Eigene Nachrechnung: gespeicherte Handelslisten bit-genau reproduziert (T1). Netto je Trade (K1) Training {de(z['K1_train'], 3, True)} R (n {z['n_train']}), "
            f"Validierung {de(z['K1_valid'], 3, True)} R (n {z['n_valid']}), gepoolt {de(z['K1_pooled'], 3, True)} R, 95-%-Band {de(z['ci_lo'])} bis {de(z['ci_hi'])} R, Newey-West t {de(z['nw_t'], 2)}. "
            f"Bleibt positiv unter dreifachen Kosten (K3 {de(z['K3_train'], 3, True)} / {de(z['K3_valid'], 3, True)} R), Bruchstelle bei {de(z['bruch_mult'], 1)}-fachen K1-Kosten. "
            f"Zufallseinstiege in SMA200-Richtung schlagen die Regel selten (p {de(z['zufall_p_train'])} / {de(z['zufall_p_valid'])}). {pct(z['nachbarn_train'])} / {pct(z['nachbarn_valid'])} der 81 Nachbarzellen positiv; "
            f"Weglassen eines Jahres oder Instruments kippt das Vorzeichen nicht; Long {de(z['long_e'], 2, True)} R, Short {de(z['short_e'], 2, True)} R.",
            ["S7", "S7b", "K-C1"],
            f"S32: dieselbe Regel auf 137 anderen Coins (Punkt-in-Zeit-Universum), Validierung: {de(z['s32_e'], 4, True)} R bei n {ganz(z['s32_n'])}, Zufalls-p {de(z['s32_p'])}, 95-%-Band {de(z['s32_ci_lo'], 3)} bis {de(z['s32_ci_hi'], 3, True)} R. "
            f"Deflated Sharpe bei N = 64: Training {de(z['dsr_n64_train'], 2)}, Validierung {de(z['dsr_n64_valid'], 2)}, gepoolt {de(z['dsr_n64_pooled'], 2)} (Schwelle 0,95; bei N = 26.707 {de(z['dsr_nmax_pooled'], 2)}). "
            f"Eine Kerze Verzögerung: Training {de(z['L1_train'], 3, True)} R, Validierung {de(z['L1_valid'], 3, True)} R. Sondenlauf Juli–Oktober 2026 (S7b-Sonde, zufällig gesehen): 35 Trades, −5,8 R. "
            f"Einfache Referenz R2 (SMA200 lang/flat, gleiche Schwankung): Sharpe {de(z['r2_sharpe'], 2)} gegen {de(z['c1_sharpe'], 2)}. S25: GARCH-Größe bringt keinen Vorteil.",
            ["S32", "S7b-Sonde", "S25", "K-Ref"],
            "Ein Datencluster (TREND-4H): dieselben Binance-4h-Kerzen BTC/ETH/SOL 2020–2024, Validierung 2023–2024 mehrfach verbraucht (S7b, S25, S7b-Makro). S7, S7b und die eigene Nachrechnung sind eine Evidenzquelle, nicht drei.",
            f"Coins im Nachhinein gewählt (Survivorship). Beste 5 % der Trades = {pct(z['top5_anteil'])} der Summe; 2020 liefert {de(z['jahr2020_r'], 0)} von {de(z['summe_r_pooled'], 0)} R, 2021 {de(z['jahr2021_e'], 2, True)} R je Trade; "
            f"Drawdown {de(z['dd_r_pooled'], 1)} R (ca. 21 % bei 1 % Risiko); im oberen Volatilitäts-Terzil {de(z['terzil_hoch_e'], 2, True)} R je Trade (n 99). Zufallseinstiege in Trendrichtung erreichen im Training schon {de(z['zufall_e_train'], 3, True)} R, ein Teil des Vorteils ist Trendseite plus Auszahlungsgeometrie.",
            "Nur als Hypothese für den Vorwärts-Papiertest (S7b-Forward). Keine Live-Aktivierung, keine Skalierung. Stufe 4 braucht mindestens 30 geschlossene Papier-Trades unter K2 oder einen freigegebenen Holdout-Lauf.",
            "historisch gut ausgesehen: ja. Korrigiert reproduziert: ja (Prüftiefe A). Außerhalb der Entwicklung bestätigt: nein (S32 negativ, kein ungesehener Abschlusstest). Prospektiv beobachtet: 7 geschlossene Papier-Trades, zu wenig.",
        ),
        zeile(
            "E2",
            "Die Trendregel überträgt sich nicht auf andere Coins: Auf dem einzigen unabhängigen Universum (137 Coins, Punkt-in-Zeit) ist die Erwartung nach Kosten nicht von null verschieden.",
            "negativ",
            f"S32 (ein Lauf, Validierung 2023–2024): {de(z['s32_e'], 4, True)} R je Trade bei n {ganz(z['s32_n'])}, Zufalls-p {de(z['s32_p'])}, 95-%-Band {de(z['s32_ci_lo'], 3)} bis {de(z['s32_ci_hi'], 3, True)} R. Ergebnisdatei gelesen und mit SHA-256 festgehalten; nicht neu gerechnet (Kerzen der 137 Coins liegen nicht im Container).",
            ["S32"],
            "Das Band schließt auch +0,10 R ein: ein kleiner Vorteil ist nicht ausgeschlossen, nur nicht gezeigt. E1 spricht für BTC/ETH/SOL, nicht für den Korb.",
            ["S7b"],
            "Gleiche Regel, gleiche Zeit (2023–2024), anderes Universum (Top-25 je Monat nach Punkt-in-Zeit, ohne BTC/ETH/SOL). Training 2020-07 bis 2022 lag im Altcoin-Aufwärtsmarkt; ob delistete Märkte fehlen (Survivorship), ist nicht geprüft.",
            "Die Zahlen sind NUR BERICHTET: Die Handelsliste lag nicht vor, nur Aggregate wurden gelesen. Der Lauf ist einmalig und vorab eingefroren; er zählt als Gegenbeleg, nicht als Beweis für das Fehlen eines Vorteils.",
            "Nicht annehmen, dass die Regel allgemein „Trend verfolgt“. Wirkung bleibt an BTC/ETH/SOL gebunden; das ist ohne unabhängige Bestätigung ein Zeichen für Auswahl im Nachhinein.",
            "Außerhalb der Entwicklung getestet: ja (negativ). Korrigiert reproduziert: nein (nur berichtet).",
        ),
        zeile(
            "E3",
            "Orderflow-Regeln (OF2, OFX-Suche, S19, S31/S31b, S2) haben keinen belegten Vorteil.",
            "negativ / nicht belegt",
            "OFX: 27.023 Konfigurationen × 300 Filter = 8.106.900 Varianten, 0 bestehen das Sieb; bestes t bei n ≥ 130 ist 2,66; aus Tausenden unabhängiger Nullversuche wäre ein Zufallsmaximum von etwa 3 zu erwarten (die effektive Zahl unabhängiger Versuche ist nicht bestimmt). S19: Familien T, H, E ohne Nachweis, I, A, C nicht testbar. "
            "S31/S31b: keine Regel erreicht n ≥ 100. S2: nicht beurteilbar (Power-Gate). S26: Absorption −0,48 R, Initiative −0,44 R (Validierung).",
            ["OFX", "S19", "S31", "S31b", "S2", "S26"],
            "OF2 Training: 56 Trades, +0,27 R je Trade, Zufallseinstiege −0,09 R (Labor-p 0,006). S31 B1 34 Trades +0,33 R, B2 13 Trades +0,44 R. Gegen den Befund: eigenes 95-%-Band −0,20 bis +0,66 R, beste 5 % der Trades = 108 % der Summe, Median −0,35 R, Deflated Sharpe (N = 64) etwa 0,06.",
            ["OF2", "S31", "OF2-Kostengrenze"],
            "Ein Datencluster (OF-MIN): S8-Minutenbalken BTC 2020–2024. S31 B1–B5 sind OF2-Modelle, OFX sucht auf demselben Training. Nicht unabhängig.",
            "n 56 ist weit unter jeder tragfähigen Mindestzahl; die Suche über 8,1 Mio. Varianten erzeugt Spitzenwerte aus Zufall. Rohdaten der PS5 nicht neu gerechnet (Prüftiefe B auf Ergebnisdateien).",
            "Kein Orderflow-Signal für Papier-Trading. Die Datensammlung bleibt als Beobachtung; OF2 nur als Hypothese, die auf neuen (prospektiven) Daten mit vorab festgelegter Mindestzahl geprüft werden müsste.",
            "historisch gut ausgesehen: OF2 ja (n 56). Korrigiert reproduziert: Kennzahlen ja (Prüftiefe B), Vorteil nein. Außerhalb der Entwicklung: nein. Prospektiv: OF-Schatten n 25, Regel nachträglich, keine Aussage.",
        ),
        zeile(
            "E4",
            "Indikator-Merkmale (Kerzen, Orderflow, Funding, Open Interest, Positionierung) sortieren BTC-1h-Trades zum Teil, tragen aber nach Kosten keine Handelsregel.",
            "negativ",
            "S24: Modell M2 sortiert echt (Abstand 0,135 R, p 0,004), aber NEHMEN verliert nach Kosten −0,378 R (n 11.181). S22: Abstand H1 +0,115 R (p 0,051), NEHMEN −0,173 R. S27: NEHMEN −0,049 / −0,098 R. S28: Abstand +0,135 R, Holm nicht bestanden, nach Kosten −0,04 R. "
            "S20/S21: Kerzen-, Orderflow- und Funding-Merkmale verbessern das Mechanik-Modell nicht. E0/E1: Brutto je Trade −0,03 bis +0,04 R, Kosten 0,09–0,42 R.",
            ["S20", "S21", "S22", "S24", "S26", "S27", "S28", "E0/E1"],
            "Einziger positiver Teilbefund: der Sortiereffekt von S24-M2 (0,135 R, p 0,004). Er ist ein Unterschied zwischen Gruppen, kein positiver Mittelwert.",
            ["S24"],
            "Ein Datencluster (BTC-1H): dieselben Standard-Trades und dieselbe Validierung 2023–2024 in S20–S28. Die p-Werte sind nicht unabhängig und wurden nicht über alle Studien korrigiert.",
            "Brutto der Ausgangstrades ist etwa null (E0): es gibt nichts zu sortieren, wofür sich die Kosten lohnen. Mehrfachtest über neun Studien auf denselben Daten.",
            "Als Filter für eine Regel mit positivem Brutto-Ergebnis weiter prüfbar (z. B. für E1), nicht als eigenständige Regel.",
            "historisch gut ausgesehen: Sortiereffekt ja, Gewinn nein. Korrigiert reproduziert: Zahlen im Logbuch in den Ergebnisdateien gefunden (Prüftiefe C+). Außerhalb der Entwicklung: nein.",
        ),
        zeile(
            "E5",
            "Kosten dominieren kurzfristige Regeln mit engen Stops: Je kleiner der Stop-Abstand, desto größer die Kosten in R, bis sie jeden Brutto-Vorteil verbrauchen.",
            "negativ",
            f"S34: Brutto −0,02 R, Kosten 1,2 R je Trade (Stop im Mittel 0,20 %). S35a: bestes Brutto +0,06 R, netto −0,25 R. S36: Brutto +0,10 R, Kosten 0,15 R. S38: netto +0,005 R. S30: Kosten 0,12–0,17 R. Stop-Analyse 30m: Kosten 2,4–2,8 R je Stopp. "
            f"E0/E1: Kosten 0,09–0,42 R. Zum Vergleich trägt C1 {de(z['kosten_r_je_trade'], 3)} R Kosten je Trade bei einem mittleren Stop von {de(z['stop_abstand_prozent'], 1)} %.",
            ["S34", "S35a", "S36", "S38", "S30", "Stop-Analyse-30m", "E0/E1", "S17"],
            "Bitunix-Gebühren sind unbestätigt (Taker 0,06 % und Maker 0,02 % nur von Uzi genannt); ein günstigerer Tarif oder Maker-Ausführung würde das Bild verbessern. S6 (Maker-Limits) bestand nicht.",
            ["S6", "Kraken-Kosten"],
            "Mehrere Cluster (BTC-1H, LEVEL-INTRADAY, PROSPEKTIV); Kosten stammen aus den Annahmen des Protokolls, nicht aus Bitunix-Füllungen. Kraken-Messung (5 bp, 22 Füllungen) stützt die Annahmen als eher vorsichtig.",
            "Bitunix-Handelshistorie fehlt (nur Live-Aufzeichnung); Schlupf bei Stopps in schnellen Märkten unterschätzt möglich (Kraken: Börsen-Stops 15 bp früher).",
            "Bei 0,16 % Kosten je Umschlag (K1) kostet ein Stop von 1 % schon 0,16 R je Trade, ein Stop von 0,2 % rund 0,8 R; der Brutto-Vorteil müsste das übersteigen, und in den geprüften Studien tat er das nie. Jede Kandidatenregel braucht den Kostenanteil in R als Pflichtangabe vor der Auswertung.",
            "Korrigiert reproduziert: Prüftiefe B (S34–S38) und C+ (Rest). Außerhalb der Entwicklung: nein (gleiche Daten, gleiche Kostenannahme).",
        ),
        zeile(
            "E6",
            "Frühe Regelfamilien (R4: 48 Varianten, S4, S6, S13, S14) haben keinen Vorteil; S9 und S10 sind am Zähl-Gate gescheitert.",
            "negativ",
            "R4: 42 Varianten scheitern schon im Training, 6 in der Validierung, SPA p 0,46 / 0,43, StepM wählt keine. S4: alle Varianten −0,12 bis −0,23 R. S6: Treffer 72–82 %, Erwartung −0,07 bis −0,11 R. S13: Training −0,044 / −0,042 R. S14: −0,19 bis −0,36 R. "
            "S9: höchstens 11 Signale statt 500; S10: 241 von 500.",
            ["R4", "S4", "S6", "S13", "S14", "S9", "S10"],
            "S13-NY Validierung +0,030 R, aber Drawdown über der Grenze und Walk-Forward −0,021 R. Sonst keine Gegenbelege.",
            ["S13"],
            "Ein Datencluster (FRÜH): BTC/ETH/SOL 2020–2024 mit Protokoll 1.x. 6 von 48 Varianten bestanden das Training und scheiterten erst in der Validierung: Die Trennung von Training und Validierung entfernt Scheintreffer des Trainings.",
            "Prüftiefe C+ (Ergebnisdateien gelesen, nicht neu gerechnet); Studien vor Protokoll 1.3 mit weniger strenger Mehrfachtestkorrektur.",
            "Verworfen. Die hohe Trefferquote allein (S4, S6) ist kein Profitabilitätsnachweis: 72–82 % bei negativer Erwartung.",
            "Außerhalb der Entwicklung: Validierungsabschnitt (negativ). Prospektiv: nein.",
        ),
        zeile(
            "E7",
            "Funding-Carry (Spot long, Perp short) ist eine Kapitalrendite mit Basis-, Liquidations- und Gegenparteirisiko, kein Handelsvorteil. In der Validierung liegt sie bei konstantem Nominal im Bereich eines Geldmarktzinses.",
            "keine belastbare Aussage",
            f"K-Carry (BTC+ETH, Binance-Funding als Stellvertreter): konstante Stückzahl Training {pct(z['carry_konst_train'])} je Jahr, Validierung {pct(z['carry_konst_valid'])} (Kriterium CG1 formal bestanden). "
            f"Monatlich neu abgesichert (konstantes Nominal): {pct(z['carry_monat_train'])} / {pct(z['carry_monat_valid'])} je Jahr gegen angenommenen Geldmarkt {pct(z['geld_train'])} / {pct(z['geld_valid'])}. S33-Carry: immer in Position +8,5 % je Jahr, 2022 nur +2 %.",
            ["K-Carry", "S33-Carry"],
            "Die konstante Stückzahl führt zu verdecktem Hebel: Ohne Nachjustieren wäre die Marge der Perp-Short-Position 2020 aufgebraucht gewesen (ETH nach 42, BTC nach 309 Tagen), der Nachschussbedarf stieg bis zum 14-Fachen (BTC) bzw. 37-Fachen (ETH) des anfänglichen Nominalwerts. Der formale Bestehenswert von CG1 ist deshalb kein Beleg. S5 (95 % Trefferquote mit Carry): nicht testbar, zu wenige Episoden.",
            ["S5"],
            "Ein Datencluster (CARRY): Binance-Funding 2020–2024; Bitunix-Funding und -Einheit nicht bestätigt. Geldmarktzinsen sind eine Annahme aus dem Gedächtnis, nicht aus TIM-Daten.",
            "Schutzabstand zur Liquidation, Spot-Gebühren auf Bitunix, Gegenparteirisiko der Börse und Steuer nicht modelliert. Die Zinsannahme entscheidet über den Vorsprung.",
            "Keine Grundlage für das Tagesziel; allenfalls Beobachtung. 50 USDT je Tag wären bei +8,5 % je Jahr rund 215.000 USDT Kapital (S33-Carry-Bericht).",
            "historisch gut ausgesehen: ja (Training). Korrigiert reproduziert: Prüftiefe A für K-Carry (eigene Rechnung). Außerhalb der Entwicklung: Validierung schwach. Prospektiv: nein.",
        ),
        zeile(
            "E8",
            "Die Kombination von Trend (C1) und Carry (C2) bringt formal einen Diversifikationsgewinn (Korrelation um null), ändert aber nichts an der Beweislage des Trendanteils.",
            "keine belastbare Aussage",
            "T12: Korrelation der Tagesrenditen −0,05 (konstante Stückzahl) bzw. −0,006 (monatlich neu abgesichert), Kriterium G10 formal bestanden.",
            ["K-C1", "K-Carry"],
            "Der Trendanteil erfüllt G7 und G8 nicht; der Carryanteil erreicht in der Validierung etwa den Geldmarkt (E7).",
            ["S32"],
            "Beide Teile aus 2020–2024 mit denselben Instrumenten (BTC, ETH).",
            "Gewichte und Hebel des Carryanteils sind Annahmen; Kosten und Liquidationsrisiko des Carry nicht voll modelliert.",
            "C2 wird nicht gegenüber C1 bevorzugt; der Carry ersetzt keinen fehlenden Trendbeleg.",
            "Korrigiert reproduziert: ja (eigene Rechnung). Außerhalb der Entwicklung: nein.",
        ),
        zeile(
            "E9",
            "Gegenüber einfachen, auf gleiche Schwankung skalierten Referenzen zeigt die Trendregel keinen Vorsprung: Ihr Vorteil kann Trendexposure auf im Nachhinein gewählten Coins sein.",
            "negativ",
            f"T10 (gepoolt, Hebel höchstens 3, Netto, nicht aufgezinst): C1 {de(z['c1_rendite'], 0)} %, Sharpe {de(z['c1_sharpe'], 2)}, Rückgang {de(z['c1_dd'], 1)} %; "
            f"R1 (gleichgewichteter Korb, Buy and Hold) {de(z['r1_rendite'], 0)} %, Sharpe {de(z['r1_sharpe'], 2)}, Rückgang {de(z['r1_dd'], 1)} %; R2 (SMA200 lang/flat) {de(z['r2_rendite'], 0)} %, Sharpe {de(z['r2_sharpe'], 2)}, Rückgang {de(z['r2_dd'], 1)} %.",
            ["K-Ref"],
            "C1 hat einen kleineren Rückgang als R1 und etwas mehr Rendite als R1; gegenüber R2 liegen Rendite und Sharpe niedriger.",
            ["K-C1"],
            "Gleiche Coins, gleiche Jahre. BTC, ETH und SOL sind im Rückblick Gewinner des Zeitraums; Buy and Hold auf ihnen ist selbst eine nachträglich gewählte Referenz.",
            "R1 und R2 sind auf die Tagesschwankung von C1 heruntergerechnet (Hebel 0,22 bzw. 0,35), Umschichtung kostet 0,09 % je Seite; alle drei Reihen ohne Zins auf nicht investiertes Kapital (gleich behandelt). Die Rangfolge hängt am Zeitraum 2020–2024.",
            "Der Beitrag der Ausbruchsregel über eine einfache Trendfilter-Position hinaus ist nicht gezeigt. Wer Trendexposure will, kann sie einfacher haben.",
            "Korrigiert reproduziert: ja (Prüftiefe A, eigene Tagesreihen). Außerhalb der Entwicklung: nein.",
        ),
        zeile(
            "E10",
            "Prospektive Beobachtungen (Papier-Journale, Schatten, Mini-Test) erlauben bisher keine belastbare Aussage, weder für noch gegen eine Regel.",
            "keine Aussage",
            "S7b-Forward: 4 bzw. 3 geschlossene Trades, +3,771 R bzw. +6,847 R, alle Short. Plan-Journale (84 Pläne): −9,32 R, KI90 −0,36 bis +0,12 R je Plan; ohne das Level-Journal 76 Pläne +8,39 R, KI90 −0,10 bis +0,18 R. OF-Schatten (25 Pläne, nur Long, Regel nach Ansicht der Zwischenstände geschrieben). Exit-Schatten: 7 Trades mit TP2.",
            ["S7b-Forward", "Plan-Journale", "OF-Schatten", "Exit-Schatten", "K1"],
            "S7b-Sonde (Juli–Oktober 2026): 35 Trades, −5,8 R, −0,17 R je Trade, zufällig gesehen; mit +0,24 R (E1) und mit 0 R verträglich. Kraken-Echtgeldtest und Bitunix-Konto: nicht zugänglich bzw. nur berichtet.",
            ["S7b-Sonde", "Kraken-Echtgeldtest", "Bitunix-Konto"],
            "Zeitlich benachbarte Fenster (Sonde und Forward), überlappende Pläne auf 15m und 1h, eine Marktphase. Nicht unabhängig.",
            "Zu kleine Zahlen; die Vorzeichen der Plan-Journale hängen an 27 Ausschlüssen laut Korrekturdatei (Zeitpunkt der Festlegung nicht geprüft).",
            "Weiterlaufen lassen mit vorab festgelegter Auswertung (30 Trades für Stufe 4, 100 für das endgültige Urteil); nichts daraus ableiten, bevor die Zahl erreicht ist.",
            "Prospektiv beobachtet: ja, aber n 2–35 je Fenster. Keine andere Stufe erreicht.",
        ),
        zeile(
            "E11",
            f"Ein Tagesziel von {de(ZIEL_USDT_PRO_TAG, 0)} USDT im Durchschnitt würde selbst bei unterstellter Gültigkeit der besten Erwartung (C1, K1) viel Kapital brauchen. Das Ziel ist ein Richtwert, keine Pflicht.",
            "Konsequenzrechnung",
            f"Reine Arithmetik mit E[R] {de(z['K1_pooled'], 3, True)} und {de(z['trades_pro_monat'], 1)} Trades je Monat: etwa {de(z['jahres_r'], 1)} R je Jahr, also {ganz(z['usdt_je_r'])} USDT je R; bei 1 % Risiko je Trade ≈ {ganz(z['kapital_c1_1pct'])} USDT, bei 0,5 % ≈ {ganz(z['kapital_c1_05pct'])} USDT. "
            f"Mit der unteren Grenze des 95-%-Bands ({de(z['ci_lo'])} R) bei 1 % Risiko ≈ {ganz(z['kapital_c1_untergrenze_1pct'])} USDT. Bitunix-Edge-Bericht für OF2: 364.000 USDT (1 % Risiko) bis 1,46 Mio. USDT (0,25 %). "
            f"Mit 10.000 USDT wären {pct(z['risiko_noetig_10k'])} Risiko je Trade nötig; der historische Drawdown von {de(z['dd_r_pooled'], 1)} R entspräche dann {pct(z['dd_bei_10k'], 0)} des Kontos.",
            ["Bitunix-Edge", "K-Bitunix", "OF2-Kostengrenze"],
            "Keine. Die Rechnung gilt nur, wenn die Erwartung stimmt (E1) und gleichmäßig verteilt anfällt; sie ist keine Prognose.",
            [],
            "Modellrechnung auf Basis von E1 beziehungsweise OF2 (n 56); gleiche Datencluster.",
            "Gewinne sind ungleichmäßig (Monate −8,5 bis +17,9 R); Drawdown bis ca. 21 R, also etwa 21 % des Kapitals bei 1 % Risiko je Trade; Steuern, Kontoführung, Slippage über K1 hinaus nicht enthalten.",
            "Mit einem kleinen Konto ist das Ziel nur über ein Risiko je Trade erreichbar, bei dem der historische Drawdown das Konto aufbrauchen würde. Höheres Risiko (Hebel) skaliert Gewinne und Drawdowns gleichermaßen und ändert die Erwartung je R nicht: Hebel ist kein Vorteil.",
            "Rechnung, keine Evidenzstufe.",
        ),
        zeile(
            "E12",
            "Die Kerzen und Kontrakte von Bitunix stimmen für BTC, ETH und SOL mit Binance überein; die Regel ist dort technisch ausführbar. Gebühren, Funding-Einheit und Verhalten bei Stress sind unbestätigt.",
            "Voraussetzung offen",
            f"T13: Netto je Trade auf Bitunix-Kerzen {de(z['bx_e'], 4)} R gegen Binance {de(z['bn_e'], 4)} R (Δ {de(z['bx_delta'], 3, True)} R), 252 gemeinsame Signale; Mindestkontrakt bei 1.000 USDT 100 % ausführbar; Spreads (Momentaufnahme ≈ 90 s) BTC 0,016 bp, ETH 0,056 bp, SOL 1,41 bp.",
            ["K-Bitunix"],
            "Bitunix liefert keine historischen Trades; die Gebühren (Taker 0,06 %, Maker 0,02 %) stammen nur von Uzi, FEES_VERIFIED ist False. Bitunix-Konto: Netto etwa −1.900 USDT in 365 Tagen bei 1.024 USDT Gebühren (nur berichtet, diskretionär, nicht TIM).",
            ["Bitunix-Konto"],
            "Bitunix-Kerzen ab 2022-04-17; überlappend mit E1.",
            "Funding-Einheit unklar (Prozent?), Tiefe nur als Momentaufnahme, Ausführung bei Stopps unter Stress unbekannt.",
            "Offene Vorbedingungen vor einem Papier-Test auf Bitunix: Gebührentabelle bestätigen, Funding-Einheit klären, Fills im Papiermodus aufzeichnen.",
            "Korrigiert reproduziert: ja (Kerzen). Gebühren: Annahme.",
        ),
        zeile(
            "E13",
            "Level-, Volumenprofil- und VWAP-Regeln auf BTC/ETH/SOL zwischen 1m und 4h haben keinen Vorteil nach Kosten.",
            "negativ",
            "S34 (n 53): netto −1,21 R. S35a: alle 12 Varianten −0,25 bis −0,41 R. S36: −0,05 / −0,09 R. S38: +0,005 R, Untergrenzen unter 0. S30: Fade-Raster netto negativ, Ausbruch −0,25 R. VWAP-1W-2σ: als Kaufsignal allein trägt es nicht, schon vor Kosten.",
            ["S34", "S35a", "S36", "S38", "S30", "VWAP-1W-2sigma"],
            "S37: n 1–5 je Variante, keine Aussage. Keine Gegenbelege.",
            ["S37"],
            "Ein Datencluster (LEVEL-INTRADAY): überlappende Zeiträume, Training 2020–2023.",
            "Nur Trainingsdaten (S30, S34–S38): keine Validierung gerechnet, weil das Training schon scheiterte oder zu wenige Fälle lieferte; VWAP-1W-2σ mit Validierung 2024, aber ohne Kosten.",
            "Verworfen als Quelle für eine Handelsregel; Level können als Anzeige bleiben.",
            "Korrigiert reproduziert: Prüftiefe B (S34, S35a, S36, S38). Außerhalb der Entwicklung: nicht erreicht.",
        ),
        zeile(
            "E14",
            "Prognose- und Risikobausteine (GARCH, Verteilungs- und Kalibrierstudien, KI-Pläne) sind brauchbar als Anzeige- und Risikoschicht, aber keine Quelle eines Handelsvorteils.",
            "keine Handelsaussage",
            "S15: GARCH(1,1) prognostiziert die Schwankung besser als 14-Tage-Varianz. S1: CPI-Stunde im Median 1,40-mal so unruhig. S17: Tageszeit-Wirkung auf Kosten 0,04–0,12 R. S39: kein Typ mit belegtem Muster, Holm-p mindestens 0,224.",
            ["S15", "S1", "S17", "S39", "S16"],
            "S25: Positionsgröße nach GARCH-Prognose bringt für S7b-D20-T3 keinen Vorteil.",
            ["S25"],
            "Cluster PROGNOSE, FRÜH; teils dieselben Kerzen.",
            "Vorhersagegüte der Schwankung sagt nichts über Handelsgewinn.",
            "Für Positionsgrößen und Anzeigen nutzbar; nicht als Gewinnquelle.",
            "Korrigiert reproduziert: Prüftiefe C/C+.",
        ),
        zeile(
            "E15",
            "Makrofilter (Realzins, Dollar, Liquidität u. a.) auf die Trendtrades sind nicht belegt.",
            "keine belastbare Aussage",
            "S7b-Makro: F5 besteht nach fünf Versuchen; der Glückstest über fünf Filter ergibt p = 0,066, F1–F4 bestehen nicht. F5 läuft als Vorwärts-Log.",
            ["S7b-Makro"],
            "Der Test über mehrere Filter erreicht die Schwelle nicht; ein einzelner Treffer nach fünf Versuchen ist bei dieser Zahl kein Beleg.",
            ["S7b"],
            "TREND-4H: dieselbe Handelsliste wie E1, dieselbe verbrauchte Validierung.",
            "Mehrfachtest nicht bestanden; Prüftiefe C (Bericht gelesen, nicht nachgerechnet).",
            "Nicht verwenden. F5 weiter als Vorwärts-Log beobachten, ohne den Filter an E1 zu hängen.",
            "historisch gut ausgesehen: nur F5. Korrigiert reproduziert: nein. Außerhalb der Entwicklung: nein.",
        ),
        zeile(
            "E16",
            "Studien ohne Ergebnis (Entwürfe, laufende Läufe, nicht zugängliche Dateien) liefern keine Evidenz und zählen weder für noch gegen eine Regel.",
            "keine Aussage",
            "S8 (läuft, keine Auswertung), S12 (Sammler seit 02.11.2026), S18 (Ergebnis nicht vor Januar), S23 (nur Entwurf), S29 (kein Ergebnis auffindbar), S33 (Optionsflow-Entwurf), GEX-Wand (Entwurf), L1, KI1, T07 (Entwürfe), Move-Kalibrierung (Detektor, kein Handelsbezug).",
            ["S8", "S12", "S18", "S23", "S29", "S33", "GEX-Wand", "L1", "KI1", "T07", "Move-Kalibrierung"],
            "Keine.",
            [],
            "Teils Datenbasis anderer Studien (S8-Minutenbalken, Move-Kalibrierung für S39).",
            "Status laut Logbuch oder Gedächtnis; S29 ist laut Gedächtnis auf der PS5 gelaufen, eine Ergebnisdatei wurde nicht gefunden.",
            "Gelistet, damit nichts verschwindet. Sobald Ergebnisse vorliegen, einzeln nach Protokoll prüfen.",
            "Keine Evidenzstufe erreicht.",
        ),
        zeile(
            "E17",
            "Plattform-, Abnahme- und Governance-Berichte belegen Datenqualität und Verfahren, nicht Profitabilität. Der Stand der Live-Regeln ist: keine einzige stützt sich auf eine bestandene Studie.",
            "keine Handelsaussage",
            "Überzeugungsregister (12.11.2026, 253 Aussagen): keine Live-Regel stützt sich auf eine bestandene Studie, 7 Live-Regeln sind widerlegt, mehr als 150 Prüfungen auf BTC 2020–2024 ohne fortlaufenden Gesamtzähler, Validierung 2023–2024 mehrfach verbraucht. "
            "V1-Juli: NOT_COMPLETE, 1-Minuten-Abdeckung 42,6 % / 60,7 %, 63 ungeklärte Lücken. tim-master P1: kein Setup mit positiver Evidenz im Register. Prüfberichte Chart: 295 von 331 Prüfungen PASS, kein Edge-Beleg.",
            ["Überzeugungsregister", "V1-Juli", "tim-master-P1", "Prüfberichte-Chart", "V2", "F4", "Kraken-Kosten"],
            "Keine.",
            [],
            "Eigenbewertung des Labors; deckt sich mit dieser Konsolidierung.",
            "Das Überzeugungsregister ist selbst eine Inventur des Labors, keine unabhängige Prüfung.",
            "Die Zählung „mehr als 150 Prüfungen“ ist die Grundlage für die Mehrfachtest-Rechnung (E1: N = 64 bis 26.707). Eine fortlaufende Versuchszählung ist eine Vorbedingung für jede künftige Aussage über Signifikanz.",
            "Keine Evidenzstufe; Verfahren.",
        ),
    ]


def pruefe(rows: list[dict]) -> list[str]:
    """Verweise auf Studien müssen im Register stehen; jede Zeile hat alle Felder."""
    ids = {x["id"] for x in alle_eintraege()}
    fehler = []
    felder = ("nr", "erkenntnis", "unterstuetzend", "gegenbelege", "ueberschneidung", "unsicherheit", "konsequenz", "evidenzstand")
    for r in rows:
        for f in felder:
            if not r.get(f):
                fehler.append(f"{r.get('nr')}: Feld {f} leer")
        for i in r["unterstuetzende_ids"] + r["gegenbeleg_ids"]:
            if i not in ids:
                fehler.append(f"{r['nr']}: unbekannte Studie {i}")
    nrn = [r["nr"] for r in rows]
    if len(set(nrn)) != len(nrn):
        fehler.append("Nummern doppelt")
    return fehler


def abdeckung(rows: list[dict]) -> dict:
    """Welche Registereinträge der gefundenen Studien tauchen in keiner Zeile der Matrix auf?"""
    genannt = {i for r in rows for i in r["unterstuetzende_ids"] + r["gegenbeleg_ids"]}
    gefunden = [x["id"] for x in alle_eintraege() if x["cluster"] != "EIGEN"]
    return {"genannt": len(genannt & set(gefunden)), "gefunden": len(gefunden), "nicht_genannt": sorted(set(gefunden) - genannt)}


def markdown(rows: list[dict], ab: dict) -> str:
    z = [
        "# Evidenzmatrix (Stand 16.11.2026)",
        "",
        "Erzeugt aus `ergebnisse/*.json` und dem Register (`python3 -m src.research_lab.konsolidierung.evidenz`). Mehrere Studien desselben Datenclusters zählen als eine Quelle. "
        "Studien können in mehreren Zeilen vorkommen; das ist keine zusätzliche Bestätigung.",
        "",
        f"Abdeckung: {ab['genannt']} von {ab['gefunden']} gefundenen Studien und Berichten sind einer Erkenntnis zugeordnet. Nicht zugeordnet (reine Infrastruktur, Entwürfe ohne Ergebnis oder noch nicht ausgewertet): "
        + (", ".join(ab["nicht_genannt"]) if ab["nicht_genannt"] else "keine") + ".",
        "",
        "## Übersicht",
        "",
        "| Nr | Erkenntnis | Richtung | Evidenzstand |",
        "|---|---|---|---|",
    ]
    for r in rows:
        z.append(f"| {r['nr']} | {r['erkenntnis']} | {r['richtung']} | {r['evidenzstand']} |")
    z += ["", "## Einzelne Erkenntnisse", ""]
    for r in rows:
        z += [f"### {r['nr']}: {r['erkenntnis']}", "",
              f"- **Richtung:** {r['richtung']}",
              f"- **Unterstützende Studien:** {', '.join(r['unterstuetzende_ids']) or '–'}. {r['unterstuetzend']}",
              f"- **Gegenbelege:** {', '.join(r['gegenbeleg_ids']) or '–'}. {r['gegenbelege']}",
              f"- **Datenüberschneidung:** {r['ueberschneidung']}",
              f"- **Unsicherheit:** {r['unsicherheit']}",
              f"- **Praktische Konsequenz:** {r['konsequenz']}",
              f"- **Evidenzstand:** {r['evidenzstand']}", ""]
    return "\n".join(z)


def schreibe(ordner: Path, ergebnisse: Path = ERGEBNISSE) -> dict:
    z = lade_zahlen(ergebnisse)
    rows = zeilen(z)
    fehler = pruefe(rows)
    if fehler:
        raise SystemExit("Evidenzmatrix fehlerhaft:\n" + "\n".join(fehler))
    ab = abdeckung(rows)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "evidenzmatrix.json").write_text(json.dumps({"stufen": STUFEN, "abdeckung": ab, "zeilen": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (ordner / "EVIDENZMATRIX.md").write_text(markdown(rows, ab) + "\n", encoding="utf-8")
    return ab


if __name__ == "__main__":
    ziel = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/research_lab/konsolidierung")
    print(json.dumps(schreibe(ziel), ensure_ascii=False, indent=1))
