"""MMT structured data adapter.

Parses structured MMT.GG exports (JSON) into a normalized `AdapterInput`.
MMT exports are still treated conservatively: any field the exporter does not
guarantee is marked missing or estimated. This adapter performs no inference.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .base import AdapterInput
from .generic import GenericOrderflowAdapter


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


class MMTStructuredDataAdapter:
    def __init__(self) -> None:
        self._generic = GenericOrderflowAdapter()
        self.adapter_kind = "MMT_STRUCTURED_DATA"

    def adapt(self, data: Mapping[str, Any], observed_at: datetime | None = None) -> AdapterInput:
        observed_at = observed_at or datetime.now(timezone.utc)
        if not isinstance(data.get("symbol"), str) or not data.get("symbol"):
            raise ValueError("MMT structured export requires symbol")
        base = self._generic.adapt(data, observed_at=observed_at)

        # MMT.GG structured exports never guarantee orderbook or position
        # data; only spot/futures candles and aggTrades are recognized.
        return AdapterInput(
            symbol=base.symbol,
            venue=str(data.get("venue", "MMT_GG")),
            market_type=str(data.get("market_type", "FUTURES")),
            timeframe=str(data.get("timeframe", "4H")),
            observed_at=observed_at,
            candles=base.candles,
            trades=base.trades,
            price_now=_dec(data.get("price_now")),
            price_timestamp=base.price_timestamp,
            net_delta=_dec(data.get("net_delta")),
            aggressive_buy_volume=_dec(data.get("aggressive_buy_volume")),
            aggressive_sell_volume=_dec(data.get("aggressive_sell_volume")),
            total_volume=_dec(data.get("total_volume")),
            open_interest_with_price=data.get("open_interest_with_price"),
            delta_divergence=data.get("delta_divergence"),
            volume_bubbles=tuple(data.get("volume_bubbles", ())),
            levels={key: _dec(value) for key, value in (data.get("levels") or {}).items() if _dec(value) is not None},
            structured=True,
            screenshot_confidence=None,
            estimated_prices=base.estimated_prices,
            missing_fields=base.missing_fields,
            extra_notes=base.extra_notes + ("mmt_structured_export_limited_to_recognized_fields",),
            positioning=base.positioning,
            profile=base.profile,
        )