"""Bounded SELECT-only legacy candle snapshot; no retroactive availability."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import asyncpg
from config.settings import settings

async def snapshot(output):
    connection=await asyncpg.connect(settings.database_url,timeout=5,command_timeout=30,
                                    server_settings={'default_transaction_read_only':'on'})
    try:
        async with connection.transaction(isolation='repeatable_read',readonly=True):
            assert await connection.fetchval('SHOW transaction_read_only')=='on'
            at=await connection.fetchval('SELECT transaction_timestamp()')
            inventory=[r['table_name'] for r in await connection.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name ~ '(funding|open_interest|liquidation)'")]
            counts=[dict(r) for r in await connection.fetch('SELECT timeframe,count(*) n,min(open_time) first,max(close_time) last FROM candles WHERE symbol=$1 GROUP BY timeframe','BTCUSDT')]
            # No silent backfill: read only existing last 120 days, 180000-row cap.
            rows=await connection.fetch("""SELECT open_time,close_time,open,high,low,close,volume,trade_count
                FROM candles WHERE symbol=$1 AND timeframe='1m' AND closed=true
                AND open_time >= $2::timestamptz - interval '120 days' AND close_time <= $2
                ORDER BY open_time DESC LIMIT 180001""",'BTCUSDT',at)
            if len(rows)>180000: raise RuntimeError('snapshot row bound exceeded')
            bars=[dict(start=r['open_time'].isoformat(),end=r['close_time'].isoformat(),available_at=at.isoformat(),
                       seconds=60,complete=True,provenance='LEGACY',**{k:r[k] for k in ('open','high','low','close','volume')}) for r in reversed(rows)]
            payload=dict(snapshot_at=at.isoformat(),transaction_read_only=True,scope='Existing closed BTCUSDT 1m candles; last 120d; <=180000 rows',
                         publication_time_policy='Unknown historic publication time; available only at snapshot_at',
                         legacy_evidence_status='INCOMPLETE',derivative_tables=inventory,inventory=counts,bars=bars)
            output.parent.mkdir(parents=True,exist_ok=True)
            with output.open('x') as f: json.dump(payload,f,indent=2,default=str)
    finally: await connection.close()

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    asyncio.run(snapshot(p.parse_args().output))
