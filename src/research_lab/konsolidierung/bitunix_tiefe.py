"""Auswertung einer kurzen Serie öffentlicher Bitunix-Orderbuch-Schnappschüsse (Spread, Marktorder-Schlupf je Ordergröße).

Das ist eine Momentaufnahme (45 Schnappschüsse im Abstand von ca. 2 s am 2026-11-16), keine Messung über Tageszeiten
oder Marktphasen. Sie belegt nur die Größenordnung des Schlupfs bei ruhigem Markt und ersetzt keine Langzeitmessung.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

GROESSEN_USDT = (1_000, 5_000, 20_000, 100_000)


def _lauf(buch: list[list[str]], notional: float, seite: str, mid: float) -> float | None:
    """Durchschnittspreis eines Marktorders über das Buch, als Abweichung zur Mitte in bp. None, wenn das Buch (50 Stufen) nicht reicht."""
    rest = notional
    kosten = 0.0
    menge = 0.0
    for preis, vol in buch:
        p, v = float(preis), float(vol)
        nominal = p * v
        nimm = min(rest, nominal)
        menge += nimm / p
        kosten += nimm
        rest -= nimm
        if rest <= 1e-9:
            break
    if rest > 1e-9:
        return None
    vwap = kosten / menge
    return (vwap / mid - 1) * 1e4 if seite == "kauf" else (1 - vwap / mid) * 1e4


def auswerten(pfad: str | Path) -> dict:
    d = json.loads(Path(pfad).read_text())
    out: dict = {}
    for sym, snaps in d.items():
        spreads, ok = [], 0
        schlupf = {g: {"kauf": [], "verkauf": [], "nicht_gedeckt": 0} for g in GROESSEN_USDT}
        tiefe50 = []
        for s in snaps:
            if "error" in s:
                continue
            asks = [[float(p), float(v)] for p, v in s["asks"]]
            bids = [[float(p), float(v)] for p, v in s["bids"]]
            bid, ask = bids[0][0], asks[0][0]
            mid = (bid + ask) / 2
            spreads.append((ask - bid) / mid * 1e4)
            ok += 1
            tiefe50.append((sum(p * v for p, v in asks), sum(p * v for p, v in bids)))
            for g in GROESSEN_USDT:
                k = _lauf(s["asks"], g, "kauf", mid)
                v = _lauf(s["bids"], g, "verkauf", mid)
                if k is None or v is None:
                    schlupf[g]["nicht_gedeckt"] += 1
                if k is not None:
                    schlupf[g]["kauf"].append(k)
                if v is not None:
                    schlupf[g]["verkauf"].append(v)
        sp = np.array(spreads)
        out[sym] = {
            "schnappschuesse": ok,
            "spread_bp": {"median": round(float(np.median(sp)), 3), "mittel": round(float(sp.mean()), 3), "p95": round(float(np.percentile(sp, 95)), 3), "max": round(float(sp.max()), 3)},
            "tiefe_50_stufen_usdt_median": {"ask": round(float(np.median([a for a, _ in tiefe50])), 0), "bid": round(float(np.median([b for _, b in tiefe50])), 0)},
            "schlupf_marktorder_bp_gegen_mitte": {
                str(g): {"kauf_median": (round(float(np.median(v["kauf"])), 3) if v["kauf"] else None), "verkauf_median": (round(float(np.median(v["verkauf"])), 3) if v["verkauf"] else None),
                          "kauf_p95": (round(float(np.percentile(v["kauf"], 95)), 3) if v["kauf"] else None), "verkauf_p95": (round(float(np.percentile(v["verkauf"], 95)), 3) if v["verkauf"] else None),
                          "nicht_gedeckt_von_50_stufen": v["nicht_gedeckt"]}
                for g, v in schlupf.items()},
        }
    return out


if __name__ == "__main__":
    import sys

    print(json.dumps(auswerten(sys.argv[1]), indent=1, ensure_ascii=False))
