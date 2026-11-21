"""Vergleich der Bitunix-4h-Kerzen (öffentliche API, bis 2024-12-31) mit den Binance-USD-M-Kerzen.

Die Bitunix-Daten wurden am 2026-11-16 von ``/api/v1/futures/market/kline`` (ohne Schlüssel) geholt,
Intervall 4h, endTime 2024-12-31T23:59:59Z. Kein Zeitpunkt ab 2025-01-01 wurde abgefragt.
Funding bleibt in der Nachrechnung das von Binance (Bitunix-Funding-Historie ist nicht Teil dieser Daten).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.research_lab.konsolidierung.daten import HOLDOUT_START_MS, HoldoutVerweigert, Kerzen


def lade_bitunix(pfad: str | Path, symbol: str) -> Kerzen:
    rows = json.loads(Path(pfad).read_text())
    t = np.array([int(r["time"]) for r in rows], dtype=np.int64)
    order = np.argsort(t)
    t = t[order]
    if t[-1] >= HOLDOUT_START_MS:
        raise HoldoutVerweigert("Bitunix-Daten reichen in den Holdout")
    f = lambda k: np.array([float(rows[i][k]) for i in order])
    return Kerzen(symbol, "4h", t, f("open"), f("high"), f("low"), f("close"), f("baseVol"), np.zeros(len(t)), len(t), 0, 0)


def beschneide(k: Kerzen, von_ms: int, bis_ms: int | None = None) -> Kerzen:
    m = k.t >= von_ms
    if bis_ms is not None:
        m &= k.t < bis_ms
    return Kerzen(k.symbol, k.intervall, k.t[m], k.o[m], k.h[m], k.l[m], k.c[m], k.v[m], k.taker_buy[m], int(m.sum()), 0, 0)


def _stat(x: np.ndarray) -> dict:
    a = np.abs(x)
    return {"mittel_bp": round(float(x.mean()), 3), "streuung_bp": round(float(x.std()), 3), "median_abs_bp": round(float(np.median(a)), 3),
            "p95_abs_bp": round(float(np.percentile(a, 95)), 3), "p99_abs_bp": round(float(np.percentile(a, 99)), 3), "max_abs_bp": round(float(a.max()), 3)}


def abgleich(bn: Kerzen, bx: Kerzen) -> dict:
    gemeinsam = np.intersect1d(bn.t, bx.t)
    i = np.searchsorted(bn.t, gemeinsam)
    j = np.searchsorted(bx.t, gemeinsam)
    out = {"symbol": bn.symbol, "gemeinsame_kerzen": int(len(gemeinsam)), "binance_kerzen_im_bereich": int(((bn.t >= gemeinsam[0]) & (bn.t <= gemeinsam[-1])).sum()),
           "bitunix_kerzen": int(len(bx.t)), "von": int(gemeinsam[0]), "bis": int(gemeinsam[-1])}
    for name, a, b in (("open", bn.o, bx.o), ("high", bn.h, bx.h), ("low", bn.l, bx.l), ("close", bn.c, bx.c)):
        d = (b[j] - a[i]) / a[i] * 1e4
        out[name] = _stat(d)
    rn = np.diff(np.log(bn.c[i]))
    rx = np.diff(np.log(bx.c[j]))
    out["korrelation_4h_renditen"] = round(float(np.corrcoef(rn, rx)[0, 1]), 6)
    spanne_n = (bn.h[i] - bn.l[i]) / bn.c[i] * 1e4
    spanne_x = (bx.h[j] - bx.l[j]) / bx.c[j] * 1e4
    out["spanne_mittel_bp"] = {"binance": round(float(spanne_n.mean()), 2), "bitunix": round(float(spanne_x.mean()), 2)}
    return out
