"""Offline rebuild of closed 1m candles for DEFERRED CANDLE_V1 outbox work.

A live cutover (``scripts/apply_live_cutover.py``) and queue back-pressure set
historical CANDLE_V1 outbox rows to ``DEFERRED``: the raw aggTrades are durable,
but no worker ever turned those minutes into candles. This module closes that
hole from the persisted raw trades alone. It is deliberately narrow:

- it reads ``agg_trades`` and writes ``candles`` plus the DEFERRED outbox rows
  of exactly the minutes it rebuilt; nothing else changes;
- the live queue is untouched: a minute with any active CANDLE_V1 work
  (PENDING, PROCESSING, RETRY, QUARANTINED) is skipped, and ``queue_depth``
  only counts active rows, so completing DEFERRED rows never moves it;
- cursor, gap ledger and follow-up stages (FEATURE_V1 and later) are not
  written. Rebuilt minutes get a candle, not back-dated features or
  observations;
- a minute is rebuilt only when it is closed and no OPEN/CATCHING_UP gap can
  still add trades to it, so a rebuilt candle is never a partial candle;
- every mutation is bound to the same ``status='DEFERRED'`` predicate again
  inside the transaction, so a concurrent status change is detected and the
  minute is rolled back instead of overwritten.

The candle arithmetic is the raw-data-only aggregate used by
``scripts/finalize_closed_1m_candles.py``: no synthetic or forward-filled rows.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from src.data_ingestion.durable import ACTIVE_OUTBOX_STATUSES, FIRST_WORKER
from src.models.market_data import Candle


UTC = timezone.utc
ONE_MINUTE = timedelta(minutes=1)
REBUILD_VERSION = "DEFERRED_CANDLE_REBUILD_V1"
METRIC_REBUILT_ITEMS = "outbox_deferred_rebuilt_total"
METRIC_REBUILT_CANDLES = "candles_deferred_rebuilt_total"
# Same serialization as DurableIngestionStore: the outbox CHECK constraint
# requires a lowercase 64-hex output_hash for every COMPLETED row.
_QUEUE_LOCK_KEY = 0x54494D4F55544258

METRIC_UNCANDLED_CANDLES = "candles_uncandled_rebuilt_total"
SCOPE_DEFERRED = "DEFERRED"
SCOPE_UNCANDLED = "UNCANDLED"

BLOCKER_NOT_CLOSED = "MINUTE_NOT_CLOSED"
BLOCKER_LIVE_WORK = "ACTIVE_LIVE_WORK_IN_MINUTE"
BLOCKER_DEFERRED_WORK = "DEFERRED_WORK_IN_MINUTE"
BLOCKER_OPEN_GAP = "OPEN_GAP_TOUCHES_MINUTE"


def minute_floor(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(second=0, microsecond=0)


def closed_before(now: datetime, safety_seconds: int) -> datetime:
    """Latest minute open_time that counts as closed at ``now``.

    A minute is closed once its close_time plus the safety margin has passed.
    The margin keeps the rebuild away from the minute the live aggregator may
    still be finishing.
    """
    if safety_seconds < 0:
        raise ValueError("safety_seconds must not be negative")
    return minute_floor(now - timedelta(seconds=safety_seconds)) - ONE_MINUTE


def candle_output_hash(candle: Candle) -> str:
    """Deterministic COMPLETED output_hash for every outbox row of one rebuilt minute."""
    payload = {
        "close": candle.close,
        "high": candle.high,
        "low": candle.low,
        "open": candle.open,
        "open_time": candle.open_time.astimezone(UTC).isoformat(),
        "rebuild": REBUILD_VERSION,
        "symbol": candle.symbol,
        "timeframe": candle.timeframe,
        "trade_count": candle.trade_count,
        "volume": candle.volume,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class MinutePlan:
    """One minute that carries DEFERRED CANDLE_V1 work, with its rebuild verdict."""

    symbol: str
    open_time: datetime
    deferred_items: int
    active_items: int
    completed_items: int
    raw_trades: int
    min_trade_id: int
    max_trade_id: int
    open_gaps: int
    blocker: str | None

    @property
    def rebuildable(self) -> bool:
        return self.blocker is None


def classify_minute(
    *,
    symbol: str,
    open_time: datetime,
    deferred_items: int,
    active_items: int,
    completed_items: int,
    raw_trades: int,
    min_trade_id: int,
    max_trade_id: int,
    open_gaps: int,
    closed_through: datetime,
    scope: str = SCOPE_DEFERRED,
) -> MinutePlan:
    """Pure verdict for one minute; the SQL only supplies the counts.

    ``SCOPE_DEFERRED`` minutes carry DEFERRED CANDLE_V1 rows that this tool
    completes. ``SCOPE_UNCANDLED`` minutes have raw trades but no closed candle
    and no outbox work at all (for example promoted offline candidates); they
    get a candle only, and a minute that still has DEFERRED rows is sent to
    the deferred scope instead of being handled twice.
    """
    if scope not in (SCOPE_DEFERRED, SCOPE_UNCANDLED):
        raise ValueError("unknown rebuild scope")
    if scope == SCOPE_DEFERRED and deferred_items < 1:
        raise ValueError("a deferred minute plan needs at least one DEFERRED item")
    if raw_trades < 1:
        raise ValueError("a minute plan needs at least one raw trade")
    blocker: str | None = None
    if open_time > closed_through:
        blocker = BLOCKER_NOT_CLOSED
    elif active_items > 0:
        blocker = BLOCKER_LIVE_WORK
    elif scope == SCOPE_UNCANDLED and deferred_items > 0:
        blocker = BLOCKER_DEFERRED_WORK
    elif open_gaps > 0:
        blocker = BLOCKER_OPEN_GAP
    return MinutePlan(
        symbol=symbol,
        open_time=open_time,
        deferred_items=deferred_items,
        active_items=active_items,
        completed_items=completed_items,
        raw_trades=raw_trades,
        min_trade_id=min_trade_id,
        max_trade_id=max_trade_id,
        open_gaps=open_gaps,
        blocker=blocker,
    )


# A gap "touches" a minute when the missing IDs sit directly next to the
# minute's trades (the missing trades could belong to this minute) or when its
# recorded time span overlaps the minute. Both tests are kept: TRADE_ID_GAP
# rows carry times, other reasons may carry only IDs.
_INVENTORY_SQL = """
WITH deferred AS (
    SELECT t.trade_time, o.aggregate_trade_id
    FROM ingestion_outbox o
    JOIN agg_trades t ON t.symbol=o.symbol AND t.aggregate_trade_id=o.aggregate_trade_id
    WHERE o.worker_name=$2 AND o.symbol=$1 AND o.status='DEFERRED'
), minutes AS (
    SELECT date_trunc('minute', trade_time) AS open_time, count(*) AS deferred_items
    FROM deferred GROUP BY 1 ORDER BY 1 LIMIT $4
), raw AS (
    SELECT m.open_time, count(*) AS raw_trades,
           min(t.aggregate_trade_id) AS min_trade_id, max(t.aggregate_trade_id) AS max_trade_id
    FROM minutes m
    JOIN agg_trades t ON t.symbol=$1 AND t.trade_time >= m.open_time AND t.trade_time < m.open_time + interval '1 minute'
    GROUP BY m.open_time
), work AS (
    SELECT m.open_time,
           count(*) FILTER (WHERE o.status = ANY($3::text[])) AS active_items,
           count(*) FILTER (WHERE o.status='COMPLETED') AS completed_items
    FROM minutes m
    JOIN agg_trades t ON t.symbol=$1 AND t.trade_time >= m.open_time AND t.trade_time < m.open_time + interval '1 minute'
    JOIN ingestion_outbox o ON o.symbol=t.symbol AND o.aggregate_trade_id=t.aggregate_trade_id AND o.worker_name=$2
    GROUP BY m.open_time
)
SELECT m.open_time, m.deferred_items, r.raw_trades, r.min_trade_id, r.max_trade_id,
       COALESCE(w.active_items, 0) AS active_items, COALESCE(w.completed_items, 0) AS completed_items,
       (SELECT count(*) FROM ingestion_gap_incidents g
         WHERE g.symbol=$1 AND g.status IN ('OPEN','CATCHING_UP')
           AND ((g.missing_from_id IS NOT NULL AND g.missing_from_id <= r.max_trade_id + 1 AND g.missing_to_id >= r.min_trade_id - 1)
             OR (g.gap_started_at IS NOT NULL AND g.gap_ended_at IS NOT NULL
                 AND g.gap_started_at < m.open_time + interval '1 minute' AND g.gap_ended_at >= m.open_time))
       ) AS open_gaps
