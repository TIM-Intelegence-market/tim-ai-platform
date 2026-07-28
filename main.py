from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import signal
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from config.settings import settings
from src.data_ingestion.aggregator import CandleAggregator
from src.data_ingestion.aggregator import bucket_start
from src.data_ingestion.binance_ws import BinanceTradeStream
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
from src.research.case_engine import ResearchCaseEngine
from src.research.trigger import ResearchTrigger

log = logging.getLogger("tim")


class TIMApplication:
    def __init__(self) -> None:
        self.database = Database(settings.database_url)
        self.repository = MarketRepository(self.database)
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
            "queue_model": "DIRECT_AWAIT_NO_APPLICATION_QUEUE",
            "ollama_enabled": settings.enable_ollama,
            "ollama_availability": "PENDING" if settings.enable_ollama else "DISABLED_BY_POLICY",
        })
        self.dashboard = DashboardServer(self.dashboard_state, settings.dashboard_host, settings.dashboard_port)
        self.history: dict[str, list[Candle]] = {timeframe: [] for timeframe in settings.timeframes}
        self.stream = BinanceTradeStream(settings.binance_ws_url, settings.symbol, self.on_trade)

    async def on_trade(self, trade: Trade) -> None:
        if not await self.repository.insert_agg_trade(trade):
            return
        for candle in self.aggregator.add_trade(trade):
            await self.repository.upsert_candle(candle)
            if candle.timeframe=="1m":
                await self.process_orderflow_window(candle.open_time,candle.close_time)
                await self.validate_pending_orderflow(candle.close_time)
            history = self.history[candle.timeframe]
            history.append(candle)
            del history[:-500]
            with self.dashboard_state.lock:
                self.dashboard_state.recent_candles.append({"symbol":candle.symbol,"timeframe":candle.timeframe,"open_time":candle.open_time.isoformat(),"close_time":candle.close_time.isoformat(),"open":candle.open,"high":candle.high,"low":candle.low,"close":candle.close,"volume":candle.volume,"trade_count":candle.trade_count,"provenance":"PUBLIC_MARKET_DATA"})
                del self.dashboard_state.recent_candles[:-50]
            observations = self.observations.evaluate(history)
            for observation in observations:
                case = self.cases.ingest(observation)
                await self.repository.save_observation_with_case(observation,case)
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

    async def restore_persisted_state(self)->None:
        for timeframe in settings.timeframes:
            self.history[timeframe]=await self.repository.recent_candles(settings.symbol,timeframe,500)
        recent_dashboard_candles=sorted((candle for candles in self.history.values() for candle in candles),key=lambda candle:candle.close_time)[-50:]
        historical=await self.repository.recent_observations(settings.symbol,1000)
        for observation in reversed(historical):self.memory.remember(observation)
        persisted_cases=await self.repository.recent_research_cases(settings.symbol,1000)
        persisted_orderflow=await self.repository.recent_orderflow_observations(settings.symbol,500) if hasattr(self.repository,"recent_orderflow_observations") else []
        persisted_validations=await self.repository.recent_orderflow_validations(settings.symbol,500) if hasattr(self.repository,"recent_orderflow_validations") else []
        current_bucket=await self.repository.agg_trades_since(settings.symbol,bucket_start(datetime.now(timezone.utc),"1h")) if hasattr(self.repository,"agg_trades_since") else []
        for trade in current_bucket:self.aggregator.add_trade(trade)
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
        await self.restore_persisted_state()
        self.dashboard.start()
        try:
            with self.dashboard_state.lock:
                self.dashboard_state.system_health["stream"] = "running"
            await self.stream.run()
        finally:
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
