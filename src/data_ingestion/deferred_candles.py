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

BLOCKER_NOT_CLOSED = "MINUTE_NOT_CLOSED"
BLOCKER_LIVE_WORK = "ACTIVE_LIVE_WORK_IN_MINUTE"
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
) -> MinutePlan:
    """Pure verdict for one minute; the SQL only supplies the counts."""
    if deferred_items < 1:
        raise ValueError("a minute plan needs at least one DEFERRED item")
    blocker: str | None = None
    if open_time > closed_through:
        blocker = BLOCKER_NOT_CLOSED
    elif active_items > 0:
        blocker = BLOCKER_LIVE_WORK
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
    applied: bool
    checked_at_utc: str
    closed_through_utc: str
    planned_minutes: int
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


async def _rebuild_minute(connection: Any, plan: MinutePlan) -> MinuteResult:
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
        if len(locked) != plan.deferred_items:
            raise _MinuteConflict(f"deferred rows changed since planning: {len(locked)} != {plan.deferred_items}")
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
        status = await connection.execute(
            """UPDATE ingestion_outbox SET status='COMPLETED',output_hash=$3,completed_at=clock_timestamp(),
                   lease_expires_at=NULL,last_error=NULL,updated_at=clock_timestamp()
               WHERE outbox_id = ANY($1::text[]) AND symbol=$2 AND status='DEFERRED'""",
            [row["outbox_id"] for row in locked], plan.symbol, output_hash,
        )
        if status != f"UPDATE {plan.deferred_items}":
            raise _MinuteConflict(f"outbox completion touched {status!r}, expected {plan.deferred_items} rows")
        await connection.execute(
            """INSERT INTO ingestion_metrics(metric_name,metric_kind,numeric_value,metadata)
               VALUES($1,'COUNTER',$2,$3::jsonb)
               ON CONFLICT(metric_name) DO UPDATE SET numeric_value=ingestion_metrics.numeric_value+EXCLUDED.numeric_value,
               metadata=EXCLUDED.metadata,updated_at=clock_timestamp()""",
            METRIC_REBUILT_ITEMS, plan.deferred_items,
            json.dumps({"rebuild": REBUILD_VERSION, "symbol": plan.symbol, "last_open_time": plan.open_time.isoformat()}),
        )
        await connection.execute(
            """INSERT INTO ingestion_metrics(metric_name,metric_kind,numeric_value,metadata)
               VALUES($1,'COUNTER',1,$2::jsonb)
               ON CONFLICT(metric_name) DO UPDATE SET numeric_value=ingestion_metrics.numeric_value+1,
               metadata=EXCLUDED.metadata,updated_at=clock_timestamp()""",
            METRIC_REBUILT_CANDLES,
            json.dumps({"rebuild": REBUILD_VERSION, "symbol": plan.symbol, "last_open_time": plan.open_time.isoformat()}),
        )
        result.output_hash = output_hash
    return result


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
        applied=apply,
        checked_at_utc=checked_at.astimezone(UTC).isoformat(),
        closed_through_utc=closed_before(checked_at, safety_seconds).isoformat(),
        planned_minutes=len(plans),
        deferred_by_worker=await deferred_counts(connection, symbol),
    )
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
            result = await _rebuild_minute(connection, plan)
        except _MinuteConflict as conflict:
            report.conflict_minutes += 1
            report.minutes.append(MinuteResult(
                open_time=plan.open_time.isoformat(), status="CONFLICT", detail=str(conflict),
                deferred_items=plan.deferred_items, raw_trades=plan.raw_trades,
            ))
            continue
        report.rebuilt_minutes += 1
        report.rebuilt_items += plan.deferred_items
        if result.candle_action == "INSERTED":
            report.candles_inserted += 1
        elif result.candle_action == "UPDATED":
            report.candles_updated += 1
        else:
            report.candles_unchanged += 1
        report.minutes.append(result)
    return report
