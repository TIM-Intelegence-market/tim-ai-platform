"""Gesamtlauf der Tests T1 bis T13 des Prüfprotokolls Konsolidierung 1.0.

Aufruf (aus dem Repo-Wurzelordner)::

    python3 -m src.research_lab.konsolidierung.lauf <archiv-wurzel> <ergebnisordner> <s7b-trades.json> <s7-trades.json> <bitunix-ordner>

``archiv-wurzel``: Binance-Archive (siehe ``daten``); ``s7b-trades.json`` / ``s7-trades.json``: gespeicherte Labor-Tradelisten (SHA-256 im Ergebnis).
Das Ergebnis wird als JSON je Test geschrieben, dazu ``kriterien.json`` (mechanische Auswertung G1 bis G11) und ``TESTLOG.md``.
Kein Test lädt Daten ab 2025-01-01.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from src.research_lab.konsolidierung import tests_bitunix as B
from src.research_lab.konsolidierung import tests_kombination as K
from src.research_lab.konsolidierung import tests_trend as T

REPO = Path(__file__).resolve().parents[3]

# G8 (Übertragung auf ein unabhängiges Universum) liegt als berichtetes Ergebnis vor dem Einfrieren vor (Protokoll 5, G8)
G8_BERICHTET = {"quelle": "S32 1.0 Validierung 2023-24 (ein Lauf, 14.11.2026): Regel S7b-D20-T3 auf 137 Coins (Punkt-in-Zeit-Top-25 je Monat ohne BTC/ETH/SOL)",
                "ergebnisdatei_sha256": "dc00bd4a3d686931e5f627b556ff254a519d57bbb0aa2f6b520bde76c49f028c", "n_trades": 3311, "netto_e_r": -0.0255,
                "zufall_p": 0.5475, "bootstrap_ci95": [-0.150, 0.101], "status": "NUR BERICHTET (nicht neu gerechnet: Kerzen der 137 Coins liegen nicht im Container)", "bestanden": False}


def git_stand() -> tuple[str, bool]:
    h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    d = subprocess.run(["git", "status", "--porcelain", "--", "src/research_lab/konsolidierung"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return h, bool(d)


def lauf_alles(wurzel: str, ausgabe: str, pfad_s7b: str, pfad_s7: str, bitunix: str, ziehungen_zufall: int = T.ZIEHUNGEN_ZUFALL) -> dict:
    aus = Path(ausgabe)
    commit, schmutzig = git_stand()
    audit = REPO / "docs/research_lab/konsolidierung/ergebnisse/datenaudit.json"
    daten_version = hashlib.sha256(audit.read_bytes()).hexdigest() if audit.exists() else None
    befehl = f"python3 -m src.research_lab.konsolidierung.lauf {wurzel} {ausgabe} {Path(pfad_s7b).name} {Path(pfad_s7).name} {bitunix}"
    log: list[dict] = []

    def schreibe(name: str, test: str, kandidat: str, konfig: dict, zeitraum: str, grenzen: list[str], ergebnis: dict, dauer: float, status: str = "abgeschlossen") -> None:
        m = T.meta(test, konfig, befehl, zeitraum, status, grenzen)
        m.update({"kandidat": kandidat, "code_commit": commit, "code_unsauber": schmutzig, "daten_version_sha256_datenaudit": daten_version, "dauer_s": round(dauer, 1)})
        T.schreibe(aus / name, {"meta": m, "ergebnis": ergebnis})
        log.append({"test": test, "kandidat": kandidat, "datei": name, "status": status, "konfig": konfig, "zeitraum": zeitraum, "grenzen": grenzen})

    kerzen, fund = T.daten_laden(wurzel)
    zeitraum = "Signale 2020-01 bis 2024-12 (Training < 2023-01-01, Validierung 2023-01-01 bis 2024-12-31); Holdout nicht geladen"
    res: dict = {}

    t0 = time.time()
    res["T1"] = T.t1_reproduktion(kerzen, fund, pfad_s7b, pfad_s7)
    schreibe("t01_reproduktion.json", "T1", "C1/C3 (Regel)", {"verglichen": "S7b- und S7-Tradelisten, 4 Varianten, 2 Abschnitte"}, zeitraum,
             ["Vergleich nur mit den vom Labor gespeicherten Tradelisten (SHA-256 im Ergebnis)"], res["T1"], time.time() - t0)
    print("T1", res["T1"]["gesamt"], flush=True)

    t0 = time.time()
    res["T2"] = T.t2_kosten(kerzen, fund)
    schreibe("t02_kosten.json", "T2", "C1, C3", {"szenarien": list(T.KOSTEN), "bruchstelle_basis": "K1, Gebühr und Schlupf skaliert", "variante": "S7b-D20-T3"}, zeitraum,
             ["Funding aus Binance-Historie als Stellvertreter", "K4 nimmt Maker-Fills am Ziel an (ungeprüft)", "K1/K2/K3: Bitunix-Gebühren unbestätigt"], res["T2"], time.time() - t0)
    print("T2", {c: res["T2"][c]["g2_bestanden"] for c in res["T2"]}, flush=True)

    res["T3"], res["T4"], res["T6"], res["T7"], res["T8"], res["T9"] = {}, {}, {}, {}, {}, {}
    for name, sym in T.KANDIDATEN.items():
        t0 = time.time()
        res["T3"][name] = T.t3_zufall(kerzen, fund, sym, ziehungen=ziehungen_zufall)
        schreibe(f"t03_zufall_{name}.json", "T3", name, {"ziehungen": ziehungen_zufall, "seed": T.SEED, "kosten": "K1", "variante": "S7b-D20-T3"}, zeitraum,
                 ["Wahrscheinlichkeit je Kerze = rohe Signalhäufigkeit des Kandidaten je Instrument und Abschnitt", "Richtung = Seite des SMA200"], res["T3"][name], time.time() - t0)
        print("T3", name, {s: round(v["p_einseitig"], 4) for s, v in res["T3"][name]["sektionen"].items()}, flush=True)

        t0 = time.time()
        res["T4"][name] = T.t4_raster(kerzen, fund, sym)
        schreibe(f"t04_raster_{name}.json", "T4", name, {"raster": T.RASTER, "nachbarn": T.NACHBARN, "kosten": "K1"}, zeitraum,
                 ["Rasterwerte außerhalb der 81 Nachbarzellen im Protokoll 1.0 nicht aufgezählt; im Code vor dem Lauf festgelegt (Commit siehe code_commit)", "keine Zelle wird ausgewählt"],
                 res["T4"][name], time.time() - t0)
        print("T4", name, res["T4"][name]["anteil_positiv_nachbarn"], flush=True)

        t0 = time.time()
        res["T6"][name] = T.t6_konzentration(kerzen, fund, sym)
        schreibe(f"t06_konzentration_{name}.json", "T6", name, {"kosten": "K1", "gepoolt": "Training + Validierung nach Abschnittsregel 1.2"}, zeitraum,
                 ["Weglassen von Instrumenten/Jahren aus der Tradeliste, nicht neu simuliert"], res["T6"][name], time.time() - t0)
        t0 = time.time()
        res["T7"][name] = T.t7_unsicherheit(kerzen, fund, sym)
        schreibe(f"t07_unsicherheit_{name}.json", "T7", name, {"ziehungen": T.ZIEHUNGEN_BOOTSTRAP, "seed": T.SEED, "kosten": "K1", "newey_west_lags": 4}, zeitraum,
                 ["Monatsblock-Bootstrap erfasst Abhängigkeit innerhalb eines Kalendermonats, nicht darüber hinaus"], res["T7"][name], time.time() - t0)
        t0 = time.time()
        res["T8"][name] = T.t8_dsr(kerzen, fund, sym, res["T4"][name])
        schreibe(f"t08_dsr_{name}.json", "T8", name, {"versuche": list(T.DSR_VERSUCHE), "kosten": ["K0", "K1"]}, zeitraum,
                 ["Nullfall-Varianz 1/(n-1) und Raster-Varianz als Gegenprobe", "Versuchszahl außerhalb des Registers geschätzt"], res["T8"][name], time.time() - t0)
        t0 = time.time()
        res["T9"][name] = T.t9_regime(kerzen, fund, sym)
        schreibe(f"t09_regime_{name}.json", "T9", name, {"kosten": "K1", "terzile": "Grenzen aus den Kerzen des Trainings"}, zeitraum, ["nur beschreibend, kein Beleg"], res["T9"][name], time.time() - t0)
        print("T6-T9", name, "G5", res["T6"][name]["g5_bestanden"], "G6", res["T7"][name]["g6_bestanden"], "G7", res["T8"][name]["g7_bestanden"], flush=True)

    t0 = time.time()
    res["T5"] = T.t5_komponenten(kerzen, fund)
    schreibe("t05_komponenten.json", "T5", "C1", {"kosten": "K1"}, zeitraum, ["nur Bericht (Evidenzmatrix)", "Einzelinstrument-Läufe ohne Positionsgrenze über Instrumente"], res["T5"], time.time() - t0)

    t0 = time.time()
    res["T11"], daily = K.t11_carry(wurzel)
    schreibe("t11_carry.json", "T11", "C2 (Carry-Anteil)", {"symbole": list(K.CARRY_SYMBOLE), "kosten": "4 Füllungen 0,06 % + 0,03 %", "margen": [1.0, 0.5, 0.2],
                                                            "geldmarkt": K.GELDMARKT_PROZENT}, zeitraum + "; Carry-Läufe: 2020-01-01 bis 2024-12-31",
             ["Geldmarkt-Vergleichswert ist ANNAHME", "Konstante Stückzahl: Notional wächst mit dem Kurs (BTC bis ca. 14-fach, ETH ca. 37-fach), verdeckter Hebel auf das Anfangskapital",
              "Funding aus Binance-Historie", "Spot-Gebühr Bitunix unbestätigt"], res["T11"], time.time() - t0)
    print("T11", "CG1", res["T11"]["cg1_bestanden"], "CG2", res["T11"]["cg2_bestanden"], flush=True)

    t0 = time.time()
    res["T12"], (tage, trend, carry) = {}, (None, None, None)
    for szen in ("basis_marge100", "monatlich_nachjustiert"):
        res["T12"][szen], (tage, trend, carry) = K.t12_kombination(kerzen, fund, daily, szen)
    schreibe("t12_kombination.json", "T12", "C2", {"carry_anteil": K.CARRY_ANTEIL, "trend_risiko": "1 % des Gesamtkapitals je R", "szenarien": ["basis_marge100 (Protokoll)", "monatlich_nachjustiert (Sensitivität)"]},
             zeitraum, ["Übriges Kapital = Bargeld ohne Zins (konservativ)", "Tagesreihe des Trends: Mark-to-Market zum 4h-Schluss"], res["T12"], time.time() - t0)
    t0 = time.time()
    res["T10"], reihen = K.t10_referenzen(kerzen, fund, tage, trend)
    schreibe("t10_referenzen.json", "T10", "C1 gegen R1/R2/R3", {"skalierung": "Tagesschwankung des Kandidaten, Hebel höchstens 3", "kosten_seite": 0.0009}, zeitraum,
             ["nur Bericht", "R1 ohne Neugewichtungskosten (optimistisch für die Referenz)", "gleiche Hindsight-Instrumente wie der Kandidat"], res["T10"], time.time() - t0)
    # Tagesreihen für die Grafiken ablegen
    T.schreibe(aus / "tagesreihen.json", {"tage": tage, "trend_prozent": trend, "carry_prozent_carrykapital": carry,
                                          "referenzen": {k: {"tage": v[0], "prozent": v[1]} for k, v in reihen.items() if not k.startswith("C1")}})

    t0 = time.time()
    res["T13"] = B.t13_gesamt(kerzen, fund, bitunix, str(REPO / "docs/research_lab/konsolidierung/ergebnisse/bitunix_tiefe_momentaufnahme.json"))
    schreibe("t13_bitunix.json", "T13", "C1, C3", {"bitunix_kerzen": "4h, öffentliche API, bis 2024-12-31", "kapitalstufen": list(B.KAPITAL_STUFEN)}, "Bitunix-Kerzen 2022-04-17 bis 2024-12-31",
             res["T13"]["offene_voraussetzungen"], res["T13"], time.time() - t0)
    print("T13", res["T13"]["g11_bestanden"], flush=True)

    krit = bewerte(res)
    T.schreibe(aus / "kriterien.json", {"meta": {"code_commit": commit, "code_unsauber": schmutzig, "protokoll": "PROTOKOLL_KONSOLIDIERUNG.md 1.0"}, "kriterien": krit})
    schreibe_testlog(aus.parent / "TESTLOG.md", log, commit, schmutzig, daten_version, befehl)
    return {"ergebnisse": res, "kriterien": krit}


def bewerte(res: dict) -> dict:
    """Mechanische Anwendung der Kriterien G1 bis G11, CG1, CG2, G10 und der Urteilsstufen (Protokoll Abschnitt 5)."""
    out: dict = {"G8_berichtet": G8_BERICHTET}
    g1 = bool(res["T1"]["gesamt"]["bestanden"])
    for name in ("C1", "C3"):
        g = {"G1": g1, "G2": res["T2"][name]["g2_bestanden"], "G3": res["T3"][name]["g3_bestanden"], "G4": res["T4"][name]["g4_bestanden"],
             "G5": res["T6"][name]["g5_bestanden"], "G6": res["T7"][name]["g6_bestanden"], "G7": res["T8"][name]["g7_bestanden"], "G8": G8_BERICHTET["bestanden"],
             "G11": res["T13"]["g11_bestanden"] if name == "C1" else res["T13"]["g11_bestanden_c3"]}
        stufe = 1 if not (g["G1"] and g["G2"]) else (3 if all(g.values()) else 2)
        out[name] = {"kriterien": g, "nicht_bestanden": [k for k, v in g.items() if not v], "stufe_ohne_vorwaertsbeleg": stufe}
    trend = out["C1"]["kriterien"]
    cg = {"CG1": res["T11"]["cg1_bestanden"], "CG2": res["T11"]["cg2_bestanden"], "G10": res["T12"]["basis_marge100"]["g10_bestanden"]}
    alle = {**trend, **cg}
    if not (trend["G1"] and trend["G2"]) and not cg["CG1"]:
        stufe2 = 1
    else:
        stufe2 = 3 if all(alle.values()) else 2
    out["C2"] = {"kriterien": alle, "nicht_bestanden": [k for k, v in alle.items() if not v], "stufe_ohne_vorwaertsbeleg": stufe2,
                 "hinweis": "Trendanteil = C1; G7/G8 gelten für den Trendanteil. CG1/CG2/G10 formal nach Protokoll (konstante Stückzahl); Sensitivität mit konstantem Notional in t11/t12"}
    out["gesamt_stufe_ohne_vorwaertsbeleg"] = max(out[c]["stufe_ohne_vorwaertsbeleg"] for c in ("C1", "C2", "C3"))
    out["stufen_text"] = {1: "KEIN BELASTBARER VORTEIL", 2: "INTERESSANTE HYPOTHESE, EVIDENZ UNZUREICHEND", 3: "HISTORISCH ROBUST, PROSPEKTIVER TEST AUSSTEHEND",
                          4: "FÜR BEGRENZTES PAPER-TRADING GEEIGNET (braucht Vorwärtsbeleg oder freigegebenen Holdout, hier nicht vorhanden)"}
    return out


def schreibe_testlog(pfad: Path, log: list[dict], commit: str, schmutzig: bool, daten_version: str | None, befehl: str) -> None:
    zeilen = ["# Testlog Konsolidierung (automatisch erzeugt von `lauf.py`)", "",
              f"Code-Version (Git): `{commit}`{' (Arbeitsbaum mit Änderungen!)' if schmutzig else ' (sauber für src/research_lab/konsolidierung)'}  ",
              f"Datenversion: SHA-256 von `ergebnisse/datenaudit.json` = `{daten_version}`; Rohdaten-Fingerabdrücke und Manifest-Prüfung stehen darin.  ",
              f"Befehl: `{befehl}`  ", "Protokoll: `PROTOKOLL_KONSOLIDIERUNG.md` 1.0 (eingefroren in Commit 1e9270a, vor allen neuen Rechnungen).", "",
              "| Test | Kandidat | Zeitraum | Konfiguration | Ergebnisdatei | Status | Grenzen |", "|---|---|---|---|---|---|---|"]
    for x in log:
        konf = "; ".join(f"{k}: {v}" for k, v in x["konfig"].items())
        zeilen.append(f"| {x['test']} | {x['kandidat']} | {x['zeitraum']} | {konf} | `ergebnisse/{x['datei']}` | {x['status']} | {'; '.join(x['grenzen'])} |")
    pfad.write_text("\n".join(zeilen) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print(__doc__)
        sys.exit(2)
    erg = lauf_alles(*sys.argv[1:6])
    print("kriterien", {c: erg["kriterien"][c]["nicht_bestanden"] for c in ("C1", "C2", "C3")}, "stufe", erg["kriterien"]["gesamt_stufe_ohne_vorwaertsbeleg"])
