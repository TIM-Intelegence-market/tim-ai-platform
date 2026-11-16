"""Datenaudit der Binance-Archive (Lücken, Duplikate, Reihenfolge, OHLC, 4h gegen 1h, Funding).

Aufruf (aus dem Repo-Wurzelordner): ``python3 -m src.research_lab.konsolidierung.datenaudit <archiv-wurzel> <ausgabe.json>``
Liest nur Zeiträume vor dem Holdout (siehe ``daten``).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import numpy as np

from src.research_lab.konsolidierung import daten
from src.research_lab.konsolidierung.daten import MS_1H, MS_4H, SYMBOLE


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _luecken(t: np.ndarray, schritt: int) -> list[dict]:
    d = np.diff(t)
    idx = np.nonzero(d != schritt)[0]
    out = []
    for i in idx:
        out.append({"nach": _iso(int(t[i])), "vor": _iso(int(t[i + 1])), "fehlend": int(d[i] // schritt - 1)})
    return out


def pruefe_kerzen(k: daten.Kerzen, schritt: int) -> dict:
    t = k.t
    erwartet = int((t[-1] - t[0]) // schritt + 1)
    luecken = _luecken(t, schritt)
    fehlend = sum(x["fehlend"] for x in luecken)
    raster = int(np.sum(t % schritt != 0))
    ohlc_bad = int(np.sum((k.l > np.minimum(k.o, k.c)) | (k.h < np.maximum(k.o, k.c)) | (k.l > k.h)))
    nichtpos = int(np.sum((k.o <= 0) | (k.h <= 0) | (k.l <= 0) | (k.c <= 0)))
    vol_neg = int(np.sum(k.v < 0))
    taker_gr = int(np.sum(k.taker_buy > k.v * (1 + 1e-9)))
    vol_null = int(np.sum(k.v == 0))
    flach = int(np.sum((k.o == k.h) & (k.h == k.l) & (k.l == k.c)))
    ret = np.abs(np.log(k.c[1:] / k.c[:-1])) if len(k.c) > 1 else np.array([])
    gr = int(np.sum(ret > 0.15)) if len(ret) else 0
    spanne = np.abs(np.log(k.h / k.l))
    top = np.argsort(-spanne)[:3]
    return {
        "symbol": k.symbol, "intervall": k.intervall,
        "von": _iso(int(t[0])), "bis": _iso(int(t[-1])), "kerzen": int(len(t)), "erwartet_im_Bereich": erwartet,
        "roh_zeilen": k.roh_zeilen, "duplikate_entfernt": k.duplikate, "unsortiert_roh": k.unsortiert,
        "luecken": luecken, "fehlende_kerzen": fehlend, "ausserhalb_raster": raster,
        "ohlc_ungueltig": ohlc_bad, "preis_nichtpositiv": nichtpos, "volumen_negativ": vol_neg,
        "taker_gt_volumen": taker_gr, "volumen_null": vol_null, "flache_kerzen": flach,
        "rendite_absolut_ueber_15_prozent": gr,
        "groesste_spannen_log": [{"zeit": _iso(int(t[i])), "log_hoch_tief": round(float(spanne[i]), 4)} for i in top],
    }


def vergleiche_4h_mit_1h(k4: daten.Kerzen, k1: daten.Kerzen) -> dict:
    """4h-Kerzen gegen aus 1h aggregierte Kerzen (Open erste, Close letzte, High max, Low min, Volumen Summe)."""
    t1 = {int(t): i for i, t in enumerate(k1.t)}
    n = 0
    unvollstaendig = 0
    abw_o = abw_h = abw_l = abw_c = 0
    abw_v = 0
    max_rel = {"o": 0.0, "h": 0.0, "l": 0.0, "c": 0.0, "v": 0.0}
    for j, t in enumerate(k4.t):
        idx = [t1.get(int(t) + m * MS_1H) for m in range(4)]
        if any(i is None for i in idx):
            unvollstaendig += 1
            continue
        n += 1
        o = k1.o[idx[0]]
        c = k1.c[idx[3]]
        h = max(k1.h[i] for i in idx)
        l = min(k1.l[i] for i in idx)
        v = sum(k1.v[i] for i in idx)
        for name, a, b in (("o", k4.o[j], o), ("h", k4.h[j], h), ("l", k4.l[j], l), ("c", k4.c[j], c), ("v", k4.v[j], v)):
            rel = abs(a - b) / max(abs(a), 1e-12)
            max_rel[name] = max(max_rel[name], rel)
            if rel > 1e-9:
                if name == "o":
                    abw_o += 1
                elif name == "h":
                    abw_h += 1
                elif name == "l":
                    abw_l += 1
                elif name == "c":
                    abw_c += 1
                else:
                    abw_v += 1
    return {"verglichen": n, "ohne_vollstaendige_1h": unvollstaendig, "abweichend_open": abw_o, "abweichend_high": abw_h,
            "abweichend_low": abw_l, "abweichend_close": abw_c, "abweichend_volumen": abw_v,
            "max_relative_abweichung": {k: float(f"{v:.3e}") for k, v in max_rel.items()}}


def pruefe_funding(f: daten.Funding) -> dict:
    t = f.t
    d = np.diff(t)
    runde = np.round(t / (8 * MS_1H)) * (8 * MS_1H)
    jitter = t - runde
    luecken = []
    soll = 8 * MS_1H
    idx = np.nonzero(np.abs(d - soll) > 5_000)[0]
    for i in idx[:20]:
        luecken.append({"nach": _iso(int(t[i])), "vor": _iso(int(t[i + 1])), "abstand_h": round(float(d[i] / MS_1H), 3)})
    return {
        "symbol": f.symbol, "von": _iso(int(t[0])), "bis": _iso(int(t[-1])), "zeilen": int(len(t)), "roh_zeilen": f.roh_zeilen,
        "duplikate_entfernt": f.duplikate,
        "unregelmaessige_abstaende": int(len(idx)), "beispiele_unregelmaessig": luecken,
        "jitter_ms_min": int(jitter.min()), "jitter_ms_max": int(jitter.max()),
        "negativer_jitter_anzahl": int(np.sum(jitter < 0)),
        "rate_min": float(f.rate.min()), "rate_max": float(f.rate.max()), "rate_mittel": float(f.rate.mean()),
        "rate_median": float(np.median(f.rate)), "anteil_positiv": float(np.mean(f.rate > 0)),
        "rate_ueber_0_5_prozent": int(np.sum(np.abs(f.rate) > 0.005)),
    }


def pruefe_manifest(wurzel: str) -> dict:
    """SHA-256 aller vorhandenen Archivdateien gegen manifest.json (Lab-Manifest vom Mac, Stand 2026-10-27)."""
    import hashlib
    from pathlib import Path

    wz = Path(wurzel)
    m = json.loads((wz / "manifest.json").read_text())
    ok = bad = fehlt = 0
    fehlt_nach: dict[str, int] = {}
    abweichend: list[str] = []
    for pfad, meta in m.items():
        p = wz / pfad
        if not p.exists():
            fehlt += 1
            teil = pfad.split("/")
            schluessel = f"{teil[0]}/{teil[1]}/{teil[3]}"
            fehlt_nach[schluessel] = fehlt_nach.get(schluessel, 0) + 1
            continue
        if hashlib.sha256(p.read_bytes()).hexdigest() == meta["sha256"]:
            ok += 1
        else:
            bad += 1
            abweichend.append(pfad)
    return {"manifest_eintraege": len(m), "geprueft_ok": ok, "geprueft_abweichend": bad, "nicht_bereitgestellt": fehlt,
            "nicht_bereitgestellt_nach_serie": fehlt_nach, "abweichende_dateien": abweichend,
            "hinweis": "Nicht bereitgestellt = 1m/15m-Serien, für die 4h-Konsolidierung nicht benötigt. Das Manifest enthält keine Monate ab 2025."}


def lauf(wurzel: str) -> dict:
    out: dict = {"holdout_geladen": False, "manifest": pruefe_manifest(wurzel), "kerzen_futures_4h": [], "kerzen_futures_1h": [], "kerzen_futures_1d": [],
                 "kerzen_spot_1h": [], "vergleich_4h_gegen_1h": {}, "funding": []}
    cache = {}
    for s in SYMBOLE:
        for (markt, iv, schluessel, schritt) in (("futures_um", "4h", "kerzen_futures_4h", MS_4H), ("futures_um", "1h", "kerzen_futures_1h", MS_1H),
                                                  ("futures_um", "1d", "kerzen_futures_1d", 24 * MS_1H), ("spot", "1h", "kerzen_spot_1h", MS_1H)):
            k = daten.laden(wurzel, markt, s, iv)
            if k is None:
                out[schluessel].append({"symbol": s, "intervall": iv, "vorhanden": False})
                continue
            cache[(markt, s, iv)] = k
            out[schluessel].append(pruefe_kerzen(k, schritt))
        k4 = cache.get(("futures_um", s, "4h"))
        k1 = cache.get(("futures_um", s, "1h"))
        if k4 is not None and k1 is not None:
            out["vergleich_4h_gegen_1h"][s] = vergleiche_4h_mit_1h(k4, k1)
        fr = daten.laden_funding(wurzel, s)
        if fr is not None:
            out["funding"].append(pruefe_funding(fr))
    return out


if __name__ == "__main__":
    ergebnis = lauf(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(ergebnis, fh, indent=1, ensure_ascii=False)
    print("ok", sys.argv[2])
