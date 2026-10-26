"""Trade sources for the footprint: TIM's ``agg_trades`` table and Binance daily archives.

Both return plain ``Trade`` and ``Candle`` objects; the footprint itself is built by
``footprint.footprint_from_trades`` through the generic adapter payload
(``payload_for_pipeline``). Nothing here writes to the database.

Archives: ``https://data.binance.vision/data/<market>/daily/aggTrades/<SYMBOL>/<SYMBOL>-aggTrades-<day>.zip``
plus a ``.CHECKSUM`` sidecar. The cloud cannot reach that host; downloads run on the Mac.
Unlike the S2 study store, this loader has no holdout lock: it serves current days for
analysis, not for research claims.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Sequence

from src.data_ingestion.aggregator import bucket_start, timeframe_seconds
from src.models.market_data import Candle, Trade
from src.research_lab.data.aggtrades import read_rows
from src.research_lab.data.store import http_fetch
from src.research_lab.studies.s2_orderflow import archive_ms, parse_is_buyer_maker
from src.v2_readiness.backfill import parse_official_checksum, verify_archive

__all__ = [
    "MARKETS",
    "archive_filename",
    "archive_url",
    "download_archive",
    "trades_from_archive",
    "candles_from_trades",
    "load_from_repository",
    "load_from_database",
    "load_from_archives",
    "payload_for_pipeline",
]

Fetcher = Callable[[str], bytes]
MARKETS = {"spot": "spot", "futures-um": "futures/um", "futures-cm": "futures/cm"}
DEFAULT_ARCHIVE_ROOT = Path("data/footprint/archives")
MAX_ARCHIVE_DAYS = 31


def archive_filename(symbol: str, day: date) -> str:
    return f"{symbol}-aggTrades-{day.isoformat()}.zip"


def archive_url(symbol: str, day: date, market: str = "spot") -> str:
    if market not in MARKETS:
        raise ValueError(f"market must be one of {', '.join(MARKETS)}")
    return f"https://data.binance.vision/data/{MARKETS[market]}/daily/aggTrades/{symbol}/{archive_filename(symbol, day)}"


def download_archive(symbol: str, day: date, root: Path, *, market: str = "spot", fetcher: Fetcher = http_fetch, verify: bool = True) -> Path:
    """Download one day's archive into ``root/<market>/`` and verify it against Binance's checksum sidecar."""
    target_dir = Path(root) / market
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / archive_filename(symbol, day)
    if target.exists():
        return target
    url = archive_url(symbol, day, market)
    payload = fetcher(url)
    if verify:
        digest = parse_official_checksum(fetcher(url + ".CHECKSUM").decode("utf-8"), expected_filename=target.name)
        if not verify_archive(payload, digest):
            raise ValueError(f"checksum mismatch for {target.name}")
    target.write_bytes(payload)
    return target


def trades_from_archive(path: Path, symbol: str, start: datetime, end: datetime) -> list[Trade]:
    """Trades within [start, end) from one Binance aggTrades archive.

    Columns: agg_id, price, quantity, first_id, last_id, time, is_buyer_maker, best_match.
    """
    _check_range(start, end)
    trades: list[Trade] = []
    for row in read_rows(Path(path).read_bytes()):
        if len(row) < 7:
            raise ValueError("aggTrades row needs at least seven columns")
        moment = datetime.fromtimestamp(archive_ms(row[5]) / 1000, tz=timezone.utc)
        if moment < start or moment >= end:
            continue
        trades.append(
            Trade(
                symbol=symbol,
                price=float(row[1]),
                quantity=float(row[2]),
                event_time=moment,
                trade_id=int(row[0]),
                buyer_is_maker=parse_is_buyer_maker(row[6]),
            )
        )
    return trades


def candles_from_trades(trades: Sequence[Trade], symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
    """OHLCV buckets from trades; a bucket without trades produces no candle (never filled)."""
    _check_range(start, end)
    step = timedelta(seconds=timeframe_seconds(timeframe))
    buckets: dict[datetime, list[Trade]] = {}
    for trade in trades:
        if trade.event_time < start or trade.event_time >= end:
            continue
        buckets.setdefault(bucket_start(trade.event_time, timeframe), []).append(trade)
    candles: list[Candle] = []
    for open_time in sorted(buckets):
        items = sorted(buckets[open_time], key=lambda t: (t.event_time, t.trade_id or 0))
        close_time = open_time + step
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time=open_time,
                close_time=close_time,
                open=items[0].price,
                high=max(t.price for t in items),
                low=min(t.price for t in items),
                close=items[-1].price,
                volume=sum(t.quantity for t in items),
                trade_count=len(items),
                closed=close_time <= end,
            )
        )
    return candles


async def load_from_repository(repo: Any, symbol: str, timeframe: str, start: datetime, end: datetime) -> tuple[list[Candle], list[Trade], list[str]]:
    """Candles, trades and notes from a ``MarketRepository``-like object (``candles_between``, ``agg_trades_between``).

    Candles missing in the table are derived from the trades, so a footprint never
    waits for the aggregator; the note ``candles_derived_from_trades`` marks that case.
    """
    _check_range(start, end)
    trades = await repo.agg_trades_between(symbol, start, end)
    candles = await repo.candles_between(symbol, timeframe, start, end)
    candles = [candle for candle in candles if candle.open_time >= start and candle.close_time <= end]
    notes: list[str] = []
    if not candles and trades:
        candles = candles_from_trades(trades, symbol, timeframe, start, end)
        notes.append("candles_derived_from_trades")
    return candles, trades, notes


def load_from_database(database_url: str, symbol: str, timeframe: str, start: datetime, end: datetime) -> tuple[list[Candle], list[Trade], list[str]]:
    """Read-only load from TIM's PostgreSQL (agg_trades, candles); returns (candles, trades, notes)."""
    from src.database.connection import Database
    from src.database.repository import MarketRepository

    async def run() -> tuple[list[Candle], list[Trade], list[str]]:
        database = Database(database_url, min_size=1, max_size=2)
        await database.connect()
        try:
            return await load_from_repository(MarketRepository(database), symbol, timeframe, start, end)
        finally:
            await database.close()

    return asyncio.run(run())


