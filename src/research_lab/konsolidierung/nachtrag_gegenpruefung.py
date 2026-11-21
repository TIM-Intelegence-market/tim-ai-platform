"""Nachtrag der Gegenprüfung (nach dem Einfrieren von Protokoll 1.0; nur Diagnose, keine Kriterien, ändert keine Stufe).

Zwei unabhängige Prüfer (nur lesend) haben Abweichungen zwischen Protokolltext und Code sowie offene Fragen gemeldet. Dieser Nachtrag misst, wie viel
sie ausmachen. Er ändert weder Code noch Ergebnisse des Laufs T1 bis T13 und wird in der Studie als Nachtrag ausgewiesen.

N1  Monatsblock-Bootstrap mit allen Kalendermonaten des Abschnitts (so beschreibt es der Protokolltext) statt nur der Monate mit Trades (so lief T7).
N2  Funding am Einstieg: Abrechnungen bis 10 ms nach dem Einstiegszeitpunkt werden nicht belastet (Laborkonvention und Lauf: sie werden belastet).
    Dafür wird der Quelltext von ``s7b_nachrechnung`` im Speicher an zwei Stellen geändert; die Datei bleibt unverändert.
N3  Aufteilung aus dem Auftrag (Training 2020 bis 2023, Validierung 2024) als zusätzliche Sicht auf dieselben Trades (Abschnittsregel 1.2 sinngemäß:
    Signal im Abschnitt, Ausstieg spätestens am Abschnittsende). Die Aufteilung des Protokolls (Training bis 2022, Validierung 2023 bis 2024) bleibt maßgeblich.
N4  T15 auf das Nominal: Stopp-Abstand je Trade aus den gespeicherten Kosten rückgerechnet (Gebühr 0,06 % je Seite), Zusammenhang mit R, Aufschlüsselung nach Jahr.

Aufruf (aus dem Repo-Wurzelordner)::

    python3 -m src.research_lab.konsolidierung.nachtrag_gegenpruefung <archiv-wurzel> <ergebnisordner>
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.research_lab.konsolidierung import kennzahlen as kz
from src.research_lab.konsolidierung import s7b_nachrechnung as S
from src.research_lab.konsolidierung import tests_trend as T
from src.research_lab.konsolidierung.lauf import git_stand

ENDE_2023_MS = 1_704_067_200_000   # 2024-01-01T00:00Z (exklusiv)
JITTER_MS = 10                     # Zeitstempel der Funding-Abrechnungen streuen um 0 bis 7 ms nach der vollen 8-Stunden-Marke
GEBUEHR_JE_SEITE = 0.0006          # K1 und K2


def monate_von_bis(von: int, bis: int) -> list[int]:
    """Kalendermonate als JJJJMM von ``von`` bis ``bis`` einschließlich."""
    out: list[int] = []
    j, m = divmod(von, 100)
    while j * 100 + m <= bis:
        out.append(j * 100 + m)
        m += 1
        if m == 13:
            j, m = j + 1, 1
    return out


def bootstrap_alle_monate(r: np.ndarray, signal_ms: np.ndarray, monate_alle: list[int], ziehungen: int = T.ZIEHUNGEN_BOOTSTRAP, seed: int = T.SEED,
                          exit_ms: np.ndarray | None = None) -> dict:
    """Wie ``kennzahlen.monatsblock_bootstrap``, aber die Ziehung läuft über alle Monate in ``monate_alle`` (auch solche ohne Trade)."""
    monate = kz.monat_schluessel(signal_ms)
    einzig = np.array(monate_alle)
    m = len(einzig)
    exit_ms = signal_ms if exit_ms is None else exit_ms
    sum_m = np.array([r[monate == k].sum() for k in einzig])
    n_m = np.array([(monate == k).sum() for k in einzig])
    seq_m = [r[monate == k][np.argsort(exit_ms[monate == k], kind="stable")] for k in einzig]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, m, size=(ziehungen, m))
    n_s = n_m[idx].sum(axis=1)
    e_r = np.where(n_s > 0, sum_m[idx].sum(axis=1) / np.maximum(n_s, 1), np.nan)
    dds = np.array([kz.max_drawdown(np.concatenate([seq_m[i] for i in idx[z]]))[0] for z in range(min(ziehungen, 2000))])
    q = lambda a, p: float(np.nanpercentile(a, p))
    return {"monate": int(m), "monate_mit_trade": int(len(np.unique(monate))), "e_r": {"ci95": [q(e_r, 2.5), q(e_r, 97.5)], "anteil_positiv": float(np.nanmean(e_r > 0))},
            "summe_r": {"ci95": [q(sum_m[idx].sum(axis=1), 2.5), q(sum_m[idx].sum(axis=1), 97.5)]},
            "max_drawdown_r": {"median": q(dds, 50), "p95": q(dds, 95), "ziehungen": int(len(dds))}}


def n1_bootstrap(kerzen: dict, fund: dict) -> dict:
    bereiche = {"train": monate_von_bis(202001, 202212), "validation": monate_von_bis(202301, 202412), "pooled": monate_von_bis(202001, 202412)}
    out: dict = {}
    for kand, sym in T.KANDIDATEN.items():
        tr = T.nach_abschnitt(T.lauf(kerzen, fund, sym, T.V_C1, T.K1))
        for sec, monate in bereiche.items():
            a = T.arrays(tr[sec])
            lauf_fassung = kz.monatsblock_bootstrap(a["r"], a["signal_ms"], ziehungen=T.ZIEHUNGEN_BOOTSTRAP, seed=T.SEED, exit_ms=a["exit_ms"])
            alle = bootstrap_alle_monate(a["r"], a["signal_ms"], monate, exit_ms=a["exit_ms"])
            out[f"{kand}_{sec}"] = {"nur_monate_mit_trade_lauf": {"monate": lauf_fassung["monate"], "e_r": lauf_fassung["e_r"], "summe_r": lauf_fassung["summe_r"],
                                                                 "max_drawdown_r": lauf_fassung["max_drawdown_r"]},
                                    "alle_monate": alle}
    return out


def _streng_modul():
    """``s7b_nachrechnung`` mit geänderter Funding-Zuordnung am Einstieg (Abrechnungen bis 10 ms nach dem Einstiegszeitpunkt zählen nicht)."""
    pfad = Path(S.__file__)
    q = pfad.read_text(encoding="utf-8")
    a1 = 'a = int(np.searchsorted(fund.t, q["einstieg_zeit"], side="left"))'
    a2 = 'a = int(np.searchsorted(ft, von, side="left"))'
    if a1 not in q or a2 not in q:
        raise RuntimeError("Quelltext von s7b_nachrechnung weicht ab: Nachtrag N2 nicht anwendbar")
    q = q.replace(a1, f'a = int(np.searchsorted(fund.t, q["einstieg_zeit"] + {JITTER_MS}, side="left"))').replace(a2, f'a = int(np.searchsorted(ft, von + {JITTER_MS}, side="left"))')
    name = "src.research_lab.konsolidierung._s7b_streng"
    spec = importlib.util.spec_from_loader(name, loader=None)
    m = importlib.util.module_from_spec(spec)
    m.__package__ = "src.research_lab.konsolidierung"
    sys.modules[name] = m          # nötig für die Verarbeitung der Datenklassen
    exec(compile(q, "s7b_nachrechnung_streng", "exec"), m.__dict__)
    return m


def _e_r(trades: list) -> dict:
    r = np.array([t.r for t in trades], dtype=float)
    return {"n": int(len(r)), "e_r": float(r.mean()) if len(r) else None}


def n2_funding_einstieg(kerzen: dict, fund: dict) -> dict:
    streng = _streng_modul()
    out: dict = {"regel": f"Abrechnungen bis {JITTER_MS} ms nach dem Einstiegszeitpunkt werden nicht belastet (Lauf: belastet)"}
    for kand, sym in T.KANDIDATEN.items():
        sym = T.reihenfolge_von(sym)
        for kname in ("K1", "K2"):
            roh = {"lauf": S.simuliere({s: kerzen[s] for s in sym}, fund, T.V_C1, T.KOSTEN[kname], portfolio=True, reihenfolge=sym),
                   "streng": streng.simuliere({s: kerzen[s] for s in sym}, fund, T.V_C1, T.KOSTEN[kname], portfolio=True, reihenfolge=sym)}
            for variante, tr in roh.items():
                nach = T.nach_abschnitt(tr)
                for sec in ("train", "validation", "pooled"):
                    out.setdefault(f"{kand}_{kname}_{sec}", {})[variante] = _e_r(nach[sec])
    tr = S.simuliere({s: kerzen[s] for s in T.reihenfolge_von(T.KANDIDATEN["C1"])}, fund, T.V_C1, T.KOSTEN["K2"], portfolio=True, reihenfolge=T.reihenfolge_von(T.KANDIDATEN["C1"]))
    gleich = sum(1 for t in tr if fund[t.symbol] is not None and np.any((fund[t.symbol].t >= t.einstieg_zeit) & (fund[t.symbol].t <= t.einstieg_zeit + JITTER_MS)))
    out["c1_k2_einstiege_mit_abrechnung_im_fenster"] = {"anzahl": int(gleich), "von": int(len(tr))}
    return out


def n3_aufteilung_auftrag(kerzen: dict, fund: dict) -> dict:
    out: dict = {"regel": "Training: Signal vor 2024-01-01, Ausstieg spätestens 2024-01-01; Validierung: Signal 2024, Ausstieg spätestens 2025-01-01 (gleiche Simulation, andere Grenze)"}
    for kand, sym in T.KANDIDATEN.items():
        for kname in ("K1", "K2"):
            tr = T.lauf(kerzen, fund, sym, T.V_C1, T.KOSTEN[kname])
            teile: dict[str, list] = {"training_2020_2023": [], "validierung_2024": []}
            for t in tr:
                if t.signal_zeit < ENDE_2023_MS and t.ausstieg_zeit <= ENDE_2023_MS:
                    teile["training_2020_2023"].append(t)
                elif ENDE_2023_MS <= t.signal_zeit < S.VALID_ENDE_MS and t.ausstieg_zeit <= S.VALID_ENDE_MS:
                    teile["validierung_2024"].append(t)
            for name, lst in teile.items():
                r = np.array([t.r for t in lst], dtype=float)
                out.setdefault(f"{kand}_{kname}", {})[name] = {"n": int(len(r)), "e_r": float(r.mean()), "summe_r": float(r.sum()),
                                                              "trefferquote": float((r > 0).mean())}
    return out


def n4_t15_nominal(t15: dict) -> dict:
    """``t15``: Inhalt von ``t15_ausserhalb.json`` (Schlüssel ``ergebnis``). Der Stopp-Abstand wird als Gebühr je Seite geteilt durch die gespeicherten Kosten in R
    zurückgerechnet (Kosten in R = Gebühr × (Einstieg + Ausstieg) / Risiko, Ausstieg ≈ Einstieg; Genauigkeit etwa 10 %)."""
    tr = t15["trades_k2"]
    r = np.array([x["r"] for x in tr], dtype=float)
    kosten = np.array([x["kosten_r"] for x in tr], dtype=float)
    stop = 2 * GEBUEHR_JE_SEITE / kosten
    jahr = np.array([datetime.fromtimestamp(x["einstieg_ms"] / 1000, timezone.utc).year for x in tr])
    kenn = t15["primaer_k2"]["kennzahlen"]
    out = {"n": int(len(r)), "e_r": float(r.mean()), "mittlerer_stop_abstand_prozent_rueckgerechnet": float(stop.mean() * 100),
           "mittlerer_stop_abstand_prozent_gespeichert": kenn["mittlerer_stop_abstand_prozent"],
           "netto_bp_rueckgerechnet": float((r * stop).mean() * 1e4), "netto_bp_gespeichert": kenn["netto_bp_je_trade_auf_nominal"],
           "produkt_der_mittel_bp": float(r.mean() * stop.mean() * 1e4), "korrelation_r_stop": float(np.corrcoef(r, stop)[0, 1]),
           "je_jahr": {}}
    for j in sorted(set(jahr.tolist())):
        m = jahr == j
        out["je_jahr"][str(j)] = {"n": int(m.sum()), "e_r": float(r[m].mean()), "mittlerer_stop_abstand_prozent": float(stop[m].mean() * 100), "netto_bp": float((r[m] * stop[m]).mean() * 1e4)}
    for name, m in (("stop_unter_4_prozent", stop < 0.04), ("stop_ab_4_prozent", stop >= 0.04)):
        out[name] = {"n": int(m.sum()), "e_r": float(r[m].mean()), "summe_r": float(r[m].sum())}
    return out


def main(argv: list[str]) -> int:
    wurzel, ausgabe = argv[1], Path(argv[2])
    kerzen, fund = T.daten_laden(wurzel)
    t15 = T.json.loads((ausgabe / "t15_ausserhalb.json").read_text(encoding="utf-8"))["ergebnis"]
    commit, schmutzig = git_stand()
    ergebnis = {"N1": n1_bootstrap(kerzen, fund), "N2": n2_funding_einstieg(kerzen, fund), "N3": n3_aufteilung_auftrag(kerzen, fund), "N4": n4_t15_nominal(t15)}
    m = T.meta("Nachtrag Gegenprüfung", {"kandidaten": list(T.KANDIDATEN), "kosten": ["K1", "K2"], "ziehungen_bootstrap": T.ZIEHUNGEN_BOOTSTRAP, "seed": T.SEED},
               f"python3 -m src.research_lab.konsolidierung.nachtrag_gegenpruefung {wurzel} {ausgabe}",
               "Signale 2020-01 bis 2024-12; T15-Handelsliste 2017-08 bis 2019-12; Holdout nicht geladen", "abgeschlossen (Diagnose, keine Kriterien)",
               ["nach dem Einfrieren von Protokoll 1.0 gerechnet; ändert keine Stufe und kein Kriterium",
                "N2 ändert den Quelltext nur im Speicher; N4 ist eine Rückrechnung (Genauigkeit etwa 10 %), keine neue Simulation von T15"])
    m.update({"code_commit": commit, "code_unsauber": schmutzig})
    T.schreibe(ausgabe / "nachtrag_gegenpruefung.json", {"meta": m, "ergebnis": ergebnis})
    print(T.json.dumps({k: list(v)[:3] if isinstance(v, dict) else v for k, v in ergebnis.items()}, ensure_ascii=False)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
