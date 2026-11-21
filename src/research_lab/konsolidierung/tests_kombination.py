"""Tests T10 (risikogleiche Referenzen), T11 (Carry) und T12 (gemeinsames Kapitalmodell) des Prüfprotokolls Konsolidierung 1.0."""
from __future__ import annotations

import numpy as np

from src.research_lab.konsolidierung import carry as cy
from src.research_lab.konsolidierung import kennzahlen as kz
from src.research_lab.konsolidierung import tagesreihe as tr
from src.research_lab.konsolidierung.s7b_nachrechnung import TRAIN_ENDE_MS, VALID_ENDE_MS
from src.research_lab.konsolidierung.tests_trend import K1, KANDIDATEN, V_C1, lauf, nach_abschnitt

T0_MS = 1_577_836_800_000          # 2020-01-01T00:00Z
GRENZEN = {"train": (T0_MS, TRAIN_ENDE_MS), "validation": (TRAIN_ENDE_MS, VALID_ENDE_MS), "pooled": (T0_MS, VALID_ENDE_MS)}
# ANNAHME (nicht aus TIM-Daten, gerundet aus dem Gedächtnis, Protokoll T11): Jahresmittel US-Schatzwechsel in Prozent
GELDMARKT_PROZENT = {2020: 0.4, 2021: 0.05, 2022: 2.0, 2023: 5.1, 2024: 5.0}
CARRY_SYMBOLE = ("BTCUSDT", "ETHUSDT")
CARRY_ANTEIL = 0.5


def geldmarkt_je_abschnitt() -> dict[str, float]:
    return {"train": float(np.mean([GELDMARKT_PROZENT[y] for y in (2020, 2021, 2022)])),
            "validation": float(np.mean([GELDMARKT_PROZENT[y] for y in (2023, 2024)])),
            "pooled": float(np.mean(list(GELDMARKT_PROZENT.values())))}


def _dd_aus_tagen(x: np.ndarray) -> float:
    kum = np.cumsum(x)
    spitze = np.maximum.accumulate(np.concatenate(([0.0], kum)))[1:]
    return float((spitze - kum).max())


def t11_carry(wurzel: str) -> dict:
    d = {s: cy.lade(wurzel, s) for s in CARRY_SYMBOLE}
    out: dict = {"annahmen": {"geldmarkt_prozent_je_jahr": GELDMARKT_PROZENT, "hinweis_geldmarkt": "ANNAHME aus dem Gedächtnis, nicht aus TIM-Daten",
                              "kapital": "Spot-Notional + Perp-Marge (Standard 100 %, wie S33 'beide Beine voll')",
                              "kosten": "4 Füllungen, je Füllung Gebühr + Schlupf 0,03 %; Perp 0,06 %, Spot 0,06 % (Standard) bzw. 0,10 % (Sensitivität); Bitunix-Spot-Gebühr unbestätigt"},
                 "lauf": {}}
    daily: dict[tuple, tuple] = {}
    for szen, (ck, marge, nj) in {"basis_marge100": (cy.CarryKosten(), 1.0, None), "spot_gebuehr_10bp": (cy.CarryKosten(gebuehr_spot=0.0010), 1.0, None),
                                  "marge50": (cy.CarryKosten(), 0.5, None), "marge20": (cy.CarryKosten(), 0.2, None),
                                  "monatlich_nachjustiert": (cy.CarryKosten(), 1.0, "monat")}.items():
        res_s: dict = {}
        for sec, (a, b) in GRENZEN.items():
            je_inst = {}
            reihen = []
            for s in CARRY_SYMBOLE:
                sp, pp, fd = d[s]
                r = cy.carry_lauf(sp, pp, fd, a, b, ck, marge, nj)
                ts, dif = r.pop("tagesreihe")
                reihen.append((ts, dif))
                je_inst[s] = r
            # gleichgewichtetes Paar BTC/ETH (je Instrument auf eigenes Kapital normiert)
            ts = reihen[0][0]
            dif = np.mean([x[1] for x in reihen], axis=0)
            daily[(szen, sec)] = (ts, dif)
            jahre = (b - a) / (365.0 * 86_400_000)
            gesamt = float(dif.sum())
            res_s[sec] = {"je_instrument": je_inst, "paar_netto_rendite_gesamt": gesamt, "paar_netto_rendite_je_jahr": gesamt / jahre,
                          "paar_max_rueckgang_tagesbasis": _dd_aus_tagen(dif), "paar_schwankung_jahr": float(dif.std(ddof=1) * np.sqrt(365)),
                          "geldmarkt_je_jahr_annahme": geldmarkt_je_abschnitt()[sec] / 100.0}
        out["lauf"][szen] = res_s
    gm = geldmarkt_je_abschnitt()
    basis = out["lauf"]["basis_marge100"]
    out["cg1_bestanden"] = bool(all(basis[sec]["paar_netto_rendite_je_jahr"] > gm[sec] / 100.0 for sec in ("train", "validation")))
    out["cg2_bestanden"] = bool(all(basis[sec]["paar_max_rueckgang_tagesbasis"] < 0.10 for sec in ("train", "validation")))
    out["cg1_vergleich"] = {sec: {"carry_je_jahr": basis[sec]["paar_netto_rendite_je_jahr"], "geldmarkt_je_jahr_annahme": gm[sec] / 100.0} for sec in ("train", "validation")}
    return out, daily


