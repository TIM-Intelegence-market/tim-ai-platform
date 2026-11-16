"""Unabhängige Nachrechnung von S7 und S7b aus der Präregistrierung.

Regel (S7/S7b, Donchian-Ausbruch in Richtung des SMA200, 4h, USD-M Perpetuals):

* Signal auf der geschlossenen Kerze t: long, wenn Schluss(t) > höchstes Hoch der Kerzen t-N..t-1
  und Schluss(t) > SMA200(t); short spiegelbildlich. Keine Signale, wenn eine der letzten
  max(200, N+1) Kerzen fehlt.
* Risiko R0 = max(1,5 x ATR14(t), 1 % x Schluss(t)); Stop = Schluss(t) -/+ R0; ATR = einfacher
  Mittelwert der True Range über 14 geschlossene Kerzen.
* Einstieg zum Eröffnungskurs der Kerze t+1, adverse Slippage; 1R = |Einstiegskurs - Stop|;
  Ziel = Einstieg +/- T x R; Zeit-Stop zum Schluss der 30. Kerze (Einstiegskerze = 1).
* Innerhalb einer Kerze gewinnt der Stop vor dem Ziel. Lücken über Stop/Ziel füllen zum Eröffnungskurs.
* Funding: Zeitstempel f mit Einstieg <= f < Ausstieg, Seite x Rate x Einstiegskurs je Einheit.
* Positionsgrenze (S7b): höchstens eine offene oder vorgemerkte Position über alle Symbole,
  Reihenfolge bei gleichem Zeitstempel BTC > ETH > SOL; Ausstiege vor Signalen derselben Kerze.

Die Kosten sind parametrisiert (``Kosten``), damit dieselbe Mechanik für Kosten- und
Slippage-Stress benutzt werden kann. Es wird kein Code aus ``src.research_lab.backtest`` benutzt.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from src.research_lab.konsolidierung.daten import MS_4H, SYMBOLE, Funding, Kerzen

TRAIN_ENDE_MS = 1_672_531_200_000   # 2023-01-01T00:00Z (exklusiv)
VALID_ENDE_MS = 1_735_689_600_000   # 2025-01-01T00:00Z (exklusiv)


@dataclass(frozen=True)
class Kosten:
    """Kostenmodell je Seite. Standard = Protokoll 1.3, Abschnitt 4.4 (Basis)."""
    gebuehr: float = 0.0005
    slip_einstieg: float = 0.0003
    slip_ziel: float = 0.0003
    slip_zeit: float = 0.0003
    slip_stop: float = 0.0005
    funding: str = "hist"          # "hist" | "hist_ohne_gutschrift" | "aus"
    funding_faktor: float = 1.0
    verzoegerung_kerzen: int = 0   # zusätzliche Verzögerung des Einstiegs (Latenzstress), in 4h-Kerzen

    def streng(self, faktor: float = 2.0) -> "Kosten":
        """Protokoll-Stress: Gebühr und Slippage verdoppelt, Funding ohne Gutschrift."""
        return replace(self, gebuehr=self.gebuehr * faktor, slip_einstieg=self.slip_einstieg * faktor, slip_ziel=self.slip_ziel * faktor,
                       slip_zeit=self.slip_zeit * faktor, slip_stop=self.slip_stop * faktor, funding="hist_ohne_gutschrift")


BASIS = Kosten()
STRESS = BASIS.streng(2.0)


@dataclass(frozen=True)
class Variante:
    kanal: int      # N (20 oder 55)
    ziel_r: float   # T (3 oder 4)
    zeitstop: int = 30
    atr_faktor: float = 1.5
    mindest_risiko: float = 0.01

    @property
    def name(self) -> str:
        return f"D{self.kanal}-T{int(self.ziel_r)}"


@dataclass
class Trade:
    symbol: str
    seite: int
    signal_zeit: int
    einstieg_zeit: int
    ausstieg_zeit: int
    einstieg: float
    ausstieg: float
    stop: float
    grund: str
    kerzen: int
    brutto_r: float
    kosten_r: float
    funding_r: float
    r: float
    stop_atr: float


@dataclass
class _Reihe:
    sym: str
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    idx: dict
    sig: np.ndarray
    stop_signal: np.ndarray
    atr: np.ndarray


def _rolling_max(x: np.ndarray, n: int) -> np.ndarray:
    """max über die n Werte x[i-n .. i-1] (ausschließlich i); NaN wo nicht verfügbar."""
    out = np.full(len(x), np.nan)
    if len(x) > n:
        win = np.lib.stride_tricks.sliding_window_view(x, n)  # win[j] = x[j..j+n-1]
        out[n:] = win[: len(x) - n].max(axis=1)
    return out


def _rolling_min(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) > n:
        win = np.lib.stride_tricks.sliding_window_view(x, n)
        out[n:] = win[: len(x) - n].min(axis=1)
    return out


def _rolling_mean_incl(x: np.ndarray, n: int) -> np.ndarray:
    """Mittelwert über x[i-n+1 .. i] (einschließlich i)."""
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        win = np.lib.stride_tricks.sliding_window_view(x, n)
        out[n - 1:] = win.mean(axis=1)
    return out


def bereite_vor(k: Kerzen, v: Variante) -> _Reihe:
    t, o, h, l, c = k.t, k.o, k.h, k.l, k.c
    n = len(t)
    prev_c = np.concatenate(([np.nan], c[:-1]))
    tr = np.maximum.reduce([h - l, np.abs(h - prev_c), np.abs(l - prev_c)])
    tr[0] = np.nan
    atr = _rolling_mean_incl(tr, 14)
    sma = _rolling_mean_incl(c, 200)
    hh = _rolling_max(h, v.kanal)
    ll = _rolling_min(l, v.kanal)
    laenge = max(200, v.kanal + 1)
    # Lückenprüfung: die letzten `laenge` Kerzen (inkl. t) müssen lückenlos im 4h-Raster liegen
    kont = np.zeros(n, dtype=bool)
    if n >= laenge:
        kont[laenge - 1:] = (t[laenge - 1:] - t[: n - laenge + 1]) == (laenge - 1) * MS_4H
    gueltig = kont & ~np.isnan(atr) & ~np.isnan(sma) & ~np.isnan(hh) & ~np.isnan(ll)
    lang = gueltig & (c > hh) & (c > sma)
    kurz = gueltig & (c < ll) & (c < sma)
    sig = np.where(lang, 1, np.where(kurz, -1, 0)).astype(np.int8)
    r0 = np.maximum(v.atr_faktor * atr, v.mindest_risiko * c)
    stop_sig = np.where(sig == 1, c - r0, np.where(sig == -1, c + r0, np.nan))
    return _Reihe(k.symbol, t, o, h, l, c, {int(x): i for i, x in enumerate(t)}, sig, stop_sig, atr)


def _funding_summe(ft: np.ndarray, fr: np.ndarray, von: int, bis: int) -> tuple[float, float]:
    """(Summe der Raten, Summe der positiven Raten) für von <= f < bis."""
    a = int(np.searchsorted(ft, von, side="left"))
    b = int(np.searchsorted(ft, bis, side="left"))
    seg = fr[a:b]
    return float(seg.sum()), float(seg[seg > 0].sum())


def simuliere(kerzen: dict[str, Kerzen], funding: dict[str, Funding | None], v: Variante, kosten: Kosten = BASIS,
              portfolio: bool = True, bis_ms: int | None = None) -> list[Trade]:
    """Chronologische Simulation. ``portfolio=True``: höchstens eine Position über alle Symbole (S7b),
    sonst eine Position je Symbol (S7). Gibt alle geschlossenen Trades zurück (zwangsgeschlossene werden nicht gebucht)."""
    reihen = {s: bereite_vor(kerzen[s], v) for s in SYMBOLE if s in kerzen}
    zeiten = np.unique(np.concatenate([r.t for r in reihen.values()]))
    if bis_ms is not None:
        zeiten = zeiten[zeiten < bis_ms]
    trades: list[Trade] = []
    pos: dict[str, dict] = {}       # symbol -> offene Position
    pend: dict[str, dict] = {}      # symbol -> vorgemerkter Einstieg
    verz = kosten.verzoegerung_kerzen

    for T0 in zeiten:
        T0 = int(T0)
        # Phase A: Einstiege füllen, Ausstiege prüfen (alle Symbole in fester Reihenfolge)
        for s in SYMBOLE:
            r = reihen.get(s)
            if r is None:
                continue
            i = r.idx.get(T0, -1)
            p = pend.get(s)
            if p is not None and p["einstieg_zeit"] == T0:
                del pend[s]
                if i < 0:
                    continue  # Einstiegskerze fehlt: Vormerkung verfällt
                seite = p["seite"]
                fill = r.o[i] * (1 + seite * kosten.slip_einstieg)
                stop = p["stop"]
                risiko = (fill - stop) * seite
                if risiko <= 0:
                    # Stop liegt bereits hinter dem Einstieg: voller Verlust zum Stop, 1R nicht definiert -> als -1R plus Kosten gebucht
                    ausstieg = stop * (1 - seite * kosten.slip_stop)
                    kost_r = kosten.gebuehr * (fill + ausstieg) / max(abs(fill - stop), 1e-12)
                    trades.append(Trade(s, seite, p["signal_zeit"], T0, T0 + MS_4H, float(fill), float(ausstieg), float(stop), "stop_vor_einstieg", 1,
                                        -1.0, float(kost_r), 0.0, float(-1.0 - kost_r), p["stop_atr"]))
                    continue
                pos[s] = {"seite": seite, "einstieg": fill, "stop": stop, "risiko": risiko, "ziel": fill + seite * v.ziel_r * risiko,
                          "einstieg_zeit": T0, "signal_zeit": p["signal_zeit"], "kerzen": 0, "stop_atr": p["stop_atr"], "letzter_schluss": fill}
            q = pos.get(s)
            if q is None:
                continue
            if i < 0:
                # Kerze fehlt: zum letzten bekannten Schluss schließen (Lücke)
                _schliesse(trades, pos, s, q, q["letzter_schluss"] * (1 - q["seite"] * kosten.slip_zeit), T0, "gap", funding.get(s), kosten)
                continue
            q["kerzen"] += 1
            seite = q["seite"]
            o, h, l, c = r.o[i], r.h[i], r.l[i], r.c[i]
            stop, ziel = q["stop"], q["ziel"]
            ausstieg = None
            grund = ""
            if seite == 1:
                if o <= stop:
                    ausstieg, grund = o * (1 - kosten.slip_stop), "stop"
                elif l <= stop:
                    ausstieg, grund = stop * (1 - kosten.slip_stop), "stop"
                elif o >= ziel:
                    ausstieg, grund = o * (1 - kosten.slip_ziel), "target"
                elif h >= ziel:
                    ausstieg, grund = ziel * (1 - kosten.slip_ziel), "target"
            else:
                if o >= stop:
                    ausstieg, grund = o * (1 + kosten.slip_stop), "stop"
                elif h >= stop:
                    ausstieg, grund = stop * (1 + kosten.slip_stop), "stop"
                elif o <= ziel:
                    ausstieg, grund = o * (1 + kosten.slip_ziel), "target"
                elif l <= ziel:
                    ausstieg, grund = ziel * (1 + kosten.slip_ziel), "target"
            if ausstieg is None and q["kerzen"] >= v.zeitstop:
                ausstieg, grund = c * (1 - seite * kosten.slip_zeit), "time"
            if ausstieg is not None:
                _schliesse(trades, pos, s, q, ausstieg, T0 + MS_4H, grund, funding.get(s), kosten)
            else:
                q["letzter_schluss"] = c
        # Phase B: Signale auf der soeben geschlossenen Kerze
        for s in SYMBOLE:
            r = reihen.get(s)
            if r is None:
                continue
            i = r.idx.get(T0, -1)
            if i < 0 or r.sig[i] == 0:
                continue
            if portfolio:
                if pos or pend:
                    continue
            else:
                if s in pos or s in pend:
                    continue
            seite = int(r.sig[i])
            pend[s] = {"seite": seite, "stop": float(r.stop_signal[i]), "signal_zeit": T0, "einstieg_zeit": T0 + MS_4H * (1 + verz),
                       "stop_atr": float(abs(r.c[i] - r.stop_signal[i]) / r.atr[i])}
    return trades


def _schliesse(trades: list[Trade], pos: dict, s: str, q: dict, ausstieg: float, ausstieg_zeit: int, grund: str,
               fund: Funding | None, kosten: Kosten) -> None:
    seite = q["seite"]
    risiko = q["risiko"]
    brutto = seite * (ausstieg - q["einstieg"]) / risiko
    kost = kosten.gebuehr * (q["einstieg"] + ausstieg) / risiko
    f_r = 0.0
    if fund is not None and kosten.funding != "aus":
        summe, summe_pos = _funding_summe(fund.t, fund.rate, q["einstieg_zeit"], ausstieg_zeit)
        if kosten.funding == "hist":
            f_r = seite * summe * q["einstieg"] / risiko
        else:  # ohne Gutschrift: nur Zahlungen zählen (je Abrechnung, nicht je Summe)
            a = int(np.searchsorted(fund.t, q["einstieg_zeit"], side="left"))
            b = int(np.searchsorted(fund.t, ausstieg_zeit, side="left"))
            zahl = seite * fund.rate[a:b]
            f_r = float(np.clip(zahl, 0, None).sum()) * q["einstieg"] / risiko
        f_r *= kosten.funding_faktor
    trades.append(Trade(s, seite, q["signal_zeit"], q["einstieg_zeit"], ausstieg_zeit, float(q["einstieg"]), float(ausstieg), float(q["stop"]), grund,
                        q["kerzen"], float(brutto), float(kost), float(f_r), float(brutto - kost - f_r), q["stop_atr"]))
    del pos[s]


def abschnitt(t: Trade) -> str | None:
    """Abschnittsregel 1.2: Signal im Abschnitt und Ausstieg spätestens am Abschnittsende."""
    if t.signal_zeit < TRAIN_ENDE_MS:
        return "train" if t.ausstieg_zeit <= TRAIN_ENDE_MS else None
    if t.signal_zeit < VALID_ENDE_MS:
        return "validation" if t.ausstieg_zeit <= VALID_ENDE_MS else None
    return None
