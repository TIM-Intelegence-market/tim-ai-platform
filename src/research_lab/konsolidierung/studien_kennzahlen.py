"""Gemeinsame Kennzahlenbasis für alle Studien mit gespeicherter Tradeliste (Prüftiefe B: Kennzahlen aus der Rohliste nachgerechnet).

Liest die Tradelisten der Trainingsläufe (PS5-Ergebnisdateien, SHA-256 im Ergebnis) und rechnet sie mit derselben Funktion ``kennzahlen.kpi``
wie die eigene Nachrechnung von S7/S7b. Es werden keine Werte ersetzt oder gemittelt; fehlende Angaben bleiben ``None``.
Die Listen enthalten nur das, was die jeweilige Studie gespeichert hat (Training). Validierung/Holdout liegen nicht vor.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from src.research_lab.konsolidierung import kennzahlen as kz

# im Logbuch berichtete Kerngrößen zum Abgleich (n, Netto-E[R]); Toleranz 0,006 R wegen Rundung im Logbuch
BERICHTET = {
    "S34": {"S34": (53, -1.21)},
    "S35a": {"E-break-15m": (None, -0.25)},
    "S36": {"SFP-alle-M": (425, -0.05), "SFP-alle-L": (438, -0.09)},
    "S38": {"T-045": (191, 0.09), "T-060": (584, 0.05), "T-075": (982, 0.02), "T-alle": (2399, 0.005)},
    "OF2": {"OF2": (56, 0.2688)},
}


def _arr(trades: list[dict], zeit: str) -> dict:
    return {
        "r": np.array([t["net_r"] for t in trades], dtype=float),
        "signal_ms": np.array([t.get(zeit) or t["entry_ms"] for t in trades], dtype=np.int64),
        "exit_ms": np.array([t["exit_ms"] for t in trades], dtype=np.int64),
        "entry_ms": np.array([t["entry_ms"] for t in trades], dtype=np.int64),
        "brutto": np.array([t["gross_r"] for t in trades], dtype=float),
        "kosten": np.array([t["gross_r"] - t["net_r"] for t in trades], dtype=float),
        "stop": np.array([t["stop_frac"] for t in trades], dtype=float),
        "seite": np.array([t["direction"] for t in trades]),
        "symbol": np.array([t["symbol"] for t in trades]),
        "grund": np.array([str(t.get("reason") or t.get("how")).lower() for t in trades]),
    }


def kpi_liste(trades: list[dict], name: str, studie: str) -> dict:
    if not trades:
        return {"n": 0}
    a = _arr(trades, "signal_ms")
    k = kz.kpi(a["r"], a["signal_ms"], a["exit_ms"], stop_anteil=a["stop"], kosten_r=a["kosten"], brutto_r=a["brutto"], seite=a["seite"], symbol=a["symbol"], grund=a["grund"],
               haltedauer_h=(a["exit_ms"] - a["entry_ms"]) / 3_600_000.0)
    if len(a["r"]) >= 20:
        k["monatsblock_bootstrap"] = kz.monatsblock_bootstrap(a["r"], a["signal_ms"], exit_ms=a["exit_ms"])
    m = kz.momente(a["r"])
    k["dsr_n64_nullfall"] = kz.deflated_sharpe(a["r"], 64)["dsr"] if len(a["r"]) > 3 and np.isfinite(m["sharpe"]) else None
    k["zu_wenige_trades_unter_30"] = bool(len(a["r"]) < 30)
    ber = BERICHTET.get(studie, {}).get(name)
    if ber:
        n_ber, e_ber = ber
        k["abgleich_logbuch"] = {"berichtet_n": n_ber, "berichtet_netto_e_r": e_ber, "nachgerechnet_n": int(len(a["r"])), "nachgerechnet_netto_e_r": float(a["r"].mean()),
                                 "stimmt": bool((n_ber is None or n_ber == len(a["r"])) and abs(a["r"].mean() - e_ber) <= 0.006)}
    return k


def lauf(ps5: str, repo: str) -> dict:
    out: dict = {"quellen": {}, "studien": {}}

    def sha(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    p = Path(ps5) / "s34/s34_train_2026-11-14.json"
    out["quellen"]["S34"] = {"datei": "s34_train_2026-11-14.json", "sha256": sha(p)}
    out["studien"]["S34"] = {"S34": kpi_liste(json.loads(p.read_text())["_trades"], "S34", "S34")}
    p = Path(ps5) / "s35a/s35a_train_2026-11-14.trades.json"
    out["quellen"]["S35a"] = {"datei": p.name, "sha256": sha(p)}
    out["studien"]["S35a"] = {n: kpi_liste(t, n, "S35a") for n, t in json.loads(p.read_text()).items()}
    p = Path(ps5) / "s36/train.trades.json"
    out["quellen"]["S36"] = {"datei": p.name, "sha256": sha(p)}
    s36 = json.loads(p.read_text())
    for v in s36.values():
        for t in v:  # Kosten- und Funding-Anteil getrennt gespeichert; gross_r - net_r = cost_r + fund_r (zur Probe)
            assert abs((t["gross_r"] - t["net_r"]) - (t["cost_r"] + t["fund_r"])) < 1e-9
    out["studien"]["S36"] = {n: kpi_liste(t, n, "S36") for n, t in s36.items()}
    p = Path(ps5) / "s37/s37_train_2026-11-15.trades.json"
    out["quellen"]["S37"] = {"datei": p.name, "sha256": sha(p)}
    out["studien"]["S37"] = {n: kpi_liste(t, n, "S37") for n, t in json.loads(p.read_text()).items()}
    p = Path(ps5) / "s38/s38_train_2026-11-15.trades.json"
    out["quellen"]["S38"] = {"datei": p.name, "sha256": sha(p)}
    out["studien"]["S38"] = {n: kpi_liste(t, n, "S38") for n, t in json.loads(p.read_text()).items()}
    p = Path(repo) / "docs/research_lab/reports/bitunix/of2_training_of_trades_aa853e1.json"
    out["quellen"]["OF2"] = {"datei": p.name, "sha256": sha(p)}
    of2 = json.loads(p.read_text())["of_trades"]
    tr = [{"symbol": "BTCUSDT", "direction": 0, "entry_ms": int(t["day"]) * 86_400_000, "signal_ms": int(t["day"]) * 86_400_000, "exit_ms": int(t["day"]) * 86_400_000 + 3_600_000,
           "gross_r": t["net_r"], "net_r": t["net_r"], "stop_frac": t["stop_dist"], "reason": t["reason"]} for t in of2]
    k = kpi_liste(tr, "OF2", "OF2")
    for feld in ("kosten_r_je_trade", "brutto_r_je_trade", "kosten_bp_je_trade_auf_nominal", "mittlere_haltedauer_h", "zeit_im_markt_anteil", "je_seite", "je_grund_ungenutzt"):
        k.pop(feld, None)  # in der Liste nicht enthalten bzw. erfunden (nur Tag, Netto-R, Stopp-Abstand, Grund)
    k["hinweis"] = "Tradeliste enthält nur Tag, Netto-R und Stopp-Abstand: kein Brutto/Kosten, keine Uhrzeit, keine Seite; Haltedauer, Marktbeteiligung und Rückgang nur tagesgenau"
    out["studien"]["OF2"] = {"OF2": k}
    return out


if __name__ == "__main__":
    import sys
    erg = lauf(sys.argv[1], sys.argv[2])
    Path(sys.argv[3]).write_text(json.dumps(erg, indent=1, ensure_ascii=False, default=lambda o: float(o) if isinstance(o, np.floating) else int(o) if isinstance(o, np.integer) else str(o)), encoding="utf-8")
    for s, vs in erg["studien"].items():
        for n, k in vs.items():
            print(s, n, "n", k.get("n"), "E[R]", round(k["e_r"], 4) if k.get("n") else None, "brutto", round(k.get("brutto_r_je_trade") or 0, 3), "kosten", round(k.get("kosten_r_je_trade") or 0, 3),
                  "abgleich", (k.get("abgleich_logbuch") or {}).get("stimmt"))
