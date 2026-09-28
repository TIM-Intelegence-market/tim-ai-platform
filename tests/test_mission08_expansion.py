from copy import deepcopy
from datetime import datetime, timedelta, timezone
import ast
from pathlib import Path
import pytest
from src.research_intelligence.expansion import (aggregate,bounds,context,derivative_feature,evaluate,history,
    minutes_asof,volume_profile,REGISTRY,REQUIREMENTS,CAPABILITIES)

BASE=datetime(2026,1,1,tzinfo=timezone.utc)
def stamp(sec):return (BASE+timedelta(seconds=sec)).isoformat()
def minutes(n=60,provenance='VERIFIED'):
    return [dict(start=stamp(i*60),end=stamp((i+1)*60),available_at=stamp((i+1)*60),seconds=60,complete=True,
                 open=100.,high=110.,low=90.,close=100.,volume=1.,provenance=provenance) for i in range(n)]
def trades(n=60):
    return [dict(event_time=stamp(i*60+1),available_at=stamp(i*60+2),price=100.,quantity=1.,trade_id=i,
                 source='BINANCE_SPOT_AGGTRADE',symbol='BTCUSDT',provenance='VERIFIED') for i in range(n)]
def capability(**kw):return dict(available=True,symbol='BTCUSDT',market='BINANCE_USDT_PERPETUAL',**kw)
def sample(t=300,v=1,**kw):return dict(event_time=stamp(t),available_at=stamp(t),value=v,source='fixture',symbol='BTCUSDT',market='BINANCE_USDT_PERPETUAL',provenance='VERIFIED',**kw)

@pytest.mark.parametrize('kind',CAPABILITIES)
def test_missing_deployment(kind):
    assert derivative_feature(kind,[sample()],CAPABILITIES[kind],stamp(300))['status']=='MISSING'

def test_oi_available_and_stale():
    data=[sample(100,10),sample(200,14)]
    assert derivative_feature('oi',data,capability(),stamp(300))['value']==4
    assert derivative_feature('oi',data,capability(),stamp(501))['status']=='MISSING'
    assert derivative_feature('oi',[data[0],data[0]],capability(),stamp(100))['status']=='MISSING'

def test_funding_settled_only():
    assert derivative_feature('funding',[sample(settled=True,v=-.001)],capability(),stamp(300))['value']==-.001
    assert derivative_feature('funding',[sample(settled=False)],capability(),stamp(300))['status']=='MISSING'
    assert derivative_feature('funding',[sample(settled=True)],capability(),stamp(30000))['status']=='MISSING'

def test_liquidations_require_coverage_including_zero():
    cap=capability(coverage_verified=True,coverage_start=stamp(0),coverage_end=stamp(300),available_at=stamp(300))
    assert derivative_feature('liquidations',[sample()],cap,stamp(300))['value']==1
    assert derivative_feature('liquidations',[],cap,stamp(300))['value']==0
    assert derivative_feature('liquidations',[sample()],capability(),stamp(300))['status']=='MISSING'
    cap['coverage_start']=stamp(1)
    assert derivative_feature('liquidations',[],cap,stamp(300))['status']=='MISSING'

@pytest.mark.parametrize('kind',CAPABILITIES)
def test_derivative_future_and_unpublished(kind):
    cap=capability();data=[sample(100,settled=True),sample(200,settled=True)]
    expected=derivative_feature(kind,data,cap,stamp(300))
    assert derivative_feature(kind,data+[sample(999,settled=True)],cap,stamp(300))==expected
    row=sample(250,settled=True);row['available_at']=stamp(999)
    assert derivative_feature(kind,data+[row],cap,stamp(300))==expected

@pytest.mark.parametrize('change',[{'market':'SPOT'},{'symbol':'ETHUSDT'},{'provenance':'LEGACY'},{'value':float('nan')}])
def test_derivative_bad_identity(change):
    row=sample(settled=True);row.update(change)
    assert derivative_feature('funding',[row],capability(),stamp(300))['status']=='MISSING'

