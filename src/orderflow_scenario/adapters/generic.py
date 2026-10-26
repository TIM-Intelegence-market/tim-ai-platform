"""Generic orderflow adapter.

A provider-agnostic adapter that accepts already-normalized structured
dictionaries (e.g. from Binance aggTrades or a generic CSV) and produces an
`AdapterInput`. It performs no heuristics; it only normalizes and validates
structure, and it flags missing fields.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from src.models.market_data import Candle, Trade

from ..positioning import parse_context
from .base import AdapterInput


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        # JSON input carries ISO-8601 strings; accept a trailing "Z" explicitly.
        text = value.strip()
        if text[-1:] in ("Z", "z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"invalid datetime value: {value!r}") from exc
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raise ValueError(f"invalid datetime value: {value!r}")


_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _period_seconds(item: Mapping[str, Any], timeframe: str) -> int:
    """Candle length: explicit `period_seconds`, else the length of the timeframe ("4H" -> 14400)."""
    if item.get("period_seconds") is not None:
        return int(item["period_seconds"])
    count, unit = timeframe[:-1], timeframe[-1:].lower()
    if not count.isdigit() or unit not in _UNIT_SECONDS:
        raise ValueError(f"period_seconds missing and timeframe {timeframe!r} unknown")
    return int(count) * _UNIT_SECONDS[unit]


def _record(item: Candle | Trade) -> dict[str, Any]:
    # AdapterInput carries plain dicts; datetimes as ISO-8601 (read back via fromisoformat).
    return {key: value.isoformat() if isinstance(value, datetime) else value for key, value in asdict(item).items()}


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc


class GenericOrderflowAdapter:
    def __init__(self) -> None:
        self.adapter_kind = "GENERIC_ORDERFLOW"

    def parse_candles(self, items: Mapping[str, Any] | list[Any]) -> tuple[tuple[Candle, ...], tuple[str, ...]]:
        raw = items.get("candles") if isinstance(items, Mapping) else items
        if not isinstance(raw, list):
            raise ValueError("candles must be a list")
        default_timeframe = str(items.get("timeframe", "4H")) if isinstance(items, Mapping) else "4H"
        candles: list[Candle] = []
        missing: list[str] = []
        for index, item in enumerate(raw):
            try:
                open_time = _dt(item.get("open_time"))
                if open_time is None:
                    missing.append(f"candles[{index}].open_time")
                    continue
                timeframe = str(item.get("timeframe", default_timeframe))
                close_time = open_time + timedelta(seconds=_period_seconds(item, timeframe))
                candles.append(
                    Candle(
                        symbol=str(item.get("symbol", "UNKNOWN")),
                        timeframe=timeframe,
                        open_time=open_time,
                        close_time=close_time,
                        open=float(item["open"]),
                        high=float(item["high"]),
                        low=float(item["low"]),
                        close=float(item["close"]),
                        volume=float(item.get("volume", 0.0)),
                        trade_count=int(item.get("trade_count", 0)),
                        closed=bool(item.get("closed", True)),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                missing.append(f"candles[{index}]:{exc}")
        return tuple(candles), tuple(missing)

    def parse_trades(self, items: Mapping[str, Any] | list[Any]) -> tuple[tuple[Trade, ...], tuple[str, ...]]:
        raw = items.get("trades") if isinstance(items, Mapping) else items
        if not raw:
            return (), ("trades",)
        if not isinstance(raw, list):
            raise ValueError("trades must be a list")
        trades: list[Trade] = []
        missing: list[str] = []
        for index, item in enumerate(raw):
            try:
                event_time = _dt(item.get("event_time"))
                if event_time is None:
                    missing.append(f"trades[{index}].event_time")
                    continue
                trades.append(
                    Trade(
                        symbol=str(item.get("symbol", "UNKNOWN")),
                        price=float(item["price"]),
                        quantity=float(item["quantity"]),
                        event_time=event_time,
                        trade_id=int(item["trade_id"]) if item.get("trade_id") is not None else None,
                        buyer_is_maker=bool(item["buyer_is_maker"]) if item.get("buyer_is_maker") is not None else None,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                missing.append(f"trades[{index}]:{exc}")
        return tuple(trades), tuple(missing)

    def adapt(self, data: Mapping[str, Any], observed_at: datetime | None = None) -> AdapterInput:
        observed_at = observed_at or datetime.now(timezone.utc)
        candles, candle_missing = self.parse_candles(data)
        trades, trade_missing = self.parse_trades(data)
        context = parse_context(data)
        missing = tuple(sorted(set(list(candle_missing) + list(trade_missing) + [f"context_rejected:{item}" for item in context.rejected])))
        estimated: list[str] = []
        if data.get("estimated_prices"):
            estimated.extend(str(item) for item in data["estimated_prices"])
        return AdapterInput(
            symbol=str(data.get("symbol", "UNKNOWN")),
            venue=str(data.get("venue", "UNKNOWN")),
            market_type=str(data.get("market_type", "FUTURES")),
            timeframe=str(data.get("timeframe", "4H")),
            observed_at=observed_at,
            candles=tuple(_record(c) for c in candles),
            trades=tuple(_record(t) for t in trades),
            price_now=_dec(data.get("price_now")),
            net_delta=_dec(data.get("net_delta")),
            aggressive_buy_volume=_dec(data.get("aggressive_buy_volume")),
            aggressive_sell_volume=_dec(data.get("aggressive_sell_volume")),
            total_volume=_dec(data.get("total_volume")),
            open_interest_with_price=data.get("open_interest_with_price"),
            delta_divergence=data.get("delta_divergence"),
            delta_series=tuple(_dec(item) for item in data["delta_series"]) if data.get("delta_series") else None,
            structured=True,
            estimated_prices=tuple(estimated),
            positioning=context.positioning,
            profile=context.profile,
            missing_fields=missing,
            extra_notes=tuple(data.get("extra_notes", ())),
        )