FROM minutes m JOIN raw r USING (open_time) LEFT JOIN work w USING (open_time)
ORDER BY m.open_time
"""

# Closed minutes inside [$2, $3) that have raw trades but no closed 1m candle.
# Bounded by a time window because this scans the raw table by time; the
# outbox counts tell whether the minute belongs to the live worker or to the
# deferred scope.
_UNCANDLED_SQL = """
WITH minutes AS (
    SELECT date_trunc('minute', trade_time) AS open_time, count(*) AS raw_trades,
           min(aggregate_trade_id) AS min_trade_id, max(aggregate_trade_id) AS max_trade_id
    FROM agg_trades
    WHERE symbol=$1 AND trade_time >= $2 AND trade_time < $3
    GROUP BY 1
), missing AS (
    SELECT m.* FROM minutes m
    LEFT JOIN candles c ON c.symbol=$1 AND c.timeframe='1m' AND c.open_time=m.open_time
    WHERE c.open_time IS NULL OR c.closed = false
    ORDER BY m.open_time LIMIT $6
), work AS (
    SELECT ms.open_time,
           count(*) FILTER (WHERE o.status = ANY($5::text[])) AS active_items,
           count(*) FILTER (WHERE o.status='DEFERRED') AS deferred_items,
           count(*) FILTER (WHERE o.status='COMPLETED') AS completed_items
    FROM missing ms
    JOIN agg_trades t ON t.symbol=$1 AND t.trade_time >= ms.open_time AND t.trade_time < ms.open_time + interval '1 minute'
    JOIN ingestion_outbox o ON o.symbol=t.symbol AND o.aggregate_trade_id=t.aggregate_trade_id AND o.worker_name=$4
    GROUP BY ms.open_time
)
SELECT ms.open_time, ms.raw_trades, ms.min_trade_id, ms.max_trade_id,
       COALESCE(w.active_items, 0) AS active_items, COALESCE(w.deferred_items, 0) AS deferred_items,
       COALESCE(w.completed_items, 0) AS completed_items,
       (SELECT count(*) FROM ingestion_gap_incidents g
         WHERE g.symbol=$1 AND g.status IN ('OPEN','CATCHING_UP')
           AND ((g.missing_from_id IS NOT NULL AND g.missing_from_id <= ms.max_trade_id + 1 AND g.missing_to_id >= ms.min_trade_id - 1)
             OR (g.gap_started_at IS NOT NULL AND g.gap_ended_at IS NOT NULL
                 AND g.gap_started_at < ms.open_time + interval '1 minute' AND g.gap_ended_at >= ms.open_time))
       ) AS open_gaps
