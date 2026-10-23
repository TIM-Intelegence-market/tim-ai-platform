#!/usr/bin/env python3
"""Bot 1: Scanner. Findet Coins mit starkem Stundenausschlag bei erhöhtem Volumen.

Regel (aus dem Setup, für TIM präzisiert):
- Universum: die `top_n` USDT-Paare von Binance Spot nach 24h-Umsatz (ohne Stablecoins, ohne Hebel-Token).
- Ausschlag: letzte abgeschlossene 1h-Kerze bewegt sich um mehr als `move_pct` Prozent (Close gegen Open).
- Volumen: Umsatz dieser Stunde mindestens `volume_multiple` mal so hoch wie der durchschnittliche
  Stundenumsatz der 7 Tage davor (= Tagesdurchschnitt / 24). Eine Stunde mit dem Tagesumsatz zu
  vergleichen ergäbe fast nie einen Treffer, deshalb diese Lesart.
- Jede Kerze wird pro Coin nur einmal gemeldet, auch wenn der Scanner alle 5 Minuten läuft.

Schreibt nach scanner.csv. Platziert keine Trades.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    LEVERAGED_SUFFIXES,
    STABLE_BASES,
    BinancePublic,
    SnapshotMarket,
    append_rows,
    default_data_dir,
    dt_to_ms,
    iso,
    ms_to_dt,
    read_rows,
    signal_key,
    utc_now,
)

FIELDS = [
    "scanned_at", "symbol", "base", "direction", "move_pct", "hour_quote_volume",
    "avg_hour_quote_volume", "volume_multiple", "close_price", "candle_close_time",
]
LOOKBACK_HOURS = 168


def select_universe(tickers: list[dict], top_n: int) -> list[str]:
    picked = []
    for t in tickers:
        sym = str(t.get("symbol", ""))
        if not sym.endswith("USDT"):
            continue
        base = sym[: -len("USDT")]
        if not base or base in STABLE_BASES or base.endswith(LEVERAGED_SUFFIXES):
            continue
        try:
            qv = float(t.get("quoteVolume", 0))
        except (TypeError, ValueError):
            continue
        if qv <= 0:
            continue
        picked.append((qv, sym))
    picked.sort(reverse=True)
    return [s for _, s in picked[:top_n]]


def closed_candles(klines: list[list], now: datetime) -> list[list]:
    now_ms = dt_to_ms(now)
    return [k for k in klines if int(k[6]) < now_ms]


def evaluate(symbol: str, klines: list[list], now: datetime, move_pct: float, volume_multiple: float) -> dict | None:
    candles = closed_candles(klines, now)
    if len(candles) < 25:  # zu wenig Historie für einen fairen Durchschnitt
        return None
    last, history = candles[-1], candles[-(LOOKBACK_HOURS + 1):-1]
    o, c = float(last[1]), float(last[4])
    if o <= 0:
        return None
    move = (c - o) / o * 100.0
    hour_qv = float(last[7])
    avg_qv = sum(float(k[7]) for k in history) / len(history)
    if avg_qv <= 0:
        return None
    mult = hour_qv / avg_qv
    if abs(move) <= move_pct or mult < volume_multiple:
        return None
    return {
        "symbol": symbol,
        "base": symbol[: -len("USDT")],
        "direction": "up" if move > 0 else "down",
        "move_pct": round(move, 3),
        "hour_quote_volume": round(hour_qv, 2),
        "avg_hour_quote_volume": round(avg_qv, 2),
        "volume_multiple": round(mult, 2),
        "close_price": c,
        "candle_close_time": iso(ms_to_dt(int(last[6]) + 1)),
    }


def scan(market, data_dir: Path, now: datetime | None = None, top_n: int = 100,
         move_pct: float = 3.0, volume_multiple: float = 2.0, log=print) -> list[dict]:
    now = now or utc_now()
    out_path = data_dir / "scanner.csv"
    seen = {signal_key(r["symbol"], r["candle_close_time"]) for r in read_rows(out_path)}
    universe = select_universe(market.tickers_24h(), top_n)
    flags, errors = [], 0
    for sym in universe:
        try:
            kl = market.klines(sym, "1h", LOOKBACK_HOURS + 2)
        except Exception as exc:  # einzelne Coins dürfen ausfallen
            errors += 1
            log(f"  {sym}: Kerzen nicht geladen ({exc})", file=sys.stderr)
            continue
        hit = evaluate(sym, kl, now, move_pct, volume_multiple)
        if hit and signal_key(hit["symbol"], hit["candle_close_time"]) not in seen:
            hit["scanned_at"] = iso(now)
            flags.append(hit)
    append_rows(out_path, FIELDS, flags)
    log(f"Scanner: {len(universe)} Coins geprüft, {len(flags)} neu markiert, {errors} Fehler -> {out_path}")
    for f in flags:
        log(f"  {f['symbol']}: {f['move_pct']:+.2f}% in 1h, Volumen {f['volume_multiple']}x")
    return flags


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=default_data_dir())
    p.add_argument("--snapshot", type=Path, help="Offline-JSON statt Binance-Live-Daten")
    p.add_argument("--top", type=int, default=100)
    p.add_argument("--move-pct", type=float, default=3.0)
    p.add_argument("--volume-multiple", type=float, default=2.0)
    a = p.parse_args(argv)
    market = SnapshotMarket.from_file(a.snapshot) if a.snapshot else BinancePublic()
    scan(market, a.data_dir, top_n=a.top, move_pct=a.move_pct, volume_multiple=a.volume_multiple)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
