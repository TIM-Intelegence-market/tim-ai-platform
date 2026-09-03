from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from config.settings import settings
from src.data_ingestion.aggregator import CandleAggregator, bucket_start, timeframe_seconds
from src.data_ingestion.durable import (
    DurableIngestionError,
    DurableIngestionStore,
    DurableOutboxWorker,
    OutboxItem,
    _canonical_hash,
)
from src.database.connection import Database
from src.database.repository import MarketRepository
from src.models.market_data import Candle, Trade


class PersistedTradeReplayService:
    """Deterministically rebuild candles from durable chronological input."""

    def __init__(self, store: DurableIngestionStore, repository: MarketRepository) -> None:
        self.store = store
        self.repository = repository
        self.last_metrics: dict[str, float | int] = {}

    async def replay(self, item: OutboxItem, trade: Trade) -> list[dict]:
        replay_started = time.perf_counter()
        replay_start = min(bucket_start(trade.event_time, timeframe) for timeframe in settings.timeframes)
        database_started = time.perf_counter()
        trades = await self.store.replay_input(item, replay_start)
        database_read_seconds = time.perf_counter() - database_started
        aggregator = CandleAggregator(settings.timeframes)
        completed: list[dict] = []
        target_seen = False
        write_seconds = 0.0
        for persisted in trades:
            target_seen = target_seen or persisted.trade_id == trade.trade_id
            for candle in aggregator.add_trade(persisted):
                write_started = time.perf_counter()
                await self.repository.upsert_candle(candle)
                write_seconds += time.perf_counter() - write_started
                completed.append(
                    {
                        "symbol": candle.symbol,
                        "timeframe": candle.timeframe,
                        "open_time": candle.open_time.isoformat(),
                        "close_time": candle.close_time.isoformat(),
                    }
                )
        if not target_seen:
            raise RuntimeError("replay target missing from durable raw input")
        replay_total_seconds = time.perf_counter() - replay_started
        self.last_metrics = {
            "replay_trade_count": len(trades),
            "candle_replay_count": len(completed),
            "database_read_seconds": database_read_seconds,
            "write_seconds": write_seconds,
            "replay_compute_seconds": max(0.0, replay_total_seconds - database_read_seconds - write_seconds),
            "replay_total_seconds": replay_total_seconds,
        }
        return completed

    async def prepare_batch(self, items: list[OutboxItem]) -> "PreparedBatchReplay":
        """Read and index shared history once; this method never writes."""
        if not items:
            raise ValueError("batch must contain at least one target")
        read_started = time.perf_counter()
        if hasattr(self.store, "load_batch_target_trades"):
            target_trades = await self.store.load_batch_target_trades(items)
        else:  # Compatibility for narrow store adapters used by offline validators.
            target_trades = [
                await self.store.load_trade(item.symbol, item.aggregate_trade_id) for item in items
            ]
        earliest = min(
            bucket_start(trade.event_time, timeframe)
            for trade in target_trades
            for timeframe in settings.timeframes
        )
        rows = await self.store.batch_replay_input(items, earliest)
        database_read_seconds = time.perf_counter() - read_started
        prepared = PreparedBatchReplay(
            self.repository,
            items,
            target_trades,
            rows,
            database_read_seconds=database_read_seconds,
        )
        self.last_metrics = prepared.metrics
        return prepared


@dataclass(frozen=True, slots=True)
class _FirstTrade:
    event_time: datetime
    trade_id: int


