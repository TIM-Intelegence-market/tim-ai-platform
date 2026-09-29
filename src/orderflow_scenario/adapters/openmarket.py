"""OpenMarket API adapter (automated provider next to the manual MMT exports).

Requests ``TRADE_SIDE_AGNOSTIC_AGG`` candles (and, optionally, ``TRADE_AGG``
per-side series) through ``OpenMarketClient`` and returns the same
``AdapterInput`` the generic and MMT adapters produce. It performs no
inference: whatever OpenMarket does not deliver is listed in
``missing_fields``; every derived value is labelled in ``extra_notes``.

Aggressor semantics: OpenMarket documents ``series.side`` as the aggressor side
only for WebSocket ``TRADE_AGG``. That statement is not transferred to REST
``TRADE_AGG`` (``series[].id.side``). TIM's ``aggressive_*_volume`` and
``net_delta`` are aggressor quantities, so they are only derived when the caller
asserts ``side_is_aggressor=True`` after REST documentation or a real proof
confirms it; by default they stay missing (REST_SIDE_AGGRESSOR_SEMANTICS=UNPROVEN).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping

from src.market_data.providers.openmarket.client import OpenMarketClient
from src.market_data.providers.openmarket.errors import OpenMarketError, OpenMarketErrorKind
from src.market_data.providers.openmarket.mapper import (
    TIM_TIMEFRAME,
    check_time_semantics,
    dedupe_candles,
    provenance_notes,
    side_volumes,
    to_tim_candles,
)
from src.market_data.providers.openmarket.schemas import INTERVAL_SECONDS, parse_candles

from .base import AdapterInput

_IDENTIFIER = re.compile(r"^[A-Z0-9_]{2,40}$")
MARKET_TYPES = frozenset({"SPOT", "FUTURES"})


@dataclass(frozen=True, slots=True)
class OpenMarketRequest:
    exchange: str
    raw_symbol: str
    interval: str
    from_seconds: int
    period_seconds: int
    market_type: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "OpenMarketRequest":
        try:
            request = cls(
                exchange=str(data["exchange"]),
                raw_symbol=str(data["raw_symbol"]),
                interval=str(data["interval"]),
                from_seconds=int(data["from"]),
                period_seconds=int(data["period"]),
                market_type=str(data["market_type"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"OpenMarket request requires exchange, raw_symbol, interval, from, period, market_type: {exc}") from None
        request.validate()
        return request

    def validate(self) -> None:
        if not _IDENTIFIER.fullmatch(self.exchange):
            raise ValueError("exchange must be an OpenMarket exchange identifier such as BINANCE_FUTURES")
        if not _IDENTIFIER.fullmatch(self.raw_symbol):
            raise ValueError("raw_symbol must be an exchange symbol such as BTCUSDT")
        if self.interval not in INTERVAL_SECONDS:
            raise ValueError(f"interval must be one of {', '.join(INTERVAL_SECONDS)}")
        if self.from_seconds < 0 or self.period_seconds <= 0:
            raise ValueError("from must be >= 0 and period > 0 (seconds)")
        if self.market_type not in MARKET_TYPES:
            raise ValueError("market_type must be SPOT or FUTURES")

    def expected_id(self, data_type: str) -> dict[str, str]:
        """What every documented ``series[].id`` must echo back."""
        return {"type": data_type, "exchange": self.exchange, "rawSymbol": self.raw_symbol, "interval": self.interval}

    def params(self, data_type: str) -> dict[str, str | int]:
        return {
            "type": data_type,
            "exchange": self.exchange,
            "rawSymbol": self.raw_symbol,
            "interval": self.interval,
            "from": self.from_seconds,
            "period": self.period_seconds,
        }


def documented_checks(parsed) -> list[str]:
    """Evidence notes for the documented REST contract (see schemas.py)."""
    documented = parsed.documented_envelope
    if any("REST timestamp schema" in item for item in parsed.rejected):
        timestamp_status = "FAIL"
    elif not parsed.points:
        timestamp_status = "UNPROVEN"
    else:
        timestamp_status = "PASS" if parsed.timestamp_encodings == {"REST"} else "FAIL"
    return [
        f"check:documented_envelope={'PASS' if documented else 'FAIL'}",
        f"check:rest_timestamp_schema={timestamp_status}",
        f"check:series_id={'PASS' if documented and parsed.series_ids else ('UNPROVEN' if documented else 'FAIL')}",
    ]


class OpenMarketAdapter:
    def __init__(
        self,
        client: OpenMarketClient | None = None,
        *,
        include_per_side: bool = True,
        side_is_aggressor: bool = False,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.client = client or OpenMarketClient()
        self.include_per_side = include_per_side
        self.side_is_aggressor = side_is_aggressor
        self.now = now
        self.adapter_kind = "OPENMARKET_API"
        self.last_input: AdapterInput | None = None

    def adapt(self, data: Mapping[str, Any], observed_at: datetime | None = None) -> AdapterInput:
        request = OpenMarketRequest.from_mapping(data)
        observed_at = observed_at or self.now()
        missing: list[str] = ["candles.trade_count", "levels", "open_interest_with_price"]
        notes: list[str] = []

        data_type = "TRADE_SIDE_AGNOSTIC_AGG"
        response = self.client.get_points(request.params(data_type))
        parsed = parse_candles(response.payload, per_side=False, expected=request.expected_id(data_type))
        points, report = dedupe_candles(
            parsed.points, exchange=request.exchange, raw_symbol=request.raw_symbol,
            interval=request.interval, data_type=data_type,
        )
        points, time_check = check_time_semantics(
            points, interval=request.interval, from_seconds=request.from_seconds, period_seconds=request.period_seconds
        )
        missing.extend(f"candle_rejected:{item}" for item in parsed.rejected + time_check.rejected)
        missing.extend(f"candle_conflict:{item}" for item in report.conflicts)
        notes.extend(documented_checks(parsed))
        notes.append(f"check:time_semantics={time_check.status}")
        if time_check.end_boundary_excluded:
            notes.append(f"window:end_boundary_points_excluded={time_check.end_boundary_excluded}")
        notes.append(f"verify:time_unit={'true' if time_check.status == 'PASS' else 'false'}")
        if report.duplicates:
            notes.append(f"dedup:candle_duplicates_dropped={report.duplicates}")
        if report.reordered:
            notes.append("dedup:candles_reordered_by_timestamp=true")
        if parsed.unexpected_fields:
            notes.append(f"schema:unexpected_fields={','.join(sorted(parsed.unexpected_fields))}")
        all_candles = to_tim_candles(points, raw_symbol=request.raw_symbol, interval=request.interval, as_of=observed_at)
        # The running interval is incomplete: it never enters the analysis.
        closed_flags = [candle["closed"] for candle in all_candles]
        candles = [candle for candle in all_candles if candle["closed"]]
        points = [point for point, closed in zip(points, closed_flags) if closed]
        if len(candles) != len(all_candles):
            notes.append(f"excluded:open_interval_candles={len(all_candles) - len(candles)}")
        if not candles:
            missing.append("candles")
        notes.extend(
            provenance_notes(
                endpoint=response.request_path, data_type=data_type, exchange=request.exchange,
                raw_symbol=request.raw_symbol, interval=request.interval, requested_at=response.requested_at,
                ingested_at=observed_at, body_sha256=response.body_sha256, envelope_paths=parsed.envelope_paths,
                first_event=points[0].timestamp if points else None,
                last_event=points[-1].timestamp if points else None,
            )
        )

        total_volume = sum((point.volume for point in points), Decimal(0)) if points else None
        if total_volume is not None:
            complete = not (parsed.rejected or time_check.rejected or report.conflicts)
            notes.append(
                "derived:total_volume=true derivation=sum_of_closed_TRADE_SIDE_AGNOSTIC_AGG_volume "
                f"complete={'true' if complete else 'false'}"
            )
        else:
            missing.append("total_volume")

        aggressive_buy = aggressive_sell = net_delta = None
        if self.include_per_side:
            aggressive_buy, aggressive_sell, net_delta = self._per_side(request, observed_at, missing, notes)
        else:
            missing.append("aggressive_volume:per_side_not_requested")

        self.last_input = AdapterInput(
            symbol=request.raw_symbol,
            venue=request.exchange,
            market_type=request.market_type,
            timeframe=TIM_TIMEFRAME[request.interval],
            observed_at=observed_at,
            candles=tuple(candles),
            trades=(),
            price_now=None,
            price_timestamp=None,
            net_delta=net_delta,
            aggressive_buy_volume=aggressive_buy,
            aggressive_sell_volume=aggressive_sell,
            total_volume=total_volume,
            structured=True,
            screenshot_confidence=None,
            missing_fields=tuple(sorted(set(missing))),
            extra_notes=tuple(notes),
        )
        return self.last_input

    def _per_side(self, request: OpenMarketRequest, observed_at: datetime, missing: list[str], notes: list[str]):
        data_type = "TRADE_AGG"
        try:
            response = self.client.get_points(request.params(data_type))
            parsed = parse_candles(response.payload, per_side=True, expected=request.expected_id(data_type))
            checked, time_check = check_time_semantics(
                parsed.points, interval=request.interval, from_seconds=request.from_seconds,
                period_seconds=request.period_seconds,
            )
            parsed.points = checked
            parsed.rejected.extend(time_check.rejected)
            if time_check.end_boundary_excluded:
                notes.append(f"window:per_side_end_boundary_points_excluded={time_check.end_boundary_excluded}")
        except OpenMarketError as error:
            # Per-side data is optional context; its absence is reported, never filled.
            if error.kind in {OpenMarketErrorKind.NO_SECRET, OpenMarketErrorKind.INVALID_SECRET, OpenMarketErrorKind.NOT_CONFIGURED}:
                raise
            missing.append(f"aggressive_volume:TRADE_AGG_unavailable:{error.kind.value}")
            return None, None, None
        points, report = dedupe_candles(
            parsed.points, exchange=request.exchange, raw_symbol=request.raw_symbol,
            interval=request.interval, data_type=data_type,
        )
        missing.extend(f"per_side_rejected:{item}" for item in parsed.rejected)
        missing.extend(f"per_side_conflict:{item}" for item in report.conflicts)
        notes.append(
            f"check:side_location={'PASS' if parsed.documented_envelope and parsed.side_location == 'series[].id.side' else 'FAIL'}"
        )
        notes.append(f"provenance:per_side_response_sha256={response.body_sha256}")
        notes.append(f"provenance:per_side_envelope_paths={'|'.join(parsed.envelope_paths)}")
        # Same rule as the side-agnostic candles: the running interval is excluded.
        interval_ns = INTERVAL_SECONDS[request.interval] * 1_000_000_000
        cutoff_ns = int(observed_at.timestamp()) * 1_000_000_000
        points = [point for point in points if point.timestamp_ns + interval_ns <= cutoff_ns]
        volumes = side_volumes(points)
        if volumes is None:
            missing.append("aggressive_volume:no_paired_BUY_SELL_intervals")
            return None, None, None
        notes.append(
            f"per_side:buy_volume={volumes.buy_volume} sell_volume={volumes.sell_volume} "
            f"paired_intervals={volumes.paired_intervals} unpaired_intervals={volumes.unpaired_intervals}"
        )
        if not self.side_is_aggressor:
            missing.append("aggressive_volume:TRADE_AGG_side_semantics_unverified")
            missing.append("net_delta")
            notes.append("verify:delta_definition=false")
            return None, None, None
        notes.append("derived:net_delta=true derivation=buy_volume_minus_sell_volume source=TRADE_AGG units=as_reported_by_provider")
        return volumes.buy_volume, volumes.sell_volume, volumes.buy_volume - volumes.sell_volume
