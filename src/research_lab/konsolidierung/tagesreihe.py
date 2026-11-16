"""Tagesrenditen des Trendkandidaten (Mark-to-Market) und risikogleiche einfache Referenzen (T10), Grundlage für T12.

Alle Reihen sind in Prozent des Gesamtkapitals, nicht aufgezinst (Summe der Tagesrenditen). Der Trendkandidat riskiert
``RISIKO`` des Gesamtkapitals je R (Protokoll: 1 %). Referenzen werden auf dieselbe Tagesschwankung skaliert (Hebel höchstens 3).
"""
from __future__ import annotations

import numpy as np

from src.research_lab.konsolidierung import kennzahlen as kz
from src.research_lab.konsolidierung.daten import MS_4H, SYMBOLE, Funding, Kerzen
from src.research_lab.konsolidierung.s7b_nachrechnung import TRAIN_ENDE_MS, VALID_ENDE_MS, Trade, bereite_vor, Variante

TAG_MS = 86_400_000
RISIKO = 0.01
HEBEL_MAX = 3.0


def tage(t0_ms: int, t1_ms: int) -> np.ndarray:
    """Tagesindizes (UTC) von t0 bis t1 (ausschließlich)."""
    return np.arange(t0_ms // TAG_MS, (t1_ms - 1) // TAG_MS + 1, dtype=np.int64)


def kandidat_tagesreihe_r(trades: list[Trade], kerzen: dict[str, Kerzen], t0_ms: int, t1_ms: int) -> tuple[np.ndarray, np.ndarray]:
    """Tagesveränderung des Kontostands in R (offene Position zum Schlusskurs bewertet, Kosten und Funding erst beim Ausstieg).
    Gibt (Tagesindizes, R je Tag) zurück."""
    master = kerzen["BTCUSDT"]
    t_open = master.t[(master.t >= t0_ms) & (master.t < t1_ms)]
    n = len(t_open)
    pos0 = int(t_open[0])
    realisiert = np.zeros(n)
    offen = np.zeros(n)
    for tr in trades:
        k = kerzen[tr.symbol]
        idx = {int(x): i for i, x in enumerate(k.t)}
        risiko = abs(tr.einstieg - tr.stop)
        if risiko <= 0:
            continue
        letzter_schluss = tr.einstieg
        b = tr.einstieg_zeit
        while b < tr.ausstieg_zeit - MS_4H + 1:
            j = (b - pos0) // MS_4H
            if b + MS_4H >= tr.ausstieg_zeit:
                break
            i = idx.get(int(b))
            if i is not None:
                letzter_schluss = float(k.c[i])
            if 0 <= j < n:
                offen[j] += tr.seite * (letzter_schluss - tr.einstieg) / risiko
            b += MS_4H
        j_aus = (tr.ausstieg_zeit - MS_4H - pos0) // MS_4H
        if 0 <= j_aus < n:
            realisiert[j_aus] += tr.r
    kontostand = np.cumsum(realisiert) + offen
    close_ms = t_open + MS_4H
    tag_idx = (close_ms - 1) // TAG_MS
    ts = np.unique(tag_idx)
    ende = np.array([kontostand[tag_idx == d][-1] for d in ts])
    diff = np.diff(np.concatenate(([0.0], ende)))
    return ts, diff


def tages_schlusskurse(k: Kerzen, t0_ms: int, t1_ms: int) -> tuple[np.ndarray, np.ndarray]:
    """Schlusskurs der letzten 4h-Kerze je UTC-Tag (vorwärts aufgefüllt, wenn der Tag fehlt)."""
    m = (k.t >= t0_ms) & (k.t < t1_ms)
    tt, cc = k.t[m], k.c[m]
    tag = tt // TAG_MS
    ts = np.arange(tag[0], tag[-1] + 1)
    out = np.full(len(ts), np.nan)
    for d, c in zip(tag, cc):
        out[d - ts[0]] = c
    for i in range(1, len(out)):
        if np.isnan(out[i]):
            out[i] = out[i - 1]
    return ts, out


def kennzahlen_tagesreihe(tag: np.ndarray, rendite: np.ndarray, grenzen: dict[str, tuple[int, int]]) -> dict:
    """Je Abschnitt: Summe der Tagesrenditen (%), Jahresschwankung, Sharpe (Tage), größter Rückgang (% des Kapitals), schlechtester Tag."""
    out = {}
    for name, (a, b) in grenzen.items():
        m = (tag * TAG_MS >= a) & (tag * TAG_MS < b)
        x = rendite[m]
        if len(x) < 5:
            out[name] = None
            continue
        kum = np.cumsum(x)
        spitze = np.maximum.accumulate(np.concatenate(([0.0], kum)))[1:]
        dd = float((spitze - kum).max())
        sd = float(x.std(ddof=1))
        out[name] = {"tage": int(len(x)), "summe_prozent": float(x.sum()), "je_jahr_prozent": float(x.sum() / (len(x) / 365.0)), "schwankung_jahr_prozent": sd * np.sqrt(365),
                     "sharpe_jahr": float(x.mean() / sd * np.sqrt(365)) if sd > 0 else None, "max_rueckgang_prozent": max(dd, float(np.maximum(0, -kum.min()))),
                     "schlechtester_tag_prozent": float(x.min())}
    return out


def monatsrenditen(tag: np.ndarray, rendite: np.ndarray, a: int, b: int) -> np.ndarray:
    m = (tag * TAG_MS >= a) & (tag * TAG_MS < b)
    mon = kz.monat_schluessel(tag[m] * TAG_MS)
    return np.array([rendite[m][mon == k].sum() for k in np.unique(mon)])


def referenzen(kerzen: dict[str, Kerzen], fund: dict[str, Funding | None], sigma_kandidat_tag: float, t0_ms: int, t1_ms: int,
               kosten_seite: float = 0.0009) -> dict[str, tuple[np.ndarray, np.ndarray, float]]:
    """R1 (gleichgewichteter Korb, Kaufen und Halten, täglich neu gleichgewichtet) und R2 (derselbe Korb, long/flat nach SMA200 der 4h-Schlüsse),
    beide auf die Tagesschwankung des Kandidaten skaliert. Perp-Funding wird für die Long-Position bezahlt (mit Gutschrift bei negativer Rate).
    Kosten je Seite 0,06 % Gebühr + 0,03 % Schlupf = 0,09 % des gehandelten Betrags (R1 ohne Neugewichtungskosten: optimistisch für die Referenz)."""
    ts_alle = tage(t0_ms, t1_ms)
    n = len(ts_alle)
    ret = np.full((len(SYMBOLE), n), np.nan)
    ind = np.zeros((len(SYMBOLE), n))
    fund_tag = np.zeros((len(SYMBOLE), n))
    for si, s in enumerate(SYMBOLE):
        k = kerzen[s]
        ts, c = tages_schlusskurse(k, t0_ms - TAG_MS, t1_ms)
        # Tagesrendite von Schluss(d-1) nach Schluss(d)
        r_d = np.concatenate(([np.nan], c[1:] / c[:-1] - 1.0))
        pos = {int(d): i for i, d in enumerate(ts)}
        reihe = bereite_vor(k, Variante(20, 3.0))
        ts_sig, sma_tag = tages_schlusskurse(Kerzen(k.symbol, k.intervall, k.t, k.o, k.h, k.l, reihe.sma_seite.astype(float), k.v, k.taker_buy, 0, 0, 0), t0_ms - TAG_MS, t1_ms)
        for j, d in enumerate(ts_alle):
            i = pos.get(int(d))
            if i is not None and not np.isnan(r_d[i]) and i > 0 and ts[i] >= (k.t[0] // TAG_MS) + 1:
                ret[si, j] = r_d[i]
                ind[si, j] = 1.0 if sma_tag[i - 1] > 0 else 0.0   # Signal vom Vortag-Schluss, Position am Tag d
        f = fund.get(s)
        if f is not None:
            fd = f.t // TAG_MS
            for d, rate in zip(fd, f.rate):
                if t0_ms // TAG_MS <= d < t1_ms // TAG_MS:
                    fund_tag[si, int(d - ts_alle[0])] += rate
    verfuegbar = ~np.isnan(ret)
    anzahl = verfuegbar.sum(axis=0)
    gew1 = np.where(verfuegbar, 1.0 / np.maximum(anzahl, 1), 0.0)
    r_ret = np.where(verfuegbar, ret, 0.0)
    gew2 = gew1 * ind
    r1 = (gew1 * r_ret).sum(axis=0)
    r2 = (gew2 * r_ret).sum(axis=0)
    f1 = (gew1 * fund_tag).sum(axis=0)
    f2 = (gew2 * fund_tag).sum(axis=0)
    wechsel2 = np.abs(np.diff(np.concatenate((np.zeros((len(SYMBOLE), 1)), gew2), axis=1), axis=1)).sum(axis=0)
    wechsel1 = np.zeros(n)
    wechsel1[0] = gew1[:, 0].sum()
    brutto = {"R1": r1 - f1, "R2": r2 - f2 - wechsel2 * kosten_seite}
    brutto["R1"][0] -= wechsel1[0] * kosten_seite
    out = {}
    for name, x in brutto.items():
        sd = float(x[1:].std(ddof=1))
        k = min(HEBEL_MAX, sigma_kandidat_tag / sd) if sd > 0 else 0.0
        out[name] = (ts_alle, x * k * 100.0, k)   # in Prozent des Kapitals
    return out
