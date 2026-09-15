from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.database.connection import Database
from src.database.repository import (
    AGG_TRADE_SOURCE,
    _validate_agg_trade_for_persistence,
    agg_trade_hash,
)
from src.models.market_data import Trade


SOURCE = "BINANCE"
MARKET = "SPOT"
DATA_TYPE = "AGG_TRADE"
FIRST_WORKER = "CANDLE_V1"
PIPELINE_WORKERS = ("CANDLE_V1", "FEATURE_V1", "OBSERVATION_V1", "RESEARCH_TRIGGER_V1")
CURSOR_VERSION = 1
WORKER_VERSION = "1.0.0"
# Terminal records remain active operational work until an explicit audited
# recovery completes them.  Counting QUARANTINED also makes a successful
# QUARANTINED -> COMPLETED recovery reduce queue_depth by exactly one.
ACTIVE_OUTBOX_STATUSES = ("PENDING", "PROCESSING", "RETRY", "QUARANTINED")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DurableIngestionError(RuntimeError):
    """Base class for fail-closed durable-ingestion errors."""


class QueueCapacityError(DurableIngestionError):
    """The bounded outbox cannot accept another item without dropping work."""


class CursorConflictError(DurableIngestionError):
    """Persisted identity is associated with a different immutable payload."""


