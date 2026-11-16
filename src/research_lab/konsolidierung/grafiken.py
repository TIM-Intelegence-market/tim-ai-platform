"""Grafiken der Konsolidierung. Alles wird aus den Ergebnisdateien (``ergebnisse/*.json``), dem Register und dem OFX-Aggregat gezeichnet.

Aufruf: ``python3 -m src.research_lab.konsolidierung.grafiken [Ausgabeordner]``. Keine Zufallszahlen, keine Netzwerkzugriffe.
Den OFX-Aggregat erzeugt ``ofx_aggregat`` aus den Bestenlisten der PS5-Kopie (nur wenn die Rohdateien vorhanden sind)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

ERGEBNISSE = Path("docs/research_lab/konsolidierung/ergebnisse")
AUSGABE = Path("docs/research_lab/konsolidierung/grafiken")
REGISTER = Path("docs/research_lab/konsolidierung/studienregister.json")

# Farben: Referenzpalette (Slots 1–3, in beiden Modi als Menge validiert), Text und Fläche
FLAECHE, TEXT, TEXT2, GITTER, ACHSE = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1", "#c9c8c2"
BLAU, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
GRAU = "#9a998f"
TRAIN_ENDE = np.datetime64("2023-01-01")
VALID_ENDE = np.datetime64("2025-01-01")
OFX_N_MIN, OFX_MITTEL_MIN = 130, 0.10          # Sieb der OFX-Suche


def komma(v: float, _pos=None) -> str:
    return f"{v:g}".replace(".", ",").replace("-", "−")


def stil() -> None:
    plt.rcParams.update({
        "figure.facecolor": FLAECHE, "axes.facecolor": FLAECHE, "savefig.facecolor": FLAECHE,
        "axes.edgecolor": ACHSE, "axes.labelcolor": TEXT2, "text.color": TEXT, "xtick.color": TEXT2, "ytick.color": TEXT2,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y",
        "grid.color": GITTER, "grid.linewidth": 0.7, "grid.linestyle": "-", "axes.axisbelow": True,
        "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "lines.linewidth": 1.6, "lines.solid_capstyle": "round", "legend.frameon": False, "legend.fontsize": 8.5,
        "axes.formatter.use_locale": False,
    })


def lade(name: str, ordner: Path = ERGEBNISSE) -> dict:
    return json.loads((ordner / name).read_text(encoding="utf-8"))


def fuss(fig, text: str) -> None:
    fig.text(0.01, 0.008, text, fontsize=7.2, color=TEXT2, ha="left", va="bottom")


def kopf(fig, titel: str, untertitel: str | None = None) -> None:
    """Titel und Untertitel links oben auf Figurebene (kein Überlappen mit Achsentiteln)."""
    fig.text(0.01, 0.975, titel, fontsize=11.5, fontweight="bold", ha="left", va="top")
    if untertitel:
        fig.text(0.01, 0.922, untertitel, fontsize=8.2, color=TEXT2, ha="left", va="top")


def eins(x: float) -> str:
    """Zahl mit genau einer Nachkommastelle und Dezimalkomma."""
    return f"{x:.1f}".replace(".", ",").replace("-", "−")


def speichern(fig, ordner: Path, name: str) -> Path:
    ordner.mkdir(parents=True, exist_ok=True)
    pfad = ordner / name
    fig.savefig(pfad, dpi=150)
    plt.close(fig)
    return pfad


def abschnitte(ax, beschriftung: bool = True) -> None:
    """Validierung 2023–2024 als heller Streifen, Training davor."""
    ax.axvspan(TRAIN_ENDE, VALID_ENDE, color=GITTER, alpha=0.55, lw=0, zorder=0)
    if beschriftung:
        ax.text(0.01, 0.985, "Training", transform=ax.transAxes, va="top", ha="left", fontsize=7.8, color=TEXT2)
        ax.text(0.612, 0.985, "Validierung", transform=ax.transAxes, va="top", ha="left", fontsize=7.8, color=TEXT2)


def tage_zu_datum(tage) -> np.ndarray:
    return np.datetime64("1970-01-01") + np.asarray(tage).astype("timedelta64[D]")


def kurven(erg: Path = ERGEBNISSE) -> dict:
    t = lade("tagesreihen.json", erg)
    d = tage_zu_datum(t["tage"])
    reihen = {"C1": np.asarray(t["trend_prozent"], float)}
    for k in ("R1", "R2"):
        assert t["referenzen"][k]["tage"] == t["tage"]
        reihen[k] = np.asarray(t["referenzen"][k]["prozent"], float)
    out = {}
    for k, v in reihen.items():
        cum = np.cumsum(v)
        spitze = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
        out[k] = {"kum": cum, "dd": cum - spitze}
    return {"datum": d, "reihen": out}


def g1_verlauf(ordner: Path, erg: Path = ERGEBNISSE) -> Path:
    k = kurven(erg)
    fig, ax = plt.subplots(figsize=(8.0, 4.3))
    abschnitte(ax)
    namen = {"C1": ("C1 Trendregel S7b-D20-T3", BLAU), "R1": ("R1 Korb Buy and Hold", ORANGE), "R2": ("R2 SMA200 lang/flat", AQUA)}
    for key in ("R1", "R2", "C1"):
        name, farbe = namen[key]
        ax.plot(k["datum"], k["reihen"][key]["kum"], color=farbe, label=f"{name}: {komma(round(k['reihen'][key]['kum'][-1]))} %", zorder=3 if key == "C1" else 2)
    ax.axhline(0, color=ACHSE, lw=0.9, zorder=1)
    ax.set_ylabel("kumulierte Nettorendite in % des Kapitals")
    ax.yaxis.set_major_formatter(FuncFormatter(komma))
    kopf(fig, "Netto-Verlauf der Trendregel gegen einfache Referenzen", "Nach Kosten K1, 1 % Risiko je Trade, nicht aufgezinst; Referenzen auf die Tagesschwankung von C1 skaliert. 2020–2024.")
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.93))
    fuss(fig, "Quelle: ergebnisse/tagesreihen.json (T10). Gleiche, im Nachhinein gewählte Coins; kein Test außerhalb der Entwicklung.")
    fig.subplots_adjust(left=0.09, right=0.98, top=0.86, bottom=0.12)
    return speichern(fig, ordner, "g1_netto_verlauf.png")


def g2_drawdown(ordner: Path, erg: Path = ERGEBNISSE) -> Path:
    k = kurven(erg)
    fig, ax = plt.subplots(figsize=(8.0, 4.0))
    abschnitte(ax)
    namen = {"C1": ("C1", BLAU), "R1": ("R1", ORANGE), "R2": ("R2", AQUA)}
    for key in ("R1", "R2", "C1"):
        name, farbe = namen[key]
        dd = k["reihen"][key]["dd"]
        ax.plot(k["datum"], dd, color=farbe, label=f"{name}: größter Rückgang {eins(float(dd.min()))} %", zorder=3 if key == "C1" else 2)
    ax.fill_between(k["datum"], k["reihen"]["C1"]["dd"], 0, color=BLAU, alpha=0.10, lw=0, zorder=1)
    ax.set_ylabel("Rückgang vom bisherigen Höchststand in % des Kapitals")
    ax.yaxis.set_major_formatter(FuncFormatter(komma))
    ax.set_ylim(-37, 5)
    kopf(fig, "Drawdowns: Trendregel und Referenzen auf gleicher Schwankung", "Rückgang der kumulierten Nettorendite vom bisherigen Höchststand, Tagesbasis, 2020–2024.")
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, 0.0))
    fuss(fig, "Quelle: ergebnisse/tagesreihen.json (T10). Rückgang auf Tagesbasis aus der nicht aufgezinsten Summe.")
    fig.subplots_adjust(left=0.09, right=0.98, top=0.86, bottom=0.12)
    return speichern(fig, ordner, "g2_drawdown.png")


def g3_kosten(ordner: Path, erg: Path = ERGEBNISSE) -> Path:
    t2 = lade("t02_kosten.json", erg)["ergebnis"]["C1"]
    b = t2["bruchstelle"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.6, 4.2), gridspec_kw={"width_ratios": [1.15, 1]})
    m = b["multiplikator_gitter"]
    for sec, name, farbe in (("train", "Training", BLAU), ("validation", "Validierung", AQUA), ("pooled", "gepoolt", TEXT2)):
        a1.plot(m, b["e_r"][sec], color=farbe, label=name, lw=1.6 if sec != "pooled" else 1.2)
    a1.axhline(0, color=ACHSE, lw=0.9)
    a1.axvline(1, color=ACHSE, lw=0.9)
    a1.text(1.25, -0.93, "K1", fontsize=8, color=TEXT2, va="bottom")
    nd = b["null_durchgang_multiplikator"]["pooled"]
    a1.plot([nd], [0], marker="o", ms=6, color=TEXT2, mec=FLAECHE, mew=1.5, zorder=4)
    a1.annotate(f"gepoolt null bei {komma(round(nd, 1))}× K1", xy=(nd, 0), xytext=(nd + 1.0, 0.18), fontsize=8, color=TEXT2, arrowprops={"arrowstyle": "-", "color": ACHSE, "lw": 0.8})
    a1.set_xlabel("Gebühr und Schlupf als Vielfaches von K1")
    a1.set_ylabel("E[R] je Trade (netto)")
    a1.yaxis.set_major_formatter(FuncFormatter(komma))
    a1.xaxis.set_major_formatter(FuncFormatter(komma))
    a1.set_title("Kostenbruchstelle")
    a1.legend(loc="upper right")
    namen = [("K0", "K0\nProtokoll"), ("K1", "K1\nBasis"), ("K2", "K2\nkonserv."), ("K3", "K3\npessim."), ("K4", "K4\nMaker"), ("L1", "L1\n+1 Kerze")]
    x = np.arange(len(namen))
    w = 0.34
    for i, (sec, name, farbe) in enumerate((("train", "Training", BLAU), ("validation", "Validierung", AQUA))):
        werte = [t2["szenarien"][k][sec]["e_r"] for k, _ in namen]
        bars = a2.bar(x + (i - 0.5) * (w + 0.03), werte, width=w, color=farbe, label=name, edgecolor=FLAECHE, linewidth=1.2)
        for xi, v, k in zip(x + (i - 0.5) * (w + 0.03), werte, [k for k, _ in namen]):
            if k in ("L1", "K2"):
                a2.text(xi, v + (0.012 if v >= 0 else -0.012), komma(round(v, 3)), ha="center", va="bottom" if v >= 0 else "top", fontsize=7.4, color=TEXT2)
    a2.axhline(0, color=ACHSE, lw=0.9)
    a2.set_xticks(x, [n for _, n in namen], fontsize=7.2)
    a2.set_ylim(-0.06, 0.40)
    a2.yaxis.set_major_formatter(FuncFormatter(komma))
    a2.set_ylabel("E[R] je Trade (netto)")
    a2.set_title("Kostenszenarien und Verzögerung")
    a2.legend(loc="upper right")
    kopf(fig, "Kostensensitivität der Trendregel (C1)")
    fuss(fig, "Quelle: ergebnisse/t02_kosten.json. K2 ist das Kriterium G2 (E[R] > 0 in beiden Abschnitten); L1 und K4 sind keine Kriterien. n: Training 287–292, Validierung 192–207.")
    fig.subplots_adjust(left=0.07, right=0.985, top=0.84, bottom=0.2, wspace=0.22)
    return speichern(fig, ordner, "g3_kostensensitivitaet.png")


def g4_stabilitaet(ordner: Path, erg: Path = ERGEBNISSE) -> Path:
    t9 = lade("t09_regime_C1.json", erg)["ergebnis"]
    hj = t9["je_halbjahr"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.8, 4.2), gridspec_kw={"width_ratios": [1.05, 1]})
    keys = list(hj.keys())
    werte = [hj[k]["e_r"] for k in keys]
    x = np.arange(len(keys))
    a1.bar(x, werte, width=0.62, color=BLAU, edgecolor=FLAECHE, linewidth=1.2)
    a1.axhline(0, color=ACHSE, lw=0.9)
    a1.axvspan(5.5, len(keys) - 0.5, color=GITTER, alpha=0.55, lw=0, zorder=0)
    a1.set_ylim(-0.34, 0.80)
    a1.set_xticks(x, [f"{k[:4]}\n{k[4:]}" for k in keys], fontsize=7.6)
    for xi, v, k in zip(x, werte, keys):
        a1.text(xi, v + (0.02 if v >= 0 else -0.02), f"n {hj[k]['n']}", ha="center", va="bottom" if v >= 0 else "top", fontsize=6.8, color=TEXT2)
    a1.yaxis.set_major_formatter(FuncFormatter(komma))
    a1.set_ylabel("E[R] je Trade (netto, K1)")
    a1.set_title("Je Halbjahr")
    a1.text(0.01, 0.985, "Training", transform=a1.transAxes, va="top", fontsize=7.8, color=TEXT2)
    a1.text(0.595, 0.985, "Validierung", transform=a1.transAxes, va="top", fontsize=7.8, color=TEXT2)
    g = t9["gleitend_6_monate"]
    mon = [k for k, v in g.items() if v["n"] >= 30]
    d = np.array([np.datetime64(f"{k[:4]}-{k[4:]}") for k in mon])
    e = [g[k]["e_r"] for k in mon]
    abschnitte(a2, beschriftung=False)
    a2.plot(d, e, color=BLAU)
    a2.axhline(0, color=ACHSE, lw=0.9)
    pooled = lade("t07_unsicherheit_C1.json", erg)["ergebnis"]["pooled"]["kennzahlen"]["e_r"]
    a2.axhline(pooled, color=TEXT2, lw=0.9, ls=(0, (4, 3)))
    a2.text(0.99, 0.885, f"Strichlinie: gepoolt {komma(round(pooled, 3))}", transform=a2.transAxes, fontsize=7.6, color=TEXT2, ha="right", va="top")
    a2.set_ylim(-0.30, 0.85)
    a2.yaxis.set_major_formatter(FuncFormatter(komma))
    a2.set_ylabel("E[R] je Trade, gleitend über 6 Monate")
    a2.set_title("Gleitendes Fenster (nur n ≥ 30)")
    a2.text(0.01, 0.985, "Training", transform=a2.transAxes, va="top", fontsize=7.8, color=TEXT2)
    a2.text(0.612, 0.985, "Validierung", transform=a2.transAxes, va="top", fontsize=7.8, color=TEXT2)
    kopf(fig, "Zeitliche Stabilität der Trendregel (C1)")
    fuss(fig, "Quelle: ergebnisse/t09_regime_C1.json. Halbjahre mit 34–60 Trades; einzelne Halbjahre sind statistisch nicht unterscheidbar von null bis +0,6 R.")
    fig.subplots_adjust(left=0.07, right=0.985, top=0.84, bottom=0.15, wspace=0.24)
    return speichern(fig, ordner, "g4_zeitliche_stabilitaet.png")


def g5_zufall_raster(ordner: Path, erg: Path = ERGEBNISSE) -> Path:
    t3 = lade("t03_zufall_C1.json", erg)["ergebnis"]
    t4 = lade("t04_raster_C1.json", erg)["ergebnis"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.8, 4.2))
    bins = np.linspace(-0.35, 0.40, 40)
    for sec, name, farbe in (("train", "Training", BLAU), ("validation", "Validierung", AQUA)):
        w = np.asarray(t3["sektionen"][sec]["e_r_zufall_werte"], float)
        a1.hist(w, bins=bins, histtype="stepfilled", color=farbe, alpha=0.12, lw=0)
        a1.hist(w, bins=bins, histtype="step", color=farbe, lw=1.6, label=name)
        c = t3["kandidat_e_r"][sec]
        a1.axvline(c, color=farbe, lw=1.2, ls=(0, (4, 3)))
        a1.text(c, a1.get_ylim()[1] * 0.97, f" C1 {komma(round(c, 3))}\n p {komma(round(t3['sektionen'][sec]['p_einseitig'], 3))}", color=TEXT2, fontsize=7.6, va="top", ha="left" if sec == "validation" else "right")
    a1.set_xlabel("E[R] je Trade (netto, K1)")
    a1.set_ylabel("Anzahl von 1.000 Ziehungen")
    a1.xaxis.set_major_formatter(FuncFormatter(komma))
    a1.set_title("Zufallseinstiege in SMA200-Richtung")
    a1.legend(loc="center right", bbox_to_anchor=(1.0, 0.45), title="Zufallseinstiege", title_fontsize=8, alignment="left")
    zellen = [z["pooled"]["e_r"] for z in t4["zellen_liste"] if z["pooled"]["e_r"] is not None]
    c1 = t4["c1_zelle"]["pooled"]["e_r"]
    a2.hist(zellen, bins=np.linspace(-0.15, 0.50, 40), color=BLAU, alpha=0.9, edgecolor=FLAECHE, linewidth=0.8)
    a2.axvline(0, color=ACHSE, lw=0.9)
    a2.axvline(c1, color=TEXT, lw=1.2, ls=(0, (4, 3)))
    a2.text(c1, a2.get_ylim()[1] * 0.97, f" C1 {komma(round(c1, 3))}\n Rang {komma(round(100 * t4['c1_rang_prozent']['pooled']))} %", fontsize=7.6, color=TEXT2, va="top")
    a2.set_xlabel("E[R] je Trade gepoolt (netto, K1)")
    a2.set_ylabel("Anzahl Zellen")
    a2.xaxis.set_major_formatter(FuncFormatter(komma))
    a2.set_title(f"Parameter-Raster ({t4['zellen']} Zellen): {komma(round(100 * t4['anteil_positiv_raster']['pooled'], 1))} % positiv")
    kopf(fig, "Zufallsvergleich und Parameter-Plateau der Trendregel (C1)")
    fuss(fig, "Quelle: ergebnisse/t03_zufall_C1.json, t04_raster_C1.json. Das Raster ist nur ein Stabilitätstest, keine Auswahl; C1 liegt nicht an der Spitze.")
    fig.subplots_adjust(left=0.07, right=0.985, top=0.84, bottom=0.18, wspace=0.22)
    return speichern(fig, ordner, "g5_zufall_und_raster.png")


def g6_register(ordner: Path, register: Path = REGISTER) -> Path:
    d = json.loads(register.read_text(encoding="utf-8"))
    klassen = [("BELASTBAR", SEQ[6]), ("BEDINGT VERWERTBAR", SEQ[4]), ("EXPLORATIV", SEQ[2]), ("NICHT REPRODUZIERBAR", GRAU), ("UNGÜLTIG", GITTER)]
    cluster = [c for c in d["cluster"] if c != "EIGEN"]
    zaehl = {c: {k: 0 for k, _ in klassen} for c in cluster}
    for x in d["eintraege"]:
        if x["cluster"] in zaehl:
            zaehl[x["cluster"]][x["klasse"]] += 1
    summe = {c: sum(v.values()) for c, v in zaehl.items()}
    reihenfolge = sorted(cluster, key=lambda c: summe[c])
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    links = np.zeros(len(reihenfolge))
    y = np.arange(len(reihenfolge))
    for k, farbe in klassen:
        werte = np.array([zaehl[c][k] for c in reihenfolge], float)
        gesamt = sum(sum(zaehl[c].values()) if False else zaehl[c][k] for c in cluster)
        ax.barh(y, werte, left=links, height=0.62, color=farbe, edgecolor=FLAECHE, linewidth=1.5, label=f"{k} ({gesamt})")
        links += werte
    for yi, c in zip(y, reihenfolge):
        ax.text(summe[c] + 0.25, yi, str(summe[c]), va="center", fontsize=8, color=TEXT2)
    ax.set_yticks(y, reihenfolge, fontsize=8.4)
    ax.set_xlim(0, 11.5)
    ax.set_xlabel("Anzahl gefundener Studien und Berichte")
    kopf(fig, "Studienlandschaft: Datencluster und Qualitätsklasse", "Gefundene Studien und Berichte je Datencluster, gefärbt nach Qualitätsklasse.")
    ax.legend(loc="lower right", title="Klasse (Anzahl)", title_fontsize=8, alignment="left")
    fuss(fig, "Quelle: studienregister.json (69 Einträge ohne die 4 eigenen Nachrechnungen). Studien im selben Cluster teilen Daten und sind nicht unabhängig.")
    fig.subplots_adjust(left=0.19, right=0.98, top=0.86, bottom=0.14)
    return speichern(fig, ordner, "g6_studienlandschaft.png")


# ---------------- OFX-Suche -----------------

OFX_DATEIEN = ("lauf1/konfigurationen.jsonl", "lauf2/konfigurationen.jsonl")
X_KANTEN = np.round(np.arange(0.6, 2.61, 0.1), 4)        # log10(n) von n = 4 an; jede Spalte enthält mindestens eine ganze Zahl n
Y_KANTEN = np.round(np.arange(-1.5, 3.51, 0.1), 4)       # Mittel in R


def ofx_aggregat(wurzel: Path) -> dict:
    """Liest die Bestenlisten und verdichtet sie. ``wurzel`` ist ``results/ofx`` der PS5-Kopie."""
    n_alle, m_alle, t_alle = [], [], []
    zeilen, hashes, gruende = 0, {}, {}
    nur_mehrfachtest = 0
    for rel in OFX_DATEIEN:
        pfad = wurzel / rel
        hashes[rel] = hashlib.sha256(pfad.read_bytes()).hexdigest()
        for zeile in pfad.read_text(encoding="utf-8").splitlines():
            if not zeile.strip():
                continue
            z = json.loads(zeile)
            zeilen += 1
            for e in z["beste"]:
                n_alle.append(e["n"]); m_alle.append(e["mean"]); t_alle.append(e["t"])
                if e["n"] >= OFX_N_MIN:
                    for g in e["gruende"]:
                        gruende[g] = gruende.get(g, 0) + 1
                    if e["gruende"] == ["mehrfachtest"]:
                        nur_mehrfachtest += 1
    # Konfigurationen laut state.json aller drei Läufe (lauf1, lauf2, probe); Bestenlisten liegen für lauf1 und lauf2 vor
    configs = 0
    for lauf in ("lauf1", "lauf2", "probe"):
        zustand = json.loads((wurzel / lauf / "state.json").read_text(encoding="utf-8"))
        configs += int(zustand["configs_tried"])
        assert zustand["kandidaten"] == 0, f"{lauf}: Kandidaten {zustand['kandidaten']}"
    n, m, t = np.array(n_alle), np.array(m_alle), np.array(t_alle)
    hx, _, _ = np.histogram2d(np.log10(np.clip(n, 1, None)), m, bins=[X_KANTEN, Y_KANTEN])
    gross = n >= OFX_N_MIN
    kein_n = n <= 3
    ausserhalb = int((~kein_n & ((m < Y_KANTEN[0]) | (m >= Y_KANTEN[-1]) | (np.log10(np.clip(n, 1, None)) >= X_KANTEN[-1]))).sum())
    i_best = int(np.argmax(np.where(gross, m, -9)))
    i_t = int(np.argmax(np.where(gross, t, -1e18)))
    return {
        "quelle_dateien_sha256": hashes, "konfigurationen": configs, "zeilen_mit_bestenliste": zeilen, "eintraege": int(len(n)), "filter_je_konfiguration": 300,
        "varianten_gesamt": configs * 300, "sieb": {"n_min": OFX_N_MIN, "mittel_min_r": OFX_MITTEL_MIN},
        "eintraege_n_ab_130": int(gross.sum()), "eintraege_n_hoechstens_3": int(kein_n.sum()), "eintraege_ausserhalb_der_darstellung": ausserhalb, "median_n": float(np.median(n)),
        "bestes_mittel_bei_n_ab_130": {"mittel": float(m[i_best]), "n": int(n[i_best]), "t": float(t[i_best])},
        "bestes_t_bei_n_ab_130": {"t": float(t[i_t]), "mittel": float(m[i_t]), "n": int(n[i_t])},
        "gruende_bei_n_ab_130": gruende, "eintraege_n_ab_130_nur_mehrfachtest": nur_mehrfachtest, "kandidaten": 0,
        "x_kanten_log10_n": X_KANTEN.tolist(), "y_kanten_mittel": Y_KANTEN.tolist(), "zaehlung": hx.astype(int).tolist(),
    }


def g7_ofx(ordner: Path, erg: Path = ERGEBNISSE) -> Path:
    a = lade("ofx_bestenlisten_aggregat.json", erg)
    h = np.array(a["zaehlung"], float)
    xk, yk = np.array(a["x_kanten_log10_n"]), np.array(a["y_kanten_mittel"])
    from matplotlib.colors import LinearSegmentedColormap, LogNorm
    cmap = LinearSegmentedColormap.from_list("blau", SEQ)
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    ax.grid(False)
    h_plot = np.where(h > 0, h, np.nan)
    gitter = ax.pcolormesh(xk, yk, h_plot.T, cmap=cmap, norm=LogNorm(vmin=1, vmax=np.nanmax(h_plot)), edgecolors=FLAECHE, linewidth=0.3)
    ax.axvline(np.log10(a["sieb"]["n_min"]), color=TEXT2, lw=1.0, ls=(0, (4, 3)))
    ax.axhline(a["sieb"]["mittel_min_r"], color=TEXT2, lw=1.0, ls=(0, (4, 3)))
    ax.axhline(0, color=ACHSE, lw=0.9)
    b = a["bestes_mittel_bei_n_ab_130"]
    ax.plot([np.log10(b["n"])], [b["mittel"]], marker="o", ms=7, color=ORANGE, mec=FLAECHE, mew=1.5, zorder=5)
    ax.annotate(f"bester Wert mit n ≥ {a['sieb']['n_min']}:\n{komma(round(b['mittel'], 2))} R (n {b['n']}, t {komma(round(b['t'], 2))})", xy=(np.log10(b["n"]), b["mittel"]), xytext=(np.log10(b["n"]) + 0.12, b["mittel"] + 1.3),
                fontsize=8, color=TEXT2, ha="left", arrowprops={"arrowstyle": "-", "color": ACHSE, "lw": 0.8})
    ticks = [10, 30, 100, 300, 1000]
    ax.set_xticks([np.log10(t) for t in ticks], [str(t) for t in ticks])
    ax.set_xlim(xk[0], 2.75)
    ax.set_ylim(-1.0, 3.5)
    ax.yaxis.set_major_formatter(FuncFormatter(komma))
    ax.set_xlabel("Zahl der Trades n (logarithmisch)")
    ax.set_ylabel("Mittel je Trade in R (Training 2020–2023)")
    kopf(fig, "OFX-Suche: bester Filter je Konfiguration (Bestenlisten)", "Jeder Eintrag ist ein Filter aus der Top-5-Liste einer Konfiguration; dunkler = mehr Einträge. Training 2020–2023.")
    cb = fig.colorbar(gitter, ax=ax, pad=0.015, fraction=0.04)
    cb.set_label("Einträge je Feld", color=TEXT2, fontsize=8)
    cb.outline.set_visible(False)
    ax.text(0.99, 0.02, "Strichlinien: Sieb n ≥ 130 und Mittel ≥ +0,10 R. Rechts oben wäre Bestehen.", transform=ax.transAxes, ha="right", va="bottom", fontsize=7.6, color=TEXT2)
    fuss(fig, f"Quelle: ergebnisse/ofx_bestenlisten_aggregat.json ({a['konfigurationen']:,} Konfigurationen × 300 Filter, {a['eintraege']:,} Bestenlisten-Einträge; 0 Kandidaten).\n"
              f"Nicht gezeigt: {a['eintraege_n_hoechstens_3']:,} Einträge mit n ≤ 3 und {a['eintraege_ausserhalb_der_darstellung']:,} weitere außerhalb des Ausschnitts.".replace(",", "."))
    fig.subplots_adjust(left=0.08, right=0.92, top=0.86, bottom=0.17)
    return speichern(fig, ordner, "g7_ofx_suche.png")


def g8_t15(ordner: Path, erg: Path = ERGEBNISSE) -> Path:
    """T15 (außerhalb der Entwicklung): kumulierte Netto-R-Summe der Trades 2017–2019 (K2) und Zufallsvergleich (K1)."""
    import matplotlib.dates as mdates
    d = lade("t15_ausserhalb.json", erg)["ergebnis"]
    tr = sorted(d["trades_k2"], key=lambda x: x["ausstieg_ms"])
    zeit = np.array([x["ausstieg_ms"] for x in tr], dtype="int64").astype("datetime64[ms]")
    kum = np.cumsum([x["r"] for x in tr])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.8, 4.2), gridspec_kw={"width_ratios": [1.2, 1]})
    a1.axvspan(np.datetime64("2018-01-01"), np.datetime64("2019-01-01"), color=GITTER, alpha=0.55, lw=0, zorder=0)
    a1.step(zeit, kum, where="post", color=BLAU, lw=1.7)
    a1.axhline(0, color=ACHSE, lw=0.9)
    spitze = np.maximum.accumulate(np.concatenate([[0.0], kum]))[1:]
    tal = int(np.argmax(spitze - kum))
    gipfel = int(np.argmax(kum[: tal + 1]))
    a1.plot([zeit[gipfel], zeit[tal]], [kum[gipfel], kum[tal]], "o", color=ORANGE, ms=4.5, zorder=5)
    a1.text(zeit[tal] + np.timedelta64(12, "D"), kum[tal] - 1.0, f"größter Rückgang {eins(d['p5']['max_drawdown_r'])} R", fontsize=7.8, color=TEXT2, ha="left", va="top")
    a1.set_ylim(-9, 33)
    a1.set_ylabel("kumulierte Summe in R (netto, K2)")
    a1.set_title(f"Handelsverlauf 2017–2019 (Spot): {d['p1']['n']} Trades, Summe {eins(kum[-1])} R")
    for jahr, mitte in ((2017, "2017-11-20"), (2018, "2018-07-02"), (2019, "2019-07-02")):
        je = d["p4"]["je_jahr"][str(jahr)]
        a1.text(np.datetime64(mitte), 32.2, f"{jahr}: n {je['n']}\nE[R] {komma(round(je['e_r'], 2))}", fontsize=7.4, color=TEXT2, ha="center", va="top")
    a1.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 7)))
    a1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%Y"))
    p3 = d["p3"]
    w = np.asarray(p3["e_r_zufall_werte"], float)
    a2.hist(w, bins=np.linspace(-0.2, 0.6, 40), color=GRAU, alpha=0.55, edgecolor=FLAECHE, linewidth=0.8)
    a2.axvline(p3["kandidat_e_r"], color=BLAU, lw=1.4, ls=(0, (4, 3)))
    p_zufall = f"{p3['p_einseitig']:.2f}".replace(".", ",")
    a2.text(0.03, 0.97, f"gestrichelt: C3 {komma(round(p3['kandidat_e_r'], 3))} R\nZufall im Mittel {komma(round(p3['e_r_zufall_mittel'], 3))} R\nEinseitiges p {p_zufall}",
            transform=a2.transAxes, color=TEXT2, fontsize=7.8, va="top", ha="left")
    a2.set_xlabel("E[R] je Trade (netto, K1)")
    a2.set_ylabel("Anzahl von 1.000 Ziehungen")
    a2.xaxis.set_major_formatter(FuncFormatter(komma))
    a2.set_title("Zufallseinstiege in SMA200-Richtung")
    p = d["p1"]["p_monatsblock_bootstrap_einseitig"]
    kopf(fig, "T15: Trendregel C3 außerhalb der Entwicklung (BTC/ETH Spot, 2017-10 bis 2019-12)", f"nicht bestätigt, Richtung positiv: E[R] {komma(round(d['p1']['e_r'], 3))} R, p {komma(round(p, 3))} (Schwelle 0,05)")
    fuss(fig, "Quelle: ergebnisse/t15_ausserhalb.json. Funding aus (keine Historie vor 09.2019). Zufallseinstiege mit gleichen Kosten, Häufigkeit und Positionsgrenze.")
    fig.subplots_adjust(left=0.07, right=0.985, top=0.80, bottom=0.18, wspace=0.22)
    return speichern(fig, ordner, "g8_t15_ausserhalb.png")


def alle(ordner: Path = AUSGABE, erg: Path = ERGEBNISSE) -> list[Path]:
    stil()
    out = [g1_verlauf(ordner, erg), g2_drawdown(ordner, erg), g3_kosten(ordner, erg), g4_stabilitaet(ordner, erg), g5_zufall_raster(ordner, erg), g6_register(ordner)]
    if (erg / "ofx_bestenlisten_aggregat.json").exists():
        out.append(g7_ofx(ordner, erg))
    if (erg / "t15_ausserhalb.json").exists():
        out.append(g8_t15(ordner, erg))
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--ofx":
        agg = ofx_aggregat(Path(sys.argv[2]))
        (ERGEBNISSE / "ofx_bestenlisten_aggregat.json").write_text(json.dumps(agg, ensure_ascii=False) + "\n", encoding="utf-8")
        print({k: v for k, v in agg.items() if k not in ("zaehlung", "x_kanten_log10_n", "y_kanten_mittel")})
    else:
        for p in alle(Path(sys.argv[1]) if len(sys.argv) > 1 else AUSGABE):
            print(p)
