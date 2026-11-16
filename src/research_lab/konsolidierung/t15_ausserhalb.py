"""T15: Prüfung der Trendregel C3 außerhalb des Entwicklungszeitraums (Binance Spot, BTCUSDT und ETHUSDT, 4h, 2017-08 bis 2019-12).

Grundlage: ``docs/research_lab/konsolidierung/PROTOKOLL_KONSOLIDIERUNG_T15.md`` (Version 1.1-T15, vor dem Laden der Daten eingefroren).
Das Zusatzprotokoll ändert keines der Kriterien G1 bis G11, CG1, CG2 und keine Urteilsstufe.

Zwei Schritte, getrennt und nacheinander:

1. ``audit``  Datenbericht (Abschnitt 4 des Zusatzprotokolls) -> ``ergebnisse/t15_datenaudit.json``. Der Bericht wird festgehalten
   (Commit), bevor der Handelslauf startet. Fehlt mehr als 5 % der erwarteten Kerzen eines Symbols, weicht eine Prüfsumme ab oder
   fehlt ein Monat, steht ``abbruch = true`` darin und der Handelslauf verweigert den Start.
2. ``lauf``   der einzige Handelslauf (Abschnitte 3 und 5) -> ``ergebnisse/t15_ausserhalb.json``. Er verweigert den Start, wenn der
   Datenbericht nicht festgehalten ist, wenn Code oder Zusatzprotokoll nicht festgehalten sind, wenn die Daten nicht dem
   Datenbericht entsprechen oder wenn schon ein Ergebnis vorliegt (genau ein Lauf).

Aufruf (aus dem Repo-Wurzelordner)::

    python3 -m src.research_lab.konsolidierung.t15_ausserhalb audit <t15-wurzel> <manifest_t15.json>
    python3 -m src.research_lab.konsolidierung.t15_ausserhalb lauf <t15-wurzel> <futures-wurzel 2020-2024>

Es wird derselbe Code wie in T1 bis T13 benutzt (``s7b_nachrechnung``, ``kennzahlen``, ``tests_trend``). Kein Parameter, keine Kosten
und kein Kriterium wird nach Sicht auf das Ergebnis geändert.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.research_lab.konsolidierung import daten
from src.research_lab.konsolidierung import kennzahlen as kz
from src.research_lab.konsolidierung import tests_trend as T
from src.research_lab.konsolidierung.daten import MS_4H, Kerzen
from src.research_lab.konsolidierung.lauf import git_stand
from src.research_lab.konsolidierung.s7b_nachrechnung import Trade, bereite_vor, mit_signalen, simuliere

REPO = Path(__file__).resolve().parents[3]
KONSOLIDIERUNG = REPO / "docs/research_lab/konsolidierung"
ERGEBNISSE = KONSOLIDIERUNG / "ergebnisse"
PROTOKOLL_T15 = KONSOLIDIERUNG / "PROTOKOLL_KONSOLIDIERUNG_T15.md"
PROTOKOLL_1_0 = KONSOLIDIERUNG / "PROTOKOLL_KONSOLIDIERUNG.md"
PROTOKOLL_STAND = ERGEBNISSE / "PROTOKOLL_STAND.json"

SYMBOLE_T15 = ("BTCUSDT", "ETHUSDT")      # BTC vor ETH bei gleichem Zeitstempel (Abschnitt 2)
MARKT = "spot"
VON, BIS = "2017-08", "2019-12"
ERWARTETE_MONATE = 29                      # 2017-08 bis 2019-12
SCHWELLE_FEHLEND = 0.05                    # Abbruchregel (Abschnitt 4)
ENDE_RASTER_MS = 1_577_836_800_000 - MS_4H  # letzter 4h-Slot im Zeitraum: 2019-12-31T20:00Z
P_SCHWELLE = 0.05
ERWARTETE_TRADES = 195                     # Schätzung aus Abschnitt 7 des Zusatzprotokolls (nur zum Vergleich)

# Kosten (Abschnitt 3): K2 primär, K1 und K0 berichtet; Funding aus (für 2017 bis August 2019 gibt es keine Funding-Historie)
KOSTEN_T15 = {name: replace(T.KOSTEN[name], funding="aus") for name in ("K2", "K1", "K0")}

# Einordnung vorab (Abschnitt 6 des Zusatzprotokolls), wörtlich
EINORDNUNG = {
    "bestätigt": "P1 erfüllt: Die Trendregel zeigt auf BTC und ETH auch im Zeitraum 2017-08 bis 2019-12 eine positive Netto-Erwartung. "
                 "Das füllt die Evidenzstufe „außerhalb der Entwicklung bestätigt“ für diese beiden Coins, nicht für andere Märkte. "
                 "G7 (Mehrfachtest) und G8 (Übertragung auf andere Coins, nicht bestanden) bleiben bestehen; das Gesamturteil nach "
                 "Protokoll Abschnitt 5 ändert sich dadurch nicht.",
    "nicht bestätigt, Richtung positiv": "E[R] > 0, p > 0,05: kein Nachweis, aber auch keine Widerlegung. Die Aussagekraft ist begrenzt (Abschnitt 7 des Zusatzprotokolls).",
    "nicht bestätigt, Richtung negativ": "E[R] ≤ 0: Die Regel hat außerhalb des Entwicklungszeitraums keine positive Erwartung gezeigt. "
                                         "Das wird als Gegenbeleg in die Evidenzmatrix aufgenommen.",
    "nicht auswertbar": "Keine Trades oder Abbruchregel ausgelöst: T15 wird nicht ausgewertet, der Befund wird berichtet.",
}

GRENZEN = [
    "Spot statt Perpetual: Basis, Funding, Leerverkauf und Liquidationen sind nicht abgebildet; Leerverkäufe sind als Perp-Short simuliert",
    "Funding im primären Lauf aus (für 2017 bis August 2019 existiert keine Funding-Historie); Sensitivität P6 mit dem Funding-Kostenanteil 2020 bis 2024",
    "Nur BTC und ETH, beide im Nachhinein als Handelsobjekte gewählt (Überlebensauswahl), mit starker Wechselkorrelation",
    "Anderes Marktregime (Blase 2017, Rückgang 2018, Erholung 2019); Übertragung auf die Gegenwart nicht gesichert",
    "Allgemeines Vorwissen über die Preisgeschichte lässt sich nicht ausschließen; die Regelparameter wurden aber nicht auf diesen Daten bestimmt",
    "Aussagekraft begrenzt: etwa 195 erwartete Trades, Power etwa 62 % bei wahrer Erwartung +0,24 R (Abschnitt 7 des Zusatzprotokolls)",
    "Eine am Ende der Daten (2019-12-31) noch offene Position wird nicht gebucht (wie am Abschnittsende in T1 bis T13)",
]

GRENZEN_AUDIT = [
    "Prüfsummen belegen die Unverändertheit gegenüber dem Binance-Archiv, nicht die Richtigkeit der Kurse",
    "Eine zweite, unabhängige Kursquelle für 2017 bis 2019 wurde nicht herangezogen",
    "Lücken (zum Beispiel Wartungszeiten) werden gemeldet, nicht aufgefüllt; die Simulation setzt nach einer Lücke 200 Kerzen Vorlauf voraus",
]


class Vorbedingung(RuntimeError):
    """Eine Vorbedingung des Handelslaufs ist nicht erfüllt (Datenbericht, Festhalten, Daten, Einmaligkeit)."""


# ---------------------------------------------------------------------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------------------------------------------------------------------

def _sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _monat_grenzen(ym: str) -> tuple[int, int]:
    """[Beginn, Ende) des Kalendermonats ``JJJJ-MM`` in ms (UTC)."""
    y, m = int(ym[:4]), int(ym[5:7])
    a = datetime(y, m, 1, tzinfo=timezone.utc)
    b = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=timezone.utc)
    return int(a.timestamp() * 1000), int(b.timestamp() * 1000)


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def _festgehalten(pfad: Path) -> tuple[bool, str | None]:
    """(Datei ist versioniert und unverändert, Commit der letzten Änderung)."""
    try:
        rel = str(pfad.resolve().relative_to(REPO))
    except ValueError:
        return False, None
    versioniert = _git(["ls-files", "--error-unmatch", rel]).returncode == 0
    sauber = not _git(["status", "--porcelain", "--", rel]).stdout.strip()
    commit = _git(["log", "-1", "--format=%H", "--", rel]).stdout.strip() or None
    return bool(versioniert and sauber), commit


# ---------------------------------------------------------------------------------------------------------------------------------------
# Schritt 1: Datenbericht (Abschnitt 4)
# ---------------------------------------------------------------------------------------------------------------------------------------

def _datei_pruefen(wurzel: Path, symbol: str, ym: str, manifest: dict) -> dict:
    rel = f"{MARKT}/klines/{symbol}/4h/{symbol}-4h-{ym}.zip"
    pfad = wurzel / rel
    m = manifest.get(rel)
    e: dict = {"monat": ym, "datei": rel, "vorhanden": pfad.is_file(), "url": m.get("url") if m else None}
    if not pfad.is_file():
        e["pruefsumme_ok"] = False
        return e
    h = _sha256(pfad)
    e.update({"bytes": pfad.stat().st_size, "sha256": h, "sha256_manifest": m.get("sha256") if m else None,
              "sha256_checksum_datei": m.get("sha256_laut_checksum_datei") if m else None})
    e["pruefsumme_ok"] = bool(m) and h == m.get("sha256") and h == m.get("sha256_laut_checksum_datei")
    try:
        with zipfile.ZipFile(pfad) as z:
            namen = [n for n in z.namelist() if n.endswith(".csv")]
            e["csv_dateien"] = len(namen)
            if len(namen) != 1:
                raise ValueError("genau eine CSV erwartet")
            text = z.read(namen[0]).decode("utf-8")
        zeilen = daten._zeilen(text)
        t = np.array([int(float(r[0])) for r in zeilen], dtype=np.int64)
        a, b = _monat_grenzen(ym)
        erste_zelle = text.splitlines()[0].split(",")[0].strip().lstrip("-")
        e.update({"zeilen": int(len(zeilen)), "spalten": int(len(zeilen[0])) if zeilen else 0, "kopfzeile": not erste_zelle.isdigit(),
                  "erste_kerze": _iso(t.min()), "letzte_kerze": _iso(t.max()), "zeilen_ausserhalb_des_monats": int(((t < a) | (t >= b)).sum())})
    except Exception as ex:  # Lesefehler werden berichtet und lösen die Abbruchregel aus
        e["lesefehler"] = f"{type(ex).__name__}: {ex}"
    return e


def _kerzen_pruefen(k: Kerzen) -> dict:
    """Prüfung der zusammengeführten Kerzenreihe eines Symbols (Raster, Lücken, ungültige Kerzen, Vorlauf für Signale)."""
    t = k.t
    n = int(len(t))
    erste, letzte = int(t[0]), int(t[-1])
    erwartet = int((ENDE_RASTER_MS - erste) // MS_4H + 1)
    nominal_start = _monat_grenzen(VON)[0]
    erwartet_nominal = int((ENDE_RASTER_MS - nominal_start) // MS_4H + 1)
    d = np.diff(t)
    luecken = [{"nach_kerze": _iso(t[i]), "naechste_kerze": _iso(t[i + 1]), "fehlende_kerzen": int(d[i] // MS_4H - 1)} for i in np.nonzero(d > MS_4H)[0]]
    fehlend_in_luecken = int(sum(x["fehlende_kerzen"] for x in luecken))
    fehlend_am_ende = int(max(0, (ENDE_RASTER_MS - letzte) // MS_4H))
    o, h, l, c, v = k.o, k.h, k.l, k.c, k.v
    # Abweichung der Kerzenzahl je Kalendermonat gegen das Raster (nur Monate mit Abweichung)
    abweichung = []
    for ym in daten._monate(VON, BIS):
        a, b = _monat_grenzen(ym)
        s0 = max(a, erste)
        s0 += (-s0) % MS_4H            # erster Rasterpunkt ab Beginn bzw. ab der ersten Kerze
        soll = int(max(0, (b - s0) // MS_4H))
        ist = int(((t >= a) & (t < b)).sum())
        if soll != ist:
            abweichung.append({"monat": ym, "erwartet": soll, "vorhanden": ist})
    nachbar = (d == MS_4H) & (c[1:] > 0) & (c[:-1] > 0)
    log_ret = np.abs(np.log(c[1:][nachbar] / c[:-1][nachbar]))
    zeit_ret = t[1:][nachbar]
    i_max = int(np.argmax(log_ret)) if len(log_ret) else 0
    vorlauf = bereite_vor(k, T.V_C1).vorlauf
    return {
        "kerzen": n, "erste_kerze": _iso(erste), "letzte_kerze": _iso(letzte), "roh_zeilen": int(k.roh_zeilen), "duplikate": int(k.duplikate), "unsortiert": int(k.unsortiert),
        "nicht_im_4h_raster": int((t % MS_4H != 0).sum()),
        "erwartet_ab_erster_kerze": erwartet, "fehlend_ab_erster_kerze": int(erwartet - n), "anteil_fehlend": float((erwartet - n) / erwartet),
        "erwartet_ab_2017_08_01_nominal": erwartet_nominal, "anteil_fehlend_nominal": float((erwartet_nominal - n) / erwartet_nominal),
        "luecken": luecken, "luecken_anzahl": len(luecken), "fehlend_in_luecken": fehlend_in_luecken, "fehlend_am_ende": fehlend_am_ende,
        "laengste_luecke_kerzen": int(max((x["fehlende_kerzen"] for x in luecken), default=0)),
        "fehlend_summe_konsistent": bool(erwartet - n == fehlend_in_luecken + fehlend_am_ende),
        "monate_mit_abweichung_vom_raster": abweichung,
        "ungueltig": {"hoch_unter_tief": int((h < l).sum()), "nichtpositive_preise": int(((o <= 0) | (h <= 0) | (l <= 0) | (c <= 0)).sum()),
                      "oc_ausserhalb_hoch_tief": int(((o > h) | (o < l) | (c > h) | (c < l)).sum()), "nan_werte": int(np.isnan(np.stack([o, h, l, c, v])).sum()),
                      "negatives_volumen": int((v < 0).sum())},
        "auffaellig": {"volumen_null": int((v == 0).sum()), "flache_kerzen_hoch_gleich_tief": int((h == l).sum())},
        "groesste_4h_bewegung_log": float(log_ret[i_max]) if len(log_ret) else None, "groesste_4h_bewegung_zeit": _iso(zeit_ret[i_max]) if len(log_ret) else None,
        "signalfaehige_kerzen_mit_200er_vorlauf": int(vorlauf.sum()), "erste_signalfaehige_kerze": _iso(t[vorlauf][0]) if vorlauf.any() else None,
        "kurs_min": float(c.min()), "kurs_max": float(c.max()),
    }


def datenaudit(wurzel: str | Path, manifest_pfad: str | Path) -> dict:
    """Datenbericht nach Abschnitt 4 des Zusatzprotokolls. Gibt das Ergebnis (ohne Meta) zurück; schreibt nichts."""
    wurzel = Path(wurzel)
    manifest = json.loads(Path(manifest_pfad).read_text(encoding="utf-8"))
    symbole: dict = {}
    reihen: dict[str, Kerzen] = {}
    for s in SYMBOLE_T15:
        dateien = [_datei_pruefen(wurzel, s, ym, manifest) for ym in daten._monate(VON, BIS)]
        a: dict = {"symbol": s, "monatsdateien_erwartet": ERWARTETE_MONATE, "monatsdateien_vorhanden": int(sum(1 for x in dateien if x["vorhanden"])),
                   "alle_pruefsummen_ok": bool(all(x.get("pruefsumme_ok") for x in dateien)), "lesefehler": [x["monat"] for x in dateien if x.get("lesefehler")],
                   "dateien": dateien}
        try:
            k = daten.laden(wurzel, MARKT, s, "4h", VON, BIS)
        except Exception as ex:
            k = None
            a["ladefehler"] = f"{type(ex).__name__}: {ex}"
        if k is not None:
            a.update(_kerzen_pruefen(k))
            reihen[s] = k
        symbole[s] = a
    gemeinsam: dict = {}
    if len(reihen) == 2:
        b, e = (set(reihen[s].t.tolist()) for s in SYMBOLE_T15)
        gemeinsam = {"zeitstempel_in_beiden": len(b & e), "nur_" + SYMBOLE_T15[0]: len(b - e), "nur_" + SYMBOLE_T15[1]: len(e - b),
                     "gleiche_erste_kerze": bool(reihen[SYMBOLE_T15[0]].t[0] == reihen[SYMBOLE_T15[1]].t[0])}
    gruende: list[str] = []
    for s, a in symbole.items():
        if a["monatsdateien_vorhanden"] != ERWARTETE_MONATE:
            gruende.append(f"{s}: {a['monatsdateien_vorhanden']} von {ERWARTETE_MONATE} Monatsdateien vorhanden")
        if not a["alle_pruefsummen_ok"]:
            gruende.append(f"{s}: Prüfsumme weicht ab oder fehlt")
        if a["lesefehler"] or a.get("ladefehler"):
            gruende.append(f"{s}: Datei nicht lesbar ({a['lesefehler'] or a.get('ladefehler')})")
        if "kerzen" not in a:
            gruende.append(f"{s}: keine Kerzen geladen")
        elif a["anteil_fehlend"] > SCHWELLE_FEHLEND:
            gruende.append(f"{s}: {a['anteil_fehlend']:.1%} der erwarteten Kerzen fehlen (Schwelle {SCHWELLE_FEHLEND:.0%})")
    return {"symbole": symbole, "gemeinsam": gemeinsam, "abbruch": bool(gruende), "abbruch_gruende": gruende,
            "abbruchregel": f"Abbruch, wenn je Symbol mehr als {SCHWELLE_FEHLEND:.0%} der erwarteten 4h-Kerzen fehlen (Raster ab der ersten Kerze bis 2019-12-31T20:00Z), "
                            f"eine Prüfsumme abweicht oder ein Monat fehlt (erwartet {ERWARTETE_MONATE} Monatsdateien je Symbol)"}


# ---------------------------------------------------------------------------------------------------------------------------------------
# Schritt 2: Handelslauf (Abschnitte 3 und 5)
# ---------------------------------------------------------------------------------------------------------------------------------------

def einordnung(e_r: float | None, p: float | None) -> str:
    """Klasse nach Abschnitt 6 des Zusatzprotokolls (P1 = E[R] unter K2 größer 0 und p höchstens 0,05)."""
    if e_r is None or p is None or not np.isfinite(e_r) or not np.isfinite(p):
        return "nicht auswertbar"
    if e_r > 0 and p <= P_SCHWELLE:
        return "bestätigt"
    return "nicht bestätigt, Richtung positiv" if e_r > 0 else "nicht bestätigt, Richtung negativ"


def _satz(trades: list[Trade], ziehungen_bootstrap: int | None) -> dict:
    if not trades:
        return {"kennzahlen": {"n": 0}}
    a = T.arrays(trades)
    out: dict = {"kennzahlen": kz.kpi(a["r"], a["signal_ms"], a["exit_ms"], stop_anteil=a["stop_anteil"], kosten_r=a["kosten_r"], funding_r=a["funding_r"],
                                      brutto_r=a["brutto_r"], seite=a["seite"], symbol=a["symbol"], grund=a["grund"], haltedauer_h=a["haltedauer_h"])}
    if ziehungen_bootstrap:
        out["monatsblock_bootstrap"] = kz.monatsblock_bootstrap(a["r"], a["signal_ms"], ziehungen=ziehungen_bootstrap, seed=T.SEED, exit_ms=a["exit_ms"])
    return out


def zufallsvergleich(kerzen: dict[str, Kerzen], fund: dict, sym: tuple[str, ...], ziehungen: int, seed: int, kosten) -> dict:
    """P3: Zufallseinstiege in SMA200-Richtung wie T3, aber für einen einzigen Zeitraum. Wahrscheinlichkeit je Kerze = rohe Signalhäufigkeit
    des Kandidaten je Instrument über alle Kerzen mit Vorlauf; Richtung = Seite des SMA200; gleiche Kosten, gleiche Positionsgrenze."""
    basis = {s: bereite_vor(kerzen[s], T.V_C1) for s in sym}
    kand = simuliere({s: kerzen[s] for s in sym}, fund, T.V_C1, kosten, portfolio=True, reihenfolge=sym, reihen=basis)
    e_kand = float(np.mean([t.r for t in kand])) if kand else float("nan")
    p_sig: dict[str, dict] = {}
    for s in sym:
        r = basis[s]
        n_v = int(r.vorlauf.sum())
        n_s = int(((r.sig != 0) & r.vorlauf).sum())
        p_sig[s] = {"signale": n_s, "kerzen_mit_vorlauf": n_v, "p_je_kerze": n_s / max(n_v, 1)}
    rng = np.random.default_rng(seed)
    e_z = np.empty(ziehungen)
    n_z = np.empty(ziehungen)
    for d in range(ziehungen):
        reihen = {}
        for s in sym:
            r = basis[s]
            u = rng.random(len(r.t))
            sig = np.where(r.vorlauf & (u < p_sig[s]["p_je_kerze"]), r.sma_seite, 0)
            reihen[s] = mit_signalen(r, sig)
        tr = simuliere({s: kerzen[s] for s in sym}, fund, T.V_C1, kosten, portfolio=True, reihenfolge=sym, reihen=reihen)
        n_z[d] = len(tr)
        e_z[d] = float(np.mean([t.r for t in tr])) if tr else np.nan
    x = e_z[~np.isnan(e_z)]
    p = (1 + int((x >= e_kand).sum())) / (1 + len(x)) if np.isfinite(e_kand) else None
    return {"kosten": "K1 (Funding aus)", "ziehungen": ziehungen, "seed": seed, "gueltige_ziehungen": int(len(x)), "kandidat_e_r": e_kand, "kandidat_n": len(kand),
            "signalhaeufigkeit": p_sig, "e_r_zufall_mittel": float(x.mean()) if len(x) else None, "e_r_zufall_median": float(np.median(x)) if len(x) else None,
            "e_r_zufall_ci90": [float(np.percentile(x, 5)), float(np.percentile(x, 95))] if len(x) else None, "e_r_zufall_max": float(x.max()) if len(x) else None,
            "anteil_ziehungen_positiv": float((x > 0).mean()) if len(x) else None, "n_zufall_mittel": float(np.nanmean(n_z)) if len(n_z) else None,
            "p_einseitig": p, "e_r_zufall_werte": [round(float(v), 5) for v in x]}


def handelslauf(kerzen: dict[str, Kerzen], ziehungen_zufall: int = T.ZIEHUNGEN_ZUFALL, ziehungen_bootstrap: int = T.ZIEHUNGEN_BOOTSTRAP) -> tuple[dict, dict[str, list[Trade]]]:
    """Der Handelslauf ohne Dateizugriff: C3 (S7b-D20-T3 auf BTC und ETH), K2 primär, K1 und K0 berichtet, Funding aus. Die Daten werden übergeben
    (``Kerzen`` je Symbol). Gibt (Ergebnis, Trades je Kostenszenario) zurück. P6 (Funding-Sensitivität) wird in ``funding_sensitivitaet`` gerechnet."""
    sym = tuple(s for s in SYMBOLE_T15 if s in kerzen)
    sub = {s: kerzen[s] for s in sym}
    fund: dict = {s: None for s in sym}
    trades = {name: simuliere(sub, fund, T.V_C1, k, portfolio=True, reihenfolge=sym) for name, k in KOSTEN_T15.items()}
    k2 = _satz(trades["K2"], ziehungen_bootstrap)
    n = k2["kennzahlen"]["n"]
    e_r = k2["kennzahlen"].get("e_r")
    zieh = k2["monatsblock_bootstrap"]["ziehungen"] if n else None
    k_nichtpositiv = int(round((1.0 - k2["monatsblock_bootstrap"]["e_r"]["anteil_positiv"]) * zieh)) if n else None
    p = k_nichtpositiv / zieh if n else None   # Anteil der Ziehungen mit Mittel <= 0 (ganzzahlig gerechnet, keine Gleitkomma-Schwelle)
    klasse = einordnung(e_r, p)
    sd = k2["kennzahlen"].get("sd_r")
    z95, z80 = 1.6448536269514722, 0.8416212335729143
    out: dict = {
        "einordnung": {"klasse": klasse, "text": EINORDNUNG[klasse]},
        "p1": {"kosten": "K2 (Gebühr 0,06 %, Schlupf 0,06 % je Seite, Stop-Schlupf 0,10 %), Funding aus", "n": n, "e_r": e_r, "e_r_groesser_null": bool(e_r is not None and e_r > 0),
               "p_monatsblock_bootstrap_einseitig": p, "p_definition": "Anteil der 10 000 Ziehungen ganzer Kalendermonate mit Mittel <= 0 (Seed 20261116); Trades gehören dem Monat ihres Signals",
               "ziehungen_mit_mittel_nicht_positiv": k_nichtpositiv, "p_hoechstens_0_05": bool(p is not None and p <= P_SCHWELLE), "erfuellt": bool(klasse == "bestätigt"),
               "ci95_bootstrap": k2["monatsblock_bootstrap"]["e_r"]["ci95"] if n else None},
        "primaer_k2": k2,
        "p2": {name: {**T.kurz(trades[name]), "kosten_r_je_trade": float(np.mean([t.kosten_r for t in trades[name]])) if trades[name] else None}
               for name in ("K1", "K0")},
        "p3": zufallsvergleich(kerzen, fund, sym, ziehungen_zufall, T.SEED, KOSTEN_T15["K1"]),
        "p4": {"je_jahr": k2["kennzahlen"].get("je_jahr", {}), "nach": "Jahr des Signals (K2)"},
        "p5": {"max_drawdown_r": k2["kennzahlen"].get("max_drawdown_r"), "max_drawdown_dauer_tage": k2["kennzahlen"].get("max_drawdown_dauer_tage"),
               "bootstrap_max_drawdown_r": k2["monatsblock_bootstrap"]["max_drawdown_r"] if n else None},
        "p7": {key: k2["kennzahlen"].get(key) for key in ("trefferquote", "trefferquote_ci95_wilson", "profit_faktor", "mittel_gewinn_r", "mittel_verlust_r",
                                                          "median_r", "bester_trade_r", "schlechtester_trade_r", "anteil_beste_5_prozent_an_summe")},
        "p8": {"je_symbol": k2["kennzahlen"].get("je_symbol"), "je_seite": k2["kennzahlen"].get("je_seite"), "je_grund": k2["kennzahlen"].get("je_grund")},
        "aussagekraft_nachtraeglich": {"n": n, "sd_r": sd, "erwartete_trades_laut_zusatzprotokoll": ERWARTETE_TRADES,
                                       "kleinste_bei_80_prozent_power_nachweisbare_erwartung_r": float((z95 + z80) * sd / np.sqrt(n)) if n and sd else None,
                                       "hinweis": "einseitiger Test zum Niveau 5 %; mit der beobachteten Streuung und Trade-Zahl gerechnet (nur Information)"},
        "daten_im_lauf": {},
    }
    for s in sym:
        r = bereite_vor(sub[s], T.V_C1)
        out["daten_im_lauf"][s] = {"kerzen": int(len(sub[s].t)), "signalfaehige_kerzen": int(r.vorlauf.sum()), "rohsignale_mit_vorlauf": int(((r.sig != 0) & r.vorlauf).sum()),
                                   "trades_k2": int(sum(1 for t in trades["K2"] if t.symbol == s))}
    out["trades_k2"] = [{"symbol": t.symbol, "seite": t.seite, "signal_ms": t.signal_zeit, "einstieg_ms": t.einstieg_zeit, "ausstieg_ms": t.ausstieg_zeit,
                         "grund": t.grund, "kerzen": t.kerzen, "brutto_r": t.brutto_r, "kosten_r": t.kosten_r, "r": t.r} for t in trades["K2"]]
    return out, trades


def funding_sensitivitaet(futures_wurzel: str | Path, r_primaer: np.ndarray, signal_ms: np.ndarray, exit_ms: np.ndarray, ziehungen_bootstrap: int) -> dict:
    """P6 (Abschnitt 3): vom primären E[R] wird der mittlere Funding-Kostenanteil je Trade abgezogen, den C3 unter K2 mit Funding ohne Gutschrift
    im Zeitraum 2020 bis 2024 (Training + Validierung, Abschnittsregel 1.2) hatte. Ersetzt P1 nicht."""
    kerzen, fund = T.daten_laden(str(futures_wurzel))
    tr = T.nach_abschnitt(T.lauf(kerzen, fund, SYMBOLE_T15, T.V_C1, T.KOSTEN["K2"]))["pooled"]
    a = T.arrays(tr)
    mittel = float(a["funding_r"].mean())
    jahr = kz.monat_schluessel(a["signal_ms"]) // 100
    t02 = json.loads((ERGEBNISSE / "t02_kosten.json").read_text(encoding="utf-8"))["ergebnis"]["C3"]["szenarien"]["K2"]["pooled"]
    e_primaer = float(r_primaer.mean())
    out: dict = {
        "quelle": "C3 (BTC/ETH), K2 mit Funding ohne Gutschrift, Signale 2020-01 bis 2024-12, Training + Validierung gepoolt (Binance USD-M Futures)",
        "n_trades_2020_2024": int(len(a["r"])), "e_r_k2_2020_2024": float(a["r"].mean()),
        "abgleich_t02": {"n_t02": t02["n"], "e_r_t02": t02["e_r"], "gleich": bool(t02["n"] == len(a["r"]) and abs(t02["e_r"] - float(a["r"].mean())) < 1e-5)},
        "funding_kostenanteil_je_trade_r": mittel, "anteil_trades_mit_funding_kosten": float((a["funding_r"] > 0).mean()),
        "funding_kostenanteil_je_jahr_r": {str(int(y)): float(a["funding_r"][jahr == y].mean()) for y in np.unique(jahr)},
        "e_r_primaer_k2": e_primaer, "e_r_nach_funding_abzug": e_primaer - mittel,
        "hinweis": "Funding ohne Gutschrift: nur Zahlungen zählen (konservativ). Die Funding-Verhältnisse 2017 bis 2019 sind nicht bekannt (keine Historie); der Abzug ist eine Annahme aus 2020 bis 2024.",
    }
    # Ergänzend (nicht in Abschnitt 5 des Zusatzprotokolls, im Code vor dem Lauf festgelegt): gleicher Monatsblock-Bootstrap auf den um den Abzug verschobenen R-Werten
    if len(r_primaer):
        bs = kz.monatsblock_bootstrap(r_primaer - mittel, signal_ms, ziehungen=ziehungen_bootstrap, seed=T.SEED, exit_ms=exit_ms)
        out["ergaenzend_bootstrap_nach_abzug"] = {"p_einseitig": round(1.0 - bs["e_r"]["anteil_positiv"], 6), "ci95": bs["e_r"]["ci95"],
                                                  "status": "ergänzend, nicht vorab im Zusatzprotokoll festgelegt; ersetzt P1 nicht"}
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------
# Vorbedingungen, Meta, Ablage, Testlog
# ---------------------------------------------------------------------------------------------------------------------------------------

def _meta(test: str, konfig: dict, befehl: str, zeitraum: str, status: str, dauer: float, commit: str, schmutzig: bool, grenzen: list[str]) -> dict:
    m = T.meta(test, konfig, befehl, zeitraum, status, grenzen)
    m.update({"kandidat": "C3 (S7b-D20-T3 auf BTC und ETH)", "code_commit": commit, "code_unsauber": schmutzig, "dauer_s": round(dauer, 1),
              "protokoll_t15": "PROTOKOLL_KONSOLIDIERUNG_T15.md 1.1-T15", "protokoll_t15_sha256": _sha256(PROTOKOLL_T15),
              "protokoll_1_0_sha256": _sha256(PROTOKOLL_1_0)})
    return m


def pruefe_vorbedingungen(wurzel: Path, ausgabe: Path) -> dict:
    """Alles, was vor dem einzigen Handelslauf feststehen muss. Wirft ``Vorbedingung`` mit allen Verstößen."""
    verstoesse: list[str] = []
    audit_pfad = ausgabe / "t15_datenaudit.json"
    audit: dict = {}
    if not audit_pfad.is_file():
        verstoesse.append("Datenbericht t15_datenaudit.json fehlt")
    else:
        audit = json.loads(audit_pfad.read_text(encoding="utf-8"))
        if audit["ergebnis"]["abbruch"]:
            verstoesse.append("Abbruchregel im Datenbericht ausgelöst: " + "; ".join(audit["ergebnis"]["abbruch_gruende"]))
        fest, _ = _festgehalten(audit_pfad)
        if not fest:
            verstoesse.append("Datenbericht ist nicht festgehalten (nicht versioniert oder geändert)")
        for s, a in audit["ergebnis"]["symbole"].items():
            for d in a["dateien"]:
                p = wurzel / d["datei"]
                if not p.is_file() or _sha256(p) != d.get("sha256"):
                    verstoesse.append(f"Datei weicht vom Datenbericht ab oder fehlt: {d['datei']}")
    if (ausgabe / "t15_ausserhalb.json").exists():
        verstoesse.append("t15_ausserhalb.json liegt schon vor: genau ein Lauf")
    commit, schmutzig = git_stand()
    if schmutzig:
        verstoesse.append("Code in src/research_lab/konsolidierung ist nicht festgehalten (Commit fehlt)")
    fest_p, _ = _festgehalten(PROTOKOLL_T15)
    if not fest_p:
        verstoesse.append("Zusatzprotokoll T15 ist nicht festgehalten oder wurde geändert")
    stand = json.loads(PROTOKOLL_STAND.read_text(encoding="utf-8"))
    if _sha256(PROTOKOLL_1_0) != stand["sha256"]:
        verstoesse.append("Protokoll 1.0 weicht von der eingefrorenen Fassung ab")
    if verstoesse:
        raise Vorbedingung("; ".join(verstoesse))
    return {"code_commit": commit, "datenaudit_sha256": _sha256(audit_pfad), "datenaudit_commit": _festgehalten(audit_pfad)[1]}


def schreibe_testlog_t15(ausgabe: Path = ERGEBNISSE) -> Path:
    zeilen = ["# Testlog T15 (Zusatzprotokoll 1.1-T15)", "",
              "Erzeugt von `t15_ausserhalb.py`, getrennt von `TESTLOG.md`, damit ein erneuter Lauf von `lauf.py` es nicht überschreibt.", "",
              "| Schritt | Zeitraum | Code-Commit | Befehl | Ergebnisdatei | Status | Grenzen |", "|---|---|---|---|---|---|---|"]
    for name, titel in (("t15_datenaudit.json", "Datenbericht (vor dem Handelslauf)"), ("t15_ausserhalb.json", "Handelslauf (genau ein Lauf)")):
        pfad = ausgabe / name
        if not pfad.exists():
            continue
        m = json.loads(pfad.read_text(encoding="utf-8"))["meta"]
        zeilen.append(f"| {titel} | {m['zeitraum']} | `{m['code_commit'][:10]}`{' (unsauber)' if m.get('code_unsauber') else ''} | `{m['befehl']}` | `ergebnisse/{name}` | {m['status']} | "
                      + "; ".join(m["grenzen"]) + " |")
    pfad_log = ausgabe.parent / "TESTLOG_T15.md"
    pfad_log.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    return pfad_log


def lauf_audit(wurzel: str, manifest: str, ausgabe: Path = ERGEBNISSE) -> dict:
    t0 = time.time()
    commit, schmutzig = git_stand()
    res = datenaudit(wurzel, manifest)
    befehl = f"python3 -m src.research_lab.konsolidierung.t15_ausserhalb audit {wurzel} {Path(manifest).name}"
    m = _meta("T15-Datenbericht", {"markt": MARKT, "symbole": list(SYMBOLE_T15), "intervall": "4h", "monate": f"{VON} bis {BIS}", "manifest_datei": Path(manifest).name,
                                   "manifest_sha256": _sha256(Path(manifest))},
              befehl, "Spot 4h-Kerzen 2017-08 bis 2019-12 (keine Handelssimulation)", "abbruch" if res["abbruch"] else "bestanden (keine Abbruchregel ausgelöst)", time.time() - t0, commit, schmutzig, GRENZEN_AUDIT)
    T.schreibe(ausgabe / "t15_datenaudit.json", {"meta": m, "ergebnis": res})
    schreibe_testlog_t15(ausgabe)
    return res


def lauf_t15(wurzel: str, futures_wurzel: str, ausgabe: Path = ERGEBNISSE, ziehungen_zufall: int = T.ZIEHUNGEN_ZUFALL,
             ziehungen_bootstrap: int = T.ZIEHUNGEN_BOOTSTRAP, vorbedingungen: bool = True) -> dict:
    """Der einzige Handelslauf von T15. ``vorbedingungen=False`` nur für Tests mit synthetischen Daten."""
    t0 = time.time()
    wurzel_p = Path(wurzel)
    vor = pruefe_vorbedingungen(wurzel_p, ausgabe) if vorbedingungen else {}
    commit, schmutzig = git_stand()
    kerzen = {s: daten.laden(wurzel_p, MARKT, s, "4h", VON, BIS) for s in SYMBOLE_T15}
    res, trades = handelslauf(kerzen, ziehungen_zufall, ziehungen_bootstrap)
    a = T.arrays(trades["K2"])
    res["p6"] = funding_sensitivitaet(futures_wurzel, a["r"], a["signal_ms"], a["exit_ms"], ziehungen_bootstrap) if len(a["r"]) else {"status": "keine Trades"}
    befehl = f"python3 -m src.research_lab.konsolidierung.t15_ausserhalb lauf {wurzel} {futures_wurzel}"
    m = _meta("T15", {"kandidat": "C3", "variante": T.V_C1.beschreibung, "symbole": list(SYMBOLE_T15), "reihenfolge": "BTC vor ETH", "markt": MARKT, "intervall": "4h",
                      "kosten_primaer": "K2, Funding aus", "kosten_berichtet": ["K1", "K0"], "ziehungen_zufall": ziehungen_zufall, "ziehungen_bootstrap": ziehungen_bootstrap,
                      "funding_sensitivitaet_daten": "Binance USD-M Futures 2020 bis 2024 (C3, K2, ohne Gutschrift)"},
              befehl, "Signale 2017-08 bis 2019-12 (Spot); Holdout (ab 2025-01-01) nicht geladen", "abgeschlossen: " + res["einordnung"]["klasse"], time.time() - t0, commit, schmutzig, GRENZEN)
    m.update(vor)
    T.schreibe(ausgabe / "t15_ausserhalb.json", {"meta": m, "ergebnis": res})
    schreibe_testlog_t15(ausgabe)
    return res


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "audit":
        res = lauf_audit(argv[2], argv[3])
        print("Datenbericht geschrieben; Abbruch:", res["abbruch"], res["abbruch_gruende"])
        return 1 if res["abbruch"] else 0
    if len(argv) == 4 and argv[1] == "lauf":
        res = lauf_t15(argv[2], argv[3])
        p1 = res["p1"]
        print("T15 abgeschlossen:", res["einordnung"]["klasse"], "| n =", p1["n"], "| E[R] K2 =", p1["e_r"], "| p =", p1["p_monatsblock_bootstrap_einseitig"])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
