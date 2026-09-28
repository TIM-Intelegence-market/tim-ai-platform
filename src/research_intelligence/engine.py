"""Versioned conservative research rules; confidence is evidence, not probability."""
from __future__ import annotations
import hashlib
import json
import math
from datetime import datetime

VERSION = '1.0.0'
CONFIG = {
    'SHORT': {'seconds': 60, 'bars': 60, 'duration': 'minutes to hours'},
    'MID': {'seconds': 3600, 'bars': 168, 'duration': 'hours to days'},
    'LONG': {'seconds': 86400, 'bars': 90, 'duration': 'days to weeks'},
}
WEIGHTS = dict(structure=20, liquidity=10, orderflow=10, volume=10,
               volatility=10, oi=5, funding=5, cross_timeframe=10,
               data_quality=10, evidence_quality=10)
CALCULATIONS = {
 'structure': 'Compare latest close and high/low with prior 20 bars; BOS beyond prior range; otherwise higher highs/lows or lower highs/lows.',
 'liquidity': 'Latest low below prior 20 lows with close reclaim => bullish sweep; inverse => bearish sweep. Liquidity pools are prior extrema.',
 'orderflow': 'Sum signed base quantity (buyer maker negative); delta/volume. Absorption proxy: abs(delta ratio)>=0.6 and body/range<=0.2; never proof of passive orders.',
 'volume': 'Latest volume divided by prior 20-bar mean; volume profile is unavailable without price-binned trades.',
 'volatility': 'Mean high-low/close over 20 bars; latest range divided by that mean.',
 'oi': 'Unavailable: no validated derivative OI adapter in v1.',
 'funding': 'Unavailable: no validated derivative funding adapter in v1.',
 'cross_timeframe': 'Aggregate complete groups of 4 primary bars; compare latest two high/low pairs.',
 'order_blocks': 'Last opposite-body candle before close-confirmed BOS; candidate zone only, never proof of institutional orders.',
 'imbalance': 'Three-bar fair-value gap when current low exceeds high two bars ago or inverse.',
 'volume_profile': 'Unavailable without price-binned volume inputs; OHLC volume is not a profile.',
 'macro_context': 'Higher-timeframe structure proxy; no macroeconomic, spot demand or accumulation proof from OHLC.',
 'data_quality': 'OHLC/finite/volume/provenance validation and contiguous closed-window coverage.',
 'evidence_quality': 'Verified bar fraction + 0.5 * legacy bar fraction; unknown evidence rejected.',
}
REGISTRY = [dict(feature_name=k, version=VERSION, horizon=h,
 input_sources=['closed_candles', 'signed_trade_volume'] if k=='orderflow' else ['closed_candles'],
 lookback=CONFIG[h]['bars'], calculation=v, missing_data_behavior='UNAVAILABLE; zero contribution; core failure vetoes thesis',
 output_type='explainable_context', quality_requirement='as_of and available_at <= T; complete bars; explicit provenance')
 for h in CONFIG for k,v in CALCULATIONS.items()]


