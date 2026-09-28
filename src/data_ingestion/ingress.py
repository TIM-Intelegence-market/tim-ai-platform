from __future__ import annotations

from collections.abc import Mapping
from src.data_ingestion.catchup import CatchUpCoordinator
from src.data_ingestion.durable import DurableIngestionError, DurableIngestionStore, IngestResult
from src.models.market_data import Trade


class DurableIngress:
    """Minimal WebSocket handler: validate, persist, cursor, outbox, metric."""

    def __init__(
        self,
        store: DurableIngestionStore,
        *,
        catchup: CatchUpCoordinator | None = None,
    ) -> None:
        self.store = store
        self.catchup = catchup

    async def __call__(self, trade: Trade) -> IngestResult:
        try:
            if trade.trade_id is not None:
                cursor = await self.store.get_cursor(trade.symbol)
                last_trade_id = cursor.last_aggregate_trade_id if cursor is not None else None
                if last_trade_id is not None and trade.trade_id > last_trade_id + 1:
                    if await self.store.approved_live_cutover(trade.symbol, last_trade_id, trade.trade_id):
                        # The receipt is immutable and the old outbox is deferred;
                        # ingest_trade records the explicit discontinuity before it
                        # advances the live cursor.
                        return await self.store.ingest_trade(trade)
                    if self.catchup is None:
                        raise DurableIngestionError(
                            "live trade gap is fail-closed until public catch-up is configured"
                        )
                    result = await self.catchup.recover_before(
                        trade.symbol,
                        trade.trade_id,
                        reason="SAME_CONNECTION_TRADE_ID_GAP",
                    )
                    if result.status not in {"COMPLETE", "NO_GAP"}:
                        raise DurableIngestionError(
                            f"live trade blocked by incomplete catch-up: {result.reason}"
                        )
                    cursor = await self.store.get_cursor(trade.symbol)
                    recovered_through = (
                        cursor.last_aggregate_trade_id if cursor is not None else None
                    )
                    if recovered_through is None or recovered_through < trade.trade_id - 1:
                        raise DurableIngestionError(
                            "live trade blocked because catch-up did not advance the durable cursor"
                        )
            return await self.store.ingest_trade(trade)
        except ValueError as error:
            await self.store.record_metric(
                "rejected_total", metadata={"error_type": type(error).__name__}
            )
            await self.store.record_metric("reject_reason:VALIDATION")
            raise
        except Exception as error:
            await self.store.record_metric(
                "persistence_error_total",
                metadata={"error_type": type(error).__name__},
            )
            raise

    async def recover_before_resume(self, first_live_trade: Trade) -> None:
        if self.catchup is None or first_live_trade.trade_id is None:
            raise DurableIngestionError("live resume is fail-closed until public catch-up is configured")
        cursor = await self.store.get_cursor(first_live_trade.symbol)
        if await self.store.approved_live_cutover(
            first_live_trade.symbol,
            cursor.last_aggregate_trade_id if cursor else None,
            first_live_trade.trade_id,
        ):
            return
        result = await self.catchup.recover_before(first_live_trade.symbol, first_live_trade.trade_id)
        if result.status not in {"COMPLETE", "NO_GAP", "NO_CURSOR"}:
            raise DurableIngestionError(f"live resume blocked by incomplete catch-up: {result.reason}")

    async def on_stream_event(self, event: str, fields: Mapping[str, object]) -> None:
        if event == "PARSE_ERROR":
            await self.store.record_metric("parse_error_total", metadata=dict(fields))
        elif event == "DISCONNECTED":
            await self.store.record_metric("reconnect_total", metadata=dict(fields))
        elif event == "CONNECTED":
            await self.store.record_metric("recovery_state_event_total", metadata={"event": event, **fields})
        elif event == "RECOVERY_COMPLETE":
            await self.store.record_metric("recovery_complete_total", metadata=dict(fields))
