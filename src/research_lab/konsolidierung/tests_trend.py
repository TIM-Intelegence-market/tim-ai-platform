"""Tests T1 bis T9 des Prüfprotokolls Konsolidierung 1.0 für die Trendkandidaten C1 (BTC/ETH/SOL) und C3 (BTC/ETH).

Alle Tests benutzen die unabhängige Nachrechnung (``s7b_nachrechnung``) und die einheitliche Kennzahlenbasis
(``kennzahlen``). Kein Test lädt Daten ab 2025-01-01 (der Lader verweigert sie). Kosten K1, wenn nichts anderes steht.
Es wird kein Parameter ausgewählt oder angepasst; Raster und Varianten dienen nur der Stabilitätsprüfung.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.research_lab.konsolidierung import daten
from src.research_lab.konsolidierung import kennzahlen as kz
from src.research_lab.konsolidierung.s7b_nachrechnung import (BASIS, SYMBOLE, TRAIN_ENDE_MS, VALID_ENDE_MS, Kosten, Trade, Variante, abschnitt,
                                                                bereite_vor, mit_signalen, simuliere)

SEED = 20261116
ZIEHUNGEN_ZUFALL = 1000
ZIEHUNGEN_BOOTSTRAP = 10_000

KANDIDATEN: dict[str, tuple[str, ...]] = {"C1": ("BTCUSDT", "ETHUSDT", "SOLUSDT"), "C3": ("BTCUSDT", "ETHUSDT")}
V_C1 = Variante(20, 3.0)

K1 = replace(BASIS, gebuehr=0.0006)
KOSTEN: dict[str, Kosten] = {
    "K0": BASIS,
    "K1": K1,
    "K2": Kosten(gebuehr=0.0006, slip_einstieg=0.0006, slip_ziel=0.0006, slip_zeit=0.0006, slip_stop=0.0010, funding="hist_ohne_gutschrift"),
    "K3": Kosten(gebuehr=0.0006, slip_einstieg=0.0009, slip_ziel=0.0009, slip_zeit=0.0009, slip_stop=0.0015, funding="hist_ohne_gutschrift", funding_faktor=1.5),
    "K4": Kosten(gebuehr=0.0006, gebuehr_ziel=0.0002, slip_einstieg=0.0003, slip_ziel=0.0, slip_zeit=0.0003, slip_stop=0.0005),
    "L1": replace(K1, verzoegerung_kerzen=1),
}

# T4: Nachbarzellen (im Protokoll festgelegt) und volles Raster (8 x 5 x 5 x 3; die Werte außerhalb der Nachbarzellen sind im
# Protokoll 1.0 nicht aufgezählt und wurden vor dem Lauf in diesem Modul festgelegt, siehe TESTLOG)
RASTER = {"kanal": (10, 15, 20, 25, 30, 40, 55, 80), "ziel": (1.5, 2.0, 3.0, 4.0, 5.0), "atr": (0.75, 1.0, 1.5, 2.0, 3.0), "zeitstop": (15, 30, 60)}
NACHBARN = {"kanal": (15, 20, 30), "ziel": (2.0, 3.0, 4.0), "atr": (1.0, 1.5, 2.0), "zeitstop": (15, 30, 60)}

DSR_VERSUCHE = (58, 64, 100, 200, 26_707)


# ---------------------------------------------------------------------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------------------------------------------------------------------

def daten_laden(wurzel: str) -> tuple[dict, dict]:
    kerzen = {s: daten.laden(wurzel, "futures_um", s, "4h") for s in SYMBOLE}
    fund = {s: daten.laden_funding(wurzel, s) for s in SYMBOLE}
    return kerzen, fund


def reihenfolge_von(symbole: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(s for s in SYMBOLE if s in symbole)


def lauf(kerzen: dict, fund: dict, symbole: tuple[str, ...], v: Variante, kosten: Kosten, portfolio: bool = True,
         reihenfolge: tuple[str, ...] | None = None, reihen: dict | None = None) -> list[Trade]:
    sym = reihenfolge_von(symbole)
    return simuliere({s: kerzen[s] for s in sym}, fund, v, kosten, portfolio=portfolio, reihenfolge=reihenfolge or sym, reihen=reihen)


def nach_abschnitt(tr: list[Trade]) -> dict[str, list[Trade]]:
    """Abschnittsregel 1.2; ``pooled`` = Training und Validierung zusammen."""
    out: dict[str, list[Trade]] = {"train": [], "validation": []}
    for t in tr:
        a = abschnitt(t)
        if a:
            out[a].append(t)
    out["pooled"] = out["train"] + out["validation"]
    return out


def arrays(trades: list[Trade]) -> dict[str, np.ndarray]:
    return {
        "r": np.array([t.r for t in trades], dtype=float),
        "signal_ms": np.array([t.signal_zeit for t in trades], dtype=np.int64),
        "exit_ms": np.array([t.ausstieg_zeit for t in trades], dtype=np.int64),
        "seite": np.array([t.seite for t in trades], dtype=np.int64),
        "symbol": np.array([t.symbol for t in trades]),
        "grund": np.array([t.grund for t in trades]),
        "kosten_r": np.array([t.kosten_r for t in trades], dtype=float),
        "funding_r": np.array([t.funding_r for t in trades], dtype=float),
        "brutto_r": np.array([t.brutto_r for t in trades], dtype=float),
        "haltedauer_h": np.array([t.kerzen * 4.0 for t in trades], dtype=float),
        "stop_anteil": np.array([abs(t.einstieg - t.stop) / t.einstieg for t in trades], dtype=float),
    }


def kurz(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0}
    a = arrays(trades)
    r = a["r"]
    ordnung = np.argsort(a["exit_ms"], kind="stable")
    return {"n": int(len(r)), "e_r": float(r.mean()), "summe_r": float(r.sum()), "sd_r": float(r.std(ddof=1)) if len(r) > 1 else None,
            "profit_faktor": kz.profit_faktor(r), "trefferquote": float((r > 0).mean()), "max_drawdown_r": kz.max_drawdown(r[ordnung])[0]}


def meta(test: str, konfig: dict, befehl: str, zeitraum: str, status: str, grenzen: list[str]) -> dict:
    return {"test": test, "erzeugt_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "konfiguration": konfig, "befehl": befehl,
            "zeitraum": zeitraum, "status": status, "grenzen": grenzen, "seed": SEED}


def schreibe(pfad: Path, obj: dict) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=_json_default), encoding="utf-8")


def _json_default(o):  # numpy-Typen
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"nicht serialisierbar: {type(o)}")


# ---------------------------------------------------------------------------------------------------------------------------------------
# T1: Reproduktion der gespeicherten Trades
# ---------------------------------------------------------------------------------------------------------------------------------------

def t1_reproduktion(kerzen: dict, fund: dict, pfad_s7b: str, pfad_s7: str) -> dict:
    import hashlib
    out: dict = {"quellen": {}, "s7b": {}, "s7": {}}
    for name, pfad in (("s7b", pfad_s7b), ("s7", pfad_s7)):
        out["quellen"][name] = {"datei": Path(pfad).name, "sha256": hashlib.sha256(Path(pfad).read_bytes()).hexdigest()}
    orig_b = json.loads(Path(pfad_s7b).read_text())
    orig_7 = json.loads(Path(pfad_s7).read_text())
    for kanal, ziel in ((20, 3.0), (20, 4.0), (55, 3.0), (55, 4.0)):
        v = Variante(kanal, ziel)
        for modus, portfolio, orig, praefix in (("s7b", True, orig_b, "S7b"), ("s7", False, orig_7, "S7")):
            tr = simuliere(kerzen, fund, v, BASIS, portfolio=portfolio)
            for sec in ("train", "validation"):
                o = {(x["symbol"], x["signal_time"]): x for x in orig if x["variant"] == f"{praefix}-{v.name}" and x["section"] == sec}
                m = {(t.symbol, t.signal_zeit): t for t in tr if abschnitt(t) == sec}
                gemeinsam = set(o) & set(m)
                max_dr = max((abs(o[k]["r"] - m[k].r) for k in gemeinsam), default=None)
                gleich = all(o[k]["reason"] == m[k].grund and o[k]["entry_time"] == m[k].einstieg_zeit and o[k]["exit_time"] == m[k].ausstieg_zeit
                             for k in gemeinsam)
                out[modus][f"{v.name}/{sec}"] = {"gespeichert": len(o), "nachgerechnet": len(m), "gemeinsam": len(gemeinsam),
                                                 "nur_gespeichert": len(set(o) - set(m)), "nur_nachgerechnet": len(set(m) - set(o)),
                                                 "max_abw_r": max_dr, "grund_und_zeiten_gleich": bool(gleich)}
    alle = [x for modus in ("s7b", "s7") for x in out[modus].values()]
    out["gesamt"] = {"trades_gespeichert": int(sum(x["gespeichert"] for x in alle)), "trades_gemeinsam": int(sum(x["gemeinsam"] for x in alle)),
                     "max_abw_r": max(x["max_abw_r"] for x in alle if x["max_abw_r"] is not None),
                     "bestanden": bool(all(x["nur_gespeichert"] == 0 and x["nur_nachgerechnet"] == 0 and x["grund_und_zeiten_gleich"] and
                                           (x["max_abw_r"] or 0) < 1e-12 for x in alle))}
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------
# T2: Kostenszenarien und Bruchstelle
# ---------------------------------------------------------------------------------------------------------------------------------------

def skaliere_kosten(basis: Kosten, m: float) -> Kosten:
    return replace(basis, gebuehr=basis.gebuehr * m, slip_einstieg=basis.slip_einstieg * m, slip_ziel=basis.slip_ziel * m,
                   slip_zeit=basis.slip_zeit * m, slip_stop=basis.slip_stop * m)


def t2_kosten(kerzen: dict, fund: dict) -> dict:
    out: dict = {}
    mgrid = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0)
    for name, symbole in KANDIDATEN.items():
        res: dict = {"szenarien": {}, "bruchstelle": {}}
        for kname, k in KOSTEN.items():
            tr = nach_abschnitt(lauf(kerzen, fund, symbole, V_C1, k))
            res["szenarien"][kname] = {sec: kurz(tr[sec]) for sec in tr}
        res["g2_bestanden"] = bool(all(res["szenarien"]["K2"][sec]["e_r"] > 0 for sec in ("train", "validation")))
        kurve = {sec: [] for sec in ("train", "validation", "pooled")}
        for m in mgrid:
            tr = nach_abschnitt(lauf(kerzen, fund, symbole, V_C1, skaliere_kosten(K1, m)))
            for sec in kurve:
                kurve[sec].append(kurz(tr[sec])["e_r"])
        res["bruchstelle"]["multiplikator_gitter"] = list(mgrid)
        res["bruchstelle"]["e_r"] = kurve
        res["bruchstelle"]["null_durchgang_multiplikator"] = {sec: _nulldurchgang(mgrid, kurve[sec]) for sec in kurve}
        out[name] = res
    return out


def _nulldurchgang(x: tuple, y: list[float]) -> float | None:
    for i in range(len(x) - 1):
        if y[i] > 0 >= y[i + 1]:
            return float(x[i] + (x[i + 1] - x[i]) * y[i] / (y[i] - y[i + 1]))
    return None


# ---------------------------------------------------------------------------------------------------------------------------------------
# T3: Zufallsvergleich in SMA200-Richtung
# ---------------------------------------------------------------------------------------------------------------------------------------

def t3_zufall(kerzen: dict, fund: dict, symbole: tuple[str, ...], ziehungen: int = ZIEHUNGEN_ZUFALL, seed: int = SEED, kosten: Kosten = K1) -> dict:
    sym = reihenfolge_von(symbole)
    ksub = {s: kerzen[s] for s in sym}
    basis = {s: bereite_vor(ksub[s], V_C1) for s in sym}
    kand = nach_abschnitt(simuliere(ksub, fund, V_C1, kosten, portfolio=True, reihenfolge=sym, reihen=basis))
    e_kand = {sec: kurz(kand[sec])["e_r"] for sec in ("train", "validation", "pooled")}
    # Signalhäufigkeit des Kandidaten je Instrument und Abschnitt (alle Signale vor der Positionsgrenze)
    p_sig: dict[str, dict[str, float]] = {}
    masken: dict[str, dict[str, np.ndarray]] = {}
    for s in sym:
        r = basis[s]
        m_tr = r.vorlauf & (r.t < TRAIN_ENDE_MS)
        m_va = r.vorlauf & (r.t >= TRAIN_ENDE_MS) & (r.t < VALID_ENDE_MS)
        masken[s] = {"train": m_tr, "validation": m_va}
        p_sig[s] = {"train": float((r.sig != 0)[m_tr].sum() / max(m_tr.sum(), 1)), "validation": float((r.sig != 0)[m_va].sum() / max(m_va.sum(), 1)),
                    "signale_train": int((r.sig != 0)[m_tr].sum()), "signale_validation": int((r.sig != 0)[m_va].sum()),
                    "kerzen_train": int(m_tr.sum()), "kerzen_validation": int(m_va.sum())}
    rng = np.random.default_rng(seed)
    e_z = {sec: np.empty(ziehungen) for sec in ("train", "validation", "pooled")}
    n_z = {sec: np.empty(ziehungen) for sec in ("train", "validation", "pooled")}
    for d in range(ziehungen):
        reihen = {}
        for s in sym:
            r = basis[s]
            u = rng.random(len(r.t))
            p = np.where(masken[s]["train"], p_sig[s]["train"], np.where(masken[s]["validation"], p_sig[s]["validation"], 0.0))
            sig = np.where(r.vorlauf & (u < p), r.sma_seite, 0)
            reihen[s] = mit_signalen(r, sig)
        tr = nach_abschnitt(simuliere(ksub, fund, V_C1, kosten, portfolio=True, reihenfolge=sym, reihen=reihen))
        for sec in e_z:
            k = kurz(tr[sec])
            e_z[sec][d] = k["e_r"] if k["n"] else np.nan
            n_z[sec][d] = k["n"]
    out: dict = {"kandidat_e_r": e_kand, "kandidat_n": {sec: len(kand[sec]) for sec in kand}, "signalhaeufigkeit": p_sig, "ziehungen": ziehungen, "seed": seed, "sektionen": {}}
    for sec in e_z:
        x = e_z[sec][~np.isnan(e_z[sec])]
        p = (1 + int((x >= e_kand[sec]).sum())) / (1 + len(x))
        out["sektionen"][sec] = {"e_r_zufall_mittel": float(x.mean()), "e_r_zufall_median": float(np.median(x)), "e_r_zufall_ci90": [float(np.percentile(x, 5)), float(np.percentile(x, 95))],
                                 "e_r_zufall_max": float(x.max()), "anteil_ziehungen_positiv": float((x > 0).mean()), "n_zufall_mittel": float(np.nanmean(n_z[sec])),
                                 "p_einseitig": p, "gueltige_ziehungen": int(len(x))}
    out["g3_bestanden"] = bool(out["sektionen"]["train"]["p_einseitig"] <= 0.05 and out["sektionen"]["validation"]["p_einseitig"] <= 0.05)
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------
# T4: Parameter-Raster
# ---------------------------------------------------------------------------------------------------------------------------------------

def t4_raster(kerzen: dict, fund: dict, symbole: tuple[str, ...], kosten: Kosten = K1) -> dict:
    sym = reihenfolge_von(symbole)
    ksub = {s: kerzen[s] for s in sym}
    zellen = []
    for kanal in RASTER["kanal"]:
        for atr in RASTER["atr"]:
            basis = {s: bereite_vor(ksub[s], Variante(kanal, 3.0, atr_faktor=atr)) for s in sym}
            for ziel in RASTER["ziel"]:
                for zs in RASTER["zeitstop"]:
                    v = Variante(kanal, ziel, zeitstop=zs, atr_faktor=atr)
                    tr = nach_abschnitt(simuliere(ksub, fund, v, kosten, portfolio=True, reihenfolge=sym, reihen=basis))
                    z = {"kanal": kanal, "ziel": ziel, "atr": atr, "zeitstop": zs}
                    for sec in ("train", "validation", "pooled"):
                        r = np.array([t.r for t in tr[sec]])
                        z[sec] = {"n": int(len(r)), "e_r": float(r.mean()) if len(r) else None, "sharpe": float(r.mean() / r.std()) if len(r) > 2 and r.std() > 0 else None}
                    z["nachbar"] = bool(kanal in NACHBARN["kanal"] and ziel in NACHBARN["ziel"] and atr in NACHBARN["atr"] and zs in NACHBARN["zeitstop"])
                    zellen.append(z)
    out: dict = {"zellen": len(zellen), "raster": {k: list(v) for k, v in RASTER.items()}, "nachbarn": {k: list(v) for k, v in NACHBARN.items()}, "zellen_liste": zellen}
    nb = [z for z in zellen if z["nachbar"]]
    out["nachbarzellen"] = len(nb)
    out["anteil_positiv_nachbarn"] = {sec: float(np.mean([(z[sec]["e_r"] or 0) > 0 for z in nb])) for sec in ("train", "validation", "pooled")}
    out["anteil_positiv_raster"] = {sec: float(np.mean([(z[sec]["e_r"] or 0) > 0 for z in zellen])) for sec in ("train", "validation", "pooled")}
    out["g4_bestanden"] = bool(out["anteil_positiv_nachbarn"]["train"] >= 0.7 and out["anteil_positiv_nachbarn"]["validation"] >= 0.7)
    for sec in ("train", "validation", "pooled"):
        e = np.array([z[sec]["e_r"] for z in zellen if z[sec]["e_r"] is not None])
        out.setdefault("verteilung_e_r", {})[sec] = {"min": float(e.min()), "p05": float(np.percentile(e, 5)), "p25": float(np.percentile(e, 25)), "median": float(np.median(e)),
                                                     "p75": float(np.percentile(e, 75)), "p95": float(np.percentile(e, 95)), "max": float(e.max())}
    c1 = next(z for z in zellen if z["kanal"] == 20 and z["ziel"] == 3.0 and z["atr"] == 1.5 and z["zeitstop"] == 30)
    out["c1_zelle"] = c1
    out["c1_rang_prozent"] = {sec: float(np.mean([(z[sec]["e_r"] or -9) <= c1[sec]["e_r"] for z in zellen])) for sec in ("train", "validation", "pooled")}
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------
# T5: Komponenten-Entfernung (nur Bericht)
# ---------------------------------------------------------------------------------------------------------------------------------------

def t5_komponenten(kerzen: dict, fund: dict) -> dict:
    alle = KANDIDATEN["C1"]
    spez = {
        "C1 (Referenz)": dict(),
        "ohne SMA200-Filter": dict(v=replace(V_C1, sma_filter=False)),
        "ohne Mindestrisiko 1 %": dict(v=replace(V_C1, mindest_risiko=0.0)),
        "ohne Zeitstopp (nur Stop/Ziel)": dict(v=replace(V_C1, zeitstop=100_000)),
        "ohne Positionsgrenze (eine Position je Instrument, S7)": dict(portfolio=False),
        "nur long": dict(v=replace(V_C1, seiten=1)),
        "nur short": dict(v=replace(V_C1, seiten=-1)),
        "nur BTC (allein gerechnet)": dict(symbole=("BTCUSDT",)),
        "nur ETH (allein gerechnet)": dict(symbole=("ETHUSDT",)),
        "nur SOL (allein gerechnet)": dict(symbole=("SOLUSDT",)),
        "ohne Funding": dict(kosten=replace(K1, funding="aus")),
        "gespiegelte Reihenfolge (SOL > ETH > BTC)": dict(reihenfolge=("SOLUSDT", "ETHUSDT", "BTCUSDT")),
    }
    out = {}
    for name, kw in spez.items():
        tr = nach_abschnitt(lauf(kerzen, fund, kw.get("symbole", alle), kw.get("v", V_C1), kw.get("kosten", K1), kw.get("portfolio", True), kw.get("reihenfolge")))
        out[name] = {sec: kurz(tr[sec]) for sec in tr}
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------
# T6: Konzentration und Abhängigkeit
# ---------------------------------------------------------------------------------------------------------------------------------------

def _jahr(ms: np.ndarray) -> np.ndarray:
    return kz.monat_schluessel(ms) // 100


def t6_konzentration(kerzen: dict, fund: dict, symbole: tuple[str, ...]) -> dict:
    tr = nach_abschnitt(lauf(kerzen, fund, symbole, V_C1, K1))["pooled"]
    a = arrays(tr)
    r = a["r"]
    jahr = _jahr(a["signal_ms"])
    monat = kz.monat_schluessel(a["signal_ms"])
    out: dict = {"gepoolt": kurz(tr), "ohne_jahr": {}, "ohne_instrument": {}}
    for y in np.unique(jahr):
        m = jahr != y
        out["ohne_jahr"][str(int(y))] = {"n": int(m.sum()), "e_r": float(r[m].mean())}
    for s in np.unique(a["symbol"]):
        m = a["symbol"] != s
        out["ohne_instrument"][str(s)] = {"n": int(m.sum()), "e_r": float(r[m].mean())}
    out["g5_bestanden"] = bool(all(x["e_r"] > 0 for x in out["ohne_jahr"].values()) and all(x["e_r"] > 0 for x in out["ohne_instrument"].values()))
    ord_r = np.sort(r)[::-1]
    out["ohne_beste_trades"] = {str(k): {"e_r": float(ord_r[k:].mean()), "summe_r": float(ord_r[k:].sum())} for k in (1, 3, 5, 10, 25)}
    k5 = max(1, int(round(0.05 * len(r))))
    out["anteil_beste_5_prozent_an_summe"] = float(ord_r[:k5].sum() / r.sum()) if r.sum() > 0 else None
    out["beste_5_prozent_trades"] = int(k5)
    monate = {}
    for mk in np.unique(monat):
        monate[int(mk)] = float(r[monat == mk].sum())
    ms = sorted(monate.items(), key=lambda kv: kv[1])
    out["schlechtester_monat"] = {"monat": ms[0][0], "summe_r": ms[0][1]}
    out["bester_monat"] = {"monat": ms[-1][0], "summe_r": ms[-1][1]}
    out["monate_gesamt"] = len(monate)
    out["monate_positiv"] = int(sum(1 for v in monate.values() if v > 0))
    out["monate_negativ"] = int(sum(1 for v in monate.values() if v < 0))
    out["summe_r_je_monat"] = {str(k): v for k, v in sorted(monate.items())}
    out["ohne_bestes_jahr_e_r"] = None
    # Beitrag je Jahr zur Gesamtsumme
    out["summe_r_je_jahr"] = {str(int(y)): float(r[jahr == y].sum()) for y in np.unique(jahr)}
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------
# T7: Unsicherheit mit Zeitabhängigkeit
# ---------------------------------------------------------------------------------------------------------------------------------------

def wochen_reihe(r: np.ndarray, signal_ms: np.ndarray, von_ms: int, bis_ms: int) -> np.ndarray:
    w0 = int(kz.woche_schluessel(np.array([von_ms]))[0])
    w1 = int(kz.woche_schluessel(np.array([bis_ms - 1]))[0])
    reihe = np.zeros(w1 - w0 + 1)
    for w, x in zip(kz.woche_schluessel(signal_ms), r):
        reihe[int(w) - w0] += x
    return reihe


def t7_unsicherheit(kerzen: dict, fund: dict, symbole: tuple[str, ...]) -> dict:
    tr = nach_abschnitt(lauf(kerzen, fund, symbole, V_C1, K1))
    out: dict = {}
    grenzen = {"train": (0, TRAIN_ENDE_MS), "validation": (TRAIN_ENDE_MS, VALID_ENDE_MS), "pooled": (0, VALID_ENDE_MS)}
    erster = min(int(kerzen[s].t[0]) for s in symbole)
    for sec in ("train", "validation", "pooled"):
        a = arrays(tr[sec])
        bs = kz.monatsblock_bootstrap(a["r"], a["signal_ms"], ziehungen=ZIEHUNGEN_BOOTSTRAP, seed=SEED, exit_ms=a["exit_ms"])
        von = max(erster, grenzen[sec][0])
        wochenreihe = wochen_reihe(a["r"], a["signal_ms"], von, grenzen[sec][1])
        t_nw, se = kz.newey_west_t(wochenreihe, lags=4)
        out[sec] = {"kennzahlen": kz.kpi(a["r"], a["signal_ms"], a["exit_ms"], stop_anteil=a["stop_anteil"], kosten_r=a["kosten_r"], funding_r=a["funding_r"], brutto_r=a["brutto_r"],
                                         seite=a["seite"], symbol=a["symbol"], grund=a["grund"], haltedauer_h=a["haltedauer_h"]),
                    "monatsblock_bootstrap": bs, "woechentlich_newey_west": {"wochen": int(len(wochenreihe)), "mittel_r_je_woche": float(wochenreihe.mean()), "t": t_nw, "se": se, "verzoegerungen": 4}}
    out["g6_bestanden"] = bool(out["pooled"]["monatsblock_bootstrap"]["e_r"]["ci95"][0] > 0)
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------
# T8: Mehrfachtest (eigene DSR-Rechnung)
# ---------------------------------------------------------------------------------------------------------------------------------------

def t8_dsr(kerzen: dict, fund: dict, symbole: tuple[str, ...], raster: dict | None = None) -> dict:
    out: dict = {"hinweis": "Sharpe je Trade (Mittel / Populations-SD); Nullfall-Varianz 1/(n-1) wie im Laborbericht; Gegenprobe mit empirischer Streuung der Raster-Sharpes (T4)"}
    for kname in ("K0", "K1"):
        tr = nach_abschnitt(lauf(kerzen, fund, symbole, V_C1, KOSTEN[kname]))
        res = {}
        for sec in ("train", "validation", "pooled"):
            r = arrays(tr[sec])["r"]
            res[sec] = {"momente": kz.momente(r), "nullfall": {str(n): kz.deflated_sharpe(r, n) for n in DSR_VERSUCHE}}
            if raster is not None and kname == "K1":
                sh = np.array([z[sec]["sharpe"] for z in raster["zellen_liste"] if z[sec]["sharpe"] is not None])
                var = float(np.var(sh, ddof=1))
                res[sec]["raster_varianz"] = {"zellen": int(len(sh)), "varianz": var, "sd": float(np.sqrt(var)),
                                              "dsr_n600": kz.deflated_sharpe(r, 600, var), "dsr_n64": kz.deflated_sharpe(r, 64, var)}
        out[kname] = res
    out["g7_bestanden"] = bool(all((out["K1"][sec]["nullfall"]["64"]["dsr"] or 0) >= 0.95 for sec in ("train", "validation")))
    out["g7_definition"] = "DSR (N=64, Nullfall-Varianz, Kosten K1) mindestens 0,95 in Training UND Validierung (strenge Lesart des Protokolltexts); gepoolt zusätzlich berichtet"
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------
# T9: Regime und Teilmengen (nur Bericht)
# ---------------------------------------------------------------------------------------------------------------------------------------

def btc_volatilitaet(kerzen: dict) -> tuple[np.ndarray, np.ndarray]:
    """Annualisierte 30-Tage-Schwankung der BTC-4h-Renditen (180 Kerzen) zum Schluss jeder Kerze; (Zeiten, Werte)."""
    k = kerzen["BTCUSDT"]
    ret = np.diff(np.log(k.c))
    fenster = 180
    vol = np.full(len(k.c), np.nan)
    if len(ret) >= fenster:
        win = np.lib.stride_tricks.sliding_window_view(ret, fenster)
        vol[fenster:] = win.std(axis=1, ddof=1) * np.sqrt(6 * 365)
    return k.t, vol


def t9_regime(kerzen: dict, fund: dict, symbole: tuple[str, ...]) -> dict:
    tr = nach_abschnitt(lauf(kerzen, fund, symbole, V_C1, K1))["pooled"]
    a = arrays(tr)
    r = a["r"]
    zeiten, vol = btc_volatilitaet(kerzen)
    idx = np.searchsorted(zeiten, a["signal_ms"])
    v_tr = vol[idx]
    # Terzil-Grenzen aus den Kerzen des Trainings (keine Information aus der Validierung)
    ref = vol[(zeiten < TRAIN_ENDE_MS) & ~np.isnan(vol)]
    q1, q2 = float(np.percentile(ref, 100 / 3)), float(np.percentile(ref, 200 / 3))
    terzil = np.where(np.isnan(v_tr), -1, np.where(v_tr <= q1, 0, np.where(v_tr <= q2, 1, 2)))

    def gruppe(m):
        return {"n": int(m.sum()), "e_r": float(r[m].mean()) if m.any() else None, "summe_r": float(r[m].sum()) if m.any() else 0.0,
                "trefferquote": float((r[m] > 0).mean()) if m.any() else None}
    monat = kz.monat_schluessel(a["signal_ms"])
    jahr = monat // 100
    halbjahr = jahr * 10 + np.where((monat % 100) <= 6, 1, 2)
    out: dict = {"terzil_grenzen_vol_annualisiert": [q1, q2],
                 "je_jahr": {str(int(y)): gruppe(jahr == y) for y in np.unique(jahr)},
                 "je_halbjahr": {f"{int(h) // 10}H{int(h) % 10}": gruppe(halbjahr == h) for h in np.unique(halbjahr)},
                 "je_instrument": {str(s): gruppe(a["symbol"] == s) for s in np.unique(a["symbol"])},
                 "je_seite": {"long": gruppe(a["seite"] == 1), "short": gruppe(a["seite"] == -1)},
                 "je_volatilitaets_terzil": {n: gruppe(terzil == i) for i, n in enumerate(("niedrig", "mittel", "hoch"))},
                 "je_ausstiegsgrund": {str(g): gruppe(a["grund"] == g) for g in np.unique(a["grund"])}}
    # gleitender 6-Monats-E[R] (nach Signalmonat), Fenster = die letzten 6 Kalendermonate
    mon = np.unique(monat)
    gleitend = {}
    for i, mk in enumerate(mon):
        fenster = mon[max(0, i - 5): i + 1]
        m = np.isin(monat, fenster)
        gleitend[int(mk)] = {"n": int(m.sum()), "e_r": float(r[m].mean())}
    out["gleitend_6_monate"] = gleitend
    out["gleitend_min_e_r"] = float(min(g["e_r"] for g in gleitend.values() if g["n"] >= 10))
    out["gleitend_anteil_negativ"] = float(np.mean([g["e_r"] < 0 for g in gleitend.values() if g["n"] >= 10]))
    return out
