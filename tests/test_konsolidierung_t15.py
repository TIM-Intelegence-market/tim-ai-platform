"""Tests des Zusatztests T15 (``t15_ausserhalb``): Datenbericht, Abbruchregel, Einordnung, Vorbedingungen und Prüfung der festgehaltenen Ergebnisse.

Die Datenprüfung läuft auf kleinen synthetischen Archiven (Zufallspfade im Format der Binance-Monatsdateien). Die festgehaltenen Ergebnisse
des echten Laufs (``docs/research_lab/konsolidierung/ergebnisse``) werden aus der gespeicherten Tradeliste nachgerechnet.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")  # numpy steht nicht in requirements.txt: ohne numpy wird das Modul übersprungen (wie bei den anderen research_lab-Tests)

from src.research_lab.konsolidierung import daten
from src.research_lab.konsolidierung import kennzahlen as kz
from src.research_lab.konsolidierung import t15_ausserhalb as X

KONS = Path(__file__).resolve().parents[1] / "docs" / "research_lab" / "konsolidierung"
ERG = KONS / "ergebnisse"


def _sha(pfad: Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def baue_daten(wurzel: Path, seed: int = 1, luecken: tuple[tuple[str, int, int], ...] = (("2018-03", 40, 3),), erster_tag: int = 17) -> Path:
    """Schreibt 29 Monatsarchive je Symbol (4h-Spotkerzen, Zufallspfad) und ein Manifest; ``luecken`` = (Monat, erste Position, Anzahl) je Symbol."""
    rng = np.random.default_rng(seed)
    manifest: dict = {}
    for si, sym in enumerate(X.SYMBOLE_T15):
        preis = 4000.0 * (1 + si)
        for ym in daten._monate(X.VON, X.BIS):
            a, b = X._monat_grenzen(ym)
            if ym == "2017-08":
                a = int(datetime(2017, 8, erster_tag, 4, tzinfo=timezone.utc).timestamp() * 1000)
            ts = np.arange(a, b, daten.MS_4H)
            for monat, start, anzahl in luecken:
                if ym == monat:
                    ts = np.delete(ts, np.arange(start, min(start + anzahl, len(ts))))
            zeilen = []
            for t in ts:
                r = rng.normal(0.0003, 0.012)
                o, c = preis, preis * (1 + r)
                h = max(o, c) * (1 + abs(rng.normal(0, 0.003)))
                l = min(o, c) * (1 - abs(rng.normal(0, 0.003)))
                zeilen.append(f"{t},{o:.2f},{h:.2f},{l:.2f},{c:.2f},{rng.uniform(10, 100):.3f},{t + daten.MS_4H - 1},1000.0,500,5.0,100.0,0")
                preis = c
            rel = f"spot/klines/{sym}/4h/{sym}-4h-{ym}.zip"
            pfad = wurzel / rel
            pfad.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(pfad, "w") as z:
                z.writestr(f"{sym}-4h-{ym}.csv", "\n".join(zeilen) + "\n")
            h256 = _sha(pfad)
            manifest[rel] = {"sha256": h256, "sha256_laut_checksum_datei": h256, "url": "synthetisch", "bytes": pfad.stat().st_size}
    mp = wurzel.parent / (wurzel.name + "_manifest.json")
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    return mp


@pytest.fixture(scope="module")
def sauber(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    wurzel = tmp_path_factory.mktemp("t15_sauber") / "daten"
    return wurzel, baue_daten(wurzel)


# ---------------------------------------------------------------------------------------------------------------------------------------
# Einordnung nach Abschnitt 6 des Zusatzprotokolls
# ---------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("e_r, p, klasse", [
    (0.20, 0.01, "bestätigt"),
    (0.20, 0.05, "bestätigt"),                                # p genau an der Schwelle zählt noch
    (0.154, 0.0793, "nicht bestätigt, Richtung positiv"),     # das echte Ergebnis
    (0.20, 0.0501, "nicht bestätigt, Richtung positiv"),
    (0.0, 0.001, "nicht bestätigt, Richtung negativ"),        # E[R] = 0 ist nicht größer als 0
    (-0.1, 0.9, "nicht bestätigt, Richtung negativ"),
    (None, 0.01, "nicht auswertbar"),
    (0.2, float("nan"), "nicht auswertbar"),
])
def test_einordnung(e_r, p, klasse) -> None:
    assert X.einordnung(e_r, p) == klasse


# ---------------------------------------------------------------------------------------------------------------------------------------
# Datenbericht (Abschnitt 4) und Abbruchregel
# ---------------------------------------------------------------------------------------------------------------------------------------

def test_datenbericht_auf_sauberem_archiv(sauber) -> None:
    wurzel, manifest = sauber
    res = X.datenaudit(wurzel, manifest)
    assert res["abbruch"] is False and res["abbruch_gruende"] == []
    for sym, a in res["symbole"].items():
        assert a["monatsdateien_vorhanden"] == a["monatsdateien_erwartet"] == 29
        assert a["alle_pruefsummen_ok"] and not a["lesefehler"]
        assert (a["duplikate"], a["unsortiert"], a["nicht_im_4h_raster"]) == (0, 0, 0)
        assert a["erste_kerze"] == "2017-08-17T04:00Z" and a["letzte_kerze"] == "2019-12-31T20:00Z"
        # drei fehlende Kerzen in einer Lücke im März 2018; sonst lückenlos
        assert (a["luecken_anzahl"], a["fehlend_in_luecken"], a["laengste_luecke_kerzen"]) == (1, 3, 3)
        assert a["fehlend_ab_erster_kerze"] == 3 and a["fehlend_summe_konsistent"]
        assert a["anteil_fehlend"] == pytest.approx(3 / a["erwartet_ab_erster_kerze"])
        assert [x["monat"] for x in a["monate_mit_abweichung_vom_raster"]] == ["2018-03"]
        assert a["monate_mit_abweichung_vom_raster"][0]["erwartet"] - a["monate_mit_abweichung_vom_raster"][0]["vorhanden"] == 3
        assert all(v == 0 for v in a["ungueltig"].values())
        # Vorlauf: Signale brauchen 200 lückenlose Kerzen, die Lücke setzt den Vorlauf zurück
        assert a["signalfaehige_kerzen_mit_200er_vorlauf"] < a["kerzen"] - 199
    assert res["gemeinsam"]["zeitstempel_in_beiden"] == res["symbole"]["BTCUSDT"]["kerzen"]
    assert res["gemeinsam"]["gleiche_erste_kerze"] is True


def test_abbruch_bei_geaenderter_datei(sauber, tmp_path: Path) -> None:
    wurzel, manifest = sauber
    kopie = tmp_path / "daten"
    shutil.copytree(wurzel, kopie)
    ziel = kopie / "spot/klines/ETHUSDT/4h/ETHUSDT-4h-2018-06.zip"
    with zipfile.ZipFile(ziel, "w") as z:   # gleiche Struktur, anderer Inhalt: Prüfsumme weicht vom Manifest ab
        z.writestr("ETHUSDT-4h-2018-06.csv", "1528070400000,1,2,0.5,1.5,1,1528084799999,1,1,1,1,0\n")
    res = X.datenaudit(kopie, manifest)
    assert res["abbruch"] is True
    assert any("ETHUSDT" in g and "Prüfsumme" in g for g in res["abbruch_gruende"])
    assert res["symbole"]["BTCUSDT"]["alle_pruefsummen_ok"] is True   # nur das betroffene Symbol


def test_abbruch_bei_fehlendem_monat(sauber, tmp_path: Path) -> None:
    wurzel, manifest = sauber
    kopie = tmp_path / "daten"
    shutil.copytree(wurzel, kopie)
    (kopie / "spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-02.zip").unlink()
    res = X.datenaudit(kopie, manifest)
    assert res["abbruch"] is True
    assert any("28 von 29 Monatsdateien" in g for g in res["abbruch_gruende"])


def test_abbruch_bei_mehr_als_fuenf_prozent_fehlender_kerzen(tmp_path: Path) -> None:
    # 180 von 186 Kerzen im März 2018 und 120 von 180 im April fehlen: 300 von etwa 5 200 = 5,8 %
    wurzel = tmp_path / "daten"
    manifest = baue_daten(wurzel, luecken=(("2018-03", 3, 180), ("2018-04", 20, 120)))
    res = X.datenaudit(wurzel, manifest)
    assert res["abbruch"] is True
    assert all(a["anteil_fehlend"] > X.SCHWELLE_FEHLEND for a in res["symbole"].values())
    assert any("Schwelle 5%" in g for g in res["abbruch_gruende"])


def test_schwelle_fuenf_prozent_liegt_darunter_und_darueber() -> None:
    assert X.SCHWELLE_FEHLEND == 0.05 and X.ERWARTETE_MONATE == 29
    assert X.SYMBOLE_T15 == ("BTCUSDT", "ETHUSDT")   # SOL gibt es 2017 bis 2019 nicht: nur C3


# ---------------------------------------------------------------------------------------------------------------------------------------
# Handelslauf auf synthetischen Daten (nur Mechanik; das echte Ergebnis steht unten)
# ---------------------------------------------------------------------------------------------------------------------------------------

def test_handelslauf_struktur_und_reproduzierbarkeit(sauber) -> None:
    wurzel, _ = sauber
    kerzen = {s: daten.laden(wurzel, X.MARKT, s, "4h", X.VON, X.BIS) for s in X.SYMBOLE_T15}
    res, trades = X.handelslauf(kerzen, ziehungen_zufall=10, ziehungen_bootstrap=300)
    res2, _ = X.handelslauf(kerzen, ziehungen_zufall=10, ziehungen_bootstrap=300)
    assert res["p1"] == res2["p1"] and res["p3"]["p_einseitig"] == res2["p3"]["p_einseitig"]   # feste Seeds
    assert res["p1"]["n"] == len(trades["K2"]) == len(res["trades_k2"])
    assert set(res["p2"]) == {"K1", "K0"}
    assert 0.0 <= res["p1"]["p_monatsblock_bootstrap_einseitig"] <= 1.0
    lo, hi = res["p1"]["ci95_bootstrap"]
    assert lo < res["p1"]["e_r"] < hi
    assert res["einordnung"]["klasse"] == X.einordnung(res["p1"]["e_r"], res["p1"]["p_monatsblock_bootstrap_einseitig"])
    # nie mehr als eine Position gleichzeitig (über beide Symbole)
    t = sorted(trades["K2"], key=lambda x: x.einstieg_zeit)
    assert all(a.ausstieg_zeit <= b.einstieg_zeit for a, b in zip(t, t[1:]))
    # Kosten: K2 ist strenger als K1 und K0, je Trade gemessen auf denselben Einstiegen
    assert np.mean([x.kosten_r for x in trades["K2"]]) > 0


# ---------------------------------------------------------------------------------------------------------------------------------------
# Vorbedingungen: genau ein Lauf, festgehaltener Datenbericht
# ---------------------------------------------------------------------------------------------------------------------------------------

def test_zweiter_lauf_wird_verweigert() -> None:
    # t15_ausserhalb.json liegt im Repo: die Vorbedingungen müssen den Start verweigern
    with pytest.raises(X.Vorbedingung, match="genau ein Lauf"):
        X.pruefe_vorbedingungen(Path("/nonexistent"), ERG)


def test_lauf_ohne_datenbericht_wird_verweigert(tmp_path: Path) -> None:
    with pytest.raises(X.Vorbedingung, match="Datenbericht t15_datenaudit.json fehlt"):
        X.pruefe_vorbedingungen(tmp_path, tmp_path / "leer")


def test_lauf_mit_abgewichenen_daten_oder_nicht_festgehaltenem_bericht_wird_verweigert(sauber, tmp_path: Path) -> None:
    wurzel, manifest = sauber
    kopie = tmp_path / "daten"
    shutil.copytree(wurzel, kopie)
    ausgabe = tmp_path / "ergebnisse"
    ausgabe.mkdir()
    X.lauf_audit(str(kopie), str(manifest), ausgabe)   # Datenbericht auf den synthetischen Daten
    # Eine Datei ändern, nachdem der Bericht geschrieben wurde: der Handelslauf darf nicht starten
    with zipfile.ZipFile(kopie / "spot/klines/BTCUSDT/4h/BTCUSDT-4h-2018-01.zip", "w") as z:
        z.writestr("BTCUSDT-4h-2018-01.csv", "1514764800000,1,2,0.5,1.5,1,1514779199999,1,1,1,1,0\n")
    with pytest.raises(X.Vorbedingung) as fehler:
        X.pruefe_vorbedingungen(kopie, ausgabe)
    meldung = str(fehler.value)
    assert "Datei weicht vom Datenbericht ab oder fehlt: spot/klines/BTCUSDT/4h/BTCUSDT-4h-2018-01.zip" in meldung
    assert "nicht festgehalten" in meldung   # der Bericht liegt nicht versioniert im Repo (Commit fehlt)


def test_lauf_mit_ausgelöster_abbruchregel_wird_verweigert(tmp_path: Path) -> None:
    wurzel = tmp_path / "daten"
    manifest = baue_daten(wurzel, luecken=(("2018-03", 3, 180), ("2018-04", 20, 120)))
    ausgabe = tmp_path / "ergebnisse"
    ausgabe.mkdir()
    X.lauf_audit(str(wurzel), str(manifest), ausgabe)
    with pytest.raises(X.Vorbedingung, match="Abbruchregel im Datenbericht ausgelöst"):
        X.pruefe_vorbedingungen(wurzel, ausgabe)


# ---------------------------------------------------------------------------------------------------------------------------------------
# Festgehaltene Ergebnisse des echten Laufs: Hashes, Reihenfolge, Nachrechnung aus der Tradeliste
# ---------------------------------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def echt() -> dict:
    return {"lauf": json.loads((ERG / "t15_ausserhalb.json").read_text(encoding="utf-8")),
            "audit": json.loads((ERG / "t15_datenaudit.json").read_text(encoding="utf-8")),
            "stand": json.loads((ERG / "PROTOKOLL_STAND.json").read_text(encoding="utf-8"))}


def test_protokolle_und_datenbericht_entsprechen_den_festgehaltenen_hashes(echt) -> None:
    assert _sha(KONS / "PROTOKOLL_KONSOLIDIERUNG.md") == echt["stand"]["sha256"]   # Protokoll 1.0 ist unverändert
    meta = echt["lauf"]["meta"]
    assert meta["protokoll_1_0_sha256"] == echt["stand"]["sha256"]
    assert meta["protokoll_t15_sha256"] == _sha(KONS / "PROTOKOLL_KONSOLIDIERUNG_T15.md")   # Zusatzprotokoll unverändert
    assert meta["datenaudit_sha256"] == _sha(ERG / "t15_datenaudit.json")                    # Lauf stützt sich auf genau diesen Bericht
    assert meta["code_unsauber"] is False and meta["seed"] == 20261116
    assert echt["audit"]["meta"]["protokoll_t15_sha256"] == meta["protokoll_t15_sha256"]


def test_datenbericht_hat_keine_abbruchbedingung_und_je_symbol_29_geprueft_dateien(echt) -> None:
    a = echt["audit"]["ergebnis"]
    assert a["abbruch"] is False and a["abbruch_gruende"] == []
    for s in X.SYMBOLE_T15:
        sym = a["symbole"][s]
        assert sym["monatsdateien_vorhanden"] == 29 and sym["alle_pruefsummen_ok"]
        assert all(d["sha256"] == d["sha256_manifest"] == d["sha256_checksum_datei"] for d in sym["dateien"])
        assert sym["anteil_fehlend"] < X.SCHWELLE_FEHLEND
        assert sym["letzte_kerze"] < "2020-01-01"   # keine Daten ab 2020 (und damit auch nicht aus dem Holdout)
    assert a["gemeinsam"]["nur_BTCUSDT"] == a["gemeinsam"]["nur_ETHUSDT"] == 0


def test_t15_kennzahlen_stimmen_mit_der_gespeicherten_tradeliste_ueberein(echt) -> None:
    e = echt["lauf"]["ergebnis"]
    t = e["trades_k2"]
    r = np.array([x["r"] for x in t])
    assert len(t) == e["p1"]["n"] == e["primaer_k2"]["kennzahlen"]["n"] == 157
    assert r.mean() == pytest.approx(e["p1"]["e_r"], abs=1e-6)
    assert r.sum() == pytest.approx(e["primaer_k2"]["kennzahlen"]["summe_r"], abs=1e-4)
    assert (r > 0).mean() == pytest.approx(e["p7"]["trefferquote"])
    assert kz.profit_faktor(r) == pytest.approx(e["p7"]["profit_faktor"], abs=1e-5)
    ordnung = sorted(t, key=lambda x: x["ausstieg_ms"])
    assert kz.max_drawdown(np.array([x["r"] for x in ordnung]))[0] == pytest.approx(e["p5"]["max_drawdown_r"], abs=1e-4)
    # jeder Trade: Netto = Brutto - Kosten (Funding ist aus)
    assert all(x["r"] == pytest.approx(x["brutto_r"] - x["kosten_r"], abs=2e-6) for x in t)
    lo, hi = kz.wilson(int((r > 0).sum()), len(r))
    assert [lo, hi] == pytest.approx(e["p7"]["trefferquote_ci95_wilson"], abs=1e-6)


def test_t15_tradeliste_beachtet_regeln_und_zeitraum(echt) -> None:
    t = sorted(echt["lauf"]["ergebnis"]["trades_k2"], key=lambda x: x["einstieg_ms"])
    erste_signalfaehige = int(datetime(2017, 10, 10, tzinfo=timezone.utc).timestamp() * 1000)
    ende = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    assert all(x["signal_ms"] >= erste_signalfaehige for x in t)             # kein Signal ohne 200 lückenlose Vorlaufkerzen
    assert all(x["ausstieg_ms"] <= ende + daten.MS_4H for x in t)            # nichts aus 2020 oder dem Holdout
    assert all(a["ausstieg_ms"] <= b["einstieg_ms"] for a, b in zip(t, t[1:]))   # höchstens eine Position über beide Symbole
    assert all(x["einstieg_ms"] == x["signal_ms"] + daten.MS_4H for x in t)  # Einstieg zur Eröffnung der Folgekerze
    assert {x["symbol"] for x in t} == {"BTCUSDT", "ETHUSDT"}
    assert all(x["kerzen"] <= 30 for x in t)                                 # Zeitstopp 30 Kerzen
    assert {x["grund"] for x in t} <= {"stop", "target", "time", "gap", "stop_vor_einstieg"}


def test_t15_p_wert_und_einordnung_sind_aus_den_ziehungen_abgeleitet(echt) -> None:
    e = echt["lauf"]["ergebnis"]
    p1 = e["p1"]
    assert p1["p_monatsblock_bootstrap_einseitig"] == pytest.approx(p1["ziehungen_mit_mittel_nicht_positiv"] / 10_000)
    assert p1["erfuellt"] is (p1["e_r_groesser_null"] and p1["p_monatsblock_bootstrap_einseitig"] <= 0.05) is False
    assert e["einordnung"]["klasse"] == X.einordnung(p1["e_r"], p1["p_monatsblock_bootstrap_einseitig"]) == "nicht bestätigt, Richtung positiv"
    assert e["p3"]["p_einseitig"] == pytest.approx(np.mean(np.array(e["p3"]["e_r_zufall_werte"]) >= e["p3"]["kandidat_e_r"]), abs=1e-3)
    assert e["p3"]["gueltige_ziehungen"] == 1000