def normalized(value):
    if isinstance(value,float) and not math.isfinite(value): return {'invalid_numeric':str(value)}
    if isinstance(value,dict): return {k:normalized(v) for k,v in value.items()}
    if isinstance(value,list): return [normalized(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(json.dumps(normalized(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def ts(value):
    d = datetime.fromisoformat(value)
    if d.tzinfo is None:
        raise ValueError('timezone required')
    return d.timestamp()


def select(bars, at, seconds):
    """Filter before calculating features, including publication and close times."""
    t = ts(at)
    return sorted([dict(b) for b in bars if ts(b['end']) <= t and ts(b['available_at']) <= t
                   and b['seconds'] == seconds and b.get('complete') is True], key=lambda b:b['end'])


def structure(bars):
    if len(bars)<2: return 'UNKNOWN'
    a,b=bars[-2:]
    prior=bars[-21:-1]
    if b['close']>max(x['high'] for x in prior): return 'BOS_BULLISH'
    if b['close']<min(x['low'] for x in prior): return 'BOS_BEARISH'
    if b['high']>a['high'] and b['low']>a['low']: return 'BULLISH'
    if b['high']<a['high'] and b['low']<a['low']: return 'BEARISH'
    return 'NEUTRAL'


def bias(s):
    return 1 if 'BULLISH' in s else -1 if 'BEARISH' in s else 0


def features(bars):
    if len(bars)<2: return dict(structure='UNKNOWN', sweep='NONE', delta_ratio=None, absorption='UNAVAILABLE', volume_ratio=None, range_ratio=None, volatility=None, cross_timeframe='UNKNOWN', regime='UNKNOWN')
    b=bars[-1]; prior=bars[-21:-1]
    low=min(x['low'] for x in prior); high=max(x['high'] for x in prior)
    bull=b['low']<low and b['close']>low
    bear=b['high']>high and b['close']<high
    sweep='CONFLICT' if bull and bear else 'BULLISH' if bull else 'BEARISH' if bear else 'NONE'
    delta=b.get('delta'); dr=delta/b['volume'] if delta is not None and b['volume'] else None
    span=b['high']-b['low']; body=abs(b['close']-b['open'])
    absorption='PROXY' if dr is not None and abs(dr)>=.6 and span>0 and body/span<=.2 else 'NONE' if dr is not None else 'UNAVAILABLE'
    mean=sum(x['volume'] for x in prior)/len(prior)
    vol=sum((x['high']-x['low'])/x['close'] for x in prior)/len(prior)
    rr=(span/b['close'])/vol if vol else None
    s=structure(bars)
    grouped=[]
    for i in range(0,len(bars)-3,4):
        g=bars[i:i+4]; grouped.append(dict(open=g[0]['open'],close=g[-1]['close'],high=max(x['high'] for x in g),low=min(x['low'] for x in g)))
    regime=('HIGH_VOLATILITY' if vol>.03 else 'LOW_VOLATILITY' if vol<.0001 else
            'EXPANSION' if rr is not None and rr>2 else 'COMPRESSION' if rr is not None and rr<.5 else
            'TRENDING_UP' if bias(s)>0 else 'TRENDING_DOWN' if bias(s)<0 else 'RANGE')
    order_block=None
    if s.startswith('BOS_'):
        opposite=[x for x in prior if (x['close']-x['open'])*bias(s)<0]
        if opposite:
            x=opposite[-1]; order_block={'zone':[x['low'],x['high']],'status':'CANDIDATE','basis':'last opposite candle before confirmed BOS'}
    imbalance=None
    if len(bars)>=3:
        earlier=bars[-3]
        if b['low']>earlier['high']: imbalance={'direction':'BULLISH','zone':[earlier['high'],b['low']]}
        elif b['high']<earlier['low']: imbalance={'direction':'BEARISH','zone':[b['high'],earlier['low']]}
    return dict(structure=s,sweep=sweep,delta_ratio=dr,absorption=absorption,volume_ratio=b['volume']/mean if mean else None,
                range_ratio=rr,volatility=vol,cross_timeframe=structure(grouped),regime=regime,
                range_low=low,range_high=high,liquidation_event='UNAVAILABLE',order_blocks=order_block,
                imbalance=imbalance,spot_vs_perp='UNAVAILABLE',accumulation_distribution='UNCONFIRMED')


def analyze(horizon, bars, at, symbol='BTCUSDT', market='SPOT'):
    cfg=CONFIG[horizon]; eligible=select(bars,at,cfg['seconds']); data=eligible[-cfg['bars']:]
    errors=[]
    for b in data:
        if (not all(isinstance(b.get(k),(float,int)) and math.isfinite(b[k]) for k in ('open','high','low','close','volume'))
            or b['low']<=0 or b['low']>min(b['open'],b['close']) or b['high']<max(b['open'],b['close']) or b['volume']<0
            or b.get('provenance') not in ('VERIFIED','LEGACY') or ts(b['end'])-ts(b['start'])!=cfg['seconds']
            or (b.get('delta') is not None and (not math.isfinite(b['delta']) or abs(b['delta'])>b['volume']))): errors.append('INVALID_CORE_DATA')
    if any(ts(b['start'])!=ts(a['end']) for a,b in zip(data,data[1:])): errors.append('COVERAGE_GAP')
    if data and ts(at)-ts(data[-1]['end'])>cfg['seconds']: errors.append('STALE_DATA')
    for b in data:
        q=b.get('quote')
        if q and (ts(q['timestamp'])>ts(at) or ts(q['available_at'])>ts(at)):
            b.pop('quote')
    n=len(data); verified=sum(b.get('provenance')=='VERIFIED' for b in data); legacy=n-verified
    vr=verified/n if n else 0; lr=legacy/n if n else 0
    state='NOT_READY' if not n or errors else 'LIMITED' if n<cfg['bars'] or vr<.8 else 'READY'
    f=features(data) if not errors else features([])
    direction_bias=bias(f['structure']); reasons=list(errors)
    if state!='READY': reasons.append('INSUFFICIENT_DATA')
    if not direction_bias: reasons.append('UNCLEAR_STRUCTURE')
    if f['sweep']=='CONFLICT' or (bias(f['sweep']) and bias(f['sweep'])!=direction_bias): reasons.append('CONFLICTING_STRUCTURE')
    if f['delta_ratio'] is not None and f['delta_ratio']*direction_bias<-.2: reasons.append('CONFLICTING_ORDERFLOW')
    if f['range_ratio'] is not None and f['range_ratio']>3: reasons.append('UNEXPLAINED_VOLATILITY')
    # No quote data adapter: never infer spread, depth, slippage or passive orders from trades.
    quote=data[-1].get('quote') if data else None
    if quote is None:
        reasons.append('LIQUIDITY_EXECUTION_QUALITY_UNAVAILABLE')
    elif (not all(isinstance(quote.get(k),(int,float)) and math.isfinite(quote[k]) for k in ('spread_bps','slippage_bps','depth_quote'))
          or not 0<=quote['spread_bps']<=5 or not 0<=quote['slippage_bps']<=10 or quote['depth_quote']<100000
          or ts(quote['available_at'])>ts(at) or ts(quote['timestamp'])>ts(at) or ts(at)-ts(quote['timestamp'])>60):
        reasons.append('POOR_LIQUIDITY_QUALITY')
    scores=dict(structure=1.0 if direction_bias else 0,liquidity=1.0 if bias(f['sweep'])==direction_bias and direction_bias else 0,
      orderflow=max(0,(f['delta_ratio'] or 0)*direction_bias),volume=min(1,(f['volume_ratio'] or 0)/2),
      volatility=1.0 if f['range_ratio'] is not None and .5<=f['range_ratio']<=2 else 0,
      oi=0,funding=0,cross_timeframe=1.0 if bias(f['cross_timeframe'])==direction_bias and direction_bias else 0,
      data_quality=0 if errors or not n else 1,evidence_quality=vr+.5*lr)
    confidence=round(sum(WEIGHTS[k]*scores[k] for k in WEIGHTS)*min(1,n/cfg['bars'])*(vr+.5*lr),6)
    entry=invalidation=None; targets=[]; multiple=None
    if direction_bias and n>=2 and not errors:
        b=data[-1]; anchor=b['low'] if direction_bias>0 else b['high']
        target=f['range_high'] if direction_bias>0 else f['range_low']
        zone=sorted([b['open'],b['close']]); worst=zone[1] if direction_bias>0 else zone[0]
        risk=(worst-anchor)*direction_bias; reward=(target-worst)*direction_bias
        if risk>0 and reward>0:
            entry={'type':'Confirmation','zone':zone,'condition':'Reclaim and hold local structure; quote-quality confirmation required'}
            invalidation={'level':anchor,'condition':'Closed primary candle beyond setup extremum','basis':'observed setup low/high'}
            targets=[{'level':target,'basis':'prior 20-bar liquidity extremum'}]; multiple=round(reward/risk,6)
        if multiple is None or multiple<2: reasons.append('INSUFFICIENT_R_MULTIPLE')
    if invalidation is None: reasons.append('INVALIDATION_UNAVAILABLE')
    if not targets: reasons.append('TARGET_UNAVAILABLE')
    result=dict(market=market,symbol=symbol,timestamp=at,horizon=horizon,direction='NO_TRADE' if reasons else 'LONG' if direction_bias>0 else 'SHORT',
      confidence=confidence,confidence_semantics='weighted evidence score, not win probability',confidence_components={k:dict(score=scores[k],weight=WEIGHTS[k]) for k in WEIGHTS},
      confidence_coverage_multiplier=min(1,n/cfg['bars']),confidence_evidence_multiplier=vr+.5*lr,
      data_state=state,setup_type='SWEEP_RECLAIM' if bias(f['sweep']) else 'STRUCTURE_CONFIRMATION',
      market_structure=f['structure'],liquidity_context={'sweep':f['sweep'],'spread':'UNAVAILABLE','slippage':'UNAVAILABLE','depth':'UNAVAILABLE'},
      orderflow_context={'delta_ratio':f['delta_ratio'],'passive_absorption':f['absorption']},volume_context=f['volume_ratio'],volatility_context=f['volatility'],
      oi_context='UNAVAILABLE',funding_context='NOT_APPLICABLE_SPOT' if market=='SPOT' else 'UNAVAILABLE',
      entry_zone=entry,invalidation=invalidation,targets=targets,expected_duration=cfg['duration'],expected_r_multiple=multiple,
      supporting_evidence=[{'feature':k,'score':v,'weight':WEIGHTS[k]} for k,v in scores.items() if v>0],contradicting_evidence=sorted(set(reasons)),
      data_quality='FAIL' if errors else 'PASS' if n else 'UNAVAILABLE',evidence_quality='WARN' if legacy else 'PASS' if n else 'UNAVAILABLE',
      verified_data_used=bool(verified),legacy_data_used=bool(legacy),verified_data_ratio=vr,legacy_data_ratio=lr,
      verified_coverage=verified/cfg['bars'],legacy_coverage=legacy/cfg['bars'],coverage={'bars':n,'required':cfg['bars'],'seconds':cfg['seconds']},
      strategy_version=VERSION,feature_version=VERSION,features=f,market_regime=f['regime'],
      input_hash=digest(data),config_hash=digest({'config':CONFIG,'weights':WEIGHTS,'registry':REGISTRY}),
      intelligence_mode='RESEARCH',trading_actions=0,execution='DISABLED',live_trading='DISABLED')
    result['result_hash']=digest(result)
    return result


def resolve(results):
    by={r['horizon']:r for r in results}
    if set(by)!=set(CONFIG): raise ValueError('exactly three horizons required')
    directions={r['direction'] for r in results}-{ 'NO_TRADE'}
    biases={bias(r['market_structure']) for r in results}-{0}
    dominant=next((h for h in ('LONG','MID','SHORT') if by[h]['data_state']=='READY'),None)
    out=dict(alignment='CONFLICT' if len(directions)>1 else 'ALIGNED' if len(directions)==1 and all(r['direction']!='NO_TRADE' for r in results) else 'INSUFFICIENT_DATA',
      conflict=len(biases)>1,dominant_context=dominant,countertrend_warning=len(biases)>1,
      data_conflict=len({r['data_quality'] for r in results})>1,
      horizons={h:dict(direction=r['direction'],data_state=r['data_state'],result_hash=r['result_hash']) for h,r in by.items()},decision='RESEARCH_LONG_BIAS' if directions=={'LONG'} and len(biases)<=1 else 'RESEARCH_SHORT_BIAS' if directions=={'SHORT'} and len(biases)<=1 else 'NO_TRADE')
    out['result_hash']=digest(out); return out
