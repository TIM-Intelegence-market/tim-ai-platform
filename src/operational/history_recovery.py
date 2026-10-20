"""Bounded historical repair without advancing the live cursor or queue."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

from src.data_ingestion.durable import (
    DurableIngestionStore, CursorConflictError, FIRST_WORKER, SOURCE, MARKET, DATA_TYPE, outbox_identity,
)
from src.database.repository import AGG_TRADE_SOURCE, _validate_agg_trade_for_persistence, agg_trade_hash
from src.models.market_data import Trade, Candle


async def persist_historical_batch(store: DurableIngestionStore, trades: list[Trade]) -> dict[str, Any]:
    """Atomically persist <=1000 old trades plus DEFERRED work, never live progress."""
    if not trades or len(trades) > 1000:
        raise ValueError("historical batch must contain 1..1000 trades")
    symbol = trades[0].symbol
    for trade in trades:
        _validate_agg_trade_for_persistence(trade)
        if trade.symbol != symbol:
            raise ValueError("historical batch must contain one symbol")
    ids = [trade.trade_id for trade in trades]
    if any(right <= left for left, right in zip(ids, ids[1:])):
        raise ValueError("historical IDs must be strictly increasing")
    async with store.database.acquire() as connection:
        async with connection.transaction():
            await connection.execute("SET LOCAL lock_timeout='2s'")
            await connection.execute("SELECT pg_advisory_xact_lock($1)", store._QUEUE_LOCK_KEY)
            cursor = await store._cursor_row(connection, symbol, lock=True)
            if not cursor or cursor["last_aggregate_trade_id"] is None or ids[-1] >= cursor["last_aggregate_trade_id"]:
                raise ValueError("historical batch must stay strictly below the trusted live cursor")
            if cursor["last_event_time"] is None or any(trade.event_time > cursor["last_event_time"] for trade in trades):
                raise ValueError("historical timestamps must not exceed the live cursor event time")
            inserted = await connection.fetch(
                """INSERT INTO agg_trades(symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker,source)
                   SELECT $1,t.id,t.ts,t.price,t.quantity,t.maker,$7
                   FROM unnest($2::bigint[],$3::timestamptz[],$4::float8[],$5::float8[],$6::boolean[])
                     AS t(id,ts,price,quantity,maker)
                   ON CONFLICT(symbol,aggregate_trade_id) DO NOTHING RETURNING aggregate_trade_id""",
                symbol, ids, [t.event_time for t in trades], [t.price for t in trades],
                [t.quantity for t in trades], [t.buyer_is_maker for t in trades], AGG_TRADE_SOURCE,
            )
            rows = await connection.fetch(
                """SELECT symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker,source
                   FROM agg_trades WHERE symbol=$1 AND aggregate_trade_id=ANY($2::bigint[])""", symbol, ids,
            )
            expected = {trade.trade_id: agg_trade_hash(trade) for trade in trades}
            if len(rows) != len(trades):
                raise CursorConflictError("historical batch failed raw population verification")
            for row in rows:
                stored = Trade(row["symbol"], row["price"], row["quantity"], row["trade_time"],
                               row["aggregate_trade_id"], row["buyer_is_maker"])
                if row["source"] != AGG_TRADE_SOURCE or agg_trade_hash(stored) != expected[stored.trade_id]:
                    raise CursorConflictError("historical batch conflicts with immutable raw payload")
            identities = [outbox_identity(symbol, trade_id, FIRST_WORKER) for trade_id in ids]
            deferred = await connection.fetch(
                """INSERT INTO ingestion_outbox(outbox_id,worker_name,idempotency_key,source,market,symbol,data_type,
                       aggregate_trade_id,input_hash,worker_version,max_attempts,status)
                   SELECT t.outbox_id,$1,t.event_key,$2,$3,$4,$5,t.id,t.hash,$6,$7,'DEFERRED'
                   FROM unnest($8::text[],$9::text[],$10::bigint[],$11::text[])
                     AS t(outbox_id,event_key,id,hash)
                   ON CONFLICT(worker_name,idempotency_key) DO NOTHING RETURNING outbox_id""",
                FIRST_WORKER, SOURCE, MARKET, symbol, DATA_TYPE, store.worker_version, store.max_attempts,
                [identity[0] for identity in identities], [identity[1] for identity in identities],
                ids, [expected[trade_id] for trade_id in ids],
            )
            await store._increment(connection, "historical_recovery_raw_total", len(inserted))
            await store._increment(connection, "historical_recovery_deferred_total", len(deferred))
    return {"inserted_ids": [row["aggregate_trade_id"] for row in inserted],
            "persisted": len(inserted), "duplicates": len(trades)-len(inserted), "deferred": len(deferred)}


async def rebuild_verified_minute(connection: Any, symbol: str, minute: datetime, *, now: datetime,
                                  max_trade_ids: int = 100_000) -> dict[str, Any]:
    """Rebuild only when adjacent raw events prove every ID across both boundaries."""
    if minute.tzinfo is None or now.tzinfo is None or minute.second or minute.microsecond:
        raise ValueError("minute must be aligned and timestamps must be timezone-aware")
    minute = minute.astimezone(timezone.utc)
    end = minute + timedelta(minutes=1)
    if end > now.astimezone(timezone.utc) - timedelta(minutes=2):
        return {"status": "DEFERRED", "reason": "minute is not settled"}
    async with connection.transaction(isolation="repeatable_read"):
        before = await connection.fetchrow(
            """SELECT aggregate_trade_id FROM agg_trades WHERE symbol=$1 AND trade_time < $2
               ORDER BY trade_time DESC,aggregate_trade_id DESC LIMIT 1""", symbol, minute,
        )
        after = await connection.fetchrow(
            """SELECT aggregate_trade_id FROM agg_trades WHERE symbol=$1 AND trade_time >= $2
               ORDER BY trade_time,aggregate_trade_id LIMIT 1""", symbol, end,
        )
        if before is None or after is None:
            return {"status": "WAIT_RAW", "reason": "raw boundary event missing"}
        first_id, last_id = before["aggregate_trade_id"]+1, after["aggregate_trade_id"]-1
        expected = last_id-first_id+1
        if not 1 <= expected <= max_trade_ids:
            return {"status": "WAIT_RAW", "reason": "raw range empty, inconsistent or above minute budget"}
        rows = await connection.fetch(
            """SELECT aggregate_trade_id,trade_time,price,quantity FROM agg_trades
               WHERE symbol=$1 AND aggregate_trade_id BETWEEN $2 AND $3
               ORDER BY aggregate_trade_id LIMIT $4""", symbol, first_id, last_id, max_trade_ids+1,
        )
        if len(rows) != expected or any(
            row["aggregate_trade_id"] != first_id+offset or not minute <= row["trade_time"] < end
            for offset, row in enumerate(rows)
        ):
            return {"status": "WAIT_RAW", "reason": "raw ID range incomplete or timestamps inconsistent"}
        if any(not math.isfinite(float(row[key])) or row[key] <= 0 for row in rows for key in ("price", "quantity")):
            return {"status": "WAIT_RAW", "reason": "invalid raw price or quantity"}
        ordered = sorted(rows, key=lambda row: (row["trade_time"], row["aggregate_trade_id"]))
        candle = Candle(symbol, "1m", minute, end, ordered[0]["price"], max(row["price"] for row in rows),
                        min(row["price"] for row in rows), ordered[-1]["price"],
                        math.fsum(row["quantity"] for row in rows), len(rows))
        if not math.isfinite(candle.volume):
            return {"status": "WAIT_RAW", "reason": "non-finite volume"}
        await connection.execute(
            """INSERT INTO candles(symbol,timeframe,open_time,close_time,open,high,low,close,volume,trade_count,closed)
               VALUES($1,'1m',$2,$3,$4,$5,$6,$7,$8,$9,true)
               ON CONFLICT(symbol,timeframe,open_time) DO UPDATE SET close_time=EXCLUDED.close_time,
                 open=EXCLUDED.open,high=EXCLUDED.high,low=EXCLUDED.low,close=EXCLUDED.close,
                 volume=EXCLUDED.volume,trade_count=EXCLUDED.trade_count,closed=true""",
            symbol, minute, end, candle.open, candle.high, candle.low, candle.close, candle.volume, candle.trade_count,
        )
    return {"status": "REBUILT", "trade_count": len(rows), "first_id": first_id, "last_id": last_id}
