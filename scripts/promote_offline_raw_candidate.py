"""Promote one complete, hashed offline raw candidate without touching live outbox/cursor."""
from __future__ import annotations
import argparse, asyncio, hashlib, json, sys
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from config.settings import settings
from src.database.connection import Database

async def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--candidate",type=Path,required=True); p.add_argument("--batch-size",type=int,default=5000); args=p.parse_args()
    manifest=json.loads((args.candidate/"manifest.json").read_text())
    if manifest.get("status")!="COMPLETE" or manifest.get("mode")!="OFFLINE_CANDIDATE_ONLY": raise SystemExit("candidate is not complete")
    payload=args.candidate/"agg_trades.jsonl"; digest=hashlib.sha256(); count=0
    with payload.open("rb") as handle:
        for block in iter(lambda:handle.read(1024*1024),b""): digest.update(block)
    if digest.hexdigest()!=manifest["sha256"]: raise SystemExit("candidate hash mismatch")
    db=Database(settings.database_url); await db.connect()
    try:
        async with db.acquire() as con:
            batch=[]
            with payload.open() as handle:
                for line in handle:
                    x=json.loads(line); batch.append((x["symbol"],x["aggregate_trade_id"],datetime.fromisoformat(x["event_time"]),float(x["price"]),float(x["quantity"]),x["buyer_is_maker"],"BINANCE_SPOT_AGGTRADE")); count+=1
                    if len(batch)>=args.batch_size:
                        async with con.transaction(): await con.executemany("""INSERT INTO agg_trades(symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker,source) VALUES($1,$2,$3::timestamptz,$4,$5,$6,$7) ON CONFLICT(symbol,aggregate_trade_id) DO NOTHING""",batch)
                        batch=[]
            if batch:
                async with con.transaction(): await con.executemany("""INSERT INTO agg_trades(symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker,source) VALUES($1,$2,$3::timestamptz,$4,$5,$6,$7) ON CONFLICT(symbol,aggregate_trade_id) DO NOTHING""",batch)
            if count!=manifest["records"]: raise RuntimeError("candidate count mismatch")
            async with con.transaction():
                covered=await con.fetchval("SELECT count(*) FROM agg_trades WHERE symbol=$1 AND aggregate_trade_id BETWEEN $2 AND $3",manifest["symbol"],manifest["from_id"],manifest["to_id"])
                if covered!=manifest["records"]: raise RuntimeError("post-import coverage mismatch")
                resolved=await con.fetchval("""WITH changed AS (UPDATE ingestion_gap_incidents g SET status='RESOLVED',resolved_at=clock_timestamp(),updated_at=clock_timestamp(),details=g.details || $4::jsonb WHERE g.symbol=$1 AND g.status IN ('OPEN','CATCHING_UP') AND g.missing_from_id >= $2 AND g.missing_to_id <= $3 AND (SELECT count(*) FROM agg_trades t WHERE t.symbol=g.symbol AND t.aggregate_trade_id BETWEEN g.missing_from_id AND g.missing_to_id)=g.missing_to_id-g.missing_from_id+1 RETURNING 1) SELECT count(*) FROM changed""",manifest["symbol"],manifest["from_id"],manifest["to_id"],json.dumps({"offline_candidate_sha256":manifest["sha256"],"promoted_at":"verified"}))
        receipt={"status":"PROMOTED","range_id":manifest["range_id"],"records":manifest["records"],"sha256":manifest["sha256"],"resolved_gap_incidents":resolved,"live_outbox_mutations":0,"live_cursor_mutations":0,"trading_actions":0}
        (args.candidate/"promotion_receipt.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
        print(json.dumps(receipt,sort_keys=True)); return 0
    finally: await db.close()
if __name__=="__main__": raise SystemExit(asyncio.run(main()))
