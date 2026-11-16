"""Funding-Carry (T11): Spot long, Perp short, gleiche Stückzahl, BTC und ETH gleichgewichtet, ein Einstieg, kein Nachjustieren (Protokoll C2).

Annahmen und Grenzen (siehe Protokoll Abschnitt 2 und 4, TESTLOG):

* Preise: Binance Spot 1h und USD-M Perp 1h; Funding: Binance-Historie (Stellvertreter für Bitunix, dessen Funding-Historie nicht vorliegt).
* Funding wird je Abrechnung mit Stückzahl x Perp-Eröffnungskurs der Abrechnungsstunde bewertet (Näherung des Mark-Preises).
* Kosten: vier Füllungen (Einstieg Spot und Perp, Ausstieg Spot und Perp), je Füllung Gebühr + Schlupf vom Füllungs-Notional (wie S33).
  Die Spot-Gebühr von Bitunix ist nicht bestätigt; Standard = 0,06 %, Sensitivität 0,10 %.
* Kapital = Spot-Notional + Perp-Marge (Marge 100 % des Notionals wie S33: "beide Beine voll"; 50 % und 20 % als Sensitivität).
* Konstante Stückzahl ohne Nachschuss ist bei steigenden Kursen nicht ausführbar: die Berichtszahlen zum Liquidationsabstand zeigen,
  wann die Marge aufgebraucht wäre. Die Renditerechnung setzt idealisiert unbegrenzten Nachschuss aus dem Spot-Gewinn voraus.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.research_lab.konsolidierung import daten
from src.research_lab.konsolidierung.daten import MS_1H, Funding, Kerzen

TAG_MS = 86_400_000


@dataclass(frozen=True)
class CarryKosten:
    gebuehr_perp: float = 0.0006
    gebuehr_spot: float = 0.0006
    schlupf: float = 0.0003


def lade(wurzel: str, symbol: str) -> tuple[Kerzen, Kerzen, Funding]:
    spot = daten.laden(wurzel, "spot", symbol, "1h")
    perp = daten.laden(wurzel, "futures_um", symbol, "1h")
    fund = daten.laden_funding(wurzel, symbol)
    if spot is None or perp is None or fund is None:
        raise FileNotFoundError(f"Carry-Daten für {symbol} unvollständig")
    return spot, perp, fund


def _spot_auf_raster(spot: Kerzen, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """Spot-Eröffnung/Schluss auf dem Perp-Stundenraster; fehlende Stunden = letzter bekannter Schluss (zählt als Lücke)."""
    idx = np.searchsorted(spot.t, t, side="right") - 1
    idx = np.clip(idx, 0, len(spot.t) - 1)
    exakt = spot.t[idx] == t
    o = np.where(exakt, spot.o[idx], spot.c[idx])
    c = spot.c[idx]
    return o, c, int((~exakt).sum())


def carry_lauf(spot: Kerzen, perp: Kerzen, fund: Funding, von_ms: int, bis_ms: int, kosten: CarryKosten = CarryKosten(), marge: float = 1.0,
               nachjustieren: str | None = None) -> dict:
    """Ein Carry-Lauf für ein Instrument. Kapitalbasis = 1 (Spot) + ``marge`` (Perp-Marge), Notional je Bein = 1 am Anfang.
    ``nachjustieren``: None = konstante Stückzahl (Protokoll), "monat" = jeden Monatsersten auf gleiches Notional je Bein (nur Sensitivität)."""
    m = (perp.t >= von_ms) & (perp.t < bis_ms)
    t = perp.t[m]
    po, pc, ph, pl = perp.o[m], perp.c[m], perp.h[m], perp.l[m]
    so, sc, luecken = _spot_auf_raster(spot, t)
    n = len(t)
    # Funding-Abrechnungen im Fenster: Gutschrift in der Stunde, die um den Abrechnungszeitpunkt beginnt
    # Die Rohzeitstempel haben Millisekunden-Jitter (siehe Datenaudit); auf die nächste volle Stunde runden
    f_rund = np.round(fund.t / MS_1H).astype(np.int64) * MS_1H
    fm = (f_rund >= von_ms) & (f_rund < bis_ms)
    f_t, f_r = f_rund[fm], fund.rate[fm]
    f_idx = np.searchsorted(t, f_t)
    ok = (f_idx < n) & (t[np.clip(f_idx, 0, n - 1)] == f_t)
    f_idx, f_r_ok = f_idx[ok], f_r[ok]
    nicht_zugeordnet = int(len(f_t) - len(f_idx))
    kosten_fuell = lambda notional_spot, notional_perp: notional_spot * (kosten.gebuehr_spot + kosten.schlupf) + notional_perp * (kosten.gebuehr_perp + kosten.schlupf)
    kapital = 1.0 + marge
    funding_stunde = np.zeros(n)
    kost_pfad = np.zeros(n)          # kumulierte Kosten (Einstieg bei h=0, Nachjustierung, Ausstieg am Ende nur im Endwert)
    pnl_preis = np.zeros(n)          # Preis-/Basis-Ergebnis zum Schluss jeder Stunde (kumuliert)
    if nachjustieren is None:
        u_s = 1.0 / so[0]
        u_p = u_s  # gleiche Stückzahl
        pnl_preis = u_s * (sc - so[0]) - u_p * (pc - po[0])
        funding_stunde[f_idx] += f_r_ok * u_p * po[f_idx]
        kost_pfad += kosten_fuell(u_s * so[0], u_p * po[0])
        ausstieg = kosten_fuell(u_s * sc[-1], u_p * pc[-1])
    else:
        monat = (t // (30 * TAG_MS)).astype(np.int64)  # Näherung: 30-Tage-Blöcke
        starts = np.concatenate(([0], np.nonzero(np.diff(monat))[0] + 1))
        u_s_alt = u_p_alt = None
        kum_preis = 0.0
        pnl_preis = np.zeros(n)
        u_s_arr = np.zeros(n)
        u_p_arr = np.zeros(n)
        grenzen = list(starts) + [n]
        for a, b in zip(grenzen[:-1], grenzen[1:]):
            u_s = 1.0 / so[a]
            u_p = 1.0 / po[a]
            if u_s_alt is None:
                kost_pfad[a:] += kosten_fuell(1.0, 1.0)
            else:
                # Neugewichtung: Notional beider Beine zum Wert der neuen Stückzahlen
                kost_pfad[a:] += (abs(u_s - u_s_alt) * so[a]) * (kosten.gebuehr_spot + kosten.schlupf) + (abs(u_p - u_p_alt) * po[a]) * (kosten.gebuehr_perp + kosten.schlupf)
            pnl_preis[a:b] = kum_preis + u_s * (sc[a:b] - so[a]) - u_p * (pc[a:b] - po[a])
            kum_preis = float(pnl_preis[b - 1])
            u_s_arr[a:b] = u_s
            u_p_arr[a:b] = u_p
            u_s_alt, u_p_alt = u_s, u_p
        funding_stunde[f_idx] += f_r_ok * u_p_arr[f_idx] * po[f_idx]
        ausstieg = kosten_fuell(u_s_arr[-1] * sc[-1], u_p_arr[-1] * pc[-1])
    funding_kum = np.cumsum(funding_stunde)
    kost_kum = kost_pfad
    konto = pnl_preis + funding_kum - kost_kum
    konto_end = konto.copy()
    konto_end[-1] -= ausstieg
    # größter Rückgang (stündlich, in Anteilen des Kapitals)
    k = konto_end / kapital
    spitze = np.maximum.accumulate(np.concatenate(([0.0], k)))[1:]
    max_dd = float((spitze - k).max())
    jahre = (bis_ms - von_ms) / (365.0 * TAG_MS)
    gesamt = float(konto_end[-1] / kapital)
    # Rückgang tagesbasiert für die Tagesreihe der Kombination
    tag_idx = (t + MS_1H - 1) // TAG_MS
    ts = np.unique(tag_idx)
    tag_end = np.array([konto_end[tag_idx == d][-1] for d in ts]) / kapital
    tag_diff = np.diff(np.concatenate(([0.0], tag_end)))
    basis_bp = (pc - sc) / sc * 1e4
    out = {
        "von_ms": int(von_ms), "bis_ms": int(bis_ms), "stunden": int(n), "spot_luecken_stunden": luecken, "kapitalbasis": kapital, "marge": marge,
        "nachjustieren": nachjustieren or "nie",
        "funding_summe_anteil_kapital": float(funding_kum[-1] / kapital), "preis_basis_anteil_kapital": float(pnl_preis[-1] / kapital),
        "kosten_anteil_kapital": float((kost_kum[-1] + ausstieg) / kapital),
        "netto_rendite_gesamt": gesamt, "netto_rendite_je_jahr": gesamt / jahre, "max_rueckgang_anteil_kapital": max_dd,
        "basis_bp": {"mittel": float(basis_bp.mean()), "sd": float(basis_bp.std()), "p01": float(np.percentile(basis_bp, 1)), "p99": float(np.percentile(basis_bp, 99)),
                     "min": float(basis_bp.min()), "max": float(basis_bp.max())},
        "funding_abrechnungen": int(len(f_idx)), "funding_nicht_zugeordnet": nicht_zugeordnet, "funding_mittel_je_abrechnung": float(f_r_ok.mean()) if len(f_r_ok) else None,
        "funding_anteil_positiv": float((f_r_ok > 0).mean()) if len(f_r_ok) else None,
        "tagesreihe": (ts, tag_diff),
    }
    # Je Kalenderjahr (aus der Tagesreihe, nicht aufgezinst)
    jahr_tag = (ts * TAG_MS)
    jahre_dt = np.array([int(np.datetime64(int(x), "ms").astype("datetime64[Y]").astype(int)) + 1970 for x in jahr_tag])
    out["je_jahr_anteil_kapital"] = {str(int(y)): float(tag_diff[jahre_dt == y].sum()) for y in np.unique(jahre_dt)}
    # Liquidationsabstand der konstanten Stückzahl: höchster Anstieg des Perp-Preises seit Einstieg
    if nachjustieren is None:
        anstieg = ph / po[0] - 1.0
        lauf_max = np.maximum.accumulate(anstieg)
        liq = {}
        for mg in (0.2, 0.5, 1.0):
            hit = np.nonzero(lauf_max >= mg)[0]
            liq[f"marge_{int(mg * 100)}"] = {"erstmals_erreicht_utc": (str(np.datetime64(int(t[hit[0]]), "ms"))[:16] + "Z") if len(hit) else None,
                                             "tage_nach_einstieg": float((t[hit[0]] - t[0]) / TAG_MS) if len(hit) else None}
        out["liquidationsabstand"] = {"max_anstieg_perp_seit_einstieg": float(lauf_max[-1]), "nachschussbedarf_anteil_notional": float(lauf_max[-1]), **liq}
    return out