FROM missing ms LEFT JOIN work w USING (open_time)
ORDER BY ms.open_time
"""

_CANDLE_SQL = """
SELECT (array_agg(price ORDER BY trade_time, aggregate_trade_id))[1] AS open,
       max(price) AS high, min(price) AS low,
       (array_agg(price ORDER BY trade_time DESC, aggregate_trade_id DESC))[1] AS close,
       sum(quantity) AS volume, count(*) AS trade_count
FROM agg_trades
WHERE symbol=$1 AND trade_time >= $2 AND trade_time < $2 + interval '1 minute'
"""


async def inventory(
    connection: Any,
    symbol: str,
    *,
    now: datetime | None = None,
    safety_seconds: int = 120,
    max_minutes: int = 500,
) -> list[MinutePlan]:
    """Oldest-first minutes with DEFERRED CANDLE_V1 rows and their verdicts. Read-only."""
    if not 1 <= max_minutes <= 10_000:
        raise ValueError("max_minutes must be between 1 and 10000")
    closed_through = closed_before(now or datetime.now(UTC), safety_seconds)
    rows = await connection.fetch(_INVENTORY_SQL, symbol, FIRST_WORKER, list(ACTIVE_OUTBOX_STATUSES), max_minutes)
    return [
        classify_minute(
            symbol=symbol,
            open_time=row["open_time"].astimezone(UTC),
            deferred_items=int(row["deferred_items"]),
            active_items=int(row["active_items"]),
            completed_items=int(row["completed_items"]),
            raw_trades=int(row["raw_trades"]),
            min_trade_id=int(row["min_trade_id"]),
            max_trade_id=int(row["max_trade_id"]),
            open_gaps=int(row["open_gaps"]),
            closed_through=closed_through,
        )
        for row in rows
    ]


async def inventory_uncandled(
    connection: Any,
    symbol: str,
    *,
    window_start: datetime,
    window_end: datetime | None = None,
    now: datetime | None = None,
    safety_seconds: int = 120,
    max_minutes: int = 500,
) -> list[MinutePlan]:
    """Closed minutes in the window with raw trades but no closed 1m candle. Read-only.

    The window end is clamped to the last closed minute, so the live minute is
    never part of the scan.
    """
    if not 1 <= max_minutes <= 10_000:
        raise ValueError("max_minutes must be between 1 and 10000")
    if window_start.tzinfo is None or (window_end is not None and window_end.tzinfo is None):
        raise ValueError("window bounds must be timezone-aware")
    closed_through = closed_before(now or datetime.now(UTC), safety_seconds)
    end = closed_through + ONE_MINUTE
    if window_end is not None:
        end = min(end, window_end.astimezone(UTC))
    start = window_start.astimezone(UTC)
    if end <= start:
        return []
    rows = await connection.fetch(
        _UNCANDLED_SQL, symbol, start, end, FIRST_WORKER, list(ACTIVE_OUTBOX_STATUSES), max_minutes
    )
    return [
        classify_minute(
            symbol=symbol,
            open_time=row["open_time"].astimezone(UTC),
            deferred_items=int(row["deferred_items"]),
            active_items=int(row["active_items"]),
            completed_items=int(row["completed_items"]),
            raw_trades=int(row["raw_trades"]),
            min_trade_id=int(row["min_trade_id"]),
            max_trade_id=int(row["max_trade_id"]),
            open_gaps=int(row["open_gaps"]),
            closed_through=closed_through,
            scope=SCOPE_UNCANDLED,
        )
        for row in rows
    ]


async def deferred_counts(connection: Any, symbol: str) -> dict[str, int]:
    """DEFERRED rows per worker, so the report shows what this tool does not touch."""
    rows = await connection.fetch(
        "SELECT worker_name, count(*) AS n FROM ingestion_outbox WHERE symbol=$1 AND status='DEFERRED' GROUP BY worker_name",
        symbol,
    )
    return {row["worker_name"]: int(row["n"]) for row in rows}


@dataclass(slots=True)
class MinuteResult:
    open_time: str
    status: str
    deferred_items: int
    raw_trades: int
    blocker: str | None = None
    candle_action: str | None = None
    output_hash: str | None = None
    detail: str | None = None


@dataclass(slots=True)
class RebuildReport:
    symbol: str
    mode: str
    scope: str
    applied: bool
    checked_at_utc: str
    closed_through_utc: str
    planned_minutes: int
    window_start_utc: str | None = None
    window_end_utc: str | None = None
    rebuilt_minutes: int = 0
    rebuilt_items: int = 0
    blocked_minutes: int = 0
    conflict_minutes: int = 0
    candles_inserted: int = 0
    candles_updated: int = 0
    candles_unchanged: int = 0
    deferred_by_worker: dict[str, int] = field(default_factory=dict)
    minutes: list[MinuteResult] = field(default_factory=list)
    synthetic_data: bool = False
    forward_fill: bool = False
    live_cursor_mutations: int = 0
    live_queue_mutations: int = 0
    gap_ledger_mutations: int = 0
    trading_actions: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _candle_from_aggregate(symbol: str, open_time: datetime, row: Any) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe="1m",
        open_time=open_time,
        close_time=open_time + ONE_MINUTE,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
        trade_count=int(row["trade_count"]),
        closed=True,
    )


def _same_candle(existing: Any, candle: Candle) -> bool:
    return (
        existing is not None
        and bool(existing["closed"])
        and existing["close_time"] == candle.close_time
        and (float(existing["open"]), float(existing["high"]), float(existing["low"]), float(existing["close"]))
        == (candle.open, candle.high, candle.low, candle.close)
        and float(existing["volume"]) == candle.volume
        and int(existing["trade_count"]) == candle.trade_count
    )


async def _rebuild_minute(connection: Any, plan: MinutePlan, scope: str = SCOPE_DEFERRED) -> MinuteResult:
    """Rebuild one minute in its own transaction; a conflict rolls the minute back."""
    result = MinuteResult(
        open_time=plan.open_time.isoformat(), status="REBUILT",
        deferred_items=plan.deferred_items, raw_trades=plan.raw_trades,
    )
    async with connection.transaction():
        # Serialize with the store's enqueue/acknowledge path, which takes the
        # same advisory lock before it changes outbox rows.
        await connection.execute("SELECT pg_advisory_xact_lock($1)", _QUEUE_LOCK_KEY)
        locked = await connection.fetch(
            """SELECT o.outbox_id FROM ingestion_outbox o
               JOIN agg_trades t ON t.symbol=o.symbol AND t.aggregate_trade_id=o.aggregate_trade_id
               WHERE o.symbol=$1 AND o.worker_name=$2 AND o.status='DEFERRED'
                 AND t.trade_time >= $3 AND t.trade_time < $3 + interval '1 minute'
               FOR UPDATE OF o""",
            plan.symbol, FIRST_WORKER, plan.open_time,
        )
        expected_deferred = plan.deferred_items if scope == SCOPE_DEFERRED else 0
        if len(locked) != expected_deferred:
            raise _MinuteConflict(f"deferred rows changed since planning: {len(locked)} != {expected_deferred}")
        active = await connection.fetchval(
            """SELECT count(*) FROM ingestion_outbox o
               JOIN agg_trades t ON t.symbol=o.symbol AND t.aggregate_trade_id=o.aggregate_trade_id
               WHERE o.symbol=$1 AND o.worker_name=$2 AND o.status = ANY($4::text[])
                 AND t.trade_time >= $3 AND t.trade_time < $3 + interval '1 minute'""",
            plan.symbol, FIRST_WORKER, plan.open_time, list(ACTIVE_OUTBOX_STATUSES),
        )
        if int(active) != 0:
            raise _MinuteConflict("live CANDLE_V1 work appeared in the minute since planning")
        aggregate = await connection.fetchrow(_CANDLE_SQL, plan.symbol, plan.open_time)
        if aggregate is None or aggregate["trade_count"] is None or int(aggregate["trade_count"]) != plan.raw_trades:
            raise _MinuteConflict("raw trade count changed since planning")
        candle = _candle_from_aggregate(plan.symbol, plan.open_time, aggregate)
        existing = await connection.fetchrow(
            "SELECT close_time,open,high,low,close,volume,trade_count,closed FROM candles WHERE symbol=$1 AND timeframe='1m' AND open_time=$2 FOR UPDATE",
            plan.symbol, plan.open_time,
        )
        if existing is None:
            result.candle_action = "INSERTED"
        elif _same_candle(existing, candle):
            result.candle_action = "UNCHANGED"
        else:
            result.candle_action = "UPDATED"
        if result.candle_action != "UNCHANGED":
            await connection.execute(
                """INSERT INTO candles(symbol,timeframe,open_time,close_time,open,high,low,close,volume,trade_count,closed)
                   VALUES($1,'1m',$2,$3,$4,$5,$6,$7,$8,$9,true)
                   ON CONFLICT(symbol,timeframe,open_time) DO UPDATE SET
                     close_time=EXCLUDED.close_time,open=EXCLUDED.open,high=EXCLUDED.high,low=EXCLUDED.low,
                     close=EXCLUDED.close,volume=EXCLUDED.volume,trade_count=EXCLUDED.trade_count,closed=true""",
                candle.symbol, candle.open_time, candle.close_time, candle.open, candle.high,
                candle.low, candle.close, candle.volume, candle.trade_count,
            )
        output_hash = candle_output_hash(candle)
        metadata = json.dumps({"rebuild": REBUILD_VERSION, "scope": scope, "symbol": plan.symbol, "last_open_time": plan.open_time.isoformat()})
        if scope == SCOPE_DEFERRED:
            status = await connection.execute(
                """UPDATE ingestion_outbox SET status='COMPLETED',output_hash=$3,completed_at=clock_timestamp(),
                       lease_expires_at=NULL,last_error=NULL,updated_at=clock_timestamp()
                   WHERE outbox_id = ANY($1::text[]) AND symbol=$2 AND status='DEFERRED'""",
                [row["outbox_id"] for row in locked], plan.symbol, output_hash,
            )
            if status != f"UPDATE {plan.deferred_items}":
                raise _MinuteConflict(f"outbox completion touched {status!r}, expected {plan.deferred_items} rows")
            await _count(connection, METRIC_REBUILT_ITEMS, plan.deferred_items, metadata)
            await _count(connection, METRIC_REBUILT_CANDLES, 1, metadata)
        else:
            await _count(connection, METRIC_UNCANDLED_CANDLES, 1, metadata)
        result.output_hash = output_hash
    return result


async def _count(connection: Any, name: str, amount: int, metadata: str) -> None:
    await connection.execute(
        """INSERT INTO ingestion_metrics(metric_name,metric_kind,numeric_value,metadata)
           VALUES($1,'COUNTER',$2,$3::jsonb)
           ON CONFLICT(metric_name) DO UPDATE SET numeric_value=ingestion_metrics.numeric_value+EXCLUDED.numeric_value,
           metadata=EXCLUDED.metadata,updated_at=clock_timestamp()""",
        name, amount, metadata,
    )


class _MinuteConflict(RuntimeError):
    """The database moved between planning and the minute's transaction."""


