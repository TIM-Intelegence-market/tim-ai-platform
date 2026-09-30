"""Durable canonical-key -> GitHub-issue mapping with a create-once claim.

Uniqueness is enforced by the database (PRIMARY KEY on the fingerprint, UNIQUE
on the canonical key), not by an in-memory lock, so concurrent threads and
processes cannot both win the claim.
"""
from dataclasses import dataclass
from enum import Enum
import json
import sqlite3
import time

SCHEMA_VERSION = 2

SCHEMA = '''
CREATE TABLE IF NOT EXISTS task_mappings (
    fingerprint TEXT PRIMARY KEY,
    canonical_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    claimant TEXT,
    claimed_at REAL,
    claim_token INTEGER NOT NULL DEFAULT 0,
    github_repository TEXT,
    github_issue_number INTEGER,
    duplicate_issues TEXT NOT NULL DEFAULT '[]',
    block_reason TEXT NOT NULL DEFAULT '',
    block_candidates TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS governance_incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
    reason TEXT NOT NULL, detail TEXT NOT NULL, created_at REAL NOT NULL);
'''


class MappingState(str, Enum):
    CLAIMED = 'CLAIMED'    # a worker holds the create-once claim, no issue mapped yet
    MAPPED = 'MAPPED'      # authoritative issue persisted
    BLOCKED = 'BLOCKED'    # ambiguous or violated uniqueness, needs a human
    RELEASED = 'RELEASED'  # claim given up or block lifted; row and token counter are kept (tokens never restart)


@dataclass(frozen=True)
class Mapping:
    fingerprint: str
    canonical_key: str
    state: MappingState
    claimant: str | None
    claimed_at: float | None
    claim_token: int
    github_repository: str | None
    github_issue_number: int | None
    duplicate_issues: tuple[int, ...]
    block_reason: str
    block_candidates: tuple[int, ...]