class PreparedBatchReplay:
    """Incremental exact replay over one immutable historical reconstruction."""

    def __init__(
        self,
        repository: MarketRepository,
        items: list[OutboxItem],
        target_trades: list[Trade],
        rows: list[tuple[Trade, str | None]],
        *,
        database_read_seconds: float,
    ) -> None:
        self.repository = repository
        self.items = items
        self.target_trades = target_trades
        self._next_index = 0
        self._timeframes = tuple(settings.timeframes)
        self._first: dict[str, dict[Any, _FirstTrade]] = {value: {} for value in self._timeframes}
        self._target_bucket_trades: dict[tuple[str, Any], list[Trade]] = {}
        self._base_bucket_trades: dict[tuple[str, Any], list[Trade]] = {}
        self._target_by_id = {item.outbox_id: trade for item, trade in zip(items, target_trades)}
        touched = {
            (timeframe, bucket_start(trade.event_time, timeframe))
            for trade in target_trades
            for timeframe in self._timeframes
        }
        index_started = time.perf_counter()
        target_rows_seen: set[str] = set()
        base_count = 0
        for trade, target_outbox_id in rows:
            if target_outbox_id is not None:
                target_rows_seen.add(target_outbox_id)
                continue
            base_count += 1
            assert trade.trade_id is not None
            for timeframe in self._timeframes:
                start = bucket_start(trade.event_time, timeframe)
                current = self._first[timeframe].get(start)
                order = _FirstTrade(trade.event_time, trade.trade_id)
                if current is None or (order.event_time, order.trade_id) < (current.event_time, current.trade_id):
                    self._first[timeframe][start] = order
                if (timeframe, start) in touched:
                    self._base_bucket_trades.setdefault((timeframe, start), []).append(trade)
        missing = set(self._target_by_id) - target_rows_seen
        if missing:
            raise RuntimeError(f"batch replay targets missing from durable raw input: {sorted(missing)}")
        for values in self._base_bucket_trades.values():
            values.sort(key=lambda value: (value.event_time, value.trade_id or -1))
        self.metrics: dict[str, float | int] = {
            "historical_reconstruction_count": 1,
            "replay_trade_count": base_count + len(target_trades),
            "batch_target_count": len(items),
            "database_read_seconds": database_read_seconds,
            "replay_compute_seconds": time.perf_counter() - index_started,
            "write_seconds": 0.0,
            "candle_replay_count": 0,
            "candle_write_count": 0,
        }

    async def replay_one(self, item: OutboxItem) -> dict[str, Any]:
        if self._next_index >= len(self.items) or self.items[self._next_index].outbox_id != item.outbox_id:
            raise DurableIngestionError("batch replay order changed")
        trade = self.target_trades[self._next_index]
        compute_started = time.perf_counter()
        assert trade.trade_id is not None
        affected: list[tuple[str, Any]] = []
        for timeframe in self._timeframes:
            start = bucket_start(trade.event_time, timeframe)
            affected.append((timeframe, start))
            order = _FirstTrade(trade.event_time, trade.trade_id)
            current = self._first[timeframe].get(start)
            if current is None or (order.event_time, order.trade_id) < (current.event_time, current.trade_id):
                self._first[timeframe][start] = order
            self._target_bucket_trades.setdefault((timeframe, start), []).append(trade)
        completed = self._completed_summary(trade)
        candles = [self._build_candle(trade.symbol, timeframe, start) for timeframe, start in affected]
        candles = [candle for candle in candles if candle is not None]
        self.metrics["replay_compute_seconds"] = float(self.metrics["replay_compute_seconds"]) + (
            time.perf_counter() - compute_started
        )
        write_started = time.perf_counter()
        for candle in candles:
            await self.repository.upsert_candle(candle)
        write_seconds = time.perf_counter() - write_started
        self.metrics["write_seconds"] = float(self.metrics["write_seconds"]) + write_seconds
        self.metrics["candle_replay_count"] = int(self.metrics["candle_replay_count"]) + len(completed)
        self.metrics["candle_write_count"] = int(self.metrics["candle_write_count"]) + len(candles)
        self._next_index += 1
        return {
            "mode": "OBSERVE",
            "idempotency_key": item.idempotency_key,
            "aggregate_trade_id": trade.trade_id,
            "completed_candles": completed,
            "trading_actions": 0,
        }

    def _completed_summary(self, target: Trade) -> list[dict[str, Any]]:
        replay_start = min(bucket_start(target.event_time, value) for value in self._timeframes)
        events: list[tuple[Any, int, int, dict[str, Any]]] = []
        for timeframe_index, timeframe in enumerate(self._timeframes):
            starts = sorted(start for start in self._first[timeframe] if start >= replay_start)
            for previous, following in zip(starts, starts[1:]):
                trigger = self._first[timeframe][following]
                events.append(
                    (
                        trigger.event_time,
                        trigger.trade_id,
                        timeframe_index,
                        {
                            "symbol": target.symbol,
                            "timeframe": timeframe,
                            "open_time": previous.isoformat(),
                            "close_time": (previous + timedelta(seconds=timeframe_seconds(timeframe))).isoformat(),
                        },
                    )
                )
        events.sort(key=lambda value: (value[0], value[1], value[2]))
        return [value[3] for value in events]

    def _build_candle(self, symbol: str, timeframe: str, start: Any) -> Candle | None:
        if not any(candidate > start for candidate in self._first[timeframe]):
            return None
        trades = [
            *self._base_bucket_trades.get((timeframe, start), ()),
            *self._target_bucket_trades.get((timeframe, start), ()),
        ]
        trades.sort(key=lambda value: (value.event_time, value.trade_id or -1))
        if not trades:
            raise RuntimeError("affected candle bucket has no replay trades")
        # Match CandleAggregator's deliberately sequential floating-point addition.
        # Python 3.12+ sum() uses compensated summation and can differ by a few ULPs.
        volume = trades[0].quantity
        for value in trades[1:]:
            volume += value.quantity
        return Candle(
            symbol=symbol,
            timeframe=timeframe,
            open_time=start,
            close_time=start + timedelta(seconds=timeframe_seconds(timeframe)),
            open=trades[0].price,
            high=max(value.price for value in trades),
            low=min(value.price for value in trades),
            close=trades[-1].price,
            volume=volume,
            trade_count=len(trades),
            closed=True,
        )


