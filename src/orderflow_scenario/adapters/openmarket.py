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
from src.market_data.providers.openmarket.context_schemas import (
    FUNDING_RATE,
    LIQUIDATION,
    OPEN_INTEREST,
    TPO,
    VOLUME_PROFILE,
    closed_points,
    liquidation_totals,
    parse_context_series,
    summarize_profile,
)
from src.market_data.providers.openmarket.schemas import INTERVAL_SECONDS, ns_to_datetime, parse_candles

from ..footprint import footprint_from_levels
from ..positioning import PositioningInputs, ProfileLevels
from .base import AdapterInput

# Context types requested next to the candles. TPO_AGG is not requested by
# default: it answered HTTP 500 (code 13) on 2026-10-21 for every window tried.
DEFAULT_CONTEXT_TYPES = (OPEN_INTEREST, FUNDING_RATE, LIQUIDATION, VOLUME_PROFILE)
DERIVATIVES_ONLY = frozenset({OPEN_INTEREST, FUNDING_RATE, LIQUIDATION})
_AUTH_KINDS = frozenset({OpenMarketErrorKind.NO_SECRET, OpenMarketErrorKind.INVALID_SECRET, OpenMarketErrorKind.NOT_CONFIGURED})

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
        context_types: tuple[str, ...] = (),
        funding_interval_hours: int = 8,
        liquidation_buy_is_short: bool = True,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.client = client or OpenMarketClient()
        self.include_per_side = include_per_side
        self.side_is_aggressor = side_is_aggressor
        unknown = set(context_types) - set(DEFAULT_CONTEXT_TYPES)
        if unknown:
            raise ValueError(f"unsupported OpenMarket context types: {sorted(unknown)}")
        self.context_types = tuple(context_types)
        self.funding_interval_hours = funding_interval_hours
        # Exchange convention for liquidation orders: a forced BUY closes a short.
        # OpenMarket does not document it; the 2026-10-21 capture (BUY dominant
        # while price and OI rose) is consistent with it. False keeps both sides
        # out of the analysis and only reports the raw BUY/SELL totals.
        self.liquidation_buy_is_short = liquidation_buy_is_short
        self.now = now
        self.adapter_kind = "OPENMARKET_API"
        self.last_input: AdapterInput | None = None

    def adapt(self, data: Mapping[str, Any], observed_at: datetime | None = None) -> AdapterInput:
        request = OpenMarketRequest.from_mapping(data)
        observed_at = observed_at or self.now()
        missing: list[str] = ["candles.trade_count"]
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

        aggressive_buy = aggressive_sell = net_delta = delta_series = None
        if self.include_per_side:
            aggressive_buy, aggressive_sell, net_delta, delta_series = self._per_side(request, observed_at, missing, notes)
        else:
            missing.append("aggressive_volume:per_side_not_requested")

        positioning = profile = footprint = None
        if self.context_types:
            opens_closes = {
                datetime.fromisoformat(candle["open_time"]): (Decimal(str(candle["open"])), Decimal(str(candle["close"])))
                for candle in candles
            }
            positioning, profile, footprint = self._context(request, observed_at, missing, notes, opens_closes)
            missing.append(f"tpo:{TPO}_not_requested_provider_returned_http_500_on_2026-10-21")
            missing.append("orderbook_depth:no_documented_openmarket_type")
        else:
            missing.extend(["levels", "open_interest_with_price", "context:not_requested"])

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
            delta_series=delta_series,
            footprint=footprint,
            structured=True,
            screenshot_confidence=None,
            missing_fields=tuple(sorted(set(missing))),
            extra_notes=tuple(notes),
            positioning=positioning,
            profile=profile,
        )
        return self.last_input

    def _fetch_context(self, request: OpenMarketRequest, data_type: str, observed_at: datetime, missing: list[str], notes: list[str]):
        """One context type: parsed closed points and the reported sides, or None when unavailable."""
        try:
            response = self.client.get_points(request.params(data_type))
            parsed = parse_context_series(response.payload, data_type=data_type, expected=request.expected_id(data_type))
        except OpenMarketError as error:
            if error.kind in _AUTH_KINDS:
                raise
            missing.append(f"context:{data_type}_unavailable:{error.kind.value}")
            return None
        points, rejected, excluded = closed_points(
            parsed.points, from_seconds=request.from_seconds, period_seconds=request.period_seconds,
            interval_seconds=INTERVAL_SECONDS[request.interval], now_seconds=int(observed_at.timestamp()),
        )
        missing.extend(f"context_rejected:{data_type}:{item}" for item in parsed.rejected + rejected)
        notes.append(f"provenance:{data_type}_response_sha256={response.body_sha256}")
        notes.append(f"context:{data_type}_closed_points={len(points)} excluded_open_or_boundary={excluded} units=as_reported_by_provider")
        if parsed.reordered:
            notes.append(f"dedup:{data_type}_reordered_by_timestamp=true")
        if parsed.unexpected_fields:
            notes.append(f"schema:{data_type}_unexpected_fields={','.join(sorted(parsed.unexpected_fields))}")
        return points, parsed.sides

    def _context(self, request: OpenMarketRequest, observed_at: datetime, missing: list[str], notes: list[str], opens_closes=None):
        funding = long_liq = short_liq = None
        open_interest: tuple = ()
        profile = footprint = None
        for data_type in self.context_types:
            if data_type in DERIVATIVES_ONLY and request.market_type != "FUTURES":
                missing.append(f"context:{data_type}_futures_only")
                continue
            fetched = self._fetch_context(request, data_type, observed_at, missing, notes)
            if fetched is None:
                continue
            points, sides = fetched
            if data_type == OPEN_INTEREST:
                # Close of each closed interval = OI at the end of that interval.
                open_interest = tuple(
                    (ns_to_datetime(point.timestamp_ns + INTERVAL_SECONDS[request.interval] * 1_000_000_000), point.close)
                    for point in points
                )
                if len(open_interest) < 2:
                    missing.append("context:OPEN_INTEREST_AGG_fewer_than_2_closed_points")
            elif data_type == FUNDING_RATE:
                if points:
                    funding = points[-1].close
                    notes.append(
                        f"derived:funding_rate=rateClose_of_last_closed_interval assumed_funding_interval_hours={self.funding_interval_hours}"
                    )
                else:
                    missing.append("funding_rate")
            elif data_type == LIQUIDATION:
                totals = liquidation_totals(points, sides)
                notes.append(f"context:LIQUIDATION_AGG_totals BUY={totals['BUY']} SELL={totals['SELL']} series={','.join(sides) or 'none'}")
                if not sides:
                    missing.append("liquidations:no_series_returned")
                elif not self.liquidation_buy_is_short:
                    missing.append("liquidations:side_semantics_unverified")
                else:
                    # Intervals without liquidations are omitted by the provider; a side
                    # with a series counts them as zero, a side without one stays unknown.
                    short_liq, long_liq = totals["BUY"], totals["SELL"]
                    notes.append("derived:liquidations=BUY_order_side_is_short_liquidation SELL_is_long_liquidation convention=exchange_order_side")
            elif data_type == VOLUME_PROFILE:
                summary = summarize_profile(points)
                if summary is None:
                    missing.append("volume_profile")
                else:
                    profile = ProfileLevels(
                        point_of_control=summary.point_of_control,
                        value_area_high=summary.value_area_high,
                        value_area_low=summary.value_area_low,
                        source=("openmarket_volume_profile",),
                    )
                    notes.append(
                        f"derived:volume_profile poc={summary.point_of_control} val={summary.value_area_low} vah={summary.value_area_high} "
                        f"value_area={summary.value_area_fraction} rows={summary.rows} intervals={summary.intervals} "
                        f"buy={summary.buy_volume} sell={summary.sell_volume}"
                    )
                    # Per-interval rows are a footprint (bid = Sell, ask = Buy) only once the
                    # side semantics are proven; until then the profile stays levels-only.
                    if self.side_is_aggressor:
                        footprint = footprint_from_levels(
                            (
                                (ns_to_datetime(point.timestamp_ns), [(row.price, row.sell_volume, row.buy_volume) for row in point.rows])
                                for point in points
                            ),
                            source="openmarket_volume_profile",
                            opens_closes=opens_closes,
                        )
                        if footprint is not None:
                            notes.append(f"derived:footprint=VOLUME_PROFILE_AGG_rows bid=Sell ask=Buy bars={len(footprint.bars)}")
                    else:
                        missing.append("footprint:VOLUME_PROFILE_AGG_side_semantics_unverified")
        try:
            positioning = PositioningInputs(
                funding_rate=funding,
                funding_interval_hours=self.funding_interval_hours,
                long_liquidation_volume=long_liq,
                short_liquidation_volume=short_liq,
                open_interest=open_interest,
            )
        except ValueError as exc:
            missing.append(f"context_rejected:positioning:{exc}")
            positioning = None
        if positioning is not None and positioning.is_empty():
            positioning = None
        return positioning, profile, footprint

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
            return None, None, None, None
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
            return None, None, None, None
        notes.append(
            f"per_side:buy_volume={volumes.buy_volume} sell_volume={volumes.sell_volume} "
            f"paired_intervals={volumes.paired_intervals} unpaired_intervals={volumes.unpaired_intervals}"
        )
        if not self.side_is_aggressor:
            missing.append("aggressive_volume:TRADE_AGG_side_semantics_unverified")
            missing.append("net_delta")
            notes.append("verify:delta_definition=false")
            return None, None, None, None
        notes.append("derived:net_delta=true derivation=buy_volume_minus_sell_volume source=TRADE_AGG units=as_reported_by_provider")
        # Delta per closed interval, oldest first, paired intervals only (never zero-filled).
        buy = {p.timestamp_ns: p.volume for p in points if p.side == "BUY"}
        sell = {p.timestamp_ns: p.volume for p in points if p.side == "SELL"}
        delta_series = tuple(buy[t] - sell[t] for t in sorted(buy.keys() & sell.keys()))
        notes.append(f"derived:delta_series=TRADE_AGG_buy_minus_sell_per_interval intervals={len(delta_series)}")
        return volumes.buy_volume, volumes.sell_volume, volumes.buy_volume - volumes.sell_volume, delta_series
