"""Generic orderflow adapter.

A provider-agnostic adapter that accepts already-normalized structured
dictionaries (e.g. from Binance aggTrades or a generic CSV) and produces an
`AdapterInput`. It performs no heuristics; it only normalizes and validates
structure, and it flags missing fields.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from src.models.market_data import Candle, Trade

from .base import AdapterInput


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raise ValueError(f"invalid datetime value: {value!r}")


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
        candles: list[Candle] = []
        missing: list[str] = []
        for index, item in enumerate(raw):
            try:
                open_time = _dt(item.get("open_time"))
                if open_time is None:
                    missing.append(f"candles[{index}].open_time")
                    continue
                period_seconds = int(item.get("period_seconds", 240))
                close_time = open_time + timedelta(seconds=period_seconds)
                candles.append(
                    Candle(
                        symbol=str(item.get("symbol", "UNKNOWN")),
                        timeframe=str(item.get("timeframe", "4H")),
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
        missing = tuple(sorted(set(list(candle_missing) + list(trade_missing))))
        estimated: list[str] = []
        if data.get("estimated_prices"):
            estimated.extend(str(item) for item in data["estimated_prices"])
        return AdapterInput(
            symbol=str(data.get("symbol", "UNKNOWN")),
            venue=str(data.get("venue", "UNKNOWN")),
            market_type=str(data.get("market_type", "FUTURES")),
            timeframe=str(data.get("timeframe", "4H")),
            observed_at=observed_at,
            candles=tuple(c.to_dict() for c in candles),
            trades=tuple(t.to_dict() for t in trades),
            price_now=_dec(data.get("price_now")),
            net_delta=_dec(data.get("net_delta")),
            aggressive_buy_volume=_dec(data.get("aggressive_buy_volume")),
            aggressive_sell_volume=_dec(data.get("aggressive_sell_volume")),
            total_volume=_dec(data.get("total_volume")),
            open_interest_with_price=data.get("open_interest_with_price"),
            delta_divergence=data.get("delta_divergence"),
            structured=True,
            estimated_prices=tuple(estimated),
            missing_fields=missing,
            extra_notes=tuple(data.get("extra_notes", ())),
        )