"""Observer-only storage: event aggregation and read cursor commit together."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import fcntl
from pathlib import Path
import sqlite3

from src.bugfixer.model import SCHEMA_VERSION, State, validate_transition
from src.bugfixer.processing import FINGERPRINT_VERSION, Event, classify, fingerprint, redact_text
from src.bugfixer.task_store import TASK_SCHEMA, TaskStoreMixin
from src.bugfixer.tasks import Task, TaskState, validate_fix_evidence

APP_ID = 0x54494D42


class IncidentStore(TaskStoreMixin):
    def __init__(self, path: Path, *, code_version='UNKNOWN'):
        Task(git_sha=code_version)  # Reject invalid versions before opening storage.
        self.code_version = code_version
        path = Path(path)
        if path.is_symlink():
            raise ValueError('store symlinks are forbidden')
        if path.exists() and path.stat().st_size:
            # Inspect read-only before accepting an existing file as our store.
            probe = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                if probe.execute('PRAGMA application_id').fetchone()[0] != APP_ID:
                    raise ValueError('not a bugfixer database')
                if probe.execute('PRAGMA user_version').fetchone()[0] not in {1, SCHEMA_VERSION}:
                    raise ValueError('unsupported bugfixer schema')
            finally:
                probe.close()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path.resolve()
        self.worker_lock_path = self.path.with_name(self.path.name + '.worker.lock')
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript(f'''
            BEGIN IMMEDIATE;
            PRAGMA application_id={APP_ID};
            PRAGMA user_version={SCHEMA_VERSION};
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY, fingerprint_version INTEGER NOT NULL,
                category TEXT NOT NULL, confidence REAL NOT NULL, matched_rule TEXT NOT NULL,
                reason TEXT NOT NULL, state TEXT NOT NULL,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL, suppressed_count INTEGER NOT NULL,
                evidence TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS history (
                sequence INTEGER PRIMARY KEY, incident_id TEXT NOT NULL,
                from_state TEXT NOT NULL, to_state TEXT NOT NULL,
                evidence TEXT NOT NULL, timestamp TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evidence_bundles (
                sha256 TEXT PRIMARY KEY, incident_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoints (
                source TEXT PRIMARY KEY, payload TEXT NOT NULL);
            {TASK_SCHEMA}
        ''')
        try:
            self._initialize_task_links()
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            self.db.close()
            raise
        path.chmod(0o600)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def _require_transaction(self):
        if not self.db.in_transaction:
            raise RuntimeError('mutation requires transaction')

    def record(self, event: Event) -> str:
        self._require_transaction()
        identity = fingerprint(event)
        existing = self.db.execute('SELECT state FROM incidents WHERE id=?', (identity,)).fetchone()
        if existing:
            self.db.execute('''UPDATE incidents SET occurrence_count=occurrence_count+1,
                suppressed_count=suppressed_count+1, first_seen=min(first_seen,?),
                last_seen=max(last_seen,?) WHERE id=?''', (event.timestamp, event.timestamp, identity))
            if existing['state'] == State.RESOLVED:
                self.transition(identity, State.INVESTIGATING, 'Recurrence after resolution', event.timestamp)
                self._ensure_incident_task(self.inspect(identity), recurrence=True)
            return identity
        result = classify(event)
        self.db.execute('INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        (identity, FINGERPRINT_VERSION, result.category, result.confidence, result.matched_rule,
                         result.reason, State.NEW, event.timestamp, event.timestamp, 1, 0,
                         json.dumps(event.safe_dict(), sort_keys=True)))
        self.transition(identity, State.NORMALIZED, 'Sanitized canonical event v1', event.timestamp)
        self.transition(identity, State.CLASSIFIED, result.reason, event.timestamp)
        if result.category == 'UNKNOWN':
            self.transition(identity, State.SAFE_STOP, 'Unknown error: preserve evidence and escalate; no auto-fix', event.timestamp)
        elif result.category in {'INVARIANT_VIOLATION', 'TERMINAL_BLOCKED'}:
            self.transition(identity, State.SAFE_STOP, 'Critical integrity event; no auto-fix', event.timestamp)
        self._ensure_incident_task(self.inspect(identity))
        return identity

    def transition(self, identity: str, target: str, evidence: str, at: str | None = None):
        self._require_transaction()
        row = self.inspect(identity)
        target = validate_transition(row['state'], target, evidence)
        if target == State.RESOLVED:
            task = self.task_for_incident(identity)
            if task.state != TaskState.FIXED:
                raise ValueError('incident resolution requires a verified FIXED repair task')
            validate_fix_evidence(task, task.completion_evidence)
        self.db.execute('UPDATE incidents SET state=? WHERE id=?', (target, identity))
        self.db.execute('INSERT INTO history (incident_id,from_state,to_state,evidence,timestamp) VALUES (?,?,?,?,?)',
                        (identity, row['state'], target, redact_text(evidence),
                         at or datetime.now(timezone.utc).isoformat()))

    def inspect(self, identity: str) -> dict:
        row = self.db.execute('SELECT * FROM incidents WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('unknown incident')
        result = dict(row)
        event = json.loads(result['evidence'])
        metadata = self.db.execute('SELECT * FROM incident_repair WHERE incident_id=?', (identity,)).fetchone()
        result.update(component=event['component'], exception_class=event['exception'],
                      normalized_message=event['message'], suppressed_duplicate_count=result['suppressed_count'],
                      evidence_references=[r[0] for r in self.db.execute(
                          'SELECT sha256 FROM evidence_bundles WHERE incident_id=? ORDER BY sha256', (identity,))])
        if metadata:
            result.update(dict(metadata))
        return result

    def list(self, limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 1000:
            raise ValueError('limit must be 1..1000')
        return [dict(row) for row in self.db.execute('SELECT * FROM incidents ORDER BY first_seen,id LIMIT ?', (limit,))]

    def checkpoint(self, source: str) -> dict | None:
        row = self.db.execute('SELECT payload FROM checkpoints WHERE source=?', (source,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_checkpoint(self, source: str, payload: dict):
        self._require_transaction()
        self.db.execute('INSERT INTO checkpoints VALUES (?,?) ON CONFLICT(source) DO UPDATE SET payload=excluded.payload',
                        (source, json.dumps(payload, sort_keys=True)))

    def worker_running(self):
        try:
            descriptor = os.open(self.worker_lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return False
        except OSError:
            return None
        with os.fdopen(descriptor, 'r') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False

    def status(self, *, now=None) -> dict:
        row = self.db.execute('''SELECT count(*) incidents_created,
            coalesce(sum(occurrence_count),0) events_ingested,
            coalesce(sum(suppressed_count),0) occurrences_deduplicated,
            coalesce(sum(category='UNKNOWN'),0) unknown_incidents,
            coalesce(sum(state!='RESOLVED'),0) active_incidents,
            coalesce(sum(state='SAFE_STOP'),0) critical_incidents FROM incidents''').fetchone()
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('status time must be timezone-aware')
        checkpoints = [json.loads(item[0]) for item in self.db.execute('SELECT payload FROM checkpoints')]
        ages = [(now - datetime.fromisoformat(item['timestamp'])).total_seconds() for item in checkpoints]
        lags = [item['ingestion_lag_seconds'] for item in checkpoints if item.get('ingestion_lag_seconds') is not None]
        return {'schema_version': SCHEMA_VERSION, 'mode': 'OBSERVE', 'auto_remediate': False,
                'origin': 'tim_bugfixer', **dict(row), 'worker_running': self.worker_running(),
                'events_normalized': row['events_ingested'],
                'records_read_total': sum(item.get('records_read_total', 0) for item in checkpoints),
                'records_ignored_total': sum(item.get('records_ignored_total', 0) for item in checkpoints),
                'pending_tracebacks': sum(bool(item.get('pending_trace')) for item in checkpoints),
                'checkpoint_age_seconds': max(ages) if ages else None,
                'ingestion_lag_seconds': max(lags) if lags else None,
                'future_timestamp_observed': any(value < 0 for value in ages + lags)}
