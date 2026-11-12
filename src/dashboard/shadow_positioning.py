"""Positionierung zum Planzeitpunkt für den Schatten-Score (TIM-Gehirn, Uzi 12.11.2026).

Funding und Open Interest von Binance (öffentlich, ohne Schlüssel), jeweils nur bis zum Moment des Plans:
``endTime`` auf den Planzeitpunkt, und es werden nur Punkte bis dahin genommen (kein Blick in die Zukunft).
Das Ergebnis geht als ``PositioningInputs`` in den zweiten Pipeline-Lauf. Es entscheidet nichts.
Fehlt ein Teil oder schlägt ein Abruf fehl, bleibt der Teil leer; sind beide leer, gibt es ``None``.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from src.dashboard.market_context import FAPI, Fetch, _url, fetch_json
from src.orderflow_scenario.positioning import MAX_FUNDING_ABS, PositioningInputs

OI_POINTS = 8  # hourly points up to the plan, enough for the trend over a few hours


def _ms(at: datetime) -> str:
    return str(int(at.timestamp() * 1000))


def _funding(fetch: Fetch, symbol: str, at: datetime) -> Decimal | None:
    rows = fetch(_url(FAPI, "/fapi/v1/fundingRate", {"symbol": symbol, "endTime": _ms(at), "limit": "1"}))
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[-1]
    if int(row["fundingTime"]) > int(at.timestamp() * 1000):
        return None
    rate = Decimal(str(row["fundingRate"]))
    return rate if rate.is_finite() and abs(rate) <= MAX_FUNDING_ABS else None


def _open_interest(fetch: Fetch, symbol: str, at: datetime) -> tuple[tuple[datetime, Decimal], ...]:
    rows = fetch(_url(FAPI, "/futures/data/openInterestHist",
                      {"symbol": symbol, "period": "1h", "endTime": _ms(at), "limit": str(OI_POINTS)}))
    if not isinstance(rows, list):
        return ()
    points: dict[datetime, Decimal] = {}
    for row in rows:
        try:
            stamp = datetime.fromtimestamp(int(row["timestamp"]) / 1000, tz=timezone.utc)
            value = Decimal(str(row["sumOpenInterest"]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
        if stamp <= at and value.is_finite() and value >= 0:
            points[stamp] = value
    return tuple(sorted(points.items()))


def positioning_at(symbol: str, at: datetime, fetch: Fetch | None = None) -> PositioningInputs | None:
    """Funding and open interest as they stood at ``at``; ``None`` when neither could be read."""
    fetch = fetch or fetch_json
    funding: Decimal | None = None
    oi: tuple[tuple[datetime, Decimal], ...] = ()
    try:
        funding = _funding(fetch, symbol, at)
    except Exception:  # noqa: BLE001 - one source failing must not drop the other
        funding = None
    try:
        oi = _open_interest(fetch, symbol, at)
    except Exception:  # noqa: BLE001
        oi = ()
    if funding is None and len(oi) < 2:
        return None
    return PositioningInputs(funding_rate=funding, open_interest=oi if len(oi) >= 2 else ())


def describe(positioning: PositioningInputs | None) -> Mapping[str, Any]:
    """What went into the shadow, for the journal."""
    if positioning is None:
        return {"funding": None, "oi_points": 0}
    return {"funding": None if positioning.funding_rate is None else float(positioning.funding_rate),
            "oi_points": len(positioning.open_interest)}
