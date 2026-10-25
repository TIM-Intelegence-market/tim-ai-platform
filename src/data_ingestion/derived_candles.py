"""Higher-timeframe candles (4h, 1d) derived from persisted 1-hour candles.

Uzi asked on 25.10.2026 for research data on the higher timeframes. The live
aggregator could build 4h and 1d candles trade by trade, but every replay and
gap repair would then start at the day's bucket boundary and rescan a day of
aggTrades. Deriving the higher timeframes from the already persisted 1h candles
avoids that: a periodic pass reads the 1h rows and writes one 4h row per four
hours and one 1d row per UTC day.

Rules, on purpose:

- A derived candle is written only when all its source candles exist and are
  contiguous (4 for 4h, 24 for 1d). A bucket with a gap is skipped, not
  approximated; the gap shows as a missing row, never as a wrong candle.
- Only buckets whose close time has passed are written (``closed`` is always
  true). There is no "building" higher-timeframe candle.
- Buckets are aligned like ``bucket_start``: 4h at 00/04/08/12/16/20 UTC, 1d at
  00:00 UTC.
- The pass is idempotent: re-deriving a bucket yields the identical row.

Provenance stays BINANCE_SPOT_AGGTRADE: the 1h candles are deterministic
aggregates of the public trade stream, and so are these.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from src.data_ingestion.aggregator import bucket_start, timeframe_seconds
from src.models.market_data import Candle

DERIVED_TIMEFRAMES: dict[str, str] = {"4h": "1h", "1d": "1h"}
DERIVE_INTERVAL_SECONDS = 300


def source_timeframe(timeframe: str) -> str:
    try:
        return DERIVED_TIMEFRAMES[timeframe]
    except KeyError as exc:
        raise ValueError(f"Not a derived timeframe: {timeframe}") from exc


def derive_candles(source: Iterable[Candle], timeframe: str, now: datetime) -> list[Candle]:
    """Build complete ``timeframe`` candles from contiguous source candles.

    ``source`` may arrive in any order and may contain more than one symbol;
    each symbol is derived on its own. Candles of the wrong timeframe raise.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    base = source_timeframe(timeframe)
    step = timedelta(seconds=timeframe_seconds(base))
    per_bucket = timeframe_seconds(timeframe) // timeframe_seconds(base)
    buckets: dict[tuple[str, datetime], dict[datetime, Candle]] = {}
    for candle in source:
        if candle.timeframe != base:
            raise ValueError(f"Deriving {timeframe} needs {base} candles, got {candle.timeframe}")
        if not candle.closed:
            continue
        key = (candle.symbol, bucket_start(candle.open_time, timeframe))
        slot = buckets.setdefault(key, {})
        if candle.open_time in slot and slot[candle.open_time] != candle:
            raise ValueError("Conflicting duplicate source candle")
        slot[candle.open_time] = candle
    result: list[Candle] = []
    for (symbol, start), slot in sorted(buckets.items()):
        close_time = start + timedelta(seconds=timeframe_seconds(timeframe))
        if close_time > now:
            continue
        expected = [start + step * index for index in range(per_bucket)]
        if any(open_time not in slot for open_time in expected):
            continue
        ordered = [slot[open_time] for open_time in expected]
        result.append(Candle(
            symbol, timeframe, start, close_time,
            ordered[0].open, max(c.high for c in ordered), min(c.low for c in ordered), ordered[-1].close,
            sum(c.volume for c in ordered), sum(c.trade_count for c in ordered), True,
        ))
    return result


def derive_from(latest_derived_open: datetime | None, timeframe: str, lookback: timedelta = timedelta(days=90)) -> datetime | None:
    """Where the next pass should start reading source candles.

    The bucket after the latest derived one, so an already written bucket is
    not re-read every pass. ``None`` means: read everything the lookback allows
    (first pass).
    """
    if latest_derived_open is None:
        return None
    return latest_derived_open + timedelta(seconds=timeframe_seconds(timeframe))