async def rebuild_deferred_candles(
    connection: Any,
    symbol: str,
    *,
    apply: bool,
    now: datetime | None = None,
    safety_seconds: int = 120,
    max_minutes: int = 500,
) -> RebuildReport:
    """Plan (and with ``apply`` execute) the rebuild for one symbol.

    Dry run is the default: it reports every minute and its verdict and writes
    nothing. With ``apply`` each rebuildable minute runs in its own transaction,
    so an interruption leaves whole rebuilt minutes behind and the next run
    simply continues with what is still DEFERRED.
    """
    checked_at = now or datetime.now(UTC)
    plans = await inventory(connection, symbol, now=checked_at, safety_seconds=safety_seconds, max_minutes=max_minutes)
    report = RebuildReport(
        symbol=symbol,
        mode="OBSERVE",
        scope=SCOPE_DEFERRED,
        applied=apply,
        checked_at_utc=checked_at.astimezone(UTC).isoformat(),
        closed_through_utc=closed_before(checked_at, safety_seconds).isoformat(),
        planned_minutes=len(plans),
        deferred_by_worker=await deferred_counts(connection, symbol),
    )
    await _execute_plans(connection, plans, report, apply=apply, scope=SCOPE_DEFERRED)
    return report


async def rebuild_uncandled_candles(
    connection: Any,
    symbol: str,
    *,
    apply: bool,
    window_start: datetime,
    window_end: datetime | None = None,
    now: datetime | None = None,
    safety_seconds: int = 120,
    max_minutes: int = 500,
) -> RebuildReport:
    """Second scope: closed minutes with raw trades and no closed candle, no outbox work.

    Covers raw data that reached ``agg_trades`` without any outbox row, such as
    promoted offline candidates. Minutes that still carry DEFERRED rows are
    reported as blocked here and belong to :func:`rebuild_deferred_candles`.
    Only ``candles`` is written.
    """
    checked_at = now or datetime.now(UTC)
    plans = await inventory_uncandled(
        connection, symbol, window_start=window_start, window_end=window_end,
        now=checked_at, safety_seconds=safety_seconds, max_minutes=max_minutes,
    )
    report = RebuildReport(
        symbol=symbol,
        mode="OBSERVE",
        scope=SCOPE_UNCANDLED,
        applied=apply,
        checked_at_utc=checked_at.astimezone(UTC).isoformat(),
        closed_through_utc=closed_before(checked_at, safety_seconds).isoformat(),
        planned_minutes=len(plans),
        deferred_by_worker=await deferred_counts(connection, symbol),
        window_start_utc=window_start.astimezone(UTC).isoformat(),
        window_end_utc=window_end.astimezone(UTC).isoformat() if window_end is not None else None,
    )
    await _execute_plans(connection, plans, report, apply=apply, scope=SCOPE_UNCANDLED)
    return report


