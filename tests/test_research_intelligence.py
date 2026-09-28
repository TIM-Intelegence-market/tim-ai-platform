from copy import deepcopy
from datetime import datetime,timezone,timedelta
import socket
import pytest
from src.research_intelligence.engine import CONFIG, REGISTRY, analyze, features, structure, resolve
from src.research_intelligence.runner import build_bars, run

BASE=datetime(2026,1,1,tzinfo=timezone.utc)
def stamp(i): return (BASE+timedelta(seconds=i)).isoformat()
def dataset(h='SHORT',n=None):
    sec=CONFIG[h]['seconds']; n=n or CONFIG[h]['bars']
    return [dict(start=stamp(i*sec),end=stamp((i+1)*sec),available_at=stamp((i+1)*sec),seconds=sec,complete=True,
                 open=100.,high=110.,low=90.,close=101.,volume=100.,delta=20.,provenance='VERIFIED') for i in range(n)]
def analyze_b(b,h='SHORT'): return analyze(h,b,b[-1]['end'])

@pytest.mark.parametrize('h',CONFIG)
def test_insufficient(h):
    r=analyze_b(dataset(h,3),h)
    assert r['direction']=='NO_TRADE' and r['data_state']=='LIMITED'
    assert analyze(h,[],stamp(100))['data_state']=='NOT_READY'

def test_valid_short():
    r=analyze_b(dataset()); assert r['data_state']=='READY'
    assert r['direction']=='NO_TRADE' # Neutral structure and unavailable quotes are vetoes.

@pytest.mark.parametrize('sign,expected',[(1,'BULLISH'),(-1,'BEARISH'),(0,'NEUTRAL')])
def test_structure(sign,expected):
    b=dataset(n=2); b[-1].update(high=110+sign,low=90+sign)
    assert structure(b)==expected

def test_sweep_and_absorption():
    b=dataset(); b[-1].update(low=89.,open=100.,close=101.,delta=-80.)
    f=features(b); assert f['sweep']=='BULLISH' and f['absorption']=='PROXY'

def test_conflicting_evidence():
    b=dataset(); b[-1].update(high=111.,low=91.,delta=-80.)
    assert 'CONFLICTING_ORDERFLOW' in analyze_b(b)['contradicting_evidence']

def test_legacy_penalty_and_verified_weight():
    b=dataset(); v=analyze_b(b)
    for x in b: x['provenance']='LEGACY'
    l=analyze_b(b)
    assert l['confidence']<v['confidence'] and l['evidence_quality']=='WARN' and l['data_state']=='LIMITED'
    assert l['verified_data_ratio']==0 and l['legacy_data_ratio']==1

@pytest.mark.parametrize('change',[{'high':0},{'close':float('nan')},{'provenance':'UNKNOWN'},{'delta':101.}])
def test_data_quality(change):
    b=dataset(); b[-1].update(change)
    r=analyze_b(b); assert r['data_quality']=='FAIL' and r['direction']=='NO_TRADE'

def test_gap_and_stale():
    b=dataset(); del b[2]
    assert 'COVERAGE_GAP' in analyze_b(b)['contradicting_evidence']
    assert 'STALE_DATA' in analyze('SHORT',dataset(),stamp(10000))['contradicting_evidence']

def test_no_lookahead():
    b=dataset(); at=b[-1]['end']; original=analyze('SHORT',b,at)
    future=deepcopy(b[-1]); future.update(start=stamp(3600),end=stamp(3660),available_at=stamp(3660),close=1e9)
    assert analyze('SHORT',b+[future],at)==original
    b[-1]['quote']=dict(timestamp=stamp(9999),available_at=stamp(9999))
    assert analyze('SHORT',b,at)==original

def test_unpublished_and_partial():
    b=dataset(); b[-1]['available_at']=stamp(9999)
    assert analyze('SHORT',b,stamp(3600))['coverage']['bars']==59
    b[-1]['available_at']=stamp(3600); b[-1]['complete']=False
    assert analyze('SHORT',b,stamp(3600))['coverage']['bars']==59

def test_determinism_and_config_binding():
    b=dataset(); assert analyze_b(b)==analyze_b(deepcopy(b))
    old=analyze_b(b)['result_hash']; b[0]['volume']+=1
    assert analyze_b(b)['result_hash']!=old

@pytest.mark.parametrize('directions,alignment',[(['LONG']*3,'ALIGNED'),(['LONG','SHORT','LONG'],'CONFLICT')])
def test_resolver(directions,alignment):
    results=[analyze_b(dataset(h),h) for h in CONFIG]
    for r,d in zip(results,directions): r['direction']=d; r['market_structure']='BULLISH' if d=='LONG' else 'BEARISH'
    before=deepcopy(results); out=resolve(results)
    assert out['alignment']==alignment and results==before
    assert out['countertrend_warning']==(alignment=='CONFLICT')

