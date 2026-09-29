"""OpenMarket candle points -> TIM canonical structures.

Deduplication is keyed by data type (never a blanket timestamp+instrument):

- candle:  provider, exchange, rawSymbol, interval, type, side, timestamp_ns
- profile: provider, exchange, rawSymbol, interval, timestamp, price level (not implemented in v1)
- trade:   provider, exchange, rawSymbol, trade.id (WebSocket, not implemented in v1)

Identical duplicates (retries, pagination overlap) collapse to one point.
Conflicting duplicates (same key, different values) are dropped entirely and
reported: TIM never picks one of two contradicting provider values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from .schemas import INTERVAL_SECONDS, CandlePoint, ns_to_datetime

PROVIDER = "openmarket"
NORMALIZER_VERSION = "openmarket-normalizer-1.0.0"

# OpenMarket interval -> TIM timeframe label (orderflow_scenario uses e.g. "4H").
TIM_TIMEFRAME = {
    "MINUTE": "1m",
    "FIVE_MINUTES": "5m",
    "FIFTEEN_MINUTES": "15m",
    "THIRTY_MINUTES": "30m",
    "HOUR": "1H",
    "FOUR_HOURS": "4H",
    "DAY": "1D",
    "WEEK": "1W",
}


@dataclass(slots=True)
class DedupReport:
    duplicates: int = 0
    conflicts: list[str] = field(default_factory=list)
    reordered: bool = False


def candle_key(point: CandlePoint, *, exchange: str, raw_symbol: str, interval: str, data_type: str) -> tuple:
    return (PROVIDER, exchange, raw_symbol, interval, data_type, point.side, point.timestamp_ns)


def dedupe_candles(
    points: list[CandlePoint], *, exchange: str, raw_symbol: str, interval: str, data_type: str
) -> tuple[list[CandlePoint], DedupReport]:
    report = DedupReport()
    report.reordered = any(
        (a.side, a.timestamp_ns) > (b.side, b.timestamp_ns)
        for a, b in zip(points, points[1:])
        if a.side == b.side
    )
    kept: dict[tuple, CandlePoint] = {}
    conflicted: set[tuple] = set()
    for point in points:
        key = candle_key(point, exchange=exchange, raw_symbol=raw_symbol, interval=interval, data_type=data_type)
        if key in conflicted:
            continue
        existing = kept.get(key)
        if existing is None:
            kept[key] = point
        elif existing == point:
            report.duplicates += 1
        else:
            conflicted.add(key)
            del kept[key]
            report.conflicts.append(f"{point.side or 'ALL'}@{ns_to_datetime(point.timestamp_ns).isoformat()}")
    ordered = sorted(kept.values(), key=lambda item: (item.side or "", item.timestamp_ns))
    return ordered, report


def to_tim_candles(
    points: list[CandlePoint], *, raw_symbol: str, interval: str, as_of: datetime
) -> list[dict]:
    """Candle dicts in the shape the orderflow_scenario pipeline consumes.

    Precision boundary: TIM's ``Candle`` model stores floats. The Decimal values
    are converted here, at the model boundary, and nowhere earlier. The
    provider does not report a trade count; ``trade_count`` is 0 and the adapter
    lists ``candles.trade_count`` as missing instead of pretending to know it.
    A candle whose interval has not ended at ``as_of`` is marked ``closed=False``.
    """
    length = timedelta(seconds=INTERVAL_SECONDS[interval])
    candles = []
    for point in points:
        open_time = point.timestamp
        close_time = open_time + length
        candles.append(
            {
                "symbol": raw_symbol,
                "timeframe": TIM_TIMEFRAME[interval],
                "open_time": open_time.isoformat(),
                "close_time": close_time.isoformat(),
                "open": float(point.open),
                "high": float(point.high),
                "low": float(point.low),
                "close": float(point.close),
                "volume": float(point.volume),
                "trade_count": 0,
                "closed": close_time <= as_of,
            }
        )
    return candles


@dataclass(slots=True)
class TimeCheck:
    """Evidence that ``timestamp`` is the interval open and inside the request.

    ``PASS`` needs every point inside ``[from, from+period)``, aligned to the
    interval grid (up to DAY) and with firstTimestamp/lastTimestamp inside
    ``[timestamp, timestamp+interval)``. Without first/last on every point the
    meaning of ``timestamp`` stays ``UNPROVEN``; any contradiction is ``FAIL``.
    """
    status: str = "UNPROVEN"
    rejected: list[str] = field(default_factory=list)


def check_time_semantics(
    points: list[CandlePoint], *, interval: str, from_seconds: int, period_seconds: int
) -> tuple[list[CandlePoint], TimeCheck]:
    length_ns = INTERVAL_SECONDS[interval] * 1_000_000_000
    start_ns, end_ns = from_seconds * 1_000_000_000, (from_seconds + period_seconds) * 1_000_000_000
    check, kept, bounded = TimeCheck(), [], True
    for point in points:
        label = f"{point.side or 'ALL'}@{point.timestamp.isoformat()}"
        if not start_ns <= point.timestamp_ns < end_ns:
            check.rejected.append(f"{label}: outside requested window")
            continue
        if interval != "WEEK" and point.timestamp_ns % length_ns:
            check.rejected.append(f"{label}: not aligned to the {interval} grid")
            continue
        first, last = point.first_timestamp_ns, point.last_timestamp_ns
        if first is None or last is None:
            bounded = False
        elif not (point.timestamp_ns <= first <= last < point.timestamp_ns + length_ns):
            check.rejected.append(f"{label}: first/last trade outside [timestamp, timestamp+interval)")
            continue
        kept.append(point)
    if check.rejected:
        check.status = "FAIL"
    elif kept and bounded:
        check.status = "PASS"
    return kept, check


@dataclass(frozen=True, slots=True)
class SideVolumes:
    buy_volume: Decimal
    sell_volume: Decimal
    paired_intervals: int
    unpaired_intervals: int


def side_volumes(points: list[CandlePoint]) -> SideVolumes | None:
    """Sum BUY and SELL volume over intervals present on both sides only.

    An interval with only one side is excluded (and counted) rather than read
    as zero volume on the other side.
    """
    buy = {p.timestamp_ns: p.volume for p in points if p.side == "BUY"}
    sell = {p.timestamp_ns: p.volume for p in points if p.side == "SELL"}
    paired = buy.keys() & sell.keys()
    if not paired:
        return None
    return SideVolumes(
        buy_volume=sum((buy[t] for t in paired), Decimal(0)),
        sell_volume=sum((sell[t] for t in paired), Decimal(0)),
        paired_intervals=len(paired),
        unpaired_intervals=len(buy.keys() ^ sell.keys()),
    )


def provenance_notes(
    *,
    endpoint: str,
    data_type: str,
    exchange: str,
    raw_symbol: str,
    interval: str,
    requested_at: datetime,
    ingested_at: datetime,
    body_sha256: str,
    envelope_paths: list[str],
    first_event: datetime | None,
    last_event: datetime | None,
) -> tuple[str, ...]:
    """Provenance in the adapter's existing channel (``AdapterInput.extra_notes``)."""
    return (
        f"provenance:provider={PROVIDER}",
        f"provenance:endpoint=GET {endpoint}",
        f"provenance:type={data_type}",
        f"provenance:exchange={exchange}",
        f"provenance:raw_symbol={raw_symbol}",
        f"provenance:interval={interval}",
        f"provenance:request_time={requested_at.isoformat()}",
        f"provenance:event_time_first={first_event.isoformat() if first_event else 'none'}",
        f"provenance:event_time_last={last_event.isoformat() if last_event else 'none'}",
        f"provenance:ingestion_time={ingested_at.isoformat()}",
        f"provenance:response_sha256={body_sha256}",
        f"provenance:envelope_paths={'|'.join(envelope_paths)}",
        f"provenance:normalizer={NORMALIZER_VERSION}",
    )
