"""Tests von Studienregister, Evidenzmatrix, Logbuch-Abgleich und Studiengenerator der Konsolidierung.

Geprüft wird die Form (Pflichtfelder, erlaubte Werte, keine doppelten Ids), die Zählungen, die Arithmetik der Kapitalrechnung und dass die
gespeicherten Dokumente (Register, Matrix, Studie) exakt dem entsprechen, was der Code aus den Ergebnisdateien erzeugt. Die Erwartungswerte
der Rechenhilfen stammen aus Handrechnung, nicht aus dem getesteten Code.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pytest

from src.research_lab.konsolidierung import evidenz, logbuch_abgleich as lb, register, register_schema as schema, studie

WURZEL = Path(__file__).resolve().parents[1]
KONS = WURZEL / "docs" / "research_lab" / "konsolidierung"
ERG = KONS / "ergebnisse"

ABSCHNITTE = (
    "## 1. Kurzzusammenfassung und belastbares Gesamturteil",
    "## 2. Suchumfang und vollständiges Studienregister",
    "## 3. Daten- und Methodikprüfung",
    "## 4. Fehler, ausgeschlossene Ergebnisse und Begründungen",
    "## 5. Vergleichbare neu berechnete Resultate",
    "## 6. Evidenzmatrix der tragfähigen Erkenntnisse",
    "## 7. Herleitung der konsolidierten Kandidaten",
    "## 8. Vorab festgelegtes Validierungsprotokoll",
    "## 9. Ergebnisse inklusive negativer und widersprüchlicher Befunde",
    "## 10. Unsicherheit, Robustheit und praktische Grenzen",
    "## 11. Vollständig spezifizierte bevorzugte Strategie, falls gerechtfertigt",
    "## 12. Konkreter nächster Forschungs- oder Paper-Trading-Schritt",
)


@pytest.fixture(scope="module")
def eintraege() -> list[dict]:
    return register.alle_eintraege()


@pytest.fixture(scope="module")
def zeilen() -> list[dict]:
    return evidenz.zeilen(evidenz.lade_zahlen(ERG))


@pytest.fixture(scope="module")
def studientext() -> str:
    """Studie aus den gespeicherten Ergebnisdateien (der Generator arbeitet mit relativen Pfaden, daher aus dem Wurzelordner)."""
    alt = Path.cwd()
    import os
    os.chdir(WURZEL)
    try:
        return studie.baue()
    finally:
        os.chdir(alt)


# --- Register -------------------------------------------------------------------------------------------------------------------------

def test_register_ist_formal_in_ordnung(eintraege) -> None:
    assert schema.pruefe(eintraege) == []
    ids = [x["id"] for x in eintraege]
    assert len(ids) == len(set(ids)) == 74


def test_register_werte_liegen_im_schema(eintraege) -> None:
    for x in eintraege:
        assert x["klasse"] in schema.KLASSEN, x["id"]
        assert x["pruefung"] in schema.PRUEFTIEFEN, x["id"]
        assert x["cluster"] in schema.CLUSTER, x["id"]
        assert x["aussagen"], x["id"]
        for a in x["aussagen"]:
            assert a["status"] in schema.AUSSAGE_STATUS and a["text"].strip(), x["id"]
        assert set(schema.PFLICHTFELDER) <= set(x), x["id"]


def test_belastbar_setzt_pruefung_durch_rechnung_voraus_und_ist_nie_positiver_beleg(eintraege) -> None:
    for x in eintraege:
        if x["klasse"] == "BELASTBAR":
            assert x["pruefung"] in ("A", "B"), x["id"]
    z = register.zusammenfassung(eintraege)
    assert z["belastbar_positiv"] == []      # keine belastbare Studie mit positivem Befund
    assert z["ungueltig"] == []
    # Negativ- und Nullbefunde dürfen belastbar sein: das ist eine Aussage über die Rechnung, nicht über die Richtung
    assert sorted(x["id"] for x in eintraege if x["klasse"] == "BELASTBAR") == ["S34", "S35a", "S36", "S38"]


def test_zusammenfassung_trennt_gefundene_studien_von_eigenen_nachrechnungen(eintraege) -> None:
    z = register.zusammenfassung(eintraege)
    assert (z["eintraege_gesamt"], z["gefundene_studien_und_berichte"], z["eigene_nachrechnungen"]) == (74, 69, 5)
    assert sum(z["nach_klasse"].values()) == 69
    assert sum(z["nach_pruefung"].values()) == 69
    assert sum(z["nach_cluster"].values()) == 69 and "EIGEN" not in z["nach_cluster"]
    assert z["nach_pruefung"] == {"A": 2, "B": 8, "C+": 23, "C": 27, "D": 9}
    assert z["nach_klasse"] == {"BEDINGT VERWERTBAR": 31, "EXPLORATIV": 30, "NICHT REPRODUZIERBAR": 4, "BELASTBAR": 4}
    assert [x["id"] for x in eintraege if x["cluster"] == "EIGEN"] == ["K-C1", "K-Carry", "K-Ref", "K-Bitunix", "K-T15"]


def test_register_pruefung_erkennt_formfehler(eintraege) -> None:
    ok = copy.deepcopy(eintraege[:3])
    assert schema.pruefe(ok) == []
    doppelt = ok + [copy.deepcopy(ok[0])]
    assert any("doppelt" in f for f in schema.pruefe(doppelt))
    leer = copy.deepcopy(ok)
    leer[1]["ergebnis"] = ""
    assert any("ergebnis leer" in f for f in schema.pruefe(leer))
    fehlt = copy.deepcopy(ok)
    del fehlt[2]["verwendung"]
    assert any("verwendung fehlt" in f for f in schema.pruefe(fehlt))
    ohne_aussage = copy.deepcopy(ok)
    ohne_aussage[0]["aussagen"] = []
    assert any("keine Aussagen" in f for f in schema.pruefe(ohne_aussage))
    schwach = copy.deepcopy(ok)
    schwach[0]["klasse"], schwach[0]["pruefung"] = "BELASTBAR", "C"
    assert any("BELASTBAR setzt Prüftiefe" in f for f in schema.pruefe(schwach))


def test_eintrag_baukasten_verweigert_unbekannte_werte() -> None:
    basis = dict(id="X", titel="t", cluster="EIGEN", typ="x", datum="2026-11-16", quellen=["q"], daten="d", aufteilung="a", kosten="k", register="r",
                 stichprobe="s", ergebnis="e", laborurteil="l", pruefung="A", klasse="EXPLORATIV", richtung="null", begruendung="b", maengel=[],
                 aussagen=[("a", "VERIFIZIERT")], verwendung="v")
    assert schema.e(**basis)["aussagen"] == [{"text": "a", "status": "VERIFIZIERT"}]
    for feld, wert in (("cluster", "ERFUNDEN"), ("pruefung", "Z"), ("klasse", "SUPER"), ("aussagen", [("a", "GLAUBHAFT")])):
        with pytest.raises(AssertionError):
            schema.e(**{**basis, feld: wert})


def test_gespeichertes_register_entspricht_dem_code(eintraege) -> None:
    gespeichert = json.loads((KONS / "studienregister.json").read_text(encoding="utf-8"))
    assert [x["id"] for x in gespeichert["eintraege"]] == [x["id"] for x in eintraege]
    assert gespeichert["zusammenfassung"] == json.loads(json.dumps(register.zusammenfassung(eintraege)))
    md = (KONS / "STUDIENREGISTER.md").read_text(encoding="utf-8")
    assert md.rstrip("\n") == register.markdown(eintraege).rstrip("\n")


# --- Evidenzmatrix --------------------------------------------------------------------------------------------------------------------

def test_kapitalbedarf_ist_reine_arithmetik() -> None:
    # 0,24 R × 8,5 Trades/Monat × 12 = 24,48 R pro Jahr; 50 USDT × 365 = 18.250 USDT; je R: 745,5 USDT; bei 1 % Risiko 74.550 USDT Kapital
    k = evidenz.kapitalbedarf(0.24, 8.5, 0.01)
    assert k["jahres_r"] == pytest.approx(24.48)
    assert k["usdt_je_r"] == pytest.approx(18_250 / 24.48)
    assert k["kapital_usdt"] == pytest.approx(18_250 / 24.48 / 0.01)
    assert evidenz.kapitalbedarf(0.24, 8.5, 0.02)["kapital_usdt"] == pytest.approx(k["kapital_usdt"] / 2)   # doppeltes Risiko, halbes Kapital
    assert evidenz.kapitalbedarf(0.24, 8.5, 0.01, ziel_usdt_pro_tag=100.0)["kapital_usdt"] == pytest.approx(2 * k["kapital_usdt"])


@pytest.mark.parametrize("e_r", [0.0, -0.05])
def test_kapitalbedarf_ohne_positive_erwartung_ist_nicht_definiert(e_r) -> None:
    k = evidenz.kapitalbedarf(e_r, 8.5, 0.01)
    assert k["usdt_je_r"] is None and k["kapital_usdt"] is None   # keine Ersatzzahl, kein "unendlich"


def test_zahlenformat_mit_dezimalkomma_und_echtem_minus() -> None:
    assert evidenz.de(0.239, 3, vz=True) == "+0,239"
    assert evidenz.de(-0.5, 2) == "−0,50"          # U+2212, nicht der Bindestrich
    assert evidenz.ganz(26_707) == "26.707" and evidenz.ganz(999.6) == "1.000"
    assert evidenz.pct(0.384) == "38,4 %"
    assert studie.dsep(1999.12) == "1.999,1"
    assert studie.dsep(-1234.56, 1) == "−1.234,6"


def test_evidenzmatrix_ist_vollstaendig_und_konsistent(zeilen) -> None:
    assert evidenz.pruefe(zeilen) == []
    ab = evidenz.abdeckung(zeilen)
    assert (ab["genannt"], ab["gefunden"], ab["nicht_genannt"]) == (69, 69, [])   # jede gefundene Studie ist einer Erkenntnis zugeordnet
    assert [r["nr"] for r in zeilen][:3] == ["E1", "E1b", "E2"] and len(zeilen) == 18


def test_evidenzmatrix_pruefung_erkennt_fehler(zeilen) -> None:
    kopie = copy.deepcopy(zeilen)
    kopie[0]["unterstuetzende_ids"] = kopie[0]["unterstuetzende_ids"] + ["S99999"]
    assert any("unbekannte Studie S99999" in f for f in evidenz.pruefe(kopie))
    kopie = copy.deepcopy(zeilen)
    kopie[1]["konsequenz"] = ""
    assert any("konsequenz leer" in f for f in evidenz.pruefe(kopie))
    kopie = copy.deepcopy(zeilen)
    kopie.append(copy.deepcopy(kopie[0]))
    assert "Nummern doppelt" in evidenz.pruefe(kopie)
    ab = evidenz.abdeckung([r for r in zeilen if r["nr"] != "E1"])
    assert ab["genannt"] <= 69       # fehlt eine Zeile, darf die Abdeckung nicht größer werden


def test_gespeicherte_evidenzmatrix_entspricht_den_ergebnisdateien(zeilen) -> None:
    gespeichert = json.loads((KONS / "evidenzmatrix.json").read_text(encoding="utf-8"))
    assert gespeichert["zeilen"] == json.loads(json.dumps(zeilen))
    assert gespeichert["stufen"] == list(evidenz.STUFEN)
    md = (KONS / "EVIDENZMATRIX.md").read_text(encoding="utf-8")
    assert md.rstrip("\n") == evidenz.markdown(zeilen, evidenz.abdeckung(zeilen)).rstrip("\n")
    stichworte = ("historisch gut ausgesehen", "reproduziert", "außerhalb der entwicklung", "prospektiv", "evidenzstufe")
    for r in zeilen:
        text = r["evidenzstand"].lower()
        assert any(s in text for s in stichworte), r["nr"]                       # jede Zeile sagt, welche Stufen erreicht sind
        assert "außerhalb der entwicklung bestätigt: ja" not in text, r["nr"]    # keine Erkenntnis ist außerhalb der Entwicklung bestätigt


# --- Logbuch-Abgleich -----------------------------------------------------------------------------------------------------------------

def test_zahlen_aus_text_erkennt_deutsche_zahlen_und_uebergeht_zaehler_und_jahre() -> None:
    z = lb.zahlen_aus_text("n 1.234, E[R] −0,17 und +0,239; 12 345 Zeilen, 2024, 38 Trades, 0,81")
    assert [(a["wert"], a["stellen"]) for a in z] == [(1234.0, 0), (-0.17, 2), (0.239, 3), (12345.0, 0), (0.81, 2)]
    assert lb.zahlen_aus_text("Jahre 2020 bis 2024, 7 von 50") == []


def test_werte_aus_json_nimmt_nur_endliche_zahlen_und_keine_wahrheitswerte() -> None:
    w = lb.werte_aus_json({"a": 1, "b": [2.5, True, None, "x", float("nan"), float("inf")], "c": {"d": -3}})
    assert w.tolist() == [-3.0, 1.0, 2.5]


@pytest.mark.parametrize("zahl,gefunden", [
    ({"text": "0,24", "wert": 0.24, "stellen": 2}, True),      # direkt
    ({"text": "−0,24", "wert": -0.24, "stellen": 2}, True),     # Vorzeichen des Logbuchs darf von der Datei abweichen
    ({"text": "24,0", "wert": 24.0, "stellen": 1}, True),      # Prozent statt Anteil (0,24 → 24 %)
    ({"text": "0,25", "wert": 0.25, "stellen": 2}, False),
    ({"text": "7,00", "wert": 7.0, "stellen": 2}, False),
])
def test_gefunden_rundet_auf_die_angegebene_stellenzahl(zahl, gefunden) -> None:
    assert lb.gefunden(zahl, np.sort(np.array([0.24, 3.0, 0.5]))) is gefunden


def test_gespeicherter_abgleich_nennt_die_nicht_gefundenen_zahlen_offen() -> None:
    erg = json.loads((ERG / "logbuch_abgleich.json").read_text(encoding="utf-8"))
    assert erg, "Abgleich leer"
    for sid, r in erg.items():
        if "zahlen_im_logbuch" in r:
            assert r["davon_in_datei"] + len(r["nicht_gefunden"]) == r["zahlen_im_logbuch"], sid


# --- Studiengenerator -----------------------------------------------------------------------------------------------------------------

def test_power_und_stichprobenrechnung_von_hand() -> None:
    # Einseitig 5 %, Power 80 %: n = ((1,6449 + 0,8416) × sd / e)² = (2,4865 × 1,72 / 0,24)² = 317,6 → 318 Trades
    assert studie.n_trades_bis_power(0.24, 1.72) == 318
    assert studie.n_trades_bis_power(0.154, 1.72) in range(765, 775)
    assert studie.power(0.24, 1.72, 30) == pytest.approx(0.19, abs=0.01)
    assert studie.power(0.24, 1.72, 318) == pytest.approx(0.80, abs=0.01)
    assert studie.holdout_trades(8.48) == 153 and studie.holdout_trades(8.48, monate=12) == 102


def test_studie_hat_die_zwoelf_abschnitte_in_der_vorgegebenen_reihenfolge(studientext) -> None:
    lage = [studientext.index("\n" + a + "\n") for a in ABSCHNITTE]
    assert lage == sorted(lage)
    assert studientext.count("\n## ") == 13                  # zwölf Abschnitte plus Abschlussurteil
    assert studientext.index("\n## Abschlussurteil und nächste Entscheidung\n") > lage[-1]


def test_studie_enthaelt_das_urteil_aus_den_vier_zulaessigen_und_keine_freigabe(studientext) -> None:
    zulaessig = ("KEIN BELASTBARER VORTEIL", "INTERESSANTE HYPOTHESE, EVIDENZ UNZUREICHEND",
                 "HISTORISCH ROBUST, PROSPEKTIVER TEST AUSSTEHEND", "FÜR BEGRENZTES PAPER-TRADING GEEIGNET")
    assert "INTERESSANTE HYPOTHESE, EVIDENZ UNZUREICHEND" in studientext
    assert "TRADING_AUTHORIZED=NO" in studientext and "keine Echtgeld-Freigabe" in studientext
    # ein einziges Gesamturteil; die beiden stärkeren Urteile werden nirgends ausgesprochen, "KEIN BELASTBARER VORTEIL" gilt für die übrigen Familien
    assert studientext.count("**Gesamturteil: ") == 1
    assert "**Gesamturteil: INTERESSANTE HYPOTHESE, EVIDENZ UNZUREICHEND.**" in studientext
    for stark in zulaessig[2:]:
        assert f"**{stark}" not in studientext, stark
    assert "**KEIN BELASTBARER VORTEIL**" in studientext


def test_studie_hat_keine_platzhalter_und_keine_fehlenden_werte(studientext) -> None:
    assert "None" not in studientext and "nan" not in re.sub(r"[A-Za-zäöüß]nan|nan[A-Za-zäöüß]", "", studientext)
    assert "{" not in studientext and "}" not in studientext     # keine unaufgelösten Formatierungsfelder
    assert "TODO" not in studientext and "XXX" not in studientext


def test_gespeicherte_studie_entspricht_dem_generator(studientext) -> None:
    gespeichert = (KONS / "KONSOLIDIERTE_STUDIE.md").read_text(encoding="utf-8")
    assert gespeichert == studientext


def test_bilder_der_studie_sind_vorhanden_und_nicht_leer(studientext) -> None:
    links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", studientext)
    assert len(links) == 6
    for rel in links:
        pfad = KONS / rel
        assert pfad.is_file() and pfad.stat().st_size > 5_000, rel
        assert pfad.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", rel


def test_studie_nennt_den_festgehaltenen_protokollstand(studientext) -> None:
    stand = json.loads((ERG / "PROTOKOLL_STAND.json").read_text(encoding="utf-8"))
    assert stand["sha256"][:12] in studientext and stand["git_commit"][:7] in studientext
    assert hashlib.sha256((KONS / "PROTOKOLL_KONSOLIDIERUNG.md").read_bytes()).hexdigest() == stand["sha256"]


def test_studie_zahlen_stimmen_mit_den_ergebnisdateien_und_dem_register(studientext) -> None:
    pooled = json.loads((ERG / "t07_unsicherheit_C1.json").read_text(encoding="utf-8"))["ergebnis"]["pooled"]["kennzahlen"]
    assert f"{evidenz.de(pooled['e_r'], 3, vz=True)} R je Trade (K1), n {pooled['n']}" in studientext
    reg = json.loads((KONS / "studienregister.json").read_text(encoding="utf-8"))["zusammenfassung"]
    assert (f"{reg['eintraege_gesamt']} Einträge: {reg['gefundene_studien_und_berichte']} gefundene Studien und Berichte, "
            f"{reg['eigene_nachrechnungen']} eigene Nachrechnungen") in studientext
