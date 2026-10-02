from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timedelta, timezone

from src.database.connection import Database
from src.models.market_data import Candle, Observation, ObservationKind, Trade
from src.research.case_builder import Gap
from src.research.case_engine import ResearchCase
from src.orderflow.observations import OrderflowObservation
from src.orderflow.validation import OrderflowValidation
from src.observation.engine import candle_input_hash


ALLOWED_TIMEFRAMES={"1m","5m","15m","1h"}
ALLOWED_OBSERVATION_PROVENANCE={"PUBLIC_MARKET_DATA_DETERMINISTIC"}
ALLOWED_RULE_VERSIONS={"bos":"1.0.0","bronxc":"1.0.0"}
SHA256_PATTERN=re.compile(r"^[0-9a-f]{64}$")
AGG_TRADE_SOURCE="BINANCE_SPOT_AGGTRADE"


def _validate_agg_trade_for_persistence(trade:Trade,now:datetime|None=None)->None:
    current=now or datetime.now(timezone.utc)
    if trade.trade_id is None or trade.trade_id < 0:raise ValueError("aggregate_trade_id must be a non-negative integer")
    if trade.buyer_is_maker is None:raise ValueError("buyer_is_maker is required for Binance Spot aggTrades")
    if not trade.symbol or not re.fullmatch(r"[A-Z0-9]{3,20}",trade.symbol):raise ValueError("Invalid aggTrade symbol")
    if trade.event_time>current+timedelta(seconds=5):raise ValueError("Future aggTrade timestamps are not allowed")