class TIMRecoveryContext:
    """Headless, exact-ID maintenance context with no runtime services."""

    def __init__(self) -> None:
        self.database = Database(settings.database_url)
        self.repository = MarketRepository(self.database)
        self.store = DurableIngestionStore(self.database)
        self.replay = PersistedTradeReplayService(self.store, self.repository)
        self.worker = DurableOutboxWorker(
            self.store,
            "CANDLE_V1",
            self._replay_one,
            batch_size=1,
            lease_seconds=300,
            strict_order=True,
        )
        self.runtime_guard: Callable[[], None] | None = None

    async def connect(self) -> None:
        await self.database.connect()

    async def close(self) -> None:
        await self.database.close()

    async def inspect(self, outbox_id: str) -> dict:
        return await self.store.inspect_recovery_target(outbox_id)

    async def recover(self, outbox_id: str) -> dict:
        started = time.perf_counter()
        result = await self.worker.recover_one(outbox_id)
        return {
            **result,
            "timing": {
                **self.replay.last_metrics,
                "recovery_total_seconds": time.perf_counter() - started,
            },
        }

    async def inspect_batch(self, limit: int) -> dict[str, Any]:
        items = await self.store.list_quarantined_batch(self.worker.worker_name, limit)
        target_trades = (
            await self.store.load_batch_target_trades(items)
            if items and hasattr(self.store, "load_batch_target_trades")
            else []
        )
        counts: dict[str, int] = {}
        for item in items:
            counts[item.status] = counts.get(item.status, 0) + 1
        return {
            "status": "PREVIEW",
            "requested_limit": limit,
            "count": len(items),
            "first_trade_id": items[0].aggregate_trade_id if items else None,
            "last_trade_id": items[-1].aggregate_trade_id if items else None,
            "estimated_replay_start": (
                min(
                    bucket_start(trade.event_time, timeframe)
                    for trade in target_trades
                    for timeframe in settings.timeframes
                ).isoformat()
                if target_trades
                else None
            ),
            "first_event_time": target_trades[0].event_time.isoformat() if target_trades else None,
            "last_event_time": target_trades[-1].event_time.isoformat() if target_trades else None,
            "status_counts": counts,
            "records": [
                {
                    "outbox_id": item.outbox_id,
                    "trade_id": item.aggregate_trade_id,
                    "status": item.status,
                    "attempts": item.attempts,
                    "max_attempts": item.max_attempts,
                    "last_error": item.last_error,
                }
                for item in items
            ],
        }

    async def recover_batch(self, limit: int) -> dict[str, Any]:
        """Recover a bounded strict-order prefix with an independent ACK per record."""
        batch_started = time.perf_counter()
        self._check_runtime_guard()
        items = await self.store.list_quarantined_batch(self.worker.worker_name, limit)
        if not items:
            return {"status": "EMPTY", "requested": limit, "completed": 0, "records": []}
        target_ids = [item.outbox_id for item in items]
        guard_supported = hasattr(self.store, "recovery_guard_snapshot")
        record_guard_supported = hasattr(self.store, "recovery_record_guard_snapshot")
        before = (
            await self.store.recovery_guard_snapshot(
                self.worker.worker_name, items[0].symbol, target_ids
            )
            if guard_supported
            else None
        )
        if before is not None:
            guard_error = self._initial_guard_error(before, items)
            if guard_error:
                return {
                    "status": "FAIL",
                    "requested": limit,
                    "selected": len(items),
                    "completed": 0,
                    "records": [],
                    "safety_stop": guard_error,
                }
        prepared = await self.replay.prepare_batch(items)
        self._check_runtime_guard()
        if before is not None:
            after_prepare = await self.store.recovery_guard_snapshot(
                self.worker.worker_name, items[0].symbol, target_ids
            )
            if after_prepare != before:
                return {
                    "status": "FAIL",
                    "requested": limit,
                    "selected": len(items),
                    "completed": 0,
                    "records": [],
                    "safety_stop": "database invariants changed during batch preparation",
                }
        records: list[dict[str, Any]] = []
        safety_stop: str | None = None
        previous_snapshot = before
        for index, expected in enumerate(items, start=1):
            self._check_runtime_guard()
            record_started = time.perf_counter()
            claimed = await self.store.claim_quarantined(
                expected.outbox_id,
                lease_seconds=self.worker.lease_seconds,
            )
            if claimed is None:
                records.append({"index": index, "outbox_id": expected.outbox_id, "status": "NOT_QUARANTINED"})
                break
            previous_error = claimed.last_error
            try:
                result = await prepared.replay_one(claimed)
                output_hash = _canonical_hash({"result": result, "worker": self.worker.worker_name})
                if not await self.store.acknowledge(claimed.outbox_id, output_hash):
                    raise DurableIngestionError("recovery lease was not acknowledgeable")
                record = {
                    "index": index,
                    "outbox_id": claimed.outbox_id,
                    "trade_id": claimed.aggregate_trade_id,
                    "status": "COMPLETED",
                    "attempts": claimed.attempts,
                    "output_hash": output_hash,
                    "duration_seconds": time.perf_counter() - record_started,
                }
                records.append(record)
                if previous_snapshot is not None:
                    if record_guard_supported:
                        immediate = items[index:index + 1]
                        current_snapshot = await self.store.recovery_record_guard_snapshot(
                            self.worker.worker_name,
                            items[0].symbol,
                            [expected.outbox_id, *(item.outbox_id for item in immediate)],
                        )
                        safety_stop = self._record_guard_error(before, current_snapshot, expected, immediate)
                    else:
                        current_snapshot = await self.store.recovery_guard_snapshot(
                            self.worker.worker_name, items[0].symbol, target_ids
                        )
                        safety_stop = self._transition_guard_error(
                            previous_snapshot, current_snapshot, expected, items[index:]
                        )
                        previous_snapshot = current_snapshot
                    if safety_stop:
                        record["safety_stop"] = safety_stop
                        break
            except asyncio.CancelledError:
                await asyncio.shield(
                    self.store.requarantine(
                        claimed.outbox_id, RuntimeError("batch recovery cancelled"), previous_error
                    )
                )
                raise
            except Exception as error:
                await self.store.requarantine(claimed.outbox_id, error, previous_error)
                records.append(
                    {
                        "index": index,
                        "outbox_id": claimed.outbox_id,
                        "trade_id": claimed.aggregate_trade_id,
                        "status": "QUARANTINED",
                        "attempts": claimed.attempts,
                        "error": f"{type(error).__name__}: {error}",
                        "duration_seconds": time.perf_counter() - record_started,
                    }
                )
                break
            try:
                self._check_runtime_guard()
            except Exception as error:
                safety_stop = f"runtime guard failed after commit: {type(error).__name__}: {error}"
                records[-1]["safety_stop"] = safety_stop
                break
        completed = sum(record["status"] == "COMPLETED" for record in records)
        if before is not None and record_guard_supported and safety_stop is None:
            final_snapshot = await self.store.recovery_guard_snapshot(
                self.worker.worker_name, items[0].symbol, target_ids
            )
            safety_stop = self._batch_transition_guard_error(before, final_snapshot, items[:completed], items[completed:])
            if safety_stop and records:
                records[-1]["safety_stop"] = safety_stop
        status = (
            "COMPLETED"
            if completed == len(items) and safety_stop is None
            else ("PARTIAL" if completed else "FAIL")
        )
        return {
            "status": status,
            "requested": limit,
            "selected": len(items),
            "completed": completed,
            "records": records,
            "safety_stop": safety_stop,
            "timing": {
                **prepared.metrics,
                "recovery_total_seconds": time.perf_counter() - batch_started,
            },
        }

    def _check_runtime_guard(self) -> None:
        guard = getattr(self, "runtime_guard", None)
        if guard is not None:
            guard()

    @staticmethod
    def _initial_guard_error(snapshot: dict[str, Any], items: list[OutboxItem]) -> str | None:
        if snapshot["processing"] != 0:
            return "PROCESSING must be zero before batch recovery"
        for item in items:
            state = snapshot["targets"].get(item.outbox_id)
            if state != {"status": "QUARANTINED", "attempts": item.attempts}:
                return f"target changed before recovery: {item.outbox_id}"
        return None

    @staticmethod
    def _transition_guard_error(
        before: dict[str, Any],
        after: dict[str, Any],
        completed: OutboxItem,
        remaining: list[OutboxItem],
    ) -> str | None:
        if after["processing"] != 0:
            return "orphaned PROCESSING lease detected"
        if after["queue_depth"] != before["queue_depth"] - 1:
            return "queue depth did not decrease by exactly one"
        if after["cursor_hash"] != before["cursor_hash"] or after["recovery_state"] != before["recovery_state"]:
            return "cursor changed during quarantine recovery"
        if after["open_gaps"] != before["open_gaps"]:
            return "open gap count changed during quarantine recovery"
        expected_counts = dict(before["status_counts"])
        expected_counts["QUARANTINED"] = expected_counts.get("QUARANTINED", 0) - 1
        expected_counts["COMPLETED"] = expected_counts.get("COMPLETED", 0) + 1
        if after["status_counts"] != expected_counts:
            return "unexpected outbox status change detected"
        if after["foreign_status_updated_at"] != before["foreign_status_updated_at"]:
            return "foreign outbox record changed during quarantine recovery"
        state = after["targets"].get(completed.outbox_id)
        if state != {"status": "COMPLETED", "attempts": completed.attempts}:
            return "completed target status or attempts changed unexpectedly"
        for item in remaining:
            state = after["targets"].get(item.outbox_id)
            if state != {"status": "QUARANTINED", "attempts": item.attempts}:
                return f"later target changed unexpectedly: {item.outbox_id}"
        return None

    @staticmethod
    def _record_guard_error(
        baseline: dict[str, Any], current: dict[str, Any], completed: OutboxItem, remaining: list[OutboxItem]
    ) -> str | None:
        if current["processing"] != 0:
            return "orphaned PROCESSING lease detected"
        if current["cursor_hash"] != baseline["cursor_hash"] or current["recovery_state"] != baseline["recovery_state"]:
            return "cursor changed during quarantine recovery"
        if current["open_gaps"] != baseline["open_gaps"]:
            return "open gap count changed during quarantine recovery"
        if current["targets"].get(completed.outbox_id) != {"status": "COMPLETED", "attempts": completed.attempts}:
            return "completed target status or attempts changed unexpectedly"
        for item in remaining:
            if current["targets"].get(item.outbox_id) != {"status": "QUARANTINED", "attempts": item.attempts}:
                return f"later target changed unexpectedly: {item.outbox_id}"
        return None

    @staticmethod
    def _batch_transition_guard_error(
        before: dict[str, Any], after: dict[str, Any], completed: list[OutboxItem], remaining: list[OutboxItem]
    ) -> str | None:
        count = len(completed)
        if after["processing"] != 0:
            return "orphaned PROCESSING lease detected"
        if after["queue_depth"] != before["queue_depth"] - count:
            return "queue depth did not decrease by completed batch size"
        if after["cursor_hash"] != before["cursor_hash"] or after["recovery_state"] != before["recovery_state"]:
            return "cursor changed during quarantine recovery"
        if after["open_gaps"] != before["open_gaps"]:
            return "open gap count changed during quarantine recovery"
        expected = dict(before["status_counts"])
        expected["QUARANTINED"] -= count
        expected["COMPLETED"] += count
        if after["status_counts"] != expected:
            return "unexpected outbox status change detected"
        if after["foreign_status_updated_at"] != before["foreign_status_updated_at"]:
            return "foreign outbox record changed during quarantine recovery"
        for item in completed:
            if after["targets"].get(item.outbox_id) != {"status": "COMPLETED", "attempts": item.attempts}:
                return f"completed target changed unexpectedly: {item.outbox_id}"
        for item in remaining:
            if after["targets"].get(item.outbox_id) != {"status": "QUARANTINED", "attempts": item.attempts}:
                return f"later target changed unexpectedly: {item.outbox_id}"
        return None

    async def _replay_one(self, item: OutboxItem, trade: Trade) -> dict:
        completed = await self.replay.replay(item, trade)
        return {
            "mode": "OBSERVE",
            "idempotency_key": item.idempotency_key,
            "aggregate_trade_id": trade.trade_id,
            "completed_candles": completed,
            "trading_actions": 0,
        }
