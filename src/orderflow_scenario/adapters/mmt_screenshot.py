"""MMT screenshot adapter.

A screenshot is never treated as fully structured market data. This adapter
extracts *only* what is explicitly provided in the parsed screenshot payload
and marks every reading as estimated. Values that could not be read are listed
as missing and are never invented. Confidence is deliberately suppressed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from src.models.market_data import Candle

from ..positioning import parse_context
from .base import AdapterInput
from .generic import _dt, _period_seconds


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


class MMTScreenshotAdapter:
    def __init__(self, default_confidence: float = 0.55) -> None:
        if not (0 <= default_confidence <= 1):
            raise ValueError("default_confidence must be within [0,1]")
        self.default_confidence = default_confidence
        self.adapter_kind = "MMT_SCREENSHOT"

    def adapt(self, data: Mapping[str, Any], observed_at: datetime | None = None) -> AdapterInput:
        """`data` is a *parsed* screenshot payload (values already OCR/vision read).

        This adapter does not perform OCR; it strictly normalizes a parsed
        payload and marks every price as estimated.
        """
        observed_at = observed_at or datetime.now(timezone.utc)
        price_now = _dec(data.get("price_now"))
        estimated: list[str] = ["price_now"]
        if not isinstance(data.get("symbol"), str) or not data.get("symbol"):
            raise ValueError("MMT screenshot payload requires symbol")

        candles_raw = data.get("candles") or []
        candles: list[dict[str, Any]] = []
        rejected: list[str] = []
        for index, item in enumerate(candles_raw):
            try:
                open_time = _dt(item["open_time"])
                if open_time is None:
                    rejected.append(f"candles[{index}].open_time")
                    continue
                timeframe = str(item.get("timeframe", data.get("timeframe", "4H")))
                period_seconds = _period_seconds(item, timeframe)
                # Validate like the generic adapter so one bad candle is rejected, not the whole run.
                candle = Candle(
                    symbol=str(item.get("symbol", data.get("symbol"))),
                    timeframe=timeframe,
                    open_time=open_time,
                    close_time=open_time + timedelta(seconds=period_seconds),
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item.get("volume", 0.0)),
                    trade_count=int(item.get("trade_count", 0)),
                    closed=bool(item.get("closed", True)),
                )
                candles.append(
                    {
                        "symbol": candle.symbol,
                        "timeframe": candle.timeframe,
                        "open_time": candle.open_time.isoformat(),
                        "close_time": candle.close_time.isoformat(),
                        "period_seconds": period_seconds,
                        "open": candle.open,
                        "high": candle.high,
                        "low": candle.low,
                        "close": candle.close,
                        "volume": candle.volume,
                        "trade_count": candle.trade_count,
                        "closed": candle.closed,
                    }
                )
                estimated.append(f"candles[{index}]")
            except (KeyError, TypeError, ValueError) as exc:
                rejected.append(f"candles[{index}]:{exc}")

        missing: list[str] = list(rejected)
        # Values read off a chart (funding, liquidations, OB depth, profile): estimates like every price here.
        context = parse_context(data)
        missing.extend(f"context_rejected:{item}" for item in context.rejected)
        if context.profile is not None:
            estimated.append("profile_levels")
        if context.positioning is not None:
            estimated.append("positioning_values")
        if not candles:
            missing.append("candles")
        if price_now is None:
            missing.append("price_now")

        timeframe = str(data.get("timeframe", "4H"))
        indicators = tuple(data.get("visible_indicators", ()))

        return AdapterInput(
            symbol=str(data["symbol"]),
            venue=str(data.get("venue", "MMT_GG")),
            market_type=str(data.get("market_type", "FUTURES")),
            timeframe=timeframe,
            observed_at=observed_at,
            candles=tuple(candles),
            trades=(),
            price_now=price_now,
            price_timestamp=None,
            net_delta=_dec(data.get("net_delta")),
            aggressive_buy_volume=_dec(data.get("aggressive_buy_volume")),
            aggressive_sell_volume=_dec(data.get("aggressive_sell_volume")),
            total_volume=_dec(data.get("total_volume")),
            open_interest_with_price=data.get("open_interest_with_price"),
            delta_divergence=data.get("delta_divergence"),
            volume_bubbles=tuple(data.get("volume_bubbles", ())),
            levels={key: _dec(value) for key, value in (data.get("levels") or {}).items() if _dec(value) is not None},
            structured=False,
            screenshot_confidence=min(self.default_confidence, float(data.get("read_confidence", self.default_confidence))),
            estimated_prices=tuple(sorted(set(estimated))),
            missing_fields=tuple(sorted(set(missing))),
            extra_notes=("screenshot_derived_data_all_prices_estimated", f"visible_indicators={list(indicators)}", "chart_timeframe=" + timeframe),
            positioning=context.positioning,
            profile=context.profile,
        )