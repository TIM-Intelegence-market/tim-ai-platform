"""Tests der Kennzahlenbasis der Konsolidierung (``src.research_lab.konsolidierung.kennzahlen``).

Erwartungswerte stammen aus Handrechnung oder unabhängiger Rechnung (scipy, Simulation), nicht aus dem getesteten Code.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.research_lab.konsolidierung import kennzahlen as kz

TAG = kz.TAGE_MS
T0 = 1_577_836_800_000  # 2020-01-01T00:00Z


def test_wilson_stimmt_mit_scipy_ueberein() -> None:
    # Referenzwerte aus scipy.stats.binomtest(k, n).proportion_ci(method="wilson"), 95 % (z = 1,959964)
    z95 = 1.959963984540054
    assert kz.wilson(38, 100, z=z95) == pytest.approx((0.2909760, 0.4779024), abs=1e-6)
    assert kz.wilson(54, 157, z=z95) == pytest.approx((0.2741699, 0.4211823), abs=1e-6)  # Trefferzahl von T15
    # mit dem im Code festen z = 1,96 weicht das Intervall nur in der fünften Stelle ab
    assert kz.wilson(54, 157) == pytest.approx((0.2741699, 0.4211823), abs=1e-4)


def test_wilson_randfaelle() -> None:
    lo, hi = kz.wilson(0, 10)
    assert lo == pytest.approx(0.0, abs=1e-12) and 0.2 < hi < 0.35
    lo, hi = kz.wilson(10, 10)
    assert hi == pytest.approx(1.0, abs=1e-12) and 0.65 < lo < 0.8
    assert all(math.isnan(x) for x in kz.wilson(0, 0))


def test_max_drawdown_von_hand() -> None:
    # kumuliert (Start 0): 0, 1, -1, -2, 1, -3  -> Spitze 1, Tal -3, Rückgang 4
    tiefe, spitze, tal = kz.max_drawdown(np.array([1.0, -2.0, -1.0, 3.0, -4.0]))
    assert tiefe == pytest.approx(4.0)
    assert (spitze, tal) == (1, 5)
    assert kz.max_drawdown(np.array([]))[0] == 0.0
    assert kz.max_drawdown(np.array([1.0, 1.0, 1.0]))[0] == 0.0  # nur Gewinne: kein Rückgang


def test_rueckgang_gilt_auch_vor_dem_ersten_gewinn() -> None:
    # Start bei 0 zählt als Spitze: wer mit Verlusten beginnt, hat schon einen Rückgang
    assert kz.max_drawdown(np.array([-1.0, -1.0, 3.0]))[0] == pytest.approx(2.0)


def test_drawdown_dauer_in_tagen() -> None:
    exit_ms = np.array([1, 2, 3, 4, 5], dtype=np.int64) * TAG
    r = np.array([1.0, -1.0, -1.0, 1.0, 2.0])  # kumuliert 1, 0, -1, 0, 2: Spitze an Tag 1, neue Spitze an Tag 5
    assert kz.drawdown_dauer_tage(exit_ms, r) == pytest.approx(4.0)
    assert kz.drawdown_dauer_tage(exit_ms[:0], r[:0]) is None
    # Rückgang bis zum Ende ohne neue Spitze zählt bis zum letzten Ausstieg
    assert kz.drawdown_dauer_tage(exit_ms[:3], np.array([1.0, -1.0, -1.0])) == pytest.approx(2.0)


def test_profit_faktor() -> None:
    assert kz.profit_faktor(np.array([2.0, -1.0, 1.0, -1.0])) == pytest.approx(1.5)
    assert kz.profit_faktor(np.array([1.0, 2.0])) is None  # kein Verlust: nicht definiert, nicht unendlich


def test_monatsschluessel_utc() -> None:
    ms = np.array([T0, T0 + 30 * TAG, T0 + 31 * TAG, T0 - 1], dtype=np.int64)  # 1.1., 31.1., 1.2., 31.12.2019 23:59:59,999
    assert kz.monat_schluessel(ms).tolist() == [202001, 202001, 202002, 201912]


def test_kpi_von_hand() -> None:
    r = np.array([3.0, -1.0, -1.0, 3.0, -1.0])
    signal = np.array([0, 5, 40, 45, 50], dtype=np.int64) * TAG + T0  # Januar, Januar, Februar, Februar, Februar
    ausstieg = signal + 2 * TAG
    stop = np.full(5, 0.04)
    k = kz.kpi(r, signal, ausstieg, stop_anteil=stop)
    assert k["n"] == 5
    assert k["e_r"] == pytest.approx(0.6)
    assert k["summe_r"] == pytest.approx(3.0)
    assert k["trefferquote"] == pytest.approx(0.4)
    assert k["profit_faktor"] == pytest.approx(2.0)          # 6 / 3
    assert k["mittel_gewinn_r"] == pytest.approx(3.0) and k["mittel_verlust_r"] == pytest.approx(-1.0)
    assert k["sd_r"] == pytest.approx(float(np.std(r, ddof=1)))
    assert k["max_drawdown_r"] == pytest.approx(2.0)          # kumuliert 3, 2, 1, 4, 3: von 3 auf 1
    assert k["monate_mit_trade"] == 2
    assert k["anteil_beste_5_prozent_an_summe"] == pytest.approx(1.0)  # bester Trade (3 R) / Summe (3 R)
    # Basispunkte: Mittel von (Netto-R x Stopp-Abstand) in Basispunkten des Nominals = 0,6 x 4 % = 240 bp
    assert k["netto_bp_je_trade_auf_nominal"] == pytest.approx(240.0)
    assert k["mittlerer_stop_abstand_prozent"] == pytest.approx(4.0)
    # Rendite mit ausdrücklicher Basis: 1 % Risiko je R, 10.000 USDT
    assert k["netto_rendite_nicht_aufgezinst_prozent"] == pytest.approx(3.0)
    assert k["netto_rendite_aufgezinst_prozent"] == pytest.approx((1.03 * 0.99 * 0.99 * 1.03 * 0.99 - 1) * 100)
    assert k["kapitalbasis_usdt"] == 10_000.0 and k["risiko_je_trade"] == 0.01
    assert set(k["je_jahr"]) == {"2020"}


def test_kpi_ohne_trades_und_fehlende_angaben_bleiben_none() -> None:
    assert kz.kpi(np.array([]), np.array([], dtype=np.int64), np.array([], dtype=np.int64)) == {"n": 0}
    r = np.array([1.0, 2.0])
    s = np.array([T0, T0 + TAG], dtype=np.int64)
    k = kz.kpi(r, s, s + TAG)
    assert k["mittel_verlust_r"] is None and k["profit_faktor"] is None  # keine Verluste: keine Ersatzwerte
    assert "netto_bp_je_trade_auf_nominal" not in k                   # ohne Stopp-Abstand keine Basispunkte
    assert "kosten_r_je_trade" not in k


def test_bootstrap_ist_bei_gleichem_seed_gleich_und_bei_anderem_nicht() -> None:
    rng = np.random.default_rng(7)
    r = rng.normal(0.2, 1.5, 300)
    s = T0 + np.sort(rng.integers(0, 24 * 30, 300)) * 30 * 3_600_000 // 30 * 30  # über etwa 24 Monate verteilt
    a = kz.monatsblock_bootstrap(r, s, ziehungen=2000, seed=11, exit_ms=s + TAG)
    b = kz.monatsblock_bootstrap(r, s, ziehungen=2000, seed=11, exit_ms=s + TAG)
    c = kz.monatsblock_bootstrap(r, s, ziehungen=2000, seed=12, exit_ms=s + TAG)
    assert a == b
    assert a["e_r"]["ci95"] != c["e_r"]["ci95"]
    lo, hi = a["e_r"]["ci95"]
    assert lo < r.mean() < hi


@pytest.mark.filterwarnings("ignore:All-NaN slice encountered")  # ohne Verlust ist der Profitfaktor nicht definiert
def test_bootstrap_band_liegt_ueber_null_bei_reinen_gewinnen_und_enthaelt_null_bei_symmetrie() -> None:
    s = T0 + np.arange(120, dtype=np.int64) * 15 * TAG  # 120 Trades über etwa 5 Jahre: jeder in einem anderen Monat
    gewinne = kz.monatsblock_bootstrap(np.full(120, 0.5), s, ziehungen=1000)
    assert gewinne["e_r"]["ci95"][0] > 0 and gewinne["e_r"]["anteil_positiv"] == 1.0
    rng = np.random.default_rng(3)
    zufall = rng.normal(0.0, 1.0, 120)
    zufall -= zufall.mean()  # Mittel exakt null
    sym = kz.monatsblock_bootstrap(zufall, s, ziehungen=2000)
    assert sym["e_r"]["ci95"][0] < 0 < sym["e_r"]["ci95"][1]
    assert 0.3 < sym["e_r"]["anteil_positiv"] < 0.7


def test_newey_west_entspricht_normalem_t_ohne_autokorrelation_und_ist_darueber_vorsichtiger() -> None:
    rng = np.random.default_rng(5)
    iid = rng.normal(0.1, 1.0, 4000)
    t_nw, se_nw = kz.newey_west_t(iid, lags=4)
    t_normal = iid.mean() / (iid.std(ddof=0) / math.sqrt(len(iid)))
    assert t_nw == pytest.approx(t_normal, rel=0.1)
    # AR(1) mit starker positiver Autokorrelation: der Standardfehler muss deutlich größer sein als ohne Korrektur
    e = rng.normal(0.0, 1.0, 4000)
    x = np.empty_like(e)
    x[0] = e[0]
    for i in range(1, len(e)):
        x[i] = 0.7 * x[i - 1] + e[i]
    _, se_ar = kz.newey_west_t(x, lags=4)
    assert se_ar > 1.5 * (x.std(ddof=0) / math.sqrt(len(x)))
    t_kurz, se_kurz = kz.newey_west_t(np.array([1.0, 2.0]), lags=4)
    assert math.isnan(t_kurz) and math.isnan(se_kurz)


def test_probabilistic_sharpe_von_hand() -> None:
    # Normalverteilt (Schiefe 0, Kurtosis 3), n = 100, Sharpe 0,2: Φ(0,2·√99 / √(1 + 0,5·0,04)) = 0,97560...
    assert kz.psr(0.2, 100, 0.0, 3.0) == pytest.approx(0.97560, abs=1e-4)
    assert kz.psr(0.0, 100, 0.0, 3.0) == pytest.approx(0.5)
    assert math.isnan(kz.psr(0.2, 1, 0.0, 3.0))


def test_erwartetes_maximum_der_sharpes_wie_bei_normalverteilten_zufallszahlen() -> None:
    # Erwartetes Maximum von N Standardnormalzahlen (Simulation): N = 100 -> 2,507; N = 1000 -> 3,243
    assert kz.erwartetes_max_sharpe(100, 1.0) == pytest.approx(2.507, abs=0.05)
    assert kz.erwartetes_max_sharpe(1000, 1.0) == pytest.approx(3.243, abs=0.05)
    assert kz.erwartetes_max_sharpe(1, 1.0) == 0.0
    assert kz.erwartetes_max_sharpe(64, 0.04) == pytest.approx(0.2 * kz.erwartetes_max_sharpe(64, 1.0))  # skaliert mit der Streuung


def test_deflated_sharpe_sinkt_mit_der_zahl_der_versuche() -> None:
    rng = np.random.default_rng(9)
    r = rng.normal(0.25, 1.7, 300)
    werte = [kz.deflated_sharpe(r, n)["dsr"] for n in (1, 10, 64, 1000, 26_707)]
    assert all(a > b for a, b in zip(werte, werte[1:]))
    assert werte[0] == pytest.approx(kz.deflated_sharpe(r, 1)["psr_null"])  # ein Versuch: keine Korrektur
    # Ein Versuch ohne Vorteil liegt bei 50 %
    mittelfrei = rng.normal(0.0, 1.0, 400)
    mittelfrei -= mittelfrei.mean()
    assert kz.deflated_sharpe(mittelfrei, 1)["dsr"] == pytest.approx(0.5, abs=0.01)


def test_deflated_sharpe_ohne_streuung_ist_nicht_auswertbar() -> None:
    erg = kz.deflated_sharpe(np.full(10, 1.0), 64)
    assert erg["dsr"] is None
