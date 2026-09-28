"""Offline continuity gate for a future bounded single-socket campaign.

Attestations must be produced by the transport; this gate does not prove their
truth and must never turn unrelated historical sessions into verified coverage.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class CampaignLimits:
    max_seconds: float
    max_events: int

    def __post_init__(self):
        if (isinstance(self.max_seconds, bool) or not isinstance(self.max_seconds, (int, float))
                or not math.isfinite(self.max_seconds) or not 0 < self.max_seconds <= 10800
                or type(self.max_events) is not int or not 1 <= self.max_events <= 10_000_000):
            raise ValueError('invalid campaign limits')


def verify_segments(segments, limits: CampaignLimits):
    """Validate ordered receipt ranges; empty/partial/untrusted chains fail closed."""
    if not segments or len(segments) > 10000:
        raise ValueError('missing or excessive segments')
    total = 0
    prior = None
    connection = segments[0]['connection_id']
    if not isinstance(connection, str) or not connection:
        raise ValueError('missing connection identity')
    for index, row in enumerate(segments):
        if row['index'] != index or row['connection_id'] != connection or row['verified'] is not True:
            raise ValueError('unverified or disconnected segment')
        for key in ('first_receipt', 'last_receipt', 'first_trade', 'last_trade', 'events'):
            if type(row[key]) is not int or row[key] < (0 if key in ('first_trade','last_trade') else 1):
                raise ValueError('invalid integer range')
        n = row['events']
        if not 1 <= n <= 10000 or row['last_receipt']-row['first_receipt']+1 != n or row['last_trade']-row['first_trade']+1 != n:
            raise ValueError('gap or inconsistent count')
        start, end = row['start_elapsed'], row['end_elapsed']
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (start,end)) or not 0 <= start <= end <= limits.max_seconds or end-start > 300:
            raise ValueError('duration outside contract')
        if prior is None:
            if row['first_receipt'] != 1 or start != 0:
                raise ValueError('missing campaign prefix')
        elif (row['first_receipt'] != prior['last_receipt']+1 or row['first_trade'] != prior['last_trade']+1 or start != prior['end_elapsed']):
            raise ValueError('cross-segment discontinuity')
        total += n
        if total > limits.max_events:
            raise ValueError('campaign event limit exceeded')
        prior = row
    return {'status':'VALIDATED_ATTESTATIONS_ONLY','events':total,'segments':len(segments),
            'elapsed_seconds':prior['end_elapsed'],'live_trading':False}


def inspect_closed_journal(path):
    """Derive bounded evidence in one read snapshot; no continuity attestation."""
    import hashlib
    import json
    import sqlite3
    from pathlib import Path
    from .verified import VerifiedJournal

    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('unsafe or oversized journal')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN')
        n = db.execute('SELECT count(*) FROM receipts').fetchone()[0]
        if not 1 <= n <= 10000:
            raise ValueError('journal outside segment budget')
        journal = object.__new__(VerifiedJournal)
        journal.db = db
        journal.contract = journal.get('contract')
        if journal.get('state') != 'CLOSED' or journal.get('gaps'):
            raise ValueError('journal not cleanly closed')
        proof = journal.verify()
        if any(proof[k] != 'PASS' for k in ('COUNTS_ACCOUNTED','ALL_UNIQUE_EVENTS_PROCESSED','DETERMINISM')):
            raise ValueError('journal verification failed')
        from datetime import datetime
        for receipt in db.execute('SELECT received_at,source_timestamp FROM receipts'):
            if receipt['source_timestamp'] is None or (datetime.fromisoformat(receipt['received_at'])-datetime.fromisoformat(receipt['source_timestamp'])).total_seconds()>30:
                raise ValueError('source lag exceeds campaign budget')
        rows = db.execute('SELECT seq,event_id,disposition FROM receipts ORDER BY seq').fetchall()
        # Conservative initial contract: duplicate/rejected receipts need explicit
        # transport accounting before supporting them across segment boundaries.
        if any(r['disposition'] != 'ACCEPTED' for r in rows):
            raise ValueError('non-unique receipt requires explicit campaign accounting')
        ids = [r['event_id'] for r in rows]
        if ids != list(range(ids[0], ids[0]+n)):
            raise ValueError('trade sequence gap')
        material = {}
        for table, order in [('control','key'),('receipts','seq'),('events','receipt_seq'),('candles','timeframe,open_time')]:
            material[table] = [dict(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY {order}')]
        digest = hashlib.sha256(json.dumps(material,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return {'journal_content_sha256':digest,'collection_id':journal.contract['collection_id'],
                'events':n,'first_trade':ids[0],'last_trade':ids[-1],
                'receipt_count':n,'continuity_proven':False}
    finally:
        db.close()
