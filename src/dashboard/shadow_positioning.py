"""Positionierung zum Planzeitpunkt für den Schatten-Score (TIM-Gehirn, Uzi 12.11.2026).

Funding und Open Interest von Binance (öffentlich, ohne Schlüssel), jeweils nur bis zum Moment des Plans:
``endTime`` auf den Planzeitpunkt, und es werden nur Punkte bis dahin genommen (kein Blick in die Zukunft).
Das Ergebnis geht als ``PositioningInputs`` in den zweiten Pipeline-Lauf. Es entscheidet nichts.
Fehlt ein Teil oder schlägt ein Abruf fehl, bleibt der Teil leer; sind beide leer, gibt es ``None``.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError

from src.dashboard.market_context import FAPI, Fetch, _url, fetch_json
from src.orderflow_scenario.positioning import MAX_FUNDING_ABS, PositioningInputs

OI_POINTS = 8  # hourly points up to the plan, enough for the trend over a few hours
FUNDING_LOOKBACK = timedelta(hours=9)  # one settlement every 8 h: the newest one must lie within this
BUDGET_SECONDS = 15.0  # if the first call took this long, the second is skipped
BAN_PAUSE_SECONDS = 900.0  # after HTTP 429/418 no call for 15 minutes
CACHE_SIZE = 8

_blocked_until = 0.0
_cache: dict[tuple[str, int], PositioningInputs | None] = {}


def _ms(at: datetime) -> str:
    return str(int(at.timestamp() * 1000))


def _funding(fetch: Fetch, symbol: str, at: datetime) -> Decimal | None:
    rows = fetch(_url(FAPI, "/fapi/v1/fundingRate", {"symbol": symbol, "startTime": _ms(at - FUNDING_LOOKBACK),
                                                    "endTime": _ms(at), "limit": "3"}))
    if not isinstance(rows, list):
        return None
    best: tuple[int, Decimal] | None = None
    for row in rows:
        try:
            when = int(row["fundingTime"])
            rate = Decimal(str(row["fundingRate"]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
        if when > int(at.timestamp() * 1000) or not rate.is_finite():
            continue  # a settlement after the plan is not used
        if best is None or when > best[0]:
            best = (when, rate)
    return best[1] if best is not None and abs(best[1]) <= MAX_FUNDING_ABS else None


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
    """Funding and open interest as they stood at ``at``; ``None`` when neither could be read.

    The answer is cached per (symbol, plan moment): the journals of one close ask for the same moment."""
    global _blocked_until
    key = (symbol, int(at.timestamp()))
    if fetch is None and key in _cache:
        return _cache[key]
    if fetch is None and time.monotonic() < _blocked_until:
        return None
    use = fetch or fetch_json
    started = time.monotonic()
    funding: Decimal | None = None
    oi: tuple[tuple[datetime, Decimal], ...] = ()
    try:
        funding = _funding(use, symbol, at)
    except HTTPError as error:
        if error.code in (418, 429):
            _blocked_until = time.monotonic() + BAN_PAUSE_SECONDS
            return None
    except Exception:  # noqa: BLE001 - one source failing must not drop the other
        funding = None
    if time.monotonic() - started < BUDGET_SECONDS:
        try:
            oi = _open_interest(use, symbol, at)
        except HTTPError as error:
            if error.code in (418, 429):
                _blocked_until = time.monotonic() + BAN_PAUSE_SECONDS
        except Exception:  # noqa: BLE001
            oi = ()
    result = None if funding is None and len(oi) < 2 else PositioningInputs(funding_rate=funding, open_interest=oi if len(oi) >= 2 else ())
    if fetch is None:
        if len(_cache) >= CACHE_SIZE:
            _cache.pop(next(iter(_cache)))
        _cache[key] = result
    return result
