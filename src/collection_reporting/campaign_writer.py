"""Exclusive campaign directory and durable receipt-to-segment mapping.

No network startup. Interrupted OPEN manifests are evidence, never resumed as a
continuous connection. Segment publication follows durable journal completion.
"""
import json
import sqlite3
from pathlib import Path

from .campaign import inspect_closed_journal
from .verified import SOURCE, VerifiedJournal, utc


class CampaignWriter:
    def __init__(self, directory, *, segment_events=10000):
        if type(segment_events) is not int or not 1 <= segment_events <= 10000:
            raise ValueError('invalid segment budget')
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.db = sqlite3.connect(self.directory/'manifest.sqlite3')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript("CREATE TABLE state(value TEXT); INSERT INTO state VALUES('OPEN'); CREATE TABLE segments(idx INTEGER PRIMARY KEY,first_receipt INTEGER,last_receipt INTEGER,evidence TEXT); CREATE TABLE mapping(receipt INTEGER PRIMARY KEY,segment INTEGER,local_seq INTEGER,elapsed REAL);")
        self.segment_events = segment_events
        self.index = self.local_count = self.total = 0
        self.journal = None
        self._open()

    def _open(self):
        self.journal = VerifiedJournal(self.directory/f'segment-{self.index:05d}.sqlite3',
            dict(collection_id=f'segment-{self.index:05d}',symbol='BTCUSDT',source=SOURCE,
                 max_events=self.segment_events,max_duration_seconds=300,live_trading=False,trading_actions=0))
        self.journal.begin()

    def _require_open(self):
        if self.db.execute('SELECT value FROM state').fetchone()[0] != 'OPEN':
            raise ValueError('campaign is not open')

    async def record(self, raw, receipt, elapsed):
        self._require_open()
        if receipt != self.total+1:
            raise ValueError('receipt sequence mismatch')
        # Journal commit precedes campaign mapping; interruption leaves OPEN,
        # never a falsely accepted complete manifest.
        seq = self.journal.receive(raw, utc())
        disposition = self.journal.classify(seq)
        self.journal.drain()
        with self.db:
            self.db.execute('INSERT INTO mapping VALUES(?,?,?,?)',(receipt,self.index,seq,elapsed))
        self.total += 1
        self.local_count += 1
        row = self.journal.db.execute('SELECT received_at,source_timestamp FROM receipts WHERE seq=?',(seq,)).fetchone()
        from datetime import datetime
        if row['source_timestamp'] is not None and (datetime.fromisoformat(row['received_at'])-datetime.fromisoformat(row['source_timestamp'])).total_seconds()>30:
            self.journal.stop('SOURCE_LAG_EXCEEDED',safe=True)
            self.fail()
            return False
        return disposition == 'ACCEPTED' and self.journal.get('state') != 'SAFE_STOP'

    def _seal(self):
        self.journal.stop('MAX_EVENTS' if self.local_count == self.segment_events else 'DURATION')
        if not self.journal.finish(self.local_count):
            raise ValueError('segment failed acceptance')
        path = self.journal.path
        self.journal.close()
        self.journal = None
        evidence = inspect_closed_journal(path)
        with self.db:
            self.db.execute('INSERT INTO segments VALUES(?,?,?,?)',
                (self.index,self.total-self.local_count+1,self.total,json.dumps(evidence,sort_keys=True)))

    async def rotate(self, total, elapsed):
        self._require_open()
        if total != self.total:
            raise ValueError('rotation count mismatch')
        self._seal()
        self.index += 1
        self.local_count = 0
        self._open()

    def fail(self):
        with self.db:
            self.db.execute("UPDATE state SET value='SAFE_STOP'")

    def finalize(self, result, limits):
        """Seal journal evidence only; no live coverage/readiness certification."""
        self._require_open()
        try:
            if (result.get('status') != 'BOUNDED_STOP' or result.get('received') != self.total
                    or result.get('reconnections') != 0 or result.get('live_trading') is not False
                    or result.get('reason') not in {'MAX_EVENTS','DURATION'}):
                raise ValueError('transport did not close cleanly')
            if not 0 < self.total <= limits.max_events:
                raise ValueError('invalid total')
            if result['reason']=='MAX_EVENTS' and self.total != limits.max_events:
                raise ValueError('premature event boundary')
            if self.local_count:
                self._seal()
            mappings=self.db.execute('SELECT receipt,segment,local_seq,elapsed FROM mapping ORDER BY receipt').fetchall()
            if [r[0] for r in mappings] != list(range(1,self.total+1)):
                raise ValueError('receipt mapping gap')
            import math
            times=[r[3] for r in mappings]
            if any(not math.isfinite(t) or t<0 or t>limits.max_seconds for t in times) or times != sorted(times):
                raise ValueError('invalid receipt times')
            previous=None
            next_receipt=1
            for expected_idx,(idx,first,last,serialized) in enumerate(self.db.execute('SELECT * FROM segments ORDER BY idx')):
                if idx != expected_idx or first != next_receipt:
                    raise ValueError('segment chain gap')
                evidence=inspect_closed_journal(self.directory/f'segment-{idx:05d}.sqlite3')
                if evidence != json.loads(serialized):
                    raise ValueError('segment changed after sealing')
                group=[r for r in mappings if r[1]==idx]
                if (len(group)!=evidence['events'] or [r[2] for r in group]!=list(range(1,len(group)+1))
                        or len(group)!=last-first+1 or group[0][0]!=first or group[-1][0]!=last):
                    raise ValueError('segment mapping mismatch')
                # This observed span is a necessary bound, not a complete
                # attestation of segment start/end or transport continuity.
                if group[-1][3]-group[0][3] > 300:
                    raise ValueError('segment receipt span outside contract')
                if previous is not None and evidence['first_trade'] != previous+1:
                    raise ValueError('cross-segment trade gap')
                previous=evidence['last_trade']
                next_receipt=last+1
            if next_receipt != self.total+1:
                raise ValueError('segment coverage gap')
            with self.db:
                self.db.execute("UPDATE state SET value='SEALED_EVIDENCE_ONLY'")
            return {'status':'SEALED_EVIDENCE_ONLY','events':self.total,'continuity_proven':False}
        except BaseException:
            self.fail()
            raise

    def close(self):
        # Closing alone never accepts the campaign; completion needs independent
        # cross-segment/time/transport validation, not yet implemented.
        if self.journal is not None:
            self.journal.close()
            self.journal = None
        self.db.close()
