from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from src.data_ingestion.catchup import CatchUpCoordinator
from src.data_ingestion.durable import DurableIngestionError, DurableIngestionStore, IngestResult
from src.models.market_data import Trade

log = logging.getLogger(__name__)
# Inline catch-up before the first live trade gets this long. It must stay below
# BinanceTradeStream's recovery_timeout (300 s) and handler_timeout (120 s).
DEFAULT_INLINE_BUDGET_SECONDS = 60.0
OK_CATCHUP = {"COMPLETE", "NO_GAP"}


class DurableIngress:
    """Minimal WebSocket handler: validate, persist, cursor, outbox, metric."""

    def __init__(
        self,
        store: DurableIngestionStore,
        *,
        catchup: CatchUpCoordinator | None = None,
        defer_incomplete_gaps: bool = False,
        inline_budget_seconds: float = DEFAULT_INLINE_BUDGET_SECONDS,
    ) -> None:
        """``defer_incomplete_gaps``: a gap the inline catch-up cannot close within
        ``inline_budget_seconds`` stays OPEN in the gap ledger (exact IDs) and live
        trades are accepted again; the background gap filler closes it later
        (issue #82). Off, a live trade waits until the whole gap is closed."""
        if inline_budget_seconds <= 0:
            raise ValueError("inline_budget_seconds must be positive")
        self.store = store
        self.catchup = catchup
        self.defer_incomplete_gaps = defer_incomplete_gaps
        self.inline_budget_seconds = inline_budget_seconds
        self._deferred_from_live_id: int | None = None

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
                    if self._take_deferral(trade):
                        # The resume path already tried and handed this gap to the
                        # background filler: ingest_trade records it as an OPEN
                        # TRADE_ID_GAP with exact IDs in the same transaction.
                        return await self.store.ingest_trade(trade)
                    result = await self._inline_catch_up(trade, reason="SAME_CONNECTION_TRADE_ID_GAP")
                    if result is None or result.status not in OK_CATCHUP:
                        detail = result.reason if result is not None else f"no result within {self.inline_budget_seconds:.0f}s"
                        if self.defer_incomplete_gaps:
                            await self._defer(trade, detail)
                            return await self.store.ingest_trade(trade)
                        raise DurableIngestionError(
                            f"live trade blocked by incomplete catch-up: {detail}"
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
        self._deferred_from_live_id = None
        cursor = await self.store.get_cursor(first_live_trade.symbol)
        if await self.store.approved_live_cutover(
            first_live_trade.symbol,
            cursor.last_aggregate_trade_id if cursor else None,
            first_live_trade.trade_id,
        ):
            return
        result = await self._inline_catch_up(first_live_trade)
        if result is not None and result.status in OK_CATCHUP | {"NO_CURSOR"}:
            return
        detail = result.reason if result is not None else f"no result within {self.inline_budget_seconds:.0f}s"
        if not self.defer_incomplete_gaps:
            raise DurableIngestionError(f"live resume blocked by incomplete catch-up: {detail}")
        await self._defer(first_live_trade, detail)
        self._deferred_from_live_id = first_live_trade.trade_id

    async def _inline_catch_up(self, trade: Trade, *, reason: str | None = None):
        """Bounded catch-up of ``cursor + 1 .. trade - 1``; None when the budget ran out.

        Without deferral the old behaviour stays: no budget of its own, the
        stream's recovery_timeout decides. A cancelled catch-up leaves its gap
        OPEN (``CatchUpCoordinator``) and keeps what it already persisted.
        """
        assert self.catchup is not None and trade.trade_id is not None
        call = (self.catchup.recover_before(trade.symbol, trade.trade_id) if reason is None
                else self.catchup.recover_before(trade.symbol, trade.trade_id, reason=reason))
        if not self.defer_incomplete_gaps:
            return await call
        try:
            async with asyncio.timeout(self.inline_budget_seconds):
                return await call
        except TimeoutError:
            return None

    async def _defer(self, trade: Trade, detail: str | None) -> None:
        log.warning(
            "Gap before live trade %s handed to the background gap filler (%s); live ingestion continues",
            trade.trade_id, detail,
        )
        await self.store.record_metric(
            "gap_deferred_to_background_total",
            metadata={"next_live_trade_id": trade.trade_id, "reason": (detail or "")[:300]},
        )

    def _take_deferral(self, trade: Trade) -> bool:
        deferred = self._deferred_from_live_id
        if deferred is None or trade.trade_id is None or trade.trade_id < deferred:
            return False
        self._deferred_from_live_id = None
        return True

    async def on_stream_event(self, event: str, fields: Mapping[str, object]) -> None:
        if event == "PARSE_ERROR":
            await self.store.record_metric("parse_error_total", metadata=dict(fields))
        elif event == "DISCONNECTED":
            await self.store.record_metric("reconnect_total", metadata=dict(fields))
        elif event == "CONNECTED":
            await self.store.record_metric("recovery_state_event_total", metadata={"event": event, **fields})
        elif event == "RECOVERY_COMPLETE":
            await self.store.record_metric("recovery_complete_total", metadata=dict(fields))