def agg_trade_hash(trade:Trade)->str:
    _validate_agg_trade_for_persistence(trade,trade.event_time)
    # Binance aggTrade event times are authoritative only to milliseconds.  A
    # legacy collector persisted some equivalent events with sub-millisecond
    # clock residue, which must not turn an otherwise identical replay into an
    # immutable-payload conflict during bounded catch-up.
    event_time=trade.event_time.replace(microsecond=(trade.event_time.microsecond // 1000) * 1000)
    payload={"aggregate_trade_id":trade.trade_id,"buyer_is_maker":trade.buyer_is_maker,"price":trade.price,"quantity":trade.quantity,"source":AGG_TRADE_SOURCE,"symbol":trade.symbol,"trade_time":event_time.isoformat()}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


def _validate_candle_for_persistence(candle:Candle,now:datetime|None=None)->None:
    current=now or datetime.now(timezone.utc)
    if candle.timeframe not in ALLOWED_TIMEFRAMES:raise ValueError(f"Unsupported candle timeframe: {candle.timeframe}")
    # Binance can deliver the first trade of a new bucket a few milliseconds
    # before the local wall clock reaches the prior bucket's close boundary.
    # The open time must already be historical; only the close boundary gets a
    # narrow, explicit skew tolerance.
    if candle.open_time>current or candle.close_time>current+timedelta(seconds=1):raise ValueError("Future candle timestamps are not allowed")


def _validate_observation_for_persistence(observation:Observation,now:datetime|None=None)->None:
    current=now or datetime.now(timezone.utc)
    if observation.timeframe not in ALLOWED_TIMEFRAMES:raise ValueError(f"Unsupported observation timeframe: {observation.timeframe}")
    if observation.observed_at>current or observation.created_at>current:raise ValueError("Future observation timestamps are not allowed")
    if observation.provenance not in ALLOWED_OBSERVATION_PROVENANCE:raise ValueError(f"Unsupported observation provenance: {observation.provenance}")
    if ALLOWED_RULE_VERSIONS.get(observation.rule_id)!=observation.rule_version:raise ValueError(f"Unsupported rule/version: {observation.rule_id}/{observation.rule_version}")
    if not SHA256_PATTERN.fullmatch(observation.input_hash):raise ValueError("Observation input_hash must be a lowercase SHA-256 digest")


def _validate_observation_input_hash(observation:Observation,candles:list[Candle])->None:
    if not candles or candle_input_hash(candles)!=observation.input_hash:raise ValueError("Observation input_hash does not match persisted candle input")


def _json_object(value: object) -> dict:
    """Normalize asyncpg JSONB output without hiding corrupt persisted data."""
    if isinstance(value, dict):
        return dict(value)
    try:
        decoded = json.loads(value) if isinstance(value, (str, bytes, bytearray)) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        decoded = None
    return dict(decoded) if isinstance(decoded, dict) else {"_quality_error": "INVALID_JSON_OBJECT"}


def _observation_from_row(row)->Observation:
    return Observation(kind=ObservationKind(row["kind"]), symbol=row["symbol"], timeframe=row["timeframe"], observed_at=row["observed_at"], summary=row["summary"], confidence=row["confidence"], evidence=_json_object(row["evidence"]), source=row["source"], provenance=row["provenance"], observation_version=row.get("observation_version",1), rule_id=row.get("rule_id","unassigned"), rule_version=row.get("rule_version","1.0.0"), input_hash=row.get("input_hash",""), observation_id=row["observation_id"], created_at=row["created_at"])


def _case_from_row(row)->ResearchCase:
    return ResearchCase(case_id=row["case_id"],symbol=row["symbol"],timeframe=row["timeframe"],opened_at=row["opened_at"],updated_at=row["updated_at"],status=row["status"],observation_ids=_json_value(row["observation_ids"],list),evidence=_json_value(row["evidence"],list),missing_evidence=_json_value(row["missing_evidence"],list),outcome=row["outcome"],rule_versions=_json_value(row["rule_versions"],dict),documentation=row["documentation"],review_history=_json_value(row.get("review_history",[]),list))


def _json_value(value:object,expected:type):
    if isinstance(value,expected):return value.copy() if isinstance(value,(list,dict)) else value
    try:decoded=json.loads(value) if isinstance(value,(str,bytes,bytearray)) else None
    except (json.JSONDecodeError,UnicodeDecodeError):decoded=None
    if not isinstance(decoded,expected):raise ValueError(f"Invalid persisted JSON; expected {expected.__name__}")
    return decoded


class MarketRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def insert_agg_trade(self,trade:Trade)->bool:
        """Persist one immutable Spot aggTrade; return False for an exact replay."""
        _validate_agg_trade_for_persistence(trade)
        query="""INSERT INTO agg_trades(symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker,source)
        VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(symbol,aggregate_trade_id) DO NOTHING"""
        async with self.database.acquire() as con:
            status=await con.execute(query,trade.symbol,trade.trade_id,trade.event_time,trade.price,trade.quantity,trade.buyer_is_maker,AGG_TRADE_SOURCE)
            if status!="INSERT 0 1":
                row=await con.fetchrow("SELECT symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker,source FROM agg_trades WHERE symbol=$1 AND aggregate_trade_id=$2",trade.symbol,trade.trade_id)
                stored=Trade(row["symbol"],row["price"],row["quantity"],row["trade_time"],row["aggregate_trade_id"],row["buyer_is_maker"])
                if row["source"]!=AGG_TRADE_SOURCE or agg_trade_hash(stored)!=agg_trade_hash(trade):raise ValueError("Conflicting payload for persisted aggregate_trade_id")
                return False
        return True

    async def agg_trades_since(self,symbol:str,since:datetime)->list[Trade]:
        async with self.database.acquire() as con:
            rows=await con.fetch("SELECT symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker FROM agg_trades WHERE symbol=$1 AND trade_time>=$2 ORDER BY trade_time,aggregate_trade_id",symbol,since)
        return [Trade(row["symbol"],row["price"],row["quantity"],row["trade_time"],row["aggregate_trade_id"],row["buyer_is_maker"]) for row in rows]

    async def agg_trades_between(self,symbol:str,start:datetime,end:datetime)->list[Trade]:
        if start.tzinfo is None or end.tzinfo is None or end<=start:raise ValueError("A valid timezone-aware aggTrade range is required")
        async with self.database.acquire() as con:
            rows=await con.fetch("SELECT symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker FROM agg_trades WHERE symbol=$1 AND trade_time>=$2 AND trade_time<$3 ORDER BY trade_time,aggregate_trade_id",symbol,start,end)
        return [Trade(row["symbol"],row["price"],row["quantity"],row["trade_time"],row["aggregate_trade_id"],row["buyer_is_maker"]) for row in rows]

    async def agg_trade_count(self,symbol:str)->int:
        async with self.database.acquire() as con:return int(await con.fetchval("SELECT count(*) FROM agg_trades WHERE symbol=$1",symbol))

    async def save_orderflow_observation_with_case(self,observation:OrderflowObservation,case:ResearchCase)->bool:
        if len(observation.evidence)<2:raise ValueError("Orderflow observation requires at least two evidence clauses")
        if observation.rule_version!="1.0.0" or observation.provenance!="BINANCE_SPOT_AGGTRADE_DETERMINISTIC" or not SHA256_PATTERN.fullmatch(observation.input_hash):raise ValueError("Invalid orderflow observation governance metadata")
        query="""INSERT INTO orderflow_observations(observation_id,kind,symbol,timeframe,observed_at,summary,evidence,rule_version,input_hash,provenance,mode)
        VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11) ON CONFLICT(observation_id) DO NOTHING"""
        async with self.database.acquire() as con:
            async with con.transaction():
                status=await con.execute(query,observation.observation_id,observation.kind,observation.symbol,observation.timeframe,observation.observed_at,observation.summary,json.dumps(observation.evidence),observation.rule_version,observation.input_hash,observation.provenance,observation.mode)
                await self._upsert_case(con,case)
        return status=="INSERT 0 1"

    async def recent_orderflow_observations(self,symbol:str,limit:int=500)->list[dict]:
        async with self.database.acquire() as con:rows=await con.fetch("SELECT * FROM orderflow_observations WHERE symbol=$1 ORDER BY observed_at DESC,observation_id LIMIT $2",symbol,limit)
        return [{**dict(row),"observed_at":row["observed_at"].isoformat(),"evidence":_json_value(row["evidence"],list)} for row in rows]

    async def pending_orderflow_observations(self,symbol:str,as_of:datetime,limit:int=500)->list[dict]:
        """Return validation work relevant to the current live replay window.

        Old incomplete observations remain durably recorded for the offline
        reconciliation path. A live observation needs its full 30-minute
        outcome horizon before it is evaluated; after that, a persisted final
        validation is immutable input for offline reconciliation. Re-reading
        either category on every candle makes live catch-up repeatedly scan
        historical agg-trades and can starve current capture. Four hours
        comfortably covers ordinary replay lag while bounding live-only cost.
        """
        oldest_live_candidate=as_of-timedelta(hours=4)
        async with self.database.acquire() as con:rows=await con.fetch("SELECT o.* FROM orderflow_observations o LEFT JOIN orderflow_validations v USING(observation_id) WHERE o.symbol=$1 AND o.observed_at<=$2 AND o.observed_at>=$3 AND (v.observation_id IS NULL OR v.validated_through < o.observed_at + interval '30 minutes') ORDER BY o.observed_at,o.observation_id LIMIT $4",symbol,as_of-timedelta(minutes=30),oldest_live_candidate,limit)
        return [{**dict(row),"observed_at":row["observed_at"].isoformat(),"evidence":_json_value(row["evidence"],list)} for row in rows]

    async def agg_trades_for_validation(self,symbol:str,observed_at:datetime,end:datetime)->list[Trade]:
        async with self.database.acquire() as con:
            baseline=await con.fetchrow("SELECT symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker FROM agg_trades WHERE symbol=$1 AND trade_time<=$2 ORDER BY trade_time DESC,aggregate_trade_id DESC LIMIT 1",symbol,observed_at)
            rows=await con.fetch("SELECT symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker FROM agg_trades WHERE symbol=$1 AND trade_time>$2 AND trade_time<=$3 ORDER BY trade_time,aggregate_trade_id",symbol,observed_at,end)
        values=([baseline] if baseline else [])+list(rows)
        return [Trade(row["symbol"],row["price"],row["quantity"],row["trade_time"],row["aggregate_trade_id"],row["buyer_is_maker"]) for row in values]

    async def save_orderflow_validation(self,validation:OrderflowValidation,case:ResearchCase|None=None)->None:
        query="""INSERT INTO orderflow_validations(observation_id,symbol,observed_at,baseline_price,horizons,complete,outcome,validation_hash,validated_through,validation_version,mode)
        VALUES($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10,$11) ON CONFLICT(observation_id) DO UPDATE SET horizons=EXCLUDED.horizons,complete=EXCLUDED.complete,outcome=EXCLUDED.outcome,validation_hash=EXCLUDED.validation_hash,validated_through=EXCLUDED.validated_through"""
        async with self.database.acquire() as con:
            async with con.transaction():
                await con.execute(query,validation.observation_id,validation.symbol,validation.observed_at,float(validation.baseline_price),json.dumps([item.to_dict() for item in validation.horizons]),validation.complete,validation.outcome,validation.validation_hash,validation.validated_through,validation.validation_version,validation.mode)
                if case is not None:await self._upsert_case(con,case)

    async def recent_orderflow_validations(self,symbol:str,limit:int=500)->list[dict]:
        async with self.database.acquire() as con:rows=await con.fetch("SELECT * FROM orderflow_validations WHERE symbol=$1 ORDER BY validated_through DESC LIMIT $2",symbol,limit)
        return [{**dict(row),"observed_at":row["observed_at"].isoformat(),"validated_through":row["validated_through"].isoformat(),"horizons":_json_value(row["horizons"],list)} for row in rows]

    async def upsert_candle(self, candle: Candle) -> None:
        _validate_candle_for_persistence(candle)
        query = """INSERT INTO candles(symbol,timeframe,open_time,close_time,open,high,low,close,volume,trade_count,closed)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        ON CONFLICT(symbol,timeframe,open_time) DO UPDATE SET close_time=EXCLUDED.close_time,open=EXCLUDED.open,high=EXCLUDED.high,
        low=EXCLUDED.low,close=EXCLUDED.close,volume=EXCLUDED.volume,trade_count=EXCLUDED.trade_count,closed=EXCLUDED.closed"""
        async with self.database.acquire() as con:
            await con.execute(query, candle.symbol, candle.timeframe, candle.open_time, candle.close_time, candle.open, candle.high, candle.low, candle.close, candle.volume, candle.trade_count, candle.closed)

    async def save_observation(self, observation: Observation) -> None:
        _validate_observation_for_persistence(observation)
        async with self.database.acquire() as con:
            await self._validate_hash_on_connection(con,observation)
            await self._insert_observation(con,observation)

    async def save_observation_with_case(self,observation:Observation,case:ResearchCase)->None:
        _validate_observation_for_persistence(observation)
        async with self.database.acquire() as con:
            async with con.transaction():
                await self._validate_hash_on_connection(con,observation)
                await self._insert_observation(con,observation)
                await self._upsert_case(con,case)

    @staticmethod
    async def _validate_hash_on_connection(con,observation:Observation)->None:
        rows=await con.fetch("SELECT * FROM candles WHERE symbol=$1 AND timeframe=$2 AND close_time<=$3 ORDER BY open_time DESC LIMIT 500",observation.symbol,observation.timeframe,observation.observed_at)
        _validate_observation_input_hash(observation,[Candle(**dict(row)) for row in reversed(rows)])

    @staticmethod
    async def _insert_observation(con,observation:Observation)->None:
        query="""INSERT INTO observations(observation_id,observed_at,created_at,kind,symbol,timeframe,summary,confidence,evidence,source,provenance,observation_version,rule_id,rule_version,input_hash)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,$14,$15) ON CONFLICT DO NOTHING"""
        await con.execute(query,observation.observation_id,observation.observed_at,observation.created_at,observation.kind.value,observation.symbol,observation.timeframe,observation.summary,observation.confidence,json.dumps(observation.evidence),observation.source,observation.provenance,observation.observation_version,observation.rule_id,observation.rule_version,observation.input_hash)

    @staticmethod
    async def _upsert_case(con,case:ResearchCase)->None:
        query="""INSERT INTO research_cases(case_id,symbol,timeframe,opened_at,updated_at,status,observation_ids,evidence,missing_evidence,outcome,rule_versions,documentation,review_history)
        VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb,$10,$11::jsonb,$12,$13::jsonb)
        ON CONFLICT(case_id) DO UPDATE SET updated_at=EXCLUDED.updated_at,status=EXCLUDED.status,observation_ids=EXCLUDED.observation_ids,evidence=EXCLUDED.evidence,missing_evidence=EXCLUDED.missing_evidence,outcome=EXCLUDED.outcome,rule_versions=EXCLUDED.rule_versions,documentation=EXCLUDED.documentation,review_history=EXCLUDED.review_history"""
        await con.execute(query,case.case_id,case.symbol,case.timeframe,case.opened_at,case.updated_at,case.status,json.dumps(case.observation_ids),json.dumps(case.evidence),json.dumps(case.missing_evidence),case.outcome,json.dumps(case.rule_versions),case.documentation,json.dumps(getattr(case,"review_history",[])))

    async def upsert_research_case(self, case: ResearchCase) -> None:
        async with self.database.acquire() as con:
            await self._upsert_case(con,case)

    async def recent_candles(self, symbol: str, timeframe: str, limit: int = 200) -> list[Candle]:
        async with self.database.acquire() as con:
            rows = await con.fetch(
                """SELECT * FROM candles
                WHERE symbol=$1 AND timeframe=$2
                  AND high >= open AND high >= close AND high >= low
                  AND low <= open AND low <= close AND low <= high
                ORDER BY open_time DESC LIMIT $3""",
                symbol,
                timeframe,
                limit,
            )
        return [Candle(**dict(row)) for row in reversed(rows)]

    async def recent_observations(self, symbol: str, limit: int = 100) -> list[Observation]:
        async with self.database.acquire() as con:
            rows = await con.fetch("SELECT * FROM observations WHERE symbol=$1 ORDER BY observed_at DESC LIMIT $2", symbol, limit)
        return [_observation_from_row(row) for row in rows]

    async def recent_research_cases(self,symbol:str,limit:int=1000)->list[ResearchCase]:
        async with self.database.acquire() as con:
            rows=await con.fetch("SELECT * FROM research_cases WHERE symbol=$1 ORDER BY updated_at DESC LIMIT $2",symbol,limit)
        return [_case_from_row(row) for row in rows]

    # --- Research Case materialization (Issue #3): reads are read-only; the
    # only write is apply_research_cases, which touches research_cases alone.
    async def observations_until(self,symbol:str,as_of:datetime)->list[Observation]:
        async with self.database.acquire() as con:
            rows=await con.fetch("SELECT * FROM observations WHERE symbol=$1 AND observed_at<=$2 ORDER BY observed_at,observation_id",symbol,as_of)
        return [_observation_from_row(row) for row in rows]

    async def observations_fingerprint(self,symbol:str,created_until:datetime|None=None)->dict:
        """Count and content hash of persisted observations; proves the materialization left them untouched.
        ``created_until`` limits the check to rows that already existed, so the live runtime may keep appending."""
        async with self.database.acquire() as con:
            row=await con.fetchrow("SELECT count(*) AS n, coalesce(md5(string_agg(observation_id::text||':'||input_hash||':'||kind||':'||observed_at::text, ',' ORDER BY observation_id)),'') AS digest FROM observations WHERE symbol=$1 AND ($2::timestamptz IS NULL OR created_at<=$2)",symbol,created_until)
        return {"observations":int(row["n"]),"digest":str(row["digest"])}

    async def observation_research_cases(self,symbol:str)->list[ResearchCase]:
        async with self.database.acquire() as con:
            rows=await con.fetch("SELECT * FROM research_cases WHERE symbol=$1 AND case_id LIKE 'case\\_%' ORDER BY case_id",symbol)
        return [_case_from_row(row) for row in rows]

    async def research_case_gaps(self,symbol:str)->list[Gap]:
        async with self.database.acquire() as con:
            rows=await con.fetch("SELECT gap_id,symbol,gap_started_at,gap_ended_at FROM ingestion_gap_incidents WHERE symbol=$1 AND gap_started_at IS NOT NULL ORDER BY gap_id",symbol)
        return [Gap(gap_id=row["gap_id"],symbol=row["symbol"],start=row["gap_started_at"],end=row["gap_ended_at"]) for row in rows]

    async def candle_closes(self,symbol:str,timeframe:str,start:datetime,end:datetime)->list[dict]:
        async with self.database.acquire() as con:
            rows=await con.fetch("SELECT close_time,close FROM candles WHERE symbol=$1 AND timeframe=$2 AND close_time>=$3 AND close_time<=$4 ORDER BY close_time",symbol,timeframe,start,end)
        return [{"close_time":row["close_time"],"close":float(row["close"])} for row in rows]

    async def apply_research_cases(self,cases:list[ResearchCase],as_of:datetime|None=None)->dict:
        """Upsert derived cases in one transaction; unchanged rows are not rewritten.

        Rows the live runtime extended after ``as_of`` (updated_at > as_of) are
        left alone: the rebuild cannot see those newer observations.
        """
        inserted=updated=unchanged=skipped_newer=0
        async with self.database.acquire() as con:
            async with con.transaction():
                for case in cases:
                    row=await con.fetchrow("SELECT * FROM research_cases WHERE case_id=$1 FOR UPDATE",case.case_id)
                    if row is not None and as_of is not None and row["updated_at"]>as_of:
                        skipped_newer+=1
                        continue
                    if row is not None and _case_from_row(row).to_dict()==case.to_dict():
                        unchanged+=1
                        continue
                    await self._upsert_case(con,case)
                    if row is None:inserted+=1
                    else:updated+=1
        return {"inserted":inserted,"updated":updated,"unchanged":unchanged,"skipped_newer":skipped_newer}