@pytest.mark.parametrize('kind',['HIGH_VOLATILITY','LOW_VOLATILITY','COMPRESSION','EXPANSION','RANGE','TRENDING_UP','TRENDING_DOWN'])
def test_regimes(kind):
    b=dataset()
    for x in b: x.update(high=101.,low=99.,close=100.,open=100.)
    if kind=='HIGH_VOLATILITY':
        for x in b: x.update(high=110.,low=90.)
    if kind=='LOW_VOLATILITY':
        for x in b: x.update(high=100.001,low=99.999)
    if kind=='COMPRESSION': b[-1].update(high=100.1,low=99.9)
    if kind=='EXPANSION': b[-1].update(high=105.,low=95.)
    if kind=='TRENDING_UP': b[-1].update(high=102.,low=100.,close=101.)
    if kind=='TRENDING_DOWN': b[-1].update(high=100.,low=98.,close=99.)
    assert features(b)['regime']==kind

def test_thesis_requires_invalidation_targets_and_quotes():
    b=dataset(); b[-1].update(open=94.,close=95.,high=110.,low=89.)
    b[-2].update(high=109.,low=88.)
    b[-1]['quote']=dict(timestamp=b[-1]['end'],available_at=b[-1]['end'],spread_bps=1,slippage_bps=1,depth_quote=200000)
    r=analyze_b(b)
    assert r['direction']=='LONG' and r['invalidation'] and r['targets'] and r['expected_r_multiple']>=2
    b[-1]['quote']['spread_bps']=100
    assert analyze_b(b)['direction']=='NO_TRADE'

def test_no_execution(monkeypatch):
    def deny(*a,**k): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket,'socket',deny)
    for h in CONFIG:
        r=analyze_b(dataset(h),h)
        assert r['trading_actions']==0 and r['execution']=='DISABLED' and r['live_trading']=='DISABLED'

def test_registry():
    assert len(REGISTRY)==42
    assert all(set(('feature_name','version','horizon','input_sources','lookback','calculation','missing_data_behavior','output_type','quality_requirement'))<=set(r) for r in REGISTRY)

def test_trade_future_filter():
    rows=[(dict(event_time=stamp(t),price=100.,quantity=1.,buyer_is_maker=False),stamp(t)) for t in (1,60,120,180)]
    before=build_bars(rows,stamp(180))
    rows.append((dict(event_time=stamp(240),price=1e9,quantity=1.,buyer_is_maker=False),stamp(240)))
    assert build_bars(rows,stamp(180))==before

def test_order_block_and_imbalance():
    b=dataset(n=3); b[-2].update(open=105.,close=95.)
    b[-1].update(open=112.,low=111.,high=115.,close=114.)
    f=features(b)
    assert f['structure']=='BOS_BULLISH' and f['order_blocks']['status']=='CANDIDATE'
    assert f['imbalance']['direction']=='BULLISH'


def test_invalidations_and_targets_veto():
    b=dataset(); b[-1].update(open=112.,close=114.,low=111.,high=115.)
    r=analyze_b(b)
    assert r['direction']=='NO_TRADE' and 'TARGET_UNAVAILABLE' in r['contradicting_evidence']


def test_no_exchange_imports():
    import ast
    from pathlib import Path
    forbidden=('requests','httpx','socket','ccxt','binance','src.execution')
    for path in Path('src/research_intelligence').glob('*.py'):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            names=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
            assert not any(n.startswith(forbidden) for n in names)


def test_real_collection_repeated_offline_run(tmp_path,monkeypatch):
    from pathlib import Path
    import shutil
    import hashlib
    source=Path('artifacts/verified_collections/verified-btcusdt-20260906T115023Z/journal.sqlite3')
    if not source.exists(): pytest.skip('local Mission 06 evidence not distributed with source')
    destination=tmp_path/'artifacts/verified_collections'/source.parent.name
    destination.mkdir(parents=True); shutil.copyfile(source,destination/source.name)
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    def deny(*args,**kwargs): raise AssertionError('network access forbidden')
    monkeypatch.setattr(socket,'socket',deny)
    out,first,cross=run(tmp_path,source.parent.name)
    _,second,_=run(tmp_path,source.parent.name)
    assert first==second and all(r['direction']=='NO_TRADE' for r in first)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    assert (out/'manifest.json').exists()
