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

        A CLAIMED row can be taken over by the same claimant (resume after a
        crash) or by anyone once the lease has expired. MAPPED and BLOCKED rows
        are never claimable.
        """
        now = self.clock()
        cur = self.db.execute(
            'INSERT OR IGNORE INTO task_mappings(fingerprint,canonical_key,state,claimant,claimed_at,created_at,updated_at) '
            'VALUES(?,?,?,?,?,?,?)', (fingerprint, canonical_key, MappingState.CLAIMED, claimant, now, now, now))
        won = cur.rowcount == 1
        if not won:
            cur = self.db.execute(
                'UPDATE task_mappings SET claimant=?, claimed_at=?, updated_at=? WHERE fingerprint=? AND state=? '
                'AND (claimant=? OR claimed_at<?)',
                (claimant, now, now, fingerprint, MappingState.CLAIMED, claimant, now - lease_seconds))
            won = cur.rowcount == 1
        return won, self.get(fingerprint)

    def map_issue(self, fingerprint: str, repository: str, issue_number: int, duplicates=()) -> Mapping:
        self.db.execute(
            'UPDATE task_mappings SET state=?, github_repository=?, github_issue_number=?, duplicate_issues=?, '
            'block_reason=\'\', updated_at=? WHERE fingerprint=? AND state IN (?,?)',
            (MappingState.MAPPED, repository, issue_number, json.dumps(sorted(set(duplicates))), self.clock(),
             fingerprint, MappingState.CLAIMED, MappingState.MAPPED))
        return self.get(fingerprint)

    def block(self, fingerprint: str, reason: str, detail: str = '') -> Mapping:
        """Fail closed: record the incident, keep any existing mapping, never delete or close anything."""
        now = self.clock()
        self.db.execute('UPDATE task_mappings SET state=?, block_reason=?, updated_at=? WHERE fingerprint=?',
                        (MappingState.BLOCKED, reason, now, fingerprint))
        self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                        (fingerprint, reason, detail, now))
        return self.get(fingerprint)

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
                       row['claimed_at'], row['github_repository'], row['github_issue_number'],
                       tuple(json.loads(row['duplicate_issues'])), row['block_reason'])
