"""Mission 08: deterministic, as-of market context; no network or execution.

Callers must verify receipt lineage before assigning VERIFIED. Candle snapshots
without publication timestamps become available at their snapshot time, never
retroactively. Legacy and verified bars are never averaged or gap-filled.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
import math
from .engine import CONFIG, REGISTRY as BASE_REGISTRY, analyze, digest, ts

VERSION = '2.0.0'
REQUIREMENTS = {
    'SHORT': {'primary': {'1m': 60}, 'context': {'1h': 2}, 'profile_seconds': 3600},
    'MID': {'primary': {'1h': 168}, 'context': {'1h': 2, '4h': 2, '1d': 2}, 'profile_seconds': 604800},
    'LONG': {'primary': {'1d': 90}, 'context': {'1d': 2, '1w': 2, '1M': 2}, 'profile_seconds': 7776000},
}
FRAMES = {'1m': 60, '1h': 3600, '4h': 14400, '1d': 86400}
DERIVATIVES = ('oi', 'funding', 'liquidations')
# No observed derivative feed or storage adapter exists in this deployment.
CAPABILITIES = {k: {'available': False, 'reason': 'NO_CONFIGURED_VALIDATED_DERIVATIVE_FEED',
                    'market': 'BINANCE_USDT_PERPETUAL', 'symbol': 'BTCUSDT'} for k in DERIVATIVES}
REGISTRY = [dict(r, version=VERSION) for r in BASE_REGISTRY if r['feature_name'] not in
            ('oi', 'funding', 'volume_profile', 'cross_timeframe', 'macro_context')]
for h, cfg in REQUIREMENTS.items():
    for name in (*DERIVATIVES, 'volume_profile', 'htf_context', 'history_gate'):
        inputs = ['normalized_derivative_observations', 'source_capability'] if name in DERIVATIVES else ['timestamped_price_quantity_trades', 'coverage_minutes'] if name == 'volume_profile' else ['closed_candles']
        lookback = {'oi': '2 samples, <=300s apart, latest age <=300s',
                    'funding': '1 settled observation, age <=28800s; no future predicted rate',
                    'liquidations': 'continuous 300s observed coverage; event count may be zero',
                    'volume_profile': {'seconds': cfg['profile_seconds'], 'min_trades_per_minute': 1,
                                       'bin_width_quote': '10', 'value_area': '0.70'},
                    'htf_context': cfg['context'], 'history_gate': cfg['primary']}[name]
        REGISTRY.append(dict(feature_name=name, horizon=h, version=VERSION, inputs=inputs,
            input_sources=inputs, lookback=lookback, missing_data_behavior='MISSING; veto READY and thesis; no weight redistribution',
            quality_requirement='event/end AND available_at <= T; contiguous closed windows; explicit provenance; >=80% verified for READY',
            calculation={'volume_profile': '10 USDT floor bins; max volume POC, lower-price ties; expand contiguous value area toward higher adjacent volume, lower-price ties, until >=70%; no OHLC approximation',
                         'htf_context': 'UTC calendar-aligned full periods; latest two high/low pairs; no BOS assertion'} .get(name, 'See expansion.py; explicit bounded as-of gate')))


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def bounds(t, frame):
    d = datetime.fromtimestamp(t, timezone.utc)
    if frame in FRAMES:
        start = math.floor(t / FRAMES[frame]) * FRAMES[frame]
        return start, start + FRAMES[frame]
    d = d.replace(hour=0, minute=0, second=0, microsecond=0)
    if frame == '1w':
        d -= timedelta(days=d.weekday())
        return d.timestamp(), (d + timedelta(days=7)).timestamp()
    if frame != '1M':
        raise ValueError('unknown frame')
    d = d.replace(day=1)
    end = d.replace(year=d.year + (d.month == 12), month=1 if d.month == 12 else d.month + 1)
    return d.timestamp(), end.timestamp()


def valid_bar(b):
    return (all(type(b.get(k)) in (float, int) and math.isfinite(b[k]) for k in ('open','high','low','close','volume'))
            and b['low'] > 0 and b['low'] <= min(b['open'], b['close'])
            and b['high'] >= max(b['open'], b['close']) and b['volume'] >= 0
            and b.get('provenance') in ('VERIFIED', 'LEGACY'))


def minutes_asof(bars, at):
    """Resolve overlaps by verified precedence; reject conflicts at equal rank."""
    groups = {}
    for b in bars:
        if b.get('seconds') != 60 or not b.get('complete'):
            continue
        start, end = ts(b['start']), ts(b['end'])
        if end > ts(at) or ts(b['available_at']) > ts(at):
            continue
        if start % 60 or end - start != 60 or not valid_bar(b):
            raise ValueError('invalid minute')
        groups.setdefault(start, []).append(b)
    result = []
    for start, group in sorted(groups.items()):
        best = [b for b in group if b['provenance'] == 'VERIFIED'] or group
        # Same OHLCV with different receipt times: take latest availability.
        core = {tuple(b[k] for k in ('open','high','low','close','volume')) for b in best}
        if len(core) != 1:
            raise ValueError('conflicting minute')
        result.append(dict(max(best, key=lambda b: (ts(b['available_at']), digest(b)))))
    return result


def aggregate(minutes, frame, at):
    groups = {}
    for b in minutes_asof(minutes, at):
        start, end = bounds(ts(b['start']), frame)
        if end <= ts(at):
            groups.setdefault((start, end), []).append(b)
    output = []
    for (start, end), group in sorted(groups.items()):
        if len(group) != int((end-start)/60) or ts(group[0]['start']) != start or ts(group[-1]['end']) != end:
            continue
        if any(ts(a['end']) != ts(b['start']) for a,b in zip(group,group[1:])):
            continue
        verified_minutes = sum(b['provenance']=='VERIFIED' for b in group)
        b = dict(start=iso(start), end=iso(end), available_at=max((x['available_at'] for x in group),key=ts),
                 seconds=int(end-start), frame=frame, complete=True, open=group[0]['open'], close=group[-1]['close'],
                 high=max(x['high'] for x in group), low=min(x['low'] for x in group), volume=sum(x['volume'] for x in group),
                 provenance='VERIFIED' if verified_minutes == len(group) else 'LEGACY',
                 verified_minutes=verified_minutes, total_minutes=len(group))
        if all(x.get('delta') is not None for x in group):
            b['delta']=sum(x['delta'] for x in group)
        output.append(b)
    return output


def history(bars, required, at, frame):
    tail = bars[-required:]
    current_start = bounds(ts(at), frame)[0]
    contiguous = all(ts(a['end']) == ts(b['start']) for a,b in zip(tail, tail[1:]))
    fresh = bool(tail) and ts(tail[-1]['end']) == current_start
    n = len(tail); verified = sum(b['provenance']=='VERIFIED' for b in tail)
    enough = n == required and contiguous and fresh
    return dict(required=required, observed=n, available_total=len(bars), contiguous=contiguous, fresh=fresh,
                sufficient=enough, verified_ratio=verified/n if n else 0,
                legacy_ratio=(n-verified)/n if n else 0, evidence_multiplier=(verified+.5*(n-verified))/n if n else 0,
                readiness=enough and verified/n >= .8 if n else False)


def context(minutes, at):
    result = {}
    for frame in ('1h','4h','1d','1w','1M'):
        bars = aggregate(minutes,frame,at); gate = history(bars,2,at,frame)
        direction = 'UNKNOWN'
        if gate['sufficient']:
            a,b=bars[-2:]
            direction='BULLISH' if b['high']>a['high'] and b['low']>a['low'] else 'BEARISH' if b['high']<a['high'] and b['low']<a['low'] else 'NEUTRAL'
        result[frame]=dict(gate=gate, direction=direction, bars=bars[-2:], status='READY' if gate['readiness'] else 'PARTIAL' if bars else 'MISSING')
    return result


def volume_profile(trades, minutes, at, lookback, bin_width='10'):
    end = int(ts(at)//60)*60; start=end-lookback
    coverage=[b for b in minutes_asof(minutes,at) if start<=ts(b['start'])<end]
    buckets={}; seen={}; per_minute={}; verified_volume=Decimal(0); total=Decimal(0)
    width=Decimal(bin_width)
    if not width.is_finite() or width<=0: raise ValueError('invalid bin width')
    for r in trades:
        t=ts(r['event_time'])
        if not start<=t<end or ts(r['available_at'])>ts(at): continue
        if r.get('symbol') != 'BTCUSDT' or r.get('provenance') not in ('VERIFIED','LEGACY'):
            raise ValueError('invalid trade identity or provenance')
        p,q=Decimal(str(r['price'])),Decimal(str(r['quantity']))
        if not p.is_finite() or not q.is_finite() or p<=0 or q<=0: raise ValueError('invalid profile trade')
        identity=(r.get('source'),r['symbol'],r['trade_id'])
        if not identity[0]: raise ValueError('source required')
        semantic=(r['event_time'],p,q,r['provenance'])
        if identity in seen:
            if seen[identity]!=semantic: raise ValueError('conflicting trade id')
            continue
        seen[identity]=semantic
        index=int((p/width).to_integral_value(rounding=ROUND_FLOOR))
        buckets[index]=buckets.get(index,Decimal(0))+q
        minute=int(t//60)*60
        per_minute[minute]=per_minute.get(minute,Decimal(0))+q
        total+=q
        if r['provenance']=='VERIFIED': verified_volume+=q
    matched=(len(coverage)==lookback//60 and all(per_minute.get(int(ts(b['start'])),0)>0 and abs(float(per_minute.get(int(ts(b['start'])),0))-b['volume'])<=max(1e-9,b['volume']*1e-9) for b in coverage))
    result=dict(status='NOT_READY', coverage_complete=matched, trades=len(seen), required_minutes=lookback//60,
                observed_minutes=len(coverage), window_start=iso(start),window_end=iso(end),bin_width=str(width),
                verified_volume_ratio=float(verified_volume/total) if total else 0, legacy_volume_ratio=float(1-verified_volume/total) if total else 0,
                poc=None,vah=None,val=None,hvn=[],lvn=[],bins=[])
    if not buckets: return result
    occupied=sorted(buckets)
    if occupied[-1]-occupied[0]>100000:
        result['reason']='PRICE_BIN_SPAN_EXCEEDS_BOUND'
        return result
    keys=list(range(occupied[0],occupied[-1]+1))
    for k in keys: buckets.setdefault(k,Decimal(0))
    poc=min(keys,key=lambda k:(-buckets[k],k)); lo=hi=keys.index(poc); area=buckets[poc]
    while area<total*Decimal('.70'):
        left=buckets[keys[lo-1]] if lo else Decimal(-1)
        right=buckets[keys[hi+1]] if hi<len(keys)-1 else Decimal(-1)
        if left>=right: lo-=1; area+=left
        else: hi+=1; area+=right
    result.update(status='READY' if matched and verified_volume/total>=Decimal('.8') else 'NOT_READY',
                  poc=str(width*poc+width/2),val=str(width*keys[lo]),vah=str(width*(keys[hi]+1)),
                  value_area_fraction=float(area/total),total_volume=str(total),
                  bins=[{'low':str(width*k),'volume':str(buckets[k])} for k in keys])
    # Nodes defined over occupied neighboring bins; absent prices are not liquidity evidence.
    result['hvn']=[str(width*k+width/2) for i,k in enumerate(occupied) if 0<i<len(occupied)-1 and buckets[k]>max(buckets[occupied[i-1]],buckets[occupied[i+1]])]
    result['lvn']=[str(width*k+width/2) for i,k in enumerate(occupied) if 0<i<len(occupied)-1 and buckets[k]<min(buckets[occupied[i-1]],buckets[occupied[i+1]])]
    return result


def derivative_feature(kind, observations, capability, at):
    """Validate normalized replay contract, not an exchange ingestion adapter.