def t12_kombination(kerzen: dict, fund: dict, daily_carry: dict, carry_szenario: str = "basis_marge100") -> dict:
    """Trendanteil (C1, 1 % des Gesamtkapitals je R) plus Carry auf ``CARRY_ANTEIL`` des Kapitals; Tagesreihe in Prozent des Gesamtkapitals."""
    trades = nach_abschnitt(lauf(kerzen, fund, KANDIDATEN["C1"], V_C1, K1))["pooled"]
    ts_t, dr = tr.kandidat_tagesreihe_r(trades, kerzen, T0_MS, VALID_ENDE_MS)
    alle_tage = tr.tage(T0_MS, VALID_ENDE_MS)
    trend = np.zeros(len(alle_tage))
    trend[np.searchsorted(alle_tage, ts_t)] = dr * tr.RISIKO * 100.0
    ts_c, dc = daily_carry[(carry_szenario, "pooled")]
    carry = np.zeros(len(alle_tage))
    carry[np.searchsorted(alle_tage, ts_c)] = dc * 100.0          # Prozent des Carry-Kapitals
    out: dict = {"hinweis": "Trend: 1 % des Gesamtkapitals je R, nicht aufgezinst; Carry: Anteil des Gesamtkapitals; übriges Kapital = Bargeld ohne Zins (konservativ)",
                 "korrelation_tagesrenditen": float(np.corrcoef(trend, carry)[0, 1]), "allokationen": {}}
    for anteil in (0.0, 0.25, 0.5, 0.75):
        komb = trend + anteil * carry
        res = {}
        for sec, (a, b) in GRENZEN.items():
            m = (alle_tage * 86_400_000 >= a) & (alle_tage * 86_400_000 < b)
            mon = kz.monat_schluessel(alle_tage[m] * 86_400_000)
            mr = np.array([komb[m][mon == k].sum() for k in np.unique(mon)])
            res[sec] = {"summe_prozent": float(komb[m].sum()), "monatssharpe_jahr": float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if mr.std(ddof=1) > 0 else None,
                        "max_rueckgang_prozent": _dd_aus_tagen(komb[m]), "monate": int(len(mr))}
        out["allokationen"][f"{int(anteil * 100)}"] = res
    ref, k50 = out["allokationen"]["0"], out["allokationen"]["50"]
    out["g10_bestanden"] = bool(all(k50[sec]["monatssharpe_jahr"] > ref[sec]["monatssharpe_jahr"] and k50[sec]["max_rueckgang_prozent"] < ref[sec]["max_rueckgang_prozent"]
                                    for sec in ("train", "validation")))
    return out, (alle_tage, trend, carry)


def t10_referenzen(kerzen: dict, fund: dict, trend_tage: np.ndarray, trend_pct: np.ndarray) -> dict:
    sigma = float(trend_pct[30:].std(ddof=1)) / 100.0
    refs = tr.referenzen(kerzen, fund, sigma, T0_MS, VALID_ENDE_MS)
    out = {"kandidat": tr.kennzahlen_tagesreihe(trend_tage, trend_pct, GRENZEN), "sigma_kandidat_tag_prozent": sigma * 100.0, "referenzen": {}}
    reihen = {"C1 Trend (1 % je R)": (trend_tage, trend_pct)}
    for name, (ts, x, k) in refs.items():
        out["referenzen"][name] = {"hebel": k, "kennzahlen": tr.kennzahlen_tagesreihe(ts, x, GRENZEN)}
        reihen[name] = (ts, x)
    out["bargeld_je_jahr_prozent_annahme"] = GELDMARKT_PROZENT
    return out, reihen