async def _execute_plans(connection: Any, plans: list[MinutePlan], report: RebuildReport, *, apply: bool, scope: str) -> None:
    for plan in plans:
        if plan.blocker is not None:
            report.blocked_minutes += 1
            report.minutes.append(MinuteResult(
                open_time=plan.open_time.isoformat(), status="BLOCKED", blocker=plan.blocker,
                deferred_items=plan.deferred_items, raw_trades=plan.raw_trades,
            ))
            continue
        if not apply:
            report.minutes.append(MinuteResult(
                open_time=plan.open_time.isoformat(), status="PLANNED",
                deferred_items=plan.deferred_items, raw_trades=plan.raw_trades,
            ))
            continue
        try:
            result = await _rebuild_minute(connection, plan, scope)
        except _MinuteConflict as conflict:
            report.conflict_minutes += 1
            report.minutes.append(MinuteResult(
                open_time=plan.open_time.isoformat(), status="CONFLICT", detail=str(conflict),
                deferred_items=plan.deferred_items, raw_trades=plan.raw_trades,
            ))
            continue
        report.rebuilt_minutes += 1
        if scope == SCOPE_DEFERRED:
            report.rebuilt_items += plan.deferred_items
        if result.candle_action == "INSERTED":
            report.candles_inserted += 1
        elif result.candle_action == "UPDATED":
            report.candles_updated += 1
        else:
            report.candles_unchanged += 1
        report.minutes.append(result)