Tests may supply an available capability. Production uses deployment inventory;
no fallback probes, futures backfill, or fabricated zero-liquidation intervals.
"""
    out=dict(status='MISSING',reason=capability.get('reason','NO_ASOF_COVERAGE'), samples=0, value=None)
    if not capability.get('available'): return out
    rows=[]
    for r in observations:
        if ts(r['event_time'])>ts(at) or ts(r['available_at'])>ts(at): continue
        if (r.get('symbol')!=capability['symbol'] or r.get('market')!=capability['market']
            or r.get('provenance')!='VERIFIED' or not r.get('source')): continue
        value=r.get('value')
        if type(value) not in (float,int) or not math.isfinite(value) or (kind!='funding' and value<0): continue
        if kind=='funding' and not r.get('settled'): continue
        rows.append(r)
    rows.sort(key=lambda r:(ts(r['event_time']),ts(r['available_at']),digest(r)))
    out['samples']=len(rows)
    if kind=='liquidations' and not rows:
        if (capability.get('coverage_verified') and ts(capability['coverage_start'])<=ts(at)-300
            and ts(capability['coverage_end'])>=ts(at) and ts(capability['available_at'])<=ts(at)
            and ts(capability['coverage_end'])<=ts(capability['available_at'])):
            return dict(status='READY',reason=None,samples=0,value=0,input_hash=digest({'rows':[], 'coverage':capability}))
        return out
    if not rows: return out
    if kind=='oi':
        if len(rows)<2 or not 0<ts(rows[-1]['event_time'])-ts(rows[-2]['event_time'])<=300 or ts(at)-ts(rows[-1]['event_time'])>300: return out
        value=rows[-1]['value']-rows[-2]['value']
    elif kind=='funding':
        if ts(at)-ts(rows[-1]['event_time'])>28800: return out
        value=rows[-1]['value']
    elif kind=='liquidations':
        # An authenticated coverage interval is mandatory, including zero events.
        if not capability.get('coverage_verified') or ts(capability['coverage_start'])>ts(at)-300 or ts(capability['coverage_end'])<ts(at) or ts(capability['available_at'])>ts(at) or ts(capability['coverage_end'])>ts(capability['available_at']): return out
        value=sum(r['value'] for r in rows if ts(r['event_time'])>ts(at)-300)
    else: raise ValueError('unknown derivative feature')
    return dict(status='READY',reason=None,samples=len(rows),value=value,input_hash=digest(rows))


def evaluate(horizon, minutes, trades, at, capabilities=None, observations=None):
    minutes=minutes_asof(minutes,at)
    if horizon=='SHORT': minutes=[b for b in minutes if b['provenance']=='VERIFIED']
    cfg=REQUIREMENTS[horizon]
    frame=next(iter(cfg['primary'])); primary=minutes if frame=='1m' else aggregate(minutes,frame,at)
    result=analyze(horizon,primary,at)
    primary_gate=history(primary,CONFIG[horizon]['bars'],at,frame)
    htf=context(minutes,at)
    profile=volume_profile(trades,minutes,at,cfg['profile_seconds'])
    caps=CAPABILITIES if capabilities is None else capabilities
    derivatives={k:derivative_feature(k,(observations or {}).get(k,[]),caps[k],at) for k in DERIVATIVES}
    sufficient=primary_gate['sufficient'] and all(htf[f]['gate']['sufficient'] for f in cfg['context']) and profile['coverage_complete']
    blockers=[]
    if not primary_gate['readiness']: blockers.append('PRIMARY_HISTORY_OR_EVIDENCE_INSUFFICIENT')
    if any(not htf[f]['gate']['readiness'] for f in cfg['context']): blockers.append('HTF_HISTORY_OR_EVIDENCE_INSUFFICIENT')
    if profile['status']!='READY': blockers.append('VOLUME_PROFILE_NOT_READY')
    blockers.extend(k.upper()+'_MISSING' for k,v in derivatives.items() if v['status']!='READY')
    # Mission 07's missing quote/passive/spot-demand adapters stay explicit.
    blockers.append('MISSION07_REMAINING_SCOPE_QUOTE_PASSIVE_SPOT_DEMAND')
    result.update(strategy_version=VERSION,feature_version=VERSION,history=primary_gate,history_sufficient=sufficient,
                  htf_context=htf,volume_profile=profile,derivatives=derivatives,technical_scope_complete=False,
                  feature_registry_hash=digest(REGISTRY),requirements=cfg)
    # New missing features never boost the previous explanatory confidence.
    available=sum(d['status']=='READY' for d in derivatives.values())+(profile['status']=='READY')+sum(htf[f]['gate']['readiness'] for f in cfg['context'])
    denominator=4+len(cfg['context'])
    result['feature_coverage_multiplier']=available/denominator
    result['confidence']=round(result['confidence']*available/denominator,6)
    result['data_state']='NOT_READY' if result['data_state']=='NOT_READY' else 'LIMITED' if blockers else 'READY'
    result['direction']='NO_TRADE' if blockers else result['direction']
    result['contradicting_evidence']=sorted(set(result['contradicting_evidence']+blockers))
    result['oi_context']=derivatives['oi']
    result['funding_context']=derivatives['funding']
    result['features']['liquidation_event']=derivatives['liquidations']
    result['features']['volume_profile']=profile
    result['features']['calendar_htf']=htf
    result['input_hash']=digest({'primary':primary[-CONFIG[horizon]['bars']:],'htf':htf,'profile':profile,'derivatives':derivatives})
    result['config_hash']=digest({'requirements':REQUIREMENTS,'registry':REGISTRY,'base_config_hash':result['config_hash']})
    result.pop('result_hash',None); result['result_hash']=digest(result)
    return result
