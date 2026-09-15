"""One-shot, audited transition of an historical outbox into offline work."""
from __future__ import annotations

import argparse, asyncio, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg, websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config.settings import settings
from src.data_ingestion.binance_ws import BinanceTradeStream

MIGRATION = ROOT / "src/database/migrations/006_live_cutover_deferred.sql"

async def first_live_trade_id() -> int:
    url = f"{settings.binance_ws_url.rstrip('/')}/{settings.symbol.lower()}@aggTrade"
    async with websockets.connect(url, open_timeout=15, ping_interval=20, ping_timeout=20) as socket:
        while True:
            trade = BinanceTradeStream.parse_message(await asyncio.wait_for(socket.recv(), 15))
            if trade.symbol == settings.symbol:
                assert trade.trade_id is not None
                return trade.trade_id

async def run(apply: bool, output: Path) -> dict:
    if not apply:
        return {"status":"REFUSED","reason":"pass --apply after explicit approval","trading_actions":0}
    connection = await asyncpg.connect(settings.database_url, timeout=10, command_timeout=60)
    try:
        await connection.execute(MIGRATION.read_text())
        cursor = await connection.fetchrow("""SELECT last_aggregate_trade_id FROM ingestion_cursors
            WHERE source='BINANCE' AND market='SPOT' AND symbol=$1 AND data_type='AGG_TRADE'""", settings.symbol)
        if cursor is None or cursor["last_aggregate_trade_id"] is None:
            raise RuntimeError("no durable cursor; cutover refused")
        processing = await connection.fetchval("SELECT count(*) FROM ingestion_outbox WHERE worker_name='CANDLE_V1' AND status='PROCESSING'")
        if processing:
            raise RuntimeError("active worker lease present; stop runtime and retry")
        first_id = await first_live_trade_id()
        baseline = int(cursor["last_aggregate_trade_id"])
        if first_id <= baseline:
            raise RuntimeError("public live trade is not newer than durable cursor")
        cutover_id = hashlib.sha256(f"{settings.symbol}:{baseline}:{first_id}".encode()).hexdigest()
        manifest = {"cutover_id":cutover_id,"symbol":settings.symbol,"baseline_cursor_id":baseline,"first_live_trade_id":first_id,"approved_at":datetime.now(timezone.utc).isoformat(),"mode":"OBSERVE_ONLY","historical_policy":"DEFERRED_OFFLINE_BACKFILL","trading_actions":0}
        digest = hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        async with connection.transaction():
            deferred = await connection.fetchval("""WITH changed AS (UPDATE ingestion_outbox SET status='DEFERRED',last_error=$1,lease_expires_at=NULL,updated_at=clock_timestamp()
                WHERE worker_name='CANDLE_V1' AND status IN ('PENDING','RETRY') RETURNING 1) SELECT count(*) FROM changed""", f"deferred by live cutover {cutover_id}")
            await connection.execute("""INSERT INTO live_cutover_receipts(cutover_id,symbol,baseline_cursor_id,first_live_trade_id,deferred_outbox_count,manifest_json,manifest_hash,mode,trading_actions)
                VALUES($1,$2,$3,$4,$5,$6::jsonb,$7,'OBSERVE_ONLY',0)""",cutover_id,settings.symbol,baseline,first_id,deferred,json.dumps(manifest),digest)
        manifest.update({"deferred_outbox_count":deferred,"manifest_hash":digest,"status":"APPLIED"})
        output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
        return manifest
    finally: await connection.close()

def main() -> int:
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');p.add_argument('--output',type=Path,default=ROOT/'artifacts/operations/live_cutover.json');a=p.parse_args()
    result=asyncio.run(run(a.apply,a.output));print(json.dumps(result,sort_keys=True));return 0 if result['status']=='APPLIED' else 2
if __name__=='__main__': raise SystemExit(main())
