"""Tests der unabhängigen Nachrechnung der Trendregel S7b (``s7b_nachrechnung``) und des Laders mit Holdout-Schranke (``daten``).

Die Kerzenreihen sind von Hand gebaut, damit jedes Ergebnis aus der Regel ableitbar ist:

* 240 flache Kerzen (Eröffnung = Schluss = 100, Hoch 100,5, Tief 99,5; True Range 1,0, SMA200 = 100),
* Ausbruchskerze Nr. 240 (Eröffnung 100, Hoch 102,2, Tief 100,0, Schluss 102),
* ATR14 dort = (13 x 1,0 + 2,2) / 14, Anfangsrisiko R0 = max(1,5 x ATR14, 1 % x 102) = 1,628571,
  Stop = 102 - R0 = 100,371429, Ziel (3 R) = 102 + 3 x R0 = 106,885714.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pytest

from src.research_lab.konsolidierung import daten
from src.research_lab.konsolidierung import s7b_nachrechnung as s7b
from src.research_lab.konsolidierung.daten import Funding, Kerzen
from src.research_lab.konsolidierung.s7b_nachrechnung import Kosten, Trade, Variante

MS = daten.MS_4H
START = 1_577_836_800_000  # 2020-01-01T00:00Z, liegt im 4h-Raster
ATR = (13 * 1.0 + 2.2) / 14
R0 = max(1.5 * ATR, 0.01 * 102.0)
STOP = 102.0 - R0
ZIEL = 102.0 + 3 * R0
OHNE_KOSTEN = Kosten(gebuehr=0.0, slip_einstieg=0.0, slip_ziel=0.0, slip_zeit=0.0, slip_stop=0.0, funding="aus")
V = Variante(20, 3.0)


def kerzenreihe(symbol: str, o, h, l, c, luecken: tuple[int, ...] = ()) -> Kerzen:
    n = len(c)
    t = START + np.arange(n, dtype=np.int64) * MS
    keep = np.ones(n, dtype=bool)
    for i in luecken:
        keep[i] = False
    f = lambda a: np.asarray(a, dtype=float)[keep]  # noqa: E731
    return Kerzen(symbol, "4h", t[keep], f(o), f(h), f(l), f(c), np.ones(int(keep.sum())), np.zeros(int(keep.sum())), int(keep.sum()), 0, 0)


def aufbau(folge: list[tuple[float, float, float, float]], flach: int = 240, spiegeln: bool = False, luecken: tuple[int, ...] = (), symbol: str = "BTCUSDT") -> Kerzen:
    """``flach`` flache Kerzen, die Ausbruchskerze (Nr. 240 bei Standardwert) und danach die Kerzen aus ``folge`` als (o, h, l, c)."""
    zeilen = [(100.0, 100.5, 99.5, 100.0)] * flach + [(100.0, 102.2, 100.0, 102.0)] + list(folge)
    o, h, l, c = (np.array(x, dtype=float) for x in zip(*zeilen))
    if spiegeln:  # Spiegelung um 100: aus Long wird Short, Hoch und Tief tauschen
        o, h, l, c = 200 - o, 200 - l, 200 - h, 200 - c
    return kerzenreihe(symbol, o, h, l, c, luecken)


def lauf(kerzen: dict[str, Kerzen], kosten: Kosten = OHNE_KOSTEN, v: Variante = V, funding: dict | None = None, **kw) -> list[Trade]:
    return s7b.simuliere(kerzen, funding if funding is not None else {s: None for s in kerzen}, v, kosten, **kw)


def einzel(folge, **kw) -> list[Trade]:
    return lauf({"BTCUSDT": aufbau(folge, **kw)})


# ---------------------------------------------------------------------------------------------------------------------------------------
# Regel: Signal, Einstieg, Stop, Ziel, Zeitstopp
# ---------------------------------------------------------------------------------------------------------------------------------------

def test_anfangsrisiko_und_signal_der_ausbruchskerze() -> None:
    reihe = s7b.bereite_vor(aufbau([]), V)
    assert reihe.sig[240] == 1 and int(np.count_nonzero(reihe.sig)) == 1   # genau ein Signal: die Ausbruchskerze
    assert reihe.atr[240] == pytest.approx(ATR)
    assert reihe.r0[240] == pytest.approx(R0)
    assert reihe.stop_signal[240] == pytest.approx(STOP)


def test_mindestrisiko_greift_bei_kleiner_atr() -> None:
    # Bei ruhigem Markt ist 1,5 x ATR kleiner als 1 % vom Schluss: dann gilt das Mindestrisiko
    n = 240
    o = np.full(n, 100.0)
    h = np.full(n, 100.05)
    l = np.full(n, 99.95)
    c = np.full(n, 100.0)
    h = np.append(h, 100.2)
    l = np.append(l, 100.0)
    o = np.append(o, 100.0)
    c = np.append(c, 100.15)
    reihe = s7b.bereite_vor(kerzenreihe("BTCUSDT", o, h, l, c), V)
    assert reihe.sig[240] == 1
    assert reihe.r0[240] == pytest.approx(0.01 * 100.15)


def test_ziel_nach_3r_bringt_plus_3r_ohne_kosten() -> None:
    t, = einzel([(102.0, 107.0, 101.5, 106.5)])
    assert (t.grund, t.seite, t.kerzen) == ("target", 1, 1)
    assert t.einstieg == pytest.approx(102.0)
    assert t.ausstieg == pytest.approx(ZIEL)
    assert t.brutto_r == pytest.approx(3.0) and t.r == pytest.approx(3.0)
    assert t.signal_zeit == START + 240 * MS and t.einstieg_zeit == START + 241 * MS and t.ausstieg_zeit == START + 242 * MS


def test_stop_bringt_minus_1r() -> None:
    t, = einzel([(102.0, 102.5, 100.0, 100.2)])
    assert t.grund == "stop" and t.ausstieg == pytest.approx(STOP)
    assert t.r == pytest.approx(-1.0)


def test_stop_gewinnt_vor_dem_ziel_innerhalb_derselben_kerze() -> None:
    t, = einzel([(102.0, 107.0, 100.0, 105.0)])   # Hoch über dem Ziel und Tief unter dem Stop in einer Kerze
    assert t.grund == "stop" and t.r == pytest.approx(-1.0)


def test_luecke_ueber_den_stop_fuellt_zum_eroeffnungskurs() -> None:
    t, = einzel([(102.0, 102.5, 101.0, 102.0), (99.0, 99.5, 98.0, 98.5)])   # zweite Kerze eröffnet unter dem Stop
    assert t.grund == "stop" and t.ausstieg == pytest.approx(99.0)
    assert t.r == pytest.approx((99.0 - 102.0) / R0) and t.r < -1.0
    assert t.kerzen == 2


def test_luecke_ueber_das_ziel_fuellt_zum_eroeffnungskurs() -> None:
    t, = einzel([(102.0, 102.5, 101.0, 102.0), (108.0, 109.0, 107.5, 108.5)])
    assert t.grund == "target" and t.ausstieg == pytest.approx(108.0)
    assert t.r == pytest.approx((108.0 - 102.0) / R0) and t.r > 3.0


def test_einstieg_unter_dem_stop_ist_voller_verlust() -> None:
    # Die Einstiegskerze eröffnet schon unter dem Stop: 1 R ist nicht definiert, gebucht wird -1 R (plus Kosten)
    t, = einzel([(100.0, 100.5, 99.0, 99.5)])
    assert t.grund == "stop_vor_einstieg" and t.r == pytest.approx(-1.0)


def test_zeitstopp_nach_30_kerzen_zum_schluss() -> None:
    ruhig = [(102.0, 103.0, 101.0, 102.5)] * 29 + [(102.0, 103.0, 101.0, 103.0)]   # Einstiegskerze = Kerze 1, Ausstieg zum Schluss der 30.
    t, = einzel(ruhig)
    assert t.grund == "time" and t.kerzen == 30
    assert t.ausstieg == pytest.approx(103.0)
    assert t.r == pytest.approx((103.0 - 102.0) / R0)
    assert t.ausstieg_zeit == START + (241 + 30) * MS


def test_short_ist_das_spiegelbild() -> None:
    reihe = s7b.bereite_vor(aufbau([], spiegeln=True), V)
    assert reihe.sig[240] == -1 and reihe.stop_signal[240] == pytest.approx(98.0 + R0)
    # Die Folgekerzen werden mit gespiegelt: dieselben Zahlen wie im Long-Test ergeben das Short-Spiegelbild
    t, = einzel([(102.0, 107.0, 101.5, 106.5)], spiegeln=True)   # gespiegelt: Eröffnung 98, Tief 93; Ziel = 98 - 3 R0 = 93,114
    assert (t.seite, t.grund) == (-1, "target")
    assert t.einstieg == pytest.approx(98.0) and t.ausstieg == pytest.approx(98.0 - 3 * R0) and t.r == pytest.approx(3.0)
    t, = einzel([(102.0, 102.5, 100.0, 100.2)], spiegeln=True)   # gespiegelt: Hoch 100,0 über dem Stop 99,63
    assert (t.seite, t.grund) == (-1, "stop") and t.r == pytest.approx(-1.0)


def test_ziel_4r_variante() -> None:
    t, = lauf({"BTCUSDT": aufbau([(102.0, 110.0, 101.5, 109.0)])}, v=Variante(20, 4.0))
    assert t.grund == "target" and t.r == pytest.approx(4.0)


def test_kein_long_unter_dem_sma200() -> None:
    # 150 Kerzen bei 200, dann 90 bei 100, dann Ausbruch über den 20er-Kanal auf 102: SMA200 liegt bei etwa 154
    zeilen = [(200.0, 200.5, 199.5, 200.0)] * 150 + [(100.0, 100.5, 99.5, 100.0)] * 90 + [(100.0, 102.2, 100.0, 102.0)]
    o, h, l, c = (np.array(x) for x in zip(*zeilen))
    reihe = s7b.bereite_vor(kerzenreihe("BTCUSDT", o, h, l, c), V)
    assert reihe.vorlauf[240] and c[240] > reihe.h[220:240].max()   # Kanalausbruch und lückenloser Vorlauf
    assert reihe.sig[240] == 0 and not reihe.sig.any()               # trotzdem kein Signal: Schluss unter SMA200


def test_ohne_200_lueckenlose_kerzen_kein_signal() -> None:
    # Fehlt Kerze 100 im Raster, ist der Vorlauf erst 200 Kerzen später wieder lückenlos (ab Raster-Platz 300)
    k = kerzenreihe("BTCUSDT", np.full(400, 100.0), np.full(400, 100.5), np.full(400, 99.5), np.full(400, 100.0), luecken=(100,))
    reihe = s7b.bereite_vor(k, V)
    platz = ((k.t - START) // MS).astype(int)
    assert not reihe.vorlauf[platz < 300].any()
    assert reihe.vorlauf[platz >= 300].all()
    # Mit der Lücke im Vorlauf der Ausbruchskerze gibt es keinen Trade; ohne Lücke gibt es einen
    assert einzel([(102.0, 107.0, 101.5, 106.5)], luecken=(100,)) == []
    assert len(einzel([(102.0, 107.0, 101.5, 106.5)])) == 1


# ---------------------------------------------------------------------------------------------------------------------------------------
# Kosten und Funding
# ---------------------------------------------------------------------------------------------------------------------------------------

def test_gebuehren_sind_kosten_in_r() -> None:
    t, = lauf({"BTCUSDT": aufbau([(102.0, 107.0, 101.5, 106.5)])}, Kosten(gebuehr=0.0005, slip_einstieg=0.0, slip_ziel=0.0, slip_zeit=0.0, slip_stop=0.0, funding="aus"))
    erwartet = 0.0005 * (102.0 + ZIEL) / R0
    assert t.kosten_r == pytest.approx(erwartet)
    assert t.r == pytest.approx(3.0 - erwartet)


def test_schlupf_wirkt_gegen_den_trader() -> None:
    k = Kosten(gebuehr=0.0, slip_einstieg=0.0003, slip_ziel=0.0003, slip_zeit=0.0003, slip_stop=0.0005, funding="aus")
    lang, = lauf({"BTCUSDT": aufbau([(102.0, 108.0, 101.5, 107.0)])}, k)
    assert lang.einstieg == pytest.approx(102.0 * 1.0003) and lang.r < 3.0
    kurz, = lauf({"BTCUSDT": aufbau([(102.0, 108.0, 101.5, 107.0)], spiegeln=True)}, k)   # gespiegelt: Eröffnung 98
    assert kurz.einstieg == pytest.approx(98.0 * (1 - 0.0003)) and kurz.r < 3.0


def test_funding_vorzeichen_und_gutschrift() -> None:
    ft = np.array([START + 241 * MS + 1000])   # Abrechnung während der Haltedauer
    mit_hist = lambda rate, modus: lauf(  # noqa: E731
        {"BTCUSDT": aufbau([(102.0, 107.0, 101.5, 106.5)])}, Kosten(**{**OHNE_KOSTEN.__dict__, "funding": modus}),
        funding={"BTCUSDT": Funding("BTCUSDT", ft, np.array([rate]), 1, 0)})[0]
    zahlung = 0.001 * 102.0 / R0
    assert mit_hist(0.001, "hist").funding_r == pytest.approx(zahlung)                  # Long zahlt bei positiver Rate
    assert mit_hist(0.001, "hist").r == pytest.approx(3.0 - zahlung)
    assert mit_hist(-0.001, "hist").funding_r == pytest.approx(-zahlung)                # Long erhält bei negativer Rate
    assert mit_hist(-0.001, "hist_ohne_gutschrift").funding_r == 0.0                    # Gutschrift wird nicht angerechnet
    assert mit_hist(0.001, "hist_ohne_gutschrift").funding_r == pytest.approx(zahlung)  # Zahlungen schon
    assert mit_hist(0.001, "aus").funding_r == 0.0
    # Abrechnungen außerhalb der Haltedauer zählen nicht: [Einstieg, Ausstieg)
    ausserhalb = lauf({"BTCUSDT": aufbau([(102.0, 107.0, 101.5, 106.5)])}, Kosten(**{**OHNE_KOSTEN.__dict__, "funding": "hist"}),
                      funding={"BTCUSDT": Funding("BTCUSDT", np.array([START + 242 * MS]), np.array([0.01]), 1, 0)})[0]
    assert ausserhalb.funding_r == 0.0


# ---------------------------------------------------------------------------------------------------------------------------------------
# Positionsgrenze und Lücken
# ---------------------------------------------------------------------------------------------------------------------------------------

def test_hoechstens_eine_position_und_vorrang_btc() -> None:
    folge = [(102.0, 107.0, 101.5, 106.5)]
    k = {"BTCUSDT": aufbau(folge, symbol="BTCUSDT"), "ETHUSDT": aufbau(folge, symbol="ETHUSDT")}
    ein = lauf(k, portfolio=True)
    assert [t.symbol for t in ein] == ["BTCUSDT"]
    beide = lauf(k, portfolio=False)
    assert sorted(t.symbol for t in beide) == ["BTCUSDT", "ETHUSDT"]
    umgekehrt = lauf(k, portfolio=True, reihenfolge=("ETHUSDT", "BTCUSDT"))
    assert [t.symbol for t in umgekehrt] == ["ETHUSDT"]


def test_fehlende_kerze_waehrend_der_position_schliesst_zum_letzten_schluss() -> None:
    folge = [(102.0, 102.5, 101.0, 102.2), (102.2, 102.6, 101.5, 102.4), (102.4, 102.9, 101.6, 102.6)]
    # BTC fehlt in Kerze 243, ETH (flach, ohne Signal) ist vorhanden: der Zeitpunkt existiert, BTC hat aber keine Kerze
    btc = aufbau(folge, luecken=(243,), symbol="BTCUSDT")
    eth = kerzenreihe("ETHUSDT", np.full(244, 100.0), np.full(244, 100.5), np.full(244, 99.5), np.full(244, 100.0))
    t, = lauf({"BTCUSDT": btc, "ETHUSDT": eth})
    assert t.grund == "gap" and t.ausstieg == pytest.approx(102.4)   # Schluss der letzten vorhandenen Kerze (Nr. 242)
    assert t.ausstieg_zeit == START + 243 * MS   # Ende der letzten vorhandenen Kerze = Beginn der fehlenden


def test_abschnittsregel_signal_im_abschnitt_und_ausstieg_spaetestens_am_ende() -> None:
    def trade(signal: int, ausstieg: int) -> Trade:
        return Trade("BTCUSDT", 1, signal, signal + MS, ausstieg, 100.0, 101.0, 99.0, "target", 1, 1.0, 0.0, 0.0, 1.0, 1.0)

    train, valid = s7b.TRAIN_ENDE_MS, s7b.VALID_ENDE_MS
    assert s7b.abschnitt(trade(train - 10 * MS, train - 5 * MS)) == "train"
    assert s7b.abschnitt(trade(train - 10 * MS, train)) == "train"                    # Ausstieg genau am Abschnittsende zählt noch
    assert s7b.abschnitt(trade(train - 2 * MS, train + MS)) is None                   # überschreitet das Ende: weder Training noch Validierung
    assert s7b.abschnitt(trade(train + MS, train + 5 * MS)) == "validation"
    assert s7b.abschnitt(trade(valid - 2 * MS, valid + MS)) is None
    assert s7b.abschnitt(trade(valid + MS, valid + 5 * MS)) is None                   # Holdout wird nie zugeordnet


# ---------------------------------------------------------------------------------------------------------------------------------------
# Lader: Holdout-Schranke, Duplikate, Reihenfolge
# ---------------------------------------------------------------------------------------------------------------------------------------

def _zip(wurzel: Path, symbol: str, ym: str, zeilen: list[str], kopf: str | None = None, markt: str = "spot") -> None:
    pfad = wurzel / markt / "klines" / symbol / "4h" / f"{symbol}-4h-{ym}.zip"
    pfad.parent.mkdir(parents=True, exist_ok=True)
    text = ("\n".join(([kopf] if kopf else []) + zeilen)) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{symbol}-4h-{ym}.csv", text)
    pfad.write_bytes(buf.getvalue())


def _zeile(t: int, preis: float = 100.0) -> str:
    return f"{t},{preis},{preis + 1},{preis - 1},{preis},10.0,{t + MS - 1},1000.0,5,5.0,500.0,0"


def test_holdout_schranke_verweigert_zeitraeume_ab_2025(tmp_path: Path) -> None:
    daten._pruefe_holdout("2024-12")  # darf nicht werfen
    for bis in ("2025-01", "2026-06"):
        with pytest.raises(daten.HoldoutVerweigert):
            daten.laden(tmp_path, "spot", "BTCUSDT", "4h", "2024-01", bis)
    assert daten.HOLDOUT_START_MS == 1_735_689_600_000   # 2025-01-01T00:00:00Z


def test_holdout_schranke_greift_auch_bei_zeilen_in_der_dezember_datei(tmp_path: Path) -> None:
    dez = int(np.datetime64("2024-12-31T20:00").astype("datetime64[ms]").astype(np.int64))
    _zip(tmp_path, "BTCUSDT", "2024-12", [_zeile(dez), _zeile(dez + MS)])   # zweite Zeile liegt am 2025-01-01T00:00
    with pytest.raises(daten.HoldoutVerweigert):
        daten.laden(tmp_path, "spot", "BTCUSDT", "4h", "2024-12", "2024-12")


def test_lader_zaehlt_duplikate_und_unsortierte_zeilen_und_ueberspringt_kopfzeile(tmp_path: Path) -> None:
    a = START
    zeilen = [_zeile(a + 2 * MS, 102.0), _zeile(a, 100.0), _zeile(a + MS, 101.0), _zeile(a + MS, 999.0)]   # unsortiert, ein Duplikat
    _zip(tmp_path, "BTCUSDT", "2020-01", zeilen, kopf="open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore")
    k = daten.laden(tmp_path, "spot", "BTCUSDT", "4h", "2020-01", "2020-01")
    assert k is not None
    assert k.roh_zeilen == 4 and k.duplikate == 1 and k.unsortiert >= 1
    assert k.t.tolist() == [a, a + MS, a + 2 * MS]            # aufsteigend, ohne Duplikat
    assert k.c[1] == 101.0                                     # das Duplikat ersetzt die erste Zeile nicht
    assert daten.laden(tmp_path, "spot", "ETHUSDT", "4h", "2020-01", "2020-01") is None   # keine Dateien: None statt Fehler


def test_lader_verlangt_genau_eine_csv_je_archiv(tmp_path: Path) -> None:
    pfad = tmp_path / "spot" / "klines" / "BTCUSDT" / "4h" / "BTCUSDT-4h-2020-01.zip"
    pfad.parent.mkdir(parents=True)
    with zipfile.ZipFile(pfad, "w") as z:
        z.writestr("a.csv", _zeile(START) + "\n")
        z.writestr("b.csv", _zeile(START + MS) + "\n")
    with pytest.raises(ValueError):
        daten.laden(tmp_path, "spot", "BTCUSDT", "4h", "2020-01", "2020-01")