def load_from_archives(
    root: Path,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    *,
    market: str = "spot",
    download: bool = False,
    fetcher: Fetcher = http_fetch,
) -> tuple[list[Candle], list[Trade], list[str]]:
    """Trades for [start, end) from daily archives under ``root/<market>/``; candles derived from them.

    Returns (candles, trades, missing_days). A missing day is downloaded only with
    ``download=True``; otherwise it is reported and skipped.
    """
    _check_range(start, end)
    first, last = start.date(), (end - timedelta(microseconds=1)).date()
    if (last - first).days + 1 > MAX_ARCHIVE_DAYS:
        raise ValueError(f"at most {MAX_ARCHIVE_DAYS} archive days per analysis")
    trades: list[Trade] = []
    missing: list[str] = []
    day = first
    while day <= last:
        path = Path(root) / market / archive_filename(symbol, day)
        if not path.exists():
            if download:
                path = download_archive(symbol, day, Path(root), market=market, fetcher=fetcher)
            else:
                missing.append(day.isoformat())
                day += timedelta(days=1)
                continue
        trades.extend(trades_from_archive(path, symbol, start, end))
        day += timedelta(days=1)
    trades.sort(key=lambda t: (t.event_time, t.trade_id or 0))
    return candles_from_trades(trades, symbol, timeframe, start, end), trades, missing


def payload_for_pipeline(
    *,
    symbol: str,
    timeframe: str,
    candles: Sequence[Candle],
    trades: Sequence[Trade],
    tick_size: Decimal,
    observed_at: datetime,
    venue: str = "BINANCE",
    market_type: str = "SPOT",
    source: str,
    notes: Sequence[str] = (),
) -> dict[str, Any]:
    """Generic-adapter JSON: candles, trades and ``footprint_tick_size`` (the CLI builds the footprint)."""
    if tick_size <= 0:
        raise ValueError("tick_size must be > 0")
    last = candles[-1].close if candles else None
    return {
        "symbol": symbol,
        "venue": venue,
        "market_type": market_type,
        "timeframe": timeframe,
        "observed_at": observed_at.isoformat(),
        "candles": [
            {
                "symbol": c.symbol, "timeframe": c.timeframe, "open_time": c.open_time.isoformat(), "close_time": c.close_time.isoformat(),
                "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume, "trade_count": c.trade_count, "closed": c.closed,
            }
            for c in candles
        ],
        "trades": [
            {"symbol": t.symbol, "price": t.price, "quantity": t.quantity, "event_time": t.event_time.isoformat(), "trade_id": t.trade_id, "buyer_is_maker": t.buyer_is_maker}
            for t in trades
        ],
        "price_now": last,
        "footprint_tick_size": str(tick_size),
        "extra_notes": [f"footprint_source={source}", *notes],
    }


def _check_range(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if end <= start:
        raise ValueError("end must be after start")