def test_profile_exact_ties_and_conservation():
    data=trades(3)
    for r,p in zip(data,(100,110,120)):r['price']=p
    v=volume_profile(data,minutes(3),stamp(180),180)
    assert v['status']=='READY' and v['poc']=='105' and v['val']=='100' and v['vah']=='130'
    assert v['total_volume']=='3.0' and v['value_area_fraction']==1
    assert volume_profile(list(reversed(data)),minutes(3),stamp(180),180)==v
    assert volume_profile(data+data,minutes(3),stamp(180),180)==v

def test_profile_contiguous_zero_bins():
    data=trades(3)
    for r,p in zip(data,(100,100,140)):r['price']=p
    v=volume_profile(data,minutes(3),stamp(180),180)
    assert len(v['bins'])==5 and v['val']=='100' and v['vah']=='150'

def test_profile_hvn_lvn():
    data=trades(5);bars=minutes(5)
    for r,b,p,q in zip(data,bars,(100,110,120,130,140),(1,3,1,3,1)):
        r.update(price=p,quantity=q);b['volume']=q
    v=volume_profile(data,bars,stamp(300),300)
    assert v['hvn']==['115','135'] and v['lvn']==['125']

@pytest.mark.parametrize('n',[0,1,59])
def test_profile_missing_minutes(n):
    assert volume_profile(trades(n),minutes(n),stamp(3600),3600)['status']=='NOT_READY'

def test_profile_legacy_evidence_and_volume_mismatch():
    data=trades();bars=minutes()
    for r in data:r['provenance']='LEGACY'
    for b in bars:b['provenance']='LEGACY'
    v=volume_profile(data,bars,stamp(3600),3600)
    assert v['status']=='NOT_READY' and v['legacy_volume_ratio']==1
    data[0]['quantity']=2
    assert not volume_profile(data,bars,stamp(3600),3600)['coverage_complete']

def test_profile_future_and_unknown_id():
    data=trades();v=volume_profile(data,minutes(),stamp(3600),3600)
    future=deepcopy(data[0]);future.update(event_time=stamp(9999),price=1e9)
    assert volume_profile(data+[future],minutes(),stamp(3600),3600)==v
    future=deepcopy(data[0]);future['available_at']=stamp(9999)
    assert volume_profile(data+[future],minutes(),stamp(3600),3600)==v
    bad=deepcopy(data[0]);bad['quantity']=2
    with pytest.raises(ValueError):volume_profile(data+[bad],minutes(),stamp(3600),3600)

@pytest.mark.parametrize('frame,n',[('1h',60),('4h',240),('1d',1440)])
def test_full_fixed_periods(frame,n):
    b=minutes(n);assert len(aggregate(b,frame,stamp(n*60)))==1
    del b[10];assert aggregate(b,frame,stamp(n*60))==[]
    assert aggregate(minutes(n),frame,stamp(n*60-1))==[]

@pytest.mark.parametrize('date,frame,start,end',[
    ('2026-01-04T12:00:00+00:00','1w','2025-12-29T00:00:00+00:00','2026-01-05T00:00:00+00:00'),
    ('2024-02-12T12:00:00+00:00','1M','2024-02-01T00:00:00+00:00','2024-03-01T00:00:00+00:00'),
    ('2026-12-31T12:00:00+00:00','1M','2026-12-01T00:00:00+00:00','2027-01-01T00:00:00+00:00')])
def test_calendar(date,frame,start,end):
    assert bounds(datetime.fromisoformat(date).timestamp(),frame)==(datetime.fromisoformat(start).timestamp(),datetime.fromisoformat(end).timestamp())

def test_monthly_complete_and_partial():
    b=minutes(31*1440);at=stamp(31*86400)
    assert len(aggregate(b,'1M',at))==1
    assert aggregate(b[:-1],'1M',at)==[]

def test_weekly_context_two_closed():
    b=minutes(18*1440);at=stamp(18*86400)
    c=context(b,at)
    assert c['1w']['gate']['sufficient'] and c['1w']['direction']=='NEUTRAL'
    assert c['1M']['status']=='MISSING'

