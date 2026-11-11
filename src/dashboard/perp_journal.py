"""Perp-Schatten: TIM's 15m and 1h plan rule on perpetual candles with a volume profile from real perp trades.

Master-Analyse 09.11.2026 (Kundensicht Broncx, P1c + P5; Uzi: "das muss unbedingt gefixt werden"). The paper
journals SHORT (15m) and MID (1h) price everything on Binance spot candles and estimate POC/VAH/VAL from candles,
while the account trades Kraken perpetuals and the trader reads the chart on the perp. This shadow runs the same
rule (plan_journal.update, tim/1) a second time:

- candles from the Binance USD-M perpetual (BTCUSDT, ``chart_live.PERP_CACHE``, closed candles only),
- the volume profile the scenario engine reads (poc/vah/val) from the real perp trades
  (``DashboardState.perp_flow``, footprint_data.profile_from_rows) over the plan window,
- its own files ``tim_plan_journal_perp_short.json`` / ``..._perp_mid.json``, same event log and rules.

Nothing here trades or touches the spot journals or the live trader. Judgement: compare the two journals
after enough closed plans (plan_journal summary), by Uzi.

Monero (Barti 11.11.2026, "tim soll mit xmr genau das machen wie mit btc"): the same step with
``symbol="XMRUSDT"`` writes the XMR journals ``tim_plan_journal_xmr_15m.json`` / ``..._xmr_1h.json`` (XMR_PATHS),
from XMR perp candles and the XMR perp trades (``DashboardState.perp_flows["XMRUSDT"]``). Binance has no XMR spot
market, so these are XMR's main journals, not a shadow. Separate files, separate event logs: a failing XMR step
never touches a BTC file, and the BTC call is unchanged. XMR plans are marked USD-M (shorts executable) and carry
no BTC evidence from the register (plan_journal.with_evidence).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SOURCE = "Setup-Pfad auf Binance USD-M Perp (BTCUSDT), VP aus Perp-Trades, TIM-Regeln, nur Papier (Schatten)"
PATHS = {"15m": Path("data/journal/tim_plan_journal_perp_short.json"), "1h": Path("data/journal/tim_plan_journal_perp_mid.json")}
XMR = "XMRUSDT"
XMR_SOURCE = "Monero auf Binance USD-M Perp (XMRUSDT), VP aus Perp-Trades, TIM-Regeln, nur Papier"
XMR_PATHS = {"15m": Path("data/journal/tim_plan_journal_xmr_15m.json"), "1h": Path("data/journal/tim_plan_journal_xmr_1h.json")}
# Per symbol: the view's source line and the market type of new plans (None keeps BTC exactly as before).
SOURCES = {"BTCUSDT": (SOURCE, None), XMR: (XMR_SOURCE, "USDM")}
# What plan_journal.update reads: 1m for fills and stops, the plan timeframes, the rest for levels and vol_4h.
SERIES = {"1m": 1000, "15m": 500, "30m": 500, "1h": 500, "4h": 500, "1d": 500}


def perp_series(cache: Any, symbol: str = "BTCUSDT") -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Closed perpetual candles per timeframe in the runtime's series shape, plus fetch errors."""
    series: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    for timeframe, limit in SERIES.items():
        rows, error = cache.get(symbol, timeframe, limit)
        if error:
            errors.append(f"{timeframe}: {error}")
        closed = [dict(r, timeframe=timeframe) for r in rows if r.get("closed", True)]
        if closed:
            series[timeframe] = closed
    return series, errors


def trade_profile(store: Mapping[str, Any] | None, candles: Sequence[Mapping[str, Any]], at: datetime) -> dict[str, Any] | None:
    """Volume profile (poc/vah/val) from the perp trade rows inside the plan window; None when the store
    does not cover the window (the engine then estimates from candles, as the spot journals do)."""
    if not store or not store.get("days") or not candles:
        return None
    from src.dashboard.footprint_data import profile_from_rows

    start = int(candles[0]["open_time"].timestamp())
    end = int(min(candles[-1]["close_time"], at).timestamp())
    rows = [row for day in store["days"].values() for row in day if start <= int(row[0]) < end]
    if not rows:
        return None
    first = min(int(row[0]) for row in rows)
    if first - start > 2 * int(store.get("bucket_seconds") or 300):
        return None  # the store starts inside the window: a partial profile would mislead
    profile = profile_from_rows(rows, float(store["tick"]))
    if not profile:
        return None
    return {"poc": profile.get("poc_mid", profile["poc"]), "vah": profile["vah"], "val": profile["val"],
            "source": f"Perp-Trades {len(rows)} Buckets", "rows": len(rows)}


def update(cache: Any, store: Mapping[str, Any] | None, now: datetime | None = None, paths: Mapping[str, Path] | None = None,
           symbol: str = "BTCUSDT") -> dict[str, Any]:
    """One step for both perp shadow journals. Returns a small status (per timeframe: plans or the reason it skipped)."""
    from src.dashboard.plan_journal import update as update_plan_journal

    if symbol not in SOURCES:
        raise ValueError(f"no perp journal for {symbol}")
    now = now or datetime.now(timezone.utc)
    source, market_type = SOURCES[symbol]
    paths = paths or (XMR_PATHS if symbol == XMR else PATHS)
    if symbol != "BTCUSDT" and set(map(Path, paths.values())) & set(PATHS.values()):
        raise ValueError("an XMR journal must not write into the BTC perp journal files")
    series, errors = perp_series(cache, symbol)
    status: dict[str, Any] = {"errors": errors, "journals": {}}
    for timeframe, path in paths.items():
        if not series.get(timeframe) or not series.get("1m"):
            status["journals"][timeframe] = {"skipped": "keine Perp-Kerzen"}
            continue
        journal = update_plan_journal(path, series, now, timeframe=timeframe, source=source, market_type=market_type,
                                      profile_fn=lambda candles, at, _store=store: trade_profile(_store, candles, at))
        status["journals"][timeframe] = {"plans": len(journal.get("entries") or []), "last_plan_candle": journal.get("last_plan_candle")}
    return status
