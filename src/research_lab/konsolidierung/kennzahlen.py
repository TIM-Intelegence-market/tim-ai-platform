"""Einheitliche Kennzahlenbasis für Trade-Listen (R-Vielfache, netto) und Zeitreihen.

Alle Studien werden auf dieselbe Weise gemessen. Eine Kennzahl, die für eine Studie nicht berechenbar ist
(zum Beispiel Basispunkte ohne Stopp-Abstand), wird als ``None`` ausgewiesen und nie ersetzt oder gemittelt.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import NormalDist

import numpy as np

TAGE_MS = 86_400_000


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def max_drawdown(r_geordnet: np.ndarray) -> tuple[float, int, int]:
    """Größter Rückgang der kumulierten R-Summe (Start bei 0). Gibt (Tiefe, Index Spitze, Index Tal) zurück."""
    if len(r_geordnet) == 0:
        return 0.0, 0, 0
    kum = np.concatenate(([0.0], np.cumsum(r_geordnet)))
    spitze = np.maximum.accumulate(kum)
    dd = spitze - kum
    tal = int(np.argmax(dd))
    sp = int(np.argmax(kum[: tal + 1]))
    return float(dd[tal]), sp, tal


def drawdown_dauer_tage(exit_ms: np.ndarray, r_geordnet: np.ndarray) -> float | None:
    """Dauer des längsten Rückgangs (Tage von Spitze bis zur nächsten neuen Spitze oder bis zum Ende)."""
    if len(r_geordnet) == 0:
        return None
    kum = np.cumsum(r_geordnet)
    spitze = -1e18
    t_spitze = exit_ms[0]
    laengste = 0.0
    kum_start = 0.0
    spitze = kum_start
    for k, t in zip(kum, exit_ms):
        if k > spitze:
            laengste = max(laengste, (t - t_spitze) / TAGE_MS)
            spitze = k
            t_spitze = t
    laengste = max(laengste, (exit_ms[-1] - t_spitze) / TAGE_MS)
    return float(laengste)


def profit_faktor(r: np.ndarray) -> float | None:
    g = r[r > 0].sum()
    v = -r[r < 0].sum()
    if v == 0:
        return None
    return float(g / v)


def monat_schluessel(ms: np.ndarray) -> np.ndarray:
    """Kalendermonat (UTC) als ganze Zahl JJJJMM."""
    out = np.empty(len(ms), dtype=np.int64)
    for i, t in enumerate(ms):
        d = datetime.fromtimestamp(int(t) / 1000, tz=timezone.utc)
        out[i] = d.year * 100 + d.month
    return out


def woche_schluessel(ms: np.ndarray) -> np.ndarray:
    return (ms // (7 * TAGE_MS)).astype(np.int64)


def kpi(r: np.ndarray, signal_ms: np.ndarray, exit_ms: np.ndarray, stop_anteil: np.ndarray | None = None, kosten_r: np.ndarray | None = None,
        funding_r: np.ndarray | None = None, brutto_r: np.ndarray | None = None, seite: np.ndarray | None = None,
        symbol: np.ndarray | None = None, grund: np.ndarray | None = None, haltedauer_h: np.ndarray | None = None,
        risiko: float = 0.01, kapital: float = 10_000.0) -> dict:
    """Standard-Kennzahlen. ``stop_anteil`` = |Einstieg - Stop| / Einstieg (für Basispunkte)."""
    n = int(len(r))
    if n == 0:
        return {"n": 0}
    order = np.argsort(exit_ms, kind="stable")
    r_o, e_o = r[order], exit_ms[order]
    gewinne = r > 0
    k_win = int(gewinne.sum())
    lo, hi = wilson(k_win, n)
    dd, i_sp, i_tal = max_drawdown(r_o)
    dauer = drawdown_dauer_tage(e_o, r_o)
    monate = monat_schluessel(signal_ms)
    wochen = woche_schluessel(signal_ms)
    spanne_tage = (exit_ms.max() - signal_ms.min()) / TAGE_MS
    summe = float(r.sum())
    out = {
        "n": n,
        "signal_wochen": int(len(np.unique(wochen))),
        "monate_mit_trade": int(len(np.unique(monate))),
        "e_r": float(r.mean()),
        "median_r": float(np.median(r)),
        "sd_r": float(r.std(ddof=1)) if n > 1 else None,
        "summe_r": summe,
        "trefferquote": k_win / n,
        "trefferquote_ci95_wilson": [lo, hi],
        "mittel_gewinn_r": float(r[gewinne].mean()) if k_win else None,
        "mittel_verlust_r": float(r[~gewinne].mean()) if k_win < n else None,
        "profit_faktor": profit_faktor(r),
        "max_drawdown_r": dd,
        "max_drawdown_dauer_tage": dauer,
        "bester_trade_r": float(r.max()),
        "schlechtester_trade_r": float(r.min()),
        "trades_pro_monat": float(n / max(spanne_tage / 30.4375, 1e-9)),
        "anteil_beste_5_prozent_an_summe": None,
    }
    k5 = max(1, int(round(0.05 * n)))
    top = np.sort(r)[::-1][:k5].sum()
    out["anteil_beste_5_prozent_an_summe"] = float(top / summe) if summe > 0 else None
    # Rendite mit expliziter Kapital- und Risikobasis (nicht aufgezinst): je R = risiko x kapital
    out["netto_rendite_nicht_aufgezinst_prozent"] = summe * risiko * 100.0
    out["kapitalbasis_usdt"] = kapital
    out["risiko_je_trade"] = risiko
    # Aufgezinst (Reihenfolge nach Ausstieg)
    eq = kapital
    for x in r_o:
        eq *= max(1.0 + risiko * x, 0.0)
    out["netto_rendite_aufgezinst_prozent"] = (eq / kapital - 1.0) * 100.0
    if haltedauer_h is not None:
        out["mittlere_haltedauer_h"] = float(np.mean(haltedauer_h))
        # Marktbeteiligung: Summe der Haltezeiten / Gesamtspanne (bei Positionsgrenze 1 höchstens 1)
        out["zeit_im_markt_anteil"] = float(np.sum(haltedauer_h) / 24.0 / max(spanne_tage, 1e-9))
    if kosten_r is not None:
        out["kosten_r_je_trade"] = float(np.mean(kosten_r))
    if funding_r is not None:
        out["funding_r_je_trade"] = float(np.mean(funding_r))
    if brutto_r is not None:
        out["brutto_r_je_trade"] = float(np.mean(brutto_r))
    if stop_anteil is not None:
        bp_netto = r * stop_anteil * 1e4
        out["netto_bp_je_trade_auf_nominal"] = float(np.mean(bp_netto))
        out["mittlerer_stop_abstand_prozent"] = float(np.mean(stop_anteil) * 100)
        if kosten_r is not None:
            out["kosten_bp_je_trade_auf_nominal"] = float(np.mean(kosten_r * stop_anteil * 1e4))
    for name, arr in (("je_symbol", symbol), ("je_seite", seite), ("je_grund", grund)):
        if arr is None:
            continue
        d = {}
        for key in np.unique(arr):
            m = arr == key
            d[str(key)] = {"n": int(m.sum()), "e_r": float(r[m].mean()), "summe_r": float(r[m].sum())}
        out[name] = d
    jahre = (monate // 100)
    out["je_jahr"] = {str(int(y)): {"n": int((jahre == y).sum()), "e_r": float(r[jahre == y].mean()), "summe_r": float(r[jahre == y].sum())} for y in np.unique(jahre)}
    return out


def monatsblock_bootstrap(r: np.ndarray, signal_ms: np.ndarray, ziehungen: int = 10_000, seed: int = 20261116, exit_ms: np.ndarray | None = None) -> dict:
    """Ziehung ganzer Kalendermonate mit Zurücklegen. Gibt Intervalle für E[R], Summe, PF und größten Rückgang zurück."""
    monate = monat_schluessel(signal_ms)
    einzig = np.unique(monate)
    m = len(einzig)
    if m == 0:
        return {}
    sum_m = np.array([r[monate == k].sum() for k in einzig])
    n_m = np.array([(monate == k).sum() for k in einzig])
    gew_m = np.array([r[(monate == k) & (r > 0)].sum() for k in einzig])
    ver_m = np.array([-r[(monate == k) & (r < 0)].sum() for k in einzig])
    # Trades je Monat für den Rückgang (chronologisch innerhalb des Monats)
    if exit_ms is None:
        exit_ms = signal_ms
    seq_m = [r[monate == k][np.argsort(exit_ms[monate == k], kind="stable")] for k in einzig]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, m, size=(ziehungen, m))
    n_s = n_m[idx].sum(axis=1)
    e_r = np.where(n_s > 0, sum_m[idx].sum(axis=1) / np.maximum(n_s, 1), np.nan)
    gew = gew_m[idx].sum(axis=1)
    ver = ver_m[idx].sum(axis=1)
    pf = np.where(ver > 0, gew / np.where(ver > 0, ver, 1), np.nan)
    dds = np.empty(min(ziehungen, 2000))
    for z in range(len(dds)):
        folge = np.concatenate([seq_m[i] for i in idx[z]])
        dds[z] = max_drawdown(folge)[0]
    q = lambda a, p: float(np.nanpercentile(a, p))
    return {
        "ziehungen": ziehungen, "seed": seed, "monate": int(m),
        "e_r": {"ci95": [q(e_r, 2.5), q(e_r, 97.5)], "ci90": [q(e_r, 5), q(e_r, 95)], "anteil_positiv": float(np.nanmean(e_r > 0))},
        "summe_r": {"ci95": [q(sum_m[idx].sum(axis=1), 2.5), q(sum_m[idx].sum(axis=1), 97.5)]},
        "profit_faktor": {"ci95": [q(pf, 2.5), q(pf, 97.5)]},
        "max_drawdown_r": {"median": q(dds, 50), "p95": q(dds, 95), "ziehungen": int(len(dds))},
    }


def newey_west_t(x: np.ndarray, lags: int = 4) -> tuple[float, float]:
    """t-Wert des Mittelwerts einer Reihe mit Newey-West-Varianz (Bartlett-Gewichte)."""
    n = len(x)
    if n < lags + 2:
        return float("nan"), float("nan")
    mu = x.mean()
    u = x - mu
    s = float(u @ u) / n
    for l in range(1, lags + 1):
        g = float(u[l:] @ u[:-l]) / n
        s += 2 * (1 - l / (lags + 1)) * g
    se = math.sqrt(max(s, 1e-18) / n)
    return float(mu / se), float(se)


# --- Mehrfachtest: Probabilistic und Deflated Sharpe (Bailey und López de Prado 2012, 2014), eigene Rechnung ---------------------------

EULER_GAMMA = 0.5772156649015329
_NORMAL = NormalDist()


def momente(r: np.ndarray) -> dict:
    """Sharpe je Beobachtung (Mittel / Populations-Standardabweichung), Schiefe, Kurtosis (roh, normal = 3)."""
    n = int(len(r))
    mu = float(np.mean(r))
    sd = float(np.std(r))  # Population wie in den Arbeiten
    if n < 3 or sd <= 0:
        return {"n": n, "mittel": mu, "sd": sd, "sharpe": float("nan"), "schiefe": float("nan"), "kurtosis": float("nan")}
    z = (r - mu) / sd
    return {"n": n, "mittel": mu, "sd": sd, "sharpe": mu / sd, "schiefe": float(np.mean(z ** 3)), "kurtosis": float(np.mean(z ** 4))}


def psr(sharpe: float, n: int, schiefe: float, kurtosis: float, vergleich: float = 0.0) -> float:
    nenner = 1.0 - schiefe * sharpe + (kurtosis - 1.0) / 4.0 * sharpe * sharpe
    if nenner <= 0 or n < 2:
        return float("nan")
    return float(_NORMAL.cdf((sharpe - vergleich) * math.sqrt(n - 1) / math.sqrt(nenner)))


def erwartetes_max_sharpe(versuche: int, varianz: float) -> float:
    """SR0: erwartetes Maximum von ``versuche`` unabhängigen Sharpe-Schätzungen ohne wahren Vorteil."""
    if versuche <= 1:
        return 0.0
    z1 = _NORMAL.inv_cdf(1.0 - 1.0 / versuche)
    z2 = _NORMAL.inv_cdf(1.0 - 1.0 / (versuche * math.e))
    return math.sqrt(varianz) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def deflated_sharpe(r: np.ndarray, versuche: int, varianz: float | None = None) -> dict:
    """DSR = PSR(SR0). ``varianz`` = Varianz der Versuchs-Sharpes; ohne Angabe der Nullfall 1/(n-1) (wie im Laborbericht)."""
    m = momente(r)
    if not np.isfinite(m["sharpe"]):
        return {"versuche": versuche, "dsr": None, **m}
    v = 1.0 / (m["n"] - 1) if varianz is None else varianz
    s0 = erwartetes_max_sharpe(versuche, v)
    return {"versuche": versuche, "varianz": v, "sr0": s0, "psr_null": psr(m["sharpe"], m["n"], m["schiefe"], m["kurtosis"], 0.0),
            "dsr": psr(m["sharpe"], m["n"], m["schiefe"], m["kurtosis"], s0), **m}
