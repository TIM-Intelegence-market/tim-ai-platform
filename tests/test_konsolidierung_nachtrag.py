"""Tests des Nachtrags der Gegenprüfung (``nachtrag_gegenpruefung``): Hilfsfunktionen auf kleinen Beispielen von Hand gerechnet, dazu Abgleich der
festgehaltenen Ergebnisdatei mit den Ergebnissen des Laufs T1 bis T13 (gleiche Zahlen, wo derselbe Rechenweg gilt)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from src.research_lab.konsolidierung import kennzahlen as kz
from src.research_lab.konsolidierung import nachtrag_gegenpruefung as N
from src.research_lab.konsolidierung import s7b_nachrechnung as S

ERG = Path(__file__).resolve().parents[1] / "docs" / "research_lab" / "konsolidierung" / "ergebnisse"
TAG = 86_400_000


def _ms(j: int, m: int, t: int = 1) -> int:
    return int(datetime(j, m, t, 12, tzinfo=timezone.utc).timestamp() * 1000)


def test_monate_von_bis_ueber_den_jahreswechsel() -> None:
    assert N.monate_von_bis(202011, 202102) == [202011, 202012, 202101, 202102]
    assert len(N.monate_von_bis(202001, 202212)) == 36 and len(N.monate_von_bis(202001, 202412)) == 60
    assert N.monate_von_bis(202301, 202301) == [202301] and N.monate_von_bis(202302, 202301) == []


def test_bootstrap_ueber_alle_monate_gleicht_dem_lauf_wenn_jeder_monat_trades_hat() -> None:
    rng = np.random.default_rng(4)
    signal = np.array([_ms(2021, m, t) for m in range(1, 7) for t in (3, 20)], dtype=np.int64)
    r = rng.normal(0.2, 1.5, len(signal))
    lab = kz.monatsblock_bootstrap(r, signal, ziehungen=500, seed=5, exit_ms=signal + TAG)
    neu = N.bootstrap_alle_monate(r, signal, N.monate_von_bis(202101, 202106), ziehungen=500, seed=5, exit_ms=signal + TAG)
    assert neu["e_r"]["ci95"] == pytest.approx(lab["e_r"]["ci95"])
    assert neu["max_drawdown_r"]["p95"] == pytest.approx(lab["max_drawdown_r"]["p95"])
    assert neu["monate"] == lab["monate"] == neu["monate_mit_trade"] == 6


def test_bootstrap_ueber_alle_monate_zieht_auch_leere_monate() -> None:
    signal = np.array([_ms(2021, 1), _ms(2021, 1, 15), _ms(2021, 3)], dtype=np.int64)    # Februar ohne Trade
    r = np.array([1.0, -0.5, 2.0])
    neu = N.bootstrap_alle_monate(r, signal, N.monate_von_bis(202101, 202103), ziehungen=300, seed=1, exit_ms=signal + TAG)
    lab = kz.monatsblock_bootstrap(r, signal, ziehungen=300, seed=1, exit_ms=signal + TAG)
    assert (neu["monate"], neu["monate_mit_trade"]) == (3, 2) and lab["monate"] == 2
    assert neu["summe_r"]["ci95"] != lab["summe_r"]["ci95"]  # leere Monate bekommen ein Los: die Summe streut anders
    assert neu["summe_r"]["ci95"][0] <= lab["summe_r"]["ci95"][0]   # und kann häufiger bei null liegen


def test_strenger_funding_zeitpunkt_am_einstieg_von_hand() -> None:
    streng = N._streng_modul()
    ft = np.array([1_000, 1_003, 1_020], dtype=np.int64)
    fr = np.array([0.1, 0.2, 0.4])
    assert S._funding_summe(ft, fr, 1_000, 2_000)[0] == pytest.approx(0.7)       # Laborkonvention: Abrechnungen ab dem Einstiegszeitpunkt zählen
    assert streng._funding_summe(ft, fr, 1_000, 2_000)[0] == pytest.approx(0.4)  # streng: nur Abrechnungen, die mehr als 10 ms nach dem Einstieg liegen
    assert streng._funding_summe(ft, fr, 1_000, 1_020)[0] == pytest.approx(0.0)  # Ausstieg exakt zur Abrechnung: nicht belastet (wie im Lauf)


def test_t15_nominal_rueckrechnung_von_hand() -> None:
    def zeit(j: int) -> int:
        return _ms(j, 6)
    # Stopp-Abstand 4 % ↔ Kosten 0,0012 / 0,04 = 0,03 R; Stopp-Abstand 2 % ↔ 0,06 R
    trades = [{"r": -1.0, "kosten_r": 0.03, "einstieg_ms": zeit(2017)}, {"r": -1.0, "kosten_r": 0.03, "einstieg_ms": zeit(2017)},
              {"r": 3.0, "kosten_r": 0.06, "einstieg_ms": zeit(2019)}, {"r": 3.0, "kosten_r": 0.06, "einstieg_ms": zeit(2019)}]
    t15 = {"trades_k2": trades, "primaer_k2": {"kennzahlen": {"mittlerer_stop_abstand_prozent": 3.0, "netto_bp_je_trade_auf_nominal": 20.0}}}
    o = N.n4_t15_nominal(t15)
    assert o["n"] == 4 and o["e_r"] == pytest.approx(1.0)
    assert o["mittlerer_stop_abstand_prozent_rueckgerechnet"] == pytest.approx(3.0)
    # Mittel von R × Stopp: (−1 × 0,04 × 2 + 3 × 0,02 × 2) / 4 = 0,01 = 100 bp; Produkt der Mittel: 1 × 0,03 = 300 bp
    assert o["netto_bp_rueckgerechnet"] == pytest.approx(100.0) and o["produkt_der_mittel_bp"] == pytest.approx(300.0)
    assert o["korrelation_r_stop"] == pytest.approx(-1.0)     # weite Stopps verlieren, enge gewinnen
    assert o["je_jahr"]["2017"]["n"] == 2 and o["je_jahr"]["2017"]["netto_bp"] == pytest.approx(-400.0)
    assert o["je_jahr"]["2019"]["netto_bp"] == pytest.approx(600.0)
    assert o["stop_unter_4_prozent"]["n"] == 2 and o["stop_ab_4_prozent"]["n"] == 2   # 4 % zählt zur oberen Gruppe


@pytest.fixture(scope="module")
def nachtrag() -> dict:
    return json.loads((ERG / "nachtrag_gegenpruefung.json").read_text(encoding="utf-8"))


def test_festgehaltener_nachtrag_gleicht_dem_lauf_wo_derselbe_rechenweg_gilt(nachtrag) -> None:
    e = nachtrag["ergebnis"]
    t7 = json.loads((ERG / "t07_unsicherheit_C1.json").read_text(encoding="utf-8"))["ergebnis"]
    lab = e["N1"]["C1_pooled"]["nur_monate_mit_trade_lauf"]
    assert lab["e_r"]["ci95"] == pytest.approx(t7["pooled"]["monatsblock_bootstrap"]["e_r"]["ci95"], abs=1e-6)
    assert lab["max_drawdown_r"]["p95"] == pytest.approx(t7["pooled"]["monatsblock_bootstrap"]["max_drawdown_r"]["p95"], abs=1e-5)
    t2 = json.loads((ERG / "t02_kosten.json").read_text(encoding="utf-8"))["ergebnis"]
    for kand in ("C1", "C3"):
        for kname in ("K1", "K2"):
            for sec in ("train", "validation", "pooled"):
                assert e["N2"][f"{kand}_{kname}_{sec}"]["lauf"]["e_r"] == pytest.approx(t2[kand]["szenarien"][kname][sec]["e_r"], abs=1e-6), (kand, kname, sec)
                assert e["N2"][f"{kand}_{kname}_{sec}"]["lauf"]["n"] == t2[kand]["szenarien"][kname][sec]["n"]
    t15 = json.loads((ERG / "t15_ausserhalb.json").read_text(encoding="utf-8"))["ergebnis"]
    assert e["N4"]["netto_bp_gespeichert"] == pytest.approx(t15["primaer_k2"]["kennzahlen"]["netto_bp_je_trade_auf_nominal"])


def test_festgehaltener_nachtrag_ist_vollstaendig_und_ohne_holdout(nachtrag) -> None:
    assert nachtrag["meta"]["code_unsauber"] is False and "Holdout nicht geladen" in nachtrag["meta"]["zeitraum"]
    e = nachtrag["ergebnis"]
    assert set(e) == {"N1", "N2", "N3", "N4"}
    for kand in ("C1", "C3"):
        for kname in ("K1", "K2"):
            teile = e["N3"][f"{kand}_{kname}"]
            assert set(teile) == {"training_2020_2023", "validierung_2024"} and teile["validierung_2024"]["n"] > 50
    # Streng gegen Lauf: die Abweichung durch das Funding am Einstieg ist klein und hat ein festes Vorzeichen (die Laborkonvention ist die vorsichtigere)
    for k, v in e["N2"].items():
        if isinstance(v, dict) and "lauf" in v and k.endswith(("_K2_pooled", "_K2_train", "_K2_validation")):
            assert 0.0 <= v["streng"]["e_r"] - v["lauf"]["e_r"] < 0.01, k
