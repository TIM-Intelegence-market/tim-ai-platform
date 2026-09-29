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


class TaskRegistry:
    def __init__(self, path: str, *, clock=time.time):
        self.path = path
        self.clock = clock
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=30000')
        self.db.executescript(SCHEMA)

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
        are never claimable.
        """
        now = self.clock()
        cur = self.db.execute(
            'INSERT OR IGNORE INTO task_mappings(fingerprint,canonical_key,state,claimant,claimed_at,claim_token,created_at,updated_at) '
            'VALUES(?,?,?,?,?,1,?,?)', (fingerprint, canonical_key, MappingState.CLAIMED, claimant, now, now, now))
        won = cur.rowcount == 1
        if not won:
            cur = self.db.execute(
                'UPDATE task_mappings SET claimant=?, claimed_at=?, claim_token=claim_token+1, updated_at=? '
                'WHERE fingerprint=? AND state=? AND claimed_at<? RETURNING claim_token',
                (claimant, now, now, fingerprint, MappingState.CLAIMED, now - lease_seconds))
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
        self.db.execute('DELETE FROM task_mappings WHERE fingerprint=? AND state=? AND claim_token=?',
                        (fingerprint, MappingState.CLAIMED, token))

    def map_issue(self, fingerprint: str, token: int, repository: str, issue_number: int, duplicates=()) -> Mapping | None:
        """Persist the authoritative issue. None means the claim was lost and nothing was written."""
        cur = self.db.execute(
            'UPDATE task_mappings SET state=?, github_repository=?, github_issue_number=?, duplicate_issues=?, '
            'block_reason=\'\', updated_at=? WHERE fingerprint=? AND state=? AND claim_token=?',
            (MappingState.MAPPED, repository, issue_number, json.dumps(sorted(set(duplicates))), self.clock(),
             fingerprint, MappingState.CLAIMED, token))
        return self.get(fingerprint) if cur.rowcount == 1 else None

    def block(self, fingerprint: str, reason: str, detail: str = '') -> Mapping:
        """Fail closed: record the incident, keep any existing mapping, never delete or close anything."""
        now = self.clock()
        self.db.execute('UPDATE task_mappings SET state=?, block_reason=?, updated_at=? WHERE fingerprint=?',
                        (MappingState.BLOCKED, reason, now, fingerprint))
        self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                        (fingerprint, reason, detail, now))
        return self.get(fingerprint)

    def unblock(self, fingerprint: str, note: str) -> None:
        """Explicit operator/hint-driven release of a BLOCKED task. History stays in governance_incidents."""
        row = self.get(fingerprint)
        if row is None or row.state is not MappingState.BLOCKED:
            return
        if row.github_issue_number is not None:
            self.db.execute('UPDATE task_mappings SET state=?, block_reason=\'\', updated_at=? WHERE fingerprint=?',
                            (MappingState.MAPPED, self.clock(), fingerprint))
        else:
            self.db.execute('DELETE FROM task_mappings WHERE fingerprint=?', (fingerprint,))
        self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                        (fingerprint, 'UNBLOCKED', note, self.clock()))

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
                       tuple(json.loads(row['duplicate_issues'])), row['block_reason'])
