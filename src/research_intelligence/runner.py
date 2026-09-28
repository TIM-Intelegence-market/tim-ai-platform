"""Read-only verified journal adapter and content-addressed research artifacts."""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from src.collection_reporting.verified import VerifiedJournal
from .engine import CONFIG, REGISTRY, analyze, resolve, digest


def iso(t): return datetime.fromtimestamp(t,timezone.utc).isoformat()


def load_collection(path):
    # Reuse the verifier without its writable constructor or recovery side effects.
    journal=object.__new__(VerifiedJournal)
    journal.db=sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro',uri=True)
    journal.db.row_factory=sqlite3.Row
    try:
        journal.contract=journal.get('contract')
        proof=journal.verify()
        if journal.get('state')!='CLOSED' or journal.get('gaps') or any(proof[k]!='PASS' for k in ('COUNTS_ACCOUNTED','ALL_UNIQUE_EVENTS_PROCESSED','DETERMINISM')):
            raise ValueError('Collection evidence failed')
        rows=[(json.loads(r['trade_json']),r['received_at']) for r in journal.db.execute('SELECT e.trade_json,r.received_at FROM events e JOIN receipts r ON e.receipt_seq=r.seq ORDER BY e.receipt_seq')]
        return journal.contract,proof,rows
    finally: journal.db.close()


def build_bars(rows,at):
    from .engine import ts
    t=ts(at)
    usable=[(r,ts(received)) for r,received in rows if ts(r['event_time'])<=t and ts(received)<=t]
    if not usable: return []
    first=min(ts(r['event_time']) for r,_ in usable); last=max(ts(r['event_time']) for r,_ in usable)
    bars=[]
    for cfg in CONFIG.values():
        seconds=cfg['seconds']; groups={}
        for r,received in usable:
            start=int(ts(r['event_time'])//seconds)*seconds
            groups.setdefault(start,[]).append((r,received))
        for start,group in sorted(groups.items()):
            prices=[r['price'] for r,_ in group]
            bars.append(dict(start=iso(start),end=iso(start+seconds),available_at=iso(max(start+seconds,max(a for _,a in group))),
              seconds=seconds,complete=start>=first and start+seconds<=last,open=prices[0],close=prices[-1],high=max(prices),low=min(prices),
              volume=sum(r['quantity'] for r,_ in group),delta=sum(r['quantity']*(-1 if r['buyer_is_maker'] else 1) for r,_ in group),provenance='VERIFIED'))
    return bars


def run(root,collection_id):
    folder=root/'artifacts/verified_collections'/collection_id
    path=folder/'journal.sqlite3'; before=digest(path.read_bytes().hex())
    contract,proof,rows=load_collection(path)
    if contract['collection_id']!=collection_id: raise ValueError('collection mismatch')
    at=max(received for _,received in rows)
    def evaluate():
        c,p,r=load_collection(path)
        bars=build_bars(r,at)
        return [analyze(h,bars,at,symbol=c['symbol']) for h in CONFIG]
    one=evaluate(); two=evaluate()
    hashes={a['horizon']:{'RUN_1_HASH':a['result_hash'],'RUN_2_HASH':b['result_hash'],'equal':a==b} for a,b in zip(one,two)}
    if not all(v['equal'] for v in hashes.values()): raise ValueError('non deterministic')
    if digest(path.read_bytes().hex())!=before: raise ValueError('journal changed')
    analysis_id='mission07-'+digest([r['result_hash'] for r in one])[:20]
    out=root/'artifacts/intelligence'/analysis_id; out.mkdir(parents=True,exist_ok=True)
    cross=resolve(one)
    def write(name,value): (out/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    for r in one: write(r['horizon'].lower()+'_analysis.json',r)
    write('cross_horizon.json',cross); write('feature_registry.json',REGISTRY); write('determinism.json',hashes)
    write('input_evidence.json',dict(collection_id=collection_id,proof=proof,as_of=at,journal_hash=before,events=len(rows),legacy_data_used=False))
    summary=['# Mission 07 — Research Market Summary',f'Collection: {collection_id}; as of {at}.','Decision: NO_TRADE. Execution and live trading DISABLED.','Legacy data quality WARN: historical ingress lineage incomplete; legacy data not loaded.']
    for r in one:
        summary.extend([f"\n## {r['horizon']}",f"Status {r['data_state']}; direction {r['direction']}; structure {r['market_structure']}; confidence {r['confidence']} (evidence score, not probability).",f"Evidence: {r['coverage']}; verified coverage {r['verified_coverage']}; legacy coverage {r['legacy_coverage']}.",f"Counterarguments / risks: {', '.join(r['contradicting_evidence'])}.",f"Invalidation: {r['invalidation']}; targets: {r['targets']}; data quality {r['data_quality']}; evidence quality {r['evidence_quality']}."])
    summary.append(f"\nCross-horizon: {cross['alignment']}; dominant context {cross['dominant_context']}; conflict {cross['conflict']}.")
    (out/'market_summary.md').write_text('\n'.join(summary)+'\n')
    (out/'technical_report.md').write_text('''# Mission 07 technical report

Offline flow: read-only SQLite → receipt-chain and native candle replay verification → as-of trade filter → complete windows → versioned features → independent horizon gates → resolver → immutable-hash reports.

Graphify architecture reference: graphify-out/.graphify_analysis.json, community 0 identifies CandleAggregator, market-data models and orderflow validation. This is an existing architecture snapshot, not a fresh index or current-code acceptance proof.

Readiness: SHORT 60 contiguous 1m bars; MID 168 contiguous 1h bars; LONG 90 contiguous daily bars. At least 80% verified bars. Legacy bars receive 50% evidence weight; no legacy history was loaded in this run. Insufficient, stale, malformed or discontinuous data cannot emit a thesis. Boundary windows are excluded. Missing hours/days are not fabricated from partial data.

Confidence: published fixed weights, component scores, coverage and evidence multipliers. Heuristic evidence score, no calibrated probability or profitability claim. Unavailable features contribute zero without weight redistribution.

Lookahead: event time, bar close time and availability must all be <= analysis time. Future or unpublished rows cannot enter features/hashes. OI/funding/orderbook feeds are unsupported and never synthesized. Passive absorption is explicitly a trade-based proxy. Price-binned volume profile, derivative context, monthly macro context and liquidation-event classification remain unsupported in version 1; LIQUIDATION_EVENT cannot be inferred from volatility alone.

Determinism: two independent read-only journal loads and full feature/engine evaluations; per-horizon hashes in determinism.json. No wall clock, random IDs, model output or network source enters analysis. No Ollama review or Omniroute call was required.

Safety: no exchange client, orders, position sizing or execution import. Existing runtime configuration untouched. These artifacts qualify a conservative research baseline only; richer feature coverage and strategy calibration remain required.
''')
    files={p.name:digest(p.read_bytes().hex()) for p in sorted(out.iterdir()) if p.name!='manifest.json'}
    write('manifest.json',dict(analysis_id=analysis_id,collection_id=collection_id,intelligence_mode='RESEARCH',files=files,hash_encoding='SHA256 of canonical JSON hex string',source_hashes={p.name:digest(p.read_bytes().hex()) for p in Path(__file__).parent.glob('*.py')},trading_actions=0,execution='DISABLED',live_trading='DISABLED'))
    return out,one,cross


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('--collection',required=True)
    args=parser.parse_args()
    output,_,_=run(Path(__file__).resolve().parents[2],args.collection)
    print(output)