class TaskRegistry:
    def __init__(self, path: str, *, clock=time.time):
        self.path = path
        self.clock = clock
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA busy_timeout=30000')
        self._init()

    def _init(self) -> None:
        """Switching to WAL and running DDL ignore busy_timeout when several processes open a fresh
        or old file at once, so retry on lock errors instead of failing the worker at startup."""
        deadline = time.monotonic() + 30
        while True:
            try:
                self.db.execute('PRAGMA journal_mode=WAL')
                self.db.executescript(SCHEMA)
                self._migrate()
                return
            except sqlite3.OperationalError as exc:
                if 'locked' not in str(exc) and 'busy' not in str(exc) or time.monotonic() > deadline:
                    raise
                time.sleep(0.02)

    def _migrate(self) -> None:
        """Bring a registry file written by an earlier release up to the current columns."""
        have = {r['name'] for r in self.db.execute('PRAGMA table_info(task_mappings)')}
        for name, ddl in (('claim_token', 'INTEGER NOT NULL DEFAULT 0'), ('block_candidates', "TEXT NOT NULL DEFAULT '[]'")):
            if name not in have:
                try:
                    self.db.execute(f'ALTER TABLE task_mappings ADD COLUMN {name} {ddl}')
                except sqlite3.OperationalError as exc:
                    if 'duplicate column' not in str(exc):       # another process migrated first
                        raise
        self.db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    def close(self):
        self.db.close()

    def get(self, fingerprint: str) -> Mapping | None:
        row = self.db.execute('SELECT * FROM task_mappings WHERE fingerprint=?', (fingerprint,)).fetchone()
        return self._mapping(row) if row else None

    def claim(self, fingerprint: str, canonical_key: str, claimant: str, lease_seconds: float) -> tuple[bool, Mapping]:
        """Atomically claim creation. True only for the single winner.

        Every successful claim gets a new `claim_token` (fencing token). A CLAIMED
        row can only be taken over after its lease expired, never by name: two
        workers sharing a claimant name must not both win. MAPPED and BLOCKED rows
        are never claimable. Rows are never deleted, so a fencing token is never reused.
        """
        now = self.clock()
        cur = self.db.execute(
            'INSERT OR IGNORE INTO task_mappings(fingerprint,canonical_key,state,claimant,claimed_at,claim_token,created_at,updated_at) '
            'VALUES(?,?,?,?,?,1,?,?)', (fingerprint, canonical_key, MappingState.CLAIMED, claimant, now, now, now))
        won = cur.rowcount == 1
        if not won:
            cur = self.db.execute(
                'UPDATE task_mappings SET state=\'CLAIMED\', claimant=?, claimed_at=?, claim_token=claim_token+1, updated_at=? '
                'WHERE fingerprint=? AND ((state=? AND claimed_at<?) OR state=?) RETURNING claim_token',
                (claimant, now, now, fingerprint, MappingState.CLAIMED, now - lease_seconds, MappingState.RELEASED))
            won = cur.fetchone() is not None
        return won, self.get(fingerprint)

    def renew(self, fingerprint: str, token: int) -> bool:
        """Extend the lease if this claim was not taken over. Call right before the irreversible create."""
        cur = self.db.execute(
            'UPDATE task_mappings SET claimed_at=?, updated_at=? WHERE fingerprint=? AND state=? AND claim_token=?',
            (self.clock(), self.clock(), fingerprint, MappingState.CLAIMED, token))
        return cur.rowcount == 1

    def release(self, fingerprint: str, token: int) -> None:
        """Give the claim up after a failure that happened before anything was created."""
        self.db.execute('UPDATE task_mappings SET state=?, updated_at=? WHERE fingerprint=? AND state=? AND claim_token=?',
                        (MappingState.RELEASED, self.clock(), fingerprint, MappingState.CLAIMED, token))

    def map_issue(self, fingerprint: str, token: int, repository: str, issue_number: int, duplicates=()) -> Mapping | None:
        """Persist the authoritative issue. None means the claim was lost and nothing was written."""
        cur = self.db.execute(
            'UPDATE task_mappings SET state=?, github_repository=?, github_issue_number=?, duplicate_issues=?, '
            'block_reason=\'\', block_candidates=\'[]\', updated_at=? WHERE fingerprint=? AND state=? AND claim_token=?',
            (MappingState.MAPPED, repository, issue_number, json.dumps(sorted(set(duplicates))), self.clock(),
             fingerprint, MappingState.CLAIMED, token))
        return self.get(fingerprint) if cur.rowcount == 1 else None

    def block(self, fingerprint: str, reason: str, detail: str = '', *, token: int | None = None,
              candidates=()) -> Mapping:
        """Fail closed: record the incident and stop the task, never delete or close anything.

        `candidates` are the issue numbers the block is about (structured, used to judge whether a
        later hint really addresses it). With a token the state change is fenced to that claim. A
        MAPPED task is never downgraded, by anyone: a stale worker or operator call only records
        the incident.
        """
        now = self.clock()
        cands = json.dumps(sorted(set(candidates)))
        if token is None:
            self.db.execute('UPDATE task_mappings SET state=?, block_reason=?, block_candidates=?, updated_at=? '
                            'WHERE fingerprint=? AND state<>?',
                            (MappingState.BLOCKED, reason, cands, now, fingerprint, MappingState.MAPPED))
        else:
            self.db.execute('UPDATE task_mappings SET state=?, block_reason=?, block_candidates=?, updated_at=? '
                            'WHERE fingerprint=? AND state=? AND claim_token=?',
                            (MappingState.BLOCKED, reason, cands, now, fingerprint, MappingState.CLAIMED, token))
        self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                        (fingerprint, reason, detail, now))
        return self.get(fingerprint)

    def record_incident(self, fingerprint: str, reason: str, detail: str = '') -> None:
        self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                        (fingerprint, reason, detail, self.clock()))

    def add_duplicates(self, fingerprint: str, numbers) -> Mapping | None:
        """Record extra duplicate issue numbers on a MAPPED task without touching its state."""
        row = self.get(fingerprint)
        if row is None:
            return None
        merged = sorted(set(row.duplicate_issues) | set(numbers))
        self.db.execute('UPDATE task_mappings SET duplicate_issues=?, updated_at=? WHERE fingerprint=?',
                        (json.dumps(merged), self.clock(), fingerprint))
        return self.get(fingerprint)

    def unblock(self, fingerprint: str, note: str) -> bool:
        """Explicit release of a BLOCKED task (two single-statement, state-guarded updates, no TOCTOU).

        With a mapped issue the task returns to MAPPED, otherwise to RELEASED (claimable again).
        History stays in governance_incidents.
        """
        now = self.clock()
        n = self.db.execute('UPDATE task_mappings SET state=?, block_reason=\'\', block_candidates=\'[]\', updated_at=? '
                            'WHERE fingerprint=? AND state=? AND github_issue_number IS NOT NULL',
                            (MappingState.MAPPED, now, fingerprint, MappingState.BLOCKED)).rowcount
        n += self.db.execute('UPDATE task_mappings SET state=?, block_reason=\'\', block_candidates=\'[]\', updated_at=? '
                             'WHERE fingerprint=? AND state=? AND github_issue_number IS NULL',
                             (MappingState.RELEASED, now, fingerprint, MappingState.BLOCKED)).rowcount
        if n:
            self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                            (fingerprint, 'UNBLOCKED', note, now))
        return bool(n)

    def incidents(self, fingerprint: str | None = None) -> list[dict]:
        sql, args = 'SELECT * FROM governance_incidents', ()
        if fingerprint:
            sql, args = sql + ' WHERE fingerprint=?', (fingerprint,)
        return [dict(r) for r in self.db.execute(sql + ' ORDER BY id', args)]

    def count_mappings(self, canonical_key: str) -> int:
        return self.db.execute('SELECT COUNT(*) FROM task_mappings WHERE canonical_key=?', (canonical_key,)).fetchone()[0]

    @staticmethod
    def _mapping(row) -> Mapping:
        return Mapping(row['fingerprint'], row['canonical_key'], MappingState(row['state']), row['claimant'],
                       row['claimed_at'], row['claim_token'], row['github_repository'], row['github_issue_number'],
                       tuple(json.loads(row['duplicate_issues'])), row['block_reason'],
                       tuple(json.loads(row['block_candidates'])))
