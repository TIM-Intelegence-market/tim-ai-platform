from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import logging
import signal
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from time import monotonic
from pathlib import Path

from config.settings import settings
from src.data_ingestion.aggregator import CandleAggregator
from src.data_ingestion.aggregator import bucket_start
from src.data_ingestion.binance_ws import BinanceTradeStream
from src.data_ingestion.catchup import CatchUpCoordinator, PublicBinanceAggTradeClient
from src.data_ingestion.durable import DurableIngestionStore, DurableOutboxWorker, OutboxItem
from src.data_ingestion.ingress import DurableIngress
from src.data_ingestion.recovery import PersistedTradeReplayService
from src.dashboard.app import DashboardServer, DashboardState
from src.database.connection import Database
from src.database.repository import MarketRepository
from src.llm.ollama_client import OllamaClient
from src.llm.prompts import observation_prompt
from src.memory.market_memory import MarketMemory
from src.models.market_data import Candle, Observation, Trade
from src.observation.engine import ObservationEngine
from src.orderflow.metrics import OrderflowMetricsService
from src.orderflow.observations import OrderflowObservationEngine, OrderflowResearchCaseEngine
from src.orderflow.validation import OrderflowValidationEngine
from src.operational.logging import StructuredLog
from src.research.case_builder import ACTIVE_STATUSES, is_builder_case, refresh_case
from src.research.case_engine import ResearchCaseEngine
from src.research.trigger import ResearchTrigger

log = logging.getLogger("tim")
# Ingestion telemetry cadence: one metrics query per interval at most. A sample
# older than FRESH (including its own query time) is always labelled stale.
HEALTH_SNAPSHOT_INTERVAL_SECONDS = 5.0
HEALTH_SNAPSHOT_FRESH_SECONDS = 1.0


