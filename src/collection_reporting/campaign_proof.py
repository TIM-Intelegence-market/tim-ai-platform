"""Independent read-only campaign integrity audit, not live coverage proof."""
import json
import math
import sqlite3
from pathlib import Path
from .campaign import CampaignLimits, inspect_closed_journal


def inspect_campaign(directory):
    root=Path(directory)
    path=root/'manifest.sqlite3'
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():
        raise ValueError('unsafe campaign path')
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('BEGIN')
        if db.execute('SELECT value FROM state').fetchall()!=[('SEALED_EVIDENCE_ONLY',)]:
            raise ValueError('campaign not sealed')
        transport=dict(db.execute('SELECT key,value FROM transport'))
        session,result=json.loads(transport['session']),json.loads(transport['result'])
        limits=CampaignLimits(session['max_seconds'],session['max_events'])
        if (result['status']!='BOUNDED_STOP' or result['connection_id']!=session['connection_id']
                or not session['connection_id'] or result['reconnections']!=0 or result['live_trading'] is not False):
            raise ValueError('invalid transport record')
        reason=result.get('reason')
        elapsed=result.get('elapsed_seconds')
        if (reason not in {'MAX_EVENTS','DURATION'} or type(elapsed) not in (int,float)
                or not math.isfinite(elapsed) or elapsed<0):
            raise ValueError('invalid stop evidence')
        if reason=='DURATION' and elapsed<limits.max_seconds:
            raise ValueError('premature duration stop')
        if reason=='MAX_EVENTS' and result['received']!=limits.max_events:
            raise ValueError('premature event stop')
        n=db.execute('SELECT count(*) FROM mapping').fetchone()[0]
        if not 0<n<=limits.max_events or result['received']!=n:
            raise ValueError('receipt count mismatch')
        rows=db.execute('SELECT receipt,segment,local_seq,elapsed FROM mapping ORDER BY receipt').fetchall()
        if [r[0] for r in rows]!=list(range(1,n+1)):
            raise ValueError('receipt sequence gap')
        times=[r[3] for r in rows]
        if any(not math.isfinite(t) or not 0<=t<=min(limits.max_seconds,elapsed) for t in times) or times!=sorted(times):
            raise ValueError('invalid elapsed sequence')
        next_receipt=1;previous_trade=None;count=0
        for expected,(idx,first,last,payload) in enumerate(db.execute('SELECT * FROM segments ORDER BY idx')):
            if idx!=expected or first!=next_receipt:raise ValueError('segment sequence gap')
            proof=inspect_closed_journal(root/f'segment-{idx:05d}.sqlite3')
            if proof!=json.loads(payload):raise ValueError('journal content mismatch')
            group=[r for r in rows if r[1]==idx]
            if (not group or len(group)!=proof['events'] or len(group)!=last-first+1
                    or [r[2] for r in group]!=list(range(1,len(group)+1))
                    or group[0][0]!=first or group[-1][0]!=last or group[-1][3]-group[0][3]>300):
                raise ValueError('segment mapping mismatch')
            if previous_trade is not None and proof['first_trade']!=previous_trade+1:raise ValueError('trade gap')
            previous_trade=proof['last_trade'];next_receipt=last+1;count+=1
        if next_receipt!=n+1:raise ValueError('missing segment coverage')
        return {'integrity':'PASS','events':n,'segments':count,'coverage_ready':False,'transport_continuity_independently_proven':False}
    finally:db.close()