@dataclass(frozen=True, slots=True)
class CursorState:
    source: str
    market: str
    symbol: str
    data_type: str
    last_aggregate_trade_id: int | None
    last_event_time: datetime | None
    last_trade_time: datetime | None
    last_persisted_at: datetime | None
    cursor_version: int
    cursor_hash: str
    recovery_state: str
    updated_at: datetime

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> CursorState:
        return cls(**{field: row[field] for field in cls.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class IngestResult:
    raw_inserted: bool
    outbox_inserted: bool
    duplicate: bool
    out_of_order: bool
    gap_detected: bool
    queue_depth: int
    cursor: CursorState


@dataclass(frozen=True, slots=True)
class OutboxItem:
    outbox_id: str
    worker_name: str
    idempotency_key: str
    symbol: str
    aggregate_trade_id: int
    status: str
    attempts: int
    max_attempts: int
    input_hash: str
    worker_version: str
    created_at: datetime
    started_at: datetime | None
    last_error: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> OutboxItem:
        return cls(**{field: row[field] for field in cls.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class TerminalBlocker:
    outbox_id: str
    worker_name: str
    aggregate_trade_id: int
    status: str
    last_error: str | None
    attempts: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    quarantined_at: datetime
    strict_order_position: int = 1

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> TerminalBlocker:
        return cls(
            outbox_id=row["outbox_id"],
            worker_name=row["worker_name"],
            aggregate_trade_id=row["aggregate_trade_id"],
            status=row["status"],
            last_error=row["last_error"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            quarantined_at=row["updated_at"],
        )


@dataclass(frozen=True, slots=True)
class ClaimResult:
    status: str
    items: tuple[OutboxItem, ...] = ()
    terminal_blocker: TerminalBlocker | None = None


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cursor_hash(
    *,
    symbol: str,
    last_aggregate_trade_id: int | None,
    last_event_time: datetime | None,
    last_trade_time: datetime | None,
    last_persisted_at: datetime | None,
    recovery_state: str,
) -> str:
    return _canonical_hash(
        {
            "cursor_version": CURSOR_VERSION,
            "data_type": DATA_TYPE,
            "last_aggregate_trade_id": last_aggregate_trade_id,
            "last_event_time": last_event_time.isoformat() if last_event_time else None,
            "last_persisted_at": last_persisted_at.isoformat() if last_persisted_at else None,
            "last_trade_time": last_trade_time.isoformat() if last_trade_time else None,
            "market": MARKET,
            "recovery_state": recovery_state,
            "source": SOURCE,
            "symbol": symbol,
        }
    )


def outbox_identity(symbol: str, aggregate_trade_id: int, worker_name: str) -> tuple[str, str]:
    idempotency_key = _canonical_hash(
        {
            "aggregate_trade_id": aggregate_trade_id,
            "data_type": DATA_TYPE,
            "market": MARKET,
            "source": SOURCE,
            "symbol": symbol,
        }
    )
    outbox_id = _canonical_hash({"idempotency_key": idempotency_key, "worker_name": worker_name})
    return outbox_id, idempotency_key


class DurableIngestionStore:
    """Transactional raw-event, cursor, gap-ledger and bounded-outbox store.

    The class deliberately exposes no order or execution operation. Queue overflow
    commits only a degraded/gap incident and rejects the event, so there can be no
    raw record without its cursor and first worker item.
    """

    _QUEUE_LOCK_KEY = 0x54494D4F55544258

    def __init__(
        self,
        database: Database,
        *,
        queue_capacity: int = 50_000,
        max_attempts: int = 5,
        worker_version: str = WORKER_VERSION,
    ) -> None:
        if queue_capacity < 1:
            raise ValueError("queue_capacity must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.database = database
        self.queue_capacity = queue_capacity
        self.max_attempts = max_attempts
        self.worker_version = worker_version

    @staticmethod
    async def _increment(
        connection: Any,
        name: str,
        amount: float = 1,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        await connection.execute(
            """INSERT INTO ingestion_metrics(metric_name,metric_kind,numeric_value,metadata)
               VALUES($1,'COUNTER',$2,$3::jsonb)
               ON CONFLICT(metric_name) DO UPDATE SET numeric_value=ingestion_metrics.numeric_value+EXCLUDED.numeric_value,
               metadata=EXCLUDED.metadata,updated_at=clock_timestamp()""",
            name,
            amount,
            json.dumps(dict(metadata or {})),
        )

    @staticmethod
    async def _gauge(
        connection: Any,
        name: str,
        value: float,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        await connection.execute(
            """INSERT INTO ingestion_metrics(metric_name,metric_kind,numeric_value,metadata)
               VALUES($1,'GAUGE',$2,$3::jsonb)
               ON CONFLICT(metric_name) DO UPDATE SET numeric_value=EXCLUDED.numeric_value,
               metadata=EXCLUDED.metadata,updated_at=clock_timestamp()""",
            name,
            value,
            json.dumps(dict(metadata or {})),
        )

    @staticmethod
    async def _maximum(connection: Any, name: str, value: float) -> None:
        await connection.execute(
            """INSERT INTO ingestion_metrics(metric_name,metric_kind,numeric_value)
               VALUES($1,'MAX',$2)
               ON CONFLICT(metric_name) DO UPDATE SET numeric_value=GREATEST(ingestion_metrics.numeric_value,EXCLUDED.numeric_value),
               updated_at=clock_timestamp()""",
            name,
            value,
        )

    @staticmethod
    async def _cursor_row(connection: Any, symbol: str, *, lock: bool = False) -> Any:
        suffix = " FOR UPDATE" if lock else ""
        return await connection.fetchrow(
            """SELECT * FROM ingestion_cursors
               WHERE source=$1 AND market=$2 AND symbol=$3 AND data_type=$4""" + suffix,
            SOURCE,
            MARKET,
            symbol,
            DATA_TYPE,
        )

    @staticmethod
    async def _write_cursor(
        connection: Any,
        *,
        symbol: str,
        trade_id: int | None,
        event_time: datetime | None,
        persisted_at: datetime | None,
        recovery_state: str,
    ) -> None:
        digest = cursor_hash(
            symbol=symbol,
            last_aggregate_trade_id=trade_id,
            last_event_time=event_time,
            last_trade_time=event_time,
            last_persisted_at=persisted_at,
            recovery_state=recovery_state,
        )
        await connection.execute(
            """INSERT INTO ingestion_cursors(
                   source,market,symbol,data_type,last_aggregate_trade_id,last_event_time,last_trade_time,
                   last_persisted_at,cursor_version,cursor_hash,recovery_state)
               VALUES($1,$2,$3,$4,$5,$6,$6,$7,$8,$9,$10)
               ON CONFLICT(source,market,symbol,data_type) DO UPDATE SET
                   last_aggregate_trade_id=EXCLUDED.last_aggregate_trade_id,
                   last_event_time=EXCLUDED.last_event_time,last_trade_time=EXCLUDED.last_trade_time,
                   last_persisted_at=EXCLUDED.last_persisted_at,cursor_version=EXCLUDED.cursor_version,
                   cursor_hash=EXCLUDED.cursor_hash,recovery_state=EXCLUDED.recovery_state,
                   updated_at=clock_timestamp()""",
            SOURCE,
            MARKET,
            symbol,
            DATA_TYPE,
            trade_id,
            event_time,
            persisted_at,
            CURSOR_VERSION,
            digest,
            recovery_state,
        )

    @staticmethod
    async def _record_gap_on_connection(
        connection: Any,
        *,
        symbol: str,
        missing_from_id: int | None,
        missing_to_id: int | None,
        reason: str,
        gap_started_at: datetime | None = None,
        gap_ended_at: datetime | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> str:
        gap_id = _canonical_hash(
            {
                "data_type": DATA_TYPE,
                "market": MARKET,
                "missing_from_id": missing_from_id,
                "missing_to_id": missing_to_id,
                "reason": reason,
                "source": SOURCE,
                "symbol": symbol,
            }
        )
        await connection.execute(
            """INSERT INTO ingestion_gap_incidents(
                   gap_id,source,market,symbol,data_type,missing_from_id,missing_to_id,
                   gap_started_at,gap_ended_at,reason,details)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb)
               ON CONFLICT(gap_id) DO UPDATE SET details=EXCLUDED.details,updated_at=clock_timestamp()""",
            gap_id,
            SOURCE,
            MARKET,
            symbol,
            DATA_TYPE,
            missing_from_id,
            missing_to_id,
            gap_started_at,
            gap_ended_at,
            reason,
            json.dumps(dict(details or {})),
        )
        return gap_id

    async def ingest_trade(self, trade: Trade, *, first_worker: str = FIRST_WORKER) -> IngestResult:
        if first_worker not in PIPELINE_WORKERS:
            raise ValueError("first_worker is not an approved OBSERVE pipeline stage")
        _validate_agg_trade_for_persistence(trade)
        assert trade.trade_id is not None
        input_hash = agg_trade_hash(trade)
        outbox_id, idempotency_key = outbox_identity(trade.symbol, trade.trade_id, first_worker)
        capacity_rejected = False

        async with self.database.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", self._QUEUE_LOCK_KEY)
                await self._increment(connection, "received_total")
                existing_work = await connection.fetchval(
                    "SELECT 1 FROM ingestion_outbox WHERE worker_name=$1 AND idempotency_key=$2",
                    first_worker,
                    idempotency_key,
                )
                queue_depth = int(
                    await connection.fetchval(
                        "SELECT count(*) FROM ingestion_outbox WHERE status=ANY($1::text[])",
                        list(ACTIVE_OUTBOX_STATUSES),
                    )
                )
                cursor_row = await self._cursor_row(connection, trade.symbol, lock=True)
                if cursor_row is None:
                    legacy_high_water = await connection.fetchrow(
                        """SELECT aggregate_trade_id,trade_time,ingest_timestamp FROM agg_trades
                           WHERE symbol=$1 ORDER BY aggregate_trade_id DESC LIMIT 1""",
                        trade.symbol,
                    )
                    if legacy_high_water is not None:
                        await self._write_cursor(
                            connection,
                            symbol=trade.symbol,
                            trade_id=legacy_high_water["aggregate_trade_id"],
                            event_time=legacy_high_water["trade_time"],
                            persisted_at=legacy_high_water["ingest_timestamp"],
                            recovery_state="NORMAL",
                        )
                        cursor_row = await self._cursor_row(connection, trade.symbol, lock=True)

                if not existing_work and queue_depth >= self.queue_capacity:
                    await self._record_gap_on_connection(
                        connection,
                        symbol=trade.symbol,
                        missing_from_id=trade.trade_id,
                        missing_to_id=trade.trade_id,
                        reason="OUTBOX_CAPACITY",
                        gap_started_at=trade.event_time,
                        gap_ended_at=trade.event_time,
                        details={"capacity": self.queue_capacity, "queue_depth": queue_depth},
                    )
                    if cursor_row:
                        await self._write_cursor(
                            connection,
                            symbol=trade.symbol,
                            trade_id=cursor_row["last_aggregate_trade_id"],
                            event_time=cursor_row["last_event_time"],
                            persisted_at=cursor_row["last_persisted_at"],
                            recovery_state="DEGRADED",
                        )
                    await self._increment(connection, "rejected_total")
                    await self._increment(connection, "reject_reason:OUTBOX_CAPACITY")
                    await self._increment(connection, "gap_total")
                    await self._gauge(connection, "queue_depth", queue_depth)
                    capacity_rejected = True
                else:
                    inserted_row = await connection.fetchrow(
                        """INSERT INTO agg_trades(
                               symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker,source)
                           VALUES($1,$2,$3,$4,$5,$6,$7)
                           ON CONFLICT(symbol,aggregate_trade_id) DO NOTHING
                           RETURNING ingest_timestamp""",
                        trade.symbol,
                        trade.trade_id,
                        trade.event_time,
                        trade.price,
                        trade.quantity,
                        trade.buyer_is_maker,
                        AGG_TRADE_SOURCE,
                    )
                    raw_inserted = inserted_row is not None
                    if raw_inserted:
                        persisted_at = inserted_row["ingest_timestamp"]
                        await self._increment(connection, "raw_persisted_total")
                    else:
                        existing = await connection.fetchrow(
                            """SELECT symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker,source,ingest_timestamp
                               FROM agg_trades WHERE symbol=$1 AND aggregate_trade_id=$2""",
                            trade.symbol,
                            trade.trade_id,
                        )
                        stored = Trade(
                            existing["symbol"], existing["price"], existing["quantity"],
                            existing["trade_time"], existing["aggregate_trade_id"], existing["buyer_is_maker"],
                        )
                        if existing["source"] != AGG_TRADE_SOURCE or agg_trade_hash(stored) != input_hash:
                            raise CursorConflictError("Conflicting payload for persisted aggregate_trade_id")
                        persisted_at = existing["ingest_timestamp"]
                        await self._increment(connection, "duplicate_total")

                    prior_id = cursor_row["last_aggregate_trade_id"] if cursor_row else None
                    prior_time = cursor_row["last_event_time"] if cursor_row else None
                    out_of_order = prior_id is not None and trade.trade_id <= prior_id
                    gap_detected = prior_id is not None and trade.trade_id > prior_id + 1
                    if out_of_order and raw_inserted:
                        await self._increment(connection, "out_of_order_total")
                        if prior_time and trade.event_time < prior_time:
                            await self._increment(connection, "late_total")
                    if gap_detected:
                        await self._record_gap_on_connection(
                            connection,
                            symbol=trade.symbol,
                            missing_from_id=prior_id + 1,
                            missing_to_id=trade.trade_id - 1,
                            reason="TRADE_ID_GAP",
                            gap_started_at=prior_time,
                            gap_ended_at=trade.event_time,
                        )
                        await self._increment(connection, "gap_total")

                    status = await connection.execute(
                        """INSERT INTO ingestion_outbox(
                               outbox_id,worker_name,idempotency_key,source,market,symbol,data_type,
                               aggregate_trade_id,input_hash,worker_version,max_attempts)
                           VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                           ON CONFLICT(worker_name,idempotency_key) DO NOTHING""",
                        outbox_id,
                        first_worker,
                        idempotency_key,
                        SOURCE,
                        MARKET,
                        trade.symbol,
                        DATA_TYPE,
                        trade.trade_id,
                        input_hash,
                        self.worker_version,
                        self.max_attempts,
                    )
                    outbox_inserted = status == "INSERT 0 1"
                    if prior_id is None or trade.trade_id > prior_id:
                        prior_state = cursor_row["recovery_state"] if cursor_row else "NORMAL"
                        recovery_state = "GAP_DETECTED" if gap_detected else prior_state
                        await self._write_cursor(
                            connection,
                            symbol=trade.symbol,
                            trade_id=trade.trade_id,
                            event_time=trade.event_time,
                            persisted_at=persisted_at,
                            recovery_state=recovery_state,
                        )

                    queue_depth += int(outbox_inserted)
                    await self._gauge(connection, "queue_depth", queue_depth)
                    await self._maximum(connection, "queue_high_water", queue_depth)
                    latency = max(0.0, (datetime.now(timezone.utc) - trade.event_time).total_seconds())
                    await self._gauge(connection, "source_to_store_latency", latency)

            if capacity_rejected:
                raise QueueCapacityError(
                    f"durable outbox capacity {self.queue_capacity} reached; event rejected for catch-up"
                )

            current = await self._cursor_row(connection, trade.symbol)
            assert current is not None
            return IngestResult(
                raw_inserted=raw_inserted,
                outbox_inserted=outbox_inserted,
                duplicate=not raw_inserted,
                out_of_order=out_of_order,
                gap_detected=gap_detected,
                queue_depth=queue_depth,
                cursor=CursorState.from_row(current),
            )

    async def get_cursor(self, symbol: str) -> CursorState | None:
        async with self.database.acquire() as connection:
            row = await self._cursor_row(connection, symbol)
        return CursorState.from_row(row) if row else None

    async def approved_live_cutover(self, symbol: str, cursor_id: int | None, first_live_id: int) -> bool:
        """Allow exactly the documented discontinuity, never a later reconnect."""
        if cursor_id is None:
            return False
        async with self.database.acquire() as connection:
            row = await connection.fetchrow(
                """SELECT baseline_cursor_id,first_live_trade_id FROM live_cutover_receipts
                   WHERE symbol=$1 ORDER BY created_at DESC LIMIT 1""", symbol
            )
        return bool(row and cursor_id == row["baseline_cursor_id"] and first_live_id >= row["first_live_trade_id"])

    async def bootstrap_cursor(self, symbol: str) -> CursorState | None:
        """Create the first cursor from immutable legacy raw data, if present."""
        async with self.database.acquire() as connection:
            async with connection.transaction():
                row = await self._cursor_row(connection, symbol, lock=True)
                if row is None:
                    high_water = await connection.fetchrow(
                        """SELECT aggregate_trade_id,trade_time,ingest_timestamp FROM agg_trades
                           WHERE symbol=$1 ORDER BY aggregate_trade_id DESC LIMIT 1""",
                        symbol,
                    )
                    if high_water is not None:
                        await self._write_cursor(
                            connection,
                            symbol=symbol,
                            trade_id=high_water["aggregate_trade_id"],
                            event_time=high_water["trade_time"],
                            persisted_at=high_water["ingest_timestamp"],
                            recovery_state="NORMAL",
                        )
                    else:
                        await self._write_cursor(
                            connection,
                            symbol=symbol,
                            trade_id=None,
                            event_time=None,
                            persisted_at=None,
                            recovery_state="NORMAL",
                        )
                    row = await self._cursor_row(connection, symbol, lock=True)
        return CursorState.from_row(row) if row else None

    async def processed_trades_since(self, symbol: str, since: datetime) -> list[Trade]:
        """Replay only legacy or acknowledged raw work; pending work stays pending."""
        async with self.database.acquire() as connection:
            rows = await connection.fetch(
                """SELECT raw.symbol,raw.aggregate_trade_id,raw.trade_time,raw.price,raw.quantity,raw.buyer_is_maker
                   FROM agg_trades raw
                   LEFT JOIN ingestion_outbox work ON work.symbol=raw.symbol
                       AND work.aggregate_trade_id=raw.aggregate_trade_id AND work.worker_name='CANDLE_V1'
                   WHERE raw.symbol=$1 AND raw.trade_time>=$2
                   AND (work.outbox_id IS NULL OR work.status='COMPLETED')
                   ORDER BY raw.trade_time,raw.aggregate_trade_id""",
                symbol,
                since,
            )
        return [
            Trade(
                row["symbol"], row["price"], row["quantity"], row["trade_time"],
                row["aggregate_trade_id"], row["buyer_is_maker"],
            )
            for row in rows
        ]

    async def load_trade(self, symbol: str, aggregate_trade_id: int) -> Trade:
        async with self.database.acquire() as connection:
            row = await connection.fetchrow(
                """SELECT symbol,price,quantity,trade_time,aggregate_trade_id,buyer_is_maker
                   FROM agg_trades WHERE symbol=$1 AND aggregate_trade_id=$2""",
                symbol,
                aggregate_trade_id,
            )
        if row is None:
            raise DurableIngestionError("outbox references a missing raw event")
        return Trade(
            row["symbol"], row["price"], row["quantity"], row["trade_time"],
            row["aggregate_trade_id"], row["buyer_is_maker"],
        )

    async def claim(
        self,
        worker_name: str,
        *,
        limit: int = 100,
        lease_seconds: int = 60,
        strict_order: bool = False,
    ) -> list[OutboxItem]:
        if not 1 <= limit <= 1_000:
            raise ValueError("claim limit must be between 1 and 1000")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        async with self.database.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """UPDATE ingestion_outbox SET status='RETRY',available_at=clock_timestamp(),
                       lease_expires_at=NULL,last_error=COALESCE(last_error,'worker lease expired'),updated_at=clock_timestamp()
                       WHERE worker_name=$1 AND status='PROCESSING' AND lease_expires_at<clock_timestamp()""",
                    worker_name,
                )
                ordering_guard = """
                           AND NOT EXISTS (
                               SELECT 1 FROM ingestion_outbox blocker
                               WHERE blocker.worker_name=ingestion_outbox.worker_name
                               AND blocker.status=ANY($4::text[])
                               AND (blocker.aggregate_trade_id,blocker.created_at,blocker.outbox_id)
                                   < (ingestion_outbox.aggregate_trade_id,ingestion_outbox.created_at,ingestion_outbox.outbox_id)
                           )""" if strict_order else ""
                rows = await connection.fetch(
                    """WITH candidates AS (
                           SELECT outbox_id FROM ingestion_outbox
                           WHERE worker_name=$1 AND status IN ('PENDING','RETRY') AND available_at<=clock_timestamp()
                    """ + ordering_guard + """
                           ORDER BY aggregate_trade_id,created_at,outbox_id FOR UPDATE SKIP LOCKED LIMIT $2
                       )
                       UPDATE ingestion_outbox AS work SET status='PROCESSING',attempts=work.attempts+1,
                           started_at=clock_timestamp(),lease_expires_at=clock_timestamp()+($3*interval '1 second'),
                           updated_at=clock_timestamp()
                       FROM candidates WHERE work.outbox_id=candidates.outbox_id
                       RETURNING work.*""",
                    worker_name,
                    limit,
                    lease_seconds,
                    list(ACTIVE_OUTBOX_STATUSES),
                )
        return [OutboxItem.from_row(row) for row in rows]

    async def claim_detailed(
        self,
        worker_name: str,
        *,
        limit: int = 100,
        lease_seconds: int = 60,
        strict_order: bool = False,
    ) -> ClaimResult:
        """Additive claim API that distinguishes idle from terminal blockage."""
        items = await self.claim(
            worker_name,
            limit=limit,
            lease_seconds=lease_seconds,
            strict_order=strict_order,
        )
        if items:
            return ClaimResult("CLAIMED", tuple(items))
        if strict_order:
            async with self.database.acquire() as connection:
                row = await connection.fetchrow(
                    """SELECT outbox_id,worker_name,aggregate_trade_id,status,last_error,
                              attempts,max_attempts,created_at,updated_at
                       FROM ingestion_outbox
                       WHERE worker_name=$1 AND status<>'COMPLETED'
                       ORDER BY aggregate_trade_id,created_at,outbox_id LIMIT 1""",
                    worker_name,
                )
            if row is not None and row["status"] == "QUARANTINED":
                return ClaimResult(
                    "TERMINAL_BLOCKED",
                    terminal_blocker=TerminalBlocker.from_row(row),
                )
        return ClaimResult("IDLE")

    async def claim_quarantined(self, outbox_id: str, *, lease_seconds: int = 300) -> OutboxItem | None:
        """Explicitly lease exactly one quarantined record without resetting attempts."""
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        async with self.database.acquire() as connection:
            row = await connection.fetchrow(
                """UPDATE ingestion_outbox SET status='PROCESSING',started_at=clock_timestamp(),
                          lease_expires_at=clock_timestamp()+($2*interval '1 second'),updated_at=clock_timestamp()
                   WHERE outbox_id=$1 AND status='QUARANTINED' RETURNING *""",
                outbox_id,
                lease_seconds,
            )
        return OutboxItem.from_row(row) if row else None

    async def inspect_recovery_target(self, outbox_id: str) -> dict[str, Any]:
        """Read one exact recovery target without claiming or modifying it."""
        async with self.database.acquire() as connection:
            row = await connection.fetchrow(
                """SELECT outbox_id,aggregate_trade_id,status,attempts,max_attempts,last_error,
                          started_at,lease_expires_at,completed_at,created_at,updated_at
                   FROM ingestion_outbox WHERE outbox_id=$1""",
                outbox_id,
            )
        if row is None:
            return {"status": "NOT_FOUND", "outbox_id": outbox_id, "recoverable": False}
        return {
            "status": "RECOVERABLE" if row["status"] == "QUARANTINED" else "NOT_QUARANTINED",
            "outbox_id": row["outbox_id"],
            "trade_id": row["aggregate_trade_id"],
            "record_status": row["status"],
            "attempts": row["attempts"],
            "max_attempts": row["max_attempts"],
            "last_error": row["last_error"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "lease_expires_at": row["lease_expires_at"].isoformat() if row["lease_expires_at"] else None,
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
            "recoverable": row["status"] == "QUARANTINED",
        }

    async def list_quarantined_batch(self, worker_name: str, limit: int) -> list[OutboxItem]:
        """Return only the contiguous quarantined prefix at the strict-order head."""
        if limit < 1:
            raise ValueError("limit must be positive")
        async with self.database.acquire() as connection:
            rows = await connection.fetch(
                """SELECT * FROM ingestion_outbox
                   WHERE worker_name=$1 AND status<>'COMPLETED'
                   ORDER BY aggregate_trade_id,created_at,outbox_id LIMIT $2""",
                worker_name,
                limit,
            )
        selected: list[OutboxItem] = []
        for row in rows:
            if row["status"] != "QUARANTINED":
                break
            selected.append(OutboxItem.from_row(row))
        return selected

    async def load_batch_target_trades(self, items: list[OutboxItem]) -> list[Trade]:
        """Load a bounded target set in one indexed raw-trade query."""
        if not items:
            return []
        symbol = items[0].symbol
        ids = [item.aggregate_trade_id for item in items]
        if any(item.symbol != symbol for item in items):
            raise ValueError("batch targets must share symbol")
        async with self.database.acquire() as connection:
            rows = await connection.fetch(
                """SELECT symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker
                   FROM agg_trades WHERE symbol=$1 AND aggregate_trade_id=ANY($2::bigint[])
                   ORDER BY aggregate_trade_id""",
                symbol,
                ids,
            )
        by_id = {
            row["aggregate_trade_id"]: Trade(
                row["symbol"], row["price"], row["quantity"], row["trade_time"],
                row["aggregate_trade_id"], row["buyer_is_maker"],
            )
            for row in rows
        }
        missing = set(ids) - set(by_id)
        if missing:
            raise RuntimeError(f"batch targets missing from agg_trades: {sorted(missing)}")
        return [by_id[value] for value in ids]

    async def recovery_guard_snapshot(
        self,
        worker_name: str,
        symbol: str,
        target_ids: list[str],
    ) -> dict[str, Any]:
        """Compact read-only invariants used around every recovery commit."""
        async with self.database.acquire() as connection:
            status_rows = await connection.fetch(
                """SELECT status,count(*)::bigint AS count,
                          max(updated_at) FILTER (WHERE NOT outbox_id=ANY($2::text[])) AS foreign_updated_at
                   FROM ingestion_outbox WHERE worker_name=$1 GROUP BY status""",
                worker_name,
                target_ids,
            )
            targets = await connection.fetch(
                """SELECT outbox_id,status,attempts FROM ingestion_outbox
                   WHERE outbox_id=ANY($1::text[]) ORDER BY aggregate_trade_id,created_at,outbox_id""",
                target_ids,
            )
            cursor = await connection.fetchrow(
                """SELECT cursor_hash,recovery_state FROM ingestion_cursors
                   WHERE source=$1 AND market=$2 AND symbol=$3 AND data_type=$4""",
                SOURCE,
                MARKET,
                symbol,
                DATA_TYPE,
            )
            open_gaps = int(
                await connection.fetchval(
                    """SELECT count(*) FROM ingestion_gap_incidents
                       WHERE symbol=$1 AND status IN ('OPEN','CATCHING_UP')""",
                    symbol,
                )
            )
        counts = {
            status: 0
            for status in ("PENDING", "PROCESSING", "RETRY", "COMPLETED", "QUARANTINED")
        }
        counts.update({row["status"]: int(row["count"]) for row in status_rows})
        foreign_updates = {status: None for status in counts}
        foreign_updates.update(
            {row["status"]: row["foreign_updated_at"] for row in status_rows}
        )
        return {
            "status_counts": counts,
            "foreign_status_updated_at": foreign_updates,
            "queue_depth": sum(counts.get(value, 0) for value in ACTIVE_OUTBOX_STATUSES),
            "processing": counts.get("PROCESSING", 0),
            "targets": {
                row["outbox_id"]: {"status": row["status"], "attempts": row["attempts"]}
                for row in targets
            },
            "cursor_hash": cursor["cursor_hash"] if cursor else None,
            "recovery_state": cursor["recovery_state"] if cursor else None,
            "open_gaps": open_gaps,
        }

    async def recovery_record_guard_snapshot(
        self, worker_name: str, symbol: str, target_ids: list[str]
    ) -> dict[str, Any]:
        """Indexed per-record invariants; global counts stay at batch boundaries."""
        async with self.database.acquire() as connection:
            processing = int(await connection.fetchval(
                "SELECT count(*) FROM ingestion_outbox WHERE worker_name=$1 AND status='PROCESSING'",
                worker_name,
            ))
            targets = await connection.fetch(
                """SELECT outbox_id,status,attempts FROM ingestion_outbox
                   WHERE outbox_id=ANY($1::text[]) ORDER BY aggregate_trade_id,created_at,outbox_id""",
                target_ids,
            )
            cursor = await connection.fetchrow(
                """SELECT cursor_hash,recovery_state FROM ingestion_cursors
                   WHERE source=$1 AND market=$2 AND symbol=$3 AND data_type=$4""",
                SOURCE, MARKET, symbol, DATA_TYPE,
            )
            open_gaps = int(await connection.fetchval(
                """SELECT count(*) FROM ingestion_gap_incidents
                   WHERE symbol=$1 AND status IN ('OPEN','CATCHING_UP')""", symbol,
            ))
        return {
            "processing": processing,
            "targets": {row["outbox_id"]: {"status": row["status"], "attempts": row["attempts"]} for row in targets},
            "cursor_hash": cursor["cursor_hash"] if cursor else None,
            "recovery_state": cursor["recovery_state"] if cursor else None,
            "open_gaps": open_gaps,
        }

    async def batch_replay_input(
        self,
        items: list[OutboxItem],
        since: datetime,
    ) -> list[tuple[Trade, str | None]]:
        """Load completed history and all explicit batch targets in one query."""
        if not items:
            return []
        symbol = items[0].symbol
        worker_name = items[0].worker_name
        if any(item.symbol != symbol or item.worker_name != worker_name for item in items):
            raise ValueError("batch targets must share symbol and worker")
        target_ids = [item.outbox_id for item in items]
        async with self.database.acquire() as connection:
            rows = await connection.fetch(
                """SELECT raw.symbol,raw.aggregate_trade_id,raw.trade_time,raw.price,
                          raw.quantity,raw.buyer_is_maker,
                          CASE WHEN work.outbox_id=ANY($4::text[]) THEN work.outbox_id END AS target_outbox_id
                   FROM agg_trades raw
                   JOIN ingestion_outbox work ON work.symbol=raw.symbol
                       AND work.aggregate_trade_id=raw.aggregate_trade_id
                       AND work.worker_name=$3
                   WHERE raw.symbol=$1 AND raw.trade_time>=$2
                     AND (work.status='COMPLETED' OR work.outbox_id=ANY($4::text[]))
                   ORDER BY raw.trade_time,raw.aggregate_trade_id""",
                symbol,
                since,
                worker_name,
                target_ids,
            )
        return [
            (
                Trade(
                    row["symbol"], row["price"], row["quantity"], row["trade_time"],
                    row["aggregate_trade_id"], row["buyer_is_maker"],
                ),
                row["target_outbox_id"],
            )
            for row in rows
        ]

    async def requarantine(self, outbox_id: str, error: BaseException, previous_error: str | None) -> bool:
        """Return an explicit recovery failure to quarantine while retaining history."""
        current = f"{type(error).__name__}: {error}"[:1_000]
        history = f"recovery_error={current}; previous_error={previous_error or '<none>'}"[:2_000]
        async with self.database.acquire() as connection:
            status = await connection.execute(
                """UPDATE ingestion_outbox SET status='QUARANTINED',last_error=$2,
                          lease_expires_at=NULL,updated_at=clock_timestamp()
                   WHERE outbox_id=$1 AND status='PROCESSING'""",
                outbox_id,
                history,
            )
        return status == "UPDATE 1"

    async def replay_input(self, item: OutboxItem, since: datetime) -> list[Trade]:
        """Chronological completed history plus one explicit recovery target."""
        async with self.database.acquire() as connection:
            rows = await connection.fetch(
                """SELECT raw.symbol,raw.aggregate_trade_id,raw.trade_time,raw.price,
                          raw.quantity,raw.buyer_is_maker
                   FROM agg_trades raw
                   JOIN ingestion_outbox work ON work.symbol=raw.symbol
                       AND work.aggregate_trade_id=raw.aggregate_trade_id
                       AND work.worker_name=$3
                   WHERE raw.symbol=$1 AND raw.trade_time>=$2
                     AND (work.status='COMPLETED' OR work.outbox_id=$4)
                   ORDER BY raw.trade_time,raw.aggregate_trade_id""",
                item.symbol,
                since,
                item.worker_name,
                item.outbox_id,
            )
        return [
            Trade(row["symbol"], row["price"], row["quantity"], row["trade_time"],
                  row["aggregate_trade_id"], row["buyer_is_maker"])
            for row in rows
        ]

    async def release_expired_leases(self, worker_name: str | None = None) -> int:
        """Make only objectively expired work retryable; never steals a live lease."""
        async with self.database.acquire() as connection:
            rows = await connection.fetch(
                """UPDATE ingestion_outbox SET status='RETRY',available_at=clock_timestamp(),
                   lease_expires_at=NULL,last_error=COALESCE(last_error,'worker lease expired'),updated_at=clock_timestamp()
                   WHERE status='PROCESSING' AND lease_expires_at<clock_timestamp()
                   AND ($1::text IS NULL OR worker_name=$1) RETURNING outbox_id""",
                worker_name,
            )
        return len(rows)

    async def acknowledge(self, outbox_id: str, output_hash: str) -> bool:
        if not SHA256.fullmatch(output_hash):
            raise ValueError("output_hash must be a lowercase SHA-256 digest")
        async with self.database.acquire() as connection:
            status = await connection.execute(
                """UPDATE ingestion_outbox SET status='COMPLETED',output_hash=$2,completed_at=clock_timestamp(),
                   lease_expires_at=NULL,last_error=NULL,updated_at=clock_timestamp()
                   WHERE outbox_id=$1 AND status='PROCESSING'""",
                outbox_id,
                output_hash,
            )
        return status == "UPDATE 1"

    async def acknowledge_with_followup(
        self,
        item: OutboxItem,
        output_hash: str,
        next_worker: str,
        *,
        worker_version: str = WORKER_VERSION,
    ) -> bool:
        """Atomically complete one stage and enqueue the next idempotent stage."""
        if next_worker not in PIPELINE_WORKERS:
            raise ValueError("next_worker is not an approved OBSERVE pipeline stage")
        if not SHA256.fullmatch(output_hash):
            raise ValueError("output_hash must be a lowercase SHA-256 digest")
        next_id, event_key = outbox_identity(item.symbol, item.aggregate_trade_id, next_worker)
        async with self.database.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", self._QUEUE_LOCK_KEY)
                current = await connection.fetchrow(
                    "SELECT * FROM ingestion_outbox WHERE outbox_id=$1 FOR UPDATE", item.outbox_id
                )
                if current is None or current["status"] != "PROCESSING":
                    return False
                status = await connection.execute(
                    """INSERT INTO ingestion_outbox(
                           outbox_id,worker_name,idempotency_key,source,market,symbol,data_type,
                           aggregate_trade_id,input_hash,worker_version,max_attempts)
                       VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                       ON CONFLICT(worker_name,idempotency_key) DO NOTHING""",
                    next_id,
                    next_worker,
                    event_key,
                    SOURCE,
                    MARKET,
                    item.symbol,
                    DATA_TYPE,
                    item.aggregate_trade_id,
                    output_hash,
                    worker_version,
                    self.max_attempts,
                )
                await connection.execute(
                    """UPDATE ingestion_outbox SET status='COMPLETED',output_hash=$2,
                       completed_at=clock_timestamp(),lease_expires_at=NULL,last_error=NULL,updated_at=clock_timestamp()
                       WHERE outbox_id=$1""",
                    item.outbox_id,
                    output_hash,
                )
                if status == "INSERT 0 1":
                    depth = int(
                        await connection.fetchval(
                            "SELECT count(*) FROM ingestion_outbox WHERE status=ANY($1::text[])",
                            list(ACTIVE_OUTBOX_STATUSES),
                        )
                    )
                    await self._gauge(connection, "queue_depth", depth)
                    await self._maximum(connection, "queue_high_water", depth)
        return True

    async def fail(self, outbox_id: str, error: BaseException, *, retry_delay_seconds: float = 1.0) -> str:
        message = f"{type(error).__name__}: {error}"[:2_000]
        async with self.database.acquire() as connection:
            row = await connection.fetchrow(
                """UPDATE ingestion_outbox SET
                       status=CASE WHEN attempts>=max_attempts THEN 'QUARANTINED' ELSE 'RETRY' END,
                       last_error=$2,available_at=clock_timestamp()+($3*interval '1 second'),
                       lease_expires_at=NULL,updated_at=clock_timestamp()
                   WHERE outbox_id=$1 AND status='PROCESSING' RETURNING status""",
                outbox_id,
                message,
                max(0.0, min(retry_delay_seconds, 3_600.0)),
            )
            await self._increment(connection, "worker_failure_total", metadata={"outbox_id": outbox_id})
        if row is None:
            raise DurableIngestionError("outbox item was not in PROCESSING state")
        return str(row["status"])

    async def defer(self, outbox_id: str, reason: str = "worker shutdown checkpoint") -> bool:
        async with self.database.acquire() as connection:
            status = await connection.execute(
                """UPDATE ingestion_outbox SET status='RETRY',attempts=GREATEST(attempts-1,0),
                   last_error=$2,available_at=clock_timestamp(),lease_expires_at=NULL,updated_at=clock_timestamp()
                   WHERE outbox_id=$1 AND status='PROCESSING'""",
                outbox_id,
                reason[:2_000],
            )
        return status == "UPDATE 1"

    async def record_gap(
        self,
        *,
        symbol: str,
        missing_from_id: int | None,
        missing_to_id: int | None,
        reason: str,
        details: Mapping[str, Any] | None = None,
    ) -> str:
        async with self.database.acquire() as connection:
            async with connection.transaction():
                gap_id = await self._record_gap_on_connection(
                    connection,
                    symbol=symbol,
                    missing_from_id=missing_from_id,
                    missing_to_id=missing_to_id,
                    reason=reason,
                    details=details,
                )
                await self._increment(connection, "gap_total")
        return gap_id

    async def set_gap_status(self, gap_id: str, status: str, *, error: str | None = None) -> None:
        if status not in {"OPEN", "CATCHING_UP", "RESOLVED", "IRREPARABLE"}:
            raise ValueError("invalid gap status")
        async with self.database.acquire() as connection:
            await connection.execute(
                """UPDATE ingestion_gap_incidents SET status=$2,last_error=$3,
                   resolved_at=CASE WHEN $2 IN ('RESOLVED','IRREPARABLE') THEN clock_timestamp() ELSE NULL END,
                   updated_at=clock_timestamp() WHERE gap_id=$1""",
                gap_id,
                status,
                error[:2_000] if error else None,
            )

    async def open_gaps(self, symbol: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1_000:
            raise ValueError("gap limit must be between 1 and 1000")
        async with self.database.acquire() as connection:
            rows = await connection.fetch(
                """SELECT * FROM ingestion_gap_incidents
                   WHERE symbol=$1 AND status IN ('OPEN','CATCHING_UP')
                   ORDER BY detected_at,gap_id LIMIT $2""",
                symbol,
                limit,
            )
        return [dict(row) for row in rows]

    async def resolve_gaps_through(self, symbol: str, aggregate_trade_id: int) -> int:
        async with self.database.acquire() as connection:
            async with connection.transaction():
                rows = await connection.fetch(
                    """UPDATE ingestion_gap_incidents SET status='RESOLVED',resolved_at=clock_timestamp(),updated_at=clock_timestamp()
                       WHERE symbol=$1 AND status IN ('OPEN','CATCHING_UP') AND missing_to_id<=$2
                       AND missing_from_id IS NOT NULL AND missing_to_id IS NOT NULL
                       AND (SELECT count(*) FROM agg_trades raw WHERE raw.symbol=ingestion_gap_incidents.symbol
                            AND raw.aggregate_trade_id BETWEEN ingestion_gap_incidents.missing_from_id
                            AND ingestion_gap_incidents.missing_to_id)=(missing_to_id-missing_from_id+1)
                       RETURNING gap_id""",
                    symbol,
                    aggregate_trade_id,
                )
                remaining = int(
                    await connection.fetchval(
                        "SELECT count(*) FROM ingestion_gap_incidents WHERE symbol=$1 AND status IN ('OPEN','CATCHING_UP')",
                        symbol,
                    )
                )
                cursor = await self._cursor_row(connection, symbol, lock=True)
                if cursor and remaining == 0:
                    await self._write_cursor(
                        connection,
                        symbol=symbol,
                        trade_id=cursor["last_aggregate_trade_id"],
                        event_time=cursor["last_event_time"],
                        persisted_at=cursor["last_persisted_at"],
                        recovery_state="NORMAL",
                    )
        return len(rows)

    async def set_recovery_state(self, symbol: str, recovery_state: str) -> None:
        if recovery_state not in {"NORMAL", "GAP_DETECTED", "CATCHING_UP", "DEGRADED"}:
            raise ValueError("invalid recovery state")
        async with self.database.acquire() as connection:
            async with connection.transaction():
                cursor = await self._cursor_row(connection, symbol, lock=True)
                if cursor is None:
                    raise DurableIngestionError("cannot update a missing cursor")
                await self._write_cursor(
                    connection,
                    symbol=symbol,
                    trade_id=cursor["last_aggregate_trade_id"],
                    event_time=cursor["last_event_time"],
                    persisted_at=cursor["last_persisted_at"],
                    recovery_state=recovery_state,
                )

    async def record_metric(
        self,
        name: str,
        value: float = 1,
        *,
        kind: str = "COUNTER",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        async with self.database.acquire() as connection:
            if kind == "COUNTER":
                await self._increment(connection, name, value, metadata)
            elif kind == "GAUGE":
                await self._gauge(connection, name, value, metadata)
            elif kind == "MAX":
                await self._maximum(connection, name, value)
            else:
                raise ValueError("kind must be COUNTER, GAUGE, or MAX")

    async def metrics_snapshot(self, symbol: str) -> dict[str, Any]:
        async with self.database.acquire() as connection:
            rows = await connection.fetch("SELECT metric_name,numeric_value,updated_at FROM ingestion_metrics")
            queue = await connection.fetchrow(
                """SELECT count(*) AS depth,
                   EXTRACT(EPOCH FROM (clock_timestamp()-min(created_at))) AS oldest_age,
                   count(*) FILTER (WHERE status='QUARANTINED') AS quarantined
                   FROM ingestion_outbox WHERE status=ANY($1::text[])""",
                list(ACTIVE_OUTBOX_STATUSES),
            )
            gaps = await connection.fetchrow(
                """SELECT count(*) FILTER (WHERE status IN ('OPEN','CATCHING_UP')) AS open_count,
                   max(COALESCE(missing_to_id-missing_from_id+1,0)) AS longest
                   FROM ingestion_gap_incidents WHERE symbol=$1""",
                symbol,
            )
            cursor = await self._cursor_row(connection, symbol)

        values = {str(row["metric_name"]): float(row["numeric_value"]) for row in rows}
        reject_reasons = {
            key.removeprefix("reject_reason:"): value
            for key, value in values.items()
            if key.startswith("reject_reason:")
        }
        cursor_age = None
        if cursor and cursor["last_persisted_at"]:
            cursor_age = max(0.0, (datetime.now(timezone.utc) - cursor["last_persisted_at"]).total_seconds())
        return {
            "received_total": values.get("received_total", 0.0),
            "raw_persisted_total": values.get("raw_persisted_total", 0.0),
            "duplicate_total": values.get("duplicate_total", 0.0),
            "rejected_total": values.get("rejected_total", 0.0),
            "reject_reason": reject_reasons,
            "out_of_order_total": values.get("out_of_order_total", 0.0),
            "late_total": values.get("late_total", 0.0),
            "parse_error_total": values.get("parse_error_total", 0.0),
            "persistence_error_total": values.get("persistence_error_total", 0.0),
            "queue_depth": int(queue["depth"] or 0),
            "queue_high_water": int(values.get("queue_high_water", 0.0)),
            "queue_oldest_age": float(queue["oldest_age"]) if queue["oldest_age"] is not None else None,
            "queue_quarantined": int(queue["quarantined"] or 0),
            "worker_latency": values.get("worker_latency"),
            "source_to_store_latency": values.get("source_to_store_latency"),
            "event_loop_lag": values.get("event_loop_lag"),
            "reconnect_total": values.get("reconnect_total", 0.0),
            "catchup_total": values.get("catchup_total", 0.0),
            "catchup_failure_total": values.get("catchup_failure_total", 0.0),
            "gap_total": values.get("gap_total", 0.0),
            "open_gap_total": int(gaps["open_count"] or 0),
            "longest_gap": int(gaps["longest"] or 0),
            "cursor_age": cursor_age,
            "restart_total": values.get("restart_total", 0.0),
            "recovery_state": cursor["recovery_state"] if cursor else "NO_CURSOR",
            "measured_at": datetime.now(timezone.utc).isoformat(),
        }


WorkerHandler = Callable[[OutboxItem, Trade], Awaitable[Any]]


class DurableOutboxWorker:
    """At-least-once worker with explicit idempotency identity and quarantine.

    A handler must use ``item.idempotency_key`` for any side effect. This makes a
    lease-expiry replay safe, including a crash after the handler but before ACK.
    """

    def __init__(
        self,
        store: DurableIngestionStore,
        worker_name: str,
        handler: WorkerHandler,
        *,
        batch_size: int = 100,
        lease_seconds: int = 60,
        next_worker: str | None = None,
        strict_order: bool = False,
    ) -> None:
        self.store = store
        self.worker_name = worker_name
        self.handler = handler
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self.next_worker = next_worker
        self.strict_order = strict_order

    async def run_once(self) -> dict[str, Any]:
        if hasattr(self.store, "claim_detailed"):
            claim = await self.store.claim_detailed(
                self.worker_name,
                limit=self.batch_size,
                lease_seconds=self.lease_seconds,
                strict_order=self.strict_order,
            )
            if claim.status == "TERMINAL_BLOCKED":
                assert claim.terminal_blocker is not None
                blocker = claim.terminal_blocker
                return {
                    "claimed": 0, "completed": 0, "retried": 0, "quarantined": 0,
                    "status": "TERMINAL_BLOCKED",
                    "terminal_blocker": {
                        "outbox_id": blocker.outbox_id,
                        "trade_id": blocker.aggregate_trade_id,
                        "status": blocker.status,
                        "last_error": blocker.last_error,
                        "attempts": blocker.attempts,
                        "max_attempts": blocker.max_attempts,
                        "created_at": blocker.created_at.isoformat(),
                        "updated_at": blocker.updated_at.isoformat(),
                        "quarantined_at": blocker.quarantined_at.isoformat(),
                        "strict_order_position": blocker.strict_order_position,
                    },
                }
            items = list(claim.items)
        else:
            items = await self.store.claim(
                self.worker_name,
                limit=self.batch_size,
                lease_seconds=self.lease_seconds,
                strict_order=self.strict_order,
            )
        completed = retried = quarantined = 0
        for item in items:
            started = datetime.now(timezone.utc)
            try:
                trade = await self.store.load_trade(item.symbol, item.aggregate_trade_id)
                result = await self.handler(item, trade)
                output_hash = _canonical_hash({"result": result, "worker": self.worker_name})
                acknowledged = (
                    await self.store.acknowledge_with_followup(item, output_hash, self.next_worker)
                    if self.next_worker is not None
                    else await self.store.acknowledge(item.outbox_id, output_hash)
                )
                if not acknowledged:
                    raise DurableIngestionError("worker lease was not acknowledgeable")
                completed += 1
                await self.store.record_metric(
                    "worker_latency",
                    (datetime.now(timezone.utc) - started).total_seconds(),
                    kind="GAUGE",
                    metadata={"worker_name": self.worker_name},
                )
            except asyncio.CancelledError:
                await asyncio.shield(self.store.defer(item.outbox_id))
                raise
            except Exception as error:
                state = await self.store.fail(item.outbox_id, error)
                if state == "QUARANTINED":
                    quarantined += 1
                else:
                    retried += 1
        return {
            "claimed": len(items),
            "completed": completed,
            "retried": retried,
            "quarantined": quarantined,
        }

    async def recover_one(self, outbox_id: str) -> dict[str, Any]:
        """Replay exactly one quarantined record; never resets attempts or skips peers."""
        item = await self.store.claim_quarantined(outbox_id, lease_seconds=self.lease_seconds)
        if item is None:
            return {"status": "NOT_QUARANTINED", "outbox_id": outbox_id}
        previous_error = item.last_error
        try:
            trade = await self.store.load_trade(item.symbol, item.aggregate_trade_id)
            result = await self.handler(item, trade)
            output_hash = _canonical_hash({"result": result, "worker": self.worker_name})
            if not await self.store.acknowledge(item.outbox_id, output_hash):
                raise DurableIngestionError("recovery lease was not acknowledgeable")
            return {"status": "COMPLETED", "outbox_id": outbox_id, "output_hash": output_hash}
        except asyncio.CancelledError:
            await asyncio.shield(self.store.requarantine(outbox_id, RuntimeError("recovery cancelled"), previous_error))
            raise
        except Exception as error:
            await self.store.requarantine(outbox_id, error, previous_error)
            return {"status": "QUARANTINED", "outbox_id": outbox_id, "error": f"{type(error).__name__}: {error}"}