def test_history_fresh_contiguous_and_weighting():
    bars=aggregate(minutes(180),'1h',stamp(10800))
    assert history(bars,2,stamp(10800),'1h')['readiness']
    assert not history([bars[0],bars[2]],2,stamp(10800),'1h')['sufficient']
    assert not history(bars,2,stamp(14400),'1h')['sufficient']
    bars[-1]['provenance']='LEGACY'
    g=history(bars,2,stamp(10800),'1h');assert g['sufficient'] and not g['readiness'] and g['evidence_multiplier']==.75

def test_mixed_aggregate_conservative_provenance():
    b=minutes();b[0]['provenance']='LEGACY'
    a=aggregate(b,'1h',stamp(3600))[0]
    assert a['provenance']=='LEGACY' and a['verified_minutes']==59

def test_overlap_and_snapshot_availability():
    b=minutes();legacy=deepcopy(b);legacy[0]['provenance']='LEGACY';legacy[0]['volume']=20
    assert minutes_asof(b+legacy,stamp(3600))==b
    legacy=deepcopy(b[0]);legacy['volume']=20
    with pytest.raises(ValueError):minutes_asof(b+[legacy],stamp(3600))
    for r in b:r['available_at']=stamp(4000)
    assert minutes_asof(b,stamp(3600))==[]

@pytest.mark.parametrize('h',REQUIREMENTS)
def test_engine_gates_and_determinism(h):
    b=minutes();t=trades();r=evaluate(h,b,t,stamp(3600))
    assert r==evaluate(h,deepcopy(b),list(reversed(t)),stamp(3600))
    assert r['direction']=='NO_TRADE' and r['data_state']!='READY' and not r['history_sufficient']
    assert r['execution']==r['live_trading']=='DISABLED' and r['trading_actions']==0
    b.extend(minutes(70)[60:]);t.extend(trades(70)[60:])
    assert evaluate(h,b,t,stamp(3600))==r

def test_registry_contract():
    for h in REQUIREMENTS:
        new=[r for r in REGISTRY if r['horizon']==h and r['feature_name'] in (*CAPABILITIES,'volume_profile','htf_context','history_gate')]
        assert len(new)==6
        assert all(all(k in r for k in ('version','inputs','lookback','missing_data_behavior','quality_requirement')) for r in new)

def test_research_has_no_network_or_execution_imports():
    for name in ('expansion.py','mission08.py'):
        tree=ast.parse((Path('src/research_intelligence')/name).read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Import): names=[n.name for n in node.names]
            elif isinstance(node,ast.ImportFrom):names=[node.module or '']
            else:continue
            assert not any(any(part in name for part in ('execution','exchange','ccxt','requests','websocket','urllib','socket')) for name in names)

def test_invalid_legacy_rejected_without_repair():
    from src.research_intelligence.mission08 import validated_legacy
    bars=minutes();bars[5]['open']=80
    snapshot={'bars':bars,'snapshot_at':stamp(3600)}
    accepted,rejected=validated_legacy(snapshot)
    assert len(accepted)==59 and len(rejected)==1 and rejected[0]['bar']==bars[5]
    assert aggregate(accepted,'1h',stamp(3600))==[]

def test_monthly_context_two_full_periods():
    bars=minutes(59*1440)
    c=context(bars,stamp(59*86400))
    assert c['1M']['gate']['sufficient'] and c['1M']['direction']=='NEUTRAL'
    assert c['1M']['bars'][0]['seconds']==31*86400
    assert c['1M']['bars'][1]['seconds']==28*86400

def test_short_rejects_legacy_substitution():
    r=evaluate('SHORT',minutes(180,'LEGACY'),trades(180),stamp(10800))
    assert r['coverage']['bars']==0 and not r['legacy_data_used'] and r['direction']=='NO_TRADE'

def test_zero_volume_is_not_observed_trade_coverage():
    b=minutes()
    for r in b:r['volume']=0
    p=volume_profile([],b,stamp(3600),3600)
    assert p['status']=='NOT_READY' and not p['coverage_complete']

def test_liquidation_future_coverage_not_evidence():
    cap=capability(coverage_verified=True,coverage_start=stamp(0),coverage_end=stamp(900),available_at=stamp(300))
    assert derivative_feature('liquidations',[],cap,stamp(300))['status']=='MISSING'
    assert derivative_feature('liquidations',[sample()],cap,stamp(300))['status']=='MISSING'