class TIMApplication:
    def __init__(self) -> None:
        self.database = Database(settings.database_url)
        self.repository = MarketRepository(self.database)
        self.durable_store = DurableIngestionStore(self.database)
        self.catchup = CatchUpCoordinator(self.durable_store, PublicBinanceAggTradeClient())
        self.durable_ingress = DurableIngress(self.durable_store, catchup=self.catchup)
        self.aggregator = CandleAggregator(settings.timeframes)
        self.observations = ObservationEngine()
        self.memory = MarketMemory()
        self.cases = ResearchCaseEngine()
        self.research_trigger = ResearchTrigger()
        self.orderflow_metrics = OrderflowMetricsService(self.repository)
        self.orderflow_observations = OrderflowObservationEngine()
        self.orderflow_cases = OrderflowResearchCaseEngine()
        self.orderflow_validation = OrderflowValidationEngine()
        self.ollama = OllamaClient(settings.ollama_url, settings.ollama_model)
        self.dashboard_state = DashboardState()
        self.dashboard_state.system_health.update({
            "queue_depth": 0,
            "queue_model": "POSTGRES_DURABLE_OUTBOX_V1",
            "ollama_enabled": settings.enable_ollama,
            "ollama_availability": "PENDING" if settings.enable_ollama else "DISABLED_BY_POLICY",
        })
        self.dashboard = DashboardServer(self.dashboard_state, settings.dashboard_host, settings.dashboard_port)
        self.history: dict[str, list[Candle]] = {timeframe: [] for timeframe in settings.timeframes}
        self.queue_log = StructuredLog(Path("data/operational/queue.jsonl"))
        self.worker_stop = asyncio.Event()
        # Ingestion telemetry is sampled at most once per interval; worker
        # decisions never depend on it (see _refresh_ingestion_health).
        self._ingestion_health_lock = asyncio.Lock()
        self._ingestion_health_snapshot: dict | None = None
        self._ingestion_health_sample_started = 0.0
        self._ingestion_health_observed_at: str | None = None
        self.enrichment_worker = DurableOutboxWorker(
            self.durable_store,
            "CANDLE_V1",
            self.process_persisted_trade,
            # Contiguous strict-order prefix per claim (see claim_strict_prefix);
            # processing, retries and quarantine stay strictly one item at a time.
            batch_size=settings.outbox_batch_size,
            # Hour-boundary enrichment has measured production runtimes up to
            # 169 seconds. Keep the lease above that verified maximum so a
            # healthy in-flight item cannot be reclaimed as an expired lease.
            lease_seconds=300,
            strict_order=True,
        )
        self.stream = BinanceTradeStream(
            settings.binance_ws_url,
            settings.symbol,
            self.ingest_trade,
            stream_event_handler=self.durable_ingress.on_stream_event,
            recovery_handler=self.durable_ingress.recover_before_resume,
            recovery_on_connect=True,
        )

    async def ingest_trade(self, trade: Trade) -> None:
        result = await self.durable_ingress(trade)
        with self.dashboard_state.lock:
            self.dashboard_state.system_health["queue_depth"] = result.queue_depth
            self.dashboard_state.system_health["cursor_trade_id"] = result.cursor.last_aggregate_trade_id
            self.dashboard_state.system_health["recovery_state"] = result.cursor.recovery_state
            # The durable cursor is updated before the asynchronous enrichment
            # worker.  It is therefore the authoritative liveness signal for
            # the market-data stream; completed candles can legitimately lag
            # while the outbox is being processed.
            self.dashboard_state.system_health["last_raw_persisted_at"] = (
                result.cursor.last_persisted_at.isoformat()
                if result.cursor.last_persisted_at else None
            )

    async def on_trade(self, trade: Trade) -> None:
        """Compatibility alias: live ingress is persistence-only."""
        await self.ingest_trade(trade)

    async def process_persisted_trade(self, item: OutboxItem, trade: Trade) -> dict:
        """Run enrichment outside the WebSocket reader for one durable raw event."""
        try:
            completed = await self._enrich_trade(trade)
        except asyncio.CancelledError:
            await asyncio.shield(self.restore_persisted_state(reset=True))
            raise
        except ValueError as error:
            if str(error) not in {
                "Out-of-order trade rejected",
                "Trade belongs to an already closed candle",
            }:
                await self.restore_persisted_state(reset=True)
                raise
            completed = await self._replay_persisted_trade(item, trade)
        except Exception:
            await self.restore_persisted_state(reset=True)
            raise
        return {
            "mode": "OBSERVE",
            "idempotency_key": item.idempotency_key,
            "aggregate_trade_id": trade.trade_id,
            "completed_candles": completed,
            "trading_actions": 0,
        }

    async def _replay_persisted_trade(self, item: OutboxItem, trade: Trade) -> list[dict]:
        """Repair candle state from persisted chronological input, isolated from live state."""
        return await PersistedTradeReplayService(self.durable_store, self.repository).replay(item, trade)

    async def _enrich_trade(self, trade: Trade) -> list[dict]:
        candidate_aggregator = copy.deepcopy(self.aggregator)
        completed_summary: list[dict] = []
        for candle in candidate_aggregator.add_trade(trade):
            await self.repository.upsert_candle(candle)
            if candle.timeframe=="1m":
                await self.process_orderflow_window(candle.open_time,candle.close_time)
                await self.validate_pending_orderflow(candle.close_time)
            history = self.history[candle.timeframe]
            history[:] = [
                existing for existing in history
                if not (existing.symbol == candle.symbol and existing.open_time == candle.open_time)
            ]
            history.append(candle)
            history.sort(key=lambda existing: existing.open_time)
            del history[:-500]
            with self.dashboard_state.lock:
                self.dashboard_state.recent_candles[:] = [
                    existing for existing in self.dashboard_state.recent_candles
                    if not (
                        existing.get("symbol") == candle.symbol
                        and existing.get("timeframe") == candle.timeframe
                        and existing.get("open_time") == candle.open_time.isoformat()
                    )
                ]
                self.dashboard_state.recent_candles.append({"symbol":candle.symbol,"timeframe":candle.timeframe,"open_time":candle.open_time.isoformat(),"close_time":candle.close_time.isoformat(),"open":candle.open,"high":candle.high,"low":candle.low,"close":candle.close,"volume":candle.volume,"trade_count":candle.trade_count,"provenance":"PUBLIC_MARKET_DATA"})
                del self.dashboard_state.recent_candles[:-50]
            observations = self.observations.evaluate(history)
            for observation in observations:
                case = self.cases.ingest(observation)
                await self._save_observation_tolerant(observation,case)
                self.memory.remember(observation)
                triggered = await self.research_trigger.handle(observation)
                if triggered is not None:
                    case.documentation = f"Research container only; trigger={triggered.pattern}; module={triggered.module}; artifact={triggered.artifact_id}; no setup, signal, or prediction."
                    await self.repository.upsert_research_case(case)
                with self.dashboard_state.lock:
                    self.dashboard_state.active_observations.append(observation.to_dict())
                    del self.dashboard_state.active_observations[:-1000]
                    self.dashboard_state.research_cases = [item.to_dict() for item in self.cases.cases.values()]
                    self.dashboard_state.memory_status = {"observations": self.memory.size, "method": "deterministic_jaccard"}
                log.info("%s", observation.to_dict())
                if triggered is not None:log.info("Research trigger: %s", asdict(triggered))
                await self.explain(observation)
            await self._refresh_research_cases(candle)
            completed_summary.append(
                {
                    "symbol": candle.symbol,
                    "timeframe": candle.timeframe,
                    "open_time": candle.open_time.isoformat(),
                    "close_time": candle.close_time.isoformat(),
                }
            )
        self.aggregator = candidate_aggregator
        return completed_summary

    async def _refresh_research_cases(self, candle: Candle) -> None:
        """Re-derive active observation cases of this timeframe at the candle close (data time, never wall clock)."""
        active = [case for case in self.cases.cases.values() if is_builder_case(case) and case.symbol == candle.symbol and case.timeframe == candle.timeframe and case.status in ACTIVE_STATUSES]
        if not active:
            return
        gaps = await self.repository.research_case_gaps(candle.symbol) if hasattr(self.repository, "research_case_gaps") else []
        bars = [{"close_time": item.close_time, "close": item.close} for item in self.history[candle.timeframe]]
        changed = [case for case in active if refresh_case(case, candle.close_time, gaps=gaps, candles=bars)]
        for case in changed:
            await self.repository.upsert_research_case(case)
        if changed:
            with self.dashboard_state.lock:
                self.dashboard_state.research_cases = [item.to_dict() for item in self.cases.cases.values()]

    async def process_orderflow_window(self,start:datetime,end:datetime)->None:
        metrics=await self.orderflow_metrics.calculate_series(settings.symbol,start-(end-start),end,int((end-start).total_seconds()))
        if len(metrics)!=2:return
        for observation in self.orderflow_observations.evaluate(metrics[0],metrics[1]):
            case=self.orderflow_cases.create(observation)
            if await self.repository.save_orderflow_observation_with_case(observation,case):
                self.cases.cases[case.case_id]=case
                with self.dashboard_state.lock:
                    self.dashboard_state.orderflow_observations.append(observation.to_dict())
                    del self.dashboard_state.orderflow_observations[:-500]
                    self.dashboard_state.research_cases=[item.to_dict() for item in self.cases.cases.values()]

    async def _save_observation_tolerant(self, observation: Observation, case) -> None:
        """Save once; on input-hash mismatch rebuild once from refreshed state.

        A concurrent historical write can land between observation build and
        the save-time re-read. Rebuild exactly once from refreshed history and
        save current truth instead. A second mismatch raises through the normal
        fail path (fail-closed preserved; attempts semantics unchanged because
        this all happens inside one claim).
        """
        try:
            await self.repository.save_observation_with_case(observation, case)
            return
        except ValueError as error:
            if "input_hash does not match persisted candle input" not in str(error):
                raise
        await self.restore_persisted_state(reset=False)
        for candidate in self.observations.evaluate(self.history[observation.timeframe]):
            await self.repository.save_observation_with_case(
                candidate, self.cases.ingest(candidate))

    async def validate_pending_orderflow(self,as_of:datetime)->None:
        for observation in await self.repository.pending_orderflow_observations(settings.symbol,as_of):
            end=min(as_of,datetime.fromisoformat(observation["observed_at"])+timedelta(minutes=30))
            trades=await self.repository.agg_trades_for_validation(settings.symbol,datetime.fromisoformat(observation["observed_at"]),end)
            validation=self.orderflow_validation.validate(observation,trades,as_of)
            if validation is None:continue
            case_id="ofcase_"+hashlib.sha256(str(observation["observation_id"]).encode()).hexdigest()[:20]
            case=self.cases.cases.get(case_id)
            if validation.complete and case:self.orderflow_validation.apply_to_case(validation,case)
            await self.repository.save_orderflow_validation(validation,case if validation.complete else None)
            with self.dashboard_state.lock:
                self.dashboard_state.orderflow_validations=[item for item in self.dashboard_state.orderflow_validations if item.get("observation_id")!=validation.observation_id]+[validation.to_dict()]

    async def explain(self, observation: Observation) -> None:
        if not settings.enable_ollama:
            return
        try:
            explanation = await self.ollama.generate_json(observation_prompt(observation))
            log.info("Ollama explanation: %s", explanation)
        except Exception as exc:
            log.warning("Optional Ollama explanation unavailable: %s", exc)

    async def restore_persisted_state(self, *, reset: bool = False)->None:
        if reset:
            self.aggregator = CandleAggregator(settings.timeframes)
            self.observations = ObservationEngine()
            self.memory = MarketMemory()
            self.cases = ResearchCaseEngine()
            self.research_trigger = ResearchTrigger()
            self.history = {timeframe: [] for timeframe in settings.timeframes}
        for timeframe in settings.timeframes:
            self.history[timeframe]=await self.repository.recent_candles(settings.symbol,timeframe,500)
        recent_dashboard_candles=sorted((candle for candles in self.history.values() for candle in candles),key=lambda candle:candle.close_time)[-50:]
        historical=await self.repository.recent_observations(settings.symbol,1000)
        for observation in reversed(historical):self.memory.remember(observation)
        persisted_cases=await self.repository.recent_research_cases(settings.symbol,1000)
        persisted_orderflow=await self.repository.recent_orderflow_observations(settings.symbol,500) if hasattr(self.repository,"recent_orderflow_observations") else []
        persisted_validations=await self.repository.recent_orderflow_validations(settings.symbol,500) if hasattr(self.repository,"recent_orderflow_validations") else []
        # Rebuild from the oldest latest persisted candle, rather than merely
        # the current hour. This preserves a raw trade bucket that was active
        # when the prior process stopped and idempotently repairs any completed
        # candles yielded during replay before live streaming resumes.
        latest_persisted=[candles[-1].open_time for candles in self.history.values() if candles]
        recovery_start=min(latest_persisted) if latest_persisted else bucket_start(datetime.now(timezone.utc),"1h")
        if hasattr(self, "durable_store") and hasattr(self.durable_store, "processed_trades_since"):
            recovery_trades = await self.durable_store.processed_trades_since(settings.symbol, recovery_start)
        else:
            recovery_trades=await self.repository.agg_trades_since(settings.symbol,recovery_start) if hasattr(self.repository,"agg_trades_since") else []
        for trade in recovery_trades:
            for recovered in self.aggregator.add_trade(trade):
                if hasattr(self.repository,"upsert_candle"):
                    await self.repository.upsert_candle(recovered)
        self.cases.cases={case.case_id:case for case in persisted_cases}
        self.observations.restore_seen([str(item.observation_id) for item in historical])
        with self.dashboard_state.lock:
            self.dashboard_state.recent_candles=[{"symbol":candle.symbol,"timeframe":candle.timeframe,"open_time":candle.open_time.isoformat(),"close_time":candle.close_time.isoformat(),"open":candle.open,"high":candle.high,"low":candle.low,"close":candle.close,"volume":candle.volume,"trade_count":candle.trade_count,"provenance":"PUBLIC_MARKET_DATA"} for candle in recent_dashboard_candles]
            self.dashboard_state.active_observations=[item.to_dict() for item in reversed(historical)]
            self.dashboard_state.research_cases=[item.to_dict() for item in persisted_cases]
            self.dashboard_state.orderflow_observations=list(reversed(persisted_orderflow))
            self.dashboard_state.orderflow_validations=list(reversed(persisted_validations))
            self.dashboard_state.memory_status={"observations":self.memory.size,"method":"deterministic_jaccard"}
            self.dashboard_state.market_status={"symbol":settings.symbol,"timeframes":settings.timeframes,"status":"COLLECTING_PUBLIC_DATA"}
            self.dashboard_state.system_health["stream"]="starting"
        if hasattr(self.repository,"save_orderflow_observation_with_case"):
            latest_complete=bucket_start(datetime.now(timezone.utc),"1m")
            await self.process_orderflow_window(latest_complete-timedelta(minutes=1),latest_complete)
            await self.validate_pending_orderflow(latest_complete)

    def _health_labels(self, now: float, *, cached: bool) -> dict:
        age = max(0.0, now - self._ingestion_health_sample_started)
        return {
            "health_snapshot_cached": cached,
            # A sample is current only when it was just taken and the query itself
            # was fast; anything else is labelled stale, never passed off as live.
            "health_snapshot_stale": cached or age > HEALTH_SNAPSHOT_FRESH_SECONDS,
            "health_snapshot_age_seconds": round(age, 3),
            "health_snapshot_observed_at": self._ingestion_health_observed_at,
            "health_snapshot_scope": "telemetry_only",
        }

    def _publish_health(self, snapshot: dict) -> None:
        with self.dashboard_state.lock:
            self.dashboard_state.system_health.update(
                {key: snapshot.get(key) for key in (
                    "queue_depth", "queue_high_water", "queue_oldest_age", "cursor_age", "recovery_state",
                    "duplicate_total", "out_of_order_total", "health_snapshot_cached", "health_snapshot_stale",
                    "health_snapshot_age_seconds", "health_snapshot_observed_at", "health_snapshot_scope",
                ) if key in snapshot}
            )

    async def _refresh_ingestion_health(self) -> dict:
        """Telemetry only: at most one metrics query per interval, never a worker dependency.

        Concurrent callers share one query (lock). A cached sample is returned as a
        copy labelled cached/stale with its age measured from the sample start, so the
        query duration counts towards the age. A failed refresh keeps the previous
        sample, marks it stale, re-raises, and the next call retries.
        """
        async with self._ingestion_health_lock:
            now = monotonic()
            if (
                self._ingestion_health_snapshot is not None
                and now - self._ingestion_health_sample_started < HEALTH_SNAPSHOT_INTERVAL_SECONDS
            ):
                labels = self._health_labels(now, cached=True)
                # Only the labels: ingest_trade publishes live queue_depth and
                # recovery_state, which an older cached sample must not overwrite.
                self._publish_health(labels)
                return {**self._ingestion_health_snapshot, **labels}
            started = now
            try:
                metrics = await self.durable_store.metrics_snapshot(settings.symbol)
            except Exception:
                with self.dashboard_state.lock:
                    self.dashboard_state.system_health.update(
                        {
                            "health_snapshot_stale": True,
                            "health_snapshot_age_seconds": round(max(0.0, monotonic() - self._ingestion_health_sample_started), 3)
                            if self._ingestion_health_snapshot is not None else None,
                        }
                    )
                raise
            self._ingestion_health_sample_started = started
            self._ingestion_health_observed_at = datetime.now(timezone.utc).isoformat()
            self._ingestion_health_snapshot = dict(metrics)
            snapshot = {**metrics, **self._health_labels(monotonic(), cached=False)}
            self._publish_health(snapshot)
            return snapshot

    def _last_health_for_evidence(self) -> dict:
        """Previous sample (or none) for log evidence without querying the database."""
        if self._ingestion_health_snapshot is None:
            return {
                "queue_depth": None, "queue_oldest_age": None, "recovery_state": None,
                "health_snapshot_cached": True, "health_snapshot_stale": True, "health_snapshot_age_seconds": None,
                "health_snapshot_observed_at": None, "health_snapshot_scope": "telemetry_only",
            }
        return {**self._ingestion_health_snapshot, **self._health_labels(monotonic(), cached=True)}

    async def _worker_loop(self) -> None:
        loop = asyncio.get_running_loop()
        next_probe = loop.time()
        while not self.worker_stop.is_set():
            try:
                result = await self.enrichment_worker.run_once()
                terminal_blocked = result.get("status") == "TERMINAL_BLOCKED"
                if terminal_blocked:
                    with self.dashboard_state.lock:
                        self.dashboard_state.system_health["worker"] = "TERMINAL_BLOCKED"
                        self.dashboard_state.system_health["terminal_blocker"] = result["terminal_blocker"]
                    # The blocker is authoritative evidence on its own; logging it must
                    # not wait for (or fail with) a telemetry query.
                    metrics = self._last_health_for_evidence()
                else:
                    try:
                        metrics = await self._refresh_ingestion_health()
                    except Exception as error:
                        # Telemetry never stops the worker, but a failing sample must stay visible.
                        self.queue_log.write(
                            "INGESTION_HEALTH_UNAVAILABLE",
                            severity="WARNING",
                            mode="OBSERVE",
                            trading_actions=0,
                            error_type=type(error).__name__,
                            rate_limit_seconds=60.0,
                            rate_limit_key=f"INGESTION_HEALTH_UNAVAILABLE:{type(error).__name__}",
                        )
                        metrics = self._last_health_for_evidence()
                self.queue_log.write(
                    "OUTBOX_WORKER_CYCLE",
                    mode="OBSERVE",
                    trading_actions=0,
                    worker="CANDLE_V1",
                    result=result,
                    queue_depth=metrics.get("queue_depth"),
                    queue_oldest_age=metrics.get("queue_oldest_age"),
                    recovery_state=metrics.get("recovery_state"),
                    health_snapshot_cached=metrics.get("health_snapshot_cached"),
                    health_snapshot_stale=metrics.get("health_snapshot_stale"),
                    health_snapshot_age_seconds=metrics.get("health_snapshot_age_seconds"),
                    health_snapshot_observed_at=metrics.get("health_snapshot_observed_at"),
                    health_snapshot_scope=metrics.get("health_snapshot_scope"),
                    severity="ERROR" if terminal_blocked else "INFO",
                    rate_limit_seconds=60.0 if not result["claimed"] else 0.0,
                    rate_limit_key=(
                        f"TERMINAL_BLOCKED:{result['terminal_blocker']['outbox_id']}"
                        if terminal_blocked else "OUTBOX_WORKER_IDLE"
                    ) if not result["claimed"] else None,
                )
                if result["claimed"]:
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as error:
                with self.dashboard_state.lock:
                    self.dashboard_state.system_health["worker"] = "DEGRADED"
                    self.dashboard_state.system_health["worker_error_type"] = type(error).__name__
                self.queue_log.write(
                    "OUTBOX_WORKER_UNAVAILABLE",
                    severity="ERROR",
                    mode="OBSERVE",
                    trading_actions=0,
                    error_type=type(error).__name__,
                    rate_limit_seconds=30.0,
                    rate_limit_key=f"OUTBOX_WORKER_UNAVAILABLE:{type(error).__name__}:{error}",
                )
            next_probe += 0.25
            delay = max(0.0, next_probe - loop.time())
            await asyncio.sleep(delay)
            lag = max(0.0, loop.time() - next_probe)
            await self.durable_store.record_metric("event_loop_lag", lag, kind="GAUGE")
            if lag > 1.0:
                next_probe = loop.time()

    async def recover_quarantined(self, outbox_id: str) -> dict:
        """Explicit single-record recovery entrypoint; never scans other quarantines."""
        result = await self.enrichment_worker.recover_one(outbox_id)
        if result["status"] == "COMPLETED":
            await self.restore_persisted_state(reset=True)
        return result

    async def run(self, initialize_schema: bool = False) -> None:
        await self.database.connect()
        with self.dashboard_state.lock:
            self.dashboard_state.system_health["database"] = "connected"
        if settings.enable_ollama:
            available = await self.ollama.available()
            with self.dashboard_state.lock:
                self.dashboard_state.system_health["ollama_availability"] = "AVAILABLE" if available else "UNAVAILABLE"
        if initialize_schema:
            await self.database.initialize_schema()
        await self.durable_store.bootstrap_cursor(settings.symbol)
        await self.durable_store.record_metric("restart_total")
        await self.restore_persisted_state()
        self.dashboard.start()
        worker_task = asyncio.create_task(self._worker_loop(), name="tim-durable-enrichment-worker")
        try:
            with self.dashboard_state.lock:
                self.dashboard_state.system_health["stream"] = "running"
            await self.stream.run()
        finally:
            self.worker_stop.set()
            try:
                await asyncio.wait_for(worker_task, timeout=30)
            except TimeoutError:
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass
            self.dashboard.stop()
            await self.database.close()


async def async_main(initialize_schema: bool) -> None:
    app = TIMApplication()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            loop.add_signal_handler(getattr(signal, name), app.stream.stop)
    await app.run(initialize_schema)


def main() -> int:
    parser = argparse.ArgumentParser(description="TIM public market observation service")
    parser.add_argument("--init-schema", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(async_main(args.init_schema))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
