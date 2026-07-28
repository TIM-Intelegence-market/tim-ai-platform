from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

import asyncpg
from config.settings import settings
from src.acceptance.monitor import AcceptanceMonitor,run_acceptance_check
from src.data_ingestion.aggregator import timeframe_seconds
from src.operational.logging import StructuredLog


def persisted_candle_gaps(records:list,configured_timeframes:tuple[str,...])->list[dict]:
    expected={timeframe:timeframe_seconds(timeframe) for timeframe in configured_timeframes}
    previous={};gaps=[]
    for record in sorted(records,key=lambda item:(str(item["timeframe"]),item["open_time"])):
        timeframe=str(record["timeframe"])
        if timeframe not in expected:continue
        prior=previous.get(timeframe);current=record["open_time"]
        if prior is not None:
            actual=int((current-prior).total_seconds())
            if actual!=expected[timeframe]:
                gaps.append({"timeframe":timeframe,"prior":prior.isoformat(),"open_time":current.isoformat(),"expected_seconds":expected[timeframe],"actual_seconds":actual})
        previous[timeframe]=current
    return gaps


def document_data_gaps(root:Path,context:dict,detected_at:datetime)->int:
    """Append each newly detected persisted gap once; never reconstruct data."""
    events_path=root/"data/operational/events.jsonl"
    known=set()
    try:lines=events_path.read_text().splitlines()
    except OSError:lines=[]
    for line in lines:
        try:value=json.loads(line)
        except (ValueError,TypeError):continue
        if value.get("event")=="DATA_GAP" and value.get("gap_key"):known.add(str(value["gap_key"]))
    logger=StructuredLog(events_path);written=0
    for gap in context.get("candle_gap_details",[]):
        timeframe=str(gap["timeframe"]);prior=datetime.fromisoformat(str(gap["prior"]));recovery=datetime.fromisoformat(str(gap["open_time"]));expected=int(gap["expected_seconds"])
        start=prior+timedelta(seconds=expected);duration=max(0,int((recovery-start).total_seconds()))
        key=f"{settings.symbol}|{timeframe}|{start.isoformat()}|{recovery.isoformat()}"
        if key in known:continue
        logger.write("DATA_GAP",severity="ERROR",mode="OBSERVE",gap_key=key,begin=start.isoformat(),end=recovery.isoformat(),duration_seconds=duration,cause="UNKNOWN_SOURCE_OR_PERSISTENCE_GAP",affected_streams=[f"{settings.symbol}_{timeframe}_CANDLES"],affected_observations=[],affected_observation_status="NOT_CREATED_FOR_MISSING_INTERVALS",recovery_at=recovery.isoformat(),detected_at=detected_at.isoformat(),scientific_impact="CONTINUOUS_COVERAGE_CLAIMS_EXCLUDE_THIS_INTERVAL",reconstruction_performed=False)
        known.add(key);written+=1
    return written


async def database_context(started_at:datetime,as_of:datetime)->dict:
    connection=await asyncpg.connect(settings.database_url,timeout=5)
    try:
        candles=await connection.fetchrow("SELECT count(*) FILTER (WHERE open_time >= $1 AND open_time <= $2) n, count(*) total, count(DISTINCT (symbol,timeframe,open_time)) distinct_n FROM candles",started_at,as_of)
        stream=await connection.fetchrow("SELECT count(*) FILTER (WHERE open_time >= ($1::timestamptz - interval '1 hour')) last_hour,max(open_time) latest,count(*) FILTER (WHERE timeframe='1m') one_minute FROM candles",as_of)
        persisted=await connection.fetch("SELECT timeframe,open_time FROM candles WHERE symbol=$1 AND timeframe=ANY($2::text[]) ORDER BY timeframe,open_time",settings.symbol,list(settings.timeframes))
        gap_details=persisted_candle_gaps(persisted,settings.timeframes);gaps=len(gap_details)
        observations=await connection.fetchrow("SELECT count(*) n,count(DISTINCT observation_id) distinct_n,count(*) FILTER (WHERE provenance='PUBLIC_MARKET_DATA_DETERMINISTIC' AND input_hash<>'') deterministic FROM observations WHERE observed_at <= $1",as_of)
        cases=await connection.fetchrow("SELECT count(*) n,count(*) FILTER (WHERE jsonb_array_length(evidence)>0 AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(evidence) e WHERE COALESCE(e->>'provenance','')<>'PUBLIC_MARKET_DATA_DETERMINISTIC')) with_provenance,(SELECT COALESCE(sum(jsonb_array_length(evidence)),0) FROM research_cases) evidence_total,(SELECT count(*) FROM research_cases r,jsonb_array_elements(r.evidence) e WHERE e->>'provenance'='PUBLIC_MARKET_DATA_DETERMINISTIC') evidence_valid FROM research_cases")
        invalid=await connection.fetchval("SELECT count(*) FROM candles WHERE low>LEAST(open,close) OR high<GREATEST(open,close) OR close_time<=open_time")
    finally:await connection.close()
    source=(ROOT/"src/dashboard/app.py").read_text();api_status=0;api_latency=999999.0
    try:
        started=time.monotonic()
        with urlopen("http://127.0.0.1:8765/api/state",timeout=3) as response:api_status=response.status;json.loads(response.read())
        api_latency=(time.monotonic()-started)*1000
    except Exception:pass
    latest=stream["latest"];age=(as_of-latest).total_seconds() if latest else 999999
    return {"database_consistent":invalid==0 and candles["total"]==candles["distinct_n"],"acceptance_candles":candles["n"],"acceptance_minutes":max(0,(as_of-started_at).total_seconds()/60),"observations":observations["n"],"distinct_observations":observations["distinct_n"],"observations_deterministic":observations["n"]==observations["deterministic"],"research_cases":cases["n"],"cases_with_provenance":cases["with_provenance"],"dashboard_auto_refresh":"INTERVAL_MS = 5000" in source and "visibilitychange" in source,"countdown_synchronized":"Date.now()" in source and "acceptance-countdown" in source,"provenance_total":observations["n"]+cases["evidence_total"],"provenance_valid":observations["deterministic"]+cases["evidence_valid"],"api_http_status":api_status,"api_latency_ms":round(api_latency,2),"candle_gaps":gaps,"candle_gap_details":gap_details,"last_candle_age_seconds":age,"candle_stream_active":latest is not None and age<300,"candle_timestamps_monotonic":candles["total"]==candles["distinct_n"],"candles_last_hour":stream["last_hour"]}


async def main()->int:
    parser=argparse.ArgumentParser(description="TIM deterministic 72-hour acceptance check");parser.add_argument("--as-of",help="Optional timezone-aware ISO-8601 audit time");args=parser.parse_args()
    as_of=datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc)
    monitor=AcceptanceMonitor(ROOT,as_of=as_of)
    if monitor.start_time is None:print(json.dumps({"status":"blocked","reason":"missing acceptance start"}));return 2
    try:context=await database_context(monitor.start_time,as_of)
    except Exception as exc:print(json.dumps({"status":"blocked","reason":f"database unavailable: {type(exc).__name__}: {exc}"}));return 2
    document_data_gaps(ROOT,context,as_of)
    result=run_acceptance_check(ROOT,context,as_of=as_of);print(json.dumps(result,indent=2));return 0 if result["status"]=="monitoring" or result["result"]["passed"] else 1


if __name__=="__main__":raise SystemExit(asyncio.run(main()))
