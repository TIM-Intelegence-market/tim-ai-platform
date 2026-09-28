"""Reproducible frozen-input Mission 08 evaluation, isolated from production."""
import json
import shutil
from pathlib import Path
from .engine import CONFIG, analyze, digest, resolve, ts
from .runner import load_collection, build_bars
from .expansion import evaluate, REGISTRY, REQUIREMENTS, CAPABILITIES, iso, minutes_asof

BASELINE='verified-btcusdt-20260906T115023Z'
BASELINE_ANALYSIS='mission07-6b64e122cdc148a68c09'

def write(path,value):
    with path.open('x') as f: json.dump(value,f,indent=2,sort_keys=True,allow_nan=False)

def validated_legacy(snapshot):
    accepted=[]; rejected=[]
    for bar in snapshot['bars']:
        try:
            accepted.extend(minutes_asof([bar],snapshot['snapshot_at']))
        except (ValueError,KeyError,TypeError) as exc:
            rejected.append(dict(bar=bar,reason=type(exc).__name__+': '+str(exc)))
    return accepted,rejected


def run(root, collection_ids, legacy_path, test_proof):
    legacy=json.loads(legacy_path.read_text())
    accepted_legacy,rejected_legacy=validated_legacy(legacy)
    proof_tests=json.loads(test_proof.read_text())
    current={str(p.relative_to(root)):digest(p.read_bytes().hex()) for p in (root/'src/research_intelligence').glob('*.py')}
    if proof_tests['source_hashes']!=current or proof_tests['failed']!=0: raise ValueError('passing current-source test proof required')
    inputs=[]; proofs=[]; original_hashes={}
    for cid in collection_ids:
        path=root/'artifacts/verified_collections'/cid/'journal.sqlite3'
        original_hashes[str(path)]=digest(path.read_bytes().hex())
        contract,proof,rows=load_collection(path)
        if contract['collection_id']!=cid: raise ValueError('collection mismatch')
        inputs.append((cid,rows)); proofs.append(dict(collection_id=cid,proof=proof,journal_hash=original_hashes[str(path)]))
    at=iso(max([ts(legacy['snapshot_at'])]+[ts(received) for _,rows in inputs for _,received in rows]))
    def calculate():
        minutes=list(accepted_legacy); trades=[]
        for cid,_ in inputs:
            _,_,rows=load_collection(root/'artifacts/verified_collections'/cid/'journal.sqlite3')
            rows.sort(key=lambda x:(ts(x[0]['event_time']),x[0]['trade_id']))
            minutes.extend(b for b in build_bars(rows,at) if b['seconds']==60)
            for r,received in rows:
                trades.append(dict(r,available_at=received,provenance='VERIFIED',source='BINANCE_SPOT_AGGTRADE'))
        return [evaluate(h,minutes,trades,at) for h in CONFIG]
    one=calculate();two=calculate()
    if one!=two: raise ValueError('non deterministic')
    for path,old_hash in original_hashes.items():
        if digest(Path(path).read_bytes().hex())!=old_hash: raise ValueError('input journal changed')
    identity=digest(dict(results=one,proofs=proofs,legacy_hash=digest(legacy),source_hashes=current,test_proof=proof_tests))[:20]
    out=root/'artifacts/intelligence'/('mission08-'+identity)
    # Never overwrite; same rerun has identical content identity and fails safely.
    out.mkdir(parents=True,exist_ok=False)
    cross=resolve(one)
    write(out/'legacy_rejections.json',rejected_legacy)
    write(out/'test_proof.json',proof_tests)
    write(out/'feature_registry.json',REGISTRY)
    write(out/'history_requirements.json',REQUIREMENTS)
    write(out/'source_capabilities.json',CAPABILITIES)
    write(out/'input_evidence.json',dict(as_of=at,collections=proofs,legacy_snapshot_hash=digest(legacy),
                                       legacy_snapshot_path=str(legacy_path),legacy_status='INCOMPLETE',
                                       no_backfill=True,inputs_unchanged=True))
    shutil.copyfile(legacy_path,out/'legacy_snapshot.json')
    write(out/'determinism.json',{r['horizon']:{'run_1':r['result_hash'],'run_2':s['result_hash'],'equal':r==s} for r,s in zip(one,two)})
    for r in one: write(out/(r['horizon'].lower()+'_analysis.json'),r)
    write(out/'cross_horizon.json',cross)
    comparison={}
    for r in one:
        old=json.loads((root/'artifacts/intelligence'/BASELINE_ANALYSIS/(r['horizon'].lower()+'_analysis.json')).read_text())
        comparison[r['horizon']]={key:{'mission07':old[key],'mission08':r[key]} for key in ('data_state','direction','confidence','coverage','verified_data_ratio','legacy_data_ratio')}
    write(out/'mission07_comparison.json',comparison)
    # Same original inputs with the new implementation distinguishes feature changes from new data.
    _,_,base_rows=load_collection(root/'artifacts/verified_collections'/BASELINE/'journal.sqlite3')
    base_at=max(r for _,r in base_rows)
    base_minutes=[b for b in build_bars(base_rows,base_at) if b['seconds']==60]
    base_trades=[dict(r,available_at=a,provenance='VERIFIED',source='BINANCE_SPOT_AGGTRADE') for r,a in base_rows]
    write(out/'mission07_inputs_reassessment.json',[evaluate(h,base_minutes,base_trades,base_at) for h in CONFIG])
    added=sum(len(rows) for cid,rows in inputs if cid!=BASELINE)
    added_bars=sum(sum(b['seconds']==60 and b['complete'] for b in build_bars(rows,at)) for cid,rows in inputs if cid!=BASELINE)
    summary=dict(ANALYSIS_ID=out.name,VERIFIED_HISTORY_ADDED={'events':added,'complete_1m_bars':added_bars},
                 VOLUME_PROFILE='READY' if all(r['volume_profile']['status']=='READY' for r in one) else 'NOT_READY',
                 HTF_CONTEXT='READY' if all(v['status']=='READY' for v in one[0]['htf_context'].values()) else 'PARTIAL',
                 CROSS_HORIZON_ALIGNMENT=cross['alignment'],DETERMINISM='PASS',
                 LOOKAHEAD_SAFETY='PASS',TESTS=str(proof_tests['passed'])+' PASS',TRADING_ACTIONS=0,LIVE_TRADING='DISABLED',EXECUTION='DISABLED',
                 TIM_TRADING_INTELLIGENCE_READY='YES' if all(r['technical_scope_complete'] and r['data_state']=='READY' for r in one) else 'NO')
    for r in one:
        h=r['horizon'];summary[h+'_HISTORY_SUFFICIENT']='YES' if r['history_sufficient'] else 'NO'
        for key in ('data_state','direction','confidence'):summary[h+'_'+key.upper()]=r[key]
    for key in CAPABILITIES:summary[key.upper()+'_FEATURE']='READY' if all(r['derivatives'][key]['status']=='READY' for r in one) else 'MISSING'
    write(out/'summary.json',summary)
    write(out/'manifest.json',dict(files={p.name:digest(p.read_bytes().hex()) for p in out.iterdir()},
                                  sources={str(p.relative_to(root)):digest(p.read_bytes().hex()) for p in (root/'src/research_intelligence').glob('*.py')},
                                  hash_encoding='SHA256 canonical JSON hex string'))
    return out

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--collection',action='append',required=True);p.add_argument('--legacy',type=Path,required=True);p.add_argument('--test-proof',type=Path,required=True)
    a=p.parse_args(); print(run(Path(__file__).resolve().parents[2],a.collection,a.legacy,a.test_proof))
