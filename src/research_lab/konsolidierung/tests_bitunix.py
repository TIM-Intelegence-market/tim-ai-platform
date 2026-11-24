"""T13: Übertragbarkeit der Regel C1 auf Bitunix (Kerzen, Kontraktgrenzen, Buch-Momentaufnahme, offene Voraussetzungen).

Nur öffentliche Bitunix-Daten (ohne Schlüssel), am 2026-11-16 vom Mac geholt. Unbekannte Größen (Gebühren, Funding-Historie, Ausführung)
bleiben offene Voraussetzungen und werden nie als null gesetzt.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.research_lab.konsolidierung.bitunix_abgleich import abgleich, beschneide, lade_bitunix
from src.research_lab.konsolidierung.s7b_nachrechnung import SYMBOLE, abschnitt, simuliere
from src.research_lab.konsolidierung.tests_trend import K1, KANDIDATEN, V_C1, kurz, lauf, nach_abschnitt

KONTRAKTSTART_MS = 1_719_403_200_000   # 2024-06-26T12:00Z (launchTime laut trading_pairs)
KAPITAL_STUFEN = (1_000.0, 5_000.0, 10_000.0)
RISIKO = 0.01


def t13_kerzen(kerzen: dict, fund: dict, bitunix_ordner: str, symbole: tuple[str, ...] = SYMBOLE) -> dict:
    sym = tuple(s for s in SYMBOLE if s in symbole)
    bx = {s: lade_bitunix(f"{bitunix_ordner}/bitunix_{s}_4h.json", s) for s in sym}
    start = int(min(bx[s].t[0] for s in sym))
    bn = {s: beschneide(kerzen[s], start) for s in sym}
    tr_n = simuliere(bn, fund, V_C1, K1, portfolio=True, reihenfolge=sym)
    tr_x = simuliere(bx, fund, V_C1, K1, portfolio=True, reihenfolge=sym)
    kn = {(t.symbol, t.signal_zeit): t for t in tr_n}
    kx = {(t.symbol, t.signal_zeit): t for t in tr_x}
    gem = set(kn) & set(kx)
    d = np.array([abs(kn[c].r - kx[c].r) for c in gem]) if gem else np.array([])
    out = {"fenster_ab_ms": start, "fenster_ab_utc": str(np.datetime64(start, "ms"))[:16] + "Z",
           "binance": kurz(tr_n), "bitunix": kurz(tr_x),
           "differenz_e_r": float(np.mean([t.r for t in tr_x]) - np.mean([t.r for t in tr_n])),
           "gemeinsame_signale": len(gem), "nur_binance": len(set(kn) - set(kx)), "nur_bitunix": len(set(kx) - set(kn)),
           "max_abw_r_gemeinsam": float(d.max()) if len(d) else None, "mittel_abw_r_gemeinsam": float(d.mean()) if len(d) else None,
           "anteil_gleicher_ausstiegsgrund": float(np.mean([kn[c].grund == kx[c].grund for c in gem])) if gem else None,
           "kerzenvergleich": {s: abgleich(kerzen[s], bx[s]) for s in sym}}
    # nach Kontraktstart (nur kurzer Abschnitt, wegen Kerzenmenge nur Bericht)
    for name, tr in (("binance", tr_n), ("bitunix", tr_x)):
        spaet = [t for t in tr if t.signal_zeit >= KONTRAKTSTART_MS]
        out[f"{name}_nach_kontraktstart"] = {"n": len(spaet), "e_r": float(np.mean([t.r for t in spaet])) if spaet else None}
    out["g11_kerzen_bestanden"] = bool(abs(out["differenz_e_r"]) < 0.05)
    return out


def t13_kontrakt(kerzen: dict, fund: dict, ordner: str) -> dict:
    """Mindestmenge und Tick bei 1 % Risiko für Kapitalstufen; benutzt die Trades von C1 (K1)."""
    pairs = {x["symbol"]: x for x in json.loads(Path(f"{ordner}/trading_pairs.json").read_text())["data"]}
    trades = nach_abschnitt(lauf(kerzen, fund, KANDIDATEN["C1"], V_C1, K1))["pooled"]
    out: dict = {"kontrakte": {s: {k: pairs[s][k] for k in ("minTradeVolume", "basePrecision", "quotePrecision", "maxLeverage", "maxMarketOrderVolume", "symbolStatus", "launchTime")}
                               for s in SYMBOLE}, "kapital": {}}
    for kap in KAPITAL_STUFEN:
        je = {}
        for s in SYMBOLE:
            rows = [t for t in trades if t.symbol == s]
            if not rows:
                continue
            mv = float(pairs[s]["minTradeVolume"])
            bp = int(pairs[s]["basePrecision"])
            qp = int(pairs[s]["quotePrecision"])
            q_soll = np.array([RISIKO * kap / abs(t.einstieg - t.stop) for t in rows])
            q_ist = np.floor(q_soll * 10 ** bp) / 10 ** bp
            ok = q_ist >= mv
            risiko_ist = q_ist * np.array([abs(t.einstieg - t.stop) for t in rows]) / kap
            hebel = q_ist * np.array([t.einstieg for t in rows]) / kap
            tick = 10.0 ** (-qp)
            abw_tick = np.array([tick / abs(t.einstieg - t.stop) for t in rows])
            abw_tick_2024 = np.array([tick / abs(t.einstieg - t.stop) for t in rows if t.signal_zeit >= 1_704_067_200_000])  # ab 2024-01-01 (heutige Preisregion)
            je[s] = {"trades": len(rows), "anteil_mindestmenge_erfuellt": float(ok.mean()), "mittlere_menge": float(q_ist.mean()), "kleinste_menge_soll": float(q_soll.min()),
                     "risiko_ist_median_prozent": float(np.median(risiko_ist[ok]) * 100) if ok.any() else None,
                     "risiko_abweichung_durch_mengenrundung_max_prozent": float(((RISIKO - risiko_ist[ok]) / RISIKO).max() * 100) if ok.any() else None,
                     "hebel_median": float(np.median(hebel)), "hebel_max": float(hebel.max()), "tick_relativ_zum_stop_max": float(abw_tick.max()),
                     "tick_relativ_zum_stop_max_ab_2024": float(abw_tick_2024.max()) if len(abw_tick_2024) else None}
        out["kapital"][str(int(kap))] = je
    out["g11_kontrakt_bestanden"] = bool(all(v["anteil_mindestmenge_erfuellt"] >= 0.99 for v in out["kapital"]["1000"].values()))
    return out


def t13_gesamt(kerzen: dict, fund: dict, ordner: str, tiefe_json: str) -> dict:
    out = {"kerzen": t13_kerzen(kerzen, fund, ordner), "kerzen_c3": t13_kerzen(kerzen, fund, ordner, KANDIDATEN["C3"]), "kontrakt": t13_kontrakt(kerzen, fund, ordner),
           "buch_momentaufnahme": json.loads(Path(tiefe_json).read_text())}
    out["funding_momentaufnahme"] = {s: json.loads(Path(f"{ordner}/funding_rate_{s}.json").read_text())["data"] for s in SYMBOLE}
    out["g11_bestanden"] = bool(out["kerzen"]["g11_kerzen_bestanden"] and out["kontrakt"]["g11_kontrakt_bestanden"])
    out["g11_bestanden_c3"] = bool(out["kerzen_c3"]["g11_kerzen_bestanden"] and out["kontrakt"]["g11_kontrakt_bestanden"])
    out["offene_voraussetzungen"] = [
        "Gebühren: VIP0 taker 0,06 % / maker 0,02 % stammen von Uzi (10.11.2026), im Code FEES_VERIFIED = False; keine Kontoprüfung möglich (kein Schlüssel)",
        "Funding-Historie: Bitunix bietet keine öffentliche Historie in diesen Daten; Binance dient als Stellvertreter. Aktuelle Momentaufnahme: Intervall 8 h, Einheit der Rate in der API unklar (Dezimal oder Prozent)",
        "Ausführung: Spread und Marktorder-Schlupf nur aus einer ca. 90-Sekunden-Momentaufnahme (ruhiger Markt); keine Messung zu Nachrichtenzeiten, Nacht, Wochenende, Stop-Marktorder bei Spitzen",
        "Kerzen vor dem Kontraktstart (2024-06-26) sind vermutlich Index-Kerzen und keine gehandelten Preise (ANNAHME)",
        "Orderarten, Latenz und Stop-Verhalten auf Bitunix (Stop-Market, Reduce-only, Teilfüllung) nicht geprüft",
    ]
    return out
