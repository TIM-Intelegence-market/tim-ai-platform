from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from src.data_ingestion.durable import DurableIngestionStore, cursor_hash


class IngestionControl:
    """Bounded runtime-control evidence for safe stop/start orchestration."""

    def __init__(self, store: DurableIngestionStore, symbol: str) -> None:
        self.store = store
        self.symbol = symbol

    async def status(self) -> dict[str, Any]:
        cursor = await self.store.get_cursor(self.symbol)
        metrics = await self.store.metrics_snapshot(self.symbol)
        async with self.store.database.acquire() as connection:
            statuses = await connection.fetch(
                "SELECT status,count(*) AS count FROM ingestion_outbox GROUP BY status ORDER BY status"
            )
            processing = await connection.fetchrow(
                """SELECT count(*) AS count,min(lease_expires_at) AS first_lease_expiry
                   FROM ingestion_outbox WHERE status='PROCESSING'"""
            )
        cursor_valid = False
        cursor_payload: dict[str, Any] | None = None
        if cursor is not None:
            expected = cursor_hash(
                symbol=cursor.symbol,
                last_aggregate_trade_id=cursor.last_aggregate_trade_id,
                last_event_time=cursor.last_event_time,
                last_trade_time=cursor.last_trade_time,
                last_persisted_at=cursor.last_persisted_at,
                recovery_state=cursor.recovery_state,
            )
            cursor_valid = expected == cursor.cursor_hash and cursor.cursor_version == 1
            cursor_payload = {
                "source": cursor.source,
                "market": cursor.market,
                "symbol": cursor.symbol,
                "data_type": cursor.data_type,
                "last_aggregate_trade_id": cursor.last_aggregate_trade_id,
                "last_event_time": cursor.last_event_time.isoformat() if cursor.last_event_time else None,
                "last_trade_time": cursor.last_trade_time.isoformat() if cursor.last_trade_time else None,
                "last_persisted_at": cursor.last_persisted_at.isoformat() if cursor.last_persisted_at else None,
                "cursor_version": cursor.cursor_version,
                "cursor_hash": cursor.cursor_hash,
                "recovery_state": cursor.recovery_state,
                "updated_at": cursor.updated_at.isoformat(),
            }
        return {
            "mode": "OBSERVE",
            "trading_actions": 0,
            "symbol": self.symbol,
            "cursor_valid": cursor_valid,
            "cursor": cursor_payload,
            "outbox_by_status": {str(row["status"]): int(row["count"]) for row in statuses},
            "processing": int(processing["count"] or 0),
            "first_lease_expiry": (
                processing["first_lease_expiry"].isoformat() if processing["first_lease_expiry"] else None
            ),
            "metrics": metrics,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def checkpoint(self, timeout_seconds: float = 30.0) -> dict[str, Any]:
        """Wait for in-flight work only; durable pending/retry work may remain."""
        timeout_seconds = max(0.0, min(timeout_seconds, 300.0))
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            await self.store.release_expired_leases()
            report = await self.status()
            if report["processing"] == 0:
                report["checkpoint_safe"] = bool(report["cursor_valid"])
                report["checkpoint_reason"] = (
                    "durable cursor valid; pending/retry work remains recoverable"
                    if report["checkpoint_safe"]
                    else "no valid durable cursor"
                )
                return report
            if asyncio.get_running_loop().time() >= deadline:
                report["checkpoint_safe"] = False
                report["checkpoint_reason"] = "processing leases did not drain before bounded timeout"
                return report
            await asyncio.sleep(min(0.25, max(0.0, deadline - asyncio.get_running_loop().time())))
