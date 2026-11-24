"""Eigener, unabhängiger Lader für die Binance-Archive (USD-M Futures, Spot, Funding).

Liest die monatlichen ZIP-Dateien aus einem Verzeichnis mit der Struktur des Lab-Archivs:
``futures_um/klines/<SYM>/<iv>/<SYM>-<iv>-YYYY-MM.zip``, ``futures_um/fundingRate/<SYM>/8h/...``,
``spot/klines/<SYM>/1h/...``. AppleDouble-Dateien (``._*``) werden übersprungen.

Holdout-Schutz: Es werden nur Monate vor ``HOLDOUT_START_MS`` (2025-01-01 UTC) gelesen. Ein
Aufruf mit späterem ``bis`` wird abgelehnt. Das ist eine zusätzliche Schranke zum Protokoll
(1.3, Abschnitt Holdout), keine Ersatzregel.
"""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HOLDOUT_START_MS = 1_735_689_600_000  # 2025-01-01T00:00:00Z
MS_4H = 4 * 3_600_000
MS_1H = 3_600_000

SYMBOLE = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


class HoldoutVerweigert(RuntimeError):
    """Die Anfrage reicht in den versiegelten Holdout (ab 2025-01-01)."""


@dataclass(frozen=True)
class Kerzen:
    symbol: str
    intervall: str
    t: np.ndarray        # Öffnungszeit in ms (int64), aufsteigend, ohne Duplikate
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    taker_buy: np.ndarray
    roh_zeilen: int      # Zeilen vor Dedup/Sortierung
    duplikate: int
    unsortiert: int


def _monate(von: str, bis: str):
    y, m = int(von[:4]), int(von[5:7])
    y2, m2 = int(bis[:4]), int(bis[5:7])
    while (y, m) <= (y2, m2):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def _zeilen(text: str) -> list[list[str]]:
    rows = [r for r in csv.reader(io.StringIO(text)) if r]
    if rows and not rows[0][0].strip().lstrip("-").isdigit():
        rows = rows[1:]
    return rows


def _pruefe_holdout(bis: str) -> None:
    jahr = int(bis[:4])
    if jahr >= 2025:
        raise HoldoutVerweigert(f"bis={bis} reicht in den Holdout (ab 2025-01-01); verweigert")


def laden(wurzel: str | Path, markt: str, symbol: str, intervall: str, von: str = "2020-01", bis: str = "2024-12") -> Kerzen | None:
    """Liest Kerzen eines Marktes ('futures_um' oder 'spot'). Fehlende Monatsdateien werden übersprungen."""
    _pruefe_holdout(bis)
    wurzel = Path(wurzel)
    zeilen_alle: list[list[str]] = []
    for ym in _monate(von, bis):
        datei = wurzel / markt / "klines" / symbol / intervall / f"{symbol}-{intervall}-{ym}.zip"
        if not datei.exists():
            continue
        with zipfile.ZipFile(datei) as z:
            namen = [n for n in z.namelist() if n.endswith(".csv")]
            if len(namen) != 1:
                raise ValueError(f"{datei}: genau eine CSV erwartet")
            zeilen_alle.extend(_zeilen(z.read(namen[0]).decode("utf-8")))
    if not zeilen_alle:
        return None
    arr = np.array([[float(x) for x in r[:10]] for r in zeilen_alle], dtype=np.float64)
    t = arr[:, 0].astype(np.int64)
    roh = len(t)
    unsortiert = int(np.sum(np.diff(t) < 0))
    reihenfolge = np.argsort(t, kind="stable")
    arr = arr[reihenfolge]
    t = t[reihenfolge]
    keep = np.ones(len(t), dtype=bool)
    keep[1:] = np.diff(t) != 0
    duplikate = int((~keep).sum())
    arr, t = arr[keep], t[keep]
    if len(t) and t[-1] >= HOLDOUT_START_MS:
        raise HoldoutVerweigert("Daten ab 2025-01-01 gelesen; verweigert")
    return Kerzen(symbol, intervall, t, arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], arr[:, 5], arr[:, 9], roh, duplikate, unsortiert)


@dataclass(frozen=True)
class Funding:
    symbol: str
    t: np.ndarray    # Rohzeitstempel (calc_time, ms) wie im Archiv
    rate: np.ndarray
    roh_zeilen: int
    duplikate: int


def laden_funding(wurzel: str | Path, symbol: str, von: str = "2020-01", bis: str = "2024-12") -> Funding | None:
    _pruefe_holdout(bis)
    wurzel = Path(wurzel)
    zeilen_alle: list[list[str]] = []
    for ym in _monate(von, bis):
        datei = wurzel / "futures_um" / "fundingRate" / symbol / "8h" / f"{symbol}-fundingRate-{ym}.zip"
        if not datei.exists():
            continue
        with zipfile.ZipFile(datei) as z:
            namen = [n for n in z.namelist() if n.endswith(".csv")]
            zeilen_alle.extend(_zeilen(z.read(namen[0]).decode("utf-8")))
    if not zeilen_alle:
        return None
    t = np.array([int(r[0]) for r in zeilen_alle], dtype=np.int64)
    rate = np.array([float(r[2]) for r in zeilen_alle], dtype=np.float64)
    roh = len(t)
    order = np.argsort(t, kind="stable")
    t, rate = t[order], rate[order]
    keep = np.ones(len(t), dtype=bool)
    keep[1:] = np.diff(t) != 0
    return Funding(symbol, t[keep], rate[keep], roh, int((~keep).sum()))
